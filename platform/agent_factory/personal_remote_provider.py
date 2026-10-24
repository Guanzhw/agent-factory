"""Owner-configured OpenCode serve verification.

Contract: https://opencode.ai/docs/server/ (reviewed 2026-10-08).
Identity means TLS origin + credential possession + exact project, not a human
identity. Secret backends are trusted injections and must enforce the entire
owner/reference/revision/destination tuple. No default environment secret lookup.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from typing import Callable, Protocol
from urllib.parse import urlsplit

PROVIDER_ID = "opencode-serve-v1"
CAPABILITIES = frozenset({"runtime:health", "project:read", "agent:read"})
MAX_BYTES = 262144
HTTP_TOTAL_SECONDS = 10.0


class RemoteConnectionError(ValueError):
    """Only fixed diagnostic codes may cross this boundary."""


@dataclass(frozen=True)
class SecretLease:
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self):
        if (not self.username or not self.password or ':' in self.username
                or len(self.username) > 128 or len(self.password) > 32768
                or any(ord(c) < 32 for c in self.username + self.password)):
            raise RemoteConnectionError("REMOTE_CREDENTIAL_INVALID")


def reject_credential_echo(value, lease):
    """Reject known authentication material before any remote JSON is persisted.

    This guards exact known service credentials, not arbitrary transformations or
    unrelated private file contents returned by a remote agent. Never echo the
    matched value in a diagnostic, and never retain a partially redacted result.
    """
    if lease is None:
        return
    if not isinstance(lease, SecretLease):
        raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE')
    encoded = base64.b64encode((lease.username + ':' + lease.password).encode()).decode()
    needles = (lease.password, encoded, 'Basic ' + encoded, 'Bearer ' + lease.password)
    pending, seen, count = [(value, 0)], set(), 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 100000 or depth > 32:
            raise RemoteConnectionError('REMOTE_RESPONSE_REJECTED')
        if isinstance(item, str):
            if any(secret in item for secret in needles):
                raise RemoteConnectionError('REMOTE_CREDENTIAL_ECHO_REJECTED')
        elif isinstance(item, (dict, list)):
            if id(item) in seen:
                raise RemoteConnectionError('REMOTE_RESPONSE_REJECTED')
            seen.add(id(item))
            children = [*item.keys(), *item.values()] if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in children)


class SecretProvider(Protocol):
    def authorize(self, *, owner: str, reference: str, revision: str, destination: str) -> bool:
        """Metadata-only check. Must reject another owner's reference and rotation."""
        ...

    def resolve(self, *, owner: str, reference: str, revision: str, destination: str) -> SecretLease:
        """Repeat authorization and return an ephemeral lease; never log its value."""
        ...


def hostname(value: str) -> str:
    """Normalize one DNS name or IP literal without an address policy."""
    try:
        if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            host = value.encode('idna').decode('ascii').lower()
            if len(host) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                    for label in host.rstrip('.').split('.')):
                raise ValueError()
            return host
    except (ValueError, TypeError, UnicodeError):
        raise RemoteConnectionError("REMOTE_HOST_INVALID") from None


def origin(value: str) -> str:
    try:
        if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or any(c in value for c in "@?#\\")
                or parsed.port is not None and not 1 <= parsed.port <= 65535):
            raise ValueError()
        host = hostname(parsed.hostname)
        authority = f"[{host}]" if ':' in host else host
        default = 443 if parsed.scheme == 'https' else 80
        if parsed.port is not None and parsed.port != default:
            authority += ':' + str(parsed.port)
        return parsed.scheme + "://" + authority
    except (ValueError, TypeError, AttributeError):
        raise RemoteConnectionError("REMOTE_ORIGIN_DENIED") from None


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, port=443):
        self._tls_context = ssl.create_default_context()
        super().__init__(host, port, timeout=5, context=self._tls_context)
        self._address = address
        self.deadline = time.monotonic() + HTTP_TOTAL_SECONDS

    def connect(self):
        # Connect numeric address; retain hostname for certificate validation/SNI.
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RemoteConnectionError("REMOTE_DEADLINE")
        sock = socket.create_connection((self._address, self.port), min(5.0, remaining))
        self.sock = sock  # Deadline interruption can reach the TLS handshake too.
        try:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise RemoteConnectionError("REMOTE_DEADLINE")
            sock.settimeout(min(5.0, remaining))
            self.sock = self._tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, address, port=80):
        super().__init__(host, port, timeout=5)
        self._address = address
        self.deadline = time.monotonic() + HTTP_TOTAL_SECONDS

    def connect(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RemoteConnectionError("REMOTE_DEADLINE")
        self.sock = socket.create_connection((self._address, self.port), min(5.0, remaining))


class PinnedHTTPSProbe:
    """Read-only fixed paths, no redirects/retries/proxy/netrc and bounded IO."""
    def __init__(self, *, dns_timeout_seconds: float = 3):
        if (type(dns_timeout_seconds) not in {int, float} or not math.isfinite(dns_timeout_seconds)
                or not 3 <= dns_timeout_seconds <= 10):
            raise ValueError('REMOTE_DNS_TIMEOUT_INVALID')
        self.dns_timeout_seconds = dns_timeout_seconds

    def addresses(self, destination):
        parsed = urlsplit(origin(destination))
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        assert host is not None
        try:
            # libc DNS has no portable deadline. A fixed isolated helper process
            # is killed and reaped on timeout; no unbounded resolver thread remains.
            result = subprocess.run([sys.executable, "-I", "-c",
                "import socket,json,sys; a=sorted({r[4][0] for r in socket.getaddrinfo(sys.argv[1],int(sys.argv[2]),type=socket.SOCK_STREAM)}); print(json.dumps(a if len(a)<=16 else []))",
                host, str(port)], capture_output=True, timeout=self.dns_timeout_seconds, check=True, text=True)
            addresses = json.loads(result.stdout)
            if not addresses or len(addresses) > 16:
                raise ValueError()
            return [str(ipaddress.ip_address(address)) for address in addresses]
        except (OSError, ValueError, subprocess.SubprocessError):
            raise RemoteConnectionError("REMOTE_DNS_FAILED") from None

    def get(self, destination, address, path, lease=None):
        if path not in {"/global/health", "/project/current", "/agent"}:
            raise RemoteConnectionError("REMOTE_PATH_DENIED")
        parsed = urlsplit(origin(destination))
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if lease is not None:
            headers["Authorization"] = "Basic " + base64.b64encode(
                (lease.username + ':' + lease.password).encode()).decode()
        conn = (_PinnedHTTPS(host, address, port) if parsed.scheme == 'https'
            else _PinnedHTTP(host, address, port))
        deadline = time.monotonic() + HTTP_TOTAL_SECONDS
        conn.deadline = deadline
        expired = threading.Event()
        active_socket: list[socket.socket | None] = [None]
        def interrupt():
            expired.set()
            sock = active_socket[0] or conn.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            conn.close()
        timer = threading.Timer(max(0, deadline - time.monotonic()), interrupt)
        timer.daemon = True
        timer.start()
        response = None
        try:
            conn.request("GET", path, headers=headers)
            # getresponse may detach conn.sock for Connection: close while the
            # response file retains the live descriptor. Keep shutdown authority.
            active_socket[0] = conn.sock
            response = conn.getresponse()
            if expired.is_set():
                raise RemoteConnectionError("REMOTE_DEADLINE")
            chunks, size = [], 0
            while size <= MAX_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RemoteConnectionError("REMOTE_RESPONSE_REJECTED")
                if conn.sock is not None:
                    conn.sock.settimeout(min(5, remaining))
                chunk = response.read1(min(16384, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b"".join(chunks)
            if expired.is_set() or time.monotonic() >= deadline:
                raise RemoteConnectionError("REMOTE_DEADLINE")
            if len(raw) > MAX_BYTES or response.getheader("Content-Encoding", "identity") != "identity":
                raise RemoteConnectionError("REMOTE_RESPONSE_REJECTED")
            # Error bodies are neither decoded nor surfaced.
            if response.status != 200:
                return response.status, None
            value = json.loads(raw)
            reject_credential_echo(value, lease)
            return response.status, value
        except RemoteConnectionError:
            raise
        except Exception:
            raise RemoteConnectionError("REMOTE_PROBE_FAILED") from None
        finally:
            timer.cancel()
            timer.join()
            if response is not None:
                response.close()
            conn.close()


class OpenCodeServeProvider:
    provider_id = PROVIDER_ID
    kind = "environment"
    capabilities = CAPABILITIES
    verification_error_codes = frozenset({'REMOTE_AUTH_REQUIRED', 'REMOTE_VERIFICATION_FAILED',
        'REMOTE_CREDENTIAL_UNAVAILABLE', 'REMOTE_IDENTITY_MISMATCH', 'REMOTE_DNS_FAILED', 'REMOTE_PROBE_FAILED', 'REMOTE_DEADLINE'})

    def __init__(self, secrets: SecretProvider, *, policy_revision="owner-endpoint-v2", probe=None):
        self.secrets = secrets
        self.policy_revision = policy_revision
        self.probe = probe or PinnedHTTPSProbe()

    @staticmethod
    def configure(configuration):
        if (not isinstance(configuration, dict) or not {'origin', 'projectId'} <= set(configuration)
                or set(configuration) - {'origin', 'projectId', 'credentialRef', 'credentialRevision'}):
            raise RemoteConnectionError("REMOTE_CONFIGURATION_INVALID")
        from .connections import _identifier
        try:
            reference, revision = configuration.get('credentialRef'), configuration.get('credentialRevision')
            if (reference is None) != (revision is None):
                raise ValueError()
            return {'origin': origin(configuration['origin']), 'projectId': _identifier(configuration['projectId']),
                'credentialRef': _identifier(reference) if reference is not None else None,
                'credentialRevision': _identifier(revision) if revision is not None else None}
        except ValueError:
            raise RemoteConnectionError("REMOTE_CONFIGURATION_INVALID") from None

    @staticmethod
    def _scope(owner, configuration):
        return dict(owner=owner, reference=configuration["credentialRef"],
                    revision=configuration["credentialRevision"], destination=configuration["origin"])

    def authorized(self, owner, configuration):
        if configuration.get('credentialRef') is None:
            return configuration.get('credentialRevision') is None
        try:
            return self.secrets.authorize(**self._scope(owner, configuration)) is True
        except Exception:
            return False

    def verify(self, owner, configuration):
        configuration = self.configure(configuration)
        if not self.authorized(owner, configuration):
            raise RemoteConnectionError("REMOTE_CREDENTIAL_UNAVAILABLE")
        destination = configuration["origin"]
        addresses = self.probe.addresses(destination)
        address = addresses[0]
        status, _ = self.probe.get(destination, address, '/global/health')
        if configuration['credentialRef'] is None and status == 401:
            raise RemoteConnectionError('REMOTE_AUTH_REQUIRED')
        if status not in {200, 401}:
            raise RemoteConnectionError('REMOTE_VERIFICATION_FAILED')
        lease = None
        if configuration['credentialRef'] is not None:
            try:
                lease = self.secrets.resolve(**self._scope(owner, configuration))
                if not isinstance(lease, SecretLease):
                    raise ValueError()
            except Exception:
                raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE') from None
        results = {}
        for path in ("/global/health", "/project/current", "/agent"):
            status, value = self.probe.get(destination, address, path, lease)
            if status != 200:
                raise RemoteConnectionError("REMOTE_VERIFICATION_FAILED")
            reject_credential_echo(value, lease)
            results[path] = value
        health, project, agents = (results[path] for path in ("/global/health", "/project/current", "/agent"))
        if (not isinstance(health, dict) or health.get("healthy") is not True
                or not isinstance(health.get("version"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}", health["version"])
                or not isinstance(project, dict) or project.get("id") != configuration["projectId"]
                or not isinstance(agents, list) or not agents or len(agents) > 256
                or any(not isinstance(agent, dict) or not isinstance(agent.get("name"), str)
                       or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", agent["name"]) for agent in agents)):
            raise RemoteConnectionError("REMOTE_IDENTITY_MISMATCH")
        return {"providerVersion": health["version"], "projectId": project["id"],
                "agentNames": sorted({agent["name"] for agent in agents}),
                "capabilities": sorted(self.capabilities), "identityBasis": "endpoint-basic-auth-project" if lease is not None else "endpoint-project"}

    def handle(self, owner, configuration):
        return VerifiedRemoteHandle(self, owner, dict(configuration))


@dataclass(frozen=True, repr=False)
class VerifiedRemoteHandle:
    provider: OpenCodeServeProvider
    owner: str
    configuration: dict
    recheck: Callable | None = field(default=None, repr=False)

    def guarded(self, recheck):
        return VerifiedRemoteHandle(self.provider, self.owner, self.configuration, recheck)

    def inspect_identity(self):
        """Read-only; workload execution remains behind governed Factory dispatch."""
        if self.recheck is not None:
            self.recheck(CAPABILITIES)
        evidence = self.provider.verify(self.owner, self.configuration)
        if self.recheck is not None:
            self.recheck(CAPABILITIES)
        return evidence

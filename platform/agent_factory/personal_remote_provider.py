"""Allowlisted OpenCode serve verification, never compute allocation or execution.

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
                or len(self.username) > 128 or len(self.password) > 4096
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


def origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (len(value) > 512 or parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"} or any(c in value for c in "@?#\\")
                or parsed.port not in {None, 443} or parsed.hostname.endswith('.')
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname)):
            raise ValueError()
        host = parsed.hostname.lower()
        # DNS only: public addresses are resolved and pinned immediately before IO.
        if '.' not in host or any(not label or len(label) > 63 or label.startswith('-')
                or label.endswith('-') for label in host.split('.')):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        return "https://" + host
    except (ValueError, TypeError, AttributeError):
        raise RemoteConnectionError("REMOTE_ORIGIN_DENIED") from None


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        self._tls_context = ssl.create_default_context()
        super().__init__(host, 443, timeout=5, context=self._tls_context)
        self._address = address
        self.deadline = time.monotonic() + HTTP_TOTAL_SECONDS

    def connect(self):
        # Connect numeric address; retain hostname for certificate validation/SNI.
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RemoteConnectionError("REMOTE_DEADLINE")
        sock = socket.create_connection((self._address, 443), min(5.0, remaining))
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


@dataclass(frozen=True)
class RemoteNetworkPolicy:
    """Global operator policy, never accepted through user HTTP configuration.

    Private targets require both an exact reviewed hostname and reviewed CIDR.
    Loopback/link-local/metadata/multicast/unspecified remain unconditionally denied.
    """
    private_hosts: frozenset[str] = frozenset()
    private_cidrs: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "private_hosts", frozenset(self.private_hosts))
        object.__setattr__(self, "private_cidrs", tuple(self.private_cidrs))
        for host in self.private_hosts:
            if origin("https://" + host) != "https://" + host:
                raise ValueError("REMOTE_POLICY_INVALID")
        for cidr in self.private_cidrs:
            network = ipaddress.ip_network(cidr, strict=True)
            if not network.is_private or network.is_loopback or network.is_link_local or network.is_multicast:
                raise ValueError("REMOTE_POLICY_INVALID")

    def permits(self, host, address):
        ip = ipaddress.ip_address(address)
        if (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified
                or ip.is_reserved or getattr(ip, "ipv4_mapped", None) is not None
                or getattr(ip, "sixtofour", None) is not None or getattr(ip, "teredo", None) is not None
                or (ip.version == 6 and ip in ipaddress.ip_network("64:ff9b::/96"))
                or str(ip) in {"100.100.100.200", "168.63.129.16"}):
            return False
        return ip.is_global or (host in self.private_hosts and any(
            ip in ipaddress.ip_network(cidr) for cidr in self.private_cidrs))


class PinnedHTTPSProbe:
    """Read-only fixed paths, no redirects/retries/proxy/netrc and bounded IO."""
    def __init__(self, policy=None):
        self.policy = policy or RemoteNetworkPolicy()

    def addresses(self, destination):
        host = urlsplit(origin(destination)).hostname
        assert host is not None
        try:
            # libc DNS has no portable deadline. A fixed isolated helper process
            # is killed and reaped on timeout; no unbounded resolver thread remains.
            result = subprocess.run([sys.executable, "-I", "-c",
                "import socket,json,sys; a=sorted({r[4][0] for r in socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)}); print(json.dumps(a if len(a)<=16 else []))",
                host], capture_output=True, timeout=3, check=True, text=True)
            addresses = json.loads(result.stdout)
            if not addresses or len(addresses) > 16 or any(not self.policy.permits(host, ip) for ip in addresses):
                raise ValueError()
            return addresses
        except (OSError, ValueError, subprocess.SubprocessError):
            raise RemoteConnectionError("REMOTE_ADDRESS_DENIED") from None

    def get(self, destination, address, path, lease=None):
        if path not in {"/global/health", "/project/current", "/agent"}:
            raise RemoteConnectionError("REMOTE_PATH_DENIED")
        host = urlsplit(origin(destination)).hostname
        if not self.policy.permits(host, address):
            raise RemoteConnectionError("REMOTE_ADDRESS_DENIED")
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if lease is not None:
            headers["Authorization"] = "Basic " + base64.b64encode(
                (lease.username + ':' + lease.password).encode()).decode()
        conn = _PinnedHTTPS(host, address)
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

    def __init__(self, secrets: SecretProvider, *, policy_revision="https-v1", network_policy=None, probe=None):
        from .store import digest
        policy = network_policy or RemoteNetworkPolicy()
        self.secrets = secrets
        self.policy_revision = policy_revision + ":" + digest({"hosts": sorted(policy.private_hosts), "cidrs": policy.private_cidrs})
        self.probe = probe or PinnedHTTPSProbe(policy)

    @staticmethod
    def configure(configuration):
        if not isinstance(configuration, dict) or set(configuration) != {
                "origin", "credentialRef", "credentialRevision", "projectId"}:
            raise RemoteConnectionError("REMOTE_CONFIGURATION_INVALID")
        from .connections import _identifier
        try:
            return {"origin": origin(configuration["origin"]), **{key: _identifier(configuration[key])
                for key in ("credentialRef", "credentialRevision", "projectId")}}
        except ValueError:
            raise RemoteConnectionError("REMOTE_CONFIGURATION_INVALID") from None

    @staticmethod
    def _scope(owner, configuration):
        return dict(owner=owner, reference=configuration["credentialRef"],
                    revision=configuration["credentialRevision"], destination=configuration["origin"])

    def authorized(self, owner, configuration):
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
        status, _ = self.probe.get(destination, address, "/global/health")
        if status != 401:
            raise RemoteConnectionError("REMOTE_AUTH_REQUIRED")
        try:
            lease = self.secrets.resolve(**self._scope(owner, configuration))
            if not isinstance(lease, SecretLease):
                raise ValueError()
        except Exception:
            raise RemoteConnectionError("REMOTE_CREDENTIAL_UNAVAILABLE") from None
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
                "capabilities": sorted(self.capabilities), "identityBasis": "tls-origin-basic-auth-project"}

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

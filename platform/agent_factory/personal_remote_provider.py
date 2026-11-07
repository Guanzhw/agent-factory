"""Owner-configured OpenCode serve verification.

Contract: https://opencode.ai/docs/server/ (reviewed 2026-10-08).
Identity means TLS origin + credential possession + exact project, not a human
identity. Secret backends are trusted injections and must enforce the entire
owner/reference/revision/destination tuple. No default environment secret lookup.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import ipaddress
import httpx
import re
from typing import Callable, Protocol
from urllib.parse import urlsplit

PROVIDER_ID = "opencode-serve-v1"
CAPABILITIES = frozenset({"runtime:health", "project:read", "agent:read"})


class RemoteConnectionError(ValueError):
    """Only fixed diagnostic codes may cross this boundary."""


@dataclass(frozen=True)
class SecretLease:
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self):
        if (not self.username or not self.password or ':' in self.username
                or any(ord(c) < 32 for c in self.username + self.password)):
            raise RemoteConnectionError("REMOTE_CREDENTIAL_INVALID")




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
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
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


class PinnedHTTPSProbe:
    """Compatibility name; HTTPX owns DNS, TLS, streaming and idle timeouts."""
    def addresses(self, destination):
        # Preserve the injected-probe interface without a separate DNS process.
        return [urlsplit(origin(destination)).hostname]

    def get(self, destination, address, path, lease=None):
        if path not in {"/global/health", "/project/current", "/agent"}:
            raise RemoteConnectionError("REMOTE_PATH_DENIED")
        headers = {"Accept": "application/json"}
        if lease is not None:
            headers["Authorization"] = "Basic " + base64.b64encode(
                (lease.username + ':' + lease.password).encode()).decode()
        try:
            # The native timeout concerns idle transport operations, not total
            # response duration. Active streams are not cut off after 10 seconds.
            with httpx.Client(follow_redirects=False) as client:
                response = client.get(origin(destination) + path, headers=headers)
                if response.status_code != 200:
                    return response.status_code, None
                value = response.json()
            return response.status_code, value
        except RemoteConnectionError:
            raise
        except Exception:
            raise RemoteConnectionError("REMOTE_PROBE_FAILED") from None


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
            results[path] = value
        health, project, agents = (results[path] for path in ("/global/health", "/project/current", "/agent"))
        if (not isinstance(health, dict) or health.get("healthy") is not True
                or not isinstance(health.get("version"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", health["version"])
                or not isinstance(project, dict) or project.get("id") != configuration["projectId"]
                or not isinstance(agents, list) or not agents
                or any(not isinstance(agent, dict) or not isinstance(agent.get("name"), str)
                       or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", agent["name"]) for agent in agents)):
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

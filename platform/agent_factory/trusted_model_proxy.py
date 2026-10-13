"""Explicit, owner/version/deployment-scoped trusted gateway; default is direct.

The gateway may terminate TLS and read credentials/request data. It is responsible
for upstream routing/filtering; client CONNECT pinning is not end-to-end IP pin.
No environment discovery, credential input, redirects, retries or fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import math
import re
import ssl
from typing import cast
from urllib.parse import urlsplit

import httpcore
import httpx

from .model_endpoint_policy import GO_BASE, base_url as normalize_base_url
from .model_protocol import protocol_name, protocol_path


def _verified(context):
    if (not isinstance(context, ssl.SSLContext) or not context.check_hostname
            or context.verify_mode != ssl.CERT_REQUIRED):
        raise ValueError('TRUSTED_MODEL_PROXY_TLS_REQUIRED')
    return hashlib.sha256(b''.join(sorted(context.get_ca_certs(binary_form=True)))).digest()


@dataclass(frozen=True, repr=False)
class TrustedModelProxy:
    environment_id: str
    owner_id: str
    model_reference: str
    model_revision: str
    credential_reference: str
    credential_revision: str
    model_id: str
    proxy_url: str = field(repr=False)
    ssl_context: ssl.SSLContext = field(repr=False)
    acknowledge_interception: bool = False
    dns_timeout_seconds: float = 3
    # Omitted fields retain the exact legacy grant rather than expanding it.
    base_url: str = GO_BASE
    protocol: str = 'chat-completions'
    _ca_digest: bytes = field(init=False, repr=False)
    _proxy_host: str = field(init=False, repr=False)
    _proxy_port: int = field(init=False, repr=False)
    _target_host: str = field(init=False, repr=False)

    def __post_init__(self):
        try:
            values = (self.environment_id, self.owner_id, self.model_reference,
                self.model_revision, self.credential_reference, self.credential_revision, self.model_id)
            if any(type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,256}', value) for value in values):
                raise ValueError()
            if self.acknowledge_interception is not True:
                raise ValueError()
            if (type(self.dns_timeout_seconds) not in {int, float}
                    or not math.isfinite(self.dns_timeout_seconds)
                    or not 3 <= self.dns_timeout_seconds <= 10):
                raise ValueError()
            target_base = normalize_base_url(self.base_url)
            protocol_path(self.protocol)
            object.__setattr__(self, 'base_url', target_base)
            object.__setattr__(self, '_target_host', httpx.URL(target_base).host)
            url = urlsplit(self.proxy_url)
            if (type(self.proxy_url) is not str or any(char.isspace() for char in self.proxy_url)
                    or url.scheme not in {'http', 'https'} or not url.hostname
                    or url.username is not None or url.password is not None
                    or url.path not in {'', '/'} or url.query or url.fragment
                    or url.port is not None and not 1 <= url.port <= 65535):
                raise ValueError()
            object.__setattr__(self, '_proxy_host', url.hostname)
            object.__setattr__(self, '_proxy_port', url.port or (443 if url.scheme == 'https' else 80))
            object.__setattr__(self, '_ca_digest', _verified(self.ssl_context))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('TRUSTED_MODEL_PROXY_CONFIGURATION_INVALID') from None

    def __repr__(self):
        return 'TrustedModelProxy(scope=<redacted>, gateway=<redacted>, mode=trusted-gateway)'

    def validate_environment(self, environment_id):
        if environment_id != self.environment_id:
            raise ValueError('TRUSTED_MODEL_PROXY_ENVIRONMENT_DENIED')
        self.validate_tls()

    def validate_tls(self):
        if _verified(self.ssl_context) != self._ca_digest:
            raise ValueError('TRUSTED_MODEL_PROXY_TLS_CHANGED')

    def select(self, owner, body, environment_id):
        if owner != self.owner_id or body.get('reference') != self.model_reference:
            return None
        self.validate_environment(environment_id)
        expected = {'ownerId': self.owner_id, 'reference': self.model_reference,
            'revision': self.model_revision, 'credentialRef': self.credential_reference,
            'credentialRevision': self.credential_revision, 'model': self.model_id, 'baseURL': self.base_url}
        try:
            if (any(body.get(key) != value for key, value in expected.items())
                    or protocol_name(body) != self.protocol):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('TRUSTED_MODEL_PROXY_SCOPE_CHANGED') from None
        return self

    def validate_payload(self, value):
        try:
            if len(value) > 1_048_576:
                raise ValueError()
            body = json.loads(value)
            if type(body) is not dict or body.get('model') != self.model_id or body.get('stream') is not False:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('TRUSTED_MODEL_PROXY_REQUEST_DENIED') from None

    def transport(self, checked_ip, hostname):
        self.validate_tls()
        # Narrow current-cloud route. IPv6 support is not silently approximated.
        try:
            address = ipaddress.IPv4Address(checked_ip)
            if not address.is_global or str(address) != checked_ip or hostname != self._target_host:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('TRUSTED_MODEL_PROXY_TARGET_DENIED') from None
        return _ProxyTransport(self, checked_ip)


class _BoundStream(httpcore.AsyncNetworkStream):
    def __init__(self, stream, grant, checked_ip):
        self.stream, self.grant, self.checked_ip = stream, grant, checked_ip
        self.stage = 'proxy' if urlsplit(grant.proxy_url).scheme == 'https' else 'target'

    async def read(self, max_bytes, timeout=None):
        return await self.stream.read(max_bytes, timeout=timeout)

    async def write(self, buffer, timeout=None):
        await self.stream.write(buffer, timeout=timeout)

    async def aclose(self):
        await self.stream.aclose()

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.grant.validate_tls()
        if ssl_context is not self.grant.ssl_context:
            raise ValueError('TRUSTED_MODEL_PROXY_TLS_CHANGED')
        if self.stage == 'proxy' and server_hostname == self.grant._proxy_host:
            name, next_stage = server_hostname, 'target'
        elif self.stage == 'target' and server_hostname == self.checked_ip:
            name, next_stage = self.grant._target_host, 'ready'
        else:
            raise ValueError('TRUSTED_MODEL_PROXY_TLS_BINDING_DENIED')
        self.stream = await self.stream.start_tls(
            ssl_context, server_hostname=name, timeout=timeout)
        self.stage = next_stage
        return self


class _BoundBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, grant, checked_ip):
        self.grant, self.checked_ip = grant, checked_ip
        self.backend = cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())
        self.connection_started = False

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self.connection_started or (host, port) != (self.grant._proxy_host, self.grant._proxy_port):
            raise ValueError('TRUSTED_MODEL_PROXY_CONNECTION_DENIED')
        self.grant.validate_tls()
        self.connection_started = True
        stream = await self.backend.connect_tcp(host, port, timeout=timeout,
            local_address=local_address, socket_options=socket_options)
        return _BoundStream(stream, self.grant, self.checked_ip)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise ValueError('TRUSTED_MODEL_PROXY_CONNECTION_DENIED')

    async def sleep(self, seconds):
        raise ValueError('TRUSTED_MODEL_PROXY_RETRY_DENIED')


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class _ProxyTransport(httpx.AsyncBaseTransport):
    def __init__(self, grant, checked_ip):
        self.grant, self.checked_ip = grant, checked_ip
        self.target_url = httpx.URL(grant.base_url + protocol_path(grant.protocol)).copy_with(host=checked_ip)
        self.started = False
        self.pool = httpcore.AsyncConnectionPool(
            proxy=httpcore.Proxy(grant.proxy_url, ssl_context=grant.ssl_context),
            ssl_context=grant.ssl_context, network_backend=_BoundBackend(grant, checked_ip),
            max_connections=1, max_keepalive_connections=0, retries=0, http1=True, http2=False)

    async def handle_async_request(self, request):
        if (self.started or request.method != 'POST'
                or request.url != self.target_url
                or request.headers.get('host') != self.grant._target_host):
            raise ValueError('TRUSTED_MODEL_PROXY_REQUEST_DENIED')
        self.grant.validate_tls()
        self.grant.validate_payload(await request.aread())
        self.started = True
        # The binding supplies target SNI; the direct extension would also affect
        # an HTTPS proxy's outer TLS. Do not forward arbitrary trace extensions.
        extensions = {key: value for key, value in request.extensions.items() if key == 'timeout'}
        core = httpcore.Request(method=request.method, url=httpcore.URL(
            scheme=request.url.raw_scheme, host=request.url.raw_host,
            port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=extensions)
        response = await self.pool.handle_async_request(core)
        return httpx.Response(response.status, headers=response.headers,
            stream=_ResponseStream(response.stream), extensions=response.extensions)

    async def aclose(self):
        await self.pool.aclose()

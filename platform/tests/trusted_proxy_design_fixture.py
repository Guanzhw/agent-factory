"""Test-only design reference; no environment reads or default network backend.

Never imported by agent_factory. A caller supplies a synthetic backend in tests.
The tests supply only an in-memory backend. Proxy upstream IP behavior remains an
environment-admin prerequisite, not something this client can establish.
"""
from dataclasses import dataclass
import ipaddress
import ssl

import httpcore


@dataclass(frozen=True)
class Binding:
    checked_ip: str
    server_name: str
    proxy_host: str
    proxy_port: int
    proxy_https: bool = False

    def __post_init__(self):
        address = ipaddress.ip_address(self.checked_ip)
        if not address.is_global or str(address) != self.checked_ip:
            raise ValueError('CHECKED_PUBLIC_IP_REQUIRED')
        if address.version != 4:
            # The current observed selected destination is IPv4. IPv6 CONNECT
            # authority formatting needs its own reviewed implementation/tests.
            raise ValueError('REVIEW_PROTOTYPE_IPV4_ONLY')
        if self.server_name != 'opencode.ai':
            raise ValueError('EXACT_BOUND_HOST_REQUIRED')
        if not self.proxy_host or not 1 <= self.proxy_port <= 65535:
            raise ValueError('DEPLOYMENT_PROXY_REQUIRED')


def require_verified(context):
    if (not isinstance(context, ssl.SSLContext)
            or context.verify_mode != ssl.CERT_REQUIRED
            or not context.check_hostname):
        raise ValueError('FULL_TLS_VERIFICATION_REQUIRED')


class BoundStream(httpcore.AsyncNetworkStream):
    def __init__(self, stream, binding):
        self.stream, self.binding = stream, binding
        self.stage = 'PROXY_TLS' if binding.proxy_https else 'TARGET_TLS'

    async def read(self, max_bytes, timeout=None):
        return await self.stream.read(max_bytes, timeout=timeout)

    async def write(self, buffer, timeout=None):
        await self.stream.write(buffer, timeout=timeout)

    async def aclose(self):
        await self.stream.aclose()

    def get_extra_info(self, info):
        return self.stream.get_extra_info(info)

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        require_verified(ssl_context)
        if self.stage == 'PROXY_TLS':
            if server_hostname != self.binding.proxy_host:
                raise ValueError('PROXY_TLS_HOST_MISMATCH')
            name = server_hostname
            next_stage = 'TARGET_TLS'
        elif self.stage == 'TARGET_TLS':
            if server_hostname != self.binding.checked_ip:
                raise ValueError('TARGET_TLS_BINDING_MISMATCH')
            name = self.binding.server_name
            next_stage = 'READY'
        else:
            raise ValueError('UNEXPECTED_TLS_REUSE')
        # Preserve the supplied CA/verification context and all TLS exceptions.
        self.stream = await self.stream.start_tls(
            ssl_context, server_hostname=name, timeout=timeout)
        self.stage = next_stage
        return self


class BoundBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, backend, binding):
        self.backend, self.binding = backend, binding

    async def connect_tcp(self, host, port, timeout=None, local_address=None,
                          socket_options=None):
        if (host, port) != (self.binding.proxy_host, self.binding.proxy_port):
            raise ValueError('ONLY_APPROVED_PROXY_CONNECT_ALLOWED')
        stream = await self.backend.connect_tcp(
            host, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options)
        return BoundStream(stream, self.binding)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise ValueError('UNIX_PROXY_ROUTE_DENIED')

    async def sleep(self, seconds):
        # A retry delay here would violate the zero-retry prototype contract.
        raise ValueError('RETRY_DENIED')


def bound_pool(binding, backend, context):
    """One immutable destination binding per invocation; no pool reuse/fallback."""
    require_verified(context)
    proxy_scheme = 'https' if binding.proxy_https else 'http'
    proxy = httpcore.Proxy(
        f'{proxy_scheme}://{binding.proxy_host}:{binding.proxy_port}',
        ssl_context=context if binding.proxy_https else None)
    return httpcore.AsyncConnectionPool(
        proxy=proxy, ssl_context=context,
        network_backend=BoundBackend(backend, binding),
        max_connections=1, max_keepalive_connections=0,
        http1=True, http2=False, retries=0)

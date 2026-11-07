"""Owner-model HTTP(S) transport shared by Agno and the private runtime broker.

Dispatch/replay decisions remain with callers. This layer never discovers an
environment proxy/key, redirects, retries, or relaxes HTTPS certificate validation.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

import httpx

from .model_endpoint_policy import base_url
from .personal_remote_provider import origin, reject_credential_echo

MAX_BYTES = 1_048_576


class PinnedChatTransport(httpx.AsyncBaseTransport):
    """Compatibility name; one configured protocol endpoint per transport."""
    def __init__(self, destination, *, before_send=None, base_path='/v1', on_dispatch=None,
            trusted_proxy=None, protocol='chat-completions'):
        from .model_protocol import protocol_path
        self.destination = origin(destination)
        self.base = base_url(self.destination + base_path)
        self.path = protocol_path(protocol)
        self.before_send = before_send
        self.on_dispatch = on_dispatch
        self.trusted_proxy = trusted_proxy
        if trusted_proxy is not None:
            from .trusted_model_proxy import TrustedModelProxy
            # An existing scoped grant cannot authorize another route/protocol.
            if (not isinstance(trusted_proxy, TrustedModelProxy) or self.base != trusted_proxy.base_url
                    or protocol != trusted_proxy.protocol):
                raise ValueError('TRUSTED_MODEL_PROXY_REQUEST_DENIED')
        self.transport = None if trusted_proxy else httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        if request.method != 'POST' or str(request.url) != self.base + self.path:
            raise ValueError('PERSONAL_MODEL_DESTINATION_DENIED')
        if self.before_send is not None:
            await asyncio.to_thread(self.before_send)
        # Let the HTTP transport (or configured gateway) resolve the original
        # hostname; no subprocess DNS deadline or address-count gate.
        forwarded = httpx.Request('POST', request.url,
            headers={**dict(request.headers), 'host': urlsplit(self.destination).netloc}, content=await request.aread(),
            extensions={**request.extensions, 'sni_hostname': request.url.host})
        if self.trusted_proxy is not None:
            if self.transport is not None:
                raise ValueError('TRUSTED_MODEL_PROXY_REQUEST_DENIED')
            self.trusted_proxy.validate_payload(forwarded.content)
            self.transport = self.trusted_proxy.transport(request.url.host, request.url.host)
        transport = self.transport
        if transport is None:
            raise ValueError('PERSONAL_MODEL_TRANSPORT_REQUIRED')
        if self.on_dispatch is not None:
            self.on_dispatch()
        return await transport.handle_async_request(forwarded)

    async def aclose(self):
        if self.transport is not None:
            await self.transport.aclose()


async def read_response_json(response, lease, idle_seconds=300):
    if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
        raise ValueError('PERSONAL_MODEL_REQUEST_FAILED')
    chunks = []
    async for chunk in with_idle_timeout(response.aiter_bytes(), idle_seconds):
        chunks.append(chunk)
    try:
        value = json.loads(b''.join(chunks))
    except (ValueError, UnicodeError):
        raise ValueError('PERSONAL_MODEL_RESPONSE_REJECTED') from None
    reject_credential_echo(value, lease)
    return value


async def with_idle_timeout(iterator, seconds=300):
    """Bound a stalled network read, not the duration or size of active output."""
    iterator = aiter(iterator)
    while True:
        try:
            async with asyncio.timeout(seconds):
                value = await anext(iterator)
        except StopAsyncIteration:
            return
        yield value

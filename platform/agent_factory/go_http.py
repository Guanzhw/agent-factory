"""Fixed Go destination with HTTPX environment proxy and verified CA support.

No host configuration is changed. Environment proxy/NO_PROXY and SSL_CERT_FILE/
SSL_CERT_DIR are interpreted by HTTPX, with no direct retry or TLS downgrade.
Explicit fixture transports remain isolated from the environment.
"""
from __future__ import annotations

import math

import httpx

_METHODS = {
    b"/zen/go/v1/chat/completions": "POST",
    b"/zen/go/v1/responses": "POST",
    b"/zen/go/v1/models": "GET",
}


async def _go_destination(request: httpx.Request) -> None:
    url = request.url
    if (url.scheme != "https" or url.host != "opencode.ai" or url.port not in {None, 443}
            or url.userinfo or url.query or url.fragment or "#" in str(url) or "@" in str(url)
            or _METHODS.get(url.raw_path) != request.method):
        # Never echo the rejected URL: it may contain credentials or user data.
        raise ValueError("GO_HTTP_DESTINATION_DENIED")


def open_go_client(*, timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("GO_HTTP_TIMEOUT_INVALID")
    if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
        raise ValueError("GO_HTTP_TRANSPORT_INVALID")
    # HTTPX's default AsyncHTTPTransport has retries=0. Leaving transport=None
    # is necessary for its native environment proxy mounts and NO_PROXY rules.
    # auth=None never opts into NetRCAuth, even when NETRC is present.
    return httpx.AsyncClient(timeout=timeout, transport=transport, trust_env=transport is None,
        verify=True, follow_redirects=False, auth=None, event_hooks={"request": [_go_destination]})

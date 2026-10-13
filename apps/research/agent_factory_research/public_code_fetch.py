"""Bounded, unauthenticated fetches of two immutable public coding references.

No credential lookup, arbitrary destination, retry, redirect, or direct fallback.
Controlled fixtures are explicitly labelled and never evidence of a live fetch.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import math
import ssl

import httpx

COMMIT = "914de54a18ee3ccda772f578a217f7df6594c805"
SOURCE_URLS = tuple("https://raw.githubusercontent.com/Guanzhw/agent-factory/" + COMMIT + "/" + path for path in (
    "platform/agent_factory/go_http.py", "platform/tests/test_go_http.py"))
MAX_FILE_BYTES = 65536
MAX_TOTAL_BYTES = 131072
_ERROR_CODES = frozenset({"CONFIG_INVALID", "DESTINATION_DENIED", "HTTP_STATUS", "REDIRECT_DENIED",
    "BODY_ENCODING", "BODY_LIMIT", "TIMEOUT", "TRANSPORT", "TLS", "PROXY", "SNAPSHOT_INVALID"})


class PublicCodeFetchError(RuntimeError):
    def __init__(self, code: str, *, http_status: int | None = None):
        self.code = code if code in _ERROR_CODES else "TRANSPORT"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.code)


@dataclass(frozen=True)
class PublicCodeFile:
    url: str
    content: bytes
    sha256: str
    http_status: int
    evidence_mode: str

    @property
    def metadata(self):
        return {"publicUrl": self.url, "httpStatus": self.http_status, "sha256": self.sha256,
                "evidenceMode": self.evidence_mode, "byteCount": len(self.content)}


async def _destination(request: httpx.Request) -> None:
    url = request.url
    if (request.method != "GET" or url.scheme != "https" or url.host != "raw.githubusercontent.com"
            or url.port not in {None, 443} or url.userinfo or url.query or url.fragment
            or "#" in str(url) or "@" in str(url) or str(url) not in SOURCE_URLS):
        raise PublicCodeFetchError("DESTINATION_DENIED")
    # Set-Cookie on the first public response must not affect the second fetch.
    for name in ("authorization", "cookie"):
        request.headers.pop(name, None)


def _client(*, timeout: float, transport: httpx.MockTransport | None):
    return httpx.AsyncClient(timeout=timeout, transport=transport, trust_env=transport is None,
        verify=True, follow_redirects=False, auth=None,
        headers={"User-Agent": "agent-factory-public-code-fetch/1", "Accept-Encoding": "identity"},
        event_hooks={"request": [_destination]})


async def fetch_public_code(*, transport: httpx.MockTransport | None = None, timeout: float = 20) -> tuple[PublicCodeFile, ...]:
    """Fetch each fixed source at most once; return only after both are bounded."""
    if (type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 20
            or (transport is not None and type(transport) is not httpx.MockTransport)):
        raise PublicCodeFetchError("CONFIG_INVALID")
    mode = "live-public-fetch" if transport is None else "controlled-fixture"
    results = []
    total = 0
    try:
        async with _client(timeout=timeout, transport=transport) as client:
            for url in SOURCE_URLS:
                async with asyncio.timeout(timeout):
                    async with client.stream("GET", url) as response:
                        status = response.status_code
                        if 300 <= status < 400:
                            raise PublicCodeFetchError("REDIRECT_DENIED", http_status=status)
                        if status != 200:
                            raise PublicCodeFetchError("HTTP_STATUS", http_status=status)
                        if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                            raise PublicCodeFetchError("BODY_ENCODING", http_status=status)
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_FILE_BYTES or total + len(body) + len(chunk) > MAX_TOTAL_BYTES:
                                raise PublicCodeFetchError("BODY_LIMIT", http_status=status)
                            body.extend(chunk)
                        content = bytes(body)
                        total += len(content)
                        results.append(PublicCodeFile(url, content, sha256(content).hexdigest(), status, mode))
    except PublicCodeFetchError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise PublicCodeFetchError("TIMEOUT") from None
    except ssl.SSLError:
        raise PublicCodeFetchError("TLS") from None
    except httpx.ProxyError:
        raise PublicCodeFetchError("PROXY") from None
    except Exception:
        raise PublicCodeFetchError("TRANSPORT") from None
    return tuple(results)


async def fetch_snapshot(*, transport: httpx.MockTransport | None = None, timeout: float = 20) -> dict:
    """Return a hash-verified knowledge snapshot; source schema owns provenance."""
    from .public_code_knowledge import SOURCE_SET_ID, source_specs, validate_snapshot
    files = await fetch_public_code(transport=transport, timeout=timeout)
    specs = source_specs()
    if len(specs) != len(files) or {s["rawUrl"] for s in specs} != set(SOURCE_URLS):
        raise PublicCodeFetchError("SNAPSHOT_INVALID")
    by_url = {value.url: value for value in files}
    snapshot = {"sourceSetId": SOURCE_SET_ID, "evidenceMode": files[0].evidence_mode,
                "sources": [{**spec, "content": by_url[spec["rawUrl"]].content} for spec in specs]}
    try:
        validate_snapshot(snapshot)
    except Exception:
        raise PublicCodeFetchError("SNAPSHOT_INVALID") from None
    return snapshot

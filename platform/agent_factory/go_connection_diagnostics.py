"""Bounded, lossy connection failure classification without exception text."""
from __future__ import annotations

import asyncio
import errno
import socket
import ssl

import httpcore
import httpx

_ERRNOS = {getattr(errno, name): name for name in (
    "ECONNREFUSED", "ECONNRESET", "ECONNABORTED", "ETIMEDOUT", "ENETUNREACH",
    "EHOSTUNREACH", "EPIPE", "EACCES", "EPERM") if hasattr(errno, name)}
_DNS_ERRNOS = {getattr(socket, name): name for name in ("EAI_AGAIN", "EAI_NONAME", "EAI_FAIL", "EAI_NODATA") if hasattr(socket, name)}
_PROXY_STATUSES = {"403 Forbidden": 403, "407 Proxy Authentication Required": 407, "451 Unavailable For Legal Reasons": 451}
_TYPES = {
    socket.gaierror: ("gaierror", "DNS"),
    ssl.SSLCertVerificationError: ("SSLCertVerificationError", "TLS"),
    ssl.SSLError: ("SSLError", "TLS"),
    httpcore.ProxyError: ("ProxyError", "PROXY"),
    httpcore.ConnectError: ("ConnectError", "CONNECTION"),
    httpcore.ConnectTimeout: ("ConnectTimeout", "TIMEOUT"),
    httpcore.ReadTimeout: ("ReadTimeout", "TIMEOUT"),
    httpx.ProxyError: ("ProxyError", "PROXY"),
    httpx.ConnectError: ("ConnectError", "CONNECTION"),
    httpx.ConnectTimeout: ("ConnectTimeout", "TIMEOUT"),
    httpx.ReadTimeout: ("ReadTimeout", "TIMEOUT"),
    httpx.WriteTimeout: ("WriteTimeout", "TIMEOUT"),
    httpx.PoolTimeout: ("PoolTimeout", "TIMEOUT"),
    httpx.TimeoutException: ("TimeoutException", "TIMEOUT"),
    TimeoutError: ("TimeoutError", "TIMEOUT"),
    ConnectionRefusedError: ("ConnectionRefusedError", "TCP"),
    ConnectionResetError: ("ConnectionResetError", "TCP"),
    ConnectionAbortedError: ("ConnectionAbortedError", "TCP"),
    BrokenPipeError: ("BrokenPipeError", "TCP"),
    OSError: ("OSError", "UNKNOWN"),
    asyncio.CancelledError: ("CancelledError", "CANCELLED"),
    ExceptionGroup: ("ExceptionGroup", "UNKNOWN"),
    BaseExceptionGroup: ("BaseExceptionGroup", "UNKNOWN"),
}


def safe_connection_diagnostic(error: BaseException) -> dict:
    """Examine at most eight nodes/four edges; never str/repr untrusted objects."""
    pending = [(error, 0)]
    seen = set()
    causes = []
    while pending and len(seen) < 8:
        current, depth = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        kind, category = _TYPES.get(type(current), ("UnknownError", "UNKNOWN"))
        item: dict = {"errorType": kind, "category": category}
        # Access the built-in descriptor, not an arbitrary subclass property.
        if type(current) in _TYPES and isinstance(current, OSError):
            number = OSError.__dict__["errno"].__get__(current)
            if type(number) is int and number in _ERRNOS:
                item["errnoSymbol"] = _ERRNOS[number]
        if type(current) is socket.gaierror:
            number = OSError.__dict__["errno"].__get__(current)
            if type(number) is int and number in _DNS_ERRNOS:
                item["errnoSymbol"] = _DNS_ERRNOS[number]
        if type(current) in {httpx.ProxyError, httpcore.ProxyError}:
            arguments = BaseException.__dict__["args"].__get__(current)
            if len(arguments) == 1 and type(arguments[0]) is str and arguments[0] in _PROXY_STATUSES:
                item["proxyStatus"] = _PROXY_STATUSES[arguments[0]]
        if type(current) is OSError and item.get("errnoSymbol") in {
                "ECONNREFUSED", "ECONNRESET", "ECONNABORTED", "ENETUNREACH", "EHOSTUNREACH", "EPIPE"}:
            item["category"] = "TCP"
        causes.append(item)
        if depth >= 4:
            continue
        for descriptor in (BaseException.__dict__["__cause__"], BaseException.__dict__["__context__"]):
            child = descriptor.__get__(current)
            if isinstance(child, BaseException):
                pending.append((child, depth + 1))
        if type(current) in {ExceptionGroup, BaseExceptionGroup}:
            for child in BaseExceptionGroup.__dict__["exceptions"].__get__(current)[:8]:
                pending.append((child, depth + 1))
    categories = {item["category"] for item in causes}
    category = next((value for value in ("CANCELLED", "PROXY", "TLS", "DNS", "TIMEOUT", "TCP", "CONNECTION")
                     if value in categories), "UNKNOWN")
    return {"category": category, "proxyErrorPresent": "PROXY" in categories,
            "safeCauses": causes,
            "summary": "Local connection diagnostics do not establish socket or server receipt."}

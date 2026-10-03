"""Lossy, allowlisted Go diagnostics. Never serialize exception or server text."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from agno.exceptions import ModelProviderError

PHASES = frozenset({"PREPARED", "CREDENTIAL_CHECK", "DISPATCH_STARTED", "RESPONSE_HEADERS",
                   "STREAM_COMPLETED", "PARSED", "FAILED", "UNKNOWN", "RUNNER_STARTED",
                   "RUNNER_FAILED", "RUNNER_STOPPED", "RUNNER_COMPLETED"})
_PHASE_SUMMARIES = {
    "PREPARED": "A durable local request slot was reserved.",
    "CREDENTIAL_CHECK": "Local credential authorization is about to be checked.",
    "DISPATCH_STARTED": "The local HTTP dispatch call is about to start; no socket or server receipt is established.",
    "RESPONSE_HEADERS": "The HTTP client exposed response headers.",
    "STREAM_COMPLETED": "The HTTP body reached EOF; successful parsing is not established.",
    "PARSED": "The bounded provider response was parsed.",
    "FAILED": "The operation failed; dispatch certainty requires the recorded phase history.",
    "UNKNOWN": "The operation outcome is not established.",
    "RUNNER_STARTED": "The local validation runner started.",
    "RUNNER_FAILED": "The local validation runner failed.",
    "RUNNER_STOPPED": "The local validation runner stopped.",
    "RUNNER_COMPLETED": "The local validation runner completed.",
}
_TYPES = {
    httpx.ConnectError: ("ConnectError", "connection"),
    httpx.ConnectTimeout: ("ConnectTimeout", "timeout"),
    httpx.ReadError: ("ReadError", "read"),
    httpx.ReadTimeout: ("ReadTimeout", "timeout"),
    httpx.WriteError: ("WriteError", "connection"),
    httpx.WriteTimeout: ("WriteTimeout", "timeout"),
    httpx.PoolTimeout: ("PoolTimeout", "timeout"),
    httpx.TimeoutException: ("TimeoutException", "timeout"),
    httpx.RemoteProtocolError: ("RemoteProtocolError", "protocol"),
    httpx.LocalProtocolError: ("LocalProtocolError", "protocol"),
    httpx.ProtocolError: ("ProtocolError", "protocol"),
    httpx.DecodingError: ("DecodingError", "parse"),
    httpx.InvalidURL: ("InvalidURL", "protocol"),
    httpx.UnsupportedProtocol: ("UnsupportedProtocol", "protocol"),
    json.JSONDecodeError: ("JSONDecodeError", "parse"),
    TimeoutError: ("TimeoutError", "timeout"),
    ConnectionError: ("ConnectionError", "connection"),
    BrokenPipeError: ("BrokenPipeError", "connection"),
    ConnectionResetError: ("ConnectionResetError", "connection"),
    ValueError: ("ValueError", "parse"),
    KeyError: ("KeyError", "parse"),
    TypeError: ("TypeError", "parse"),
    AttributeError: ("AttributeError", "parse"),
    IndexError: ("IndexError", "parse"),
    RuntimeError: ("RuntimeError", "unknown"),
    OSError: ("OSError", "unknown"),
}
_ERROR_PAIRS = frozenset((*_TYPES.values(), ("UnknownError", "unknown"),
                          ("CancelledError", "cancel"), ("ModelProviderError", "protocol")))


def _error_kind(error, phase):
    if isinstance(error, asyncio.CancelledError):
        kind, category = "CancelledError", "cancel"
    elif isinstance(error, ModelProviderError):
        kind, category = "ModelProviderError", "protocol"
        original = getattr(error, "_go_diagnostic", None)
        if (type(original) is tuple and len(original) == 2
                and all(type(value) is str for value in original) and original in _ERROR_PAIRS):
            kind, category = original
    else:
        kind, category = _TYPES.get(type(error), ("UnknownError", "unknown"))
    return kind, "credential" if phase == "CREDENTIAL_CHECK" and category != "cancel" else category


def _headers(value):
    # Even a request ID or a Retry-After value can contain arbitrary server text.
    # Map only recognized syntax to a finite set; never copy raw values or hashes.
    if type(value) not in {dict, httpx.Headers}:
        return {}
    result = {}
    content = value.get("content-type")
    if type(content) is str:
        media = content.split(";", 1)[0].strip().lower()
        result["contentType"] = {"text/event-stream": "event-stream", "application/json": "json"}.get(media, "other")
    retry = value.get("retry-after")
    if retry is not None:
        bucket = "invalid"
        if type(retry) is str and retry.isascii() and retry.isdecimal() and len(retry) <= 4:
            seconds = int(retry)
            bucket = "none" if seconds == 0 else "short" if seconds <= 60 else "long"
        result["retryAfterBucket"] = bucket
    return result


def safe_diagnostic(phase, *, http_status=None, response_headers=None, error=None) -> dict[str, Any]:
    if type(phase) is not str or phase not in PHASES:
        raise ValueError("Unsupported diagnostic phase")
    result: dict[str, Any] = {"phase": phase, "summary": _PHASE_SUMMARIES[phase]}
    if type(http_status) is int and 100 <= http_status <= 599:
        result["httpStatus"] = http_status
    if response_headers is not None:
        result["responseHeaders"] = _headers(response_headers)
    if error is not None:
        result["errorType"], result["errorCategory"] = _error_kind(error, phase)
    return result

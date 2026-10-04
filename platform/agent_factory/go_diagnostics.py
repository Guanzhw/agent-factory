"""Lossy, allowlisted Go diagnostics. Never serialize exception or server text."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import httpcore
import socket
import ssl
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



# Stable diagnostic vocabulary, independent of human-facing exception messages.
REJECTION_CODES = frozenset({
    "STREAM_SIZE", "STREAM_AFTER_DONE", "STREAM_MODEL_CHANGED", "RESPONSES_ERROR",
    "RESPONSES_FAILED", "RESPONSES_INCOMPLETE", "CHAT_ERROR", "STREAM_CHOICES_SHAPE",
    "STREAM_CHOICES_COUNT", "STREAM_CHOICE_INDEX", "STREAM_AFTER_TERMINAL", "STREAM_TOOL_INDEX",
    "STREAM_TOOL_TYPE", "STREAM_USAGE_EARLY", "STREAM_USAGE_REPEATED", "STREAM_INCOMPLETE_BUFFER",
    "STREAM_MISSING_TERMINAL", "STREAM_MISSING_RESPONSE", "TOOL_SHAPE", "TOOL_FUNCTION_SHAPE",
    "TOOL_ARGUMENTS_JSON", "TOOL_ARGUMENTS_SHAPE", "BILLING_UNVERIFIED", "CREDENTIAL_FAILURE",
    "CREDENTIAL_INVALID", "RESPONSE_INCOMPLETE", "RESPONSE_CHOICES", "RESPONSE_FINISH_REASON",
    "RESPONSE_CONTENT", "RESPONSE_DUPLICATE_TOOLS", "RESPONSE_USAGE_UNKNOWN", "RESPONSE_MODEL_MISMATCH",
    "RESPONSE_SHAPE", "REQUEST_DEADLINE", "HTTP_STATUS", "LIVE_REQUEST_CONTRACT", "RESPONSE_SIZE",
    "RESPONSE_USAGE_BOUND", "TRANSPORT_CONNECT", "TRANSPORT_READ", "TRANSPORT_WRITE",
    "TRANSPORT_PROTOCOL", "TRANSPORT_TIMEOUT", "TRANSPORT_DECODING", "TRANSPORT_URL",
    "JSON_DECODE", "STRUCTURE_ERROR", "CANCELLED", "UNKNOWN_ERROR",
})
INCOMPLETE_REASONS = frozenset({"MAX_OUTPUT_TOKENS", "CONTENT_FILTER", "MISSING", "MALFORMED", "OTHER"})
_INCOMPLETE_REJECTIONS = frozenset({"RESPONSES_INCOMPLETE", "RESPONSE_INCOMPLETE"})


def incomplete_reason(response):
    """Classify a decoded Responses object without retaining provider strings."""
    if type(response) is not dict:
        return "MALFORMED"
    details = dict.get(response, "incomplete_details")
    if details is None:
        return "MISSING"
    if type(details) is not dict:
        return "MALFORMED"
    reason = dict.get(details, "reason")
    if reason is None:
        return "MISSING"
    if type(reason) is not str:
        return "MALFORMED"
    return {"max_output_tokens": "MAX_OUTPUT_TOKENS", "content_filter": "CONTENT_FILTER"}.get(reason, "OTHER")


_OBSERVATION_MODELS = frozenset({"deepseek-flash", "deepseek-v4-flash", "deepseek-v4.1-flash", "gpt-6-luna"})


def _valid_usage_triple(value):
    return (type(value) is tuple and len(value) == 3
            and all(type(v) is int and 0 <= v <= 2**31 for v in value)
            and value[0] + value[1] == value[2])


def incomplete_usage(response, *, expected_model=None):
    """Provider-reported observation only; never authoritative ledger usage."""
    if (type(expected_model) is not str or expected_model not in _OBSERVATION_MODELS
            or type(response) is not dict or type(dict.get(response, "model")) is not str
            or dict.get(response, "model") != expected_model
            or type(dict.get(response, "status")) is not str or dict.get(response, "status") != "incomplete"):
        return None
    usage = dict.get(response, "usage")
    if type(usage) is not dict:
        return None
    values = tuple(dict.get(usage, key) for key in ("input_tokens", "output_tokens", "total_tokens"))
    return values if _valid_usage_triple(values) else None


_TYPE_REJECTIONS = {
    httpx.ConnectError: "TRANSPORT_CONNECT", httpx.ReadError: "TRANSPORT_READ",
    httpx.WriteError: "TRANSPORT_WRITE", httpx.RemoteProtocolError: "TRANSPORT_PROTOCOL",
    httpx.LocalProtocolError: "TRANSPORT_PROTOCOL", httpx.ProtocolError: "TRANSPORT_PROTOCOL",
    httpx.ConnectTimeout: "TRANSPORT_TIMEOUT", httpx.ReadTimeout: "TRANSPORT_TIMEOUT",
    httpx.WriteTimeout: "TRANSPORT_TIMEOUT", httpx.PoolTimeout: "TRANSPORT_TIMEOUT",
    httpx.TimeoutException: "TRANSPORT_TIMEOUT", TimeoutError: "TRANSPORT_TIMEOUT",
    httpx.DecodingError: "TRANSPORT_DECODING", httpx.InvalidURL: "TRANSPORT_URL",
    httpx.UnsupportedProtocol: "TRANSPORT_URL", json.JSONDecodeError: "JSON_DECODE",
    KeyError: "STRUCTURE_ERROR", TypeError: "STRUCTURE_ERROR", AttributeError: "STRUCTURE_ERROR",
    IndexError: "STRUCTURE_ERROR", asyncio.CancelledError: "CANCELLED",
}
_CHAIN_TYPES = {kind: name for kind, (name, _) in _TYPES.items()}
_CHAIN_TYPES.update({
    ModelProviderError: "ModelProviderError", asyncio.CancelledError: "CancelledError",
    httpx.ProxyError: "ProxyError", httpcore.ConnectError: "ConnectError",
    httpcore.ReadError: "ReadError", httpcore.WriteError: "WriteError",
    httpcore.ConnectTimeout: "ConnectTimeout", httpcore.ReadTimeout: "ReadTimeout",
    httpcore.WriteTimeout: "WriteTimeout", httpcore.PoolTimeout: "PoolTimeout",
    httpcore.RemoteProtocolError: "RemoteProtocolError", httpcore.LocalProtocolError: "LocalProtocolError",
    httpcore.ProxyError: "ProxyError", socket.gaierror: "gaierror",
    ssl.SSLError: "SSLError", ssl.SSLCertVerificationError: "SSLCertVerificationError",
    ExceptionGroup: "ExceptionGroup", BaseExceptionGroup: "BaseExceptionGroup",
})
EXCEPTION_CHAIN_NAMES = frozenset({*_CHAIN_TYPES.values(), "UnknownError"})
MAX_EXCEPTION_CHAIN = 6


def _exception_data(error):
    # Bypass subclass properties/__getattribute__; never inspect args or text.
    if not issubclass(type(error), BaseException):
        return {}
    return BaseException.__dict__["__dict__"].__get__(error, type(error))


def _class_name(error):
    if issubclass(type(error), ModelProviderError):
        return "ModelProviderError"
    if issubclass(type(error), asyncio.CancelledError):
        return "CancelledError"
    return _CHAIN_TYPES.get(type(error), "UnknownError")


def _stored_chain(data):
    value = dict.get(data, "_go_exception_chain")
    if (type(value) is tuple and 1 <= len(value) <= MAX_EXCEPTION_CHAIN
            and all(type(name) is str and name in EXCEPTION_CHAIN_NAMES for name in value)):
        return value
    return None


def _exception_chain(error):
    chain, seen = [], set()
    current = error
    while issubclass(type(current), BaseException) and len(chain) < MAX_EXCEPTION_CHAIN:
        if id(current) in seen:
            break
        seen.add(id(current))
        stored = _stored_chain(_exception_data(current))
        if stored is not None:
            chain.extend(stored[:MAX_EXCEPTION_CHAIN - len(chain)])
            break
        chain.append(_class_name(current))
        cause = BaseException.__dict__["__cause__"].__get__(current, type(current))
        context = BaseException.__dict__["__context__"].__get__(current, type(current))
        # One causal spine, not exception-group children or arbitrary attributes.
        current = cause if cause is not None else context
    return tuple(chain) or ("UnknownError",)


def _rejection_code(error):
    value = dict.get(_exception_data(error), "_go_rejection_code")
    if type(value) is str and value in REJECTION_CODES:
        return value
    return _TYPE_REJECTIONS.get(type(error), "UNKNOWN_ERROR")


def annotate_go_error(error, *, rejection_code=None, original_error=None, incomplete_reason=None, reported_usage=None):
    """Attach only finite diagnostic metadata; preserve the original exception."""
    data = _exception_data(error)
    if original_error is not None:
        # Copy only sanitized metadata before a wrapper suppresses its context.
        original = safe_diagnostic("FAILED", error=original_error)
        dict.__setitem__(data, "_go_diagnostic", (original["errorType"], original["errorCategory"]))
        dict.__setitem__(data, "_go_rejection_code", original["rejectionCode"])
        if "incompleteReason" in original:
            dict.__setitem__(data, "_go_incomplete_reason", original["incompleteReason"])
        if "reportedUsage" in original:
            usage = original["reportedUsage"]
            dict.__setitem__(data, "_go_reported_usage", (usage["inputTokens"], usage["outputTokens"], usage["totalTokens"]))
        dict.__setitem__(data, "_go_exception_chain", (_class_name(error), *original["exceptionChain"])[:MAX_EXCEPTION_CHAIN])
    # Without a wrapper, inspect the causal spine at recording time: Python
    # may attach __cause__/__context__ only when this exception is raised.
    if type(rejection_code) is str and rejection_code in REJECTION_CODES:
        dict.__setitem__(data, "_go_rejection_code", rejection_code)
    if type(incomplete_reason) is str and incomplete_reason in INCOMPLETE_REASONS:
        dict.__setitem__(data, "_go_incomplete_reason", incomplete_reason)
    if _valid_usage_triple(reported_usage):
        dict.__setitem__(data, "_go_reported_usage", reported_usage)
    return error


def _error_kind(error, phase):
    if issubclass(type(error), asyncio.CancelledError):
        kind, category = "CancelledError", "cancel"
    elif issubclass(type(error), ModelProviderError):
        kind, category = "ModelProviderError", "protocol"
        original = dict.get(_exception_data(error), "_go_diagnostic")
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
        result["rejectionCode"] = _rejection_code(error)
        reason = dict.get(_exception_data(error), "_go_incomplete_reason")
        if (result["rejectionCode"] in _INCOMPLETE_REJECTIONS
                and type(reason) is str and reason in INCOMPLETE_REASONS):
            result["incompleteReason"] = reason
        usage = dict.get(_exception_data(error), "_go_reported_usage")
        if result["rejectionCode"] in _INCOMPLETE_REJECTIONS and usage is not None and _valid_usage_triple(usage):
            result["reportedUsage"] = {"inputTokens": usage[0], "outputTokens": usage[1], "totalTokens": usage[2],
                                       "observationStatus": "provider-incomplete-unsettled"}
        result["exceptionChain"] = list(_exception_chain(error))
    return result

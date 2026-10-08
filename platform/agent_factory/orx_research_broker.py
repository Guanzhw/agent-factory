"""Task-local, buffered ChatCompletions broker; never exposes provider credentials.

The operator supplies durable reservation/settlement callbacks. A new broker
instance is not a fresh billing budget: reserve must enforce the task's ledger.
No endpoint starts a server, discovers credentials, or authorizes paid access.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from agno.models.response import ModelResponse
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .go_diagnostics import safe_diagnostic
from .go_http import open_go_client
from .go_usage import go_response_usage
from .opencode_go import USER_AGENT, _Stream, _call, _usage
from .usage_ledger import UsageEvidence

MODEL = "deepseek-flash"
_URL = "https://opencode.ai/zen/go/v1/chat/completions"


class _Rejected(Exception):
    def __init__(self, code: str):
        self.code = code


def _safe_error(error):
    # Same sanitizer used by GoDiagnosticJournal; no message/args/header/body.
    value = safe_diagnostic("FAILED", error=error)
    return {key: value[key] for key in ("errorType", "errorCategory", "rejectionCode", "exceptionChain")}


class _BufferedResponse(Response):
    async def __call__(self, scope, receive, send):
        self.diagnostic["operation"] = "delivery"
        try:
            await super().__call__(scope, receive, send)
        except BaseException as error:
            self.diagnostic["error"] = _safe_error(error)
            raise
        self.diagnostic["phase"] = "delivered"

    def __init__(self, content, *, media_type, diagnostic):
        super().__init__(content, media_type=media_type)
        self.diagnostic = diagnostic


def _json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


class ORXResearchBroker:
    """One capability, model and stable conversation, with serial admission.

    Callback failures stop the broker. ``hold`` must preserve the original
    reservation on unknown outcomes; ``settle`` receives authoritative counters
    only after verified response EOF. All callbacks are trusted async callables.
    Streaming responses retain their original bytes but are buffered before any
    child-visible output, so partial tools cannot execute before verification.
    """

    def __init__(self, *, capability: str, session_id: str,
                 credential: Callable[[], str], current_authority: Callable[[], Awaitable[bool]],
                 reserve: Callable[[int, int, int, dict], Awaitable[Any]],
                 settle: Callable[[Any, UsageEvidence], Awaitable[None]],
                 hold: Callable[[Any, str], Awaitable[None]],
                 transport: httpx.AsyncBaseTransport | None = None,
                 max_requests: int = 3, max_output_tokens: int = 512,
                 max_input_bytes: int = 32768, max_output_bytes: int = 262144):
        if not isinstance(capability, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", capability):
            raise ValueError("BROKER_CAPABILITY_INVALID")
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("BROKER_SESSION_INVALID")
        for value, upper in ((max_requests, 16), (max_output_tokens, 4096),
                             (max_input_bytes, 32768), (max_output_bytes, 262144)):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("BROKER_BOUND_INVALID")
        if not all(callable(x) for x in (credential, current_authority, reserve, settle, hold)):
            raise ValueError("BROKER_CALLBACK_INVALID")
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise ValueError("BROKER_TRANSPORT_INVALID")
        self._capability = capability
        self._session = session_id
        self._credential, self._authority = credential, current_authority
        self._reserve, self._settle, self._hold = reserve, settle, hold
        self._transport = transport
        self._max_requests, self._output_cap = max_requests, max_output_tokens
        self._input_bytes, self._output_bytes = max_input_bytes, max_output_bytes
        self._lock = asyncio.Lock()
        self.requests = 0
        self.stopped_reason: str | None = None
        self._diagnostics: list[dict[str, Any]] = []

    @property
    def diagnostics(self):
        """At most 16 local records; dispatch is not server acknowledgement.

        delivered means ASGI send returned, not downstream execution or receipt.
        phase=None means no reservation was confirmed; no historical backfill.
        """
        return json.loads(json.dumps(self._diagnostics))

    @property
    def app(self):
        return self

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            raise ValueError("BROKER_HTTP_ONLY")
        request = Request(scope, receive)
        response: Response
        try:
            headers = request.headers.getlist("authorization")
            if (len(headers) != 1 or not hmac.compare_digest(
                    headers[0].encode(), ("Bearer " + self._capability).encode())):
                raise _Rejected("CAPABILITY_DENIED")
            if request.method != "POST" or scope["path"] != "/v1/chat/completions" or scope.get("query_string"):
                raise _Rejected("ENDPOINT_DENIED")
            async with asyncio.timeout(60):
                raw = bytearray()
                async for part in request.stream():
                    raw.extend(part)
                    if len(raw) > self._input_bytes:
                        raise _Rejected("INPUT_BOUND")
                body = self._request(bytes(raw))
                if self._lock.locked():
                    raise _Rejected("INFLIGHT")
                async with self._lock:
                    response = await self._invoke(body)
        except _Rejected as error:
            response = JSONResponse({"error": {"code": error.code}}, status_code=401 if error.code == "CAPABILITY_DENIED" else 409)
        except asyncio.CancelledError:
            raise
        except Exception:
            response = JSONResponse({"error": {"code": "BROKER_REQUEST_INVALID"}}, status_code=400)
        await response(scope, receive, send)

    def _request(self, raw: bytes):
        body = _json(raw)
        if not isinstance(body, dict) or set(body) - {"model", "messages", "tools", "tool_choice", "stream",
                "stream_options", "max_tokens", "max_completion_tokens", "temperature", "top_p", "n",
                "parallel_tool_calls", "stop"}:
            raise _Rejected("REQUEST_CONTRACT")
        if body.get("model") != MODEL or not isinstance(body.get("messages"), list) or not body["messages"]:
            raise _Rejected("REQUEST_CONTRACT")
        if type(body.get("stream", False)) is not bool or body.get("n", 1) != 1 or type(body.get("n", 1)) is not int:
            raise _Rejected("REQUEST_CONTRACT")
        caps = [body[k] for k in ("max_tokens", "max_completion_tokens") if k in body]
        if len(caps) > 1 or any(type(v) is not int or not 1 <= v <= self._output_cap for v in caps):
            raise _Rejected("OUTPUT_BOUND")
        body.pop("max_completion_tokens", None)
        body["max_tokens"] = caps[0] if caps else self._output_cap
        body["parallel_tool_calls"] = False
        if body.get("stream"):
            body["stream_options"] = {"include_usage": True}
        elif "stream_options" in body:
            raise _Rejected("REQUEST_CONTRACT")
        if len(json.dumps(body, ensure_ascii=False).encode()) > self._input_bytes:
            raise _Rejected("INPUT_BOUND")
        return body

    async def _invoke(self, body):
        if self.stopped_reason is not None:
            raise _Rejected("STOPPED")
        if self.requests >= self._max_requests:
            raise _Rejected("REQUEST_LIMIT")
        ticket = None
        reserved = False
        settled = False
        reason = "UNKNOWN"
        diagnostic: dict[str, Any] = {"ordinal": self.requests + 1, "phase": None, "operation": "authority"}
        self._diagnostics.append(diagnostic)
        try:
            if await self._authority() is not True:
                raise _Rejected("AUTHORITY_DENIED")
            input_bound = len(json.dumps(body, ensure_ascii=False).encode()) + 512 * (1 + len(body["messages"]) + len(body.get("tools", [])))
            diagnostic["operation"] = "reserve"
            ticket = await self._reserve(self.requests + 1, input_bound, body["max_tokens"],
                                         _json(json.dumps(body).encode()))
            reserved = True
            diagnostic.update(phase="reserved", operation="authority")
            # Counts before credential/dispatch: unknown attempts cannot be replayed.
            self.requests += 1
            if await self._authority() is not True:
                raise _Rejected("AUTHORITY_DENIED")
            diagnostic["operation"] = "credential"
            secret = self._credential()
            if not isinstance(secret, str) or not secret or any(ord(c) < 33 or ord(c) > 126 for c in secret):
                raise _Rejected("CREDENTIAL_UNAVAILABLE")
            headers = {"Authorization": "Bearer " + secret, "User-Agent": USER_AGENT,
                       "x-opencode-session": self._session, "Accept-Encoding": "identity"}
            del secret
            streaming = body.get("stream", False)
            state = _Stream(False, expected_model=MODEL) if streaming else None
            data = bytearray()
            async with open_go_client(timeout=60, transport=self._transport) as client:
                diagnostic.update(phase="dispatch", operation="transport")
                async with client.stream("POST", _URL, headers=headers, json=body) as response:
                    diagnostic["phase"] = "headers"
                    if response.status_code != 200:
                        raise _Rejected("AUTH" if response.status_code in {401, 403} else
                                        "QUOTA" if response.status_code in {402, 429} else "HTTP_REJECTED")
                    async for part in response.aiter_bytes():
                        diagnostic.update(phase="stream", operation="authority")
                        if await self._authority() is not True:
                            raise _Rejected("AUTHORITY_DENIED")
                        data.extend(part)
                        if len(data) > self._output_bytes:
                            raise _Rejected("OUTPUT_BOUND")
                        if state is not None:
                            diagnostic["operation"] = "parse"
                            state.feed(part)
                        diagnostic["operation"] = "transport"
                    diagnostic.update(phase="eof", operation="parse")
                    payload = state.finish() if state is not None else _json(bytes(data))
                    if payload.get("model") != MODEL:
                        raise _Rejected("MODEL_MISMATCH")
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or len(choices) != 1 or choices[0].get("finish_reason") not in {"stop", "tool_calls"}:
                        raise _Rejected("PROTOCOL")
                    message = choices[0]["message"]
                    if message.get("content") is not None and not isinstance(message["content"], str):
                        raise _Rejected("PROTOCOL")
                    calls = [_call(call) for call in message.get("tool_calls", [])]
                    if len({call["id"] for call in calls}) != len(calls):
                        raise _Rejected("PROTOCOL")
                    usage = go_response_usage(ModelResponse(response_usage=_usage(payload.get("usage"), False)))
                    if usage is None:
                        raise _Rejected("USAGE_UNKNOWN")
                    # Verified EOF counters remain authoritative even on overrun or revocation.
                    diagnostic.update(phase="parsed", operation="settle")
                    await self._settle(ticket, usage)
                    settled = True
                    diagnostic["phase"] = "settled"
                    if usage.input_tokens > input_bound or usage.output_tokens > body["max_tokens"]:
                        raise _Rejected("USAGE_BOUND")
                    diagnostic["operation"] = "transport"
            diagnostic["operation"] = "authority"
            if await self._authority() is not True:
                raise _Rejected("AUTHORITY_DENIED")
            return _BufferedResponse(bytes(data), media_type="text/event-stream" if streaming else "application/json", diagnostic=diagnostic)
        except BaseException as error:
            diagnostic["error"] = _safe_error(error)
            if isinstance(error, _Rejected):
                reason = error.code
            self.stopped_reason = reason
            if reserved and not settled:
                try:
                    await self._hold(ticket, reason)
                except Exception as hold_error:
                    diagnostic["holdError"] = _safe_error(hold_error)
                    # The existing reservation remains held if persistence fails.
                    self.stopped_reason = "ACCOUNTING_UNAVAILABLE"
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            raise _Rejected(self.stopped_reason) from None

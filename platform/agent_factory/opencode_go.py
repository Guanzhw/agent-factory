"""Opt-in, development-only Go transport. No environment or credential discovery.

Unregistered by default. A trusted operator must supply a billing verifier which
rejects balance fallback; no public request-level subscription-only flag is known.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx
from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse

BASE_URL = "https://opencode.ai/zen/go/v1"
USER_AGENT = "agent-factory-dev/0.1 (+https://github.com/Guanzhw/agent-factory)"
MODELS = {"deepseek-v4-flash": "chat/completions", "deepseek-v4.1-flash": "chat/completions",
          "gpt-6-luna": "responses"}
MAX_BYTES = 1_048_576


class _LoopbackResponseStream(httpx.AsyncByteStream):
    def __init__(self, response, transport):
        self.response, self.transport = response, transport

    async def __aiter__(self):
        async for chunk in self.response.aiter_raw():
            yield chunk

    async def aclose(self):
        try:
            await self.response.aclose()
        finally:
            await self.transport.aclose()


class GoLoopbackTransport(httpx.AsyncBaseTransport):
    """Explicit synthetic wire fixture, incapable of routing to the Go host.

    Only literal loopback HTTP origins are accepted, with no proxy, redirect,
    credentials, or hidden HTTP retry. Authorization is never forwarded.
    """

    def __init__(self, base_url: str):
        url = httpx.URL(base_url)
        if (url.scheme != "http" or url.host not in {"127.0.0.1", "::1"} or url.port is None
                or not 1 <= url.port <= 65535 or url.userinfo or url.query or url.fragment
                or url.path not in {"", "/"}):
            raise ValueError("Go fixture requires an explicit literal loopback HTTP origin")
        self._origin = url

    async def handle_async_request(self, request):
        if (request.method != "POST" or str(request.url) not in {BASE_URL + "/chat/completions", BASE_URL + "/responses"}
                or request.headers.get("user-agent") != USER_AGENT
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request.headers.get("x-opencode-session", ""))):
            raise ValueError("Go fixture request differs from the reviewed wire contract")
        transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        try:
            forwarded = httpx.Request("POST", self._origin.copy_with(path=request.url.path),
                content=await request.aread(), headers={"content-type": "application/json",
                    "user-agent": USER_AGENT, "x-opencode-session": request.headers["x-opencode-session"]},
                extensions=request.extensions)
            response = await transport.handle_async_request(forwarded)
            return httpx.Response(response.status_code, headers=response.headers,
                stream=_LoopbackResponseStream(response, transport), request=request)
        except BaseException:
            await transport.aclose()
            raise


def _unknown(message="Go protocol response is invalid", status=400):
    # Never interpolate server bodies, request headers, credentials or SDK errors.
    return ModelProviderError(message=message, status_code=status, model_name="OpenCode Go development")


def _usage(value, responses):
    if not isinstance(value, dict):
        return None
    incoming = value.get("input_tokens" if responses else "prompt_tokens")
    outgoing = value.get("output_tokens" if responses else "completion_tokens")
    total = value.get("total_tokens")
    if (type(incoming) is not int or type(outgoing) is not int or type(total) is not int
            or min(incoming, outgoing) < 0 or total != incoming + outgoing):
        return None
    return MessageMetrics(input_tokens=incoming, output_tokens=outgoing, total_tokens=total)


def _call(value):
    if (not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]
            or value.get("type") != "function" or not isinstance(value.get("function"), dict)):
        raise _unknown()
    function = value["function"]
    if (not isinstance(function.get("name"), str) or not function["name"]
            or not isinstance(function.get("arguments"), str)):
        raise _unknown()
    try:
        arguments = json.loads(function["arguments"])
    except (ValueError, TypeError):
        raise _unknown() from None
    if not isinstance(arguments, dict):
        raise _unknown()
    return value


class GoDevelopmentModel(Model):
    """Native Agno model with bounded single HTTP invocation, never a tool loop.

    billing_verified(session_id, exact_model_id) must independently verify current
    subscription-only authorization on EVERY invocation. It is not a user prompt
    flag. Default denies before credential access. Mock transports are test-only.
    """

    def __init__(self, *, model_id: str, session_id: str, credential: Callable[[], str],
                 billing_verified: Callable[[str, str], bool] | None = None,
                 max_output_tokens: int = 256, timeout_seconds: float = 30,
                 wire_stream: bool = False, native_retries: int = 0,
                 transport: httpx.BaseTransport | None = None,
                 async_transport: httpx.AsyncBaseTransport | None = None):
        if model_id not in MODELS:
            raise ValueError("Unsupported exact Go model; aliases require a separately verified contract")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("A stable opaque native conversation identity is required")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 512:
            raise ValueError("Development output budget must be 1..512 tokens")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("Development timeout must be at most 60 seconds")
        if type(wire_stream) is not bool or type(native_retries) is not int or not 0 <= native_retries <= 1:
            raise ValueError("Development wire mode/retry limit is invalid")
        if native_retries and transport is None and async_transport is None:
            raise ValueError("Native retry verification is restricted to an explicit fixture transport")
        super().__init__(id=model_id, name="OpenCode Go development", provider="opencode-go-development",
                         retries=native_retries)
        self.factory_wire_stream = wire_stream
        self._native_retry_limit = native_retries
        self._session = session_id
        self._credential = credential
        self._billing = billing_verified
        self._cap = max_output_tokens
        self._timeout = timeout_seconds
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise ValueError("Test transport must support asynchronous deadline cancellation")
        self._async_transport = async_transport or transport

    def _is_retryable_error(self, error: ModelProviderError) -> bool:
        # Only explicit fixture retries may retry a transient service failure.
        # Quota/auth, incomplete protocol and unknown usage always stop.
        return error.status_code == 503

    def _headers(self):
        try:
            allowed = self._billing is not None and self._billing(self._session, self.id) is True
        except Exception:
            allowed = False
        if not allowed:
            raise _unknown("GO_SUBSCRIPTION_ONLY_UNVERIFIED")
        try:
            secret = self._credential()
        except Exception:
            raise _unknown("GO_CREDENTIAL_UNAVAILABLE") from None
        if not isinstance(secret, str) or not secret or any(c.isspace() for c in secret):
            raise _unknown("GO_CREDENTIAL_UNAVAILABLE")
        return {"Authorization": "Bearer " + secret, "User-Agent": USER_AGENT,
                "x-opencode-session": self._session}

    def _body(self, messages, *, stream=False, tools=None, tool_choice=None, response_format=None, **kwargs):
        if response_format is not None:
            raise ValueError("Structured output contract is not verified for Go")
        responses = MODELS[self.id] == "responses"
        encoded = []
        for message in messages:
            if (message.role not in {"system", "user", "assistant", "tool"}
                    or message.content is not None and not isinstance(message.content, str)
                    or any(getattr(message, field, None) for field in ("images", "videos", "audio", "files"))):
                raise ValueError("Only text and function-tool messages are supported")
            if responses:
                if message.role == "tool":
                    encoded.append({"type": "function_call_output", "call_id": message.tool_call_id,
                                    "output": message.content or ""})
                else:
                    if message.content:
                        encoded.append({"role": message.role, "content": message.content})
                    for call in message.tool_calls or []:
                        call = _call(call)
                        encoded.append({"type": "function_call", "call_id": call["id"], **call["function"]})
            else:
                item = {"role": message.role, "content": message.content}
                if message.role == "tool":
                    item["tool_call_id"] = message.tool_call_id
                if message.tool_calls:
                    item["tool_calls"] = [_call(call) for call in message.tool_calls]
                encoded.append(item)
        body = {"model": self.id, "stream": stream,
                "input" if responses else "messages": encoded,
                "max_output_tokens" if responses else "max_tokens": self._cap}
        if responses:
            body["store"] = False
        elif stream:
            body["stream_options"] = {"include_usage": True}
        if tools:
            if any(tool.get("type") != "function" or not isinstance(tool.get("function"), dict) for tool in tools):
                raise ValueError("Only approved function tools are supported")
            body["tools"] = [{"type": "function", **tool["function"]} for tool in tools] if responses else tools
            body["parallel_tool_calls"] = False
        if tool_choice is not None:
            if tool_choice not in ("none", "auto", "required"):
                raise ValueError("Named tool-choice contract is not verified")
            body["tool_choice"] = tool_choice
        if len(json.dumps(body).encode()) > MAX_BYTES:
            raise ValueError("Development request exceeds size bound")
        return body

    def _parse_provider_response(self, response, **kwargs):
        try:
            responses = MODELS[self.id] == "responses"
            if responses:
                if response.get("status") != "completed":
                    raise _unknown("Go response did not complete")
                content, calls = [], []
                for item in response["output"]:
                    if item["type"] == "message":
                        for part in item["content"]:
                            if part["type"] == "output_text":
                                content.append(part["text"])
                    elif item["type"] == "function_call":
                        calls.append(_call({"id": item["call_id"], "type": "function", "function": {
                            "name": item["name"], "arguments": item["arguments"]}}))
                result = ModelResponse(role="assistant", content="".join(content) or None, tool_calls=calls)
            else:
                if not isinstance(response["choices"], list) or len(response["choices"]) != 1:
                    raise _unknown("Unexpected multiple or missing choices")
                choice = response["choices"][0]
                if choice.get("finish_reason") not in {"stop", "tool_calls"}:
                    raise _unknown("Go response did not complete")
                message = choice["message"]
                if message.get("content") is not None and not isinstance(message["content"], str):
                    raise _unknown()
                result = ModelResponse(role="assistant", content=message.get("content"),
                                       tool_calls=[_call(call) for call in message.get("tool_calls", [])])
            calls = result.tool_calls or []
            if len({call["id"] for call in calls}) != len(calls):
                raise _unknown("Go response contains duplicate tool identities")
            result.response_usage = _usage(response.get("usage"), responses)
            if result.response_usage is None:
                raise _unknown("GO_USAGE_UNKNOWN")
            return result
        except (KeyError, TypeError, IndexError, AttributeError):
            raise _unknown() from None

    def _parse_provider_response_delta(self, response):
        return response

    def _check(self, response, started):
        if time.monotonic() - started > self._timeout:
            raise _unknown("Go request deadline exceeded", 408)
        if response.status_code != 200:
            raise _unknown("Go request rejected", response.status_code)

    def invoke(self, messages, **kwargs):
        # Public methods are separately wrapped by the Factory usage ledger.
        # Never bridge through another public method: that reserves twice.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(self._ainvoke_http(messages, stream=self.factory_wire_stream, **kwargs))).result()

    async def ainvoke(self, messages, **kwargs):
        return await self._ainvoke_http(messages, stream=self.factory_wire_stream, **kwargs)

    def invoke_stream(self, messages, **kwargs):
        # Bounded buffering deliberately avoids executing partial tool arguments.
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(lambda: asyncio.run(self._ainvoke_http(messages, stream=True, **kwargs))).result()
        yield result

    async def ainvoke_stream(self, messages, **kwargs):
        yield await self._ainvoke_http(messages, stream=True, **kwargs)

    async def _ainvoke_http(self, messages, *, stream=False, **kwargs):
        body = self._body(messages, stream=stream, **kwargs)
        headers = self._headers()
        started = time.monotonic()
        state = _Stream(MODELS[self.id] == "responses") if stream else None
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(timeout=self._timeout, trust_env=False, follow_redirects=False,
                                            transport=self._async_transport) as client:
                    async with client.stream("POST", BASE_URL + "/" + MODELS[self.id], headers=headers, json=body) as response:
                        self._check(response, started)
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if state is not None:
                                state.feed(chunk)
                            else:
                                data.extend(chunk)
                                if len(data) > MAX_BYTES:
                                    raise _unknown("Go response exceeds size bound")
                        payload = state.finish() if state is not None else json.loads(data)
                        return self._parse_provider_response(payload)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, TimeoutError):
            raise _unknown("Go transport or JSON failure") from None


class _Stream:
    def __init__(self, responses):
        self.responses = responses
        self.buffer = b""
        self.size = 0
        self.done = False
        self.result = None
        self.content = ""
        self.calls = {}
        self.usage = None
        self.reason = None

    def feed(self, chunk):
        self.size += len(chunk)
        if self.size > MAX_BYTES:
            raise _unknown("Go stream exceeds size bound")
        self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                self.done = True
                continue
            if self.done:
                raise _unknown("Go stream contains data after completion")
            value = json.loads(payload)
            if self.responses:
                kind = value.get("type", "")
                if kind in {"error", "response.failed", "response.incomplete"}:
                    raise _unknown("Go stream failed")
                if kind == "response.completed":
                    self.result = value["response"]
                    self.done = True
                # Responses completed contains authoritative full text/tools/usage.
            else:
                if "error" in value:
                    raise _unknown("Go stream failed")
                choices = value.get("choices", [])
                if not isinstance(choices, list) or len(choices) > 1:
                    raise _unknown("Unexpected multiple choices")
                for choice in choices:
                    if choice.get("index", 0) != 0:
                        raise _unknown("Unexpected multiple choices")
                    if self.reason is not None:
                        raise _unknown("Go stream contains a choice after its terminal event")
                    delta = choice.get("delta", {})
                    self.content += delta.get("content") or ""
                    for tool in delta.get("tool_calls", []):
                        index = tool["index"]
                        if type(index) is not int or index < 0:
                            raise _unknown("Invalid streamed tool index")
                        if tool.get("type", "function") != "function":
                            raise _unknown("Unsupported streamed tool type")
                        call = self.calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        call["id"] += tool.get("id", "")
                        for key in ("name", "arguments"):
                            call["function"][key] += tool.get("function", {}).get(key, "")
                    if choice.get("finish_reason"):
                        self.reason = choice["finish_reason"]
                if value.get("usage") is not None:
                    if self.reason is None:
                        raise _unknown("Go stream contains usage before its terminal choice")
                    if self.usage is not None:
                        raise _unknown("Go stream contains repeated usage")
                    self.usage = value["usage"]

    def finish(self):
        if self.buffer.strip() or not self.done:
            raise _unknown("Go stream ended without a complete terminal event")
        if self.responses:
            if self.result is None:
                raise _unknown()
            return self.result
        return {"choices": [{"finish_reason": self.reason, "message": {
            "content": self.content or None, "tool_calls": list(self.calls.values())}}], "usage": self.usage}

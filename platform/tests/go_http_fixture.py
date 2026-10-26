"""Controlled loopback HTTP peer; never contacts OpenCode or reads credentials."""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from typing import Any

import httpx

from agent_factory.opencode_go import BASE_URL, USER_AGENT


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


class GoHTTPFixture:
    """Scripted chat/responses tool round trips over an actual local socket.

    Authorization headers are deliberately neither forwarded nor retained.
    Blocking the first response permits deterministic current-authority tests.
    """
    def __init__(self, scenario="success", *, block=False):
        self.scenario = scenario
        self.requests = []
        self.lock = Lock()
        self.entered, self.release = Event(), Event()
        self.tool_delta_sent = Event()
        self.block_after_tool_delta = False
        if not block:
            self.release.set()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with fixture.lock:
                    fixture.requests.append({"path": self.path, "body": body,
                        "session": self.headers["x-opencode-session"],
                        "hasAuthorization": "Authorization" in self.headers})
                    attempt = len(fixture.requests)
                fixture.entered.set()
                if not fixture.block_after_tool_delta and not fixture.release.wait(20):
                    self.send_error(504)
                    return
                status, content_type, payload = fixture.reply(body, attempt)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    if fixture.block_after_tool_delta:
                        first, rest = payload.split(b"\n\n", 1)
                        self.wfile.write(first + b"\n\n")
                        self.wfile.flush()
                        fixture.tool_delta_sent.set()
                        if not fixture.release.wait(20):
                            return
                        payload = rest
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.transport = GoLoopbackTransport(self.url)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def reply(self, body, attempt):
        if self.scenario in {"quota", "always503"} or self.scenario == "retry" and attempt == 1:
            return (429 if self.scenario == "quota" else 503,
                    "application/json", b'{"error":{"message":"synthetic rejection"}}')
        responses = body["model"] == "gpt-6-luna"
        messages = body["input" if responses else "messages"]
        returned = any(item.get("type") == "function_call_output" or item.get("role") == "tool"
                       for item in messages)
        call = {"id": "fixture_checksum_call", "type": "function",
                "function": {"name": "checksum", "arguments": '{"text":"synthetic Go development"}'}}
        usage = ({"input_tokens": 11, "output_tokens": 7, "total_tokens": 18} if responses
                 else {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
        if responses:
            output = ([{"type": "message", "content": [{"type": "output_text", "text": "Checksum verified."}]}]
                      if returned else [{"type": "function_call", "call_id": call["id"], **call["function"]}])
            result = {"status": "completed", "output": output, "usage": usage}
        else:
            message = ({"content": "Checksum verified."} if returned else {"content": None, "tool_calls": [call]})
            result = {"choices": [{"finish_reason": "stop" if returned else "tool_calls", "message": message}], "usage": usage}
        if self.scenario == "unknown_usage":
            result.pop("usage")
        if not body.get("stream"):
            return 200, "application/json", json.dumps(result).encode()
        events: list[dict[str, Any]]
        if responses:
            events = [{"type": "response.created", "response": {"status": "in_progress"}},
                      {"type": "response.completed", "response": result}]
        else:
            delta = ({"content": "Checksum verified."} if returned else
                     {"tool_calls": [{"index": 0, **call}]})
            events = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if returned else "tool_calls"}]}]
            if "usage" in result:
                events.append({"choices": [], "usage": usage})
        if self.scenario == "partial_stream":
            events = events[:1]
        payload = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
        if not responses and self.scenario != "partial_stream":
            payload += b"data: [DONE]\n\n"
        return 200, "text/event-stream", payload

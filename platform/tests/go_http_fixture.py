"""Controlled loopback HTTP peer; never contacts OpenCode or reads credentials."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from typing import Any

from agent_factory.opencode_go import GoLoopbackTransport


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
                        "session": self.headers["x-opencode-session"]})
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

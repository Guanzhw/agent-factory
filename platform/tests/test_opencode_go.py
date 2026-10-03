"""Offline only; no credentials or environment access, network replaced by MockTransport."""
import asyncio
import json
import unittest

import httpx
from agno.exceptions import ModelProviderError
from agno.models.message import Message

from agent_factory.opencode_go import GoDevelopmentModel, USER_AGENT, MAX_BYTES
from agent_factory.usage_ledger import native_response_usage


def chat(**updates):
    return {"choices": [{"finish_reason": "stop", "message": {"content": "synthetic"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}, **updates}


def responses(**updates):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "synthetic"}]}],
            "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}, **updates}


class GoContractTests(unittest.TestCase):
    def model(self, handler=None, model_id="deepseek-v4-flash", **kwargs):
        transport = httpx.MockTransport(handler or (lambda request: httpx.Response(200, json=chat())))
        return GoDevelopmentModel(model_id=model_id, session_id="synthetic-session-1", credential=lambda: "synthetic-opaque",
                                  billing_verified=lambda *_: True, transport=transport, async_transport=transport, **kwargs)

    def invoke(self, model):
        return model.invoke([Message(role="user", content="Explain this synthetic test.")])

    def test_billing_denied_before_credential_or_transport(self):
        def forbidden(*_):
            self.fail("No credential/network access allowed")
        model = GoDevelopmentModel(model_id="gpt-6-luna", session_id="synthetic-session", credential=forbidden,
                                   transport=httpx.MockTransport(forbidden))
        with self.assertRaisesRegex(ModelProviderError, "GO_SUBSCRIPTION_ONLY_UNVERIFIED"):
            self.invoke(model)

    def test_exact_models_and_limits(self):
        for model_id in ("deepseek-unknown", "gpt-6", "https://other.invalid"):
            with self.assertRaises(ValueError):
                self.model(model_id=model_id)
        for kwargs in ({"timeout_seconds": 61}, {"max_output_tokens": 513}, {"max_output_tokens": True}):
            with self.assertRaises(ValueError):
                self.model(**kwargs)  # pyright: ignore[reportArgumentType]

    def test_chat_headers_body_usage_and_session(self):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(str(request.url), "https://opencode.ai/zen/go/v1/chat/completions")
            self.assertEqual(request.headers["user-agent"], USER_AGENT)
            self.assertEqual(request.headers["x-opencode-session"], "synthetic-session-1")
            body = json.loads(request.content)
            self.assertEqual(body["max_tokens"], 256)
            self.assertFalse(body["stream"])
            return httpx.Response(200, json=chat())
        model = self.model(handler)
        for _ in range(2):
            result = self.invoke(model)
            self.assertEqual(result.content, "synthetic")
            evidence = native_response_usage(result)
            assert evidence is not None
            self.assertEqual(evidence.input_tokens, 4)
        self.assertEqual(len(calls), 2)

    def test_responses_tool_round_trip(self):
        def handler(request):
            self.assertTrue(str(request.url).endswith("/responses"))
            body = json.loads(request.content)
            self.assertFalse(body["store"])
            self.assertEqual(body["max_output_tokens"], 256)
            self.assertEqual(body["input"][0]["call_id"], "call-1")
            self.assertEqual(body["input"][1]["type"], "function_call_output")
            self.assertEqual(body["tools"][0]["name"], "inspect")
            return httpx.Response(200, json=responses(output=[{"type": "function_call", "call_id": "call-2", "name": "inspect", "arguments": "{}"}]))
        result = self.model(handler, "gpt-6-luna").invoke([
            Message(role="assistant", tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}]),
            Message(role="tool", tool_call_id="call-1", content="synthetic")],
            tools=[{"type": "function", "function": {"name": "inspect", "parameters": {"type": "object"}}}])
        self.assertEqual(result.tool_calls[0]["id"], "call-2")
        evidence = native_response_usage(result)
        assert evidence is not None
        self.assertEqual(evidence.output_tokens, 2)

    def test_errors_no_retry_no_server_body(self):
        for status in (302, 401, 402, 429, 503):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, headers={"location": "https://other.invalid"}, text="sensitive-response")
            with self.assertRaises(ModelProviderError) as caught:
                self.invoke(self.model(handler))
            self.assertEqual(caught.exception.status_code, status)
            self.assertNotIn("sensitive-response", str(caught.exception))
            self.assertEqual(len(calls), 1)

    def test_native_retries_never_repeat_quota_auth_or_unknown_usage(self):
        from agno.agent import Agent
        for status in (401, 402, 403, 429, None):
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(status, text="synthetic rejection") if status else httpx.Response(200, json=chat(usage=None))
            model = self.model(handler, native_retries=1)
            result = Agent(model=model, telemetry=False).run("Synthetic coding test")
            self.assertEqual(result.status.value, "ERROR")
            self.assertEqual(len(requests), 1)

    def test_loopback_transport_rejects_nonliteral_or_credentialed_targets(self):
        from agent_factory.opencode_go import GoLoopbackTransport
        for target in ("https://opencode.ai", "http://localhost:8000", "http://example.invalid:8000",
                       "http://127.0.0.1:8000/path", "http://user:pass@127.0.0.1:8000",
                       "http://127.0.0.1:8000/?query=1"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                GoLoopbackTransport(target)
        GoLoopbackTransport("http://127.0.0.1:8000")
        GoLoopbackTransport("http://[::1]:8000")

    def test_missing_invalid_usage_unknown(self):
        for usage in (None, {}, {"prompt_tokens": True, "completion_tokens": 0, "total_tokens": 1},
                      {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 99}):
            with self.assertRaisesRegex(ModelProviderError, "GO_USAGE_UNKNOWN") as denied:
                self.invoke(self.model(lambda request: httpx.Response(200, json=chat(usage=usage))))
            self.assertIsNone(native_response_usage(denied.exception))

    def test_partial_response_fails_closed(self):
        for model_id, payload in (("gpt-6-luna", responses(status="incomplete")),
                                  ("deepseek-v4-flash", chat(choices=[{"finish_reason": "length", "message": {"content": "partial"}}]))):
            with self.assertRaises(ModelProviderError):
                self.invoke(self.model(lambda request: httpx.Response(200, json=payload), model_id))

    def stream_model(self, events, model_id="deepseek-v4-flash", done=True):
        content = "".join("data: " + json.dumps(event) + "\r\n\r\n" for event in events)
        if done:
            content += "data: [DONE]\n\n"
        return self.model(lambda request: httpx.Response(200, content=content, headers={"content-type": "text/event-stream"}), model_id)

    def test_chat_stream_split_tool_and_usage(self):
        model = self.stream_model([
            {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "inspect", "arguments": "{"}}]}}]},
            {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}])
        values = list(model.invoke_stream([Message(role="user", content="synthetic")]))
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].tool_calls[0]["function"]["arguments"], "{}")
        self.assertIsNotNone(native_response_usage(values[0]))

    def test_responses_stream_completed_authoritative(self):
        model = self.stream_model([{"type": "response.output_text.delta", "delta": "synthetic"},
                                   {"type": "response.completed", "response": responses()}], "gpt-6-luna", done=False)
        value = list(model.invoke_stream([Message(role="user", content="synthetic")]))[0]
        self.assertEqual(value.content, "synthetic")
        self.assertIsNotNone(native_response_usage(value))

    def test_stream_truncation_yields_no_usage_or_tools(self):
        model = self.stream_model([{"choices": [{"delta": {"content": "partial"}}]}], done=False)
        with self.assertRaises(ModelProviderError):
            list(model.invoke_stream([Message(role="user", content="synthetic")]))

    def test_response_size_bound(self):
        with self.assertRaises(ModelProviderError):
            self.invoke(self.model(lambda request: httpx.Response(200, content=b"x" * (MAX_BYTES + 1))))

    def test_async_invoke_and_stream(self):
        async def exercise():
            result = await self.model().ainvoke([Message(role="user", content="synthetic")])
            self.assertEqual(result.content, "synthetic")
            model = self.stream_model([{"type": "response.completed", "response": responses()}], "gpt-6-luna", done=False)
            values = [item async for item in model.ainvoke_stream([Message(role="user", content="synthetic")])]
            self.assertEqual(values[0].content, "synthetic")
        asyncio.run(exercise())

    def test_native_agno_response(self):
        from agno.agent import Agent
        result = Agent(model=self.model(), telemetry=False).run("Synthetic coding test")
        self.assertEqual(result.content, "synthetic")

    def test_native_agno_stream(self):
        from agno.agent import Agent
        model = self.stream_model([{"choices": [{"delta": {"content": "synthetic"}, "finish_reason": "stop"}]},
                                   {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}])
        events = list(Agent(model=model, telemetry=False).run("Synthetic coding test", stream=True))
        self.assertEqual("".join(event.content or "" for event in events), "synthetic")

    def test_total_deadline_cancels_slow_mock_once(self):
        calls = []
        cancelled = []
        async def slow(request):
            calls.append(request)
            try:
                await asyncio.sleep(1)
            finally:
                cancelled.append(True)
            return httpx.Response(200, json=chat())
        with self.assertRaises(ModelProviderError):
            self.invoke(self.model(slow, timeout_seconds=0.01))
        self.assertEqual(len(calls), 1)
        self.assertEqual(cancelled, [True])

    def test_secret_callback_error_redacted(self):
        def secret():
            raise RuntimeError("synthetic-sensitive-text")
        model = GoDevelopmentModel(model_id="gpt-6-luna", session_id="synthetic-session", credential=secret,
                                   billing_verified=lambda *_: True)
        with self.assertRaises(ModelProviderError) as caught:
            self.invoke(model)
        self.assertNotIn("synthetic-sensitive-text", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_truncated_tool_json_never_executes(self):
        model = self.stream_model([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1",
            "function": {"name": "inspect", "arguments": "{"}}]}, "finish_reason": "tool_calls"}]}])
        with self.assertRaises(ModelProviderError):
            list(model.invoke_stream([Message(role="user", content="synthetic")]))

    def test_chat_stream_terminal_cannot_be_rewritten(self):
        for first_reason in ("length", "stop", "tool_calls"):
            model = self.stream_model([
                {"choices": [{"delta": {"content": "partial"}, "finish_reason": first_reason}]},
                {"choices": [{"delta": {"content": "late"}, "finish_reason": "stop"}]}])
            with self.subTest(first_reason=first_reason), self.assertRaises(ModelProviderError):
                list(model.invoke_stream([Message(role="user", content="synthetic")]))

    def test_stream_usage_requires_terminal_choice_before_or_in_same_event(self):
        usage = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
        terminal = {"choices": [{"delta": {"content": "synthetic"}, "finish_reason": "stop"}]}
        for events in (
            [{"usage": usage}, terminal],
            [{"choices": [{"delta": {"content": "partial"}}], "usage": usage}, terminal],
            [{**terminal, "usage": usage}, {"choices": [{"delta": {"content": "late"}}]}],
        ):
            with self.subTest(events=events), self.assertRaises(ModelProviderError):
                list(self.stream_model(events).invoke_stream([Message(role="user", content="synthetic")]))
        for events in ([{**terminal, "usage": usage}], [terminal, {"usage": usage}]):
            result = list(self.stream_model(events).invoke_stream([Message(role="user", content="synthetic")]))
            evidence = native_response_usage(result[0])
            assert evidence is not None
            self.assertEqual(evidence.output_tokens, 2)

    def test_chat_rejects_ambiguous_choices_and_content(self):
        choice = {"finish_reason": "stop", "message": {"content": "synthetic"}}
        for payload in (chat(choices=[choice, choice]), chat(choices=[]),
                        chat(choices=[{"finish_reason": "stop", "message": {"content": {"unexpected": True}}}])):
            with self.subTest(payload=payload), self.assertRaises(ModelProviderError):
                self.invoke(self.model(lambda request: httpx.Response(200, json=payload)))

    def test_duplicate_tool_identities_rejected_in_both_protocols(self):
        call = {"id": "call-1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}
        item = {"type": "function_call", "call_id": "call-1", "name": "inspect", "arguments": "{}"}
        for model_id, payload in (
            ("deepseek-v4-flash", chat(choices=[{"finish_reason": "tool_calls", "message": {"tool_calls": [call, call]}}])),
            ("gpt-6-luna", responses(output=[item, item])),
        ):
            with self.subTest(model_id=model_id), self.assertRaises(ModelProviderError):
                self.invoke(self.model(lambda request: httpx.Response(200, json=payload), model_id))

    def test_stream_rejects_ambiguous_usage_choices_and_tool_indexes(self):
        usage = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
        choice = {"delta": {"content": "synthetic"}}
        cases = [
            [{"choices": [choice, choice]}],
            [{"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage}, {"usage": usage}],
        ]
        for index in (True, -1, "0", []):
            cases.append([{"choices": [{"delta": {"tool_calls": [{"index": index,
                "id": "call-1", "function": {"name": "inspect", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}])
        for events in cases:
            with self.subTest(events=events), self.assertRaises(ModelProviderError):
                list(self.stream_model(events).invoke_stream([Message(role="user", content="synthetic")]))

    def test_cancelled_async_transport_settles_unknown_once(self):
        from agent_factory.model_dispatch import DelegatingModel

        async def exercise(streaming):
            entered = asyncio.Event()
            requests, reservations, settlements, closed = [], [], [], []

            class Body(httpx.AsyncByteStream):
                async def __aiter__(self):
                    # Neither an incomplete JSON body nor partial SSE may settle usage.
                    yield b'data: {"choices": [{"delta": {"content": "partial"}}]}\n\n' if streaming else b'{"choices": ['
                    entered.set()
                    await asyncio.Event().wait()

                async def aclose(self):
                    closed.append(True)

            class Ledger:
                def begin_attempt(self, *args, **kwargs):
                    reservations.append(True)
                    return "attempt-cancelled"

                def evidence_for(self, plan, value):
                    return native_response_usage(value)

                def finish_attempt(self, identity, evidence):
                    settlements.append((identity, evidence))

            def handler(request):
                requests.append(request)
                return httpx.Response(200, stream=Body())

            model = self.model(handler)
            DelegatingModel._guard_provider_calls(model, lambda: None, ledger=Ledger())

            async def run():
                messages = [Message(role="user", content="synthetic")]
                if streaming:
                    return [value async for value in model.ainvoke_stream(messages)]
                return await model.ainvoke(messages)

            task = asyncio.create_task(run())
            await asyncio.wait_for(entered.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(len(requests), 1)
            self.assertEqual(reservations, [True])
            self.assertEqual(settlements, [("attempt-cancelled", None)])
            self.assertEqual(closed, [True])

        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                asyncio.run(exercise(streaming))

    def test_dispatcher_guard_reserves_and_settles_once_per_public_method(self):
        from agent_factory.model_dispatch import DelegatingModel
        for method in ("invoke", "ainvoke", "invoke_stream", "ainvoke_stream"):
            for fail in (False, "http", "missing_usage", "timeout", "protocol", "early_stream_usage"):
                with self.subTest(method=method, fail=fail):
                    requests, reservations, settlements, authority = [], [], [], []

                    class Ledger:
                        def begin_attempt(self, context, plan, model, **kwargs):
                            reservations.append(kwargs)
                            return "attempt-1"

                        def evidence_for(self, plan, value):
                            return native_response_usage(value)

                        def finish_attempt(self, identity, evidence):
                            settlements.append((identity, evidence))

                    async def handler(request):
                        requests.append(request)
                        if fail == "timeout":
                            await asyncio.sleep(1)
                        if fail == "http":
                            return httpx.Response(503, text="synthetic failure")
                        usage = None if fail == "missing_usage" else {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
                        reason = "length" if fail == "protocol" else "stop"
                        if fail == "early_stream_usage":
                            events = [{"choices": [], "usage": usage},
                                      {"choices": [{"delta": {"content": "later output"}, "finish_reason": "stop"}]}]
                            content = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
                            # An unsolicited SSE body must also fail closed on JSON methods.
                            return httpx.Response(200, content=content)
                        if json.loads(request.content)["stream"]:
                            event = {"choices": [{"delta": {"content": "synthetic"}, "finish_reason": reason}], "usage": usage}
                            return httpx.Response(200, content="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n")
                        return httpx.Response(200, json=chat(usage=usage, choices=[{"finish_reason": reason, "message": {"content": "synthetic"}}]))

                    model = self.model(handler, timeout_seconds=0.01 if fail == "timeout" else 30)
                    DelegatingModel._guard_provider_calls(model, lambda: authority.append(True), ledger=Ledger())
                    messages = [Message(role="user", content="synthetic coding test")]

                    def run():
                        if method == "invoke":
                            return model.invoke(messages)
                        if method == "invoke_stream":
                            return list(model.invoke_stream(messages))
                        async def async_run():
                            if method == "ainvoke":
                                return await model.ainvoke(messages)
                            return [item async for item in model.ainvoke_stream(messages)]
                        return asyncio.run(async_run())

                    if fail in ("http", "missing_usage", "timeout", "protocol", "early_stream_usage"):
                        with self.assertRaises(ModelProviderError):
                            run()
                    else:
                        run()
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(len(reservations), 1)
                    self.assertEqual(len(settlements), 1)
                    self.assertEqual(settlements[0][0], "attempt-1")
                    self.assertEqual(reservations[0]["streaming"], method.endswith("stream"))
                    self.assertGreaterEqual(len(authority), 1)
                    if fail:
                        self.assertIsNone(settlements[0][1])
                    else:
                        self.assertEqual(settlements[0][1].input_tokens, 4)

# pyright: reportMissingImports=false
"""Mock-only adapter/campaign/accounting checks. Never discovers credentials."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
from agno.exceptions import ModelProviderError
from agno.models.message import Message

from agent_factory.go_live import GoLiveCampaign, GoLiveGateError, MODELS
from agent_factory.go_usage import go_response_usage
from agent_factory.model_dispatch import DelegatingModel
from agent_factory.opencode_go import GoCancelledWithUsage, GoDevelopmentModel, GoResponseRejected


def sse(model, *, actual=None, missing_usage=False, output_tokens=3):
    actual = actual or model
    if model == MODELS[1]:
        response = {"status": "completed", "model": actual,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Synthetic coding response."}]}]}
        if not missing_usage:
            response["usage"] = {"input_tokens": 12, "output_tokens": output_tokens, "total_tokens": 12 + output_tokens}
        events = [{"type": "response.completed", "response": response}]
    else:
        events = [{"model": actual, "choices": [{"index": 0, "delta": {"content": "Synthetic coding response."}, "finish_reason": "stop"}]}]
        if not missing_usage:
            events.append({"model": actual, "choices": [], "usage": {
                "prompt_tokens": 12, "completion_tokens": output_tokens, "total_tokens": 12 + output_tokens}})
    result = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
    return result + (b"data: [DONE]\n\n" if model == MODELS[0] else b"")


@unittest.skipUnless(os.name == "posix", "Live campaign requires private POSIX file permissions")
class GoLiveTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def campaign(self):
        return GoLiveCampaign.create(Path(self.directory.name) / (str(uuid4()) + ".sqlite"),
            campaign_id="synthetic-campaign", owner_id="alice", confirmation_id="synthetic-confirmation",
            expires_at=time.time() + 3600)

    def complete_first_model_offline(self, gate):
        """Populate prerequisite tickets directly; no transport or live evidence."""
        model = MODELS[0]
        usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        for purpose, count in (("smoke", 1), ("product", 2)):
            session = "prior-" + purpose
            gate.authorize(session, model, purpose=purpose, owner_id="alice")
            for _ in range(count):
                body = {"model": model, "stream": True, "messages": [{"role": "user", "content": "synthetic"}],
                        "max_tokens": 16, "stream_options": {"include_usage": True}}
                ticket = gate.begin(session, model, body)
                gate.finish(ticket, usage=usage, actual_model=model)
        gate.complete_model(model, "a" * 64)

    def setup_model(self, model, handler):
        gate = self.campaign()
        if model == MODELS[1]:
            self.complete_first_model_offline(gate)
        session = "smoke-current"
        gate.authorize(session, model, owner_id="alice")

        def synthetic_credential():
            # Independent connection sees the committed reservation before the
            # adapter gets even its non-secret test credential.
            self.assertEqual(GoLiveCampaign(gate.path).inspect()["tickets"][-1]["state"], "INFLIGHT")
            return "synthetic-not-a-credential"

        credential = Mock(side_effect=synthetic_credential)
        transport = Mock(side_effect=handler)
        adapter = GoDevelopmentModel(model_id=model, session_id=session, credential=credential,
            live_campaign=gate, wire_stream=True, native_retries=0, timeout_seconds=60,
            async_transport=httpx.MockTransport(transport))
        return gate, adapter, credential, transport

    async def test_both_protocols_settle_exact_actual_model_and_usage(self):
        for model in MODELS:
            with self.subTest(model=model):
                def respond(request):
                    body = json.loads(request.content)
                    self.assertEqual(body["model"], model)
                    self.assertIs(body["stream"], True)
                    self.assertEqual(request.headers["x-opencode-session"], "smoke-current")
                    self.assertEqual(request.url.path, "/zen/go/v1/" + ("responses" if model == MODELS[1] else "chat/completions"))
                    return httpx.Response(200, content=sse(model))
                gate, adapter, credential, transport = self.setup_model(model, respond)
                result = await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
                evidence = go_response_usage(result)
                self.assertIsNotNone(evidence)
                self.assertEqual((evidence.input_tokens, evidence.output_tokens), (12, 3))  # type: ignore[union-attr]
                ticket = gate.inspect()["tickets"][-1]
                self.assertEqual((ticket["state"], ticket["actual_model"], ticket["total_tokens"]), ("SETTLED", model, 15))
                credential.assert_called_once_with()
                transport.assert_called_once()

    async def test_model_mismatch_stops_but_reader_preserves_incurred_usage(self):
        for model in MODELS:
            with self.subTest(model=model):
                gate, adapter, credential, transport = self.setup_model(model,
                    lambda _: httpx.Response(200, content=sse(model, actual="unapproved-model")))
                with self.assertRaises(GoResponseRejected) as raised:
                    await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
                evidence = go_response_usage(raised.exception)
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence.input_tokens, 12)  # type: ignore[union-attr]
                facts = gate.inspect()
                self.assertEqual(facts["status"], "STOPPED")
                self.assertEqual(facts["tickets"][-1]["state"], "SETTLED")
                self.assertIsNone(facts["tickets"][-1]["actual_model"])
                self.assertNotIn("unapproved-model", json.dumps(facts))
                credential.assert_called_once()
                transport.assert_called_once()

    async def test_auth_quota_unknown_usage_stop_globally_and_never_retry(self):
        for status, missing in ((401, False), (403, False), (429, False), (402, False), (200, True), (503, False)):
            with self.subTest(status=status, missing=missing):
                gate, adapter, credential, transport = self.setup_model(MODELS[0], lambda _:
                    httpx.Response(status, content=sse(MODELS[0], missing_usage=missing) if status == 200 else b"{}"))
                with self.assertRaises(ModelProviderError):
                    await adapter._ainvoke_with_retry(messages=[Message(role="user", content="Synthetic coding check")])
                self.assertEqual(adapter.retries, 0)
                self.assertEqual(gate.inspect()["status"], "STOPPED")
                self.assertEqual(gate.inspect()["tickets"][-1]["state"], "UNKNOWN")
                transport.assert_called_once()
                credential.reset_mock()
                with self.assertRaises(GoLiveGateError):
                    await adapter.ainvoke([Message(role="user", content="Synthetic repeat must fail")])
                credential.assert_not_called()
                transport.assert_called_once()
                for model in MODELS:
                    with self.assertRaises(GoLiveGateError):
                        GoLiveCampaign(gate.path).authorize("new-session", model, owner_id="alice")

    async def test_usage_bound_rejection_keeps_reader_evidence(self):
        gate, adapter, _, transport = self.setup_model(MODELS[0], lambda _:
            httpx.Response(200, content=sse(MODELS[0], output_tokens=257)))
        with self.assertRaises(GoResponseRejected) as raised:
            await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
        evidence = go_response_usage(raised.exception)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence.output_tokens, 257)  # type: ignore[union-attr]
        self.assertEqual(gate.inspect()["status"], "STOPPED")
        self.assertEqual(gate.inspect()["tickets"][-1]["state"], "SETTLED")
        transport.assert_called_once()

    async def test_cleanup_failure_after_complete_sse_settles_once_and_stops(self):
        for model in MODELS:
            with self.subTest(model=model):
                gate, adapter, credential, transport = self.setup_model(model,
                    lambda _: httpx.Response(200, content=sse(model)))
                close = AsyncMock(side_effect=RuntimeError("synthetic cleanup failure"))
                with patch.object(adapter._async_transport, "aclose", close), patch.object(
                        gate, "finish", wraps=gate.finish) as finish:
                    with self.assertRaises(GoResponseRejected) as raised:
                        await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
                    finish.assert_called_once()
                close.assert_awaited_once()
                evidence = go_response_usage(raised.exception)
                self.assertIsNotNone(evidence)
                self.assertEqual((evidence.input_tokens, evidence.output_tokens), (12, 3))  # type: ignore[union-attr]
                state = gate.inspect()
                self.assertEqual(state["status"], "STOPPED")
                self.assertEqual(state["tickets"][-1]["state"], "SETTLED")
                self.assertEqual(state["tickets"][-1]["total_tokens"], 15)
                self.assertEqual(state["tickets"][-1]["actual_model"], model)
                self.assertNotIn("TICKET_FINISHED", str(raised.exception))
                credential.assert_called_once()
                transport.assert_called_once()

    async def test_cleanup_cancellation_preserves_cancel_semantics_and_known_usage(self):
        for model in MODELS:
            with self.subTest(model=model):
                gate, adapter, credential, transport = self.setup_model(model,
                    lambda _: httpx.Response(200, content=sse(model)))
                close = AsyncMock(side_effect=asyncio.CancelledError())
                with patch.object(adapter._async_transport, "aclose", close), patch.object(
                        gate, "finish", wraps=gate.finish) as finish:
                    with self.assertRaises(GoCancelledWithUsage) as raised:
                        await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
                    finish.assert_called_once()
                self.assertIsInstance(raised.exception, asyncio.CancelledError)
                evidence = go_response_usage(raised.exception)
                self.assertIsNotNone(evidence)
                self.assertEqual((evidence.input_tokens, evidence.output_tokens), (12, 3))  # type: ignore[union-attr]
                state = gate.inspect()
                self.assertEqual((state["status"], state["stopCode"]), ("STOPPED", "CANCELLED"))
                self.assertEqual(state["tickets"][-1]["state"], "SETTLED")
                self.assertEqual(state["tickets"][-1]["total_tokens"], 15)
                self.assertEqual(state["tickets"][-1]["actual_model"], model)
                close.assert_awaited_once()
                credential.assert_called_once()
                transport.assert_called_once()

    async def test_stopped_gate_refuses_before_credential_or_http(self):
        gate, adapter, credential, transport = self.setup_model(MODELS[0], lambda _: httpx.Response(200))
        gate.stop("CANCELLED")
        with self.assertRaises(GoLiveGateError):
            await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
        credential.assert_not_called()
        transport.assert_not_called()
        self.assertEqual(gate.inspect()["requestCount"], 0)

    def test_campaign_model_refuses_native_retry_configuration(self):
        gate = self.campaign()
        credential = Mock(return_value="synthetic-not-a-credential")
        with self.assertRaises(ValueError):
            GoDevelopmentModel(model_id=MODELS[0], session_id="synthetic-session", credential=credential,
                live_campaign=gate, wire_stream=True, native_retries=1, async_transport=httpx.MockTransport(Mock()))
        credential.assert_not_called()

    async def test_all_public_guards_settle_error_usage_before_reraising(self):
        for method in ("invoke", "ainvoke", "invoke_stream", "ainvoke_stream"):
            for cancelled in (False, True):
                with self.subTest(method=method, cancelled=cancelled):
                    gate, adapter, credential, transport = self.setup_model(MODELS[0], lambda _:
                        httpx.Response(200, content=sse(MODELS[0], actual=MODELS[0] if cancelled else "unapproved-model")))
                    ledger = Mock()
                    ledger.begin_attempt.return_value = "synthetic-attempt"
                    ledger.evidence_for.side_effect = lambda _plan, value: go_response_usage(value)
                    DelegatingModel._guard_provider_calls(adapter, lambda: None, ledger=ledger,
                                                         plan={"fixture": True}, context=None)
                    close = AsyncMock(side_effect=asyncio.CancelledError()) if cancelled else AsyncMock()
                    expected = GoCancelledWithUsage if cancelled else GoResponseRejected
                    with patch.object(adapter._async_transport, "aclose", close):
                        with self.assertRaises(expected) as raised:
                            messages = [Message(role="user", content="Synthetic coding check")]
                            if method == "invoke":
                                adapter.invoke(messages)
                            elif method == "ainvoke":
                                await adapter.ainvoke(messages)
                            elif method == "invoke_stream":
                                list(adapter.invoke_stream(messages))
                            else:
                                async for _ in adapter.ainvoke_stream(messages):
                                    self.fail("Rejected provider response must not yield model output")
                    ledger.begin_attempt.assert_called_once()
                    ledger.finish_attempt.assert_called_once()
                    identity, evidence = ledger.finish_attempt.call_args.args
                    self.assertEqual(identity, "synthetic-attempt")
                    self.assertIsNotNone(evidence, "Known exception usage must not become UNKNOWN at stream guard")
                    self.assertEqual((evidence.input_tokens, evidence.output_tokens), (12, 3))
                    self.assertEqual(evidence, go_response_usage(raised.exception))
                    self.assertEqual(gate.inspect()["tickets"][-1]["state"], "SETTLED")
                    credential.assert_called_once()
                    transport.assert_called_once()


if __name__ == "__main__":
    unittest.main()

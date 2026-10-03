"""Exact-ID Go transport tests. Mock HTTP only; no alias/version equivalence.

Official Go chat route selects oa-compat and forwards body.model:
https://github.com/anomalyco/opencode/blob/dev/packages/console/app/src/routes/zen/go/v1/chat/completions.ts
The helper uses /chat/completions:
https://github.com/anomalyco/opencode/blob/dev/packages/console/app/src/routes/zen/util/provider/openai-compatible.ts
"""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock
from uuid import uuid4

import httpx
from agno.exceptions import ModelProviderError
from agno.models.message import Message

from agent_factory.go_development import MODEL_ADAPTER_IDS
from agent_factory.go_live import GoLiveCampaign
from agent_factory.go_single_smoke import GoSingleSmokeCampaign
from agent_factory.go_usage import go_response_usage, pricing_registrations
from agent_factory.opencode_go import GoDevelopmentModel, GoResponseRejected, MODELS, safe_actual_model


def response(model, *, missing_usage=False):
    events = [{"model": model, "choices": [{"index": 0, "delta": {"content": "Synthetic coding answer"}, "finish_reason": "stop"}]},
              {"model": model, "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}]
    if missing_usage:
        events = events[:1]
    return b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n"


@unittest.skipUnless(os.name == "posix", "Private campaign files require POSIX permissions")
class ExactGoAliasTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def adapter(self, requested, returned):
        path = Path(self.directory.name) / (str(uuid4()) + ".sqlite")
        history = GoLiveCampaign.create(path, campaign_id="synthetic-history", owner_id="alice",
            confirmation_id="synthetic-confirmation", expires_at=time.time() + 3600)
        if requested == "deepseek-flash":
            history.authorize("synthetic-history-session", "deepseek-v4-flash", owner_id="alice")
            ticket = history.begin("synthetic-history-session", "deepseek-v4-flash", {
                "model": "deepseek-v4-flash", "stream": True, "messages": [{"role": "user", "content": "synthetic history"}],
                "max_tokens": 64, "stream_options": {"include_usage": True}})
            history.finish(ticket, error_code="UNKNOWN")
            self.campaign = GoSingleSmokeCampaign.create(str(path) + ".budget.sqlite", history_path=path,
                campaign_id="synthetic-continuation", owner_id="alice", confirmation_id="synthetic-confirmation",
                expires_at=time.time() + 3600)
        else:
            self.campaign = history
        self.campaign.authorize("exact-alias-session", requested, owner_id="alice")
        self.finish_probe = Mock(wraps=self.campaign.finish)
        self.campaign.finish = self.finish_probe
        self.credential = Mock(return_value="synthetic-nonsecret-placeholder")

        def handler(request):
            self.assertEqual(str(request.url), "https://opencode.ai/zen/go/v1/chat/completions")
            self.assertEqual(json.loads(request.content)["model"], requested)
            self.assertEqual(request.headers["x-opencode-session"], "exact-alias-session")
            return httpx.Response(200, content=response(returned))

        self.handler = Mock(side_effect=handler)
        return GoDevelopmentModel(model_id=requested, session_id="exact-alias-session", credential=self.credential,
            live_campaign=self.campaign, wire_stream=True, native_retries=0, max_output_tokens=64,
            async_transport=httpx.MockTransport(self.handler))

    async def test_deepseek_flash_is_sent_unchanged_on_chat_protocol(self):
        adapter = self.adapter("deepseek-flash", "deepseek-flash")
        result = await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
        self.assertEqual(adapter.id, "deepseek-flash")
        self.assertEqual(MODELS[adapter.id], "chat/completions")
        self.assertEqual(adapter.retries, 0)
        self.assertEqual(result.response_usage.total_tokens, 8)
        self.finish_probe.assert_called_once_with(self.campaign.inspect()["tickets"][-1]["id"],
            usage={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}, actual_model="deepseek-flash")
        self.credential.assert_called_once()
        self.handler.assert_called_once()

    async def test_known_returned_version_is_evidence_not_alias_equivalence(self):
        for requested, returned in (("deepseek-flash", "deepseek-v4-flash"),
                                    ("deepseek-flash", "deepseek-v4.1-flash"),
                                    ("deepseek-v4-flash", "deepseek-flash")):
            with self.subTest(requested=requested, returned=returned):
                adapter = self.adapter(requested, returned)
                with self.assertRaises(GoResponseRejected) as raised:
                    await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
                self.assertEqual(raised.exception.actual_model, returned)
                usage = go_response_usage(raised.exception)
                self.assertIsNotNone(usage)
                self.assertEqual((usage.input_tokens, usage.output_tokens), (5, 3))  # type: ignore[union-attr]
                self.finish_probe.assert_called_once_with(self.campaign.inspect()["tickets"][-1]["id"],
                    usage={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                    actual_model=returned, error_code="MODEL_MISMATCH")
                self.handler.assert_called_once()
                self.assertEqual(self.campaign.inspect()["status"], "STOPPED")
                self.assertEqual(self.campaign.inspect()["tickets"][-1]["state"], "SETTLED")
                if requested == "deepseek-flash":
                    self.assertEqual(self.campaign.inspect()["tickets"][-1]["actual_model"], returned)

    async def test_unknown_returned_id_is_not_retained_but_usage_is(self):
        adapter = self.adapter("deepseek-flash", "untrusted-server-model-text")
        with self.assertRaises(GoResponseRejected) as raised:
            await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
        self.assertIsNone(raised.exception.actual_model)
        self.assertIsNotNone(go_response_usage(raised.exception))
        self.finish_probe.assert_called_once_with(self.campaign.inspect()["tickets"][-1]["id"],
            usage={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
            actual_model=None, error_code="MODEL_MISMATCH")
        self.assertNotIn("untrusted-server-model-text", str(raised.exception))

    async def test_known_returned_id_survives_missing_usage_without_settlement(self):
        adapter = self.adapter("deepseek-flash", "deepseek-v4.1-flash")
        self.handler.side_effect = lambda _: httpx.Response(200, content=response("deepseek-v4.1-flash", missing_usage=True))
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content="Synthetic coding check")])
        state = self.campaign.inspect()
        self.assertEqual(state["status"], "STOPPED")
        self.assertEqual(state["tickets"][-1]["state"], "UNKNOWN")
        self.assertEqual(state["tickets"][-1]["actual_model"], "deepseek-v4.1-flash")
        self.assertIsNone(state["tickets"][-1]["total_tokens"])
        self.handler.assert_called_once()

    def test_only_finite_returned_ids_are_safe_and_prices_are_not_inherited(self):
        for model in MODELS:
            self.assertEqual(safe_actual_model(model), model)
        for value in (None, [], {}, True, 1, "untrusted-server-model-text"):
            self.assertIsNone(safe_actual_model(value))
        class NamedString(str):
            pass
        self.assertIsNone(safe_actual_model(NamedString("deepseek-flash")))
        self.assertNotIn("deepseek-flash", MODEL_ADAPTER_IDS)
        self.assertNotIn("deepseek-flash", {price.model for price in pricing_registrations(MODEL_ADAPTER_IDS)})

    def test_missing_campaign_methods_or_retry_fail_before_credentials(self):
        credential = Mock(return_value="synthetic-nonsecret-placeholder")
        self.adapter("deepseek-flash", "deepseek-flash")
        for campaign, retries in ((object(), 0), (Mock(), 0), (self.campaign, 1)):
            with self.subTest(retries=retries):
                with self.assertRaises(ValueError):
                    GoDevelopmentModel(model_id="deepseek-flash", session_id="exact-alias-session", credential=credential,
                        live_campaign=campaign, wire_stream=True, native_retries=retries,
                        async_transport=httpx.MockTransport(Mock()))
        credential.assert_not_called()


if __name__ == "__main__":
    unittest.main()

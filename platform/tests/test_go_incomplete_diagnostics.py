"""Future-only finite Responses incompleteness diagnostics; no live calls."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from uuid import uuid4

import httpx
from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.message import Message

from agent_factory.go_diagnostics import annotate_go_error, incomplete_reason, incomplete_usage, safe_diagnostic
from agent_factory.go_live_events import GoDiagnosticJournal
from agent_factory.go_live import GoLiveGateError
from agent_factory.opencode_go import GoCancelledWithUsage, GoDevelopmentModel, GoResponseRejected, _Stream, _unknown
import test_go_project_campaign as fixture  # type: ignore[reportMissingImports]

PRIVATE = "synthetic-private-body-prompt-header-error"


def response(reason: object = "max_output_tokens"):
    return {"model": "gpt-6-luna", "status": "incomplete", "incomplete_details": {"reason": reason},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": PRIVATE}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}


def sse(value):
    return b"data: " + json.dumps(value).encode() + b"\n\n"


class IncompleteDiagnosticTests(unittest.TestCase):
    def test_classifier_exact_allowlist_missing_malformed_and_unknown(self):
        cases = ((response(), "MAX_OUTPUT_TOKENS"), (response("content_filter"), "CONTENT_FILTER"),
            (response(PRIVATE), "OTHER"), (response("MAX_OUTPUT_TOKENS"), "OTHER"),
            (response(" max_output_tokens"), "OTHER"), (response(None), "MISSING"),
            ({}, "MISSING"), ({"incomplete_details": None}, "MISSING"),
            ({"incomplete_details": {}}, "MISSING"), (None, "MALFORMED"),
            ([], "MALFORMED"), ({"incomplete_details": []}, "MALFORMED"),
            (response(True), "MALFORMED"), (response({"secret": PRIVATE}), "MALFORMED"))
        for value, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(incomplete_reason(value), expected)

    def test_classifier_never_invokes_hostile_subclass_methods(self):
        class BadDict(dict):
            def get(self, *args):
                raise AssertionError("must not call mapping methods")
        class BadStr(str):
            def __hash__(self):
                raise AssertionError("must not hash a string subclass")
            def __str__(self):
                raise AssertionError("must not stringify")
        for value in (BadDict(), {"incomplete_details": BadDict()}, response(BadStr(PRIVATE))):
            self.assertEqual(incomplete_reason(value), "MALFORMED")

    def test_stream_throw_site_reason_preserves_error_contract_and_rejects_usage(self):
        for reason, expected in (("max_output_tokens", "MAX_OUTPUT_TOKENS"), ("content_filter", "CONTENT_FILTER"),
                                 (PRIVATE, "OTHER"), (None, "MISSING"), ([], "MALFORMED")):
            stream = _Stream(True)
            with self.assertRaises(ModelProviderError) as caught:
                stream.feed(sse({"type": "response.incomplete", "response": response(reason)}))
            facts = safe_diagnostic("FAILED", error=caught.exception)
            self.assertEqual(facts["rejectionCode"], "RESPONSES_INCOMPLETE")
            self.assertEqual(facts["incompleteReason"], expected)
            self.assertEqual(caught.exception.status_code, 400)
            self.assertEqual(getattr(caught.exception, "_go_code"), "UNKNOWN")
            self.assertIsNone(stream.result)
            self.assertIsNone(stream.usage)
            self.assertFalse(stream.done)
            self.assertNotIn(PRIVATE, json.dumps(facts))

    def test_nonstream_incomplete_has_reason_other_statuses_and_success_unchanged(self):
        adapter = GoDevelopmentModel(model_id="gpt-6-luna", session_id="synthetic-incomplete-session",
            credential=lambda: "synthetic-placeholder", async_transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        for status in ("incomplete", "failed", "queued"):
            value = {**response(), "status": status}
            with self.assertRaises(ModelProviderError) as caught:
                adapter._parse_provider_response(value)
            facts = safe_diagnostic("FAILED", error=caught.exception)
            self.assertEqual(facts["rejectionCode"], "RESPONSE_INCOMPLETE")
            self.assertEqual("incompleteReason" in facts, status == "incomplete")
        result = adapter._parse_provider_response({**response(), "status": "completed"})
        self.assertEqual(result.response_usage.total_tokens, 15)
        self.assertEqual(result.content, PRIVATE)

    def test_wrappers_propagate_enum_with_existing_chain_bound(self):
        error = _unknown(rejection_code="RESPONSES_INCOMPLETE", incomplete_reason="CONTENT_FILTER")
        usage = MessageMetrics(input_tokens=1, output_tokens=2, total_tokens=3)
        for _ in range(10):
            error = GoResponseRejected("GO_LIVE_RESPONSE_REJECTED", usage, original_error=error)
        wrapped = GoCancelledWithUsage(usage, original_error=error)
        self.assertIsInstance(wrapped, asyncio.CancelledError)
        for value in (error, wrapped):
            facts = safe_diagnostic("FAILED", error=value)
            self.assertEqual(facts["incompleteReason"], "CONTENT_FILTER")
            self.assertEqual(facts["rejectionCode"], "RESPONSES_INCOMPLETE")
            self.assertLessEqual(len(facts["exceptionChain"]), 6)
            self.assertNotIn(PRIVATE, json.dumps(facts))

    def test_tampered_metadata_and_unrelated_error_never_emit_untrusted_reason(self):
        class Dangerous(ModelProviderError):
            @property
            def _go_incomplete_reason(self):
                raise AssertionError("must not invoke properties")
            def __str__(self):
                raise AssertionError("must not stringify")
        error = Dangerous(PRIVATE)
        annotate_go_error(error, rejection_code="RESPONSES_INCOMPLETE", incomplete_reason="MAX_OUTPUT_TOKENS")
        self.assertEqual(safe_diagnostic("FAILED", error=error)["incompleteReason"], "MAX_OUTPUT_TOKENS")
        for forged in (PRIVATE, True, ["MAX_OUTPUT_TOKENS"], {"reason": "MAX_OUTPUT_TOKENS"}):
            error.__dict__["_go_incomplete_reason"] = forged
            self.assertNotIn("incompleteReason", safe_diagnostic("FAILED", error=error))
        annotate_go_error(error, rejection_code="CHAT_ERROR", incomplete_reason="MAX_OUTPUT_TOKENS")
        self.assertNotIn("incompleteReason", safe_diagnostic("FAILED", error=error))
        legacy = _unknown(rejection_code="RESPONSES_INCOMPLETE")
        self.assertNotIn("incompleteReason", safe_diagnostic("FAILED", error=legacy))

    def test_incomplete_usage_requires_exact_model_status_and_bounded_integer_counts(self):
        self.assertEqual(incomplete_usage(response(), expected_model="gpt-6-luna"), (10, 5, 15))
        self.assertIsNone(incomplete_usage(response()))
        self.assertIsNone(incomplete_usage(response(), expected_model="deepseek-flash"))
        for update in ({"model": PRIVATE}, {"status": "completed"}, {"usage": []},
                       {"usage": {"input_tokens": True, "output_tokens": 5, "total_tokens": 6}},
                       {"usage": {"input_tokens": -1, "output_tokens": 5, "total_tokens": 4}},
                       {"usage": {"input_tokens": 1, "output_tokens": 5, "total_tokens": 7}},
                       {"usage": {"input_tokens": 1, "output_tokens": 5}},
                       {"usage": {"input_tokens": 2**31, "output_tokens": 1, "total_tokens": 2**31+1}}):
            self.assertIsNone(incomplete_usage({**response(), **update}, expected_model="gpt-6-luna"))
        boundary = {**response(), "usage": {"input_tokens": 2**31, "output_tokens": 0, "total_tokens": 2**31}}
        self.assertEqual(incomplete_usage(boundary, expected_model="gpt-6-luna"), (2**31, 0, 2**31))

    def test_reported_usage_propagation_is_diagnostic_only_and_revalidates_forgery(self):
        original = _unknown(rejection_code="RESPONSES_INCOMPLETE", incomplete_reason="MAX_OUTPUT_TOKENS",
                            reported_usage=incomplete_usage(response(), expected_model="gpt-6-luna"))
        wrapped = _unknown(original_error=original)
        facts = safe_diagnostic("FAILED", error=wrapped)
        self.assertEqual(facts["reportedUsage"]["totalTokens"], 15)
        self.assertEqual(facts["reportedUsage"]["observationStatus"], "provider-incomplete-unsettled")
        self.assertFalse(hasattr(original, "response_usage"))
        self.assertFalse(hasattr(wrapped, "response_usage"))
        for invalid in ([10, 5, 15], (True, 5, 6), (10, 5, 99), (10, 5, PRIVATE)):
            wrapped.__dict__["_go_reported_usage"] = invalid
            self.assertNotIn("reportedUsage", safe_diagnostic("FAILED", error=wrapped))
        annotate_go_error(wrapped, rejection_code="CHAT_ERROR", reported_usage=(10, 5, 15))
        self.assertNotIn("reportedUsage", safe_diagnostic("FAILED", error=wrapped))

    def test_stream_usage_observation_requires_explicit_matching_expected_model(self):
        for expected in (None, "deepseek-flash", "gpt-6-luna"):
            stream = _Stream(True, expected_model=expected)
            with self.assertRaises(ModelProviderError) as caught:
                stream.feed(sse({"type": "response.incomplete", "response": response()}))
            facts = safe_diagnostic("FAILED", error=caught.exception)
            self.assertEqual("reportedUsage" in facts, expected == "gpt-6-luna")
            self.assertIsNone(stream.usage)
            self.assertIsNone(stream.result)

    @unittest.skipUnless(os.name == "posix", "Private synthetic diagnostic journal")
    def test_journal_appends_future_enum_and_does_not_backfill_old_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite"
            journal = GoDiagnosticJournal.create(path, "synthetic-incomplete")
            journal.record(str(uuid4()), "FAILED", error=_unknown(rejection_code="RESPONSES_INCOMPLETE"))
            previous = journal.inspect()["events"][0]
            error = _unknown(rejection_code="RESPONSES_INCOMPLETE", incomplete_reason=incomplete_reason(response(PRIVATE)))
            journal.record(str(uuid4()), "FAILED", error=error,
                response_headers={"content-type": "text/event-stream", "authorization": PRIVATE, "x-request-id": PRIVATE})
            events = GoDiagnosticJournal(path).inspect()["events"]
            self.assertEqual(events[0], previous)
            self.assertNotIn("incompleteReason", events[0])
            self.assertEqual(events[1]["incompleteReason"], "OTHER")
            self.assertNotIn(PRIVATE, json.dumps(events))
            self.assertNotIn(PRIVATE.encode(), path.read_bytes())


@unittest.skipUnless(os.name == "posix", "Private synthetic project campaign")
class IncompleteCampaignTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_valid_looking_usage_stays_unknown_one_dispatch_and_stopped(self):
        helper = fixture.ProjectCampaignTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        policy = helper.migrate()
        policy.authorize("synthetic-incomplete-luna", "gpt-6-luna", owner_id="alice")
        handler = Mock(return_value=httpx.Response(200, headers={"content-type": "text/event-stream", "x-request-id": PRIVATE},
            content=sse({"type": "response.incomplete", "response": response()})))
        credential = Mock(return_value="synthetic-placeholder")
        adapter = GoDevelopmentModel(model_id="gpt-6-luna", session_id="synthetic-incomplete-luna",
            credential=credential, live_campaign=policy, wire_stream=True, native_retries=0,
            async_transport=httpx.MockTransport(handler))
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content=PRIVATE)])
        facts = policy.inspect()
        self.assertEqual(facts["requestCount"], 4)
        self.assertEqual(facts["status"], "STOPPED")
        self.assertEqual(facts["tickets"][:3], helper.history)
        self.assertEqual(facts["tickets"][-1]["state"], "UNKNOWN")
        self.assertIsNone(facts["tickets"][-1]["total_tokens"])
        latest = facts["diagnostics"]["events"][-1]
        self.assertEqual(latest["incompleteReason"], "MAX_OUTPUT_TOKENS")
        self.assertEqual(latest["reportedUsage"], {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15,
                                                   "observationStatus": "provider-incomplete-unsettled"})
        self.assertNotIn(PRIVATE, json.dumps(facts))
        handler.assert_called_once()
        credential.assert_called_once()
        with self.assertRaises(GoLiveGateError):
            await adapter.ainvoke([Message(role="user", content="synthetic no replay")])
        handler.assert_called_once()
        self.assertEqual(policy.inspect()["requestCount"], 4)

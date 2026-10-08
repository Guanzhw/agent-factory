"""Synthetic repeated terminal usage contract; no external requests or credentials."""
import json
import os
import unittest
from unittest.mock import Mock

import httpx
from agno.exceptions import ModelProviderError
from agno.models.message import Message

from agent_factory.go_diagnostics import safe_diagnostic
from agent_factory.opencode_go import GoDevelopmentModel, _Stream
import test_go_project_campaign as fixture  # type: ignore[reportMissingImports]

MODEL = "deepseek-flash"
USAGE = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
PRIVATE = "synthetic-output-not-for-diagnostics"


def event(value):
    return b"data: " + json.dumps(value).encode() + b"\n\n"


def terminal():
    return event({"model": MODEL, "choices": [{"index": 0, "delta": {"content": PRIVATE}, "finish_reason": "stop"}], "usage": USAGE})


def repeated(usage=None):
    return event({"model": MODEL, "choices": [], "usage": USAGE if usage is None else usage})


class RepeatedUsageTests(unittest.TestCase):
    def test_complete_identical_terminal_usage_is_idempotent_across_chunk_boundaries(self):
        payload = terminal() + repeated() + repeated() + b"data: [DONE]\n\n"
        for width in (1, 7, len(payload)):
            with self.subTest(width=width):
                stream = _Stream(False)
                for index in range(0, len(payload), width):
                    stream.feed(payload[index:index+width])
                result = stream.finish()
                self.assertEqual(result["usage"], USAGE)
                self.assertEqual(result["choices"][0]["message"]["content"], PRIVATE)

    def test_conflicting_or_malformed_repeat_is_rejected_without_echoing_payload(self):
        for usage in (
            {"prompt_tokens": 6, "completion_tokens": 3, "total_tokens": 9},
            {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
            {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 9},
            {"prompt_tokens": 5, "completion_tokens": 3},
            {"prompt_tokens": True, "completion_tokens": 3, "total_tokens": 4},
            {"prompt_tokens": "5", "completion_tokens": 3, "total_tokens": 8},
            {"prompt_tokens": 5, "completion_tokens": -3, "total_tokens": 2},
            PRIVATE, [], {},
        ):
            with self.subTest(usage=usage):
                stream = _Stream(False)
                stream.feed(terminal())
                with self.assertRaises(ModelProviderError) as caught:
                    stream.feed(repeated(usage))
                facts = safe_diagnostic("FAILED", error=caught.exception)
                self.assertEqual(facts["rejectionCode"], "STREAM_USAGE_REPEATED")
                self.assertNotIn(PRIVATE, json.dumps(facts))

    def test_optional_usage_metadata_does_not_change_identical_counter_semantics(self):
        stream = _Stream(False)
        stream.feed(terminal())
        stream.feed(repeated({**USAGE, "completion_tokens_details": {"reasoning_tokens": 1}}))
        stream.feed(b"data: [DONE]\n\n")
        self.assertEqual(stream.finish()["usage"], USAGE)

    def test_identically_malformed_usage_is_not_accepted_by_equality_alone(self):
        bad = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 99}
        value = {"model": MODEL, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": bad}
        stream = _Stream(False)
        stream.feed(event(value))
        with self.assertRaises(ModelProviderError) as caught:
            stream.feed(repeated(bad))
        self.assertEqual(safe_diagnostic("FAILED", error=caught.exception)["rejectionCode"], "STREAM_USAGE_REPEATED")

    def test_early_usage_is_still_rejected(self):
        stream = _Stream(False)
        with self.assertRaises(ModelProviderError) as caught:
            stream.feed(repeated())
        self.assertEqual(safe_diagnostic("FAILED", error=caught.exception)["rejectionCode"], "STREAM_USAGE_EARLY")

    def test_repeated_usage_does_not_replace_required_done_marker(self):
        stream = _Stream(False)
        stream.feed(terminal()+repeated())
        with self.assertRaises(ModelProviderError) as caught:
            stream.finish()
        self.assertEqual(safe_diagnostic("FAILED", error=caught.exception)["rejectionCode"], "STREAM_MISSING_TERMINAL")

    def test_usage_after_done_is_not_accepted_as_duplicate(self):
        stream = _Stream(False)
        stream.feed(terminal()+b"data: [DONE]\n\n")
        with self.assertRaises(ModelProviderError) as caught:
            stream.feed(repeated())
        self.assertEqual(safe_diagnostic("FAILED", error=caught.exception)["rejectionCode"], "STREAM_AFTER_DONE")


@unittest.skipUnless(os.name == "posix", "Private synthetic project history")
class RepeatedUsageLedgerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.helper = fixture.ProjectCampaignTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.policy = self.helper.migrate()
        self.policy.authorize("synthetic-repetition-session", MODEL, owner_id="alice")

    def model(self, stream):
        handler = Mock(return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream))
        credential = Mock(return_value="synthetic-placeholder")
        adapter = GoDevelopmentModel(model_id=MODEL, session_id="synthetic-repetition-session", credential=credential,
            live_campaign=self.policy, wire_stream=True, native_retries=0, max_output_tokens=64,
            async_transport=httpx.MockTransport(handler))
        return adapter, handler, credential

    async def test_duplicate_usage_settles_once_only_after_eof(self):
        case = self
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield terminal()
                yield repeated()
                yield b"data: [DONE]\n\n"
                # The consumer has parsed DONE but has not observed iterator EOF.
                ticket = case.policy.inspect()["tickets"][-1]
                case.assertEqual(ticket["state"], "INFLIGHT")
                case.assertIsNone(ticket["total_tokens"])
        adapter, handler, credential = self.model(Stream())
        result = await adapter.ainvoke([Message(role="user", content="synthetic coding")])
        self.assertEqual(result.response_usage.total_tokens, 8)
        facts = self.policy.inspect()
        self.assertEqual(facts["requestCount"], 4)
        self.assertEqual(facts["tickets"][:3], self.helper.history)
        self.assertEqual(facts["tickets"][-1]["state"], "SETTLED")
        self.assertEqual(facts["tickets"][-1]["total_tokens"], 8)
        self.assertEqual(sum(t["total_tokens"] or 0 for t in facts["tickets"]), 8)
        handler.assert_called_once()
        credential.assert_called_once()
        self.assertNotIn(PRIVATE, json.dumps(facts))

    async def test_missing_done_keeps_unknown_no_usage_settlement(self):
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield terminal()+repeated()
        adapter, handler, _ = self.model(Stream())
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content="synthetic coding")])
        facts = self.policy.inspect()
        self.assertEqual(facts["tickets"][-1]["state"], "UNKNOWN")
        self.assertIsNone(facts["tickets"][-1]["total_tokens"])
        self.assertEqual(facts["diagnostics"]["events"][-1]["rejectionCode"], "STREAM_MISSING_TERMINAL")
        self.assertEqual(facts["requestCount"], 4)
        handler.assert_called_once()

    async def test_transport_failure_after_done_preserves_unknown(self):
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield terminal()+repeated()+b"data: [DONE]\n\n"
                raise httpx.RemoteProtocolError(PRIVATE)
        adapter, handler, _ = self.model(Stream())
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content="synthetic coding")])
        facts = self.policy.inspect()
        self.assertEqual(facts["tickets"][-1]["state"], "UNKNOWN")
        self.assertIsNone(facts["tickets"][-1]["total_tokens"])
        self.assertEqual(facts["diagnostics"]["events"][-1]["rejectionCode"], "TRANSPORT_PROTOCOL")
        self.assertNotIn(PRIVATE, json.dumps(facts))
        handler.assert_called_once()

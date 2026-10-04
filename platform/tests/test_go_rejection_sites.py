"""Offline throw-site diagnostics: fixed codes, unchanged rejection semantics."""
import asyncio
import json
import os
import unittest

import httpx

from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics

from agent_factory.go_diagnostics import safe_diagnostic
from agent_factory.opencode_go import (
    GoCancelledWithUsage, GoResponseRejected, MAX_BYTES, _Stream, _unknown,
)
import test_go_stream_diagnosis as diagnosis  # type: ignore[reportMissingImports]
from test_go_stream_diagnosis import event, terminal, USAGE  # type: ignore[reportMissingImports]


class GoRejectionSiteTests(unittest.TestCase):
    def test_every_explicit_stream_guard_has_a_distinct_stable_code(self):
        cases = [
            ("STREAM_SIZE", False, [b"x" * (MAX_BYTES + 1)], False),
            ("STREAM_AFTER_DONE", False, [b"data: [DONE]\n", event({})], False),
            ("STREAM_MODEL_CHANGED", False, [event({"model": "deepseek-flash"}),
                event({"model": "deepseek-v4-flash"})], False),
            *[(code, True, [event({"type": kind})], False) for kind, code in (
                ("error", "RESPONSES_ERROR"), ("response.failed", "RESPONSES_FAILED"),
                ("response.incomplete", "RESPONSES_INCOMPLETE"))],
            ("CHAT_ERROR", False, [event({"error": None})], False),
            ("STREAM_CHOICES_SHAPE", False, [event({"choices": {}})], False),
            ("STREAM_CHOICES_COUNT", False, [event({"choices": [{}, {}]})], False),
            ("STREAM_CHOICE_INDEX", False, [event({"choices": [{"index": 1}]})], False),
            ("STREAM_AFTER_TERMINAL", False, [terminal(), event({"choices": [{}]})], False),
            ("STREAM_TOOL_INDEX", False, [event({"choices": [{"delta": {"tool_calls": [{"index": -1}]}}]})], False),
            ("STREAM_TOOL_TYPE", False, [event({"choices": [{"delta": {"tool_calls": [{"index": 0, "type": "shell"}]}}]})], False),
            ("STREAM_USAGE_EARLY", False, [event({"usage": USAGE})], False),
            ("STREAM_USAGE_REPEATED", False, [terminal(), event({"usage": USAGE}), event({"usage": {**USAGE, "completion_tokens": 4, "total_tokens": 9}})], False),
            ("STREAM_INCOMPLETE_BUFFER", False, [b"data: {"], True),
            ("STREAM_MISSING_TERMINAL", False, [terminal()], True),
            ("STREAM_MISSING_RESPONSE", True, [b"data: [DONE]\n"], True),
        ]
        self.assertEqual(len({case[0] for case in cases}), 18)
        for code, responses, chunks, finish in cases:
            with self.subTest(code=code):
                stream = _Stream(responses)
                with self.assertRaises(ModelProviderError) as raised:
                    for chunk in chunks:
                        stream.feed(chunk)
                    if finish:
                        stream.finish()
                error = raised.exception
                self.assertEqual(error.status_code, 400)
                self.assertEqual(getattr(error, "_go_code"), "GO_MODEL_MISMATCH" if code == "STREAM_MODEL_CHANGED" else "UNKNOWN")
                self.assertEqual(safe_diagnostic("FAILED", error=error)["rejectionCode"], code)

    def test_known_usage_wrappers_preserve_rejection_metadata(self):
        original = _unknown("Go stream failed", rejection_code="CHAT_ERROR")
        usage = MessageMetrics(input_tokens=2, output_tokens=1, total_tokens=3)
        wrapped = GoResponseRejected("GO_LIVE_RESPONSE_REJECTED", usage, original_error=original)
        self.assertIs(wrapped.response_usage, usage)
        facts = safe_diagnostic("FAILED", error=wrapped)
        self.assertEqual(facts["rejectionCode"], "CHAT_ERROR")
        self.assertIn("ModelProviderError", facts["exceptionChain"])
        cancellation = GoCancelledWithUsage(usage, original_error=asyncio.CancelledError())
        self.assertIsInstance(cancellation, asyncio.CancelledError)
        self.assertIs(cancellation.response_usage, usage)
        self.assertIn("CancelledError", safe_diagnostic("FAILED", error=cancellation)["exceptionChain"])


@unittest.skipUnless(os.name == "posix", "Private synthetic campaign requires POSIX permissions")
class GoRejectionStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_json_and_eof_failures_persist_distinct_codes_and_stages(self):
        helper = diagnosis.GoStreamDiagnosisTests()
        helper.setUp()
        self.addCleanup(helper.directory.cleanup)
        cases = (
            ("TRANSPORT_READ", terminal(), {"error": httpx.ReadError("synthetic truncation"),
                "error_type": "ReadError", "category": "read"}),
            ("TRANSPORT_PROTOCOL", terminal(), {"error": httpx.RemoteProtocolError("synthetic truncation"),
                "error_type": "RemoteProtocolError", "category": "protocol"}),
            ("JSON_DECODE", b"data: {invalid}\n\n", {"error_type": "JSONDecodeError", "category": "parse"}),
            ("STREAM_MISSING_TERMINAL", terminal(), {"stage": "STREAM_COMPLETED"}),
            ("STREAM_INCOMPLETE_BUFFER", b'data: {"choices":', {"stage": "STREAM_COMPLETED"}),
        )
        for code, payload, options in cases:
            with self.subTest(code=code):
                facts = await helper.failure([payload], **options)
                records = facts["diagnostics"]["events"]
                self.assertEqual(records[-1]["rejectionCode"], code)
                self.assertEqual(records[-2]["rejectionCode"], code)
                self.assertEqual(records[-2]["phase"], options.get("stage", "RESPONSE_HEADERS"))
                self.assertEqual(facts["tickets"][-1]["state"], "UNKNOWN")

    async def test_persisted_codes_disambiguate_failures_without_releasing_unknown_slots(self):
        helper = diagnosis.GoStreamDiagnosisTests()
        helper.setUp()
        self.addCleanup(helper.directory.cleanup)
        for code, payload in (("CHAT_ERROR", event({"error": {"message": "synthetic body must not persist"}})),
                              ("STREAM_USAGE_EARLY", event({"usage": USAGE})),
                              ("STREAM_CHOICES_COUNT", event({"choices": [{}, {}]}))):
            with self.subTest(code=code):
                facts = await helper.failure([payload])
                self.assertEqual(facts["diagnostics"]["events"][-1]["rejectionCode"], code)
                self.assertEqual(facts["tickets"][0]["state"], "UNKNOWN")
                self.assertNotIn("synthetic body must not persist", json.dumps(facts))


if __name__ == "__main__":
    unittest.main()

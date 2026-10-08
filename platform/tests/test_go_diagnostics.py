"""Safe diagnostic contracts and MockTransport stage injection; no live calls."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from agno.exceptions import ModelProviderError
from agno.models.message import Message

from agent_factory.go_diagnostics import PHASES, safe_diagnostic
from agent_factory.go_live import GoLiveCampaign
from agent_factory.go_usage import go_response_usage
from agent_factory.opencode_go import GoDevelopmentModel, GoResponseRejected


_UNTRUSTED = "UNTRUSTED_TEXT_NEVER_PERSIST"
_MODEL = "deepseek-v4-flash"


def _sse():
    events = [{"model": _MODEL, "choices": [{"index": 0, "delta": {"content": _UNTRUSTED}, "finish_reason": "stop"}]},
              {"model": _MODEL, "choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}]
    return b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + b"data: [DONE]\n\n"


class SafeDiagnosticTests(unittest.TestCase):
    def test_arbitrary_exception_name_text_cause_and_headers_cannot_escape(self):
        class MaliciousError(Exception):
            def __str__(self):
                raise AssertionError("Diagnostic must not stringify an exception")
        MaliciousError.__name__ = _UNTRUSTED
        error = MaliciousError(_UNTRUSTED)
        error.__cause__ = ValueError(_UNTRUSTED)
        result = safe_diagnostic("FAILED", http_status=429, error=error, response_headers={
            "content-type": _UNTRUSTED, "retry-after": _UNTRUSTED, "x-request-id": _UNTRUSTED,
            "authorization": _UNTRUSTED, "set-cookie": _UNTRUSTED})
        self.assertNotIn(_UNTRUSTED, json.dumps(result))
        self.assertEqual(result["errorType"], "UnknownError")
        self.assertEqual(result["responseHeaders"], {"contentType": "other", "retryAfterBucket": "invalid"})

    def test_error_categories_use_fixed_type_mappings(self):
        cases = [(httpx.ConnectError(_UNTRUSTED), "connection"), (httpx.ReadError(_UNTRUSTED), "read"),
                 (httpx.RemoteProtocolError(_UNTRUSTED), "protocol"), (httpx.ReadTimeout(_UNTRUSTED), "timeout"),
                 (json.JSONDecodeError(_UNTRUSTED, _UNTRUSTED, 0), "parse"), (asyncio.CancelledError(_UNTRUSTED), "cancel")]
        for error, category in cases:
            with self.subTest(category=category):
                result = safe_diagnostic("FAILED", error=error)
                self.assertEqual(result["errorCategory"], category)
                self.assertNotIn(_UNTRUSTED, json.dumps(result))
        self.assertEqual(safe_diagnostic("CREDENTIAL_CHECK", error=KeyError(_UNTRUSTED))["errorCategory"], "credential")

    def test_headers_and_status_are_normalized_to_bounded_values(self):
        for status in (True, 99, 600, 429.0, _UNTRUSTED):
            self.assertNotIn("httpStatus", safe_diagnostic("RESPONSE_HEADERS", http_status=status))
        result = safe_diagnostic("RESPONSE_HEADERS", http_status=200,
                                 response_headers=httpx.Headers({"Content-Type": "text/event-stream; charset=" + _UNTRUSTED,
                                                               "Retry-After": "120"}))
        self.assertEqual(result["responseHeaders"], {"contentType": "event-stream", "retryAfterBucket": "long"})
        self.assertNotIn(_UNTRUSTED, json.dumps(result))
        for retry in (True, 30, 1.5, _UNTRUSTED):
            self.assertEqual(safe_diagnostic("RESPONSE_HEADERS", response_headers={"retry-after": retry})[
                "responseHeaders"]["retryAfterBucket"], "invalid")

    def test_phase_set_is_fixed_and_dispatch_never_claims_receipt(self):
        for phase in PHASES:
            self.assertEqual(safe_diagnostic(phase)["phase"], phase)
        with self.assertRaises(ValueError):
            safe_diagnostic(_UNTRUSTED)
        summary = safe_diagnostic("DISPATCH_STARTED")["summary"]
        self.assertIn("no socket or server receipt", summary)
        self.assertIn("successful parsing is not established", safe_diagnostic("STREAM_COMPLETED")["summary"])

    def test_untrusted_exception_metadata_is_revalidated(self):
        error = ModelProviderError(_UNTRUSTED)
        setattr(error, "_go_diagnostic", (_UNTRUSTED, _UNTRUSTED))
        result = safe_diagnostic("FAILED", error=error)
        self.assertEqual(result["errorType"], "ModelProviderError")
        self.assertNotIn(_UNTRUSTED, json.dumps(result))

    def test_actual_parser_wrap_preserves_only_safe_original_type(self):
        adapter = GoDevelopmentModel(model_id=_MODEL, session_id="synthetic-session", credential=Mock())
        with self.assertRaises(ModelProviderError) as raised:
            adapter._parse_provider_response({"choices": [{"finish_reason": "stop"}], "server_text": _UNTRUSTED})
        result = safe_diagnostic("FAILED", error=raised.exception)
        self.assertEqual((result["errorType"], result["errorCategory"]), ("KeyError", "parse"))
        self.assertNotIn(_UNTRUSTED, json.dumps(result))


class _ReadFailure(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices": []}\n\n'
        raise httpx.ReadError(_UNTRUSTED)


@unittest.skipUnless(os.name == "posix", "Private campaign files require POSIX permissions")
class DiagnosticTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.gate = GoLiveCampaign.create(Path(self.directory.name) / "campaign.sqlite",
            campaign_id="synthetic-diag", owner_id="alice", confirmation_id="synthetic-confirmation",
            expires_at=time.time() + 3600)
        self.gate.authorize("synthetic-session", _MODEL, owner_id="alice")

    def model(self, handler, credential=None):
        self.transport = Mock(side_effect=handler)
        self.credential = credential or Mock(return_value="synthetic-placeholder")
        return GoDevelopmentModel(model_id=_MODEL, session_id="synthetic-session", credential=self.credential,
            live_campaign=self.gate, wire_stream=True, async_transport=httpx.MockTransport(self.transport))

    def events(self):
        records = self.gate.inspect()["diagnostics"]["events"]
        self.assertNotIn(_UNTRUSTED, json.dumps(records))
        self.assertNotIn(_UNTRUSTED.encode(), Path(str(self.gate.path) + ".events.sqlite").read_bytes())
        return records

    async def test_success_records_order_without_input_output_or_header_text(self):
        adapter = self.model(lambda _: httpx.Response(200, content=_sse(), headers={
            "content-type": "text/event-stream", "x-request-id": _UNTRUSTED, "set-cookie": _UNTRUSTED}))
        await adapter.ainvoke([Message(role="user", content=_UNTRUSTED)])
        self.assertEqual([row["phase"] for row in self.events()], ["PREPARED", "CREDENTIAL_CHECK",
            "DISPATCH_STARTED", "RESPONSE_HEADERS", "STREAM_COMPLETED", "PARSED"])
        self.transport.assert_called_once()

    async def test_credential_failure_prevents_dispatch_and_records_original_type(self):
        adapter = self.model(lambda _: httpx.Response(200), credential=Mock(side_effect=KeyError(_UNTRUSTED)))
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content="synthetic")])
        records = self.events()
        self.assertNotIn("DISPATCH_STARTED", [row["phase"] for row in records])
        self.assertTrue(any(row.get("errorType") == "KeyError" and row.get("errorCategory") == "credential" for row in records))
        self.transport.assert_not_called()

    async def test_connection_failure_has_local_dispatch_but_no_response_headers(self):
        adapter = self.model(lambda _: (_ for _ in ()).throw(httpx.ConnectError(_UNTRUSTED)))
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content="synthetic")])
        records = self.events()
        self.assertIn("DISPATCH_STARTED", [row["phase"] for row in records])
        self.assertNotIn("RESPONSE_HEADERS", [row["phase"] for row in records])
        self.assertEqual(records[-1]["errorType"], "ConnectError")
        self.assertEqual(records[-1]["errorCategory"], "connection")

    async def test_read_failure_records_headers_without_eof(self):
        adapter = self.model(lambda _: httpx.Response(200, stream=_ReadFailure()))
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content="synthetic")])
        records = self.events()
        self.assertIn("RESPONSE_HEADERS", [row["phase"] for row in records])
        self.assertNotIn("STREAM_COMPLETED", [row["phase"] for row in records])
        self.assertEqual(records[-1]["errorCategory"], "read")

    async def test_timeout_is_classified_without_exception_text(self):
        adapter = self.model(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout(_UNTRUSTED)))
        with self.assertRaises(ModelProviderError):
            await adapter.ainvoke([Message(role="user", content="synthetic")])
        self.assertEqual(self.events()[-1]["errorType"], "ReadTimeout")
        self.assertEqual(self.events()[-1]["errorCategory"], "timeout")

    async def test_cancellation_keeps_native_exception_and_safe_diagnostic(self):
        adapter = self.model(lambda _: (_ for _ in ()).throw(asyncio.CancelledError(_UNTRUSTED)))
        with self.assertRaises(asyncio.CancelledError):
            await adapter.ainvoke([Message(role="user", content="synthetic")])
        self.assertEqual(self.events()[-1]["errorType"], "CancelledError")
        self.assertEqual(self.events()[-1]["errorCategory"], "cancel")
        self.assertEqual(self.gate.inspect()["status"], "STOPPED")

    async def test_malformed_sse_retains_json_error_type_without_response_text(self):
        adapter = self.model(lambda _: httpx.Response(200, content=b"data: {" + _UNTRUSTED.encode() + b"}\n\n"))
        with self.assertRaises(ModelProviderError) as raised:
            await adapter.ainvoke([Message(role="user", content="synthetic")])
        self.assertEqual(self.events()[-1]["errorType"], "JSONDecodeError")
        self.assertEqual(self.events()[-1]["errorCategory"], "parse")
        self.assertEqual(safe_diagnostic("FAILED", error=raised.exception)["errorType"], "JSONDecodeError")

    async def test_parser_wrapped_error_keeps_original_safe_type(self):
        adapter = self.model(lambda _: httpx.Response(200, content=b"data: [DONE]\n\n"))
        with patch.object(adapter, "_parse_provider_response", side_effect=KeyError(_UNTRUSTED)):
            with self.assertRaises(ModelProviderError) as raised:
                await adapter.ainvoke([Message(role="user", content="synthetic")])
        self.assertEqual(self.events()[-1]["errorType"], "KeyError")
        self.assertEqual(self.events()[-1]["errorCategory"], "parse")
        self.assertEqual(safe_diagnostic("FAILED", error=raised.exception)["errorType"], "KeyError")

    async def test_pre_dispatch_diagnostic_failure_stops_before_credential_or_http(self):
        adapter = self.model(lambda _: httpx.Response(200))
        original = self.gate.record_event
        def fail(ticket, phase, **fields):
            if phase == "CREDENTIAL_CHECK":
                raise OSError(_UNTRUSTED)
            return original(ticket, phase, **fields)
        with patch.object(self.gate, "record_event", side_effect=fail):
            with self.assertRaises(ModelProviderError):
                await adapter.ainvoke([Message(role="user", content="synthetic")])
        self.credential.assert_not_called()
        self.transport.assert_not_called()
        self.assertEqual(self.gate.inspect()["status"], "STOPPED")

    async def test_parsed_diagnostic_failure_keeps_usage_and_stops(self):
        adapter = self.model(lambda _: httpx.Response(200, content=_sse()))
        original = self.gate.record_event
        def fail(ticket, phase, **fields):
            if phase == "PARSED":
                raise OSError(_UNTRUSTED)
            return original(ticket, phase, **fields)
        with patch.object(self.gate, "record_event", side_effect=fail):
            with self.assertRaises(GoResponseRejected) as raised:
                await adapter.ainvoke([Message(role="user", content="synthetic")])
        self.assertIsNotNone(go_response_usage(raised.exception))
        facts = self.gate.inspect()
        self.assertEqual(facts["status"], "STOPPED")
        self.assertEqual(facts["tickets"][-1]["state"], "SETTLED")
        self.assertEqual(facts["tickets"][-1]["total_tokens"], 5)
        self.transport.assert_called_once()


if __name__ == "__main__":
    unittest.main()

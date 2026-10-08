"""Characterize 329236c stream failures using synthetic HTTP 200 SSE only.

These fixtures demonstrate diagnostic equivalence and distinctions. They cannot
identify a historical response whose body and error text were not retained.
No real provider, environment credentials, or historical evidence is accessed.
"""
from __future__ import annotations

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

from agent_factory.go_live import GoLiveCampaign
from agent_factory.go_single_smoke import GoSingleSmokeCampaign
from agent_factory.opencode_go import GoDevelopmentModel, MAX_BYTES

MODEL = "deepseek-flash"
SYNTHETIC_TEXT = "synthetic-stream-text-not-persisted"
USAGE = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}


def event(value):
    return b"data: " + json.dumps(value, separators=(",", ":")).encode() + b"\n\n"


def choice(*, reason=None, content=SYNTHETIC_TEXT, index=0):
    return {"model": MODEL, "choices": [{"index": index, "delta": {"content": content}, "finish_reason": reason}]}


def terminal():
    return event(choice(reason="stop"))


def complete():
    return terminal() + event({"model": MODEL, "choices": [], "usage": USAGE}) + b"data: [DONE]\n\n"


class SyntheticStream(httpx.AsyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks, self.error = chunks, error
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error

    async def aclose(self):
        self.closed = True


@unittest.skipUnless(os.name == "posix", "Private synthetic campaign requires POSIX permissions")
class GoStreamDiagnosisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="synthetic-stream-diagnosis-")
        self.addCleanup(self.directory.cleanup)

    def fixture(self, chunks, *, error=None):
        path = Path(self.directory.name) / (str(uuid4()) + ".sqlite")
        history = GoLiveCampaign.create(path, campaign_id="synthetic-history", owner_id="alice",
            confirmation_id="synthetic-confirmation", expires_at=time.time() + 3600)
        history.authorize("synthetic-history-session", "deepseek-v4-flash", owner_id="alice")
        ticket = history.begin("synthetic-history-session", "deepseek-v4-flash", {
            "model": "deepseek-v4-flash", "stream": True,
            "messages": [{"role": "user", "content": "Synthetic coding history"}],
            "max_tokens": 64, "stream_options": {"include_usage": True}})
        history.finish(ticket, error_code="UNKNOWN")
        gate = GoSingleSmokeCampaign.create(str(path) + ".budget.sqlite", history_path=path,
            campaign_id="synthetic-continuation", owner_id="alice", confirmation_id="synthetic-confirmation",
            expires_at=time.time() + 3600)
        gate.authorize("synthetic-diagnostic-session", MODEL, owner_id="alice")
        stream = SyntheticStream(chunks, error)
        transport = Mock(return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream))
        credential = Mock(return_value="synthetic-nonsecret-placeholder")
        model = GoDevelopmentModel(model_id=MODEL, session_id="synthetic-diagnostic-session", credential=credential,
            live_campaign=gate, wire_stream=True, native_retries=0, max_output_tokens=64,
            async_transport=httpx.MockTransport(transport))
        return gate, model, transport, credential, stream

    async def failure(self, chunks, *, error=None, error_type="ModelProviderError", category="protocol",
                      stage="RESPONSE_HEADERS", stop="UNKNOWN"):
        gate, model, transport, credential, stream = self.fixture(chunks, error=error)
        with self.assertRaises(ModelProviderError):
            await model.ainvoke([Message(role="user", content="Synthetic coding diagnostic")])
        facts = gate.inspect()
        records = facts["diagnostics"]["events"]
        header = next(row for row in records if row["phase"] == "RESPONSE_HEADERS" and "httpStatus" in row)
        self.assertEqual(header["httpStatus"], 200)
        self.assertEqual(header["responseHeaders"]["contentType"], "event-stream")
        self.assertEqual((records[-2]["phase"], records[-2]["errorType"], records[-2]["errorCategory"]),
                         (stage, error_type, category))
        self.assertEqual((records[-1]["phase"], records[-1]["errorType"], records[-1]["errorCategory"]),
                         ("FAILED", error_type, category))
        self.assertEqual("STREAM_COMPLETED" in [row["phase"] for row in records], stage == "STREAM_COMPLETED")
        self.assertNotIn("PARSED", [row["phase"] for row in records])
        self.assertEqual((facts["status"], facts["stopCode"]), ("STOPPED", stop))
        self.assertEqual(facts["requestCount"], 2)
        self.assertEqual(facts["tickets"][-1]["state"], "UNKNOWN")
        self.assertIsNone(facts["tickets"][-1]["total_tokens"])
        self.assertNotIn(SYNTHETIC_TEXT, json.dumps(facts))
        transport.assert_called_once()
        credential.assert_called_once()
        self.assertTrue(stream.closed)
        return facts

    async def test_protocol_checks_share_the_observed_pre_eof_failure_signature(self):
        # Every case below has the same retained signature. A historical record
        # with that signature cannot distinguish these branches.
        cases = {
            "application_error": event({"error": {"message": SYNTHETIC_TEXT}}),
            "null_error_field": event({**choice(reason="stop"), "error": None}),
            "premature_usage": event({**choice(), "usage": USAGE}),
            "conflicting_repeated_usage": terminal() + event({"choices": [], "usage": USAGE}) + event({"choices": [], "usage": {**USAGE, "completion_tokens": 4, "total_tokens": 9}}),
            "choice_after_terminal": terminal() + event(choice(content="later synthetic content")),
            "data_after_done": complete() + event({"choices": []}),
            "multiple_choices": event({"choices": [choice()["choices"][0], choice(index=1)["choices"][0]]}),
            "nonzero_choice_index": event(choice(index=1)),
            "invalid_tool_type": event({"choices": [{"delta": {"tool_calls": [{"index": 0, "type": "shell"}]}}]}),
            "invalid_tool_index": event({"choices": [{"delta": {"tool_calls": [{"index": -1}]}}]}),
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                await self.failure([payload])

    async def test_size_bound_is_also_a_pre_eof_protocol_failure(self):
        await self.failure([b":" + b"x" * MAX_BYTES + b"\n"])

    async def test_model_change_has_same_phase_and_type_but_distinct_stop_code(self):
        await self.failure([event(choice()), event({"model": "deepseek-v4.1-flash", "choices": []})],
                           stop="MODEL_MISMATCH")

    async def test_transport_truncation_has_a_distinct_error_type(self):
        for error, kind, category in ((httpx.ReadError("synthetic truncation"), "ReadError", "read"),
                                      (httpx.RemoteProtocolError("synthetic truncation"), "RemoteProtocolError", "protocol")):
            with self.subTest(error_type=kind):
                await self.failure([event(choice())], error=error, error_type=kind, category=category)

    async def test_graceful_eof_without_done_fails_after_stream_completed(self):
        await self.failure([terminal(), event({"choices": [], "usage": USAGE})], stage="STREAM_COMPLETED")

    async def test_unterminated_partial_json_line_fails_at_eof_not_during_feed(self):
        await self.failure([b'data: {"choices":'], stage="STREAM_COMPLETED")

    async def test_invalid_json_with_newline_is_a_parse_failure_before_eof(self):
        await self.failure([b"data: {" + SYNTHETIC_TEXT.encode() + b"}\n\n"],
                           error_type="JSONDecodeError", category="parse")

    async def test_valid_multiline_data_event_is_currently_rejected_as_json(self):
        # SSE concatenates data fields with a newline before dispatching an
        # event. This combined JSON is valid; the current parser decodes each
        # data line separately. Characterization, not a claim about live bytes.
        parts = [b'{"model":"deepseek-flash",',
                 b'"choices":[{"index":0,"delta":{"content":"synthetic"},"finish_reason":"stop"}]}']
        self.assertEqual(json.loads(b"\n".join(parts))["model"], MODEL)
        payload = b"".join(b"data: " + part + b"\n" for part in parts) + b"\n"
        await self.failure([payload], error_type="JSONDecodeError", category="parse")

    async def test_done_before_terminal_choice_is_distinguished_by_eof_stage(self):
        await self.failure([b"data: [DONE]\n\n"], stage="STREAM_COMPLETED")

    async def test_valid_chunk_fragmentation_and_comments_do_not_fail(self):
        payload = b": synthetic heartbeat\r\n\r\n" + complete().replace(b"\n", b"\r\n")
        chunks = [payload[index:index + 7] for index in range(0, len(payload), 7)]
        gate, model, transport, _, stream = self.fixture(chunks)
        result = await model.ainvoke([Message(role="user", content="Synthetic coding diagnostic")])
        self.assertEqual(result.response_usage.total_tokens, 8)
        self.assertEqual(gate.inspect()["tickets"][-1]["state"], "SETTLED")
        self.assertEqual(gate.inspect()["diagnostics"]["events"][-1]["phase"], "PARSED")
        transport.assert_called_once()
        self.assertTrue(stream.closed)

    async def test_duplicate_done_is_currently_accepted_without_extra_dispatch(self):
        gate, model, transport, _, _ = self.fixture([complete() + b"data: [DONE]\n\n"])
        result = await model.ainvoke([Message(role="user", content="Synthetic coding diagnostic")])
        self.assertEqual(result.response_usage.total_tokens, 8)
        self.assertEqual(gate.inspect()["requestCount"], 2)
        self.assertEqual(gate.inspect()["tickets"][-1]["state"], "SETTLED")
        transport.assert_called_once()


if __name__ == "__main__":
    unittest.main()

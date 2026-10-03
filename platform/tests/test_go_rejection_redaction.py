"""Synthetic rejection metadata/exception-chain redaction. No HTTP or credentials."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import httpx
from agno.exceptions import ModelProviderError

from agent_factory.go_diagnostics import annotate_go_error, safe_diagnostic
from agent_factory.go_live_events import GoDiagnosticJournal

PRIVATE = "PRIVATE_BODY_PROMPT_HEADER_EXCEPTION_SENTINEL"


class GoRejectionRedactionTests(unittest.TestCase):
    def assert_redacted(self, value):
        serialized = json.dumps(value)
        self.assertNotIn(PRIVATE, serialized)
        self.assertNotIn("authorization", serialized.lower())
        self.assertNotIn("x-request-id", serialized.lower())

    def test_known_code_preserves_identity_and_existing_error_category(self):
        for error, code, kind, category in (
                (httpx.ReadError(PRIVATE), "TRANSPORT_READ", "ReadError", "read"),
                (json.JSONDecodeError(PRIVATE, PRIVATE, 0), "JSON_DECODE", "JSONDecodeError", "parse"),
                (ValueError(PRIVATE), "STREAM_USAGE_EARLY", "ValueError", "parse")):
            with self.subTest(code=code):
                self.assertIs(annotate_go_error(error, rejection_code=code), error)
                result = safe_diagnostic("FAILED", error=error)
                self.assertEqual(result["rejectionCode"], code)
                self.assertEqual((result["errorType"], result["errorCategory"]), (kind, category))
                self.assertIn(kind, result["exceptionChain"])
                self.assert_redacted(result)

    def test_cause_attached_when_raising_remains_visible_after_annotation(self):
        error = ModelProviderError(PRIVATE)
        annotate_go_error(error, rejection_code="CHAT_ERROR")
        try:
            raise error from httpx.ReadError(PRIVATE)
        except ModelProviderError as caught:
            facts = safe_diagnostic("FAILED", error=caught)
        self.assertEqual(facts["exceptionChain"], ["ModelProviderError", "ReadError"])
        self.assertEqual(facts["rejectionCode"], "CHAT_ERROR")
        self.assert_redacted(facts)

    def test_wrapping_preserves_original_code_safe_chain_and_legacy_category(self):
        original = json.JSONDecodeError(PRIVATE, PRIVATE, 0)
        annotate_go_error(original, rejection_code="JSON_DECODE")
        wrapped = ModelProviderError(PRIVATE)
        self.assertIs(annotate_go_error(wrapped, original_error=original), wrapped)
        result = safe_diagnostic("FAILED", error=wrapped)
        self.assertEqual(result["rejectionCode"], "JSON_DECODE")
        self.assertEqual((result["errorType"], result["errorCategory"]), ("JSONDecodeError", "parse"))
        self.assertIn("ModelProviderError", result["exceptionChain"])
        self.assertIn("JSONDecodeError", result["exceptionChain"])
        self.assert_redacted(result)

    def test_dynamic_names_and_properties_cannot_execute_or_escape(self):
        class Dangerous(ModelProviderError):
            def __str__(self):
                raise AssertionError("Must not stringify")
            def __repr__(self):
                raise AssertionError("Must not repr")
            @property
            def _go_diagnostic(self):
                raise AssertionError("Must not invoke metadata properties")
            @property
            def _go_rejection_code(self):
                raise AssertionError("Must not invoke rejection properties")
            @property
            def _go_exception_chain(self):
                raise AssertionError("Must not invoke chain properties")
            @property
            def __cause__(self):
                raise AssertionError("Must not invoke cause properties")
            @property
            def __context__(self):
                raise AssertionError("Must not invoke context properties")
        Dangerous.__name__ = PRIVATE
        error = Dangerous(PRIVATE)
        result = safe_diagnostic("FAILED", error=error)
        self.assert_redacted(result)
        self.assertLessEqual(len(result["exceptionChain"]), 6)

    def test_forged_metadata_revalidated_on_every_read(self):
        for forged_code in (PRIVATE, True, ["JSON_DECODE"], {"code": "JSON_DECODE"}):
            error = ModelProviderError(PRIVATE)
            annotate_go_error(error, rejection_code="JSON_DECODE")
            error.__dict__["_go_rejection_code"] = forged_code
            error.__dict__["_go_exception_chain"] = (PRIVATE, "ReadError")
            error.__dict__["_go_diagnostic"] = (PRIVATE, PRIVATE)
            result = safe_diagnostic("FAILED", error=error)
            self.assertIn(result.get("rejectionCode"), (None, "UNKNOWN_ERROR"))
            self.assertEqual(result["errorType"], "ModelProviderError")
            self.assertLessEqual(len(result["exceptionChain"]), 6)
            self.assert_redacted(result)

    def test_metadata_subclasses_cannot_supply_hash_equality_or_iteration(self):
        class DangerousString(str):
            def __hash__(self):
                raise AssertionError("Must not hash subclass metadata")
            def __eq__(self, other):
                raise AssertionError("Must not compare subclass metadata")
        class DangerousTuple(tuple):
            def __iter__(self):
                raise AssertionError("Must not iterate subclass metadata")
        error = ValueError(PRIVATE)
        error.__dict__["_go_rejection_code"] = DangerousString("JSON_DECODE")
        error.__dict__["_go_exception_chain"] = DangerousTuple((PRIVATE,))
        result = safe_diagnostic("FAILED", error=error)
        self.assertIn(result.get("rejectionCode"), (None, "UNKNOWN_ERROR"))
        self.assert_redacted(result)

    def test_cause_context_cycle_and_long_chain_are_bounded(self):
        first, second = ValueError(PRIVATE), httpx.ReadError(PRIVATE)
        first.__cause__ = second
        second.__context__ = first
        result = safe_diagnostic("FAILED", error=first)
        self.assertIn("ValueError", result["exceptionChain"])
        self.assertIn("ReadError", result["exceptionChain"])
        self.assertLessEqual(len(result["exceptionChain"]), 6)
        for _ in range(100):
            parent = RuntimeError(PRIVATE)
            parent.__cause__ = first
            first = parent
        result = safe_diagnostic("FAILED", error=first)
        self.assertLessEqual(len(result["exceptionChain"]), 6)
        self.assert_redacted(result)

    def test_cancellation_category_and_credential_phase_are_not_overwritten(self):
        cancel = asyncio.CancelledError(PRIVATE)
        annotate_go_error(cancel, rejection_code="UNKNOWN_ERROR")
        result = safe_diagnostic("FAILED", error=cancel)
        self.assertEqual(result["errorCategory"], "cancel")
        error = KeyError(PRIVATE)
        annotate_go_error(error, rejection_code="JSON_DECODE")
        self.assertEqual(safe_diagnostic("CREDENTIAL_CHECK", error=error)["errorCategory"], "credential")

    def test_group_children_are_not_traversed_and_causal_spine_stays_bounded(self):
        group = ExceptionGroup(PRIVATE, [ValueError(PRIVATE) for _ in range(100)])
        group.__cause__ = httpx.ReadError(PRIVATE)
        result = safe_diagnostic("FAILED", error=group)
        self.assertEqual(result["exceptionChain"], ["ExceptionGroup", "ReadError"])
        self.assert_redacted(result)

    def test_invalid_annotation_and_oversized_stored_chain_are_revalidated(self):
        error = ValueError(PRIVATE)
        annotate_go_error(error, rejection_code=PRIVATE)
        self.assertEqual(safe_diagnostic("FAILED", error=error)["rejectionCode"], "UNKNOWN_ERROR")
        for forged in (("ReadError",) * 7, ["ReadError"], (), ("ReadError", PRIVATE)):
            error.__dict__["_go_exception_chain"] = forged
            result = safe_diagnostic("FAILED", error=error)
            self.assertEqual(result["exceptionChain"], ["ValueError"])
            self.assert_redacted(result)

    def test_exception_dict_subclass_hooks_are_bypassed_without_losing_annotation(self):
        class Trap(dict):
            def get(self, *args):
                raise AssertionError("Must bypass dict read hooks")
            def __setitem__(self, key, value):
                raise AssertionError("Must bypass dict write hooks")
        original = httpx.ReadError(PRIVATE)
        original.__dict__ = Trap()
        annotate_go_error(original, rejection_code="TRANSPORT_READ")
        self.assertEqual(dict.get(original.__dict__, "_go_rejection_code"), "TRANSPORT_READ")
        wrapped = ModelProviderError(PRIVATE)
        wrapped.__dict__ = Trap()
        annotate_go_error(wrapped, original_error=original)
        self.assertEqual(dict.get(wrapped.__dict__, "_go_rejection_code"), "TRANSPORT_READ")
        result = safe_diagnostic("FAILED", error=wrapped)
        self.assertEqual(result["rejectionCode"], "TRANSPORT_READ")
        self.assertEqual(result["exceptionChain"], ["ModelProviderError", "ReadError"])
        self.assertEqual((result["errorType"], result["errorCategory"]), ("ReadError", "read"))
        self.assert_redacted(result)

    @unittest.skipUnless(os.name == "posix", "Private POSIX diagnostic journal")
    def test_rejection_and_chain_persist_at_real_journal_stage_without_source_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite"
            journal = GoDiagnosticJournal.create(path, "synthetic-redaction")
            ticket = str(uuid4())
            journal.record(ticket, "PREPARED")
            original = httpx.ReadError(PRIVATE)
            annotate_go_error(original, rejection_code="TRANSPORT_READ")
            wrapped = ModelProviderError(PRIVATE)
            annotate_go_error(wrapped, original_error=original)
            journal.record(ticket, "FAILED", error=wrapped, response_headers={
                "authorization": PRIVATE, "x-request-id": PRIVATE,
                "content-type": PRIVATE, "retry-after": PRIVATE})
            reopened = GoDiagnosticJournal(path).inspect()
            self.assertEqual([row["phase"] for row in reopened["events"]], ["PREPARED", "FAILED"])
            failure = reopened["events"][-1]
            self.assertEqual(failure["rejectionCode"], "TRANSPORT_READ")
            self.assertIn("ReadError", failure["exceptionChain"])
            self.assert_redacted(reopened)
            self.assertNotIn(PRIVATE.encode(), path.read_bytes())

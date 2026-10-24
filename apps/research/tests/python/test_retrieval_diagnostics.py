"""Offline adapter failure facts retain bounded diagnostics without command text."""
import json
import unittest

from agent_factory_research.openresearch import CommandResult, OpenResearchError
from agent_factory_research.retrieval_diagnostics import safe_retrieval_diagnostic

PRIVATE = "private-token https://user:password@example.invalid/?secret=hidden"


def command(returncode=1):
    return CommandResult((PRIVATE,), PRIVATE, PRIVATE, returncode, 1.25, PRIVATE)


class RetrievalDiagnosticsTests(unittest.TestCase):
    def test_exact_codes_and_stages_only_with_no_transport_inference(self):
        for stage in ("discover", "paper", "text"):
            for code, category in (("COMMAND_FAILED", "command-exit"), ("TIMEOUT", "deadline"), ("OUTPUT_LIMIT", "output-bound")):
                with self.subTest(stage=stage, code=code):
                    error = OpenResearchError(code, PRIVATE + " DNS TLS ECONNREFUSED", command())
                    error.__cause__ = RuntimeError(PRIVATE)
                    facts = safe_retrieval_diagnostic(error, stage)
                    self.assertEqual(facts, {"schema": 1, "stage": stage, "code": code,
                        "failureClass": category, "transportCause": "UNKNOWN", "exitCode": 1})
                    self.assertNotIn(PRIVATE, json.dumps(facts))

    def test_unclassified_adapter_failure_does_not_copy_message_or_guess_transport(self):
        error = OpenResearchError("INVALID_OUTPUT", PRIVATE + " DNS TLS ECONNREFUSED")
        self.assertEqual(safe_retrieval_diagnostic(error, "discover"), {"schema": 1, "stage": "discover",
            "code": "UNKNOWN", "failureClass": "unknown", "transportCause": "UNKNOWN"})

    def test_native_exit_and_signal_codes_preserved_when_command_result_exists(self):
        for value in (-9, 0, 1, 255):
            with self.subTest(returncode=value):
                facts = safe_retrieval_diagnostic(OpenResearchError("COMMAND_FAILED", PRIVATE, command(value)), "text")
                self.assertEqual(facts["exitCode"], value)
        facts = safe_retrieval_diagnostic(OpenResearchError("TIMEOUT", PRIVATE), "text")
        self.assertNotIn("exitCode", facts)

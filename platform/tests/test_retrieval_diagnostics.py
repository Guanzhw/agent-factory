"""No networking or credentials: finite diagnostics from hostile synthetic objects."""
import json
import unittest
from typing import Any
from unittest.mock import patch

from agent_factory.openresearch import CommandResult, OpenResearchError
from agent_factory.retrieval_diagnostics import safe_retrieval_diagnostic

PRIVATE = "private-token https://user:password@example.invalid/?secret=hidden"


def command(returncode: Any = 1):
    return CommandResult((PRIVATE,), PRIVATE, PRIVATE, returncode, 1.25, PRIVATE)


class RetrievalDiagnosticsTests(unittest.TestCase):
    def test_exact_codes_and_stages_only_with_no_transport_inference(self):
        for stage in ("discover", "paper", "text"):
            for code, category in (("COMMAND_FAILED", "command-exit"), ("TIMEOUT", "deadline"), ("OUTPUT_LIMIT", "output-bound")):
                with self.subTest(stage=stage, code=code):
                    facts = safe_retrieval_diagnostic(OpenResearchError(code, PRIVATE + " DNS TLS ECONNREFUSED", command()), stage)
                    self.assertEqual(facts, {"schema": 1, "stage": stage, "code": code,
                        "failureClass": category, "transportCause": "UNKNOWN", "exitCode": 1})
                    self.assertNotIn(PRIVATE, json.dumps(facts))

    def test_unknown_error_code_is_never_copied(self):
        for code in (PRIVATE, "AUTH", None, [], {}, True, 1):
            error = OpenResearchError("COMMAND_FAILED", PRIVATE)
            error.__dict__["code"] = code
            self.assertEqual(safe_retrieval_diagnostic(error, "discover"), {"schema": 1, "stage": "discover",
                "code": "UNKNOWN", "failureClass": "unknown", "transportCause": "UNKNOWN"})

    def test_exit_code_requires_exact_bounded_integer(self):
        for value in (-255, -9, 0, 1, 255):
            self.assertEqual(safe_retrieval_diagnostic(OpenResearchError("COMMAND_FAILED", PRIVATE, command(value)), "text")["exitCode"], value)
        for value in (-256, 256, 2**128, True, 1.0, "1", PRIVATE, None, [], {}):
            self.assertNotIn("exitCode", safe_retrieval_diagnostic(OpenResearchError("COMMAND_FAILED", PRIVATE, command(value)), "text"))

    def test_foreign_errors_and_error_subclasses_are_not_inspected(self):
        class HostileError(OpenResearchError):
            def __getattribute__(self, name):
                raise AssertionError("property access forbidden")
            def __str__(self):
                raise AssertionError("string access forbidden")
            def __repr__(self):
                raise AssertionError("repr access forbidden")
        class HostileObject:
            def __getattribute__(self, name):
                raise AssertionError("foreign properties forbidden")
        for error in (HostileError("COMMAND_FAILED", PRIVATE, command()), HostileObject(), RuntimeError(PRIVATE), None):
            facts = safe_retrieval_diagnostic(error, "paper")
            self.assertEqual(facts["code"], "UNKNOWN")
            self.assertEqual(set(facts), {"schema", "stage", "code", "failureClass", "transportCause"})

    def test_command_subclass_or_lookalike_properties_never_run(self):
        class HostileCommand(CommandResult):
            def __getattribute__(self, name):
                raise AssertionError("command properties forbidden")
        class Lookalike:
            @property
            def returncode(self):
                raise AssertionError("lookalike returncode forbidden")
        for value in (HostileCommand((), PRIVATE, PRIVATE, 1, 1.0, PRIVATE), Lookalike(), {"returncode": 1}, PRIVATE):
            error = OpenResearchError("COMMAND_FAILED", PRIVATE)
            error.__dict__["result"] = value
            self.assertNotIn("exitCode", safe_retrieval_diagnostic(error, "discover"))

    def test_direct_dict_reads_bypass_malicious_get_hooks_and_missing_fields(self):
        class HostileDict(dict):
            def get(self, *args, **kwargs):
                raise AssertionError("dictionary hook forbidden")
        error = OpenResearchError("COMMAND_FAILED", PRIVATE, command())
        error.__dict__ = HostileDict(error.__dict__)
        self.assertEqual(safe_retrieval_diagnostic(error, "discover")["exitCode"], 1)
        error.__dict__.clear()
        self.assertEqual(safe_retrieval_diagnostic(error, "discover")["code"], "UNKNOWN")

    def test_known_objects_do_not_read_messages_output_args_or_exception_chain(self):
        error = OpenResearchError("COMMAND_FAILED", PRIVATE, command())
        error.__cause__ = RuntimeError(PRIVATE)
        with patch.object(OpenResearchError, "__str__", side_effect=AssertionError("no strings")), \
                patch.object(CommandResult, "stdout", new=property(lambda _: self.fail("no stdout")), create=True), \
                patch.object(CommandResult, "stderr", new=property(lambda _: self.fail("no stderr")), create=True), \
                patch.object(CommandResult, "argv", new=property(lambda _: self.fail("no argv")), create=True):
            facts = safe_retrieval_diagnostic(error, "discover")
        self.assertEqual(facts["transportCause"], "UNKNOWN")
        self.assertNotIn("private", json.dumps(facts))

    def test_invalid_stage_fails_with_fixed_non_echoing_message(self):
        class HostileStage(str):
            def __hash__(self):
                raise AssertionError("no subclass hash")
        for stage in (PRIVATE, "DISCOVER", None, [], {}, HostileStage("discover")):
            with self.assertRaises(ValueError) as caught:
                safe_retrieval_diagnostic(OpenResearchError("COMMAND_FAILED", PRIVATE), stage)
            self.assertEqual(str(caught.exception), "Unsupported retrieval diagnostic stage")

"""Offline runner admission, replay and safe-report contracts; no real model calls."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "run_go_project_workflow.py"
spec = importlib.util.spec_from_file_location("go_project_workflow", _RUNNER)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GoProjectWorkflowTests(unittest.TestCase):
    def proof(self, **changes):
        ticket = dict(model="deepseek-flash", actual_model="deepseek-flash", purpose="smoke",
                      state="SETTLED", error_code=None, ordinal=4)
        ticket.update(changes)
        return {"ownerId": "alice", "projectPolicy": {"historicalCount": 3}, "tickets": [ticket]}

    def args(self, root):
        return argparse.Namespace(model="deepseek-flash", campaign="existing-only", evidence_directory=root,
                                  database_url="not-read-by-offline-contract")

    def test_only_current_exact_settled_smoke_allows_product(self):
        runner.check_smoke(self.proof(), "deepseek-flash")
        for change in ({"ordinal": 3}, {"state": "UNKNOWN"}, {"error_code": "PROTOCOL"},
                       {"actual_model": "deepseek-v4-flash"}, {"purpose": "product"},
                       {"model": "gpt-6-luna"}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                runner.check_smoke(self.proof(**change), "deepseek-flash")
        with self.assertRaises(RuntimeError):
            runner.check_smoke({"ownerId": "alice", "tickets": self.proof()["tickets"]}, "deepseek-flash")

    def test_usage_selection_does_not_echo_untrusted_fields(self):
        usage = {"attempts": [{"state": "SETTLED", "provider": "private-payload"},
                              {"state": "private-payload"}],
                 "scopes": [{"scope": "task", "settledTokens": 12, "heldTokens": 0,
                             "description": "private-payload"}, {"scope": "private-payload"}]}
        self.assertEqual(runner.safe_usage(usage), {"attempts": [{"state": "SETTLED"}, {"state": "UNKNOWN"}],
                         "scopes": [{"scope": "task", "settledTokens": 12, "heldTokens": 0}]})

    def test_runner_uses_existing_authority_once_and_stores_safe_failure(self):
        campaign = Mock()
        campaign.inspect.return_value = self.proof()
        factory = Mock(return_value=campaign)
        with tempfile.TemporaryDirectory() as root, \
                patch.dict(sys.modules, {"agent_factory.go_project_campaign": SimpleNamespace(GoProjectCampaign=factory)}), \
                patch.object(runner, "credential", side_effect=AssertionError) as secret, \
                patch.object(runner, "execute_product", side_effect=ValueError("private-payload")) as execute:
            result = runner.run(self.args(root))
            self.assertEqual(result["status"], "stopped")
            self.assertNotIn("private-payload", json.dumps(result))
            self.assertEqual(json.loads((Path(root) / "workflow-result.json").read_text()), result)
            second = runner.run(self.args(root))
            self.assertEqual(second["status"], "inspection-only")
            execute.assert_called_once()
            factory.assert_called_once_with("existing-only")
            secret.assert_not_called()
            campaign.preflight.assert_called_once_with("deepseek-flash", "alice")
            campaign.create.assert_not_called()

    def test_missing_smoke_and_nonempty_directory_prevent_factory_setup(self):
        campaign = Mock()
        campaign.inspect.return_value = self.proof(state="UNKNOWN")
        with tempfile.TemporaryDirectory() as root, \
                patch.dict(sys.modules, {"agent_factory.go_project_campaign": SimpleNamespace(GoProjectCampaign=Mock(return_value=campaign))}), \
                patch.object(runner, "execute_product") as execute:
            with self.assertRaises(RuntimeError):
                runner.run(self.args(root))
            self.assertEqual(list(Path(root).iterdir()), [])
            (Path(root) / "unrelated").touch()
            with self.assertRaises(RuntimeError):
                runner.run(self.args(root))
            execute.assert_not_called()

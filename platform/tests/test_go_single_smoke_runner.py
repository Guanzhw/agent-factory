"""Offline operator orchestration tests: no credential callback or HTTP access."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "run_go_single_smoke.py"
spec = importlib.util.spec_from_file_location("go_single_smoke_runner", _RUNNER)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GoSingleSmokeRunnerTests(unittest.TestCase):
    def settled(self):
        return {"status": "DONE", "requestCount": 2, "budgetCounts": {"deepseek": 2},
                "tickets": [{"state": "SETTLED", "actual_model": "deepseek-flash", "error_code": None}]}

    def args(self, directory, **changes):
        values = dict(history_path=str(Path(directory) / "history.sqlite"),
            evidence_directory=str(Path(directory) / "evidence"),
            campaign_id="synthetic-campaign", owner_id="alice", confirmation_id="synthetic-attestation",
            execute_authorized_live=True, use_balance_off=True, auto_reload_off=True,
            synthetic_only=True, confirm_one_attempt=True, exact_model="deepseek-flash")
        values.update(changes)
        return argparse.Namespace(**values)

    def test_all_explicit_confirmations_and_exact_model_required_before_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            for change in ({name: False} for name in ("execute_authorized_live", "use_balance_off",
                    "auto_reload_off", "synthetic_only", "confirm_one_attempt")):
                with self.subTest(change=change), patch.object(runner, "GoSingleSmokeCampaign") as campaign, \
                     patch.object(runner, "credential", side_effect=AssertionError) as credential:
                    with self.assertRaises(ValueError):
                        runner.run(self.args(directory, **change))
                    campaign.create.assert_not_called()
                    credential.assert_not_called()
            for model in (None, "deepseek-v4-flash", "gpt-6-luna", "DEEPSEEK-FLASH"):
                with self.subTest(model=model), patch.object(runner, "GoSingleSmokeCampaign") as campaign:
                    with self.assertRaises(ValueError):
                        runner.run(self.args(directory, exact_model=model))
                    campaign.create.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_existing_derived_budget_is_inspection_only_without_new_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(directory, execute_authorized_live=False, exact_model=None)
            budget = Path(args.history_path + ".budget.sqlite")
            budget.write_bytes(b"synthetic-existing-budget")
            before = budget.read_bytes(), budget.stat().st_mtime_ns
            with patch.object(runner, "GoSingleSmokeCampaign") as campaign, \
                 patch.object(runner, "GoDevelopmentModel") as model, \
                 patch.object(runner, "credential", side_effect=AssertionError) as credential:
                campaign.return_value.inspect.return_value = {"requestCount": 2, "status": "stopped"}
                result = runner.run(args)
                self.assertEqual(result["execution"], "inspection-only")
                campaign.assert_called_once_with(budget)
                campaign.create.assert_not_called()
                model.assert_not_called()
                credential.assert_not_called()
            self.assertEqual(before, (budget.read_bytes(), budget.stat().st_mtime_ns))
            self.assertFalse(Path(args.evidence_directory).exists())

    def test_single_bounded_model_invocation_follows_create_and_authorize(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(directory)
            calls = []
            campaign = MagicMock()
            campaign.authorize.side_effect = lambda *a, **kw: calls.append("authorize")
            campaign.inspect.return_value = self.settled()
            model = MagicMock()
            async def invoke(messages):
                calls.append("invoke")
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0].content, runner.PUBLIC_PROMPT)
                return SimpleNamespace(content="never-persist-model-text")
            model.ainvoke = AsyncMock(side_effect=invoke)
            def create(*a, **kw):
                calls.append("create")
                self.assertEqual(a, (Path(args.history_path + ".budget.sqlite"),))
                self.assertEqual(kw["history_path"], Path(args.history_path))
                return campaign
            def build(**kw):
                calls.append("build")
                self.assertEqual(kw["model_id"], "deepseek-flash")
                self.assertEqual(kw["max_output_tokens"], 64)
                self.assertEqual(kw["native_retries"], 0)
                self.assertEqual(kw["timeout_seconds"], 60)
                self.assertIs(kw["wire_stream"], True)
                self.assertIs(kw["live_campaign"], campaign)
                self.assertEqual(kw["session_id"], campaign.authorize.call_args.args[0])
                return model
            with patch.object(runner.GoSingleSmokeCampaign, "create", side_effect=create), \
                 patch.object(runner, "GoDevelopmentModel", side_effect=build), \
                 patch.object(runner, "credential", side_effect=AssertionError) as credential:
                result = runner.run(args)
                credential.assert_not_called()
            self.assertEqual(calls, ["create", "authorize", "build", "invoke"])
            model.ainvoke.assert_awaited_once()
            campaign.authorize.assert_called_once_with(campaign.authorize.call_args.args[0],
                "deepseek-flash", purpose="smoke", owner_id="alice")
            self.assertEqual(result["status"], "completed")
            self.assertIsNone(result["monetaryUpperBound"])
            self.assertNotIn("never-persist", json.dumps(result))

    def test_failure_preserves_original_category_when_diagnostics_and_stop_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = MagicMock()
            campaign.journal.record.side_effect = [None, OSError("storage-private"), OSError("storage-private")]
            campaign.stop.side_effect = OSError("stop-private")
            campaign.inspect.side_effect = [{"status": "ACTIVE"}, OSError("inspect-private"), {"requestCount": 2}]
            model = MagicMock()
            model.ainvoke = AsyncMock(side_effect=TimeoutError("original-private"))
            with patch.object(runner.GoSingleSmokeCampaign, "create", return_value=campaign), \
                 patch.object(runner, "GoDevelopmentModel", return_value=model), \
                 patch.object(runner, "credential", side_effect=AssertionError) as credential:
                result = runner.run(self.args(directory))
                credential.assert_not_called()
            self.assertEqual(result["status"], "stopped")
            self.assertEqual(result["diagnostic"]["errorType"], "TimeoutError")
            self.assertNotIn("private", json.dumps(result))
            model.ainvoke.assert_awaited_once()
            campaign.stop.assert_called_once_with("UNKNOWN")
            campaign.inspect.assert_called_with(include_diagnostics=False)
            self.assertEqual([row["operation"] for row in result["diagnosticPersistence"]],
                ["campaign-stop", "RUNNER_FAILED", "RUNNER_STOPPED", "campaign-inspect"])

    def test_cancel_and_completed_diagnostic_failure_never_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            for error in (asyncio.CancelledError(), None):
                with self.subTest(cancelled=error is not None):
                    campaign = MagicMock()
                    campaign.inspect.return_value = self.settled()
                    if error is None:
                        campaign.journal.record.side_effect = [None, OSError("private"), None, None]
                    model = MagicMock()
                    model.ainvoke = AsyncMock(side_effect=error)
                    with patch.object(runner.GoSingleSmokeCampaign, "create", return_value=campaign), \
                         patch.object(runner, "GoDevelopmentModel", return_value=model):
                        result = runner.run(self.args(directory))
                    model.ainvoke.assert_awaited_once()
                    campaign.stop.assert_called_once_with("CANCELLED" if error else "UNKNOWN")
                    self.assertEqual(result["status"], "stopped")

    def test_failed_history_import_or_start_event_never_builds_model(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner.GoSingleSmokeCampaign, "create", side_effect=ValueError("invalid history")), \
                 patch.object(runner, "GoDevelopmentModel") as model:
                with self.assertRaises(ValueError):
                    runner.run(self.args(directory))
                model.assert_not_called()
            campaign = MagicMock()
            campaign.inspect.return_value = {"status": "ACTIVE", "requestCount": 1}
            campaign.journal.record.side_effect = OSError("private")
            with patch.object(runner.GoSingleSmokeCampaign, "create", return_value=campaign), \
                 patch.object(runner, "GoDevelopmentModel") as model:
                result = runner.run(self.args(directory))
                self.assertEqual(result["status"], "stopped")
                campaign.authorize.assert_not_called()
                model.assert_not_called()

    def test_existing_provider_stop_reason_is_preserved_without_another_request(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = MagicMock()
            campaign.inspect.return_value = {"status": "STOPPED", "stopCode": "AUTH", "requestCount": 2}
            model = MagicMock()
            model.ainvoke = AsyncMock(side_effect=ValueError("private"))
            with patch.object(runner.GoSingleSmokeCampaign, "create", return_value=campaign), \
                 patch.object(runner, "GoDevelopmentModel", return_value=model):
                result = runner.run(self.args(directory))
            self.assertEqual(result["campaign"]["stopCode"], "AUTH")
            campaign.stop.assert_not_called()
            model.ainvoke.assert_awaited_once()

    def test_normal_adapter_return_requires_durable_exact_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            for field, value in (("state", "UNKNOWN"), ("actual_model", "deepseek-v4-flash"),
                                 ("error_code", "MODEL_MISMATCH")):
                with self.subTest(field=field):
                    campaign = MagicMock()
                    facts = self.settled()
                    facts["tickets"][-1][field] = value
                    campaign.inspect.return_value = facts
                    model = MagicMock()
                    model.ainvoke = AsyncMock(return_value=SimpleNamespace(content="synthetic"))
                    with patch.object(runner.GoSingleSmokeCampaign, "create", return_value=campaign), \
                         patch.object(runner, "GoDevelopmentModel", return_value=model):
                        result = runner.run(self.args(directory))
                    self.assertEqual(result["status"], "stopped")
                    self.assertEqual(result["stoppedPhase"], "settlement-check")
                    model.ainvoke.assert_awaited_once()
                    self.assertNotIn("RUNNER_COMPLETED", [c.args[1] for c in campaign.journal.record.call_args_list])

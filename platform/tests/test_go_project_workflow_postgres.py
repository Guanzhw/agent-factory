# pyright: reportMissingImports=false
"""Actual project runner + Factory/Agno/Postgres; HTTP is strictly synthetic."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from agent_factory.go_project_campaign import GoProjectCampaign
from agent_factory.opencode_go import GoDevelopmentModel
from pg_fixture import IsolatedPostgres
from test_go_live_product_postgres import SyntheticCampaignPeer
import test_go_project_campaign as policy_helpers

_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "run_go_project_workflow.py"
spec = importlib.util.spec_from_file_location("go_project_workflow_pg", _RUNNER)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CodingPeer(SyntheticCampaignPeer):
    def reply(self, request):
        response = super().reply(request)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
            content=response.content.replace(b"synthetic Go development", runner.PUBLIC_CODE.encode()))


@unittest.skipUnless(os.name == "posix" and os.getenv("FACTORY_TEST_DATABASE_URL"),
                     "Requires POSIX policy fixtures and disposable loopback PostgreSQL")
class GoProjectWorkflowPostgresTests(unittest.TestCase):
    path: Path
    source: Path
    source_bytes: bytes
    history: list[dict]

    def setUp(self):
        # Opt the strictly fake provider/campaign fixture into compatibility
        # accounting. The actual operator runner retains disabled defaults.
        original_settings = runner.Settings
        settings_patch = patch.object(runner, 'Settings', side_effect=lambda **values:
            original_settings(**values, fee_management_enabled=True, platform_paid_models_enabled=True))
        settings_patch.start(); self.addCleanup(settings_patch.stop)
        # Reuse fixture construction only; do not inherit its policy unit tests.
        policy_helpers.ProjectCampaignTests.setUp(self)
        self.campaign = GoProjectCampaign.migrate(self.path, owner_id="alice", confirmation_id="synthetic-project")
        for model in runner.MODELS:
            session = "synthetic-smoke-" + model
            self.campaign.authorize(session, model, owner_id="alice")
            ticket = self.campaign.begin(session, model, policy_helpers.body(model))
            self.campaign.finish(ticket, usage={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}, actual_model=model)
        self.peer = CodingPeer()
        self.credential = Mock(return_value="offline-only-synthetic-credential")

    def test_both_exact_models_complete_real_native_workflow_with_nominal_accounting(self):
        def offline_model(**kwargs):
            self.assertIsNone(kwargs.pop("async_transport"))
            self.assertIs(type(kwargs["live_campaign"]), GoProjectCampaign)
            self.assertEqual(kwargs["native_retries"], 0)
            return GoDevelopmentModel(**kwargs, async_transport=self.peer.transport)

        with patch.object(runner, "credential", self.credential), \
                patch("agent_factory.go_development.GoDevelopmentModel", side_effect=offline_model):
            for model in runner.MODELS:
                with self.subTest(model=model), \
                        IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as database, \
                        tempfile.TemporaryDirectory(prefix="go-project-workflow-mock-") as root:
                    start = len(self.peer.requests)
                    args = argparse.Namespace(model=model, campaign=str(self.path), database_url=database.url,
                                              evidence_directory=root)
                    result = runner.run(args)
                    self.assertEqual(result["status"], "completed", result)
                    self.assertTrue(result["receiptVerified"])
                    self.assertEqual(result["nativeAttempts"], 1)
                    self.assertRegex(result["artifactSha256"], r"^[a-f0-9]{64}$")
                    self.assertEqual([a["state"] for a in result["usage"]["attempts"]], ["SETTLED", "SETTLED"])
                    self.assertEqual(result["usage"]["scopes"], [{"scope": "task", "settledTokens": 36, "heldTokens": 0}])
                    self.assertEqual(result["usage"]["pricingBasis"], "operator-nominal-not-invoice")
                    self.assertIs(result["usage"]["invoiceVerified"], False)
                    self.assertEqual(result["usage"]["actualCostStatus"], "UNKNOWN")
                    requests = self.peer.requests[start:]
                    self.assertEqual(len(requests), 2)
                    self.assertEqual([r["returnedTool"] for r in requests], [False, True])
                    self.assertEqual({r["model"] for r in requests}, {model})
                    self.assertEqual({r["session"] for r in requests}, {result["taskId"]})
                    self.assertTrue(all(r["product"] and r["stream"] for r in requests))
                    self.assertEqual(runner.run(args)["status"], "inspection-only")
                    self.assertEqual(len(self.peer.requests), start + 2)
        self.assertEqual(self.credential.call_count, 4)
        facts = self.campaign.inspect()
        self.assertEqual(facts["tickets"][:3], self.history)
        product = [t for t in facts["tickets"] if t["purpose"] == "product"]
        self.assertEqual(len(product), 4)
        self.assertTrue(all(t["state"] == "SETTLED" and t["actual_model"] == t["model"] for t in product))
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

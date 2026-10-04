# pyright: reportMissingImports=false
"""Native public coding research uses a newly pinned Luna output revision."""
import argparse
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent_factory.go_project_campaign import GoProjectCampaign
from agent_factory.go_usage import luna_512_pricing
from agent_factory.opencode_go import GoDevelopmentModel
from pg_fixture import IsolatedPostgres
import test_go_project_workflow_postgres as workflow
from test_public_coding_research_postgres import ResearchPeer
from test_public_code_knowledge import snapshot


@unittest.skipUnless(os.name == "posix" and os.getenv("FACTORY_TEST_DATABASE_URL"),
                     "Requires POSIX policy fixtures and disposable loopback PostgreSQL")
class PublicCodingRevisionPostgresTests(unittest.TestCase):
    campaign: GoProjectCampaign
    credential: Mock
    history: list[dict]

    def setUp(self):
        workflow.GoProjectWorkflowPostgresTests.setUp(self)
        self.peer = ResearchPeer()

    def test_luna_revision_two_pins_512_wire_cap_material_and_pricing(self):
        captured = {}
        original_create = workflow.runner.create_app
        def create_app(settings):
            app = original_create(settings)
            captured["state"] = app.app.state.factory
            return app
        def offline_model(**kwargs):
            self.assertIsNone(kwargs.pop("async_transport"))
            self.assertIs(type(kwargs["live_campaign"]), GoProjectCampaign)
            self.assertEqual(kwargs["model_id"], "gpt-6-luna")
            self.assertEqual(kwargs["max_output_tokens"], 512)
            self.assertEqual(kwargs["native_retries"], 0)
            return GoDevelopmentModel(**kwargs, async_transport=self.peer.transport)
        with IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as database, \
                tempfile.TemporaryDirectory(prefix="luna-revision-native-fixture-") as directory, \
                patch.object(workflow.runner, "credential", self.credential), \
                patch.object(workflow.runner, "create_app", side_effect=create_app), \
                patch("agent_factory.go_development.GoDevelopmentModel", side_effect=offline_model):
            args = argparse.Namespace(model="gpt-6-luna", database_url=database.url,
                                      evidence_directory=directory, luna_output_revision="2")
            result = workflow.runner.execute_product(self.campaign, args, research_snapshot=snapshot())
            self.assertEqual(result["status"], "completed", result)
            self.assertTrue(result["receiptVerified"])
            self.assertTrue(result["research"]["citationPresenceVerified"])
            self.assertEqual(result["research"]["sourceEvidenceMode"], "controlled-fixture")
            self.assertEqual(result["nativeAttempts"], 1)
            self.assertEqual(len(self.peer.bodies), 2)
            self.assertEqual([body["max_output_tokens"] for body in self.peer.bodies], [512, 512])
            self.assertEqual([body["model"] for body in self.peer.bodies], ["gpt-6-luna", "gpt-6-luna"])
            self.assertEqual([row["state"] for row in result["usage"]["attempts"]], ["SETTLED", "SETTLED"])
            store = captured["state"]["store"]
            plan = store.plan(result["planId"], "alice")
            model = plan["executionBindings"]["model"]
            self.assertEqual(model["revision"], "2")
            self.assertEqual(model["config"]["maxOutputTokens"], 512)
            material = next(m for m in store.materials(published_only=True)
                            if all(m[key] == value for key, value in model["materialRef"].items()))
            self.assertEqual(material["runtimeBinding"]["revision"], "2")
            self.assertEqual(material["runtimeBinding"]["config"]["maxOutputTokens"], 512)
            budget = plan["usageBudget"]
            price = luna_512_pricing()
            self.assertEqual(budget["adapterRevision"], "2")
            self.assertEqual(budget["pricingRevision"], price.revision)
            self.assertEqual(budget["pricingSha256"], price.sha256)
            self.assertEqual(budget["perAttemptOutputTokens"], 512)
            usage = store.usage_ledger.inspect("alice", result["taskId"])
            self.assertEqual(usage["commitment"], budget)
            self.assertEqual(usage["pricingBasis"], "operator-nominal-not-invoice")
            self.assertIs(usage["invoiceVerified"], False)
            self.assertEqual(usage["actualCostStatus"], "UNKNOWN")
            self.assertTrue(all(row["state"] == "SETTLED" for row in usage["attempts"]))
            self.assertEqual(next(s for s in usage["scopes"] if s["scope"] == "task")["heldTokens"], 0)
            self.assertEqual(store.plan(result["planId"], "alice"), plan)
            self.assertEqual(self.campaign.inspect()["tickets"][:3], self.history)
            self.credential.assert_called()
            self.assertEqual(self.credential.call_count, 2)
            store.engine.dispose()

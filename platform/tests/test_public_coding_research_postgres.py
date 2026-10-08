# pyright: reportMissingImports=false
"""Actual public-code Factory/Agno path with fixed snapshots and mocked HTTP."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from agent_factory.go_project_campaign import GoProjectCampaign
from agent_factory.opencode_go import GoDevelopmentModel
from agent_factory.public_code_knowledge import SOURCE_SET_ID
from agent_factory.public_coding_research import CHECKSUM_TEXT, INSTRUCTIONS
from pg_fixture import IsolatedPostgres
import test_go_project_workflow_postgres as workflow_helpers
from test_go_live_product_postgres import SyntheticCampaignPeer
from test_public_code_knowledge import snapshot

ANSWER = "The client verifies TLS and limits the destination while using managed proxy/CA settings [S1]. The synthetic test checks one proxy attempt without direct fallback [S2]."


class ResearchPeer(SyntheticCampaignPeer):
    def __init__(self):
        super().__init__()
        self.bodies = []
        self.encoded_sizes = []

    def reply(self, request):
        body = json.loads(request.content)
        self.bodies.append(body)
        # Match GoProjectCampaign's actual admission serialization, not HTTPX's
        # more compact wire JSON. This is the existing 8192-byte boundary.
        self.encoded_sizes.append(len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode()))
        response = super().reply(request)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=response.content
            .replace(b"synthetic Go development", CHECKSUM_TEXT.encode())
            .replace(b"Synthetic coding check complete.", ANSWER.encode()))


@unittest.skipUnless(os.name == "posix" and os.getenv("FACTORY_TEST_DATABASE_URL"),
                     "Requires POSIX policy fixtures and disposable loopback PostgreSQL")
class PublicCodingResearchPostgresTests(unittest.TestCase):
    campaign: GoProjectCampaign
    credential: Mock
    history: list[dict]

    def setUp(self):
        workflow_helpers.GoProjectWorkflowPostgresTests.setUp(self)
        self.peer = ResearchPeer()

    def test_both_protocols_receive_reviewed_sources_and_persist_cited_native_answer(self):
        campaign = self.campaign

        def offline_model(**kwargs):
            self.assertIsNone(kwargs.pop("async_transport"))
            self.assertIs(type(kwargs["live_campaign"]), GoProjectCampaign)
            self.assertEqual(kwargs["native_retries"], 0)
            return GoDevelopmentModel(**kwargs, async_transport=self.peer.transport)

        with patch.object(workflow_helpers.runner, "credential", self.credential), \
                patch("agent_factory.go_development.GoDevelopmentModel", side_effect=offline_model):
            for model in workflow_helpers.runner.MODELS:
                with self.subTest(model=model), \
                        IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as database, \
                        tempfile.TemporaryDirectory(prefix="public-code-native-fixture-") as root:
                    start = len(self.peer.requests)
                    args = argparse.Namespace(model=model, database_url=database.url, evidence_directory=root)
                    result = workflow_helpers.runner.execute_product(campaign, args, research_snapshot=snapshot())
                    self.assertEqual(result["status"], "completed", result)
                    self.assertTrue(result["receiptVerified"])
                    self.assertEqual(result["nativeAttempts"], 1)
                    self.assertRegex(result["artifactSha256"], r"^[a-f0-9]{64}$")
                    self.assertEqual([row["state"] for row in result["usage"]["attempts"]], ["SETTLED", "SETTLED"])
                    self.assertEqual(result["usage"]["scopes"], [{"scope": "task", "settledTokens": 36, "heldTokens": 0}])
                    research = result["research"]
                    self.assertEqual(research["sourceEvidenceMode"], "controlled-fixture")
                    self.assertEqual(research["sourceSetId"], SOURCE_SET_ID)
                    self.assertEqual(research["sourceCount"], 2)
                    self.assertTrue(research["citationPresenceVerified"])
                    self.assertEqual(research["semanticReview"], "required-separately")
                    self.assertEqual(research["answer"], ANSWER)
                    requests = self.peer.requests[start:]
                    self.assertEqual(len(requests), 2)
                    self.assertEqual([row["returnedTool"] for row in requests], [False, True])
                    self.assertEqual({row["session"] for row in requests}, {result["taskId"]})
                    for body, size in zip(self.peer.bodies[start:], self.peer.encoded_sizes[start:], strict=True):
                        self.assertLessEqual(size, 8192)
                        messages = body["input" if model == "gpt-6-luna" else "messages"]
                        serialized = json.dumps(messages)
                        self.assertIn(INSTRUCTIONS, serialized)
                        self.assertIn(SOURCE_SET_ID, serialized)
                        self.assertIn("go-http-policy", serialized)
                        self.assertIn("go-http-tests", serialized)
                        self.assertIn("test_proxy_failure_has_no_retry_or_direct_fallback", serialized)
                        self.assertIn("controlled-fixture", serialized)
                        self.assertEqual(len(body.get("tools", [])), 1)
                    self.assertEqual(campaign.inspect()["tickets"][:3], self.history)
        self.assertEqual(self.credential.call_count, 4)

# pyright: reportMissingImports=false
"""Actual Agno queue and PostgreSQL fixture; no live scientific model or retrieval."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_factory.literature_evidence import source_projection
from agent_factory.literature_synthesis import SCIENTIFIC_CAPABILITY, build_source_context, validate_synthesis_report
from agent_factory.literature_synthesis_profile import (APPLICATION_ID, CONNECTION_NAME, FIXTURE_PROVIDER,
    REGISTRATION_REF, TOOL_NAME, ScientificFixtureModel, registrations, publish_synthesis_application, synthesis_settings)
from agent_factory.execution_bindings import BindingContext
from agno.models.message import Message
from agno.run import RunContext
from agent_factory.main import create_app
from agent_factory.orx_literature_tools import evidence_record
from pg_fixture import IsolatedPostgres


def controlled_sources():
    record = evidence_record("123", "Synthetic bounded excerpt describes an observation, not a validated finding.",
        status="abstract_only", field="abstract")
    return {"schema": 1, "status": "ready", "evidenceKind": "controlled_literature_fixture",
        "mode": "bibliography-excerpts-no-provider", "sourceCount": 1,
        "sources": [source_projection({**record, "title": "Synthetic source title", "evidenceKind": "controlled_literature_fixture"})],
        "retrievalErrors": [], "reportArtifactId": None, "bundleArtifactId": None}


class LiteratureSynthesisProfileOfflineTests(unittest.TestCase):
    def test_native_instruction_bullets_and_validated_save_idempotency(self):
        question, sources = "Describe controlled evidence", controlled_sources()
        source_context = build_source_context(question, sources)
        model = ScientificFixtureModel(source_context)
        native_system = "- FACTORY_KNOWLEDGE_CONTEXT=" + json.dumps({"content": source_context.content})
        response = model.invoke([Message(role="system", content=native_system)])
        report = json.loads(response.tool_calls[0]["function"]["arguments"])["report"]
        context = RunContext(user_id="alice", session_id="task", run_id="run")
        store = Mock()
        store.effect_reserve.return_value = {"status": "new"}
        store.artifact_write.side_effect = [{"id": "json"}, {"id": "markdown"}]
        registration = next(item for item in registrations(question, sources) if item.kind == "tool")
        binding = BindingContext(SimpleNamespace(demo=True), store,
            {"ownerId": "alice", "application": APPLICATION_ID, "applicationRef": {"id": APPLICATION_ID},
             "mode": "controlled-fixture", "tools": [TOOL_NAME], "capabilities": ["research:read"]}, context,
            {"config": {"snapshotSha256": source_context.provenance["snapshotSha256"]}})
        function = registration.factory(binding)
        first = json.loads(function.entrypoint(run_context=context, report=report))
        store.effect_reserve.return_value = {"status": "done", "result": first}
        second = json.loads(function.entrypoint(run_context=context, report=report))
        self.assertEqual(first, second)
        self.assertEqual(store.artifact_write.call_count, 2)
        store.effect_complete.assert_called_once()
        altered = json.loads(json.dumps(report))
        altered["claims"][0]["sourceIds"] = ["not-selected"]
        with self.assertRaises(ValueError):
            function.entrypoint(run_context=context, report=altered)
        self.assertEqual(store.effect_reserve.call_count, 2)
        with self.assertRaises(ValueError):
            function.entrypoint(run_context=RunContext(user_id="bob", session_id="task", run_id="run"), report=report)
        self.assertEqual(store.artifact_write.call_count, 2)
        with self.assertRaises(ValueError):
            model.invoke([Message(role="user", content=native_system)])


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class LiteratureSynthesisProfilePostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix="literature-synthesis-fixture-")
        self.addCleanup(self.workspace.cleanup)
        self.question = "Describe what the controlled source record contains."
        self.sources = controlled_sources()
        settings = synthesis_settings(db_url=self.database.url, workspace=Path(self.workspace.name),
            question=self.question, evidence_projection=self.sources)
        application = create_app(settings)
        self.state = application.app.state.factory
        self.store = self.state["store"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(application).__enter__()  # type: ignore[arg-type]
        self.addCleanup(self.client.__exit__, None, None, None)
        auth = self.state["auth"]
        auth.authorization.unassign("bob", "factory-user")
        auth.authorization.assign("bob", "factory-manager")
        application = publish_synthesis_application(self.state, self.question, self.sources, author="manager", reviewer="bob")
        self.reference = {key: application[key] for key in ("id", "version", "sha256")}
        self.connection = self.state["connections"].bind("alice", REGISTRATION_REF, str(uuid4()),
            capabilities=[SCIENTIFIC_CAPABILITY])
        self.login("alice")

    def post(self, path, body, status=201):
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def login(self, owner):
        self.client.cookies.clear()
        self.post("/api/factory/demo/login", {"persona": owner}, 200)

    def run_task(self):
        proposal = self.post("/api/factory/compositions/proposals", {"goal": self.question,
            "mode": "controlled-fixture", "applicationRef": self.reference,
            "connectionRefs": {CONNECTION_NAME: self.connection["ref"]}, "requestId": str(uuid4())})
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal)
        plan = self.post(f"/api/factory/compositions/proposals/{proposal['id']}/accept", {"requestId": str(uuid4())})
        self.assertEqual(plan["application"], APPLICATION_ID)
        key = str(uuid4())
        task = self.post("/api/factory/instances", {"planId": plan["id"], "requestId": key}, 202)
        receipt = self.client.get("/api/factory/requests/" + key)
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.json()["taskId"], task["id"])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = self.client.get("/api/factory/jobs/" + task["id"])
            self.assertEqual(response.status_code, 200)
            detail = response.json()
            if detail["job"]["status"] in {"completed", "failed", "unknown", "cancelled"}:
                self.assertEqual(detail["job"]["status"], "completed", detail)
                return task["id"], detail
            time.sleep(.05)
        self.fail("Controlled native synthesis task did not settle")

    def test_native_injected_sources_report_artifacts_receipt_usage_and_owner_isolation(self):
        task, detail = self.run_task()
        artifacts = {row["name"]: row for row in detail["artifacts"]}
        self.assertEqual(set(artifacts), {"literature-synthesis.json", "literature-synthesis.md"})
        artifact = artifacts["literature-synthesis.json"]
        path = f"/api/factory/jobs/{task}/artifacts/{artifact['id']}"
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), artifact["sha256"])
        document = response.json()
        context = build_source_context(self.question, self.sources)
        self.assertEqual(document["snapshotSha256"], context.provenance["snapshotSha256"])
        self.assertTrue(document["citationIntegrityVerified"])
        self.assertEqual(document["semanticReview"], "required")
        self.assertEqual(document["evidenceKind"], "controlled_model_synthesis")
        self.assertFalse(document["scientificConclusionVerified"])
        self.assertIn("Synthetic source title", document["report"]["claims"][0]["text"])
        self.assertEqual(document["report"]["claims"][0]["quotes"][0]["text"], self.sources["sources"][0]["excerpt"])
        effects = self.store.effects(task)
        effect = next(row for row in effects if row["effect_key"].endswith(":literature-synthesis-report-v1"))
        self.assertEqual(effect["status"], "DONE")
        self.assertEqual(effect["result"]["originalReportSha256"], artifact["sha256"])
        usage = self.store.usage_ledger.inspect("alice", task)
        self.assertEqual(len(usage["attempts"]), 2, usage)
        self.assertEqual([row["state"] for row in usage["attempts"]], ["SETTLED", "SETTLED"])
        self.assertTrue(all(row["heldTokens"] == 0 and row["settledTokens"] == 0 for row in usage["scopes"]))
        # Adversarial citation is rejected by the same boundary used before save.
        malicious = json.loads(json.dumps(document["report"]))
        malicious["claims"][0]["sourceIds"] = ["unselected-source"]
        with self.assertRaises(ValueError):
            validate_synthesis_report(malicious, context, provider_id=FIXTURE_PROVIDER,
                capabilities=(SCIENTIFIC_CAPABILITY,), execution_mode="controlled-fixture")
        self.login("bob")
        self.assertIn(self.client.get(path).status_code, {403, 404})
        self.assertIn(self.client.get("/api/factory/jobs/" + task).status_code, {403, 404})


if __name__ == "__main__":
    unittest.main()

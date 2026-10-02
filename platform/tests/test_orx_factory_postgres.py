# pyright: reportMissingImports=false
"""Actual Factory/Agno/PostgreSQL ORX discovery integration using local fixtures.

Only the trusted adapter's discovery transport and DemoModel response are
synthetic. Main wiring, material/admin review, owner connection resolution,
application composition, native task queue, Agent tool loop, effects, and
artifact persistence remain the real Factory implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.connections import TrustedConnectionBinding
from agent_factory.main import create_app
from agent_factory.openresearch import BinaryPin, REVISION, VERSION
from agent_factory.orx_tools import (CAPABILITY, ORX_ADAPTER_ID, ORX_ADAPTER_REVISION,
    TOOL_NAME, register_orx_adapter)
from pg_fixture import IsolatedPostgres


APPROVED_BINARY_SHA256 = "d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7"


class ControlledORXAdapter:
    """No-network synthetic transport at the trusted OpenResearch boundary."""

    def __init__(self, owner_id, task_id, max_output_bytes, command_timeout):
        self.owner_id, self.task_id = owner_id, task_id
        self.pin = BinaryPin(REVISION, VERSION, APPROVED_BINARY_SHA256)
        self.enabled = True
        self.transport_kind = "controlled_transport_fixture"
        self.max_output_bytes = max_output_bytes
        self.command_timeout = command_timeout
        self._processes = set()
        self.calls = []

    async def discover(self, query, *, corpus, limit):
        self.calls.append({"query": query, "corpus": corpus, "limit": limit})
        return [{"source": "openalex", "id": "W-fixture-1",
                 "title": "Synthetic metadata fixture", "year": 2026}][:limit]


class ControlledORXProvider:
    """Operator-installed provider fixture. Never reaches a provider/network."""

    def __init__(self):
        self.created = []
        self.handle_marker = object()

    def create_adapter(self, *, owner_id, task_id, scope, authorize, pin,
                       max_output_bytes, command_timeout):
        adapter = ControlledORXAdapter(owner_id, task_id, max_output_bytes, command_timeout)
        self.created.append({"ownerId": owner_id, "taskId": task_id, "scope": scope,
                             "authorize": authorize, "pin": pin,
                             "maxOutputBytes": max_output_bytes,
                             "commandTimeout": command_timeout, "adapter": adapter})
        return adapter


def pin(material):
    return {key: material[key] for key in ("id", "version", "sha256")}


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class ORXNativeFactoryPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix="orx-native-factory-")
        self.addCleanup(self.workspace.cleanup)
        self.provider = ControlledORXProvider()
        self.registration_ref = "fixture-openresearch"
        self.trusted = TrustedConnectionBinding("alice", "orx", ORX_ADAPTER_ID,
            frozenset({CAPABILITY}), "controlled-transport-v1", available=True,
            opaque_handle=self.provider, handle_ref="synthetic-provider-handle-v1")
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.workspace.name),
            max_workers=1, max_tool_calls=4, experiment_timeout_seconds=10,
            experiment_output_bytes=65536, temporary_policy="read-only-auto",
            policy_revision="orx-plan-policy-v1", material_policy_revision="orx-material-policy-v1",
            runtime_tool_contract="registered-runtime-v1", material_review_mode="separate-admin",
            trusted_connections={self.registration_ref: self.trusted})
        self.application = create_app(self.settings)
        self.state = self.application.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        # This generated test database owns these native grants. The separately
        # authenticated Bob reviewer is deliberately elevated only in-fixture.
        self.auth.authorization.unassign("bob", "factory-user")
        self.auth.authorization.assign("bob", "factory-manager")
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(self.application).__enter__()  # type: ignore[arg-type]
        self.addCleanup(self.client.__exit__, None, None, None)
        bindings = self.state["execution_bindings"]
        if ("tool", ORX_ADAPTER_ID, ORX_ADAPTER_REVISION) not in bindings._adapters:
            register_orx_adapter(bindings)

    def login(self, persona):
        self.client.cookies.clear()
        result = self.client.post("/api/factory/demo/login", json={"persona": persona})
        self.assertEqual(result.status_code, 200, result.text)

    def test_approved_material_application_and_native_task_execute_discovery(self):
        seeds = {row["id"]: row for row in self.store.materials(published_only=True)}
        self.assertIn("demo-model", seeds)
        self.assertIn("local-environment", seeds)

        self.login("manager")
        material_response = self.client.post("/api/factory/material-governance/drafts", json={
            "requestId": "orx-tool-draft",
            "definition": {
                "id": "fixture-orx-discovery-tool", "kind": "tool",
                "name": "Synthetic OpenResearch discovery", "content": TOOL_NAME,
                "description": "Bounded read-only discovery integration fixture.",
                "license": "MIT", "compatibility": ["agno:3.1.0"],
                "permissions": [CAPABILITY], "dependencies": [],
                "runtimeBinding": {"adapterId": ORX_ADAPTER_ID,
                    "revision": ORX_ADAPTER_REVISION,
                    "config": {"connectionName": "literatureProvider"}},
                "provenance": {"kind": "original", "notice": "Synthetic controlled transport fixture."},
            }})
        self.assertEqual(material_response.status_code, 201, material_response.text)
        material = material_response.json()
        review = self.client.post("/api/factory/material-governance/reviews", json={
            "materialId": material["id"], "version": material["version"], "requestId": "orx-material-review"})
        self.assertEqual(review.status_code, 201, review.text)
        review_id = review.json()["id"]
        self.assertEqual(self.client.post(f"/api/factory/material-governance/reviews/{review_id}/decision",
            json={"approved": True, "requestId": "orx-material-self-review"}).status_code, 403)

        # A distinct native manager approves publication.
        self.login("bob")
        approved_material = self.client.post(f"/api/factory/material-governance/reviews/{review_id}/decision",
            json={"approved": True, "requestId": "orx-material-distinct-admin"})
        self.assertEqual(approved_material.status_code, 200, approved_material.text)
        material = next(row for row in self.store.materials(published_only=True)
                        if row["id"] == material["id"] and row["version"] == material["version"])

        self.login("bob")
        app_definition = {
            "id": "fixture-openresearch-application", "name": "Synthetic OpenResearch workflow",
            "description": "Local deterministic end-to-end adapter fixture.",
            "defaultMode": "literature", "discoveryKeywords": ["synthetic orx"],
            "modes": {"literature": {
                "materialRefs": [pin(seeds["demo-model"]), pin(seeds["local-environment"]), pin(material)],
                "capabilities": [CAPABILITY], "toolOrder": [TOOL_NAME],
                "connectionRequirements": [{"name": "literatureProvider", "kind": "orx",
                    "requiredCapabilities": [CAPABILITY], "required": True}],
                "budget": {"toolCalls": 3, "maxDepth": 1, "maxChildren": 1,
                    "experimentSeconds": 10, "outputBytes": 65536},
            }}
        }
        application_response = self.client.post("/api/factory/applications/drafts", json={
            "definition": app_definition, "requestId": "orx-application-draft"})
        self.assertEqual(application_response.status_code, 201, application_response.text)
        app = application_response.json()
        application_review = self.client.post(f"/api/factory/applications/{app['id']}/versions/{app['version']}/review",
            json={"requestId": "orx-application-review"})
        self.assertEqual(application_review.status_code, 201, application_review.text)
        application_review_id = application_review.json()["id"]
        self.assertEqual(self.client.post(f"/api/factory/applications/reviews/{application_review_id}/decision",
            json={"approved": True, "requestId": "orx-application-self-review"}).status_code, 403)
        self.login("manager")
        application_approved = self.client.post(f"/api/factory/applications/reviews/{application_review_id}/decision",
            json={"approved": True, "requestId": "orx-application-distinct-admin"})
        self.assertEqual(application_approved.status_code, 200, application_approved.text)

        connection = self.state["connections"].bind("alice", self.registration_ref,
            "orx-owner-connection", capabilities=[CAPABILITY])
        self.assertEqual(connection["status"], "active")
        public_connection = json.dumps(connection)
        self.assertNotIn(repr(self.provider), public_connection)
        self.assertNotIn("handle_ref", public_connection)

        self.login("alice")
        proposal = self.client.post("/api/factory/compositions/proposals", json={
            "goal": "Find synthetic retrieval augmented generation papers",
            "applicationRef": {"id": app["id"], "version": app["version"], "sha256": app["sha256"]},
            "connectionRefs": {"literatureProvider": connection["ref"]},
            "requestId": "orx-compose-proposal"})
        self.assertEqual(proposal.status_code, 201, proposal.text)
        self.assertEqual(proposal.json()["candidate"]["status"], "ready", proposal.json()["candidate"].get("missing"))
        accepted = self.client.post(f"/api/factory/compositions/proposals/{proposal.json()['id']}/accept",
            json={"requestId": "orx-compose-accept"})
        self.assertEqual(accepted.status_code, 201, accepted.text)
        plan = accepted.json()
        self.assertEqual(plan["executionBindings"]["tools"][0]["toolName"], TOOL_NAME)
        self.assertEqual(plan["executionBindings"]["tools"][0]["connection"]["version"], 1)

        admitted = self.client.post("/api/factory/instances", json={
            "planId": plan["id"], "requestId": "orx-native-task"})
        self.assertEqual(admitted.status_code, 202, admitted.text)
        task_id = admitted.json()["id"]
        deadline = time.monotonic() + 15
        detail = None
        while time.monotonic() < deadline:
            response = self.client.get("/api/factory/jobs/" + task_id)
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail["job"]["status"] in {"completed", "failed", "unknown", "cancelled"}:
                break
            time.sleep(0.04)
        if detail is None:
            self.fail("Native task did not reach a terminal state")
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(len(self.provider.created), 1)
        created = self.provider.created[0]
        self.assertEqual(created["ownerId"], "alice")
        self.assertEqual(created["taskId"], task_id)
        self.assertTrue(created["scope"].is_relative_to(Path(self.workspace.name).resolve()))
        self.assertLessEqual(created["maxOutputBytes"], plan["budget"]["outputBytes"] - 4096)
        self.assertLessEqual(created["commandTimeout"], 15)
        self.assertEqual(created["adapter"].calls, [{"query": plan["normalizedGoal"], "corpus": "openalex", "limit": 5}])

        events = self.store.events(task_id)
        self.assertTrue(any(event["type"] == "orx_discovery_started" for event in events))
        self.assertTrue(any(event["type"] == "orx_discovery_completed" for event in events))
        effects = self.store.sql("SELECT status,result FROM af_effects WHERE task_id=:task", task=task_id)
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["status"], "DONE")
        self.assertEqual(effects[0]["result"]["provenance"]["sourceRevision"], REVISION)
        artifact = next(row for row in detail["artifacts"] if row["name"].startswith("orx-discovery-"))
        raw = self.client.get(f"/api/factory/jobs/{task_id}/artifacts/{artifact['id']}")
        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact["sha256"])
        document = json.loads(raw.content)
        self.assertEqual(document["result"]["results"][0]["id"], "W-fixture-1")
        self.assertEqual(document["result"]["evidenceKind"], "controlled_transport_fixture")
        self.assertEqual(document["result"]["provenance"]["taskId"], task_id)
        self.assertEqual(document["result"]["provenance"]["connection"]["version"], 1)
        self.assertNotIn("binarySha256", document["result"]["provenance"])
        self.assertEqual(document["result"]["provenance"]["configuredBinarySha256"], APPROVED_BINARY_SHA256)
        self.assertNotIn(repr(self.provider), raw.text)


if __name__ == "__main__":
    unittest.main()

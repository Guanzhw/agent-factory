# pyright: reportMissingImports=false
"""Real Factory queue/PG/HTTP acceptance; synthetic loopback provider only.

These tests do not prove live Go entitlement, billing, or API compatibility.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.go_development import (CAPABILITY, CONNECTION_NAME, REGISTRATION_REF,
    GoDevelopmentHandle, application_definition, publish_go_development_models, trusted_model_binding)
from agent_factory.main import create_app
from agent_factory.usage_ledger import UsagePolicy
from go_http_fixture import GoHTTPFixture
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class GoProductPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix="go-product-")
        self.addCleanup(self.workspace.cleanup)
        self.peer = GoHTTPFixture().__enter__()
        self.addCleanup(self.peer.__exit__, None, None, None)

    def start(self, *, retries=0):
        handle = GoDevelopmentHandle(mode="fixture", async_transport=self.peer.transport,
                                     wire_stream=True, native_retries=retries)
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.workspace.name),
            development_profile="opencode-go", max_workers=1, max_tool_calls=3,
            temporary_policy="read-only-auto", policy_revision="go-test-policy-v1",
            material_policy_revision="go-test-material-v1", runtime_tool_contract="registered-runtime-v1",
            usage_policy=UsagePolicy(revision="go-fixture-usage-v1", task_amount_micros=1_000_000,
                user_amount_micros=10_000_000, task_token_limit=500_000, user_token_limit=2_000_000),
            trusted_connections={REGISTRATION_REF: trusted_model_binding("alice", handle)})
        self.open_application()
        auth = self.state["auth"]
        auth.authorization.unassign("bob", "factory-user")
        auth.authorization.assign("bob", "factory-manager")
        models = publish_go_development_models(self.state, author="manager", reviewer="bob")
        seeds = self.store.materials(published_only=True)
        checksum = next(row for row in seeds if row["kind"] == "tool" and row["content"] == "checksum")
        environment = next(row for row in seeds if row["id"] == "local-environment")
        self.login("bob")
        app = self.post("/api/factory/applications/drafts", {
            "definition": application_definition(models, checksum, environment), "requestId": str(uuid4())}, 201)
        review = self.post(f"/api/factory/applications/{app['id']}/versions/{app['version']}/review",
                           {"requestId": str(uuid4())}, 201)
        self.login("manager")
        self.post(f"/api/factory/applications/reviews/{review['id']}/decision",
                  {"approved": True, "requestId": str(uuid4())}, 200)
        self.app_ref = {key: app[key] for key in ("id", "version", "sha256")}
        self.connection = self.state["connections"].bind("alice", REGISTRATION_REF,
            str(uuid4()), capabilities=[CAPABILITY])
        self.login("alice")
        self.assertEqual(self.peer.requests, [], "publication/preflight must not dispatch HTTP")

    def open_application(self):
        application = create_app(self.settings)
        self.state = application.app.state.factory
        self.store = self.state["store"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(application).__enter__()  # type: ignore[arg-type]
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self, owner):
        self.client.cookies.clear()
        self.post("/api/factory/demo/login", {"persona": owner}, 200)

    def post(self, path, body, status):
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def plan(self, model):
        proposal = self.post("/api/factory/compositions/proposals", {
            "goal": "Validate synthetic coding output with checksum", "mode": model,
            "applicationRef": self.app_ref,
            "connectionRefs": {CONNECTION_NAME: self.connection["ref"]}, "requestId": str(uuid4())}, 201)
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal)
        return self.post(f"/api/factory/compositions/proposals/{proposal['id']}/accept",
                         {"requestId": str(uuid4())}, 201)

    def submit(self, model):
        plan = self.plan(model)
        key = str(uuid4())
        job = self.post("/api/factory/instances", {"planId": plan["id"], "requestId": key}, 202)
        receipt = self.client.get("/api/factory/requests/" + key)
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json()["taskId"], job["id"])
        return job["id"]

    def wait(self, task):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = self.client.get("/api/factory/jobs/" + task)
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail["job"]["status"] in {"completed", "failed", "unknown", "cancelled"}:
                return detail
            time.sleep(0.04)
        self.fail("Native Factory task did not settle within fixture deadline")

    def usage(self, task):
        return self.store.usage_ledger.inspect("alice", task)

    def assert_roundtrip(self, task, *, offset=0, retry=False):
        detail = self.wait(task)
        self.assertEqual(detail["job"]["status"], "completed", detail)
        requests = self.peer.requests[offset:]
        self.assertEqual(len(requests), 3 if retry else 2)
        self.assertEqual({row["session"] for row in requests}, {task})
        self.assertTrue(all(row["body"]["stream"] is True for row in requests))
        final = requests[-1]["body"]
        messages = final.get("input", final.get("messages", []))
        self.assertTrue(any(row.get("type") == "function_call_output" or row.get("role") == "tool"
                            for row in messages), messages)
        artifact = next(row for row in detail["artifacts"] if row["name"] == "checksum.json")
        download = self.client.get(f"/api/factory/jobs/{task}/artifacts/{artifact['id']}")
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(hashlib.sha256(download.content).hexdigest(), artifact["sha256"])
        self.assertIn(hashlib.sha256(b"synthetic Go development").hexdigest(), json.dumps(download.json()))
        usage = self.usage(task)
        attempts = usage["attempts"]
        self.assertEqual(len(attempts), len(requests), usage)
        self.assertEqual(len({row["id"] for row in attempts}), len(requests))
        self.assertEqual([row["state"] for row in attempts], ["UNKNOWN", "SETTLED", "SETTLED"] if retry
                         else ["SETTLED", "SETTLED"])
        task_scope = next(row for row in usage["scopes"] if row["scope"] == "task")
        self.assertEqual(task_scope["settledTokens"], 36)
        if retry:
            self.assertGreater(task_scope["heldTokens"], 0)
            self.assertGreater(task_scope["heldAmountMicros"], 0)
        else:
            self.assertEqual(task_scope["heldTokens"], 0)

    def test_chat_and_responses_native_factory_tool_roundtrip(self):
        self.start()
        for model in ("deepseek-v4-flash", "gpt-6-luna"):
            with self.subTest(model=model):
                offset = len(self.peer.requests)
                self.assert_roundtrip(self.submit(model), offset=offset)

    def assert_unknown(self, task):
        detail = self.wait(task)
        self.assertNotEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(detail["artifacts"], [])
        usage = self.usage(task)
        self.assertEqual([row["state"] for row in usage["attempts"]], ["UNKNOWN"])
        self.assertGreater(next(row for row in usage["scopes"] if row["scope"] == "task")["heldTokens"], 0)
        self.assertGreater(next(row for row in usage["scopes"] if row["scope"] == "task")["heldAmountMicros"], 0)
        return usage

    def test_quota_has_one_attempt_no_retry_and_no_artifact(self):
        self.peer.scenario = "quota"
        self.start(retries=1)
        task = self.submit("deepseek-v4-flash")
        before = self.assert_unknown(task)
        self.client.__exit__(None, None, None)
        self.open_application()
        self.login("alice")
        self.assertEqual(self.usage(task)["attempts"], before["attempts"])
        self.assertEqual(self.usage(task)["scopes"], before["scopes"])
        self.assertNotEqual(self.wait(task)["job"]["status"], "completed")
        self.assertEqual(len(self.peer.requests), 1)

    def test_partial_stream_stops_before_tool_and_holds_usage(self):
        self.peer.scenario = "partial_stream"
        self.start(retries=1)
        self.assert_unknown(self.submit("deepseek-v4-flash"))
        self.assertEqual(len(self.peer.requests), 1)

    def test_missing_usage_stops_before_tool_and_survives_app_restart(self):
        self.peer.scenario = "unknown_usage"
        self.start(retries=1)
        task = self.submit("gpt-6-luna")
        before = self.assert_unknown(task)
        self.client.__exit__(None, None, None)
        self.open_application()
        self.login("alice")
        after = self.usage(task)
        self.assertEqual(after["attempts"], before["attempts"])
        self.assertEqual(after["scopes"], before["scopes"])
        self.assertEqual(len(self.peer.requests), 1, "restart must not replay uncertain provider dispatch")

    def test_native_retry_gets_distinct_durable_attempt(self):
        self.peer.scenario = "retry"
        self.start(retries=1)
        self.assert_roundtrip(self.submit("deepseek-v4-flash"), retry=True)

    def test_exhausted_native_retries_cannot_be_expanded_by_queue(self):
        self.peer.scenario = "always503"
        self.start(retries=1)
        task = self.submit("deepseek-v4-flash")
        detail = self.wait(task)
        self.assertNotEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(detail["artifacts"], [])
        usage = self.usage(task)
        self.assertEqual([row["state"] for row in usage["attempts"]], ["UNKNOWN", "UNKNOWN"])
        self.assertEqual(len({row["id"] for row in usage["attempts"]}), 2)
        scope = next(row for row in usage["scopes"] if row["scope"] == "task")
        self.assertEqual(scope["settledTokens"], 0)
        self.assertGreater(scope["heldTokens"], 0)
        self.assertGreater(scope["heldAmountMicros"], 0)
        self.assertEqual(len(self.peer.requests), 2)
        self.assertEqual({row["session"] for row in self.peer.requests}, {task})

    def test_revoke_during_http_prevents_tool_and_second_dispatch(self):
        self.peer.release.clear()
        self.peer.block_after_tool_delta = True
        self.start()
        task = self.submit("deepseek-v4-flash")
        self.assertTrue(self.peer.tool_delta_sent.wait(10), "HTTP peer must send checksum tool intent before revocation")
        self.state["connections"].revoke("alice", self.connection["ref"], str(uuid4()))
        self.peer.release.set()
        detail = self.wait(task)
        self.assertNotEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(detail["artifacts"], [])
        usage = self.usage(task)
        self.assertEqual(len(usage["attempts"]), 1)
        # A completed HTTP response is still charged before the fresh authority
        # fence. Cancellation before response completion retains UNKNOWN instead.
        self.assertIn(usage["attempts"][0]["state"], {"SETTLED", "UNKNOWN"})
        scope = next(row for row in usage["scopes"] if row["scope"] == "task")
        self.assertGreater(scope["heldTokens"] + scope["settledTokens"], 0)
        self.assertEqual(len(self.peer.requests), 1)


if __name__ == "__main__":
    unittest.main()

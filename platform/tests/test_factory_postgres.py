"""Actual native queue/API tests; a fresh disposable PostgreSQL DB is required.

Set FACTORY_TEST_DATABASE_URL; never point this at a production database.
The deterministic model replaces only provider output, not runtime or queue.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from fastapi.testclient import TestClient

from pg_fixture import IsolatedPostgres
from agent_factory.config import Settings
from agent_factory.main import create_app


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class FactoryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.workspace = tempfile.TemporaryDirectory()
        cls.settings = Settings(db_url=cls.database.url, workspace=Path(cls.workspace.name), max_workers=1)
        cls.app = create_app(cls.settings)
        cls.client = TestClient(cls.app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        state = cls.app.app.state.factory
        state["store"].engine.dispose()
        state["store"].native_db.db_engine.dispose()
        cls.workspace.cleanup()
        cls.database.__exit__(None, None, None)

    def login(self, persona="alice"):
        self.client.cookies.clear()
        response = self.client.post("/api/factory/demo/login", json={"persona": persona})
        self.assertEqual(response.status_code, 200, response.text)

    def plan(self, topic, mode="literature", application="research", request=None):
        from uuid import uuid4
        body = {"topic": topic, "mode": mode, "application": application, "requestId": request or str(uuid4())}
        response = self.client.post("/api/factory/plans", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), body

    def submit(self, plan, request=None):
        from uuid import uuid4
        body = {"planId": plan["id"], "requestId": request or str(uuid4())}
        response = self.client.post("/api/factory/instances", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json(), body

    def wait(self, task_id, states):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = self.client.get("/api/factory/jobs/" + task_id)
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail["job"]["status"] in states:
                return detail
            time.sleep(.05)
        self.fail("Native lifecycle did not reach " + str(states) + ": " + json.dumps(detail))

    def test_01_literature_duplicate_conflict_artifacts_and_cross_user(self):
        self.login()
        plan, request = self.plan("Compare two synthetic research candidates")
        same_plan = self.client.post("/api/factory/plans", json=request)
        self.assertEqual(same_plan.json()["id"], plan["id"])
        self.assertEqual(self.client.post("/api/factory/plans", json={**request, "topic": "changed synthetic question"}).status_code, 409)
        task, request = self.submit(plan)
        replay = self.client.post("/api/factory/instances", json=request)
        self.assertEqual(replay.json()["id"], task["id"])
        detail = self.wait(task["id"], {"completed", "failed", "unknown"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertTrue(detail["artifacts"])
        artifact = detail["artifacts"][0]
        path = f'/api/factory/jobs/{task["id"]}/artifacts/{artifact["id"]}'
        raw = self.client.get(path)
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact["sha256"])
        new_plan, _ = self.plan("Another synthetic research question")
        self.assertEqual(self.client.post("/api/factory/instances", json={**request, "planId": new_plan["id"]}).status_code, 409)
        self.login("bob")
        self.assertEqual(self.client.get('/api/factory/jobs/' + task["id"]).status_code, 404)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post("/api/factory/materials", json={"kind": "prompt", "name": "Denied", "content": "x", "description": "x"}).status_code, 403)

    def test_02_question_exact_version_then_checksum(self):
        self.login()
        plan, _ = self.plan("sort")
        task, _ = self.submit(plan)
        detail = self.wait(task["id"], {"waiting_input", "failed"})
        self.assertEqual(detail["job"]["status"], "waiting_input", detail)
        question = detail["job"]["questionDetail"]
        body = {"questionId": question["id"], "version": question["version"] + 1, "answer": "Synthetic sorting scope"}
        self.assertEqual(self.client.post(f'/api/factory/jobs/{task["id"]}/answer', json=body).status_code, 409)
        body["version"] = question["version"]
        result = self.client.post(f'/api/factory/jobs/{task["id"]}/answer', json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.wait(task["id"], {"completed", "failed"})["job"]["status"], "completed")
        plan, _ = self.plan("factory checksum fixture", application="checksum")
        task, _ = self.submit(plan)
        detail = self.wait(task["id"], {"completed", "failed"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        artifact = detail["artifacts"][0]
        raw = self.client.get(f'/api/factory/jobs/{task["id"]}/artifacts/{artifact["id"]}')
        self.assertEqual(raw.json()["sha256"], hashlib.sha256(b"factory checksum fixture").hexdigest())

    def test_03_scoped_approval_and_running_cancel(self):
        self.login()
        plan, _ = self.plan("Evaluate the synthetic sorting candidate", "experiment")
        task, _ = self.submit(plan)
        detail = self.wait(task["id"], {"waiting_approval", "failed"})
        self.assertEqual(detail["job"]["status"], "waiting_approval", detail)
        approval = detail["job"]["approvalDetail"]
        result = self.client.post(f'/api/factory/jobs/{task["id"]}/approve', json={"requirementId": approval["id"], "version": approval["version"], "approved": True})
        self.assertEqual(result.status_code, 200, result.text)
        self.wait(task["id"], {"running"})
        result = self.client.post(f'/api/factory/jobs/{task["id"]}/cancel')
        self.assertEqual(result.status_code, 200, result.text)
        detail = self.wait(task["id"], {"canceled", "unknown", "failed"})
        self.assertEqual(detail["job"]["status"], "canceled", detail)
        effects = detail["snapshot"]["effects"]
        self.assertTrue(all(row["status"] != "UNKNOWN" for row in effects), effects)

    def test_04_native_bypass_and_manager_publication(self):
        self.login("manager")
        body = {"id": "test-prompt", "kind": "prompt", "name": "Synthetic prompt", "description": "Fixture", "content": "Evidence only", "requestId": "draft-first-v1"}
        first = self.client.post("/api/factory/materials", json=body)
        self.assertEqual(first.status_code, 201, first.text)
        material = first.json()
        reviewed = self.client.post(f'/api/factory/materials/{material["id"]}/{material["version"]}/publish', json={"requestId": "request-publication-v1"})
        self.assertEqual(reviewed.status_code, 202, reviewed.text)
        review = reviewed.json()
        path = '/api/factory/material-governance/reviews/' + review["id"] + '/decision'
        self.assertEqual(self.client.post(path, json={"approved": True, "requestId": "reject-self-review"}).status_code, 403)
        state = self.app.app.state.factory
        state["store"].native_db.replace_authz_subject_roles("bob", "factory-manager")  # Isolated test identity only.
        try:
            self.login("bob")
            published = self.client.post(path, json={"approved": True, "requestId": "distinct-admin-review"})
            self.assertEqual(published.status_code, 200, published.text)
            self.assertEqual(published.json()["reviewerId"], "bob")
        finally:
            state["store"].native_db.replace_authz_subject_roles("bob", "factory-user")
            self.login("manager")
        second = self.client.post("/api/factory/materials", json={**body, "content": "New version", "requestId": "draft-second-v2"})
        self.assertEqual(second.json()["version"], material["version"] + 1)
        self.assertNotEqual(second.json()["sha256"], material["sha256"])
        self.assertEqual(self.client.post("/agents/factory-executor/runs", data={"message": "bypass", "background": "true"}).status_code, 403)

    def test_05_current_policy_withdrawal_and_quota_recovery(self):
        from uuid import uuid4
        self.login()
        ready, _ = self.plan("Ready immutable plan before policy withdrawal")
        try:
            self.settings.temporary_policy = "unset"
            blocked, _ = self.plan("Preview after current policy withdrawal")
            self.assertEqual(blocked["status"], "blocked")
            denied = self.client.post("/api/factory/instances", json={"planId":ready["id"],"requestId":str(uuid4())})
            self.assertEqual(denied.status_code,409,denied.text)
            self.assertIn("POLICY_UNSET",denied.text)
        finally:
            self.settings.temporary_policy = "bounded-synthetic"
        held = []
        try:
            for topic in ("one", "two"):
                plan, _ = self.plan(topic)
                task, _ = self.submit(plan)
                held.append(task["id"])
                self.assertEqual(self.wait(task["id"], {"waiting_input","failed"})["job"]["status"],"waiting_input")
            plan, _ = self.plan("Known quota rejection can recover after confirmed cancellation")
            body = {"planId":plan["id"],"requestId":str(uuid4())}
            rejected = self.client.post("/api/factory/instances",json=body)
            self.assertEqual(rejected.status_code,429,rejected.text)
            self.client.post('/api/factory/jobs/'+held[0]+'/cancel')
            self.assertEqual(self.wait(held[0],{"canceled","unknown","failed"})["job"]["status"],"canceled")
            accepted = self.client.post("/api/factory/instances",json=body)
            self.assertEqual(accepted.status_code,202,accepted.text)
            completed = self.wait(accepted.json()["id"],{"completed","failed","unknown"})
            self.assertEqual(completed["job"]["status"],"completed",completed)
            cancelled = self.client.post('/api/factory/jobs/'+accepted.json()["id"]+'/cancel')
            self.assertEqual(cancelled.json()["status"],"completed")
        finally:
            for task_id in held:
                self.client.post('/api/factory/jobs/'+task_id+'/cancel')


if __name__ == "__main__":
    unittest.main()

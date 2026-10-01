"""Plan approval against real managed native auth and persisted metadata.

Portable tests use owned disk SQLite metadata; the optional PostgreSQL tests use
the actual Factory Store/executor/queue and native HITL. No paid provider calls.
The production integration is deliberately not implied by mounting test guards.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.run import RunContext
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine, select

from agent_factory.auth import AuthService
from agent_factory.config import Settings
from agent_factory.demo_model import DemoModel
from agent_factory.main import create_app
from agent_factory.plan_policy import (
    PlanPolicyConfig, PlanPolicyService, persisted_ancestor_guard, plan_policy_router,
)
from agent_factory.store import digest
from pg_fixture import IsolatedPostgres


class MetadataFixture:
    """Real disk metadata, not the production PostgreSQL admission implementation."""
    def __init__(self, db, settings):
        self.engine, self.settings = db.db_engine, settings
        self.table = Table("fixture_immutable_plans", MetaData(), Column("id", String, primary_key=True),
                           Column("owner_id", String), Column("body", JSON), Column("hash", String))
        self.table.metadata.create_all(self.engine)

    def add(self, owner="alice", *, experiment=False, delegation=None, **changes):
        tools = ["literature_search", "ask_scope"]
        caps = ["research:read", "question:ask"]
        if experiment:
            tools.append("run_experiment")
            caps.append("experiment:synthetic")
        plan = {"id": str(uuid4()), "ownerId": owner, "tools": tools, "capabilities": caps,
                "mode": "experiment" if experiment else "literature", "status": "ready", "missing": [],
                "policy": "bounded-synthetic", "syntheticFixture": True,
                "budget": {"toolCalls": 8, "experimentSeconds": 8, "outputBytes": 65536,
                           "maxDepth": 2, "maxChildren": 4}, **changes}
        if delegation:
            plan["delegation"] = delegation
        plan["fingerprint"] = digest(plan)
        with self.engine.begin() as conn:
            conn.execute(self.table.insert().values(id=plan["id"], owner_id=owner, body=plan, hash=digest(plan)))
        return plan

    def plan(self, plan_id, owner=None):
        with self.engine.connect() as conn:
            row = conn.execute(select(self.table).where(self.table.c.id == plan_id)).mappings().first()
        if not row or owner is not None and row["owner_id"] != owner:
            raise HTTPException(404, "Scoped immutable plan not found")
        if digest(row["body"]) != row["hash"]:
            raise HTTPException(409, "Immutable plan integrity mismatch")
        return copy.deepcopy(row["body"])

    def require_current_policy(self):
        if getattr(self.settings, "temporary_policy", None) == "unset":
            raise HTTPException(409, "POLICY_UNSET: emergency configuration denies execution")


class PlanPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "policy.sqlite"))
        self.settings = SimpleNamespace(demo=True, jwt_key=secrets.token_urlsafe(48))
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        self.store = MetadataFixture(self.db, self.settings)
        self.at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        self.service = PlanPolicyService(self.store, self.auth, clock=lambda: self.at)
        self.plan = self.store.add()

    def tearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    def change(self, name):
        return self.service.replace_configuration(PlanPolicyConfig(name=name, revision=str(uuid4()), review_ttl_seconds=60),
                                                  expected_revision=self.service.current()["revision"])

    def approve(self, plan=None):
        plan = plan or self.plan
        review = self.service.request_review("alice", plan["id"], str(uuid4()))
        return self.service.decide("manager", review["id"], True, str(uuid4()))

    def test_conservative_default_requires_exact_admin_review(self):
        self.assertEqual(self.service.current()["name"], "admin-review")
        with self.assertRaises(HTTPException) as missing:
            self.service.require_execution("alice", self.plan["id"])
        self.assertIn("PLAN_REVIEW_REQUIRED", str(missing.exception.detail))
        decision = self.approve()
        result = self.service.require_execution("alice", self.plan["id"])
        self.assertEqual(result["reviewId"], decision["id"])
        self.assertEqual(result["planDigest"], digest(self.plan))
        self.assertTrue(self.service.current()["nativeToolConfirmationSeparate"])
        self.assertTrue(self.service.status("alice", self.plan["id"])["executionAllowed"])
        self.assertTrue(decision["planIntegrityMatches"])
        self.assertEqual(decision["planSummary"]["tools"], self.plan["tools"])

    def test_review_request_deduplicates_and_conflicts_on_changed_plan(self):
        first = self.service.request_review("alice", self.plan["id"], "review-original")
        self.at += timedelta(seconds=10)
        replay = self.service.request_review("alice", self.plan["id"], "review-original")
        self.assertEqual(first, replay)
        other = self.store.add()
        with self.assertRaises(HTTPException) as conflict:
            self.service.request_review("alice", other["id"], "review-original")
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(len(self.service.list_reviews("alice")), 1)

    def test_manager_decision_deduplication_and_no_model_or_user_approval(self):
        review = self.service.request_review("alice", self.plan["id"], "request-first")
        with self.assertRaises(HTTPException) as user:
            self.service.decide("alice", review["id"], True, "user-decision")
        self.assertEqual(user.exception.status_code, 403)
        first = self.service.decide("manager", review["id"], True, "decision-first")
        replay = self.service.decide("manager", review["id"], True, "decision-first")
        self.assertEqual(first, replay)
        with self.assertRaises(HTTPException) as changed:
            self.service.decide("manager", review["id"], False, "decision-first")
        self.assertEqual(changed.exception.status_code, 409)
        self.auth.directory.set_disabled("manager", True)
        with self.assertRaises(HTTPException) as revoked:
            self.service.decide("manager", review["id"], True, "decision-first")
        self.assertEqual(revoked.exception.status_code, 403)

    def test_read_only_auto_preserves_separate_experiment_review(self):
        self.change("read-only-auto")
        self.assertEqual(self.service.require_execution("alice", self.plan["id"])["source"], "read-only-auto")
        experiment = self.store.add(experiment=True)
        with self.assertRaises(HTTPException):
            self.service.require_execution("alice", experiment["id"])
        self.approve(experiment)
        self.assertEqual(self.service.require_execution("alice", experiment["id"])["source"], "administrator-review")

    def test_unknown_scope_and_preflight_cannot_be_approved(self):
        for changes in [{"tools": ["arbitrary_shell"]}, {"capabilities": ["agent_os:admin"]},
                        {"capabilities": []}, {"status": "blocked", "missing": ["provider unavailable"]}]:
            plan = self.store.add(**changes)
            with self.assertRaises(HTTPException):
                self.service.request_review("alice", plan["id"], str(uuid4()))
            with self.assertRaises(HTTPException):
                self.service.require_execution("alice", plan["id"])
        self.assertEqual(self.service.list_reviews("alice"), [])

    def test_expiry_cannot_be_renewed_by_replaying_request_key(self):
        self.change("admin-review")
        approved = self.approve()
        self.at += timedelta(seconds=60)
        with self.assertRaises(HTTPException) as expired:
            self.service.require_execution("alice", self.plan["id"])
        self.assertIn("PLAN_REVIEW_EXPIRED", str(expired.exception.detail))
        replay = self.service.request_review("alice", self.plan["id"], approved["requestId"])
        self.assertTrue(replay["expired"])
        self.assertEqual(replay["expiresAt"], approved["expiresAt"])
        self.approve()
        self.assertTrue(self.service.require_execution("alice", self.plan["id"])["allowed"])

    def test_expired_pending_review_cannot_be_approved(self):
        self.change("admin-review")
        review = self.service.request_review("alice", self.plan["id"], "pending-expiry")
        self.at += timedelta(seconds=60)
        with self.assertRaises(HTTPException):
            self.service.decide("manager", review["id"], True, "too-late")
        self.assertEqual(self.service.inspect("alice", review["id"])["decision"], "pending")

    def test_current_revision_invalidation_and_stale_operator_configuration(self):
        approved = self.approve()
        previous = self.service.current()["revision"]
        current = self.change("admin-review")
        self.assertFalse(self.service.inspect("alice", approved["id"])["currentPolicy"])
        with self.assertRaises(HTTPException):
            self.service.require_execution("alice", self.plan["id"])
        with self.assertRaises(HTTPException):
            self.service.request_review("alice", self.plan["id"], approved["requestId"])
        with self.assertRaises(HTTPException):
            self.service.replace_configuration(PlanPolicyConfig(revision="stale"), expected_revision=previous)
        with self.assertRaises(ValueError):
            PlanPolicyService(self.store, self.auth)
        restarted = PlanPolicyService(self.store, self.auth, PlanPolicyConfig(name="admin-review", revision=current["revision"], review_ttl_seconds=60), clock=lambda: self.at)
        self.assertEqual(restarted.inspect("manager", approved["id"])["id"], approved["id"])

    def test_unset_and_bounded_synthetic_mode_are_fail_closed(self):
        self.change("unset")
        with self.assertRaises(HTTPException):
            self.service.require_execution("alice", self.plan["id"])
        with self.assertRaises(HTTPException):
            self.service.request_review("alice", self.plan["id"], "unset-review")
        self.change("bounded-synthetic")
        self.assertEqual(self.service.require_execution("alice", self.plan["id"])["source"], "bounded-synthetic")
        live = self.store.add(syntheticFixture=False)
        with self.assertRaises(HTTPException):
            self.service.require_execution("alice", live["id"])
        self.settings.demo = False
        with self.assertRaises(HTTPException):
            self.service.require_execution("alice", self.plan["id"])

    def test_owner_isolation_current_revocation_and_snapshot_changes(self):
        review = self.approve()
        with self.assertRaises(HTTPException) as hidden:
            self.service.inspect("bob", review["id"])
        self.assertEqual(hidden.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            self.service.request_review("bob", self.plan["id"], "bob-review")
        with self.assertRaises(HTTPException):
            self.service.list_reviews("alice", all_owners=True)
        self.assertEqual(len(self.service.list_reviews("manager", all_owners=True)), 1)
        with self.assertRaises(HTTPException):
            self.service.require_execution("alice", {**self.plan, "tools": ["checksum"]})
        self.auth.authorization.unassign("alice", "factory-user")
        for action in [lambda: self.service.require_execution("alice", self.plan["id"]),
                       lambda: self.service.inspect("alice", review["id"]),
                       lambda: self.service.request_review("alice", self.plan["id"], review["requestId"])]:
            with self.assertRaises(HTTPException) as denied:
                action()
            self.assertEqual(denied.exception.status_code, 403)

    def test_denied_latest_review_blocks_previous_approval(self):
        approved = self.approve()
        review = self.service.request_review("alice", self.plan["id"], "new-review")
        self.service.decide("manager", review["id"], False, "deny-new")
        with self.assertRaises(HTTPException) as denied:
            self.service.require_execution("alice", self.plan["id"])
        self.assertIn("PLAN_REVIEW_DENIED", str(denied.exception.detail))
        self.assertFalse(self.service.inspect("alice", approved["id"])["approvalEffective"])

    def test_child_without_current_persisted_mandate_is_not_auto_approved(self):
        self.change("bounded-synthetic")
        child = self.store.add(delegation={"rootTaskId": str(uuid4()), "parentTaskId": str(uuid4()), "depth": 1})
        with self.assertRaises(HTTPException) as unbound:
            self.service.require_execution("alice", child["id"])
        self.assertIn("DELEGATION_POLICY_UNBOUND", str(unbound.exception.detail))
        with self.assertRaises(HTTPException):
            self.service.request_review("alice", child["id"], "child-own-review")

    def test_config_ttl_and_revision_cannot_be_unsafe_or_rebound(self):
        for ttl in [True, 0, 59, 86401]:
            with self.assertRaises(ValueError):
                PlanPolicyConfig(review_ttl_seconds=ttl)
        with self.assertRaises(ValueError):
            PlanPolicyConfig(revision="../policy")
        with self.assertRaises(ValueError):
            self.service.replace_configuration(PlanPolicyConfig(name="unset"), expected_revision="plan-policy-v1")

    def test_router_uses_native_identity_and_admin_auth_not_body_owner(self):
        native = AgentOS(id="policy-router-fixture", agents=[Agent(id="factory-executor", db=self.db, model=DemoModel(), telemetry=False)],
                         db=self.db, **self.auth.agentos_kwargs(), mcp=False, scheduler=False, telemetry=False).get_app()
        native.include_router(plan_policy_router(self.auth, self.service))
        with TestClient(native) as client:
            alice = {"Authorization": "Bearer " + self.auth.issue_demo_token("alice")}
            manager = {"Authorization": "Bearer " + self.auth.issue_demo_token("manager")}
            self.assertEqual(client.get("/api/factory/plan-policy").status_code, 401)
            body = {"planId": self.plan["id"], "requestId": "route-review"}
            self.assertEqual(client.post("/api/factory/plan-reviews", json={**body, "ownerId": "manager"}, headers=alice).status_code, 422)
            response = client.post("/api/factory/plan-reviews", json=body, headers=alice)
            self.assertEqual(response.status_code, 201, response.text)
            review = response.json()
            self.assertEqual(review["ownerId"], "alice")
            path = "/api/factory/plan-reviews/" + review["id"] + "/decision"
            self.assertEqual(client.post(path, json={"approved": True, "requestId": "alice-decision"}, headers=alice).status_code, 403)
            self.assertEqual(client.post(path, json={"approved": "yes", "requestId": "untyped"}, headers=manager).status_code, 422)
            result = client.post(path, json={"approved": True, "requestId": "manager-decision"}, headers=manager)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json()["approvalEffective"])


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class PlanPolicyPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.directory = TemporaryDirectory()
        settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1,
                            temporary_policy="read-only-auto")
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.service = self.state["plan_policy"]
        self.client = TestClient(self.app).__enter__()
        self.login()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.engine.dispose()
        self.store.native_db.db_engine.dispose()
        self.directory.cleanup()
        self.database.__exit__(None, None, None)

    def login(self, owner="alice"):
        self.client.cookies.clear()
        response = self.client.post("/api/factory/demo/login", json={"persona": owner})
        self.assertEqual(response.status_code, 200, response.text)

    def plan(self, *, mode="literature", goal="Controlled policy research comparison", application="research"):
        response = self.client.post("/api/factory/plans", json={"topic": goal, "mode": mode,
                                    "application": application, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def submit(self, plan):
        self.service.require_execution("alice", plan["id"])
        response = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def wait(self, task_id, expected):
        end = time.monotonic() + 15
        detail = {}
        while time.monotonic() < end:
            response = self.client.get("/api/factory/jobs/" + task_id)
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail["job"]["status"] in expected:
                return detail
            time.sleep(.03)
        self.fail(str(detail))

    def approve(self, plan):
        request = self.service.request_review("alice", plan["id"], str(uuid4()))
        self.service.decide("manager", request["id"], True, str(uuid4()))
        return request

    def test_postgres_concurrent_request_and_reopen_have_one_exact_receipt(self):
        plan = self.plan(mode="experiment")
        original_engine = self.store.engine
        bounded_engine = create_engine(self.database.url, pool_size=1, max_overflow=0, pool_timeout=2)
        self.store.engine = bounded_engine
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                receipts = list(pool.map(lambda _: self.service.request_review("alice", plan["id"], "concurrent-review"), range(2)))
        finally:
            self.store.engine = original_engine
            bounded_engine.dispose()
        self.assertEqual(receipts[0]["id"], receipts[1]["id"])
        self.assertEqual(len(self.service.list_reviews("alice")), 1)
        self.service.decide("manager", receipts[0]["id"], True, "persisted-decision")
        restarted = PlanPolicyService(self.store, self.auth, PlanPolicyConfig(name="read-only-auto"),
                                      ancestor_guard=persisted_ancestor_guard(self.store))
        self.assertTrue(restarted.require_execution("alice", plan["id"])["allowed"])
        self.assertEqual(restarted.inspect("manager", receipts[0]["id"])["decision"], "approved")

    def test_native_tool_confirmation_does_not_replace_review_or_current_policy(self):
        plan = self.plan(mode="experiment")
        with self.assertRaises(HTTPException):
            self.service.require_execution("alice", plan["id"])
        self.approve(plan)
        job = self.submit(plan)
        detail = self.wait(job["id"], {"waiting_approval", "failed"})
        self.assertEqual(detail["job"]["status"], "waiting_approval", detail)
        self.assertEqual(detail["snapshot"]["effects"], [])
        self.service.replace_configuration(PlanPolicyConfig(name="unset", revision="policy-revoked"), expected_revision="plan-policy-v1")
        approval = detail["job"]["approvalDetail"]
        with patch("subprocess.Popen") as no_compute:
            result = self.client.post("/api/factory/jobs/" + job["id"] + "/approve", json={"requirementId": approval["id"], "version": approval["version"], "approved": True})
            self.assertEqual(result.status_code, 200, result.text)
            stopped = self.wait(job["id"], {"failed", "unknown"})
            self.assertEqual(no_compute.call_count, 0)
        self.assertFalse(any(event["type"] == "compute_started" for event in stopped["events"]))
        self.assertEqual(stopped["artifacts"], detail["artifacts"])
        self.assertEqual(stopped["snapshot"]["effects"], detail["snapshot"]["effects"])
        evidence_types = {"artifact", "compute_started", "compute_stopped", "compute_cancelled", "experiment_completed"}
        self.assertEqual([event for event in stopped["events"] if event["type"] in evidence_types],
                         [event for event in detail["events"] if event["type"] in evidence_types])

    def test_actual_native_checksum_executes_only_read_only_authorized_plan(self):
        goal = "controlled UTF-8 policy checksum"
        plan = self.plan(goal=goal, application="checksum")
        job = self.submit(plan)
        detail = self.wait(job["id"], {"completed", "failed"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        artifact = detail["artifacts"][0]
        raw = self.client.get(f'/api/factory/jobs/{job["id"]}/artifacts/{artifact["id"]}')
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact["sha256"])
        self.assertEqual(self.service.list_reviews("alice"), [])
        self.state["settings"].temporary_policy = "unset"
        status = self.client.get(f'/api/factory/plans/{plan["id"]}/authorization')
        self.assertEqual(status.status_code, 200, status.text)
        self.assertFalse(status.json()["executionAllowed"])
        self.assertIn("POLICY_UNSET", status.json()["reason"])
        rejected = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": str(uuid4())})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], 1)

    def test_actual_persisted_child_mandate_inherits_exact_root_review(self):
        self.service.replace_configuration(PlanPolicyConfig(name="admin-review", revision="root-reviewed"), expected_revision="plan-policy-v1")
        plan = self.plan(mode="experiment", goal="sort")
        root_review = self.approve(plan)
        root = self.submit(plan)
        self.assertEqual(self.wait(root["id"], {"waiting_input", "failed"})["job"]["status"], "waiting_input")
        response = self.client.post(f'/api/factory/jobs/{root["id"]}/children', json={"goal": "tiny", "mode": "literature", "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 202, response.text)
        child = response.json()["job"]
        detail = self.wait(child["id"], {"waiting_input", "failed"})
        self.assertEqual(detail["job"]["status"], "waiting_input", detail)
        task = self.store.task(child["id"], "alice")
        context = RunContext(run_id=task["run_id"], session_id=task["id"], user_id="alice")
        receipt = self.service.require_execution("alice", child["planId"], run_context=context)
        self.assertTrue(receipt["inheritedFromRoot"])
        self.assertEqual(receipt["reviewId"], root_review["id"])
        self.store.request_cancel(root["id"])
        with self.assertRaises(Exception):
            self.service.require_execution("alice", child["planId"], run_context=context)


if __name__ == "__main__":
    unittest.main()

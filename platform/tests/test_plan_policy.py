"""Member execution, original historical reviews and current native boundaries."""
from contextvars import ContextVar
import copy
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import RunCancelledException
from agno.os import AgentOS
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine, select

from agent_factory.auth import AuthService
from agent_factory.config import Settings
from core_native_fixture import FixtureModel as DemoModel
from core_native_fixture import create_fixture_app as create_app
from agent_factory.plan_policy import PlanPolicyConfig, PlanPolicyService, plan_policy_router
from agent_factory.store import Store, digest
from pg_fixture import IsolatedPostgres


class MetadataFixture:
    """Real disk metadata, not the production PostgreSQL admission implementation."""
    def __init__(self, db, settings):
        self.engine, self.settings = db.db_engine, settings
        self.table = Table("fixture_immutable_plans", MetaData(), Column("id", String, primary_key=True),
                           Column("owner_id", String), Column("body", JSON), Column("hash", String))
        self.table.metadata.create_all(self.engine)

    def add(self, owner="alice", *, experiment=False, delegation=None, **changes):
        tools = ["checksum", "ask_scope"]
        caps = ["checksum:read", "question:ask"]
        if experiment:
            tools.append("fixture_operation")
            caps.append("fixture:operate")
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


def historical_review(service, plan, *, decision=None):
    """Seed old database rows directly; retired production APIs never write them."""
    value = {"id": str(uuid4()), "owner_id": plan["ownerId"], "plan_id": plan["id"],
             "plan_hash": digest(plan), "plan_fingerprint": plan["fingerprint"],
             "policy_revision": "old-admin-review", "policy_hash": "old-policy-digest",
             "request_id": str(uuid4()), "intent_hash": "old-intent-digest",
             "created_at": "2026-01-01T00:00:00+00:00", "expires_at": "2026-01-01T01:00:00+00:00"}
    with service.store.engine.begin() as conn:
        conn.execute(service.reviews.insert().values(**value))
        if decision is not None:
            conn.execute(service.decisions.insert().values(review_id=value["id"], actor_id="manager",
                request_id=str(uuid4()), intent_hash="original-decision", decision=decision,
                decided_at="2026-01-01T00:30:00+00:00"))
    return value


class PlanPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "policy.sqlite"))
        self.settings = SimpleNamespace(demo=True, jwt_key=secrets.token_urlsafe(48))
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        self.store = MetadataFixture(self.db, self.settings)
        self.at = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        self.service = PlanPolicyService(self.store, self.auth, clock=lambda: self.at)
        self.plan = self.store.add(policy="member-self-service")

    def tearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    def test_member_runs_custom_tool_without_review_or_secondary_policy(self):
        plan = self.store.add(tools=["member_created_tool"], capabilities=["tool:invoke"], syntheticFixture=False)
        result = self.service.require_execution("alice", plan["id"])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["source"], "member-self-service")
        self.assertIsNone(result["reviewId"])
        self.assertEqual(self.service.list_reviews("alice"), [])

    def test_owner_disabled_member_and_missing_prerequisites_still_deny(self):
        with self.assertRaises(HTTPException): self.service.require_execution("bob", self.plan)
        blocked = self.store.add(status="blocked", missing=["unavailable resource"])
        self.assertFalse(self.service.status("alice", blocked)["executionAllowed"])
        self.auth.directory.set_disabled("alice", True)
        with self.assertRaises(HTTPException): self.service.require_execution("alice", self.plan)

    def test_historical_decisions_remain_readable_without_execution_authority(self):
        originals = [historical_review(self.service, self.plan, decision=value) for value in (None, "denied", "approved")]
        restarted = PlanPolicyService(self.store, self.auth, PlanPolicyConfig(revision="members-next"))
        self.assertEqual({r["decision"] for r in restarted.list_reviews("alice")}, {"pending", "denied", "approved"})
        for original in originals:
            result = restarted.inspect("alice", original["id"])
            self.assertEqual(result["planDigest"], original["plan_hash"])
            self.assertTrue(result["planIntegrityMatches"])
            self.assertFalse(result["approvalEffective"])
            for other in ("bob", "manager"):
                with self.assertRaises(HTTPException) as hidden: restarted.inspect(other, original["id"])
                self.assertEqual(hidden.exception.status_code, 404)
        self.assertTrue(restarted.require_execution("alice", self.plan["id"])["allowed"])

    def test_persisted_integrity_is_checked_once_at_store_boundary(self):
        self.store._connection = ContextVar("test_policy_connection", default=None)
        with patch.object(self.store, "plan", wraps=self.store.plan) as read:
            stored = self.store.plan(self.plan["id"], "alice")
            self.service.require_execution("alice", stored)
        self.assertEqual(read.call_count, 1)
        with self.store.engine.begin() as conn:
            conn.execute(self.store.table.update().where(self.store.table.c.id == self.plan["id"]).values(body={**self.plan, "tools": ["changed"]}))
        with self.assertRaises(HTTPException): self.service.require_execution("alice", self.plan["id"])

    def test_legacy_modes_and_ttl_are_removed_configuration(self):
        for name in ("admin-review", "read-only-auto", "bounded-synthetic", "unset"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "retired"):
                PlanPolicyConfig(name=name)
        with self.assertRaises(TypeError): PlanPolicyConfig(review_ttl_seconds=60)
        with self.assertRaises(ValueError): PlanPolicyConfig(revision="../policy")

    def test_delegated_execution_requires_current_original_context(self):
        child = self.store.add(delegation={"rootTaskId": "root", "parentTaskId": "parent", "depth": 1})
        with self.assertRaises(HTTPException): self.service.require_execution("alice", child)
        context = SimpleNamespace(user_id="alice", session_id="child", run_id="native-child")
        guard = unittest.mock.Mock(return_value=[self.plan])
        self.service.ancestor_guard = guard
        self.assertTrue(self.service.require_execution("alice", child, run_context=context)["allowed"])
        guard.assert_called_once_with("alice", child, context)
        guard.side_effect = HTTPException(409, "Original parent cancelled")
        with self.assertRaises(HTTPException): self.service.require_execution("alice", child, run_context=context)

    def test_router_uses_native_identity_and_retires_writes(self):
        native = AgentOS(id="member-policy-router", agents=[Agent(id="factory-executor", db=self.db, model=DemoModel(), telemetry=False)],
                         db=self.db, **self.auth.agentos_kwargs(), mcp=False, scheduler=False, telemetry=False).get_app()
        native.include_router(plan_policy_router(self.auth, self.service))
        original = historical_review(self.service, self.plan, decision="approved")
        with TestClient(native) as client:
            headers = {"Authorization": "Bearer " + self.auth.issue_demo_token("alice")}
            self.assertEqual(client.get("/api/factory/plan-policy").status_code, 401)
            self.assertEqual(client.post("/api/factory/plan-reviews", json={"planId": self.plan["id"]}, headers=headers).status_code, 410)
            self.assertEqual(client.post("/api/factory/plan-reviews/" + original["id"] + "/decision", json={"approved": True}, headers=headers).status_code, 410)
            detail = client.get("/api/factory/plan-reviews/" + original["id"], headers=headers)
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertFalse(detail.json()["approvalEffective"])
            self.assertTrue(client.get("/api/factory/plans/" + self.plan["id"] + "/authorization", headers=headers).json()["executionAllowed"])
            self.auth.directory.set_disabled("alice", True)
            self.assertEqual(client.get("/api/factory/plan-policy", headers=headers).status_code, 403)


class StoreToolBoundaryTests(unittest.TestCase):
    def test_tool_entry_checks_member_plan_once_and_passes_actual_tool_to_guards(self):
        store = Store.__new__(Store)
        plan = {"id": "plan", "ownerId": "alice", "tools": ["custom_member_tool"]}
        context = SimpleNamespace(user_id="alice", session_id="task", run_id="native-run")
        store.resolve_run = Mock(return_value=plan)
        store.plan_policy = SimpleNamespace(require_execution=Mock())
        guard = Mock()
        store.execution_guards = {"current-resource": guard}
        store.delegation = None
        store.cancellation_requested = Mock(return_value=False)
        store.event = Mock()
        self.assertIs(store.authorize_tool(context, "custom_member_tool"), plan)
        store.plan_policy.require_execution.assert_called_once_with("alice", plan, run_context=context)
        guard.assert_called_once_with("alice", plan, context, "custom_member_tool")
        with self.assertRaises(PermissionError): store.authorize_tool(context, "unselected_tool")
        store.cancellation_requested.return_value = True
        with self.assertRaises(RunCancelledException): store.authorize_tool(context, "custom_member_tool")


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class PlanPolicyPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.directory = TemporaryDirectory()
        settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1,
                            temporary_policy="member-self-service", policy_revision="department-member-v1")
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

    def plan(self, *, mode="literature", goal="Controlled policy research comparison", application="fixture-text"):
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

    def test_repeated_submission_reuses_original_native_task_and_effect(self):
        plan = self.plan(application="fixture-checksum", mode="literature")
        request_id = str(uuid4())
        body = {"planId": plan["id"], "requestId": request_id}
        first = self.client.post("/api/factory/instances", json=body)
        self.assertEqual(first.status_code, 202, first.text)
        repeated = self.client.post("/api/factory/instances", json=body)
        self.assertEqual(repeated.status_code, 202, repeated.text)
        self.assertEqual(repeated.json()["id"], first.json()["id"])
        detail = self.wait(first.json()["id"], {"completed", "failed"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], 1)
        self.assertEqual(self.service.list_reviews("alice"), [])

    def test_native_tool_confirmation_cannot_resume_cancelled_task(self):
        plan = self.plan(mode="experiment")
        job = self.submit(plan)
        detail = self.wait(job["id"], {"waiting_approval", "failed"})
        self.assertEqual(detail["job"]["status"], "waiting_approval", detail)
        approval = detail["job"]["approvalDetail"]
        artifacts_before = self.store.artifacts(job["id"])
        self.store.request_cancel(job["id"])
        with patch("subprocess.Popen") as no_compute:
            result = self.client.post("/api/factory/jobs/" + job["id"] + "/approve", json={"requirementId": approval["id"], "version": approval["version"], "approved": True})
            self.assertEqual(result.status_code, 409, result.text)
            self.assertIn("Task is no longer waiting for this action", result.text)
            self.assertFalse(no_compute.called)
        self.assertEqual(self.store.effects(job["id"]), [])
        self.assertEqual(self.store.artifacts(job["id"]), artifacts_before)

    def test_history_read_borrows_single_metadata_connection(self):
        plan = self.plan()
        original = historical_review(self.service, plan, decision="approved")
        engine = self.store.engine
        bounded = create_engine(self.database.url, pool_size=1, max_overflow=0, pool_timeout=1)
        self.store.engine = bounded
        try:
            self.assertEqual(self.service.inspect("alice", original["id"])["decision"], "approved")
        finally:
            self.store.engine = engine
            bounded.dispose()

"""Two actual Factory apps and isolated PostgreSQL databases; synthetic models.

The HTTP transport is explicitly controlled ASGI. This proves backend/native
handoff contracts, not deployed hosts, credentials, network TLS or live models.
"""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
from uuid import uuid4

from agno.run import RunContext
from agno.exceptions import RunCancelledException
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import MetaData, Table, func, inspect, select

from pg_fixture import IsolatedPostgres
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.plan_policy import PlanPolicyConfig
from agent_factory.remote_handoff import (
    HandoffCancellationRequested, HandoffTarget, PrepareBody, PreparedHandoffService, TrustedHandoffClient, TrustedOrigin, plan_manifest,
)
from agent_factory.runtime import build_runtime
from agent_factory.store import digest


class LostReplyTransport(httpx.AsyncBaseTransport):
    """Lose an actual accepted receiver reply once; never replace its behavior."""
    def __init__(self, app, suffix):
        self.inner = httpx.ASGITransport(app=app)
        self.suffix = suffix
        self.lost = False

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if request.method == "POST" and request.url.path.endswith(self.suffix) and not self.lost:
            self.lost = True
            await response.aread()
            raise httpx.ReadTimeout("Synthetic lost receiver reply", request=request)
        return response


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class RemoteHandoffPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.origin_db = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.origin_db.__exit__, None, None, None)
        cls.remote_db = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.remote_db.__exit__, None, None, None)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.origin_settings = Settings(db_url=cls.origin_db.url, workspace=Path(cls.workspace.name) / "origin", max_workers=1, max_user_tasks=12, max_total_tasks=24)
        cls.remote_settings = Settings(db_url=cls.remote_db.url, workspace=Path(cls.workspace.name) / "receiver", max_workers=1, max_user_tasks=12, max_total_tasks=24)
        cls.origin_app = create_app(cls.origin_settings)
        def capture(*args, **kwargs):
            result = build_runtime(*args, **kwargs)
            cls.registry = result[1]
            return result
        with mock.patch("agent_factory.main.build_runtime", side_effect=capture):
            cls.remote_app = create_app(cls.remote_settings)
        cls.origin = cls.origin_app.app.state.factory
        cls.remote = cls.remote_app.app.state.factory
        for state in (cls.origin, cls.remote):
            cls.addClassCleanup(state["store"].engine.dispose)
            cls.addClassCleanup(state["store"].native_db.db_engine.dispose)
        target = HandoffTarget("receiver", "origin-fixture", "http://receiver.factory.invalid", {"alice": "bob"},
                               lambda owner: {"Authorization": "Bearer " + cls.remote["auth"]._issue_native_token("bob")},
                               transport=httpx.ASGITransport(app=cls.remote_app))
        cls.handoff = TrustedHandoffClient(cls.origin["store"], cls.origin["auth"], {"receiver": target})
        cls.handoff.install_guard()
        cls.trusted = TrustedOrigin("origin-fixture", {"alice": "bob"}, cls.handoff.authority_callback)
        cls.receiver = PreparedHandoffService(cls.remote["store"], cls.remote["auth"], cls.remote["bridge"], {"origin-fixture": cls.trusted})
        cls.receiver.install_guard()
        cls.remote_app.app.include_router(cls.receiver.router)
        cls.origin_client = TestClient(cls.origin_app).__enter__()
        cls.addClassCleanup(cls.origin_client.__exit__, None, None, None)
        cls.remote_client = TestClient(cls.remote_app).__enter__()
        cls.addClassCleanup(cls.remote_client.__exit__, None, None, None)

    def setUp(self):
        self.placements = []
        self.original_target = self.handoff.targets["receiver"]
        self.origin["auth"].authorization.assign("alice", "factory-user")
        self.remote["auth"].authorization.assign("bob", "factory-user")
        self.origin_settings.temporary_policy = self.remote_settings.temporary_policy = "bounded-synthetic"

    def tearDown(self):
        self.handoff.targets["receiver"] = self.original_target
        self.origin["auth"].authorization.assign("alice", "factory-user")
        self.remote["auth"].authorization.assign("bob", "factory-user")
        self.origin_settings.temporary_policy = self.remote_settings.temporary_policy = "bounded-synthetic"
        for row in self.placements:
            found = self.remote["store"].sql("SELECT body FROM af_remote_handoffs WHERE origin_task=:id", id=row["task_id"])
            if found and found[0]["body"].get("remoteTaskId"):
                task_id = found[0]["body"]["remoteTaskId"]
                self.call_remote(self.remote["store"].delegation.cascade_cancel, "bob", task_id)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    group = self.call_remote(self.remote["store"].delegation.inspect_group, "bob", task_id)
                    if group["allStopped"] or group["unknown"]:
                        break
                    time.sleep(.03)
                task = self.remote["store"].task(task_id)
                if not task["run_id"]:
                    self.remote["store"].admission_failed(task_id, "Controlled test fixture never dispatched")
            self.origin["store"].admission_failed(row["task_id"], "Controlled origin fixture cleanup; no origin native submission")

    def call(self, function, *args):
        return self.origin_client.portal.call(function, *args)

    def call_remote(self, function, *args):
        return self.remote_client.portal.call(function, *args)

    def headers(self, state, owner):
        return {"Authorization": "Bearer " + state["auth"]._issue_native_token(owner)}

    def reserve(self, goal="sort", mode="literature", request=None, application="research"):
        response = self.origin_client.post("/api/factory/plans", headers=self.headers(self.origin, "alice"),
                                           json={"topic": goal, "mode": mode, "application": application, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        plan = response.json()
        row = self.handoff.reserve("alice", plan["id"], "receiver", request or str(uuid4()))
        self.placements.append(row)
        return row

    def body(self, row):
        return PrepareBody(originRef="origin-fixture", originOwnerId="alice", originTaskId=row["task_id"],
                           requestId=row["request_id"], manifest=row["body"]["manifest"])

    def ticket_count(self, state, task_id=None):
        db = state["store"].native_db
        if not inspect(db.db_engine).has_table(db.job_table_name, schema=db.db_schema):
            return 0
        tickets = Table(db.job_table_name, MetaData(), schema=db.db_schema, autoload_with=db.db_engine)
        query = select(func.count()).select_from(tickets)
        if task_id:
            query = query.where(tickets.c.session_id == task_id)
        with db.db_engine.connect() as conn:
            return conn.execute(query).scalar()

    def wait_native(self, receipt, states):
        deadline = time.monotonic() + 15
        last = {}
        while time.monotonic() < deadline:
            task = self.remote["store"].task(receipt["remoteTaskId"])
            last = self.remote["store"].native_db.get_job(task["run_id"]) if task.get("run_id") else {}
            if last and last["status"] in states:
                return last
            time.sleep(.03)
        self.fail(f"Receiver native ticket did not reach {states}: {last}")

    def denied(self, status, function, *args):
        with self.assertRaises(HTTPException) as caught:
            function(*args)
        self.assertEqual(caught.exception.status_code, status, str(caught.exception.detail))

    def test_01_prepare_imports_owner_bound_plan_with_no_execution(self):
        row = self.reserve()
        receipt = self.call(self.handoff.prepare, "alice", row["task_id"])
        self.assertNotEqual(self.origin_db.name, self.remote_db.name)
        self.assertEqual(receipt["state"], "PREPARED")
        self.assertIsNone(receipt["remoteRunId"])
        self.assertNotEqual(receipt["remoteTaskId"], row["task_id"])
        source = row["body"]["manifest"]["plan"]
        imported = self.remote["store"].plan(receipt["remotePlanId"], "bob")
        self.assertEqual(imported["ownerId"], "bob")
        self.assertNotEqual(imported["id"], source["id"])
        for key in ("instructions", "tools", "config", "materialRefs", "budget"):
            self.assertEqual(imported[key], source[key])
        self.assertEqual(self.ticket_count(self.origin), 0)
        self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 0)
        self.denied(404, self.remote["store"].plan, source["id"], "alice")
        self.denied(404, self.remote["store"].plan, receipt["remotePlanId"], "alice")
        forged = self.remote_client.post("/api/factory/remote-handoffs/prepare", headers=self.headers(self.remote, "bob"),
                                         json={**self.body(row).model_dump(mode="json"), "url": "http://user-chosen.invalid"})
        self.assertEqual(forged.status_code, 422, forged.text)
        wrong_key = self.remote_client.get("/api/factory/remote-handoffs/" + receipt["id"], headers=self.headers(self.origin, "alice"))
        self.assertEqual(wrong_key.status_code, 401)

    def test_02_single_receiver_dispatch_and_native_ingress_remains_closed(self):
        row = self.reserve()
        self.call(self.handoff.prepare, "alice", row["task_id"])
        with mock.patch.object(self.remote["bridge"], "submit", wraps=self.remote["bridge"].submit) as submit:
            receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
            self.wait_native(receipt, {"paused"})
            duplicate = self.call(self.handoff.dispatch, "alice", row["task_id"])
            restarted = PreparedHandoffService(self.remote["store"], self.remote["auth"], self.remote["bridge"], {"origin-fixture": self.trusted})
            again = self.call_remote(restarted.dispatch, "bob", receipt["id"])
            self.assertEqual(duplicate["remoteRunId"], receipt["remoteRunId"])
            self.assertEqual(again["remoteRunId"], receipt["remoteRunId"])
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.ticket_count(self.origin), 0)
        self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 1)
        raw = self.remote_client.post("/agents/factory-executor/runs", headers={**self.headers(self.remote, "bob"), "X-Factory-Internal": "true"},
                                      data={"message": "Bypass attempt", "session_id": receipt["remoteTaskId"], "background": "true"})
        self.assertEqual(raw.status_code, 403, raw.text)
        ctx = SimpleNamespace(session_id=row["task_id"], user_id="alice", run_id="synthetic-unsubmitted", session_state={})
        with self.assertRaises(PermissionError):
            self.origin["store"].require_plan_execution("alice", row["body"]["manifest"]["plan"], run_context=ctx)

    def test_03_lost_native_ack_recovers_by_exact_read_without_replay(self):
        row = self.reserve()
        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
        original = self.remote["bridge"].submit
        async def lose_ack(*args):
            await original(*args)
            raise httpx.ReadTimeout("Synthetic reply loss after actual native commit")
        with mock.patch.object(self.remote["bridge"], "submit", side_effect=lose_ack) as submit:
            with self.assertRaises(HTTPException) as caught:
                self.call(self.handoff.dispatch, "alice", row["task_id"])
            self.assertEqual(caught.exception.status_code, 503)
            self.assertEqual(self.handoff._row("alice", row["task_id"])["state"], "DISPATCH_UNKNOWN")
            recovered = self.call(self.handoff.receipt, "alice", row["task_id"])
            self.assertEqual(recovered["state"], "ACCEPTED")
            self.assertTrue(recovered["remoteRunId"])
            self.wait_native(recovered, {"paused"})
            self.call(self.handoff.dispatch, "alice", row["task_id"])
            self.call_remote(self.receiver.dispatch, "bob", prepared["id"])
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), 1)
        self.assertFalse(self.remote["store"].task(prepared["remoteTaskId"])["terminal"])
        self.assertFalse(self.origin["store"].task(row["task_id"])["terminal"])

    def test_04_lost_prepare_reply_owner_request_lookup_has_no_execution(self):
        row = self.reserve()
        old = self.original_target
        self.handoff.targets["receiver"] = HandoffTarget(old.reference, old.origin_ref, old.base_url, old.identity_map,
                                                         old.headers, LostReplyTransport(self.remote_app, "/prepare"))
        with self.assertRaises(HTTPException):
            self.call(self.handoff.prepare, "alice", row["task_id"])
        self.assertEqual(self.handoff._row("alice", row["task_id"])["state"], "PREPARE_UNKNOWN")
        receipt = self.call(self.handoff.receipt, "alice", row["task_id"])
        self.assertEqual(receipt["state"], "PREPARED")
        self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 0)
        accepted = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(accepted, {"paused"})
        self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 1)

    def test_05_owner_key_manifest_catalog_and_budget_conflicts(self):
        row = self.reserve()
        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
        self.denied(404, self.receiver.prepare, "alice", self.body(row))
        self.denied(404, self.handoff._row, "bob", row["task_id"])
        changed_key = self.body(row).model_copy(update={"requestId": str(uuid4())})
        self.denied(409, self.receiver.prepare, "bob", changed_key)
        changed = copy.deepcopy(row["body"]["manifest"]["plan"])
        changed["normalizedGoal"] = "Changed synthetic task"
        changed["fingerprint"] = digest({k: v for k, v in changed.items() if k not in {"id", "createdAt", "fingerprint"}})
        self.denied(409, self.receiver.prepare, "bob", self.body(row).model_copy(update={"manifest": plan_manifest(changed)}))
        changed_manifest = copy.deepcopy(row["body"]["manifest"])
        changed_manifest["plan"]["materials"][0]["content"] = "Altered material content"
        self.denied(409, self.receiver.prepare, "bob", self.body(row).model_copy(update={"manifest": changed_manifest}))
        before = self.ticket_count(self.remote, prepared["remoteTaskId"])
        self.remote_settings.max_tool_calls = 4
        try:
            with self.assertRaises(HTTPException) as caught:
                self.call_remote(self.receiver.dispatch, "bob", prepared["id"])
            self.assertEqual(caught.exception.status_code, 403)
        finally:
            self.remote_settings.max_tool_calls = 8
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), before)
        self.assertEqual(self.receiver._row(prepared["id"], "bob")["state"], "PREPARED")

    def test_06_current_origin_and_remote_revocation_block_native_and_direct_effects(self):
        for scenario in ("origin", "receiver"):
            with self.subTest(scenario=scenario):
                row = self.reserve("Controlled sorting experiment fixture", "experiment")
                self.call(self.handoff.prepare, "alice", row["task_id"])
                receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
                self.wait_native(receipt, {"paused"})
                task = self.remote["store"].task(receipt["remoteTaskId"])
                native = self.call_remote(self.remote["bridge"].detail, task["run_id"], task["id"], "bob")
                requirements = native.get("requirements") or native.get("run", {}).get("requirements") or []
                self.assertTrue(requirements)
                for requirement in requirements:
                    requirement["tool_execution"]["confirmed"] = True
                artifacts = self.remote["store"].artifacts(task["id"])
                effects = self.remote["store"].effects(task["id"])
                original = self.remote["store"].authorize_tool
                revoked = []
                def revoke_at_boundary(ctx, name):
                    if name == "run_experiment" and not revoked:
                        revoked.append(scenario)
                        state, owner = (self.origin, "alice") if scenario == "origin" else (self.remote, "bob")
                        state["auth"].authorization.unassign(owner, "factory-user")
                    return original(ctx, name)
                try:
                    with mock.patch("agent_factory.tools.subprocess.Popen", side_effect=AssertionError("Denied remote experiment attempted compute")) as spawn:
                        with mock.patch.object(self.remote["store"], "authorize_tool", side_effect=revoke_at_boundary):
                            self.call_remote(self.remote["bridge"].continue_run, task["run_id"], task["id"], "bob", requirements)
                            self.wait_native(receipt, {"completed", "failed"})
                        self.assertEqual(revoked, [scenario])
                        registered = next(tool for tool in self.registry.tools if tool.name == "run_experiment")
                        ctx = RunContext(run_id=task["run_id"], session_id=task["id"], user_id="bob", session_state={})
                        async def entrypoint():
                            return await registered.entrypoint(run_context=ctx, experiment="bounded-sort-v1")
                        with self.assertRaises((HTTPException, PermissionError, RuntimeError, RunCancelledException)):
                            self.call_remote(entrypoint)
                        spawn.assert_not_called()
                        self.assertEqual(self.remote["store"].effects(task["id"]), effects)
                        self.assertEqual(self.remote["store"].artifacts(task["id"]), artifacts)
                        self.assertFalse(any(event["type"] == "compute_started" for event in self.remote["store"].events(task["id"])))
                finally:
                    self.origin["auth"].authorization.assign("alice", "factory-user")
                    self.remote["auth"].authorization.assign("bob", "factory-user")

    def test_07_unknown_without_ticket_never_replays_or_frees_capacity(self):
        row = self.reserve()
        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
        with mock.patch.object(self.remote["bridge"], "submit", side_effect=httpx.ReadTimeout("Synthetic loss before visible admission")) as submit:
            with self.assertRaises(HTTPException):
                self.call(self.handoff.dispatch, "alice", row["task_id"])
            for _ in range(2):
                receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
                self.assertEqual(receipt["state"], "UNKNOWN")
                self.assertIsNone(receipt["remoteRunId"])
                self.assertFalse(receipt["allStopped"])
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), 0)
        self.assertFalse(self.remote["store"].task(prepared["remoteTaskId"])["terminal"])
        self.assertFalse(self.origin["store"].task(row["task_id"])["terminal"])

    def test_08_receiver_local_children_inherit_origin_guard_and_cannot_move_servers(self):
        row = self.reserve()
        self.call(self.handoff.prepare, "alice", row["task_id"])
        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(receipt, {"paused"})
        child = self.call_remote(self.remote["store"].delegation.create, "bob", receipt["remoteTaskId"], "sort", "literature", str(uuid4()))
        task = child["childTask"]
        child_receipt = {"remoteTaskId": task["id"]}
        self.wait_native(child_receipt, {"paused"})
        self.assertEqual(self.ticket_count(self.origin), 0)
        self.assertEqual(self.ticket_count(self.remote, task["id"]), 1)
        self.origin["auth"].authorization.unassign("alice", "factory-user")
        ctx = RunContext(run_id=task["run_id"], session_id=task["id"], user_id="bob", session_state={})
        with self.assertRaises(HTTPException):
            self.remote["store"].authorize_tool(ctx, "literature_search")
        self.origin["auth"].authorization.assign("alice", "factory-user")
        # A delegated plan cannot be imported as a new root on another server.
        delegated = self.remote["store"].plan(task["plan_id"], "bob")
        invalid = self.body(row).model_copy(update={"manifest": plan_manifest(delegated)})
        self.denied(409, self.receiver.prepare, "bob", invalid)

    def test_09_concurrent_dispatch_has_one_native_submission(self):
        row = self.reserve()
        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
        async def concurrently():
            return await asyncio.gather(self.receiver.dispatch("bob", prepared["id"]),
                                        self.receiver.dispatch("bob", prepared["id"]))
        with mock.patch.object(self.remote["bridge"], "submit", wraps=self.remote["bridge"].submit) as submit:
            receipts = self.call_remote(concurrently)
            self.assertEqual(receipts[0]["id"], receipts[1]["id"])
            self.assertEqual(submit.await_count, 1)
        self.wait_native(receipts[0], {"paused"})
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), 1)
        self.assertEqual(self.ticket_count(self.origin), 0)

    def test_10_positive_native_checksum_provenance_and_origin_capacity_release(self):
        sample = "Controlled remote checksum acceptance fixture"
        row = self.reserve(sample, application="checksum")
        self.call(self.handoff.prepare, "alice", row["task_id"])
        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(receipt, {"completed"})
        observed = self.call(self.handoff.receipt, "alice", row["task_id"])
        self.assertEqual(observed["applicationStatus"], "completed")
        self.assertTrue(observed["allStopped"])
        self.assertTrue(self.origin["store"].task(row["task_id"])["terminal"])
        self.assertEqual(len(observed["artifacts"]), 1)
        artifact = observed["artifacts"][0]
        metadata, content = self.remote["store"].artifact(receipt["remoteTaskId"], artifact["id"])
        self.assertEqual(metadata, artifact)
        self.assertEqual(hashlib.sha256(content).hexdigest(), artifact["sha256"])
        self.assertIn(hashlib.sha256(sample.encode()).hexdigest().encode(), content)
        self.assertEqual(self.origin["store"].artifacts(row["task_id"]), [])
        self.assertIsNone(self.origin["store"].task(row["task_id"])["run_id"])
        self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 1)
        self.assertEqual(self.ticket_count(self.origin), 0)

    def test_11_receiver_plan_review_is_separate_and_revision_rechecked(self):
        row = self.reserve()
        policy = self.remote["store"].plan_policy
        current = policy.current()
        original = PlanPolicyConfig(name=current["name"], revision=current["revision"], review_ttl_seconds=current["review_ttl_seconds"])
        strict = PlanPolicyConfig(name="admin-review", revision="remote-review-" + uuid4().hex)
        policy.replace_configuration(strict, expected_revision=original.revision)
        try:
            with self.assertRaises(HTTPException) as caught:
                self.call(self.handoff.prepare, "alice", row["task_id"])
            self.assertEqual(caught.exception.status_code, 409)
            intent = self.call(self.handoff.receipt, "alice", row["task_id"])
            self.assertEqual(intent["state"], "PREPARING")
            self.assertIsNone(intent["remoteTaskId"])
            self.assertEqual(self.ticket_count(self.origin), 0)
            review = policy.request_review("bob", intent["remotePlanId"], str(uuid4()))
            self.denied(403, policy.decide, "bob", review["id"], True, str(uuid4()))
            policy.decide("manager", review["id"], True, str(uuid4()))
            prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
            self.assertEqual(prepared["id"], intent["id"])
            self.assertEqual(prepared["remotePlanId"], intent["remotePlanId"])
            self.assertEqual(prepared["state"], "PREPARED")
            receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
            self.wait_native(receipt, {"paused"})
            task = self.remote["store"].task(receipt["remoteTaskId"])
            ctx = RunContext(run_id=task["run_id"], session_id=task["id"], user_id="bob", session_state={})
            changed = PlanPolicyConfig(name="admin-review", revision="remote-review-next-" + uuid4().hex)
            policy.replace_configuration(changed, expected_revision=strict.revision)
            with self.assertRaises(HTTPException) as changed_revision:
                self.remote["store"].authorize_tool(ctx, "literature_search")
            self.assertEqual(changed_revision.exception.status_code, 409)
            self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 1)
        finally:
            policy.replace_configuration(original, expected_revision=policy.current()["revision"])

    def test_12_immutable_material_changes_and_server_change_do_not_admit(self):
        row = self.reserve()
        manifest = copy.deepcopy(row["body"]["manifest"])
        plan = manifest["plan"]
        material = plan["materials"][0]
        material["content"] = "Changed synthetic approved-material fixture"
        material["sha256"] = digest({k: v for k, v in material.items() if k not in {"sha256", "published", "createdAt"}})
        plan["materialRefs"][0]["sha256"] = material["sha256"]
        plan["fingerprint"] = digest({k: v for k, v in plan.items() if k not in {"id", "createdAt", "fingerprint"}})
        manifest["sha256"] = digest(plan)
        self.denied(409, self.receiver.prepare, "bob", self.body(row).model_copy(update={"manifest": manifest}))
        self.assertEqual(self.remote["store"].sql("SELECT * FROM af_remote_handoffs WHERE origin_task=:id", id=row["task_id"]), [])
        old = self.original_target
        alternate = HandoffTarget("another-receiver", old.origin_ref, old.base_url, old.identity_map, old.headers, old.transport)
        self.handoff.targets["another-receiver"] = alternate
        try:
            self.denied(409, self.handoff.reserve, "alice", plan["id"], "another-receiver", row["request_id"])
        finally:
            self.handoff.targets.pop("another-receiver")
        self.assertEqual(self.ticket_count(self.origin), 0)

    def test_13_forwarded_questions_local_children_scoped_reads_and_artifact_bytes(self):
        row = self.reserve()
        self.call(self.handoff.prepare, "alice", row["task_id"])
        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(receipt, {"paused"})
        child = self.call(self.handoff.delegate, "alice", row["task_id"], "sort", "literature", str(uuid4()))
        child_id = child["childTask"]["id"]
        self.wait_native({"remoteTaskId": child_id}, {"paused"})
        children = self.call(self.handoff.children, "alice", row["task_id"])
        self.assertEqual([entry["taskId"] for entry in children], [child_id])
        with self.assertRaises(HTTPException) as wrong_tree:
            self.call(self.handoff.detail, "alice", row["task_id"], str(uuid4()))
        self.assertEqual(wrong_tree.exception.status_code, 404)
        for remote_id in (child_id, None):
            detail = self.call(self.handoff.detail, "alice", row["task_id"], remote_id)
            question = detail["job"]["questionDetail"]
            body = {"questionId": question["id"], "version": question["version"], "answer": "Controlled remote sorting method scope"}
            with self.assertRaises(HTTPException) as stale:
                self.call(self.handoff.answer, "alice", row["task_id"], {**body, "version": question["version"] + 1}, remote_id)
            self.assertEqual(stale.exception.status_code, 409)
            self.call(self.handoff.answer, "alice", row["task_id"], body, remote_id)
            self.wait_native({"remoteTaskId": remote_id or receipt["remoteTaskId"]}, {"completed"})
            completed = self.call(self.handoff.detail, "alice", row["task_id"], remote_id)
            self.assertEqual(completed["job"]["status"], "completed")
            artifact = completed["artifacts"][0]
            metadata, content = self.call(self.handoff.artifact, "alice", row["task_id"], artifact["id"], remote_id)
            self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(self.ticket_count(self.origin), 0)
        self.assertTrue(self.call(self.handoff.receipt, "alice", row["task_id"])["allStopped"])

    def test_14_cancel_after_origin_cancellation_and_policy_expiry_still_reconciles(self):
        row = self.reserve("Controlled remote experimental sorting fixture", "experiment")
        self.call(self.handoff.prepare, "alice", row["task_id"])
        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(receipt, {"paused"})
        child = self.call(self.handoff.delegate, "alice", row["task_id"], "sort", "literature", str(uuid4()))
        self.wait_native({"remoteTaskId": child["childTask"]["id"]}, {"paused"})
        detail = self.call(self.handoff.detail, "alice", row["task_id"])
        approval = detail["job"]["approvalDetail"]
        self.call(self.handoff.approve, "alice", row["task_id"], {"requirementId": approval["id"], "version": approval["version"], "approved": True})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if any(event["type"] == "compute_started" for event in self.remote["store"].events(receipt["remoteTaskId"])):
                break
            time.sleep(.02)
        else:
            self.fail("Actual receiver experiment did not start")
        self.origin_settings.temporary_policy = "unset"
        self.remote_settings.temporary_policy = "unset"
        result = self.call(self.handoff.cancel, "alice", row["task_id"])
        self.assertTrue(self.origin["store"].task(row["task_id"])["cancel_requested"])
        # The autonomous observer may already have issued the child's native
        # cancel. Current durable intent and positive whole-tree stop are the
        # contract; this request's newly-signaled subset depends on timing.
        for identifier in (receipt["remoteTaskId"], child["childTask"]["id"]):
            self.assertTrue(self.remote["store"].task(identifier, "bob")["cancel_requested"])
        self.assertEqual(result["errors"], [])
        deadline = time.monotonic() + 15
        observed = {}
        while time.monotonic() < deadline:
            observed = self.call(self.handoff.receipt, "alice", row["task_id"])
            if observed["allStopped"] and all(self.remote["store"].task(identifier, "bob")["terminal"]
                    for identifier in (receipt["remoteTaskId"], child["childTask"]["id"])):
                break
            time.sleep(.03)
        self.assertTrue(observed["allStopped"], observed)
        self.assertEqual(observed["applicationStatus"], "canceled")
        for identifier in (receipt["remoteTaskId"], child["childTask"]["id"]):
            task = self.remote["store"].task(identifier, "bob")
            self.assertTrue(task["cancel_requested"])
            self.assertTrue(task["terminal"])
            self.assertEqual(self.remote["store"].native_db.get_job(task["run_id"], strict=True)["status"], "cancelled")
        effects = self.remote["store"].effects(receipt["remoteTaskId"])
        self.assertEqual([effect["status"] for effect in effects], ["CANCELLED"])
        self.assertTrue(any(event["type"] == "compute_stopped" and event["data"].get("cleanupComplete") for event in self.remote["store"].events(receipt["remoteTaskId"])))
        self.assertFalse(any(event["type"] == "experiment_completed" for event in self.remote["store"].events(receipt["remoteTaskId"])))
        self.assertTrue(self.origin["store"].task(row["task_id"])["terminal"])

    def test_15_cancel_before_dispatch_has_positive_no_execution_proof(self):
        row = self.reserve()
        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
        result = self.call(self.handoff.cancel, "alice", row["task_id"])
        self.assertEqual(result["receipt"]["state"], "CANCELLED_NO_DISPATCH")
        self.assertTrue(result["receipt"]["allStopped"])
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), 0)
        with self.assertRaises(HTTPException):
            self.call_remote(self.receiver.dispatch, "bob", prepared["id"])
        self.assertTrue(self.origin["store"].task(row["task_id"])["terminal"])

    def test_16_origin_lost_dispatch_before_receiver_boundary_never_replays(self):
        row = self.reserve()
        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
        original = self.handoff._request
        attempted = []
        async def drop_before_send(owner, target, method, path, **kwargs):
            if method == "POST" and path.endswith("/dispatch"):
                attempted.append(path)
                raise HTTPException(503, "Synthetic lost request before observable receiver boundary")
            return await original(owner, target, method, path, **kwargs)
        with mock.patch.object(self.handoff, "_request", side_effect=drop_before_send):
            with self.assertRaises(HTTPException):
                self.call(self.handoff.dispatch, "alice", row["task_id"])
            for _ in range(2):
                observed = self.call(self.handoff.dispatch, "alice", row["task_id"])
                self.assertEqual(observed["state"], "PREPARED")
                self.assertEqual(observed["originDispatchState"], "DISPATCH_UNKNOWN")
            self.assertEqual(len(attempted), 1)
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), 0)
        self.assertFalse(self.origin["store"].task(row["task_id"])["terminal"])

    def test_17_current_read_grant_can_observe_when_execution_grant_is_revoked(self):
        row = self.reserve()
        self.call(self.handoff.prepare, "alice", row["task_id"])
        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(receipt, {"paused"})
        before_artifacts = self.remote["store"].artifacts(receipt["remoteTaskId"])
        before_effects = self.remote["store"].effects(receipt["remoteTaskId"])
        for state, owner in ((self.origin, "alice"), (self.remote, "bob")):
            state["auth"].authorization.define_role("fixture-handoff-reader", ["agents:factory-executor:read", "sessions:read", "components:read", "registry:read"])
            state["auth"].authorization.unassign(owner, "factory-user")
            state["auth"].authorization.assign(owner, "fixture-handoff-reader")
        try:
            observed = self.call(self.handoff.receipt, "alice", row["task_id"])
            self.assertEqual(observed["remoteRunId"], receipt["remoteRunId"])
            detail = self.call(self.handoff.detail, "alice", row["task_id"])
            self.assertIn(detail["job"]["status"], {"waiting_input", "canceling", "failed"})
            snapshot = detail["snapshot"].get("run", detail["snapshot"])
            self.assertTrue(snapshot["readOnly"])
            self.assertEqual(snapshot["run_id"], receipt["remoteRunId"])
            self.assertEqual(snapshot["session_id"], receipt["remoteTaskId"])
            self.assertEqual(self.call(self.handoff.children, "alice", row["task_id"]), [])
            with self.assertRaises(HTTPException) as cannot_cancel:
                self.call(self.handoff.cancel, "alice", row["task_id"])
            self.assertEqual(cannot_cancel.exception.status_code, 403)
            with self.assertRaises(HTTPException) as cannot_dispatch:
                self.call(self.handoff.dispatch, "alice", row["task_id"])
            self.assertEqual(cannot_dispatch.exception.status_code, 403)
            with self.assertRaises(HTTPException) as cannot_answer:
                self.call(self.handoff.answer, "alice", row["task_id"],
                          {"questionId": "fixture-denied", "version": 1, "answer": "No new execution grant"})
            self.assertEqual(cannot_answer.exception.status_code, 403)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                observed = self.call(self.handoff.receipt, "alice", row["task_id"])
                detail = self.call(self.handoff.detail, "alice", row["task_id"])
                if observed["allStopped"] and detail["job"]["status"] == "failed" and self.remote["store"].task(receipt["remoteTaskId"], "bob")["terminal"]:
                    break
                time.sleep(.03)
            self.assertTrue(observed["allStopped"], observed)
            self.assertEqual(detail["job"]["status"], "failed", detail)
            self.assertTrue(self.remote["store"].task(receipt["remoteTaskId"], "bob")["cancel_requested"])
            self.assertTrue(self.remote["store"].task(receipt["remoteTaskId"], "bob")["terminal"])
            self.assertTrue(self.origin["store"].task(row["task_id"], "alice")["terminal"])
            self.assertEqual(self.remote["store"].artifacts(receipt["remoteTaskId"]), before_artifacts)
            self.assertEqual(self.remote["store"].effects(receipt["remoteTaskId"]), before_effects)
            self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 1)
            self.assertEqual(self.ticket_count(self.origin), 0)
        finally:
            for state, owner in ((self.origin, "alice"), (self.remote, "bob")):
                state["auth"].authorization.unassign(owner, "fixture-handoff-reader")
                state["auth"].authorization.assign(owner, "factory-user")

    def test_18_stale_receipt_row_cannot_erase_sticky_dispatch_attempt(self):
        row = self.reserve()
        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
        stale = self.handoff._row("alice", row["task_id"])
        self.assertFalse(stale["body"]["dispatchAttempted"])
        self.origin["store"].sql("UPDATE af_remote_placements SET state='DISPATCH_UNKNOWN',body=jsonb_set(body,'{dispatchAttempted}','true'::jsonb) WHERE task_id=:id", id=row["task_id"])
        saved = self.handoff._save_receipt(stale, self.original_target, prepared)
        self.assertEqual(saved["originDispatchState"], "DISPATCH_UNKNOWN")
        current = self.handoff._row("alice", row["task_id"])
        self.assertTrue(current["body"]["dispatchAttempted"])
        self.assertEqual(current["state"], "DISPATCH_UNKNOWN")
        original = self.handoff._request
        async def forbid_submission(owner, target, method, path, **kwargs):
            if method == "POST" and path.endswith("/dispatch"):
                self.fail("Stale receipt erased a durable dispatch attempt")
            return await original(owner, target, method, path, **kwargs)
        with mock.patch.object(self.handoff, "_request", side_effect=forbid_submission):
            self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), 0)

    def test_19_unavailable_cancel_ack_keeps_origin_intent_and_read_recovery(self):
        row = self.reserve()
        self.call(self.handoff.prepare, "alice", row["task_id"])
        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(receipt, {"paused"})
        old = self.original_target
        self.handoff.targets["receiver"] = HandoffTarget(old.reference, old.origin_ref, old.base_url, old.identity_map,
                                                         old.headers, LostReplyTransport(self.remote_app, "/cancel"))
        with self.assertRaises(HTTPException) as unknown:
            self.call(self.handoff.cancel, "alice", row["task_id"])
        self.assertEqual(unknown.exception.status_code, 503)
        self.assertTrue(self.origin["store"].task(row["task_id"])["cancel_requested"])
        self.origin_settings.temporary_policy = self.remote_settings.temporary_policy = "unset"
        deadline = time.monotonic() + 15
        observed = {}
        while time.monotonic() < deadline:
            observed = self.call(self.handoff.receipt, "alice", row["task_id"])
            if observed["allStopped"]:
                break
            time.sleep(.03)
        self.assertTrue(observed["allStopped"], observed)
        self.assertTrue(self.origin["store"].task(row["task_id"])["terminal"])
        self.assertEqual(self.ticket_count(self.remote, receipt["remoteTaskId"]), 1)

    def test_20_prepare_cancel_race_cannot_leave_an_unbound_reservation(self):
        row = self.reserve()
        reached, release = threading.Event(), threading.Event()
        original = self.remote["store"].reserve_task
        def pause_reservation(*args):
            reached.set()
            if not release.wait(5):
                raise AssertionError("Controlled prepare cancellation race did not release")
            return original(*args)
        with mock.patch.object(self.remote["store"], "reserve_task", side_effect=pause_reservation):
            with ThreadPoolExecutor(max_workers=2) as workers:
                preparing = workers.submit(self.receiver.prepare, "bob", self.body(row))
                self.assertTrue(reached.wait(5))
                intent = self.remote["store"].sql("SELECT id FROM af_remote_handoffs WHERE origin_task=:id", id=row["task_id"])[0]
                canceling = workers.submit(self.call_remote, self.receiver.cancel, "bob", intent["id"])
                release.set()
                prepared = preparing.result(timeout=10)
                canceled = canceling.result(timeout=10)
        self.assertEqual(canceled["receipt"]["state"], "CANCELLED_NO_DISPATCH")
        self.assertTrue(canceled["receipt"]["allStopped"])
        self.assertEqual(canceled["receipt"]["remoteTaskId"], prepared["remoteTaskId"])
        task = self.remote["store"].task(prepared["remoteTaskId"])
        self.assertTrue(task["terminal"])
        self.assertTrue(task["cancel_requested"])
        self.assertEqual(self.ticket_count(self.remote, prepared["remoteTaskId"]), 0)


    def test_21_misbound_trusted_cancel_denies_native_continuation_without_touching_other_run(self):
        row = self.reserve()
        self.call(self.handoff.prepare, "alice", row["task_id"])
        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
        self.wait_native(receipt, {"paused"})
        foreign = self.reserve()
        self.call(self.handoff.prepare, "alice", foreign["task_id"])
        foreign_receipt = self.call(self.handoff.dispatch, "alice", foreign["task_id"])
        self.wait_native(foreign_receipt, {"paused"})
        detail = self.call(self.handoff.detail, "alice", row["task_id"])
        question = detail["job"]["questionDetail"]
        body = {"questionId": question["id"], "version": question["version"],
                "answer": "Controlled native continuation must remain denied"}
        identifiers = (receipt["remoteTaskId"], foreign_receipt["remoteTaskId"])
        before = {identifier: {"effects": self.remote["store"].effects(identifier),
                               "artifacts": self.remote["store"].artifacts(identifier)} for identifier in identifiers}
        ticket_count = self.ticket_count(self.remote)
        original = self.receiver.origins["origin-fixture"]
        wired = self.remote["lifecycle_observer"]
        # A denial itself authorizes cleanup of the exact bound current run.
        # Stop this fixture's autonomous observer to isolate the rejected HTTP
        # action and prove the misbound signal cannot target either native run.
        self.call_remote(wired.stop)
        try:
            for mutation in ("owner", "task", "manifest"):
                def misbound(owner, task_id, manifest_hash, tool):
                    if task_id != row["task_id"]:
                        return original.authorize(owner, task_id, manifest_hash, tool)
                    raise HandoffCancellationRequested(
                        "bob" if mutation == "owner" else owner,
                        foreign["task_id"] if mutation == "task" else task_id,
                        "0" * 64 if mutation == "manifest" else manifest_hash)
                self.receiver.origins["origin-fixture"] = TrustedOrigin(original.reference, original.identity_map, misbound)
                with self.subTest(mutation=mutation), mock.patch("agent_factory.lifecycle_observer.Agent.acancel_run") as signal:
                    with self.assertRaises(HTTPException) as denied:
                        self.call(self.handoff.answer, "alice", row["task_id"], body)
                    self.assertEqual(denied.exception.status_code, 403)
                    signal.assert_not_called()
                    for identifier in identifiers:
                        task = self.remote["store"].task(identifier, "bob")
                        self.assertFalse(task["cancel_requested"])
                        self.assertFalse(task["terminal"])
                        self.assertEqual(self.remote["store"].native_db.get_job(task["run_id"], strict=True)["status"], "paused")
                        self.assertEqual(self.remote["store"].effects(identifier), before[identifier]["effects"])
                        self.assertEqual(self.remote["store"].artifacts(identifier), before[identifier]["artifacts"])
                    self.assertEqual(self.ticket_count(self.remote), ticket_count)
                    self.assertFalse(self.origin["store"].task(row["task_id"], "alice")["terminal"])
                    self.assertFalse(self.origin["store"].task(foreign["task_id"], "alice")["terminal"])
        finally:
            self.receiver.origins["origin-fixture"] = original
            self.call_remote(wired.start)

    def test_22_late_origin_cancel_at_native_recheck_returns_public_409_without_dispatch_or_continuation(self):
        wired = self.remote["lifecycle_observer"]
        self.call_remote(wired.stop)
        try:
            for stage in ("prepare", "dispatch", "answer", "children"):
                with self.subTest(stage=stage):
                    row = self.reserve()
                    prepared = None
                    if stage != "prepare":
                        prepared = self.call(self.handoff.prepare, "alice", row["task_id"])
                    if stage in {"answer", "children"}:
                        receipt = self.call(self.handoff.dispatch, "alice", row["task_id"])
                        native = self.wait_native(receipt, {"paused"})
                        detail = self.call(self.handoff.detail, "alice", row["task_id"])
                        task = self.remote["store"].task(receipt["remoteTaskId"], "bob")
                    before_tickets = self.ticket_count(self.remote)
                    entered = []
                    original = self.remote["store"].require_plan_execution

                    def cancel_at_recheck(owner, plan, *, run_context=None):
                        entered.append(plan["id"])
                        self.origin["store"].request_cancel(row["task_id"])
                        return original(owner, plan, run_context=run_context)

                    if stage in {"prepare", "dispatch"}:
                        def cancel_at_admission(owner, plan):
                            return cancel_at_recheck(owner, plan)
                        patch = mock.patch.object(self.receiver, "admission_guard", side_effect=cancel_at_admission)
                    else:
                        patch = mock.patch.object(self.remote["store"], "require_plan_execution", side_effect=cancel_at_recheck)
                    path = "/api/factory/remote-handoffs"
                    if stage == "prepare":
                        body = self.body(row).model_dump(mode="json")
                        path += "/prepare"
                    else:
                        path += "/" + prepared["id"] + "/" + stage
                        if stage == "answer":
                            question = detail["job"]["questionDetail"]
                            body = {"questionId": question["id"], "version": question["version"], "answer": "Controlled canceled scope"}
                        elif stage == "children":
                            body = {"goal": "sort", "mode": "literature", "requestId": str(uuid4())}
                        else:
                            body = {}
                    # The first public origin check succeeds. Cancellation is
                    # committed only inside the subsequent installed native
                    # plan/admission guard. The HTTP route must contain it.
                    with patch:
                        response = self.remote_client.post(path, headers=self.headers(self.remote, "bob"), json=body)
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(len(entered), 1)
                    self.assertIn("cancellation", response.json()["message"])
                    self.assertEqual(self.ticket_count(self.remote), before_tickets)
                    records = self.remote["store"].sql("SELECT * FROM af_remote_handoffs WHERE origin_task=:id", id=row["task_id"])
                    self.assertEqual(len(records), 1)
                    record = records[0]
                    if stage == "prepare":
                        self.assertEqual(record["state"], "PREPARING")
                        self.assertIsNone(record["body"]["remoteTaskId"])
                    elif stage == "dispatch":
                        self.assertEqual(record["state"], "PREPARED")
                        self.assertIsNone(self.remote["store"].task(prepared["remoteTaskId"], "bob")["run_id"])
                    else:
                        unchanged = self.remote["store"].native_db.get_job(task["run_id"], strict=True)
                        self.assertEqual(unchanged["status"], "paused")
                        self.assertEqual(unchanged["attempt"], native["attempt"])
                        self.assertFalse(self.remote["store"].task(task["id"], "bob")["terminal"])
                        self.assertEqual(self.remote["store"].effects(task["id"]), [])
                        self.assertEqual(self.remote["store"].artifacts(task["id"]), [])
                        self.assertEqual(self.remote["store"].sql("SELECT * FROM af_delegation_links WHERE root_id=:id", id=task["id"]), [])
        finally:
            self.call_remote(wired.start)

if __name__ == "__main__":
    unittest.main()

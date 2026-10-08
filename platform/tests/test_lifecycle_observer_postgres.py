"""Actual native queued/paused/running cleanup without product detail polling.

PostgreSQL and native authentication/queue/HITL are real. Provider output is
synthetic; failure injection is explicitly bounded to these disposable apps.
"""
import copy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from uuid import uuid4

from agno.db.base import SessionType
from agno.exceptions import InputCheckError
from agno.run import RunContext
from fastapi import HTTPException
from fastapi.testclient import TestClient

from pg_fixture import IsolatedPostgres
from agent_factory.config import Settings
from agent_factory.lifecycle_observer import FactoryLifecycleObserver
from agent_factory.main import create_app
from agent_factory.plan_policy import PlanPolicyConfig
from agent_factory.tools import build_tools


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class LifecycleObserverPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.settings = Settings(db_url=cls.database.url, workspace=Path(cls.workspace.name), max_workers=2,
                                max_user_tasks=12, max_total_tasks=24, queue_poll=.03)
        cls.app = create_app(cls.settings)
        cls.state = cls.app.app.state.factory
        cls.store, cls.auth, cls.bridge = cls.state["store"], cls.state["auth"], cls.state["bridge"]
        cls.addClassCleanup(cls.store.engine.dispose)
        cls.addClassCleanup(cls.store.native_db.db_engine.dispose)
        cls.client = TestClient(cls.app).__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    def setUp(self):
        self.wired = self.state["lifecycle_observer"]
        self.assertIs(self.store.lifecycle_observer, self.wired)
        self.call(self.wired.stop)  # Manual fault fixtures own one observer, not two.
        self.observer = FactoryLifecycleObserver(self.store, self.auth, self.store.native_db,
                                                 lambda: self.app.app.state.queue_worker, interval=.05)
        self.owned = []
        self.auth.authorization.assign("alice", "factory-user")

    def tearDown(self):
        self.call(self.observer.stop)
        self.call(self.wired.stop)
        self.auth.authorization.assign("alice", "factory-user")
        self.call(self.app.app.state.queue_worker.start)
        for identifier in self.owned:
            self.store.request_cancel(identifier)
        self.call(self.observer.tick)

    def call(self, function, *args):
        return self.client.portal.call(function, *args)

    def headers(self):
        return {"Authorization": "Bearer " + self.auth._issue_native_token("alice")}

    def request(self, method, path, expected=200, **kwargs):
        response = self.client.request(method, "/api/factory" + path, headers=self.headers(), **kwargs)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def task(self, goal="sort", mode="literature", application="research"):
        plan = self.request("POST", "/plans", 201,
                            json={"topic": goal, "mode": mode, "application": application, "requestId": str(uuid4())})
        job = self.request("POST", "/instances", 202, json={"planId": plan["id"], "requestId": str(uuid4())})
        self.owned.append(job["id"])
        return job["id"]

    def child(self, parent):
        result = self.request("POST", f"/jobs/{parent}/children", 202,
                              json={"goal": "sort", "mode": "literature", "requestId": str(uuid4())})
        self.owned.append(result["job"]["id"])
        return result["job"]["id"]

    def native(self, identifier):
        task = self.store.task(identifier, "alice")
        return self.store.native_db.get_job(task["run_id"], strict=True) if task["run_id"] else None

    def wait_native(self, identifier, states):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            ticket = self.native(identifier)
            if ticket and ticket["status"] in states:
                return ticket
            time.sleep(.03)
        self.fail(f"Exact native ticket did not reach {states}: {ticket}")

    def wait_condition(self, condition, message, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.03)
        self.fail(message)

    def native_run_status(self, identifier):
        task = self.store.task(identifier)
        session = self.store.native_db.get_session(identifier, session_type=SessionType.AGENT, user_id="alice")
        raw = session.get_run(task["run_id"]).status
        return str(getattr(raw, "value", raw)).lower()

    def continue_native(self, identifier, *, answer=None, approved=None):
        task = self.store.task(identifier, "alice")
        snapshot = self.call(self.bridge.detail, task["run_id"], identifier, "alice")
        requirements = copy.deepcopy(snapshot.get("run", snapshot)["requirements"])
        requirement = requirements[0]
        tool = requirement["tool_execution"]
        if answer is not None:
            fields = requirement.get("user_input_schema") or tool["user_input_schema"]
            next(field for field in fields if field["name"] == "scope")["value"] = answer
            tool.update(user_input_schema=fields, answered=True)
            requirement["user_input_schema"] = fields
        else:
            requirement["confirmation"] = approved
            tool["confirmed"] = approved
        # Actual public native background continuation, with current owner auth.
        # No Factory detail read can perform automatic child cleanup afterwards.
        self.call(self.bridge.continue_run, task["run_id"], identifier, "alice", requirements)

    def assert_stopped_without_user_read(self, *identifiers):
        self.wait_condition(lambda: all(self.store.task(identifier, "alice")["terminal"] for identifier in identifiers),
                            "Background observer did not positively settle every owned native task")
        for identifier in identifiers:
            task = self.store.task(identifier, "alice")
            self.assertTrue(task["cancel_requested"])
            self.assertIn(self.native(identifier)["status"], {"cancelled", "completed"} if any(event["type"] == "protected_denied" for event in self.store.events(identifier)) else {"cancelled"})
            self.assertFalse(any(effect["status"] == "UNKNOWN" for effect in self.store.effects(identifier)))
        observed = self.call(self.observer.observe_root, identifiers[0])
        self.assertTrue(observed["allStopped"], observed)
        self.assertFalse(observed["errors"], observed)

    def test_01_actual_protected_root_failure_cancels_paused_descendants_in_background(self):
        root = self.task()
        self.wait_native(root, {"paused"})
        child = self.child(root)
        self.wait_native(child, {"paused"})
        grandchild = self.child(child)
        self.wait_native(grandchild, {"paused"})
        original = self.store.authorize_tool
        def deny_root_literature(context, name):
            if context.session_id == root and name == "literature_search":
                raise PermissionError("Controlled protected-tool failure after actual native HITL")
            return original(context, name)
        self.call(self.observer.start)
        with mock.patch.object(self.store, "authorize_tool", side_effect=deny_root_literature):
            self.continue_native(root, answer="Controlled evidence scope for synthetic sorting")
            self.wait_condition(lambda: any(event["type"] == "protected_denied" for event in self.store.events(root)),
                                "Actual native tool pre-hook did not persist its protected failure")
            with mock.patch.object(self.auth, "_issue_native_token", side_effect=AssertionError("Observer must never mint an impersonation token")):
                self.assert_stopped_without_user_read(root, child, grandchild)
        self.call(self.observer.stop)
        before = {identifier: len(self.store.events(identifier)) for identifier in (root, child, grandchild)}
        self.call(self.observer.tick)
        self.assertEqual(before, {identifier: len(self.store.events(identifier)) for identifier in before})
        self.assertEqual([event["type"] for event in self.store.events(root)].count("lifecycle_cleanup_requested"), 1)

    def test_02_current_role_revocation_cleans_paused_root_and_unstarted_queued_child(self):
        root = self.task()
        self.wait_native(root, {"paused"})
        worker = self.app.app.state.queue_worker
        self.call(worker.stop)
        child = self.child(root)
        ticket = self.wait_native(child, {"queued"})
        self.assertEqual(ticket["attempt"], 0)
        self.assertEqual(self.store.artifacts(child), [])
        self.auth.authorization.unassign("alice", "factory-user")
        with mock.patch.object(self.auth, "_issue_native_token", side_effect=AssertionError("Cleanup is not owner impersonation")):
            self.call(self.observer.start)
            self.assert_stopped_without_user_read(root, child)
            self.call(self.observer.stop)
        self.assertNotIn("factory-user", self.auth.authorization.roles_of("alice"))
        self.assertEqual(self.store.artifacts(child), [])
        self.assertFalse(any(event["type"] == "plan_bound" for event in self.store.events(child)))
        self.assertTrue(self.store.sql("SELECT reclaimed FROM af_delegation_roots WHERE root_id=:id", id=root)[0]["reclaimed"])

    def test_03_unconfirmed_no_ticket_intent_never_releases_after_authority_loss(self):
        with mock.patch.object(self.bridge, "submit", side_effect=HTTPException(503, "Controlled native acceptance uncertainty")):
            root = self.task()
        self.assertIsNone(self.native(root))
        self.auth.authorization.unassign("alice", "factory-user")
        with mock.patch("agent_factory.lifecycle_observer.Agent.acancel_run") as signal:
            observed = self.call(self.observer.observe_root, root)
        self.assertFalse(observed["allStopped"], observed)
        self.assertTrue(observed["facts"][0]["unknown"])
        self.assertFalse(self.store.task(root, "alice")["terminal"])
        self.assertTrue(self.store.task(root, "alice")["cancel_requested"])
        signal.assert_not_called()
        self.call(self.observer.tick)
        self.assertFalse(self.store.task(root, "alice")["terminal"])

    def test_04_mismatched_native_owner_envelope_or_original_key_prevents_cancellation_and_release(self):
        root = self.task()
        self.wait_native(root, {"paused"})
        child = self.child(root)
        self.wait_native(child, {"paused"})
        self.store.event(root, "protected_denied", "Controlled binding-verification fixture trigger", {"syntheticFixture": True})
        self.store.sql("""INSERT INTO af_events(task_id,type,message,data,created_at)
            SELECT :id,'fixture_progress','Controlled old-failure display-window fixture','{}'::jsonb,'fixture'
            FROM generate_series(1,1005)""", id=root)
        self.assertFalse(any(event["type"] == "protected_denied" for event in self.store.events(root)))
        self.assertTrue(self.store.has_failures(root))
        original = self.store.native_db.get_job
        child_run = self.store.task(child)["run_id"]
        for mutation in ("owner", "envelope", "key"):
            def mismatched(identifier, *args, **kwargs):
                ticket = copy.deepcopy(original(identifier, *args, **kwargs))
                if identifier == child_run:
                    if mutation == "owner":
                        ticket["user_id"] = "bob"
                    elif mutation == "key":
                        ticket["idempotency_key"] = "controlled-wrong-original-key"
                    else:
                        ticket["payload"]["kwargs"]["session_state"]["factory_envelope"]["task_id"] = str(uuid4())
                return ticket
            with self.subTest(mutation=mutation), mock.patch.object(self.store.native_db, "get_job", side_effect=mismatched):
                observed = self.call(self.observer.observe_root, root)
                self.assertFalse(observed["allStopped"], observed)
                self.assertTrue(any(fact.get("errorType") == "ValueError" for fact in observed["facts"]))
                self.assertEqual(original(child_run, strict=True)["status"], "paused")
                self.assertFalse(self.store.task(root)["terminal"])
                self.assertFalse(self.store.task(child)["terminal"])
        self.call(self.observer.start)
        self.assert_stopped_without_user_read(root, child)

    def test_05_running_authority_loss_signals_native_cleanup_and_requires_queue_stop_proof(self):
        root = self.task("Controlled bounded synthetic running experiment", "experiment")
        self.wait_native(root, {"paused"})
        child = self.child(root)
        self.wait_native(child, {"paused"})
        self.continue_native(root, approved=True)
        self.wait_condition(lambda: any(event["type"] == "compute_started" for event in self.store.events(root)),
                            "Actual owned experiment process did not start")
        self.auth.authorization.unassign("alice", "factory-user")
        self.call(self.observer.start)
        self.wait_condition(lambda: any(event["type"] == "compute_stopped" and event["data"].get("cleanupComplete")
                                       for event in self.store.events(root)), "Owned running process did not clean up")
        self.wait_condition(lambda: self.native(child)["status"] == "cancelled", "Paused child was not natively canceled")
        self.wait_condition(lambda: [effect["status"] for effect in self.store.effects(root)] == ["CANCELLED"],
                            "Actual experiment effect was not positively canceled")
        self.wait_condition(lambda: self.native_run_status(root) == "cancelled",
                            "Native persisted running run did not reach cancellation")
        observed = self.call(self.observer.observe_root, root)
        queue_status = self.native(root)["status"]
        if queue_status == "running":
            self.assertFalse(observed["allStopped"], observed)
            self.assertFalse(self.store.task(root)["terminal"], "Persisted cancelled RunOutput is not running-ticket stop proof")
        else:
            self.assertIn(queue_status, {"cancelled", "failed"})
            self.assertTrue(observed["allStopped"], observed)
        self.assertTrue(self.store.task(root)["cancel_requested"])
        self.assertFalse(any(event["type"] == "experiment_completed" for event in self.store.events(root)))
        self.assertNotIn("factory-user", self.auth.authorization.roles_of("alice"))
        print(f"Native running cleanup evidence: persistedRun=cancelled, effects=CANCELLED, queue={queue_status}, allStopped={observed['allStopped']}")

    def test_06_unknown_authority_store_does_not_imply_known_revocation(self):
        root = self.task()
        self.wait_native(root, {"paused"})
        with mock.patch.object(self.auth, "require", side_effect=HTTPException(503, "Controlled authorization store outage")), \
             mock.patch("agent_factory.lifecycle_observer.Agent.acancel_run") as signal:
            observed = self.call(self.observer.observe_root, root)
        self.assertTrue(observed["errors"], observed)
        self.assertFalse(observed["allStopped"])
        self.assertEqual(self.native(root)["status"], "paused")
        self.assertFalse(self.store.task(root)["cancel_requested"])
        self.assertFalse(self.store.task(root)["terminal"])
        signal.assert_not_called()

    def test_07_settled_unrelated_completed_root_stays_unchanged_and_rejects_new_child(self):
        root = self.task("Controlled settled checksum evidence", application="checksum")
        self.wait_native(root, {"completed"})
        settled = self.call(self.observer.observe_root, root)
        self.assertTrue(settled["allStopped"], settled)
        self.assertTrue(self.store.task(root)["terminal"])
        events = self.store.events(root)
        artifacts = self.store.artifacts(root)
        self.auth.authorization.unassign("alice", "factory-user")
        with mock.patch("agent_factory.lifecycle_observer.Agent.acancel_run") as signal:
            unchanged = self.call(self.observer.observe_root, root)
        self.assertTrue(unchanged["allStopped"])
        self.assertEqual(unchanged["requested"], [])
        self.assertFalse(self.store.task(root)["cancel_requested"])
        self.assertEqual(self.store.events(root), events)
        self.assertEqual(self.store.artifacts(root), artifacts)
        signal.assert_not_called()
        self.auth.authorization.assign("alice", "factory-user")
        self.request("POST", f"/jobs/{root}/children", 409,
                     json={"goal": "Controlled late child", "mode": "literature", "requestId": str(uuid4())})
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_links WHERE root_id=:id", id=root)[0]["n"], 0)

    def test_08_bounded_rotation_observes_healthy_work_among_persisted_unknown_roots(self):
        with mock.patch.object(self.bridge, "submit", side_effect=HTTPException(503, "Controlled no-ticket acceptance uncertainty")):
            unknown = [self.task() for _ in range(3)]
        healthy = self.task()
        self.wait_native(healthy, {"paused"})
        bounded = FactoryLifecycleObserver(self.store, self.auth, self.store.native_db,
                                           lambda: self.app.app.state.queue_worker, batch_limit=1)
        expected = {row["id"] for row in self.store.sql("""SELECT id FROM af_tasks task WHERE NOT terminal
            AND NOT EXISTS(SELECT 1 FROM af_delegation_links link WHERE link.child_id=task.id)""")}
        seen = set()
        for _ in range(len(expected) + 2):
            observed = self.call(bounded.tick)
            self.assertLessEqual(len(observed["groups"]) + len(observed["errors"]), 1)
            seen.update(group["rootTaskId"] for group in observed["groups"])
        self.assertTrue(expected <= seen, {"expected": expected, "observed": seen})
        self.assertEqual(self.native(healthy)["status"], "paused")
        self.assertFalse(self.store.task(healthy)["cancel_requested"])
        self.assertTrue(all(not self.store.task(identifier)["terminal"] for identifier in unknown))

    def test_09_cancelled_run_output_with_running_ticket_read_never_releases_capacity(self):
        root = self.task()
        self.wait_native(root, {"paused"})
        task = self.store.task(root)
        # Actual public native cancellation first, without a product detail
        # read that would change Factory capacity. Then inject only a stale
        # running-ticket read to test disagreement with persisted RunOutput.
        cancelled = self.call(self.app.app.state.queue_worker.acancel_queued, task["run_id"])
        self.assertTrue(cancelled)
        self.assertEqual(self.native_run_status(root), "cancelled")
        self.assertFalse(self.store.task(root)["terminal"])
        original = self.store.native_db.get_job
        def stale_running(identifier, *args, **kwargs):
            ticket = copy.deepcopy(original(identifier, *args, **kwargs))
            if identifier == task["run_id"]:
                ticket["status"] = "running"
            return ticket
        with mock.patch.object(self.store.native_db, "get_job", side_effect=stale_running):
            observed = self.call(self.observer.observe_root, root)
            self.assertFalse(observed["allStopped"], observed)
            self.assertEqual(observed["facts"][0]["persistedRunStatus"], "cancelled")
            self.assertEqual(observed["facts"][0]["nativeStatus"], "running")
            self.assertFalse(self.store.task(root)["terminal"])
        confirmed = self.call(self.observer.observe_root, root)
        self.assertTrue(confirmed["allStopped"], confirmed)
        self.assertTrue(self.store.task(root)["terminal"])

    def test_10_main_wired_observer_autonomously_cleans_revoked_native_tree_without_ui_reads(self):
        root = self.task()
        self.wait_native(root, {"paused"})
        child = self.child(root)
        self.wait_native(child, {"paused"})
        self.assertIs(self.wired.worker_getter(), self.app.app.state.queue_worker)
        self.auth.authorization.unassign("alice", "factory-user")
        with mock.patch.object(self.auth, "_issue_native_token", side_effect=AssertionError("Default cleanup must not impersonate owner")):
            self.call(self.wired.start)
            self.wait_condition(lambda: all(self.store.task(identifier)["terminal"] for identifier in (root, child)),
                                "Default main-wired observation did not autonomously confirm native tree stop")
            self.call(self.wired.stop)
        for identifier in (root, child):
            self.assertTrue(self.store.task(identifier)["cancel_requested"])
            self.assertEqual(self.native(identifier)["status"], "cancelled")
            self.assertEqual(self.store.artifacts(identifier), [])
        self.assertNotIn("factory-user", self.auth.authorization.roles_of("alice"))
        self.assertTrue(self.store.sql("SELECT reclaimed FROM af_delegation_roots WHERE root_id=:id", id=root)[0]["reclaimed"])


    def test_11_reviewed_healthy_child_survives_pre_ack_and_completed_with_pending_descendant(self):
        policy = self.state["plan_policy"]
        original = policy.current()
        policy.replace_configuration(PlanPolicyConfig(name="admin-review", revision="lifecycle-reviewed-child"),
                                     expected_revision=original["revision"])
        try:
            plan = self.request("POST", "/plans", 201,
                                json={"topic": "sort", "mode": "literature", "requestId": str(uuid4())})
            review = self.request("POST", "/plan-reviews", 201,
                                  json={"planId": plan["id"], "requestId": str(uuid4())})
            approved = self.client.post(f'/api/factory/plan-reviews/{review["id"]}/decision',
                headers={"Authorization": "Bearer " + self.auth._issue_native_token("manager")},
                json={"approved": True, "requestId": str(uuid4())})
            self.assertEqual(approved.status_code, 200, approved.text)
            job = self.request("POST", "/instances", 202,
                               json={"planId": plan["id"], "requestId": str(uuid4())})
            root = job["id"]
            self.owned.append(root)
            self.wait_native(root, {"paused"})
            original_submit = self.bridge.submit
            before_ack = []

            async def observe_bound_reservation(child_plan, owner, request_id):
                identifier = child_plan["task_id"]
                self.assertIsNone(self.store.task(identifier, owner)["run_id"])
                observed = await self.observer.observe_root(root)
                self.assertEqual(observed["errors"], [], observed)
                self.assertEqual(observed["requested"], [], observed)
                self.assertFalse(observed["allStopped"], observed)
                self.assertTrue(next(fact for fact in observed["facts"] if fact["taskId"] == identifier)["unknown"])
                self.assertFalse(self.store.task(identifier, owner)["cancel_requested"])
                before_ack.append(identifier)
                return await original_submit(child_plan, owner, request_id)

            with mock.patch.object(self.bridge, "submit", side_effect=observe_bound_reservation):
                child = self.child(root)
            self.assertEqual(before_ack, [child])
            self.wait_native(child, {"paused"})
            child_task = self.store.task(child, "alice")
            receipt = policy.require_execution("alice", child_task["plan_id"],
                run_context=mock.Mock(session_id=child, run_id=child_task["run_id"], user_id="alice"))
            self.assertTrue(receipt["inheritedFromRoot"])
            self.assertEqual(receipt["reviewId"], review["id"])
            grandchild = self.child(child)
            self.wait_native(grandchild, {"paused"})
            self.continue_native(child, answer="Controlled reviewed child synthetic evidence scope")
            self.wait_native(child, {"completed"})
            self.assertFalse(self.store.task(child)["terminal"])
            observed = self.call(self.observer.observe_root, root)
            self.assertEqual(observed["errors"], [], observed)
            self.assertEqual(observed["requested"], [], observed)
            self.assertFalse(observed["allStopped"], observed)
            self.assertFalse(self.store.task(child)["terminal"], "Paused descendant retains completed-child capacity")
            for identifier in (root, child, grandchild):
                self.assertFalse(self.store.task(identifier)["cancel_requested"])
                self.assertFalse(self.store.has_failures(identifier))
            self.assertEqual(self.native(root)["status"], "paused")
            self.assertEqual(self.native(grandchild)["status"], "paused")
            self.call(self.wired.start)
            self.continue_native(grandchild, answer="Controlled reviewed grandchild synthetic evidence scope")
            self.wait_native(grandchild, {"completed"})
            self.continue_native(root, answer="Controlled reviewed root synthetic evidence scope")
            self.wait_native(root, {"completed"})
            self.wait_condition(lambda: all(self.store.task(identifier)["terminal"] for identifier in (root, child, grandchild)),
                                "Default observer did not settle the healthy reviewed native group")
            self.call(self.wired.stop)
            for identifier in (root, child, grandchild):
                self.assertFalse(self.store.task(identifier)["cancel_requested"])
                self.assertFalse(self.store.has_failures(identifier))
                self.assertEqual(self.store.task(identifier)["body"]["lastStatus"], "completed")
            self.assertTrue(self.store.sql("SELECT reclaimed FROM af_delegation_roots WHERE root_id=:id", id=root)[0]["reclaimed"])
        finally:
            self.call(self.wired.stop)
            policy.replace_configuration(PlanPolicyConfig(name=original["name"], revision=original["revision"]),
                                         expected_revision="lifecycle-reviewed-child")

    def test_12_exact_native_ack_preserves_rejection_and_stop_and_denies_resumed_or_direct_effects(self):
        """Controlled rejection/late-ACK phases; native queues/HITL are real."""
        root = self.task()
        native = self.wait_native(root, {"paused"})
        original_task = self.store.task(root, "alice")
        before_effects, before_artifacts = self.store.effects(root), self.store.artifacts(root)
        before_bound_events = sum(event["type"] == "plan_bound" for event in self.store.events(root))
        self.store.admission_failed(root, "Controlled metadata rejection after actual native pause")
        self.store.accept(root, original_task["run_id"])
        self.assertEqual(self.store.task(root)["admission"], "rejected")
        self.assertFalse(self.store.task(root)["terminal"])
        context = RunContext(run_id=original_task["run_id"], session_id=root, user_id="alice",
            session_state={"factory_envelope": {"plan_ref": original_task["plan_id"], "user_id": "alice",
                "task_id": root, "request_id": original_task["request_id"]}})
        with self.assertRaisesRegex(InputCheckError, "admission is rejected"):
            self.store.bind_run(context)
        with self.assertRaisesRegex(InputCheckError, "admission is rejected"):
            build_tools(self.settings, self.store)["literature_search"]("Denied controlled direct research", run_context=context)
        self.assertEqual(self.native(root)["status"], "paused")
        self.assertEqual(self.native(root)["attempt"], native["attempt"])
        self.assertEqual(self.store.effects(root), before_effects)
        self.assertEqual(self.store.artifacts(root), before_artifacts)
        # Resume the real persisted HITL requirement through native HTTP. The
        # execution-only current-admission guard must deny before domain work.
        self.continue_native(root, answer="Controlled denied native continuation")
        self.wait_native(root, {"completed", "failed", "cancelled"})
        self.assertEqual(self.store.task(root)["admission"], "rejected")
        self.assertEqual(self.store.effects(root), before_effects)
        self.assertEqual(self.store.artifacts(root), before_artifacts)
        self.assertFalse(any(event["type"] in {"scope_answered", "literature_fixture", "compute_started"}
                             for event in self.store.events(root)))
        self.assertEqual(sum(event["type"] == "plan_bound" for event in self.store.events(root)), before_bound_events)
        observed = self.call(self.observer.observe_root, root)
        self.assertEqual(observed["errors"], [], observed)
        self.assertTrue(observed["allStopped"], observed)
        self.assertTrue(self.store.failure_cleanup_requested(root))
        settled_task, settled_events = self.store.task(root), self.store.events(root)
        for _ in range(3):
            self.store.accept(root, original_task["run_id"])
            self.assertEqual(self.store.task(root), settled_task)
        with self.assertRaises(InputCheckError):
            self.store.accept(root, str(uuid4()))
        self.assertEqual(self.store.task(root), settled_task)
        self.assertEqual(self.store.events(root), settled_events)

        worker = self.app.app.state.queue_worker
        self.call(worker.stop)
        try:
            plan = self.request("POST", "/plans", 201,
                json={"topic": "sort", "mode": "literature", "application": "research", "requestId": str(uuid4())})
            request_id = str(uuid4())
            waiting, fresh = self.store.reserve_task(plan, request_id)
            self.assertTrue(fresh)
            self.owned.append(waiting["id"])
            receipt = self.call(self.bridge.submit, {**plan, "task_id": waiting["id"]}, "alice", request_id)
            self.assertIsNone(self.store.task(waiting["id"])["run_id"])
            # Inject metadata rejection after actual queue commit, before its
            # delayed acknowledgment is bound. No worker executes this phase.
            self.store.admission_failed(waiting["id"], "Controlled rejection before delayed exact native acknowledgment")
            self.store.accept(waiting["id"], receipt["run_id"])
            bound = self.store.task(waiting["id"], "alice")
            self.assertEqual(bound["admission"], "rejected")
            self.assertFalse(bound["terminal"], "Known queued native work must keep capacity held")
            self.assertEqual(self.native(waiting["id"])["status"], "queued")
            self.assertEqual(self.native(waiting["id"])["attempt"], 0)
            observed = self.call(self.observer.observe_root, waiting["id"])
            self.assertEqual(observed["errors"], [], observed)
            self.assertTrue(observed["allStopped"], observed)
            settled = self.store.task(waiting["id"])
            self.assertTrue(settled["terminal"])
            self.assertEqual(settled["admission"], "rejected")
            self.assertEqual(self.native(waiting["id"])["status"], "cancelled")
            self.store.accept(waiting["id"], receipt["run_id"])
            self.assertEqual(self.store.task(waiting["id"]), settled)
            self.assertEqual(self.store.effects(waiting["id"]), [])
            self.assertEqual(self.store.artifacts(waiting["id"]), [])
            self.assertFalse(any(event["type"] == "plan_bound" for event in self.store.events(waiting["id"])))
        finally:
            self.call(worker.start)


    def test_13_terminal_orx_without_stop_proof_holds_every_capacity_projection(self):
        from agent_factory.factory_api import status_of
        from agent_factory.orx_experiment_tools import LAUNCH_EFFECT_KEY
        from agent_factory.store import canonical
        root = self.task("Controlled terminal ORX metadata fault", application="checksum")
        self.wait_native(root, {"completed"})
        task = self.store.task(root)
        run_id = task["run_id"]
        self.store.effect_reserve(run_id, LAUNCH_EFFECT_KEY, {"syntheticFault": True})
        for state in ("done", "failed", "cancelled"):
            with self.subTest(state=state):
                result = {"status": state, "cancelled": state == "cancelled",
                          "stopEvidence": {"allStopped": False, "activeProcesses": 1}}
                with self.assertRaisesRegex(ValueError, "positive adapter stop evidence"):
                    self.store.effect_complete(run_id, LAUNCH_EFFECT_KEY, result)
                # Reproduce pre-fix persisted DONE, rather than claiming a real
                # Windows orphan on this portable controlled-metadata fixture.
                self.store.sql("UPDATE af_effects SET status='DONE',result=CAST(:body AS JSONB) WHERE effect_key=:key",
                    body=canonical(result), key=run_id + ":" + LAUNCH_EFFECT_KEY)
                self.store.sql("UPDATE af_tasks SET terminal=TRUE WHERE id=:id", id=root)
                self.store.initialize()  # Pre-fix terminal capacity is re-held on upgrade.
                self.assertFalse(self.store.task(root)["terminal"])
                self.assertFalse(self.observer._facts(task)["stopped"])
                self.assertIn("unresolved", self.observer._reason(task, self.observer._binding(task)))
                group = self.call(self.store.delegation.inspect_group, "alice", root)
                self.assertFalse(group["allStopped"])
                self.assertEqual(status_of(task, {"queue": {"status": "completed"}}, self.store.effects(root), []), "unknown")
                self.store.reserve_task(self.store.plan(task["plan_id"], "alice"), task["request_id"])
                self.assertFalse(self.store.task(root)["terminal"])
        self.store.effect_complete(run_id, LAUNCH_EFFECT_KEY,
            {"status": "done", "stopEvidence": {"allStopped": True, "activeProcesses": 0}})
        self.assertTrue(self.observer._facts(task)["stopped"])
        self.assertTrue(self.call(self.store.delegation.inspect_group, "alice", root)["allStopped"])

    def test_14_revoked_cleanup_checks_actual_persisted_launch_fingerprint(self):
        from types import SimpleNamespace
        from agent_factory.connections import ConnectionService, TrustedConnectionBinding
        from agent_factory.orx_experiment_tools import ADAPTER_ID, LAUNCH_EFFECT_KEY, initialize_orx_experiments
        from agent_factory.store import canonical, digest
        root = self.task("Controlled cleanup-binding admission", application="checksum")
        self.wait_native(root, {"completed"})
        task = self.store.task(root)
        handle = SimpleNamespace(create_experiment_adapter=lambda **kwargs: None)
        registration = "cleanup-fixture-" + uuid4().hex
        registry = {registration: TrustedConnectionBinding("alice", "orx", ADAPTER_ID,
            frozenset({"research:read", "compute:local"}), "cleanup-fixture-v1", available=True,
            opaque_handle=handle, handle_ref="inert-cleanup-handle")}
        service = ConnectionService(self.store, self.auth, registry)
        bound = service.bind("alice", registration, uuid4().hex)
        pin = {key: bound[key] for key in ("ref", "version", "fingerprint", "revision", "capabilities", "taskId")}
        request = {"ownerId": "alice", "taskId": root, "planId": task["plan_id"],
                   "nativeRunId": task["run_id"], "connection": pin}
        binding = {**request, "projectId": "controlled-project", "experimentId": "controlled-experiment"}
        initialize_orx_experiments(self.store)
        self.store.sql("INSERT INTO af_orx_task_experiments VALUES(:task,:owner,:plan,:run,CAST(:binding AS JSONB),:hash,CAST(:observation AS JSONB),:ohash)",
            task=root, owner="alice", plan=task["plan_id"], run=task["run_id"], binding=canonical(binding), hash=digest(binding),
            observation=canonical({}), ohash=digest({}))
        self.store.effect_reserve(task["run_id"], LAUNCH_EFFECT_KEY, request)
        self.assertNotIn("fingerprint", self.store.effects(root)[-1])  # Public projection deliberately omits it.
        service.revoke("alice", pin["ref"], uuid4().hex)
        with self.assertRaises(HTTPException):
            service.resolve("alice", pin["ref"], "orx")
        self.auth.authorization.unassign("alice", "factory-user")
        self.assertIs(service.cleanup_handle("alice", pin, adapter_ref=ADAPTER_ID, task_id=root), handle)
        self.store.sql("UPDATE af_effects SET fingerprint=:hash WHERE effect_key=:key",
            hash="0" * 64, key=task["run_id"] + ":" + LAUNCH_EFFECT_KEY)
        with self.assertRaises(HTTPException) as changed:
            service.cleanup_handle("alice", pin, adapter_ref=ADAPTER_ID, task_id=root)
        self.assertIn("durable launch intent", str(changed.exception.detail))
        # Restore only this synthetic fixture so ordinary test teardown can run.
        self.store.sql("UPDATE af_effects SET fingerprint=:hash WHERE effect_key=:key",
            hash=digest(request), key=task["run_id"] + ":" + LAUNCH_EFFECT_KEY)

if __name__ == "__main__":
    unittest.main()

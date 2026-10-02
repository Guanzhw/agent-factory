"""Real native Agno queue delegation tests on a disposable PostgreSQL database.

FACTORY_TEST_DATABASE_URL is opt-in. Provider output alone is deterministic;
the worker, lifecycle, authentication, metadata and effects are native/real.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, func, select
from pg_fixture import IsolatedPostgres
from agno.exceptions import RunCancelledException
from agno.run import RunContext

from agent_factory.config import Settings
from agent_factory.delegation import DelegationService, application_group_status
from agent_factory.main import create_app
from agent_factory.runtime import build_runtime
from agent_factory.tools import DATASET_HASH


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class DelegationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        # Explicit hierarchy fixture override; application default remains two.
        cls.settings = Settings(db_url=cls.database.url, workspace=Path(cls.workspace.name), max_workers=1, max_user_tasks=8)
        def capture_registry(*args, **kwargs):
            result = build_runtime(*args, **kwargs)
            cls.registry = result[1]
            return result
        # Capture the actual sole registration, without replacing its loop/model.
        with mock.patch("agent_factory.main.build_runtime", side_effect=capture_registry):
            cls.app = create_app(cls.settings)
        cls.state = cls.app.app.state.factory
        cls.store, cls.auth, cls.bridge = (cls.state[name] for name in ("store", "auth", "bridge"))
        cls.addClassCleanup(cls.store.engine.dispose)
        cls.addClassCleanup(cls.store.native_db.db_engine.dispose)
        cls.service = DelegationService(cls.settings, cls.store, cls.auth, cls.bridge)
        cls.service.initialize()
        cls.store.delegation = cls.service
        cls.client = TestClient(cls.app).__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    def setUp(self):
        self.roots = []
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/factory/demo/login", json={"persona": "alice"}).status_code, 200)

    def tearDown(self):
        self.auth.authorization.assign("alice", "factory-user")
        for root in self.roots:
            self.call(self.service.cascade_cancel, "alice", root)
            self.wait_group(root)

    def call(self, function, *args):
        return self.client.portal.call(function, *args)

    def parent(self, mode="literature"):
        response = self.client.post("/api/factory/plans", json={"topic": "sort", "mode": mode, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        plan = response.json()
        response = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 202, response.text)
        task_id = response.json()["id"]
        self.roots.append(task_id)
        self.wait_native(task_id, {"paused"})
        return self.store.task(task_id, "alice")

    def child(self, parent, mode="literature", request=None, goal="sort"):
        result = self.call(self.service.create, "alice", parent["id"], goal, mode, request or str(uuid4()))
        if result["receipt"]:
            self.wait_native(result["childTask"]["id"], {"paused", "completed", "failed"})
        return result

    def wait_native(self, task_id, states):
        deadline = time.monotonic() + 15
        native = {}
        while time.monotonic() < deadline:
            task = self.store.task(task_id)
            native = self.store.native_db.get_job(task["run_id"]) if task.get("run_id") else {}
            if native and native["status"] in states:
                return native
            time.sleep(.05)
        self.fail(f"Native task {task_id} did not reach {states}: {native}")

    def wait_group(self, root, *, unknown=False):
        deadline = time.monotonic() + 15
        group = {}
        while time.monotonic() < deadline:
            group = self.call(self.service.inspect_group, "alice", root)
            if group["allStopped"] or (unknown and group["unknown"] and all(child["stopped"] or child["unknown"] for child in group["children"])):
                return group
            time.sleep(.05)
        self.fail(f"Group did not stop: {group}")

    def denied(self, status, function, *args):
        with self.assertRaises(HTTPException) as caught:
            self.call(function, *args)
        self.assertEqual(caught.exception.status_code, status, str(caught.exception.detail))

    def test_01_independent_tickets_duplicates_snapshot_and_restart_metadata(self):
        parent = self.parent()
        scope = self.service.delegation_scope("alice", parent["id"])
        self.assertTrue(scope["allowed"], scope)
        self.assertEqual(scope["sharedBudget"]["childrenUsed"], 0)
        request = str(uuid4())
        first = self.child(parent, request=request)
        second = self.child(parent, request=request, goal="  sort  ")
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["childTask"]["id"], second["childTask"]["id"])
        self.assertEqual(first["receipt"]["run_id"], second["receipt"]["run_id"])
        self.assertNotEqual(parent["run_id"], first["receipt"]["run_id"])
        self.denied(409, self.service.create, "alice", parent["id"], "changed", "literature", request)
        child = self.store.task(first["childTask"]["id"])
        native = self.store.native_db.get_job(child["run_id"])
        self.assertEqual(native["component_id"], "factory-executor")
        self.assertEqual(native["session_id"], child["id"])
        plan = self.store.plan(child["plan_id"])
        self.assertEqual(plan["budget"]["depth"], 1)
        pinned = copy.deepcopy(plan)
        self.store.add_material({"id": "research-prompt", "kind": "prompt", "name": "Changed synthetic prompt", "description": "Fixture", "content": "Later catalog update", "dependencies": [], "permissions": [], "compatibility": ["agno:3.1.0", "mode:demo"], "archived": False}, "manager", seed=True)
        self.assertEqual(self.store.plan(child["plan_id"]), pinned)
        recovered = DelegationService(self.settings, self.store, self.auth, self.bridge)
        recovered.initialize()
        children = self.call(recovered.children, "alice", parent["id"])
        self.assertEqual([entry["taskId"] for entry in children], [child["id"]])
        self.assertFalse(children[0]["stopped"])
        recovered.authorize_child(SimpleNamespace(run_id=child["run_id"], session_id=child["id"], user_id="alice"))

    def test_02_depth_and_root_lifetime_count(self):
        root = self.parent()
        first = self.child(root)["childTask"]
        grandchild = self.child(first)["childTask"]
        self.denied(429, self.service.create, "alice", grandchild["id"], "sort", "literature", str(uuid4()))
        second = self.child(root)["childTask"]
        self.child(second)
        self.denied(429, self.service.create, "alice", first["id"], "sort", "literature", str(uuid4()))
        group = self.call(self.service.inspect_group, "alice", root["id"])
        self.assertEqual(len(group["children"]), 4)
        self.assertEqual(sorted(entry["link"]["depth"] for entry in group["children"]), [1, 1, 2, 2])

    def test_03_owner_mode_subset_and_current_revocation(self):
        root = self.parent()
        self.denied(404, self.service.create, "bob", root["id"], "sort", "literature", str(uuid4()))
        with self.assertRaises(HTTPException) as inaccessible:
            self.service.delegation_scope("bob", root["id"])
        self.assertEqual(inaccessible.exception.status_code, 404)
        self.denied(403, self.service.create, "alice", root["id"], "sort", "experiment", str(uuid4()))
        child = self.child(root)["childTask"]
        before_tasks = self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"]
        db = self.store.native_db
        tickets = Table(db.job_table_name, MetaData(), schema=db.db_schema, autoload_with=db.db_engine)
        with db.db_engine.connect() as conn:
            before_tickets = conn.execute(select(func.count()).select_from(tickets)).scalar()
        reused = self.client.post("/api/factory/instances", json={"planId": child["plan_id"], "requestId": str(uuid4())})
        self.assertIn(reused.status_code, {403, 409}, reused.text)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], before_tasks)
        with db.db_engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(tickets)).scalar(), before_tickets)
        # Trusted-code defense independently rejects an unlinked delegated plan,
        # even if another adapter attempts ordinary Store admission.
        orphan, _ = self.store.reserve_task(self.store.plan(child["plan_id"]), "unlinked-fixture-" + str(uuid4()))
        try:
            with self.assertRaises(PermissionError):
                self.service.authorize_child(SimpleNamespace(run_id=orphan["id"], session_id=orphan["id"], user_id="alice"))
        finally:
            self.store.admission_failed(orphan["id"], "Controlled unlinked adapter fixture; never queued")
        self.auth.authorization.unassign("alice", "factory-user")
        try:
            self.assertFalse(self.service.delegation_scope("alice", root["id"])["allowed"])
            self.denied(403, self.service.create, "alice", root["id"], "sort", "literature", str(uuid4()))
            with self.assertRaises(PermissionError):
                self.service.authorize_child(SimpleNamespace(run_id=child["run_id"], session_id=child["id"], user_id="alice"))
        finally:
            self.auth.authorization.assign("alice", "factory-user")
        self.assertTrue(any(event["type"] == "protected_denied" for event in self.store.events(child["id"])))

    def test_04_existing_store_user_and_global_quota(self):
        self.assertEqual(Settings(db_url=self.settings.db_url).max_user_tasks, 2)
        root = self.parent()
        self.child(root)
        old_user, old_total = self.settings.max_user_tasks, self.settings.max_total_tasks
        try:
            self.settings.max_user_tasks = 2
            self.denied(429, self.service.create, "alice", root["id"], "sort", "literature", str(uuid4()))
            self.settings.max_user_tasks = 8
            self.settings.max_total_tasks = 2
            self.denied(429, self.service.create, "alice", root["id"], "sort", "literature", str(uuid4()))
            self.assertEqual(len(self.call(self.service.children, "alice", root["id"])), 1)
        finally:
            self.settings.max_user_tasks, self.settings.max_total_tasks = old_user, old_total

    def test_05_cascade_all_tickets_and_ancestor_cancellation_guard(self):
        root = self.parent()
        child = self.child(root)["childTask"]
        grand = self.child(child)["childTask"]
        self.store.request_cancel(root["id"])
        with self.assertRaises(PermissionError):
            self.service.authorize_child(SimpleNamespace(run_id=grand["run_id"], session_id=grand["id"], user_id="alice"))
        self.denied(403, self.service.create, "alice", child["id"], "sort", "literature", str(uuid4()))
        result = self.call(self.service.cascade_cancel, "alice", root["id"])
        expected = {root["id"], child["id"], grand["id"]}
        # The autonomous observer may already have delivered native cleanup
        # after the root's durable cancel intent. This call requests only work
        # still outstanding; final positive native/effect/group proof below
        # still covers every member of the original exact tree.
        self.assertLessEqual(set(result["requested"]), expected)
        group = self.wait_group(root["id"])
        self.assertTrue(group["allStopped"])
        self.assertTrue(all(entry["cancelRequested"] for entry in [group["parent"], *group["children"]]))
        self.assertTrue(all(entry["nativeStatus"] == "cancelled" for entry in [group["parent"], *group["children"]]))

    def test_06_completed_parent_waits_for_accepted_children(self):
        root = self.parent()
        child = self.child(root)["childTask"]
        detail = self.client.get("/api/factory/jobs/" + root["id"]).json()
        requirement = detail["job"]["questionDetail"]
        result = self.client.post(f'/api/factory/jobs/{root["id"]}/answer', json={"questionId": requirement["id"], "version": requirement["version"], "answer": "Synthetic sorting scope"})
        self.assertEqual(result.status_code, 200, result.text)
        self.wait_native(root["id"], {"completed"})
        charged = self.store.sql("SELECT tool_name FROM af_delegation_tool_calls WHERE task_id=:task", task=root["id"])
        self.assertEqual({row["tool_name"] for row in charged}, {"ask_scope", "literature_search"})
        self.assertFalse(self.service.delegation_scope("alice", root["id"])["allowed"])
        group = self.call(self.service.inspect_group, "alice", root["id"])
        self.assertEqual(application_group_status("completed", group), "waiting_children")
        self.assertFalse(group["allStopped"])
        self.service.authorize_child(SimpleNamespace(run_id=child["run_id"], session_id=child["id"], user_id="alice"))
        self.denied(409, self.service.create, "alice", root["id"], "sort", "literature", str(uuid4()))
        result = self.call(self.service.cascade_cancel, "alice", root["id"])
        self.assertNotIn(root["id"], result["requested"])
        self.wait_group(root["id"])

    def test_07_failed_parent_mandate_denies_protected_child(self):
        observer = self.state["lifecycle_observer"]
        # Isolate metadata/native disagreement before positive cleanup. The
        # actual autonomous observer is exercised explicitly in the second
        # phase and has independent production-wired acceptance coverage.
        self.call(observer.stop)
        try:
            root = self.parent()
            child = self.child(root)["childTask"]
            self.store.admission_failed(root["id"], "Known synthetic parent failure")
            with self.assertRaises(PermissionError):
                self.service.authorize_child(SimpleNamespace(run_id=child["run_id"], session_id=child["id"], user_id="alice"))
            before_tasks = self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"]
            before_links = self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_links")[0]["n"]
            before_artifacts = {identifier: self.store.artifacts(identifier) for identifier in (root["id"], child["id"])}
            before_effects = {identifier: self.store.effects(identifier) for identifier in (root["id"], child["id"])}
            with mock.patch.object(self.bridge, "submit") as submit:
                self.denied(409, self.service.create, "alice", child["id"], "sort", "literature", str(uuid4()))
                submit.assert_not_called()
            self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], before_tasks)
            self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_links")[0]["n"], before_links)
            # Metadata rejection cannot erase an actual acknowledged native
            # ticket or release held capacity before authoritative stop.
            self.store.admission_failed(child["id"], "Controlled metadata/ticket race fixture")
            self.assertFalse(self.store.task(root["id"])["terminal"])
            self.assertFalse(self.store.task(child["id"])["terminal"])
            group = self.call(self.service.inspect_group, "alice", root["id"])
            self.assertEqual(group["parent"]["nativeStatus"], "paused")
            self.assertFalse(group["parent"]["stopped"])
            self.assertFalse(group["children"][0]["stopped"])
            self.assertTrue(self.service.has_pending_children(root["id"]))
            # Rejected metadata still cannot authorize cancellation or stop
            # proof for a mismatched native owner. Only the exactly bound child
            # may settle; this parent ticket and its capacity remain held.
            original_native = self.store.native_db.get_job
            def mismatched_parent(identifier, *args, **kwargs):
                ticket = copy.deepcopy(original_native(identifier, *args, **kwargs))
                if identifier == root["run_id"]:
                    ticket["user_id"] = "bob"
                return ticket
            with mock.patch.object(self.store.native_db, "get_job", side_effect=mismatched_parent):
                held = self.call(observer.observe_root, root["id"])
                parent_fact = next(fact for fact in held["facts"] if fact["taskId"] == root["id"])
                self.assertTrue(parent_fact["unknown"])
                self.assertFalse(parent_fact["stopped"])
                self.assertFalse(held["allStopped"])
                self.assertFalse(self.store.task(root["id"], "alice")["terminal"])
                self.assertEqual(original_native(root["run_id"], strict=True)["status"], "paused")
            # Cleanup is now driven through the same trusted wired observer,
            # without owner detail polling or an execution grant change.
            observed = self.call(observer.observe_root, root["id"])
            self.assertEqual(observed["errors"], [], observed)
            stopped = self.wait_group(root["id"])
            self.assertTrue(stopped["allStopped"])
            self.assertTrue(stopped["parent"]["failed"])
            self.assertTrue(stopped["children"][0]["failed"])
            self.assertTrue(any(event["type"] == "lifecycle_cleanup_requested" and event["data"].get("reason") == "admission-rejected"
                                for event in self.store.events(root["id"])))
            for identifier in (root["id"], child["id"]):
                current = self.store.task(identifier, "alice")
                self.assertTrue(current["cancel_requested"])
                self.assertTrue(current["terminal"])
                self.assertEqual(self.store.native_db.get_job(current["run_id"], strict=True)["status"], "cancelled")
                self.assertEqual(self.store.artifacts(identifier), before_artifacts[identifier])
                self.assertEqual(self.store.effects(identifier), before_effects[identifier])
                self.assertTrue(self.store.failure_cleanup_requested(identifier))
                self.assertTrue(self.store.has_failures(identifier))
                self.assertEqual(current["body"]["lastStatus"], "failed")
            self.assertTrue(self.store.has_failures(child["id"]))
        finally:
            self.call(observer.start)

    def test_08_running_experiment_cascade_confirms_cleanup(self):
        root = self.parent("experiment")
        child = self.child(root, mode="experiment", goal="Evaluate synthetic candidate")["childTask"]
        detail = self.client.get("/api/factory/jobs/" + child["id"]).json()
        approval = detail["job"]["approvalDetail"]
        result = self.client.post(f'/api/factory/jobs/{child["id"]}/approve', json={"requirementId": approval["id"], "version": approval["version"], "approved": True})
        self.assertEqual(result.status_code, 200, result.text)
        self.wait_native(child["id"], {"running"})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not any(event["type"] == "compute_started" for event in self.store.events(child["id"])):
            time.sleep(.03)
        self.assertTrue(any(event["type"] == "compute_started" for event in self.store.events(child["id"])))
        group = self.call(self.service.inspect_group, "alice", root["id"])
        self.assertFalse(group["unknown"], group)
        self.assertFalse(group["allStopped"])
        running = next(entry for entry in group["children"] if entry["taskId"] == child["id"])
        self.assertEqual(running["nativeStatus"], "running")
        self.assertFalse(running["unknown"])
        self.assertEqual(application_group_status("running", group), "running")
        self.call(self.service.cascade_cancel, "alice", root["id"])
        group = self.wait_group(root["id"])
        child_facts = next(entry for entry in group["children"] if entry["taskId"] == child["id"])
        self.assertEqual(child_facts["nativeStatus"], "cancelled")
        self.assertFalse(child_facts["unknown"])
        self.assertTrue(any(effect["status"] == "CANCELLED" and effect["result"]["cleanupComplete"] for effect in child_facts["effects"]))
        stopped = [event for event in self.store.events(child["id"]) if event["type"] == "compute_stopped"]
        self.assertTrue(stopped)

    def test_09_shared_tool_budget_durable_duplicate_and_exhaustion(self):
        old = self.settings.max_tool_calls
        self.settings.max_tool_calls = 2
        try:
            root = self.parent()
            root_ctx = SimpleNamespace(run_id=root["run_id"], session_id=root["id"], user_id="alice")
            self.assertTrue(self.service.consume_tool_budget(root_ctx, "fixture-root-call", "ask_scope")["charged"])
            child = self.child(root)["childTask"]
            child_ctx = SimpleNamespace(run_id=child["run_id"], session_id=child["id"], user_id="alice")
            self.assertTrue(self.service.consume_tool_budget(child_ctx, "fixture-child-call", "ask_scope")["charged"])
            recovered = DelegationService(self.settings, self.store, self.auth, self.bridge)
            recovered.initialize()
            self.assertFalse(recovered.consume_tool_budget(root_ctx, "fixture-root-call", "ask_scope")["charged"])
            scope = recovered.delegation_scope("alice", root["id"])
            self.assertFalse(scope["allowed"])
            self.assertEqual(scope["sharedBudget"]["toolCallsUsed"], 2)
            self.denied(429, self.service.create, "alice", root["id"], "sort", "literature", str(uuid4()))
            with self.assertRaises(PermissionError):
                recovered.consume_tool_budget(child_ctx, "fixture-third-call", "literature_search")
            with self.assertRaises(PermissionError):
                recovered.consume_tool_budget(root_ctx, "fixture-root-call", "literature_search")
            self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE root_id=:root", root=root["id"])[0]["n"], 2)
        finally:
            self.settings.max_tool_calls = old

    def test_10_native_worker_enforces_shared_execution_budget(self):
        old = self.settings.max_tool_calls
        self.settings.max_tool_calls = 2
        try:
            root = self.parent()
            child = self.child(root, goal="Compare synthetic candidates")["childTask"]
            self.wait_native(child["id"], {"completed"})
            detail = self.client.get("/api/factory/jobs/" + root["id"]).json()
            question = detail["job"]["questionDetail"]
            result = self.client.post(f'/api/factory/jobs/{root["id"]}/answer', json={"questionId": question["id"], "version": question["version"], "answer": "Synthetic sorting scope"})
            self.assertEqual(result.status_code, 200, result.text)
            self.wait_native(root["id"], {"completed", "failed"})
            detail = self.client.get("/api/factory/jobs/" + root["id"]).json()
            self.assertEqual(detail["job"]["status"], "failed", detail)
            self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE root_id=:root", root=root["id"])[0]["n"], 2)
            self.assertTrue(any(event["type"] == "protected_denied" for event in self.store.events(root["id"])))
            self.assertFalse(self.store.artifacts(root["id"]), "Shared limit must stop the unbudgeted literature tool")
        finally:
            self.settings.max_tool_calls = old

    def test_11_concurrent_duplicate_has_one_native_ticket(self):
        root = self.parent()
        request = str(uuid4())
        def submit():
            return self.call(self.service.create, "alice", root["id"], "sort", "literature", request)
        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = list(workers.map(lambda _: submit(), range(2)))
        self.assertEqual(first["childTask"]["id"], second["childTask"]["id"])
        child = self.store.task(first["childTask"]["id"])
        self.wait_native(child["id"], {"paused"})
        receipt = self.call(self.bridge.find_run, child["id"], "alice")
        self.assertEqual(receipt["run_id"], self.store.task(child["id"])["run_id"])
        self.assertEqual(len(self.call(self.service.children, "alice", root["id"])), 1)

    def test_12_uncertain_admission_and_unknown_effect_do_not_replay_or_release(self):
        root = self.parent()
        request = str(uuid4())
        original = self.bridge.submit
        calls = []
        async def unacknowledged(plan, owner, key):
            calls.append(key)
            raise HTTPException(503, "Controlled unknown transport outcome")
        self.bridge.submit = unacknowledged
        try:
            first = self.child(root, request=request)
            second = self.child(root, request=request)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["childTask"]["id"], second["childTask"]["id"])
            self.assertIsNone(second["receipt"])
            self.assertEqual(second["childTask"]["admission"], "unknown")
            group = self.call(self.service.inspect_group, "alice", root["id"])
            self.assertTrue(group["unknown"])
            self.assertFalse(group["allStopped"])
            self.assertFalse(second["childTask"]["terminal"])
            self.assertTrue(self.service.has_pending_children(root["id"]))
            self.store.effect_reserve(root["run_id"], "uncertain-fixture", {"fixture": True})
            self.call(self.service.cascade_cancel, "alice", root["id"])
            self.wait_group(root["id"], unknown=True)
            self.roots.remove(root["id"])  # Intentionally retained UNKNOWN in disposable DB.
        finally:
            self.bridge.submit = original
        # Real ledger UNKNOWN keeps a terminal native parent from being stopped.
        group = self.call(self.service.inspect_group, "alice", root["id"])
        self.assertTrue(group["unknown"])
        self.assertFalse(group["allStopped"])

    def test_13_native_approved_experiment_current_authority_policy_and_unknown_stop_before_process(self):
        for scenario in ("revoked", "policy-unset", "unknown"):
            with self.subTest(scenario=scenario):
                response = self.client.post("/api/factory/plans", json={"topic": "Evaluate synthetic candidate", "mode": "experiment", "requestId": str(uuid4())})
                self.assertEqual(response.status_code, 201, response.text)
                response = self.client.post("/api/factory/instances", json={"planId": response.json()["id"], "requestId": str(uuid4())})
                self.assertEqual(response.status_code, 202, response.text)
                task = self.store.task(response.json()["id"])
                self.roots.append(task["id"])
                self.wait_native(task["id"], {"paused"})
                snapshot = self.call(self.bridge.detail, task["run_id"], task["id"], "alice")
                requirements = copy.deepcopy(snapshot.get("requirements") or snapshot.get("run", {}).get("requirements"))
                self.assertEqual(len(requirements), 1)
                self.assertEqual(requirements[0]["tool_execution"]["tool_name"], "run_experiment")
                requirements[0]["confirmation"] = True
                requirements[0]["tool_execution"]["confirmed"] = True
                artifacts_before = copy.deepcopy(self.store.artifacts(task["id"]))
                if scenario == "unknown":
                    self.store.effect_reserve(task["run_id"], "experiment:bounded-sort-v1", {"experiment": "bounded-sort-v1", "datasetHash": DATASET_HASH, "evaluatorVersion": "1"})
                effects_before = copy.deepcopy(self.store.effects(task["id"]))
                original = self.store.authorize_tool
                changed = []
                def change_at_protected_boundary(ctx, name):
                    if name == "run_experiment" and not changed:
                        changed.append(name)
                        if scenario == "revoked":
                            self.auth.authorization.unassign("alice", "factory-user")
                        elif scenario == "policy-unset":
                            self.settings.temporary_policy = "unset"
                    return original(ctx, name)
                with mock.patch("agent_factory.tools.subprocess.Popen", side_effect=AssertionError("Denied native experiment attempted compute")) as start_process:
                    try:
                        with mock.patch.object(self.store, "authorize_tool", side_effect=change_at_protected_boundary):
                            self.call(self.bridge.continue_run, task["run_id"], task["id"], "alice", requirements)
                            self.wait_native(task["id"], {"completed", "failed"})
                        self.assertEqual(changed, ["run_experiment"])
                        self.assertEqual(self.store.effects(task["id"]), effects_before)
                        self.assertEqual(self.store.artifacts(task["id"]), artifacts_before)
                        registered = next(tool for tool in self.registry.tools if tool.name == "run_experiment")
                        ctx = RunContext(run_id=task["run_id"], session_id=task["id"], user_id="alice", session_state={})
                        async def direct_entrypoint():
                            return await registered.entrypoint(run_context=ctx, experiment="bounded-sort-v1")
                        with self.assertRaises((HTTPException, PermissionError, RuntimeError, RunCancelledException)):
                            self.call(direct_entrypoint)
                        start_process.assert_not_called()
                        self.assertEqual(self.store.effects(task["id"]), effects_before)
                        self.assertEqual(self.store.artifacts(task["id"]), artifacts_before)
                        self.assertFalse(any(event["type"] == "compute_started" for event in self.store.events(task["id"])))
                    finally:
                        self.auth.authorization.assign("alice", "factory-user")
                        self.settings.temporary_policy = "bounded-synthetic"
                response = self.client.get("/api/factory/jobs/" + task["id"])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["job"]["status"], "unknown" if scenario == "unknown" else "failed")
                if scenario == "unknown":
                    self.roots.remove(task["id"])  # Deliberately unresolved in isolated fixture.


if __name__ == "__main__":
    unittest.main()

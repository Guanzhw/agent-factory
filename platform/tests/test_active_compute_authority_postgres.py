"""Live PostgreSQL/native-queue tests for authority loss during bounded compute.

Requires FACTORY_TEST_DATABASE_URL pointing to an authorized disposable
loopback PostgreSQL server. The only model is the in-process deterministic
DemoModel, and the only subprocess is the repository's allowlisted synthetic
sort fixture. No HTTP cancellation is used after authorization is revoked.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

PLATFORM = Path(__file__).resolve().parents[1]
TESTS = PLATFORM / "tests"
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from fastapi.testclient import TestClient
from agno.db.base import SessionType
from pg_fixture import IsolatedPostgres
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.plan_policy import PlanPolicyConfig


def process_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        return not stat.exists() or stat.read_text().split(") ", 1)[1].split()[0] != "Z"
    except ProcessLookupError:
        return False


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class ActiveComputeAuthorityPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.workspace = tempfile.TemporaryDirectory(prefix="factory-authority-loss-")
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.workspace.name),
                                 max_workers=1, queue_poll=.03, experiment_timeout_seconds=8)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app).__enter__()
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.client.post("/api/factory/demo/login", json={"persona": "alice"})
        self.task_id = None

    def tearDown(self):
        if self.task_id:
            try:
                task = self.store.task(self.task_id)
                if not task["terminal"]:
                    self.store.request_cancel(self.task_id)
                    self._wait_for_event(self.task_id, "compute_stopped", timeout=5, required=False)
            except Exception:
                pass
        self.client.__exit__(None, None, None)
        self.store.engine.dispose()
        self.store.native_db.db_engine.dispose()
        self.workspace.cleanup()
        self.database.__exit__(None, None, None)

    def _wait_for_event(self, task_id, event_type, *, timeout=8, required=True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = [event for event in self.store.events(task_id) if event["type"] == event_type]
            if matches:
                return matches[-1]
            time.sleep(.02)
        if required:
            self.fail(f"Native queue did not record {event_type}")
        return None

    def _start_confirmed_compute(self):
        plan_response = self.client.post("/api/factory/plans", json={
            "topic": "Bounded synthetic authority-loss integration fixture",
            "mode": "experiment", "application": "research", "requestId": str(uuid4())})
        self.assertEqual(plan_response.status_code, 201, plan_response.text)
        plan = plan_response.json()
        self.assertEqual(plan["status"], "ready", plan)
        submit = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": str(uuid4())})
        self.assertEqual(submit.status_code, 202, submit.text)
        self.task_id = submit.json()["id"]
        deadline = time.monotonic() + 15
        detail = None
        while time.monotonic() < deadline:
            detail = self.client.get(f"/api/factory/jobs/{self.task_id}").json()
            if detail["job"]["status"] == "waiting_approval":
                break
            if detail["job"]["status"] in {"failed", "canceled", "completed", "unknown"}:
                self.fail(f"Native fixture did not reach HITL approval: {detail}")
            time.sleep(.03)
        else:
            self.fail(f"Native queue did not reach HITL approval: {detail}")
        approval = detail["job"]["approvalDetail"]
        approved = self.client.post(f"/api/factory/jobs/{self.task_id}/approve", json={
            "requirementId": approval["id"], "version": approval["version"], "approved": True})
        self.assertEqual(approved.status_code, 200, approved.text)
        started = self._wait_for_event(self.task_id, "compute_started", timeout=12)
        pid = int(started["data"]["pid"])
        self.assertTrue(process_running(pid), "compute_started must refer to a live owned fixture process")
        return plan, pid

    def _assert_authority_loss_cleans_compute(self, revoke):
        plan, pid = self._start_confirmed_compute()
        effects_before = self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE task_id=:id", id=self.task_id)[0]["n"]
        artifacts_before = self.store.artifacts(self.task_id)
        lost_at = time.monotonic()
        revoke(plan)
        stopped = self._wait_for_event(self.task_id, "compute_stopped", timeout=3)
        elapsed = time.monotonic() - lost_at
        self.assertLessEqual(elapsed, 2.5, f"compute cleanup exceeded authority-loss bound: {elapsed:.3f}s")
        self.assertEqual(stopped["data"]["pid"], pid)
        self.assertTrue(stopped["data"]["cleanupComplete"], stopped)
        self.assertFalse(process_running(pid), "task-owned subprocess must be gone after compute_stopped")
        events = self.store.events(self.task_id)
        self.assertTrue(any(event["type"] == "protected_denied" for event in events), events)
        self.assertFalse(any(event["type"] == "experiment_completed" for event in events), events)
        self.assertEqual(self.store.artifacts(self.task_id), artifacts_before,
                         "authority loss after compute start must not publish experiment output")
        self.assertFalse(any(item["name"] == "synthetic-experiment.json" for item in self.store.artifacts(self.task_id)))
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE task_id=:id", id=self.task_id)[0]["n"], effects_before,
                         "periodic authority checks must not charge native tool-call budget again")
        # compute_stopped is the subprocess-thread acknowledgement; the async
        # tool commits its durable effect only afterwards. Wait for that exact
        # settlement event, retaining all strict CANCELLED/result assertions.
        self._wait_for_event(self.task_id, "compute_cancelled", timeout=3)
        effects = self.store.effects(self.task_id)
        self.assertEqual(len(effects), 1, effects)
        self.assertEqual(effects[0]["status"], "CANCELLED", effects)
        self.assertTrue(effects[0]["result"]["cancelled"], effects)
        self.assertTrue(effects[0]["result"]["cleanupComplete"], effects)
        task = self.store.task(self.task_id)
        native_job = self.store.native_db.get_job(task["run_id"], strict=True)
        self.assertIsNotNone(native_job, "native durable queue must retain the exact run ticket")
        # Tool cleanup can precede the native runner's durable run-state update.
        # Give the actual session a short bounded settle period, while retaining
        # the strict terminal-state assertion below.
        native_session = None
        native_runs = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            native_session = self.store.native_db.get_session(
                self.task_id, session_type=SessionType.AGENT, user_id="alice")
            self.assertIsNotNone(native_session, "native persisted session must remain owner-scoped and readable in the fixture")
            native_runs = [run for run in (native_session.runs or []) if run.run_id == task["run_id"]]
            if native_runs:
                status = getattr(native_runs[0].status, "value", native_runs[0].status)
                if str(status).casefold() in {"cancelled", "failed", "completed"}:
                    break
            time.sleep(.05)
        self.assertEqual(len(native_runs), 1, native_runs)
        native_status = getattr(native_runs[0].status, "value", native_runs[0].status)
        self.assertEqual(str(native_status).casefold(), "cancelled", {"runStatus": native_status, "queueStatus": native_job.get("status")})

    def test_current_sql_role_revocation_stops_owned_compute(self):
        def revoke(_plan):
            self.auth.authorization.unassign("alice", "factory-user")
        try:
            self._assert_authority_loss_cleans_compute(revoke)
        finally:
            self.auth.authorization.assign("alice", "factory-user")

    def test_persisted_plan_policy_unset_stops_owned_compute(self):
        policy = self.state["plan_policy"]
        original = policy.current()
        def revoke(_plan):
            policy.replace_configuration(
                PlanPolicyConfig(name="unset", revision="authority-loss-unset-" + uuid4().hex),
                expected_revision=original["revision"])
        self._assert_authority_loss_cleans_compute(revoke)

    def test_governing_material_withdrawal_stops_owned_compute(self):
        governance = self.state["material_governance"]
        self.auth.authorization.assign("manager", "factory-manager")
        def revoke(plan):
            binding = next(ref for ref in plan["materialRefs"] if ref["id"] == "experiment-tool")
            result = governance.withdraw("manager", binding["id"], binding["version"],
                                         "authority-loss-withdraw-" + uuid4().hex,
                                         reason="isolated runtime authority-loss acceptance fixture")
            self.assertEqual(result["state"], "withdrawn", result)
        self._assert_authority_loss_cleans_compute(revoke)


if __name__ == "__main__":
    unittest.main(verbosity=2)

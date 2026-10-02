"""Actual guarded scheduler/process restart and native lease acceptance.

Models are synthetic; Factory HTTP, immutable metadata, native schedule history,
native queue and PostgreSQL are real. Faults delay replies at recorded boundaries
before an owned process hard kill. No lease rows are manually reset or cleared.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.db.schemas.scheduler import Schedule
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine, text

from pg_fixture import IsolatedPostgres
from agent_factory.catalog import create_plan
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.plan_policy import PlanPolicyConfig


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class SchedulingProcessRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.engine = create_engine(cls.database.url)
        cls.addClassCleanup(cls.engine.dispose)
        cls.db = PostgresDb(db_url=cls.database.url, id="factory-native-postgres")
        cls.addClassCleanup(cls.db.db_engine.dispose)
        cls.root = Path(__file__).resolve().parents[2]
        cls.control = Path(cls.directory.name) / "fault-control.json"
        cls.marker = Path(cls.directory.name) / "fault-boundary.json"
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            cls.port = available.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH", "LANG", "LC_ALL") if name in os.environ}
        cls.env.update(PYTHONPATH=os.pathsep.join((str(cls.root / "platform"), str(cls.root / "platform/tests"))),
                       PYTHONIOENCODING="utf-8", FACTORY_DATABASE_URL=cls.database.url, FACTORY_MODE="demo",
                       FACTORY_JWT_KEY=secrets.token_urlsafe(48), FACTORY_PORT=str(cls.port),
                       FACTORY_WORKSPACE=cls.directory.name, FACTORY_RECOVERY_FIXTURE_DIRECTORY=cls.directory.name,
                       AGNO_TELEMETRY="false")
        cls.process, cls.log = None, None
        cls.addClassCleanup(cls.stop)

    @classmethod
    def start(cls, phase=None, queue_poll=.2, schedule_poll=60):
        cls.control.write_text(json.dumps({"phase": phase}), encoding="utf-8")
        cls.env["FACTORY_RECOVERY_QUEUE_POLL"] = str(queue_poll)
        cls.env["FACTORY_RECOVERY_SCHEDULE_POLL"] = str(schedule_poll)
        cls.log = open(Path(cls.directory.name) / "owned-scheduling-api.log", "ab")
        cls.process = subprocess.Popen([sys.executable, "-m", "scheduling_recovery_worker"], cwd=cls.root,
            env=cls.env, stdout=cls.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        deadline = time.monotonic() + 25
        with httpx.Client(timeout=1, trust_env=False) as probe:
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    cls.log.flush()
                    raise RuntimeError("Owned scheduling API startup failed: " + (Path(cls.directory.name) / "owned-scheduling-api.log").read_text(encoding="utf-8", errors="replace")[-5000:])
                try:
                    if probe.get(cls.base + "/api/factory/status").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(.05)
        raise TimeoutError("Owned scheduling API did not start")

    @classmethod
    def stop(cls):
        process = cls.process
        if process is not None and process.poll() is None:
            # Exact owned Popen launcher tree only. Never locate/kill a port owner.
            if os.name == "nt":
                subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        cls.process = None
        if cls.log is not None:
            cls.log.close()
            cls.log = None

    def setUp(self):
        self.ids = []
        self.client = httpx.Client(base_url=self.base, timeout=15, trust_env=False)
        self.addCleanup(self.client.close)

    def tearDown(self):
        fault_active = json.loads(self.control.read_text(encoding="utf-8")).get("phase") if self.control.exists() else None
        if not fault_active and self.process is not None and self.process.poll() is None:
            for schedule_id in self.ids:
                self.client.post(f"/api/factory/schedules/{schedule_id}/enabled", json={"enabled": False})
                for occurrence in self.client.get(f"/api/factory/schedules/{schedule_id}/occurrences").json():
                    if occurrence["task_id"] and occurrence.get("task", {}).get("run_id"):
                        self.client.post(f"/api/factory/schedules/{schedule_id}/occurrences/{occurrence['id']}/cancel")
        self.stop()
        if self.marker.exists():
            self.marker.unlink()

    def login(self):
        self.client.post("/api/factory/demo/login", json={"persona": "manager"}).raise_for_status()

    def rows(self, statement, **params):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(text(statement), params).mappings()]

    def schedule(self):
        plan = self.client.post("/api/factory/plans", json={"topic": "scope", "mode": "literature", "requestId": str(uuid4())})
        plan.raise_for_status()
        result = self.client.post("/api/factory/schedules", json={"planId": plan.json()["id"], "name": "process-schedule-" + str(uuid4()), "cron": "0 0 1 1 *"})
        result.raise_for_status()
        self.ids.append(result.json()["id"])
        return result.json()

    def wait_marker(self, phase):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                body = json.loads(self.marker.read_text(encoding="utf-8"))
                if body["phase"] == phase:
                    return body
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            time.sleep(.03)
        self.fail("Owned process did not reach recorded " + phase)

    def interrupted(self, phase):
        self.start(phase, queue_poll=30 if phase == "after-native" else .2)
        self.login()
        schedule, key = self.schedule(), str(uuid4())
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(self.client.post, f"/api/factory/schedules/{schedule['id']}/trigger", json={"requestId": key})
            marker = self.wait_marker(phase)
            before = self.rows("SELECT * FROM af_schedule_occurrences WHERE schedule_id=:id", id=schedule["id"])
            self.assertEqual(len(before), 1)
            self.assertEqual(before[0]["status"], "reserving")
            self.stop()
            try:
                pending.result(timeout=5)
            except httpx.HTTPError:
                pass
        self.start()
        self.login()
        receipt = self.client.get(f"/api/factory/schedules/{schedule['id']}/occurrences")
        receipt.raise_for_status()
        self.assertEqual(len(receipt.json()), 1)
        after = receipt.json()[0]
        self.assertEqual(after["id"], before[0]["id"])
        self.assertEqual(after["request_id"], before[0]["request_id"])
        return schedule, key, marker, before[0], after

    def test_01_actual_hardkill_after_native_commit_recovers_exact_ticket(self):
        schedule, key, marker, before, after = self.interrupted("after-native")
        self.assertEqual(after["status"], "accepted")
        self.assertEqual(after["task_id"], marker["taskId"])
        self.assertEqual(after["task"]["run_id"], marker["runId"])
        duplicate = self.client.post(f"/api/factory/schedules/{schedule['id']}/trigger", json={"requestId": key})
        duplicate.raise_for_status()
        self.assertEqual(duplicate.json()["id"], after["id"])
        self.assertEqual(self.db.get_schedule_run(after["id"], user_id="manager")["run_id"], marker["runId"])
        jobs = self.rows("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=marker["taskId"])
        self.assertEqual(jobs[0]["n"], 1)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            ticket = self.db.get_job(marker["runId"])
            if ticket and ticket["status"] == "paused":
                break
            time.sleep(.05)
        self.assertEqual(ticket["status"], "paused", "Restarted native worker must execute the original ticket and persist its real scope question")
        detail = self.client.get(f"/api/factory/jobs/{marker['taskId']}")
        detail.raise_for_status()
        self.assertEqual(detail.json()["job"]["status"], "waiting_input")
        self.assertTrue(detail.json()["job"]["questionDetail"]["id"])

    def test_02_actual_hardkill_before_native_never_resubmits_unknown(self):
        schedule, key, marker, before, after = self.interrupted("before-native")
        self.assertEqual(after["status"], "unknown")
        self.assertEqual(after["task_id"], marker["taskId"])
        self.assertIsNone(after["task"]["run_id"])
        self.assertFalse(after["task"]["terminal"])
        duplicate = self.client.post(f"/api/factory/schedules/{schedule['id']}/trigger", json={"requestId": key})
        duplicate.raise_for_status()
        self.assertEqual(duplicate.json()["task_id"], marker["taskId"])
        self.assertEqual(duplicate.json()["status"], "unknown")
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=marker["taskId"])[0]["n"], 0)
        for _ in range(2):
            duplicate = self.client.post(f"/api/factory/schedules/{schedule['id']}/trigger", json={"requestId": key})
            duplicate.raise_for_status()
            self.assertEqual(duplicate.json()["id"], after["id"])
            self.assertEqual(duplicate.json()["status"], "unknown")
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=marker["taskId"])[0]["n"], 0)
        self.assertEqual(self.db.get_schedule_run(after["id"], user_id="manager")["status"], "unknown")

    def test_03_actual_hardkill_between_task_commit_and_occurrence_link_recovers_binding(self):
        schedule, key, marker, before, after = self.interrupted("before-task-binding")
        self.assertIsNone(before["task_id"])
        self.assertEqual(after["status"], "unknown")
        self.assertEqual(after["task_id"], marker["taskId"], "Startup must recover exact owner/request reservation without submission")
        self.assertIsNone(after["task"]["run_id"])
        self.assertFalse(after["task"]["terminal"])
        duplicate = self.client.post(f"/api/factory/schedules/{schedule['id']}/trigger", json={"requestId": key})
        duplicate.raise_for_status()
        self.assertEqual(duplicate.json()["task_id"], marker["taskId"])
        self.assertEqual(duplicate.json()["status"], "unknown")
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=marker["taskId"])[0]["n"], 0)

    def test_09_native_poller_due_occurrence_hardkill_recovers_receipt_without_clearing_lease(self):
        self.start("after-native", queue_poll=30, schedule_poll=.2)
        self.login()
        schedule = self.schedule()
        # An operator sets only the due time through native's PUBLIC API.
        # Actual SchedulePoller owns the claim and invokes guarded admission.
        due_at = int(time.time()) - 1
        self.db.update_schedule(schedule["id"], user_id="manager", next_run_at=due_at)
        marker = self.wait_marker("after-native")
        before = self.rows("SELECT * FROM af_schedule_occurrences WHERE schedule_id=:id", id=schedule["id"])
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["occurrence_key"], "due:" + str(due_at))
        self.assertEqual(before[0]["status"], "reserving")
        claimed = self.db.get_schedule(schedule["id"])
        self.assertTrue(claimed["locked_by"])
        self.assertIsNotNone(claimed["locked_at"])
        self.stop()
        self.start(schedule_poll=.2)
        self.login()
        response = self.client.get(f"/api/factory/schedules/{schedule['id']}/occurrences")
        response.raise_for_status()
        after = response.json()
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["id"], before[0]["id"])
        self.assertEqual(after[0]["request_id"], before[0]["request_id"])
        self.assertEqual(after[0]["status"], "accepted")
        self.assertEqual(after[0]["task_id"], marker["taskId"])
        self.assertEqual(after[0]["task"]["run_id"], marker["runId"])
        # Factory's startup receipt observer does not mutate native leases.
        # The pinned native poller keeps its default 300-second stale grace;
        # this bounded test does not claim to have waited those five minutes.
        retained = self.db.get_schedule(schedule["id"])
        self.assertEqual(retained["locked_by"], claimed["locked_by"])
        self.assertEqual(retained["locked_at"], claimed["locked_at"])
        self.assertEqual(retained["next_run_at"], due_at)
        self.assertIsNone(self.db.claim_due_schedule("fixture-default-grace-probe"))
        deadline = time.monotonic() + 15
        ticket = None
        while time.monotonic() < deadline:
            ticket = self.db.get_job(marker["runId"])
            if ticket and ticket["status"] == "paused":
                break
            time.sleep(.05)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket["status"], "paused")
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=marker["taskId"])[0]["n"], 1)
        self.assertEqual(self.db.get_schedule_run(after[0]["id"], user_id="manager")["run_id"], marker["runId"])


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class SchedulingLeaseRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.settings = Settings(db_url=cls.database.url, workspace=Path(cls.directory.name), max_workers=1, max_user_tasks=8)
        cls.settings.schedule_poll_seconds = 60
        cls.app = create_app(cls.settings)
        cls.state = cls.app.app.state.factory
        cls.store, cls.auth, cls.db, cls.service = cls.state["store"], cls.state["auth"], cls.state["store"].native_db, cls.state["schedules"]
        cls.addClassCleanup(cls.store.engine.dispose)
        cls.addClassCleanup(cls.db.db_engine.dispose)
        cls.client = TestClient(cls.app).__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)
        # Native last-admin revocation safeguards remain enabled. This extra
        # synthetic principal exists solely inside this generated test DB.
        cls.backup_admin = "synthetic-recovery-admin-" + uuid4().hex
        cls.auth.directory.upsert(cls.backup_admin, name="Synthetic recovery fixture operator")
        cls.auth.authorization.assign(cls.backup_admin, "factory-manager")

    def setUp(self):
        self.ids = []

    def tearDown(self):
        self.auth.authorization.assign("manager", "factory-manager")
        self.auth.directory.set_disabled("manager", False)
        for identifier in self.ids:
            self.service.set_enabled("manager", identifier, False)
            for row in self.service.occurrences("manager", identifier):
                if row["task_id"]:
                    self.call(self.service.cancel_occurrence, "manager", identifier, row["id"])

    def call(self, function, *args):
        return self.client.portal.call(function, *args)

    def schedule(self):
        plan = create_plan(self.store, "manager", "scope", "literature")
        result = self.service.create("manager", plan["id"], "lease-schedule-" + str(uuid4()), "0 0 1 1 *")
        self.ids.append(result["id"])
        return result

    def due(self, schedule):
        # Public native operator update of a generated fixture's due time.
        # No lock fields are changed or cleared by the test.
        self.service.manager.update(schedule["id"], user_id="manager", next_run_at=int(time.time()) - 1)

    def test_04_same_manual_occurrence_concurrent_callers_admit_one_ticket(self):
        schedule, key = self.schedule(), str(uuid4())
        async def contend():
            return await asyncio.gather(self.service.trigger("manager", schedule["id"], key),
                                        self.service.trigger("manager", schedule["id"], key), return_exceptions=True)
        results = self.call(contend)
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertTrue(receipts)
        self.assertTrue(all(isinstance(result, dict) or isinstance(result, HTTPException) and result.status_code == 409 for result in results))
        repeated = self.call(self.service.trigger, "manager", schedule["id"], key)
        self.assertEqual({row["id"] for row in receipts}, {repeated["id"]})
        native = self.service.occurrences("manager", schedule["id"])
        self.assertEqual(len(native), 1)
        self.assertEqual(native[0]["status"], "accepted")
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=native[0]["task_id"])[0]["n"], 1)

    def test_05_native_concurrent_claimants_and_stale_lease_fencing(self):
        schedule = self.schedule()
        self.due(schedule)
        with ThreadPoolExecutor(max_workers=2) as workers:
            claims = list(workers.map(lambda worker: self.db.claim_due_schedule(worker), ("fixture-worker-a", "fixture-worker-b")))
        admitted = [row for row in claims if row]
        self.assertEqual(len(admitted), 1)
        first = Schedule.from_dict(admitted[0])
        self.assertIsNone(self.db.claim_due_schedule("fixture-fresh-grace"))
        successor = self.db.claim_due_schedule("fixture-successor", lock_grace_seconds=0)
        self.assertIsNotNone(successor)
        self.assertEqual(successor["id"], first.id)
        self.assertNotEqual(successor["locked_by"], first.locked_by)
        with self.assertRaises(HTTPException) as stale:
            self.call(self.service.execute, first, self.db)
        self.assertEqual(stale.exception.status_code, 409, "A stale native lease cannot admit before the successor")
        current = self.db.get_schedule(first.id)
        self.assertEqual(current["locked_by"], successor["locked_by"])
        self.assertEqual(current["locked_at"], successor["locked_at"])
        result = self.call(self.service.execute, Schedule.from_dict(successor), self.db)
        self.assertEqual(result["status"], "accepted")
        self.assertIsNone(self.db.get_schedule(first.id)["locked_by"])
        self.assertGreater(self.db.get_schedule(first.id)["next_run_at"], successor["next_run_at"])

    def test_06_canceled_revoked_owner_and_current_policies_block_due_effects(self):
        for reason in ("disabled-schedule", "disabled-owner", "revoked-owner-role", "policy-unset", "policy-review-required"):
            with self.subTest(reason=reason):
                schedule = self.schedule()
                self.due(schedule)
                claim = self.db.claim_due_schedule("fixture-denied-" + reason)
                self.assertIsNotNone(claim)
                policy = self.store.plan_policy
                original = policy.current()
                if reason == "disabled-schedule":
                    self.service.set_enabled("manager", schedule["id"], False)
                elif reason == "disabled-owner":
                    self.auth.directory.set_disabled("manager", True)
                elif reason == "revoked-owner-role":
                    self.auth.authorization.unassign("manager", "factory-manager")
                else:
                    policy.replace_configuration(PlanPolicyConfig(name="unset" if reason == "policy-unset" else "admin-review", revision="fixture-policy-" + uuid4().hex), expected_revision=original["revision"])
                before = self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"]
                try:
                    with self.assertRaises(HTTPException) as denied:
                        self.call(self.service.execute, Schedule.from_dict(claim), self.db)
                    self.assertIn(denied.exception.status_code, {403, 409})
                    self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], before)
                    self.assertEqual(self.store.sql("SELECT * FROM af_schedule_occurrences WHERE schedule_id=:id", id=schedule["id"]), [])
                finally:
                    self.auth.authorization.assign("manager", "factory-manager")
                    self.auth.directory.set_disabled("manager", False)
                    if reason.startswith("policy-"):
                        policy.replace_configuration(PlanPolicyConfig(name=original["name"], revision=original["revision"], review_ttl_seconds=original["review_ttl_seconds"]), expected_revision=policy.current()["revision"])

    def test_07_native_unconditional_release_race_is_visible_without_duplicate_admission(self):
        """Evidence of a pinned native limitation, not atomic lease ownership.

        A successor uses the PUBLIC native short-grace claim between Factory's
        final snapshot check and native release. Native 3.1.0 release is by ID,
        without expected lease fields. The receipt fence still admits once.
        """
        schedule = self.schedule()
        self.due(schedule)
        first = self.db.claim_due_schedule("fixture-release-first")
        self.assertIsNotNone(first)
        original_release = self.db.release_schedule
        successors = []

        def takeover_then_native_release(identifier, next_run_at=None):
            successors.append(self.db.claim_due_schedule("fixture-release-successor", lock_grace_seconds=0))
            return original_release(identifier, next_run_at=next_run_at)

        self.db.release_schedule = takeover_then_native_release
        try:
            result = self.call(self.service.execute, Schedule.from_dict(first), self.db)
        finally:
            self.db.release_schedule = original_release
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(successors), 1)
        self.assertIsNotNone(successors[0])
        self.assertEqual(successors[0]["id"], first["id"])
        self.assertEqual(successors[0]["locked_by"], "fixture-release-successor")
        current = self.db.get_schedule(first["id"])
        self.assertIsNone(current["locked_by"], "Pinned native release demonstrably clears a successor lease after the Factory snapshot check")
        self.assertGreater(current["next_run_at"], first["next_run_at"])
        with self.assertRaises(HTTPException) as stale:
            self.call(self.service.execute, Schedule.from_dict(successors[0]), self.db)
        self.assertEqual(stale.exception.status_code, 409)
        occurrences = self.service.occurrences("manager", first["id"])
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["id"], result["id"])
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=result["task_id"])[0]["n"], 1)

    def test_08_successor_takeover_after_reservation_denies_before_native_submission(self):
        schedule = self.schedule()
        self.due(schedule)
        first = self.db.claim_due_schedule("fixture-before-submit-first")
        self.assertIsNotNone(first)
        original_reserve = self.store.reserve_task
        successors = []

        def reserve_then_successor(plan, request_id):
            reservation = original_reserve(plan, request_id)
            successors.append(self.db.claim_due_schedule("fixture-before-submit-successor", lock_grace_seconds=0))
            return reservation

        self.store.reserve_task = reserve_then_successor
        try:
            result = self.call(self.service.execute, Schedule.from_dict(first), self.db)
        finally:
            self.store.reserve_task = original_reserve
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(len(successors), 1)
        self.assertIsNotNone(successors[0])
        self.assertEqual(self.db.get_schedule(first["id"])["locked_by"], successors[0]["locked_by"])
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=result["task_id"])[0]["n"], 0)
        # A later claimant reads the persisted rejected receipt, never blindly
        # resubmits an occurrence whose admission path has already finished.
        repeat = self.call(self.service.execute, Schedule.from_dict(successors[0]), self.db)
        self.assertEqual(repeat["id"], result["id"])
        self.assertEqual(repeat["status"], "rejected")
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM ai.agno_jobs WHERE session_id=:id", id=result["task_id"])[0]["n"], 0)


if __name__ == "__main__":
    unittest.main()

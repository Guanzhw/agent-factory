"""Real PostgreSQL/native queue scheduling contracts; deterministic provider only.

Set FACTORY_TEST_DATABASE_URL to an owned disposable database. These tests never
replace the scheduler, HTTP route, queue or worker with a synthetic service.
"""
import copy
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pg_fixture import IsolatedPostgres

from agent_factory.catalog import create_plan
from agent_factory.config import Settings
from agent_factory.main import create_app


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class SchedulingPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.workspace = tempfile.TemporaryDirectory()
        cls.settings = Settings(db_url=cls.database.url,
            workspace=Path(cls.workspace.name), max_workers=1, max_user_tasks=12, max_total_tasks=100)
        # Fixture-only shorter tick; the application still starts exactly one
        # public native poller through its composed lifespan.
        cls.settings.schedule_poll_seconds = 1
        cls.app = create_app(cls.settings)
        cls.state = cls.app.app.state.factory
        cls.store, cls.auth, cls.bridge = (cls.state[key] for key in ("store", "auth", "bridge"))
        cls.db = cls.store.native_db
        cls.client = TestClient(cls.app).__enter__()
        cls.service = cls.state["schedules"]
        # Preserve the native last-admin safeguard while testing revocation.
        cls.backup_admin = "synthetic-scheduler-admin-" + str(uuid4())
        cls.auth.directory.upsert(cls.backup_admin, name="Synthetic scheduler test operator")
        cls.auth.authorization.assign(cls.backup_admin, "factory-manager")

    @classmethod
    def tearDownClass(cls):
        cls.auth.authorization.unassign(cls.backup_admin, "factory-manager")
        cls.auth.directory.remove(cls.backup_admin)
        cls.client.__exit__(None, None, None)
        cls.store.engine.dispose()
        cls.db.db_engine.dispose()
        cls.workspace.cleanup()
        cls.database.__exit__(None, None, None)

    def setUp(self):
        self.schedule_ids = []
        self.original_bridge = self.service.bridge

    def tearDown(self):
        self.service.bridge = self.original_bridge
        self.auth.authorization.assign("manager", "factory-manager")
        self.auth.directory.set_disabled("manager", False)
        for identifier in self.schedule_ids:
            self.service.set_enabled("manager", identifier, False)
            for row in self.service.occurrences("manager", identifier):
                if row["task_id"]:
                    self.call(self.service.cancel_occurrence, "manager", identifier, row["id"])

    def call(self, function, *args):
        return self.client.portal.call(function, *args)

    def fixture(self, goal="scheduled checksum fixture", application="checksum"):
        plan = create_plan(self.store, "manager", goal, "literature", application)
        schedule = self.service.create("manager", plan["id"], "schedule-" + str(uuid4()), "0 0 1 1 *")
        self.schedule_ids.append(schedule["id"])
        return plan, schedule

    def wait(self, task_id, states):
        deadline = time.monotonic() + 15
        ticket = {}
        while time.monotonic() < deadline:
            task = self.store.task(task_id)
            ticket = self.db.get_job(task["run_id"]) if task["run_id"] else {}
            if ticket and ticket["status"] in states:
                return ticket
            time.sleep(.05)
        self.fail(f"Native scheduled run did not reach {states}: {ticket}")

    def test_01_independent_native_runs_idempotency_and_conflict(self):
        _, schedule = self.fixture()
        first = self.call(self.service.trigger, "manager", schedule["id"], "first")
        repeat = self.call(self.service.trigger, "manager", schedule["id"], "first")
        second = self.call(self.service.trigger, "manager", schedule["id"], "second")
        self.assertEqual(first["task_id"], repeat["task_id"])
        self.assertNotEqual(first["task_id"], second["task_id"])
        tickets = [self.wait(row["task_id"], {"completed", "failed"}) for row in (first, second)]
        self.assertTrue(all(ticket["status"] == "completed" for ticket in tickets))
        self.assertNotEqual(tickets[0]["id"], tickets[1]["id"])
        self.assertTrue(all(ticket["idempotency_key"] for ticket in tickets))
        self.service.update("manager", schedule["id"], "0 0 2 1 *")
        with self.assertRaises(HTTPException) as error:
            self.call(self.service.trigger, "manager", schedule["id"], "first")
        self.assertEqual(error.exception.status_code, 409)

    def test_02_current_rights_and_owner_partition(self):
        _, schedule = self.fixture()
        with self.assertRaises(HTTPException) as error:
            self.service.get("bob", schedule["id"])
        self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as error:
            self.service.create("alice", self.store.plan(schedule["payload"]["planId"])["id"], "denied", "0 0 1 1 *")
        self.assertEqual(error.exception.status_code, 403)
        self.auth.authorization.unassign("manager", "factory-manager")
        with self.assertRaises(HTTPException) as error:
            self.call(self.service.execute, Schedule.from_dict(schedule), self.db)
        self.assertEqual(error.exception.status_code, 403)
        self.auth.authorization.assign("manager", "factory-manager")
        self.auth.directory.set_disabled("manager", True)
        with self.assertRaises(HTTPException) as error:
            self.call(self.service.trigger, "manager", schedule["id"], "disabled")
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_schedule_occurrences WHERE schedule_id=:id", id=schedule["id"])[0]["n"], 0)

    def test_03_lost_ack_reconciles_existing_native_ticket_without_replay(self):
        _, schedule = self.fixture()
        native_bridge = self.bridge

        class LostAcknowledgement:
            submissions = 0

            async def submit(inner, *args):
                inner.submissions += 1
                await native_bridge.submit(*args)  # Actual native commit, then transport observation fault.
                raise TimeoutError("Synthetic acknowledgement loss after real native acceptance")

            async def find_run(inner, *args):
                return await native_bridge.find_run(*args)

        boundary = LostAcknowledgement()
        self.service.bridge = boundary
        first = self.call(self.service.trigger, "manager", schedule["id"], "ack-loss")
        self.assertIn(first["status"], {"unknown", "accepted"})
        # Exercise startup reconciliation of the application's existing service;
        # no additional service/poller is created and no hard process restart
        # is claimed by this test.
        self.call(self.service.stop)
        self.call(self.service.start)
        second = self.call(self.service.trigger, "manager", schedule["id"], "ack-loss")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(second["status"], "accepted")
        self.assertEqual(boundary.submissions, 1)
        self.assertEqual(self.wait(second["task_id"], {"completed", "failed"})["status"], "completed")
        history = self.db.get_schedule_run(second["id"], user_id="manager")
        self.assertEqual(history["run_id"], self.store.task(second["task_id"])["run_id"])

    def test_04_quota_unknown_does_not_replay_pause_and_scoped_cancel(self):
        _, schedule = self.fixture("sort", "research")
        previous = self.settings.max_user_tasks
        try:
            self.settings.max_user_tasks = 0
            rejected = self.call(self.service.trigger, "manager", schedule["id"], "quota")
            self.assertEqual(rejected["status"], "rejected")
            self.assertIsNone(rejected["task_id"])
        finally:
            self.settings.max_user_tasks = previous
        accepted = self.call(self.service.trigger, "manager", schedule["id"], "waiting")
        self.assertEqual(self.wait(accepted["task_id"], {"paused", "failed"})["status"], "paused")
        self.service.set_enabled("manager", schedule["id"], False)
        with self.assertRaises(HTTPException):
            self.call(self.service.trigger, "manager", schedule["id"], "disabled")
        with self.assertRaises(HTTPException) as error:
            self.call(self.service.cancel_occurrence, "bob", schedule["id"], accepted["id"])
        self.assertEqual(error.exception.status_code, 404)
        self.call(self.service.cancel_occurrence, "manager", schedule["id"], accepted["id"])
        self.assertEqual(self.wait(accepted["task_id"], {"cancelled", "failed"})["status"], "cancelled")

    def test_05_native_poller_claims_due_definition_and_detects_tampering(self):
        _, schedule = self.fixture()
        self.db.update_schedule(schedule["id"], next_run_at=int(time.time()) - 1)
        deadline = time.monotonic() + 15
        rows = []
        while time.monotonic() < deadline:
            rows = self.service.occurrences("manager", schedule["id"])
            if rows and rows[0]["task_id"]:
                break
            time.sleep(.05)
        self.assertTrue(rows)
        self.assertEqual(self.wait(rows[0]["task_id"], {"completed", "failed"})["status"], "completed")
        self.assertGreater(self.db.get_schedule(schedule["id"])["next_run_at"], int(time.time()))
        original = copy.deepcopy(self.db.get_schedule(schedule["id"]))
        self.db.update_schedule(schedule["id"], payload={"planId": "forged", "user_id": "bob"})
        with self.assertRaises(HTTPException) as error:
            self.call(self.service.trigger, "manager", schedule["id"], "tampered")
        self.assertEqual(error.exception.status_code, 409)
        self.db.update_schedule(schedule["id"], payload=original["payload"])

    def test_06_no_ticket_unknown_retains_capacity_without_automatic_replay(self):
        _, schedule = self.fixture()
        native_bridge = self.bridge

        class UnknownTransport:
            submissions = 0

            async def submit(inner, *args):
                inner.submissions += 1
                raise TimeoutError("Synthetic transport failure before observable acknowledgement")

            async def find_run(inner, *args):
                return await native_bridge.find_run(*args)

        boundary = UnknownTransport()
        self.service.bridge = boundary
        first = self.call(self.service.trigger, "manager", schedule["id"], "unknown")
        second = self.call(self.service.trigger, "manager", schedule["id"], "unknown")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(second["status"], "unknown")
        self.assertEqual(boundary.submissions, 1)
        task = self.store.task(second["task_id"])
        self.assertFalse(task["terminal"])
        self.assertEqual(task["admission"], "unknown")
        self.assertIsNone(task["run_id"])

    def test_07_http_wrapper_plan_only_replay_ownership_and_native_ingress(self):
        def login(persona):
            self.client.cookies.clear()
            response = self.client.post("/api/factory/demo/login", json={"persona": persona})
            self.assertEqual(response.status_code, 200, response.text)

        login("manager")
        response = self.client.post("/api/factory/plans", json={
            "topic": "HTTP scheduling checksum fixture", "mode": "literature",
            "application": "checksum", "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        body = {"planId": response.json()["id"], "name": "HTTP-" + str(uuid4()),
                "cron": "0 0 1 1 *", "timezone": "Etc/UTC"}
        self.assertEqual(self.client.post("/api/factory/schedules", json={
            **body, "endpoint": "/arbitrary", "payload": {"user_id": "bob"}}).status_code, 422)
        response = self.client.post("/api/factory/schedules", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        schedule_id = response.json()["id"]
        self.schedule_ids.append(schedule_id)
        path = "/api/factory/schedules/" + schedule_id
        listing = self.client.get("/api/factory/schedules")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn(schedule_id, {item["id"] for item in listing.json()})
        request = {"requestId": "http-" + str(uuid4())}
        first = self.client.post(path + "/trigger", json=request)
        repeat = self.client.post(path + "/trigger", json=request)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(repeat.status_code, 202, repeat.text)
        self.assertEqual(first.json()["task_id"], repeat.json()["task_id"])
        self.assertEqual(self.wait(first.json()["task_id"], {"completed", "failed"})["status"], "completed")
        self.assertEqual(self.client.get(path + "/occurrences").status_code, 200)
        self.assertEqual(self.client.get("/schedules").status_code, 403)
        self.assertEqual(self.client.post("/schedules", json=body).status_code, 403)
        self.assertEqual(self.client.post(path + "/enabled", json={"enabled": False}).status_code, 200)
        self.assertEqual(self.client.post(path + "/trigger", json={"requestId": "disabled-trigger"}).status_code, 409)
        login("bob")
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get(path + "/occurrences").status_code, 404)
        self.assertEqual(self.client.post("/api/factory/schedules", json={**body, "name": "denied"}).status_code, 403)
        self.assertEqual(self.client.post(path + "/trigger", json=request).status_code, 403)


if __name__ == "__main__":
    unittest.main()

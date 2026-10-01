"""Twenty test identities against actual PostgreSQL, auth and native queue.

The deterministic model is an explicit fixture. These tests verify admission,
held capacity and cancellation, not twenty CPU workers or production throughput.
Subjects and native grants exist only inside the generated test database.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text

from pg_fixture import IsolatedPostgres
from agent_factory.config import Settings
from agent_factory.main import create_app


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class CapacityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.settings = Settings(db_url=cls.database.url, workspace=Path(cls.workspace.name),
                                max_workers=2, max_user_tasks=2, max_total_tasks=12, queue_poll=.05)
        cls.app = create_app(cls.settings)
        cls.state = cls.app.app.state.factory
        cls.store, cls.auth = cls.state["store"], cls.state["auth"]
        cls.addClassCleanup(cls.store.engine.dispose)
        cls.addClassCleanup(cls.store.native_db.db_engine.dispose)
        cls.users = [f"fixture-capacity-{index:02d}" for index in range(20)]
        for index, owner in enumerate(cls.users):
            cls.auth.directory.upsert(owner, name=f"Synthetic capacity user {index:02d}")
            cls.auth.authorization.assign(owner, "factory-user")
        cls.client = TestClient(cls.app).__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    def tearDown(self):
        # No rows or effects are erased to manufacture free capacity. Actual
        # native tickets are canceled and their complete group stop is read.
        for row in self.store.sql("SELECT id,owner_id FROM af_tasks WHERE NOT terminal AND run_id IS NOT NULL"):
            self.cancel_and_confirm(row["owner_id"], row["id"])

    def headers(self, owner):
        return {"Authorization": "Bearer " + self.auth._issue_native_token(owner)}

    def request(self, owner, method, path, *, expected=200, **kwargs):
        response = self.client.request(method, "/api/factory" + path, headers=self.headers(owner), **kwargs)
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def plan(self, owner):
        response = self.request(owner, "POST", "/plans", expected=201,
                                json={"topic": "sort", "mode": "literature", "application": "research",
                                      "requestId": str(uuid4())})
        self.assertEqual(response.json()["status"], "ready", response.text)
        return response.json()

    def submit(self, owner, plan, key=None):
        body = {"planId": plan["id"], "requestId": key or str(uuid4())}
        return self.request(owner, "POST", "/instances", expected=202, json=body).json(), body

    def wait(self, owner, task_id, states):
        deadline = time.monotonic() + 15
        last = None
        while time.monotonic() < deadline:
            last = self.request(owner, "GET", "/jobs/" + task_id).json()
            if last["job"]["status"] in states:
                return last
            time.sleep(.03)
        self.fail(f"Native capacity task did not reach {states}: {last}")

    def cancel_and_confirm(self, owner, task_id):
        self.request(owner, "POST", f"/jobs/{task_id}/cancel")
        stopped = self.wait(owner, task_id, {"canceled", "failed", "unknown"})
        expected = "failed" if self.store.failure_cleanup_requested(task_id) else "canceled"
        self.assertEqual(stopped["job"]["status"], expected, stopped)
        self.assertTrue(stopped["snapshot"]["delegation"]["allStopped"], stopped)
        task = self.store.task(task_id, owner)
        self.assertTrue(task["terminal"])
        self.assertEqual(self.store.native_db.get_job(task["run_id"])["status"], "cancelled")
        return stopped

    def held(self, owner=None):
        query = "SELECT COUNT(*) AS n FROM af_tasks WHERE NOT terminal"
        if owner:
            query += " AND owner_id=:owner"
        return self.store.sql(query, owner=owner)[0]["n"]

    def tickets(self, task_id=None):
        db = self.store.native_db
        if not inspect(db.db_engine).has_table(db.job_table_name, schema=db.db_schema):
            return 0
        table = Table(db.job_table_name, MetaData(), schema=db.db_schema, autoload_with=db.db_engine)
        query = select(func.count()).select_from(table)
        if task_id:
            query = query.where(table.c.session_id == task_id)
        with db.db_engine.connect() as connection:
            return connection.execute(query).scalar()

    def test_01_twenty_concurrent_users_twelve_held_two_native_workers_and_scoped_release(self):
        worker = self.app.app.state.queue_worker
        self.assertTrue(worker.config.durable)
        self.assertEqual(worker.config.max_concurrency, 2)
        self.assertEqual(worker.config.max_queue_depth, self.settings.max_queued)
        self.assertEqual(len(self.users), 20)
        self.assertTrue(all(self.auth.directory.get(owner) is not None for owner in self.users))
        plans = {owner: self.plan(owner) for owner in self.users}
        requests = {owner: {"planId": plan["id"], "requestId": str(uuid4())} for owner, plan in plans.items()}
        baseline = self.tickets()
        barrier = threading.Barrier(20)
        stop = threading.Event()
        observations, observation_errors = [], []
        monitor_engine = create_engine(self.database.url, pool_size=1, max_overflow=0)
        def monitor_capacity():
            try:
                with monitor_engine.connect() as connection:
                    while not stop.is_set():
                        observations.append(connection.execute(text("SELECT COUNT(*) FROM af_tasks WHERE NOT terminal")).scalar())
                        stop.wait(.005)
            except Exception as error:
                observation_errors.append(type(error).__name__)
        monitor = threading.Thread(target=monitor_capacity, name="isolated-capacity-observer", daemon=True)
        monitor.start()
        def concurrent_submit(owner):
            barrier.wait(timeout=10)
            return owner, self.client.post("/api/factory/instances", headers=self.headers(owner), json=requests[owner])
        try:
            with ThreadPoolExecutor(max_workers=20) as pool:
                responses = list(pool.map(concurrent_submit, self.users))
        finally:
            stop.set()
            monitor.join(timeout=5)
            monitor_engine.dispose()
        accepted = [(owner, response.json()) for owner, response in responses if response.status_code == 202]
        rejected = [(owner, response) for owner, response in responses if response.status_code == 429]
        self.assertEqual(len(accepted), 12, [(owner, r.status_code, r.text) for owner, r in responses])
        self.assertEqual(len(rejected), 8)
        self.assertFalse(observation_errors, observation_errors)
        self.assertTrue(observations)
        self.assertLessEqual(max(observations), 12)
        self.assertEqual(self.held(), 12)
        self.assertEqual(self.tickets() - baseline, 12)
        for owner, job in accepted:
            paused = self.wait(owner, job["id"], {"waiting_input", "failed", "unknown"})
            self.assertEqual(paused["job"]["status"], "waiting_input", paused)
            self.assertEqual(paused["job"]["ownerId"], owner)
            self.assertFalse(paused["snapshot"]["delegation"]["allStopped"])
            self.assertEqual(self.held(owner), 1)
        first_owner, first_job = accepted[0]
        other_owner = next(owner for owner in self.users if owner != first_owner)
        self.request(other_owner, "GET", "/jobs/" + first_job["id"], expected=404)
        self.request(other_owner, "POST", "/instances", expected=404,
                     json={"planId": plans[first_owner]["id"], "requestId": str(uuid4())})
        with ThreadPoolExecutor(max_workers=4) as pool:
            duplicates = list(pool.map(lambda _: self.client.post("/api/factory/instances", headers=self.headers(first_owner),
                                                                  json=requests[first_owner]), range(4)))
        self.assertTrue(all(response.status_code == 202 for response in duplicates), [response.text for response in duplicates])
        self.assertEqual({response.json()["id"] for response in duplicates}, {first_job["id"]})
        self.assertEqual(self.tickets(first_job["id"]), 1)
        self.assertEqual(self.held(), 12)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda pair: self.cancel_and_confirm(pair[0], pair[1]["id"]), accepted))
        self.assertEqual(self.held(), 0)
        self.assertEqual(self.tickets() - baseline, 12)
        # A quota-denied key had no reservation and can recover after known stop.
        recovered_owner = rejected[0][0]
        recovered = self.request(recovered_owner, "POST", "/instances", expected=202,
                                 json=requests[recovered_owner]).json()
        self.assertEqual(self.wait(recovered_owner, recovered["id"], {"waiting_input"})["job"]["status"], "waiting_input")
        self.cancel_and_confirm(recovered_owner, recovered["id"])
        self.assertEqual(self.held(), 0)

    def test_02_per_user_third_denied_with_global_room_and_native_current_grant(self):
        owner, peer = self.users[:2]
        first, _ = self.submit(owner, self.plan(owner))
        second, _ = self.submit(owner, self.plan(owner))
        for job in (first, second):
            self.wait(owner, job["id"], {"waiting_input"})
        self.assertEqual(self.held(), 2)
        self.assertEqual(self.held(owner), 2)
        self.assertLess(self.held(), 12)
        denied_body = {"planId": self.plan(owner)["id"], "requestId": str(uuid4())}
        self.request(owner, "POST", "/instances", expected=429, json=denied_body)
        self.request(owner, "GET", "/requests/" + denied_body["requestId"], expected=404)
        peer_job, _ = self.submit(peer, self.plan(peer))
        self.wait(peer, peer_job["id"], {"waiting_input"})
        self.assertEqual(self.held(), 3)
        self.auth.authorization.unassign(owner, "factory-user")
        try:
            self.request(owner, "POST", "/instances", expected=403, json=denied_body)
            self.request(owner, "GET", "/jobs/" + first["id"], expected=403)
        finally:
            # Explicit test-only fixture assignment, inside the disposable DB.
            self.auth.authorization.assign(owner, "factory-user")
        self.cancel_and_confirm(owner, first["id"])
        recovered = self.request(owner, "POST", "/instances", expected=202, json=denied_body).json()
        self.wait(owner, recovered["id"], {"waiting_input"})
        # The earlier current-rights revocation may also have positively
        # stopped the second original ticket in the background. The newly
        # accepted paused ticket holds capacity; the hard per-user cap remains.
        self.assertIn(self.held(owner), {1, 2})
        for subject, job in ((owner, second), (owner, recovered), (peer, peer_job)):
            self.cancel_and_confirm(subject, job["id"])
        self.assertEqual(self.held(), 0)

    def test_03_unknown_no_ticket_persists_holds_quota_and_cancel_never_manufactures_stop(self):
        owner = self.users[2]
        with mock.patch.object(self.state["bridge"], "submit", side_effect=HTTPException(503, "Controlled absent native acknowledgement")) as submit:
            unknown, body = self.submit(owner, self.plan(owner))
            duplicate = self.request(owner, "POST", "/instances", expected=202, json=body).json()
            self.assertEqual(duplicate["id"], unknown["id"])
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(unknown["status"], "unknown")
        task = self.store.task(unknown["id"], owner)
        self.assertEqual(task["admission"], "unknown")
        self.assertIsNone(task["run_id"])
        self.assertFalse(task["terminal"])
        self.assertEqual(self.tickets(unknown["id"]), 0)
        actual, _ = self.submit(owner, self.plan(owner))
        self.wait(owner, actual["id"], {"waiting_input"})
        self.assertEqual(self.held(owner), 2)
        blocked = {"planId": self.plan(owner)["id"], "requestId": str(uuid4())}
        self.request(owner, "POST", "/instances", expected=429, json=blocked)
        self.request(owner, "POST", f'/jobs/{unknown["id"]}/cancel')
        self.request(owner, "POST", f'/jobs/{unknown["id"]}/reconcile')
        observed = self.request(owner, "GET", "/jobs/" + unknown["id"]).json()
        self.assertEqual(observed["job"]["status"], "unknown", observed)
        self.assertFalse(observed["snapshot"]["delegation"]["allStopped"])
        self.assertTrue(observed["snapshot"]["delegation"]["unknown"])
        self.assertFalse(self.store.task(unknown["id"], owner)["terminal"])
        receipt = self.request(owner, "GET", "/requests/" + body["requestId"]).json()
        self.assertEqual(receipt["admission"], "unknown")
        self.assertIsNone(receipt["runId"])
        self.request(owner, "POST", "/instances", expected=429, json=blocked)
        self.cancel_and_confirm(owner, actual["id"])
        self.assertEqual(self.held(owner), 1)
        recovered = self.request(owner, "POST", "/instances", expected=202, json=blocked).json()
        self.wait(owner, recovered["id"], {"waiting_input"})
        self.cancel_and_confirm(owner, recovered["id"])
        self.assertEqual(self.held(owner), 1)
        self.assertEqual(self.tickets(unknown["id"]), 0)
        self.assertTrue(self.store.task(unknown["id"], owner)["cancel_requested"])
        self.assertFalse(self.store.task(unknown["id"], owner)["terminal"])


if __name__ == "__main__":
    unittest.main()

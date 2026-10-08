# pyright: reportMissingImports=false
"""Real PostgreSQL/Factory tasks; synthetic allocation effects, no host capacity claim."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.resources import ComputePool, PersistentResourceService, RemoteTarget
from pg_fixture import IsolatedPostgres


class ControlledProvider:
    """Thread-safe external-effect stand-in; all effects are synthetic records."""
    def __init__(self):
        self.lock = threading.Lock()
        self.records = {}
        self.allocations = self.cancellations = self.reclaims = 0
        self.lose_allocate_ack = self.lose_reclaim_ack = False
        self.confirm_cancel = self.confirm_release = False
        self.effect_identities = []

    async def allocate(self, lease_id, owner, fingerprint, limits):
        with self.lock:
            self.allocations += 1
            record = {"leaseId": lease_id, "ownerId": owner, "fingerprint": fingerprint,
                "state": "RUNNING", "providerJobId": "controlled-" + lease_id}
            self.records[lease_id] = record
            if self.lose_allocate_ack:
                raise TimeoutError("Controlled allocation acknowledgement loss")
            return dict(record)

    async def inspect(self, lease_id, owner):
        with self.lock:
            record = self.records[lease_id]
            if record["ownerId"] != owner:
                raise ValueError("Controlled owner mismatch")
            return dict(record)

    async def cancel(self, lease_id, owner):
        with self.lock:
            self.cancellations += 1
            self.effect_identities.append(("cancel", lease_id, owner))
            if self.confirm_cancel:
                self.records[lease_id]["state"] = "CANCEL_CONFIRMED"
            return {"accepted": True}

    async def reclaim(self, lease_id, owner):
        with self.lock:
            self.reclaims += 1
            self.effect_identities.append(("reclaim", lease_id, owner))
            if self.lose_reclaim_ack:
                raise TimeoutError("Controlled release acknowledgement loss")
            if self.confirm_release:
                self.records[lease_id].update(state="RECLAIMED", released=True)
            return {"accepted": True}

    def observe(self, lease_id, **values):
        with self.lock:
            self.records[lease_id].update(values)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class ResourceCapacityPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix="resource-capacity-")
        self.addCleanup(self.workspace.cleanup)
        self.peer = ControlledProvider()

    def start(self, *, slots=2, owner_slots=2):
        self.pool = ComputePool("controlled-shared-pool", cpu=slots, memory_mb=slots * 1024,
            disk_mb=slots * 512, max_leases=4, max_owner_leases=owner_slots)
        self.targets = {ref: RemoteTarget("Controlled shared compute", "compute", frozenset({"alice", "bob"}),
            provider=self.peer, max_leases=4, max_cpu=2, max_memory_mb=2048, max_disk_mb=1024,
            capacity_pool=self.pool, synthetic_fixture=True) for ref in ("first-ref", "second-ref")}
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.workspace.name),
            max_workers=2, max_user_tasks=3, max_total_tasks=6, queue_poll=.05,
            remote_targets=self.targets)
        application = create_app(self.settings)
        self.state = application.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(application).__enter__()  # type: ignore[arg-type]
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.stop_tasks)
        self.service = self.state["resources"]
        # A second actual Store object shares durable rows but not a SQLAlchemy
        # engine or service instance. PostgreSQL locks, not Python locks, arbitrate.
        second_store = copy.copy(self.store)
        second_store.engine = create_engine(self.database.url)
        self.addCleanup(second_store.engine.dispose)
        self.other = PersistentResourceService(second_store, self.auth, self.targets)

    def headers(self, owner):
        return {"Authorization": "Bearer " + self.auth._issue_native_token(owner)}

    def request(self, owner, method, path, *, expected=200, **kwargs):
        response = self.client.request(method, "/api/factory" + path, headers=self.headers(owner), **kwargs)
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def task(self, owner):
        plan = self.request(owner, "POST", "/plans", expected=201, json={"topic": "sort", "mode": "literature",
            "application": "research", "requestId": str(uuid4())}).json()
        task = self.request(owner, "POST", "/instances", expected=202,
            json={"planId": plan["id"], "requestId": str(uuid4())}).json()["id"]
        self.wait(owner, task, {"waiting_input"})
        return task

    def wait(self, owner, task, states):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            detail = self.request(owner, "GET", "/jobs/" + task).json()
            if detail["job"]["status"] in states:
                return detail
            time.sleep(.04)
        self.fail("Controlled native task did not reach expected state")

    def stop_tasks(self):
        # Restore fixture grants solely for test cleanup; production revocation
        # cleanup belongs to the separate maintenance boundary, not user APIs.
        self.auth.authorization.assign("alice", "factory-user")
        self.auth.authorization.assign("bob", "factory-user")
        for row in self.store.sql("SELECT id,owner_id FROM af_tasks WHERE NOT terminal AND run_id IS NOT NULL"):
            self.request(row["owner_id"], "POST", "/jobs/" + row["id"] + "/cancel")
            self.wait(row["owner_id"], row["id"], {"canceled", "failed", "unknown"})

    @staticmethod
    def limits():
        return {"cpu": 1, "memoryMb": 1024, "diskMb": 512, "seconds": 30}

    def allocate(self, service, owner, ref, task, key=None):
        return asyncio.run(service.allocate(owner, ref, task, key or str(uuid4()), self.limits()))

    def assert_capacity_denied(self, owner, task):
        with self.assertRaises(HTTPException) as raised:
            self.allocate(self.other, owner, "second-ref", task)
        self.assertEqual(raised.exception.status_code, 429)

    def test_two_services_compete_across_owners_and_references_without_overselling(self):
        self.start()
        work = [(owner, self.task(owner)) for owner in ("alice", "bob", "alice", "bob")]
        barrier = threading.Barrier(4)
        def compete(index):
            owner, task = work[index]
            barrier.wait(timeout=10)
            try:
                return self.allocate(self.service if index % 2 else self.other, owner,
                    "first-ref" if index < 2 else "second-ref", task)
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(compete, range(4)))
        leases = [row for row in results if isinstance(row, dict)]
        self.assertEqual(len(leases), 2, results)
        self.assertEqual(sum(row == 429 for row in results), 2)
        self.assertEqual(self.peer.allocations, 2)
        for row in leases:
            self.assertEqual(row["poolId"], self.pool.pool_id)
            self.assertTrue(row["poolFingerprint"])
            self.assertTrue(row["capacityHeld"])
        rows = self.store.sql("SELECT body FROM af_leases WHERE state <> 'RECLAIMED'")
        self.assertEqual(len(rows), 2)
        for key, maximum in (("cpu", 2), ("memoryMb", 2048), ("diskMb", 1024)):
            self.assertLessEqual(sum(row["body"]["limits"][key] for row in rows), maximum)

    def test_unknown_restart_cancel_and_lost_release_hold_pool_until_positive_read(self):
        self.start(slots=1)
        alice, bob = self.task("alice"), self.task("bob")
        self.peer.lose_allocate_ack = True
        key = str(uuid4())
        lease = self.allocate(self.service, "alice", "first-ref", alice, key)
        self.assertEqual(lease["state"], "UNKNOWN")
        resumed = self.allocate(self.other, "alice", "first-ref", alice, key)
        self.assertEqual(resumed["id"], lease["id"])
        self.assertEqual(self.peer.allocations, 1)
        self.assert_capacity_denied("bob", bob)
        self.service.disconnect("alice", lease["id"])
        self.assert_capacity_denied("bob", bob)
        self.auth.authorization.unassign("alice", "factory-user")
        with self.assertRaises(HTTPException) as revoked:
            asyncio.run(self.other.cancel("alice", lease["id"]))
        self.assertEqual(revoked.exception.status_code, 403)
        self.assertEqual(self.peer.cancellations, 0)
        self.auth.authorization.assign("alice", "factory-user")
        asyncio.run(self.other.cancel("alice", lease["id"]))
        asyncio.run(self.service.cancel("alice", lease["id"]))
        self.assertEqual(self.peer.cancellations, 1)
        self.peer.observe(lease["id"], state="CANCEL_CONFIRMED")
        terminal = asyncio.run(self.other.reconcile("alice", lease["id"]))
        self.assertEqual(terminal["state"], "CANCEL_CONFIRMED")
        self.assertTrue(terminal["capacityHeld"])
        self.assert_capacity_denied("bob", bob)
        self.peer.lose_reclaim_ack = True
        uncertain = asyncio.run(self.service.reclaim("alice", lease["id"]))
        self.assertTrue(uncertain["capacityHeld"])
        with self.assertRaises(HTTPException):
            asyncio.run(self.other.reclaim("alice", lease["id"]))
        self.assertEqual(self.peer.reclaims, 1)
        self.assert_capacity_denied("bob", bob)
        self.peer.observe(lease["id"], state="RECLAIMED", released=True)
        released = asyncio.run(self.other.reconcile("alice", lease["id"]))
        self.assertEqual(released["state"], "RECLAIMED")
        self.assertFalse(released["capacityHeld"])
        self.peer.lose_allocate_ack = False
        self.assertEqual(self.allocate(self.other, "bob", "second-ref", bob)["state"], "RUNNING")

    def test_native_resource_api_is_scoped_and_same_task_cannot_alias_pool(self):
        self.start(owner_slots=1)
        alice, second = self.task("alice"), self.task("alice")
        lease = self.request("alice", "POST", "/resources/allocate", json={"connectionRef": "first-ref",
            "taskId": alice, "requestId": str(uuid4()), "limits": self.limits()}).json()
        for method, suffix in (("GET", ""), ("POST", "/cancel"), ("POST", "/reconcile"), ("POST", "/reclaim")):
            self.request("bob", method, "/resources/leases/" + lease["id"] + suffix, expected=404)
        self.assertEqual((self.peer.cancellations, self.peer.reclaims), (0, 0))
        with self.assertRaises(HTTPException) as duplicate:
            self.allocate(self.other, "alice", "second-ref", alice)
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assert_capacity_denied("alice", second)
        self.assertEqual(self.peer.allocations, 1)

    def test_admin_maintenance_cleans_revoked_owner_without_restoring_authority(self):
        self.start(slots=1)
        alice, bob = self.task("alice"), self.task("bob")
        lease = self.request("alice", "POST", "/resources/allocate", json={"connectionRef": "first-ref",
            "taskId": alice, "requestId": str(uuid4()), "limits": self.limits()}).json()
        self.assert_capacity_denied("bob", bob)
        self.auth.authorization.unassign("alice", "factory-user")
        for operation in ("cancel", "reclaim"):
            self.request("alice", "POST", f"/resources/leases/{lease['id']}/{operation}", expected=403)
        self.request("bob", "POST", "/resources/maintenance", expected=403)
        self.assertEqual((self.peer.cancellations, self.peer.reclaims), (0, 0))
        self.peer.confirm_cancel = self.peer.confirm_release = True
        result = self.request("manager", "POST", "/resources/maintenance").json()
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["outcomes"], [{"leaseId": lease["id"], "status": "reclaimed",
            "reason": "OWNER_REVOKED", "capacityHeld": False}])
        self.assertEqual(self.peer.effect_identities, [("cancel", lease["id"], "alice"),
            ("reclaim", lease["id"], "alice")])
        self.assertEqual(self.peer.allocations, 1, "Maintenance must not allocate replacement work")
        persisted = self.store.sql("SELECT body FROM af_leases WHERE id=:id", id=lease["id"])[0]["body"]
        self.assertEqual(persisted["state"], "RECLAIMED")
        self.assertFalse(persisted["capacityHeld"])
        for key in ("id", "ownerId", "connectionRef", "fingerprint", "poolFingerprint"):
            self.assertEqual(persisted[key], lease[key])
        # Maintenance has no grant-restoration side effect, even after cleanup.
        self.request("alice", "POST", f"/resources/leases/{lease['id']}/cancel", expected=403)
        self.assertEqual(self.request("manager", "POST", "/resources/maintenance").json()["scanned"], 0)
        self.assertEqual((self.peer.cancellations, self.peer.reclaims), (1, 1))
        # A separately authorized user's explicit allocation observes free pool.
        replacement = self.request("bob", "POST", "/resources/allocate", json={"connectionRef": "second-ref",
            "taskId": bob, "requestId": str(uuid4()), "limits": self.limits()}).json()
        self.assertEqual(replacement["state"], "RUNNING")
        self.assertNotEqual(replacement["id"], lease["id"])


if __name__ == "__main__":
    unittest.main()

"""Native PG + real bounded cooperative processes, never host-capacity proof."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import sys
import threading
from tempfile import TemporaryDirectory
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec
from agent_factory.process_provider import ProcessResourceProvider
from agent_factory.process_runtime_profile import process_settings, publish_process_application, TOOL_NAME
from agent_factory.process_runtime import ProcessRuntimeService
from agent_factory.resources import ComputePool, PersistentResourceService, RemoteTarget
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres


class MustNotAllocate:
    """Admission probe only: shared pool must reject before external dispatch."""
    async def allocate(self, *args):
        raise AssertionError("A held shared pool must reject the second allocation")


@unittest.skipUnless(sys.platform == "linux" and os.getenv("FACTORY_TEST_DATABASE_URL"),
                     "Requires Linux cooperative process limits and disposable loopback PostgreSQL")
class ProcessRuntimePostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        workspace = TemporaryDirectory(prefix="native-process-runtime-")
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.target_ref = "bounded-process-target"

    def start(self, *, code="print('Synthetic bounded native process')", wall=5, start_client=True):
        initial = Settings(db_url=self.database.url, workspace=self.root)
        self.bootstrap = Store(self.database.url, initial)
        self.addCleanup(self.bootstrap.engine.dispose)
        custody = self.root / "process-custody"
        custody.mkdir(mode=0o700)
        executable = Path(sys.executable).resolve()
        self.spec = ProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(), ("-I", "-c", code))
        self.limits = ProcessLimits(wall_seconds=wall)
        self.provider = ProcessResourceProvider(self.bootstrap, custody, self.spec, self.limits)
        self.pool = ComputePool("native-process-pool", 1, 128, 1, max_leases=1, max_owner_leases=1)
        target = RemoteTarget("Synthetic bounded process", "compute", frozenset({"alice", "bob"}),
            provider=self.provider, synthetic_fixture=True, max_cpu=1, max_memory_mb=128,
            max_disk_mb=1, max_seconds=5, capacity_pool=self.pool)
        probe = RemoteTarget("Shared pool admission probe", "compute", frozenset({"bob"}),
            provider=MustNotAllocate(), synthetic_fixture=True, max_cpu=1, max_memory_mb=128,
            max_disk_mb=1, max_seconds=5, capacity_pool=self.pool)
        self.settings = process_settings(db_url=self.database.url, workspace=self.root,
            target_ref=self.target_ref, remote_targets={self.target_ref: target, "capacity-probe": probe})
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.auth.directory.upsert("process-reviewer", name="Synthetic process reviewer")
        self.auth.authorization.assign("process-reviewer", "factory-manager")
        self.application = publish_process_application(self.state, target_ref=self.target_ref,
            author="manager", reviewer="process-reviewer")
        if start_client:
            self.client = TestClient(self.app).__enter__()
            self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        # Explicit original-custody cleanup only; never replacement dispatch.
        for row in self.store.sql("SELECT id,owner_id FROM af_process_allocations"):
            asyncio.run(self.provider.cancel(row["id"], row["owner_id"]))
            path = self.provider.root / row["id"] / "custody.sqlite"
            if path.exists():
                original = BoundedProcessAdapter(path)
                snapshot = original.inspect(owner_id=row["owner_id"])
                if snapshot.get("child") or snapshot.get("guardian"):
                    self.assertTrue(original.wait(owner_id=row["owner_id"])["stoppedProof"],
                                    "Real fixture processes must stop before private scratch cleanup")

    def request(self, method, path, body=None, owner="alice"):
        response = self.client.request(method, "/api/factory" + path, json=body,
            headers={"Authorization": "Bearer " + self.auth._issue_native_token(owner)})
        self.assertTrue(response.is_success, response.text)
        return response.json()

    def submit(self):
        def post(path, body, owner="alice"):
            return self.request("POST", path, {"requestId": str(uuid4()), **body}, owner)
        proposal = post("/compositions/proposals", {"goal": "Run the pinned synthetic process once",
            "mode": "controlled-fixture", "applicationRef": {key: self.application[key] for key in ("id", "version", "sha256")}})
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal)
        plan = post("/compositions/proposals/" + proposal["id"] + "/accept", {})
        self.assertEqual(plan["tools"], [TOOL_NAME])
        review = post("/plan-reviews", {"planId": plan["id"]})
        post("/plan-reviews/" + review["id"] + "/decision", {"approved": True}, "manager")
        return post("/instances", {"planId": plan["id"]}), plan

    def until(self, probe, *, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = probe()
            if result:
                return result
            time.sleep(.04)
        self.fail("Bounded process fixture did not reach its expected observable state")

    def lease(self, task):
        rows = self.store.sql("SELECT body FROM af_leases WHERE body->>'localTaskId'=:task", task=task["id"])
        if not rows:
            return None
        lease = rows[0]["body"]
        allocated = self.store.sql("SELECT body FROM af_process_allocations WHERE id=:id", id=lease["id"])
        return lease if allocated and allocated[0]["body"].get("processPin") else None

    def process_state(self, lease, *, running=False):
        result = asyncio.run(self.provider.inspect(lease["id"], "alice"))
        return result if (result["state"] == "RUNNING" if running else result["allStopped"]) else None

    def test_original_native_plan_task_lease_and_process_identity_survive_reopen(self):
        self.start()
        task, plan = self.submit()
        def completed():
            detail = self.request("GET", "/jobs/" + task["id"])
            return detail if detail["job"]["status"] == "completed" else None
        detail = self.until(completed)
        self.assertEqual(detail["job"]["status"], "completed")
        lease = self.lease(task)
        persisted = self.store.task(task["id"])
        self.assertEqual(lease["planId"], plan["id"])
        self.assertEqual(lease["nativeRunId"], persisted["run_id"])
        self.assertEqual(lease["localTaskId"], task["id"])
        self.assertEqual(self.store.native_db.get_job(persisted["run_id"])["status"], "completed")
        snapshot = self.until(lambda: self.process_state(lease))
        reopened = ProcessResourceProvider(self.bootstrap, self.provider.root, self.spec, self.limits)
        same = asyncio.run(reopened.inspect(lease["id"], "alice"))
        self.assertEqual(same["providerJobId"], snapshot["providerJobId"])
        self.assertEqual(same["fingerprint"], lease["fingerprint"])
        self.assertEqual(same["state"], "RECLAIMED")
        self.assertEqual(same["executionStatus"], "COMPLETED")
        self.assertEqual(same["exitCode"], 0)
        self.assertTrue(same["released"])
        self.assertFalse(same["capacityHeld"])
        self.assertTrue(same["stopEvidence"]["allStopped"])
        self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)
        for key in ("aggregateQuota", "hostileCodeSandbox", "networkIsolation"):
            self.assertFalse(same["enforcement"][key])
        self.assertEqual(self.store.plan(plan["id"], "alice"), plan)
        denied = self.client.get("/api/factory/jobs/" + task["id"],
            headers={"Authorization": "Bearer " + self.auth._issue_native_token("bob")})
        self.assertEqual(denied.status_code, 404)
        with self.assertRaises(ValueError):
            asyncio.run(reopened.inspect(lease["id"], "bob"))
        # A completed original context may read its receipt or be denied; a
        # released lease must never turn that request into another allocation.
        with patch.object(BoundedProcessAdapter, "launch") as launch:
            try:
                repeated = asyncio.run(self.store.process_runtime.run(self.store.process_runtime._context(persisted),
                    {"targetRef": self.target_ref}))
            except HTTPException as denied_replay:
                self.assertIn(denied_replay.status_code, (403, 409))
            else:
                self.assertEqual(repeated["leaseId"], lease["id"])
                self.assertEqual(repeated["providerJobId"], same["providerJobId"])
                self.assertEqual(repeated["nativeRunId"], persisted["run_id"])
                self.assertEqual(repeated["localTaskId"], task["id"])
                self.assertEqual(repeated["planId"], plan["id"])
                self.assertEqual(repeated["artifactId"], detail["artifacts"][0]["id"])
                self.assertEqual(repeated["artifactSha256"], detail["artifacts"][0]["sha256"])
            launch.assert_not_called()
        self.assertEqual(self.lease(task)["id"], lease["id"])
        self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)

    def test_running_pool_contention_and_current_cancel_stop_original_process(self):
        self.start(code="import time;time.sleep(20)")
        task, _ = self.submit()
        lease = self.until(lambda: self.lease(task))
        self.until(lambda: self.process_state(lease, running=True))
        other_plan = self.store.save_plan({"id": str(uuid4()), "ownerId": "bob", "syntheticFixture": True})
        other_task, _ = self.store.reserve_task(other_plan, str(uuid4()))
        resources = self.state["resources"]
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(resources.allocate("bob", "capacity-probe", other_task["id"], str(uuid4()),
                {"cpu": 1, "memoryMb": 128, "diskMb": 1, "seconds": 5}))
        self.assertEqual(caught.exception.status_code, 429)
        self.store.request_cancel(task["id"])
        self.assertTrue(self.until(lambda: self.process_state(lease))["allStopped"])
        custody = BoundedProcessAdapter(self.provider.root / lease["id"] / "custody.sqlite")
        self.assertEqual(custody.inspect(owner_id="alice")["state"], "CANCELLED")
        self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)

    def test_current_role_revocation_stops_original_without_new_launch(self):
        self.start(code="import time;time.sleep(20)")
        task, _ = self.submit()
        lease = self.until(lambda: self.lease(task))
        self.until(lambda: self.process_state(lease, running=True))
        self.auth.authorization.unassign("alice", "factory-user")
        self.until(lambda: self.process_state(lease))
        custody = BoundedProcessAdapter(self.provider.root / lease["id"] / "custody.sqlite")
        self.assertEqual(custody.inspect(owner_id="alice")["state"], "CANCELLED")
        self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)
        self.assertEqual(self.auth.authorization.roles_of("alice"), [])

    def test_lost_launch_receipt_reconciles_original_process_without_replay(self):
        self.start(code="import time;time.sleep(.2);print('Original process only')")
        original = BoundedProcessAdapter.launch
        launches = []
        def lose_receipt(adapter, **kwargs):
            launches.append(adapter.path)
            original(adapter, **kwargs)
            raise ValueError("Synthetic lost launch receipt")
        with patch.object(BoundedProcessAdapter, "launch", lose_receipt):
            task, _ = self.submit()
            lease = self.until(lambda: self.lease(task))
            stopped = self.until(lambda: self.process_state(lease))
        reopened = ProcessResourceProvider(self.bootstrap, self.provider.root, self.spec, self.limits)
        again = asyncio.run(reopened.inspect(lease["id"], "alice"))
        self.assertEqual(again["providerJobId"], stopped["providerJobId"])
        self.assertEqual(len(launches), 1)
        self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)
        self.assertTrue(again["allStopped"])

    def test_unknown_launch_retains_pool_after_provider_restart_without_replay(self):
        self.start()
        with patch("agent_factory.process_enforcement.subprocess.Popen",
                   side_effect=OSError("Synthetic dispatch result unavailable")) as spawn:
            task, _ = self.submit()
            lease = self.until(lambda: self.lease(task))
            self.until(lambda: spawn.call_count == 1)
            reopened = ProcessResourceProvider(self.bootstrap, self.provider.root, self.spec, self.limits)
            unknown = asyncio.run(reopened.inspect(lease["id"], "alice"))
            self.assertEqual(unknown["state"], "UNKNOWN")
            self.assertTrue(unknown["capacityHeld"])
            self.assertFalse(unknown["allStopped"])
            original_run = self.store.task(task["id"])["run_id"]
            native = self.until(lambda: (row if row["status"] in {"completed", "failed", "cancelled"} else None)
                                if (row := self.store.native_db.get_job(original_run)) else None)
            print("Synthetic UNKNOWN custody native terminal: " + native["status"])
            # Native terminal status is not positive process-stop evidence. Even an
            # explicit terminal observation must retain both custody budgets.
            self.store.observed(self.store.task(task["id"]), "failed", True)
            self.assertFalse(self.store.task(task["id"])["terminal"])
            self.assertTrue(self.store.process_runtime.task_held(task["id"]))
            self.assertEqual(self.store.sql("SELECT state FROM af_disk_holds WHERE task_id=:id",
                                            id=task["id"]), [{"state": "HELD"}])
            other_plan = self.store.save_plan({"id": str(uuid4()), "ownerId": "bob", "syntheticFixture": True})
            other_task, _ = self.store.reserve_task(other_plan, str(uuid4()))
            # reserve_task opportunistically inspects terminal native jobs;
            # that second release path must preserve the original UNKNOWN hold.
            retained = self.store.task(task["id"])
            self.assertFalse(retained["terminal"])
            self.assertEqual(retained["run_id"], original_run)
            self.assertTrue(self.store.process_runtime.task_held(task["id"]))
            self.assertEqual(self.store.sql("SELECT state FROM af_disk_holds WHERE task_id=:id",
                                            id=task["id"]), [{"state": "HELD"}])
            self.assertEqual(self.lease(task)["id"], lease["id"])
            self.assertNotEqual(self.lease(task)["state"], "RECLAIMED")
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(self.state["resources"].allocate("bob", "capacity-probe", other_task["id"], str(uuid4()),
                    {"cpu": 1, "memoryMb": 128, "diskMb": 1, "seconds": 5}))
            self.assertEqual(caught.exception.status_code, 429)
            self.assertEqual(spawn.call_count, 1)
            self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)

    def test_guardian_deadline_records_stop_proof_without_claiming_success(self):
        self.start(code="import time;time.sleep(20)", wall=.3)
        # This case isolates the guardian deadline from the independent outer
        # lease deadline. Slow DB/dispatch admission must not turn it into a
        # race between cancellation and the .3-second child wall limit.
        from agent_factory.process_runtime import process_reservation
        reservation = process_reservation(self.provider) | {"seconds": 5}
        with patch("agent_factory.process_runtime.process_reservation", return_value=reservation):
            task, _ = self.submit()
            lease = self.until(lambda: self.lease(task))
            self.until(lambda: self.process_state(lease))
        custody = BoundedProcessAdapter(self.provider.root / lease["id"] / "custody.sqlite")
        evidence = custody.inspect(owner_id="alice")
        self.assertEqual(evidence["state"], "LIMIT_STOPPED")
        self.assertTrue(evidence["stoppedProof"])
        self.until(lambda: self.lease(task)["state"] == "RECLAIMED")
        self.assertEqual(self.lease(task)["executionStatus"], "LIMIT_STOPPED")
        self.assertFalse(self.lease(task)["capacityHeld"])
        def failed():
            detail = self.request("GET", "/jobs/" + task["id"])
            return detail if detail["job"]["status"] == "failed" else None
        self.until(failed)
        self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)

    def test_lost_stop_receipt_reconciles_without_repeating_cancel(self):
        self.start(code="import time;time.sleep(20)")
        task, _ = self.submit()
        lease = self.until(lambda: self.lease(task))
        self.until(lambda: self.process_state(lease, running=True))
        original = self.provider.cancel
        cancellations = []
        async def lose_receipt(lease_id, owner):
            cancellations.append((lease_id, owner))
            await original(lease_id, owner)
            raise TimeoutError("Synthetic original stop acknowledgement lost")
        with patch.object(self.provider, "cancel", lose_receipt):
            self.store.request_cancel(task["id"])
            self.until(lambda: self.process_state(lease))
            self.until(lambda: self.lease(task)["state"] == "RECLAIMED")
        self.assertEqual(cancellations, [(lease["id"], "alice")])
        reopened = ProcessResourceProvider(self.bootstrap, self.provider.root, self.spec, self.limits)
        result = asyncio.run(reopened.inspect(lease["id"], "alice"))
        self.assertEqual(result["state"], "RECLAIMED")
        self.assertTrue(result["stopEvidence"]["allStopped"])
        self.assertEqual(len(self.store.sql("SELECT id FROM af_process_allocations")), 1)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class ProcessRuntimeTransactionPostgresTests(unittest.TestCase):
    """SQL concurrency contracts with explicit stub authority, no process claim."""
    def setUp(self):
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        self.settings = Settings(db_url=database.url)
        self.store = Store(database.url, self.settings)
        self.addCleanup(self.store.engine.dispose)
        plan = self.store.save_plan({"id": str(uuid4()), "ownerId": "alice", "syntheticFixture": True})
        self.plan = plan
        self.task, _ = self.store.reserve_task(plan, str(uuid4()))
        self.run_id = str(uuid4())
        self.store.accept(self.task["id"], self.run_id)
        self.task = self.store.task(self.task["id"])

    def test_terminal_commit_between_initial_read_and_reserve_lock_denies_allocation(self):
        authority = SimpleNamespace(require=lambda *args: None)
        target = RemoteTarget("Transaction-only fixture", "compute", frozenset({"alice"}),
            provider=MustNotAllocate(), synthetic_fixture=True,
            capacity_pool=ComputePool("transaction-pool", 1, 128, 1, max_leases=1, max_owner_leases=1))
        resources = PersistentResourceService(self.store, authority, {"fixed": target})
        runtime = ProcessRuntimeService(self.store, authority, resources)
        self.store.process_runtime = runtime
        reached, release = threading.Event(), threading.Event()
        original = resources._lock
        def pause(conn):
            reached.set()
            if not release.wait(5):
                raise AssertionError("Terminal transaction did not release reservation test barrier")
            original(conn)
        def reserve():
            return resources._reserve("alice", "fixed", self.task["id"], "synthetic-request",
                {"cpu": 1, "memoryMb": 128, "diskMb": 1, "seconds": 1},
                execution={"nativeRunId": self.run_id, "effectKey": "bounded-process-run-v1"})
        # Native authority itself is covered above. This fixture isolates the
        # ordering between the real Store terminal transaction and admission.
        with patch.object(runtime, "validate_execution"), patch.object(resources, "_lock", pause), \
                ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(reserve)
            try:
                self.assertTrue(reached.wait(5))
                self.store.observed(self.task, "completed", True)
                self.assertTrue(self.store.task(self.task["id"])["terminal"])
            finally:
                release.set()
            with self.assertRaises(HTTPException) as denied:
                future.result(timeout=5)
            self.assertEqual(denied.exception.status_code, 409)
        for table in ("af_process_runs", "af_leases", "af_process_allocations"):
            self.assertEqual(self.store.sql("SELECT * FROM " + table), [])

    def test_two_receipts_share_one_artifact_with_size_one_metadata_pool(self):
        self.store.engine.dispose()
        self.store.engine = create_engine(self.settings.db_url, pool_size=1, max_overflow=0, pool_timeout=1)
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.dispose_root_locks)
        service = ProcessRuntimeService(self.store, None, None)
        context = SimpleNamespace(session_id=self.task["id"], run_id=self.run_id, user_id="alice")
        lease = {"id": str(uuid4()), "localTaskId": self.task["id"], "planId": self.plan["id"],
                 "nativeRunId": self.run_id, "providerJobId": "synthetic-process-id", "state": "RECLAIMED",
                 "capacityHeld": False, "stopEvidence": {"allStopped": True}, "executionStatus": "COMPLETED", "exitCode": 0}
        barrier = threading.Barrier(2)
        def metadata_authority(*args):
            # A receipt lock must leave the only metadata connection available
            # for each fresh authorization call, rather than deadlock on itself.
            with self.store.engine.connect() as conn:
                self.assertEqual(conn.execute(text("SELECT 1")).scalar_one(), 1)
        def emit():
            barrier.wait(timeout=5)
            return service._receipt(context, lease)
        with patch.object(self.store, "authorize_tool", side_effect=metadata_authority), \
                ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(emit) for _ in range(2)]
            results = [future.result(timeout=8) for future in futures]
        self.assertEqual(results[0]["artifactId"], results[1]["artifactId"])
        self.assertEqual(len(self.store.artifacts(self.task["id"])), 1)

"""Only generated task scratch is moved or deleted; real PostgreSQL/native stop."""
import asyncio
import os
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_factory_postgres as fixture


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL") and os.name == "posix", "Requires isolated PostgreSQL and Linux descriptor operations")
class StorageGovernancePostgresTests(unittest.TestCase):
    login = fixture.FactoryPostgresTests.login
    plan = fixture.FactoryPostgresTests.plan
    submit = fixture.FactoryPostgresTests.submit
    wait = fixture.FactoryPostgresTests.wait

    @classmethod
    def setUpClass(cls):
        fixture.FactoryPostgresTests.setUpClass.__func__(cls)
        cls.state = cls.app.app.state.factory
        cls.store = cls.state["store"]
        cls.storage = cls.store.storage

    @classmethod
    def tearDownClass(cls):
        fixture.FactoryPostgresTests.tearDownClass.__func__(cls)

    def setUp(self):
        self.login()
        self.tasks = []
        self.settings.storage_retention_grace_seconds = 0
        self.settings.storage_allow_purge = False

    def tearDown(self):
        self.login()
        for task in self.tasks:
            self.client.post(f"/api/factory/jobs/{task}/cancel")

    def owned(self, *, evidence=False):
        plan, _ = self.plan("sort")
        task, _ = self.submit(plan)
        self.tasks.append(task["id"])
        self.wait(task["id"], {"waiting_input"})
        path = self.storage.directory(task["id"], "owned-test-scratch", evidence=evidence)
        (path / "nested").mkdir()
        (path / "nested" / "synthetic.txt").write_bytes(b"Explicitly rebuildable fixture only\n" * 10)
        return task["id"], path

    def stop(self, task):
        response = self.client.post(f"/api/factory/jobs/{task}/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        self.wait(task, {"canceled", "failed"})

    def retention(self, path):
        response = self.client.post("/api/factory/storage/retention/plans", json={"objectId": path.name, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def action(self, plan, action):
        return self.client.post(f'/api/factory/storage/retention/plans/{plan["id"]}/{action}')

    def test_low_water_refusal_is_atomic_and_duplicate_admission_keeps_original_hold(self):
        task, path = self.owned()
        row = self.store.task(task)
        hold = self.store.sql("SELECT * FROM af_disk_holds WHERE task_id=:task", task=task)[0]
        with patch.object(self.storage, "filesystems", return_value=[{"freeBytes": 1} ]):
            replay = self.client.post("/api/factory/instances", json={"planId": row["plan_id"], "requestId": row["request_id"]})
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(replay.json()["id"], task)
            plan, _ = self.plan("Another storage admission fixture")
            request = str(uuid4())
            denied = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": request})
            self.assertEqual(denied.status_code, 507, denied.text)
            self.assertEqual(self.store.sql("SELECT 1 FROM af_tasks WHERE request_id=:id", id=request), [])
        self.assertEqual(self.store.sql("SELECT * FROM af_disk_holds WHERE task_id=:task", task=task)[0], hold)
        self.assertTrue(path.exists())

    def test_active_unknown_and_evidence_are_protected_and_owner_reads_are_scoped(self):
        task, path = self.owned()
        response = self.client.post("/api/factory/storage/retention/plans", json={"objectId": path.name, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 409)
        self.stop(task)
        self.store.sql("UPDATE af_tasks SET admission='unknown' WHERE id=:id", id=task)
        response = self.client.post("/api/factory/storage/retention/plans", json={"objectId": path.name, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 409)
        self.store.sql("UPDATE af_tasks SET admission='accepted' WHERE id=:id", id=task)
        self.login("bob")
        self.assertNotIn(path.name, self.client.get("/api/factory/storage").text)
        response = self.client.post("/api/factory/storage/retention/plans", json={"objectId": path.name, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 404)
        self.login()
        task2, path2 = self.owned(evidence=True)
        self.stop(task2)
        response = self.client.post("/api/factory/storage/retention/plans", json={"objectId": path2.name, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 409)

    def test_dry_run_quarantine_restart_read_recovery_restore_and_explicit_fixture_purge(self):
        task, path = self.owned()
        self.stop(task)
        plan = self.retention(path)
        content = (path / "nested" / "synthetic.txt").read_bytes()
        self.assertTrue(path.exists())
        original = self.storage._state
        def lose_after_move(saved, state, object_state, patch=None):
            if state == "QUARANTINED":
                raise RuntimeError("Owned fault after rename before DB receipt")
            return original(saved, state, object_state, patch)
        with patch.object(self.storage, "_state", side_effect=lose_after_move):
            with self.assertRaises(RuntimeError):
                self.action(plan, "quarantine")
        self.assertFalse(path.exists())
        response = self.client.get(f'/api/factory/storage/retention/plans/{plan["id"]}')
        self.assertEqual(response.json()["state"], "QUARANTINED", response.text)
        self.assertEqual(response.json()["reclaimedLogicalBytes"], 0)
        self.assertEqual(self.action(plan, "restore").json()["state"], "RESTORED")
        self.assertEqual((path / "nested" / "synthetic.txt").read_bytes(), content)
        plan = self.retention(path)
        self.assertEqual(self.action(plan, "quarantine").status_code, 200)
        self.assertEqual(self.action(plan, "purge").status_code, 403)
        self.settings.storage_allow_purge = True  # Generated fixture namespace only.
        self.assertEqual(self.action(plan, "purge").json()["state"], "PURGED")
        self.assertFalse((self.storage.quarantine / path.name).exists())
        self.assertEqual(self.action(plan, "purge").json()["state"], "PURGED")
        self.assertTrue(self.store.events(task))

    def test_modified_content_links_and_namespace_replacement_never_touch_foreign_directory(self):
        task, path = self.owned()
        self.stop(task)
        plan = self.retention(path)
        (path / "nested" / "synthetic.txt").write_bytes(b"Changed owned fixture")
        self.assertEqual(self.action(plan, "quarantine").status_code, 409)
        with tempfile.TemporaryDirectory() as foreign:
            keep = Path(foreign) / "unrelated.txt"
            keep.write_bytes(b"Never delete this other fixture")
            (path / "foreign").symlink_to(foreign, target_is_directory=True)
            response = self.client.post("/api/factory/storage/retention/plans", json={"objectId": path.name, "requestId": str(uuid4())})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(keep.read_bytes(), b"Never delete this other fixture")
            (path / "foreign").unlink()
            os.link(keep, path / "hardlink")
            response = self.client.post("/api/factory/storage/retention/plans", json={"objectId": path.name, "requestId": str(uuid4())})
            self.assertEqual(response.status_code, 409)
            (path / "hardlink").unlink()
            self.assertTrue(keep.exists())

    def test_unknown_admission_retains_disk_hold_across_service_reconstruction(self):
        from fastapi import HTTPException
        from agent_factory.storage_governance import StorageGovernance
        plan, _ = self.plan("sort")
        with patch.object(self.state["bridge"], "submit", side_effect=HTTPException(503, "Owned missing acknowledgement")):
            job, _ = self.submit(plan)
        self.tasks.append(job["id"])
        self.assertEqual(job["status"], "unknown")
        self.client.post(f'/api/factory/jobs/{job["id"]}/cancel')
        restored = StorageGovernance(self.store, self.state["auth"])
        value = self.client.portal.call(restored.summary, "alice")
        hold = next(row for row in value["ownerHolds"] if row["task_id"] == job["id"])
        self.assertEqual(hold["state"], "HELD")

    def test_original_plan_recovery_after_move_and_grace_protect_rebuildable_fixture(self):
        task, path = self.owned()
        self.stop(task)
        request = {"objectId": path.name, "requestId": str(uuid4())}
        plan = self.client.post("/api/factory/storage/retention/plans", json=request).json()
        self.assertEqual(self.action(plan, "quarantine").status_code, 200)
        recovered = self.client.post("/api/factory/storage/retention/plans", json=request)
        self.assertEqual(recovered.status_code, 201, recovered.text)
        self.assertEqual(recovered.json()["id"], plan["id"])
        self.assertEqual(recovered.json()["state"], "QUARANTINED")
        self.settings.storage_allow_purge = True
        self.settings.storage_retention_grace_seconds = 3600
        self.assertEqual(self.action(plan, "purge").status_code, 409)
        self.assertTrue((self.storage.quarantine / path.name / "nested" / "synthetic.txt").exists())
        path.mkdir()
        (path / "conflict.txt").write_bytes(b"New conflicting fixture must survive")
        self.assertEqual(self.action(plan, "restore").status_code, 409)
        self.assertEqual((path / "conflict.txt").read_bytes(), b"New conflicting fixture must survive")
        (path / "conflict.txt").unlink()
        path.rmdir()
        self.assertEqual(self.action(plan, "restore").status_code, 200)

    def test_partial_purge_is_only_resumed_by_explicit_owner_action(self):
        task, path = self.owned()
        self.stop(task)
        plan = self.retention(path)
        self.assertEqual(self.action(plan, "quarantine").status_code, 200)
        self.settings.storage_allow_purge = True
        original = os.unlink
        calls = []
        def lose_after_owned_unlink(name, *args, **kwargs):
            original(name, *args, **kwargs)
            calls.append(name)
            raise RuntimeError("Owned injected interruption after first unlink")
        with patch("agent_factory.storage_governance.os.unlink", side_effect=lose_after_owned_unlink):
            with self.assertRaises(RuntimeError):
                self.action(plan, "purge")
        self.assertEqual(len(calls), 1)
        target = self.storage.quarantine / path.name
        self.assertTrue(target.exists())
        result = self.client.get(f'/api/factory/storage/retention/plans/{plan["id"]}')
        self.assertEqual(result.json()["state"], "PURGING")
        self.assertTrue(target.exists(), "GET must never resume deletion")
        self.assertEqual(self.action(plan, "restore").status_code, 409)
        self.assertEqual(self.action(plan, "purge").json()["state"], "PURGED")
        self.assertFalse(target.exists())

    def test_replaced_object_and_namespace_are_refused(self):
        task, path = self.owned()
        self.stop(task)
        plan = self.retention(path)
        saved = path.with_name(path.name + "-fixture-original")
        path.rename(saved)
        try:
            path.mkdir()
            (path / "untouched.txt").write_bytes(b"Unregistered replacement fixture")
            self.assertEqual(self.action(plan, "quarantine").status_code, 409)
            self.assertEqual((path / "untouched.txt").read_bytes(), b"Unregistered replacement fixture")
            (path / "untouched.txt").unlink()
            path.rmdir()
        finally:
            saved.rename(path)
        namespace = self.storage.objects
        moved = namespace.with_name("objects-fixture-original")
        namespace.rename(moved)
        try:
            namespace.mkdir()
            self.assertEqual(self.action(plan, "quarantine").status_code, 409)
            self.assertTrue((moved / path.name / "nested" / "synthetic.txt").exists())
        finally:
            namespace.rmdir()
            moved.rename(namespace)

    def test_object_fence_prevents_parallel_mutation_and_rechecks_protection(self):
        from fastapi import HTTPException
        task, path = self.owned()
        self.stop(task)
        plan = self.retention(path)
        with self.storage._lock(path.name):
            self.assertEqual(self.action(plan, "quarantine").status_code, 409)
        original = self.storage._eligible
        calls = []
        async def protection_changed(owner, row):
            calls.append(row["id"])
            if len(calls) == 2:
                raise HTTPException(409, "Owned proof: protection changed before mutation")
            return await original(owner, row)
        with patch.object(self.storage, "_eligible", side_effect=protection_changed):
            self.assertEqual(self.action(plan, "quarantine").status_code, 409)
        self.assertEqual(len(calls), 2)
        self.assertTrue(path.exists())

    def test_upgrade_backfills_active_holds_without_adopting_legacy_files(self):
        from agent_factory.storage_governance import StorageGovernance
        task, path = self.owned()
        self.store.sql("DELETE FROM af_disk_holds WHERE task_id=:id", id=task)  # This generated fixture models the pre-upgrade schema.
        old = self.settings.workspace / "unregistered-fixture"
        old.mkdir()
        (old / "evidence.txt").write_bytes(b"Never adopt a historical path")
        service = StorageGovernance(self.store, self.state["auth"])
        hold = self.store.sql("SELECT * FROM af_disk_holds WHERE task_id=:id", id=task)[0]
        self.assertEqual(hold["state"], "HELD")
        self.assertEqual(hold["bytes"], self.settings.storage_task_reserve_bytes)
        value = self.client.portal.call(service.summary, "alice")
        self.assertNotIn("unregistered-fixture", str(value))
        self.assertEqual((old / "evidence.txt").read_bytes(), b"Never adopt a historical path")
        self.assertTrue(path.exists())

    def test_dry_run_receipt_and_audit_commit_together(self):
        task, path = self.owned()
        self.stop(task)
        request = {"objectId": path.name, "requestId": str(uuid4())}
        original = self.store.event
        def reject_audit(task_id, kind, *args, **kwargs):
            if kind == "retention_planned":
                raise RuntimeError("Owned fixture audit transaction failure")
            return original(task_id, kind, *args, **kwargs)
        with patch.object(self.store, "event", side_effect=reject_audit):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/factory/storage/retention/plans", json=request)
        self.assertFalse(self.store.sql("SELECT id FROM af_retention_plans WHERE owner_id='alice' AND request_id=:key", key=request["requestId"]))
        self.assertTrue(path.exists())
        response = self.client.post("/api/factory/storage/retention/plans", json=request)
        self.assertEqual(response.status_code, 201, response.text)
        events = [event for event in self.store.events(task) if event["type"] == "retention_planned"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["planId"], response.json()["id"])

    def test_retention_fence_fails_fast_without_starving_awaited_owner_or_root_locks(self):
        from fastapi import HTTPException
        from sqlalchemy import text

        async def concurrent():
            entered, release = asyncio.Event(), asyncio.Event()

            async def owner():
                with self.storage._lock('synthetic-fence-owner'):
                    entered.set()
                    await release.wait()
                    self.assertEqual(self.store.sql('SELECT 1 AS n')[0]['n'], 1)

            async def contender():
                await entered.wait()
                started = time.monotonic()
                try:
                    with self.assertRaises(HTTPException) as busy:
                        with self.storage._lock('synthetic-fence-contender'):
                            self.fail('A second retention connection must not be created')
                    self.assertEqual(busy.exception.status_code, 409)
                    self.assertLess(time.monotonic() - started, 1)
                    with self.store.root_lock_engine().connect() as connection:
                        self.assertEqual(connection.execute(text('SELECT 1')).scalar(), 1)
                finally:
                    release.set()
            await asyncio.wait_for(asyncio.gather(owner(), contender()), timeout=2)
        asyncio.run(concurrent())
        with self.storage._lock('synthetic-fence-recovered'):
            self.assertEqual(self.store.sql('SELECT 1 AS n')[0]['n'], 1)

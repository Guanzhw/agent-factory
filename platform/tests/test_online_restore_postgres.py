"""Bounded online exported-snapshot proof on two explicitly owned databases.

Database-backed artifacts are part of the same snapshot. External workspace,
container and credential restoration is deliberately not inferred from a dump.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, text

import test_restore_postgres as fixture


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL") and fixture.pg_tools(),
                     "Requires isolated PostgreSQL and official dump/restore tools")
class OnlineRestorePostgresTests(unittest.TestCase):
    setUp = fixture.PostgreSQLRestoreTests.setUp
    app = fixture.PostgreSQLRestoreTests.app
    close_app = fixture.PostgreSQLRestoreTests.close_app
    close_apps = fixture.PostgreSQLRestoreTests.close_apps
    login = fixture.PostgreSQLRestoreTests.login
    approved_plan = fixture.PostgreSQLRestoreTests.approved_plan
    wait_completed = fixture.PostgreSQLRestoreTests.wait_completed
    postgres_command = fixture.PostgreSQLRestoreTests.postgres_command

    def test_exported_snapshot_with_live_artifact_writes_and_uncertain_admission(self):
        client, store, state = self.app(self.source, "online-source")
        plan, _ = self.approved_plan(client, state["plan_policy"], "checksum")
        accepted = client.post("/api/factory/instances", json={"planId": plan, "requestId": uuid4().hex})
        self.assertEqual(accepted.status_code, 202)
        task = accepted.json()["id"]
        self.wait_completed(client, task)
        before = store.artifact_write(task, "confirmed-before.txt", b"Confirmed before snapshot", "text/plain")
        unknown_plan, _ = self.approved_plan(client, state["plan_policy"], "research")
        unknown, _ = store.reserve_task(store.plan(unknown_plan, "alice"), uuid4().hex)
        store.admission_unknown(unknown["id"])
        engine = create_engine(self.source.url, isolation_level="REPEATABLE READ")
        self.addCleanup(engine.dispose)
        written, failures = [], []
        begin, first, stop = threading.Event(), threading.Event(), threading.Event()
        def writer():
            try:
                if not begin.wait(10):
                    raise RuntimeError("Owned writer was not released")
                # At most 64 KiB of payload in total, no disk exhaustion.
                for index in range(64):
                    if stop.is_set():
                        break
                    receipt = store.artifact_write(task, f"after-cut-{index:03}.txt", bytes([index]) * 1024, "application/octet-stream")
                    written.append(receipt["id"])
                    first.set()
                    stop.wait(.03)
            except Exception as error:
                failures.append(type(error).__name__)
                first.set()
        worker = threading.Thread(target=writer, name="owned-online-artifact-writer", daemon=True)
        worker.start()
        try:
            with engine.connect() as snapshot, snapshot.begin():
                snapshot.execute(text("SET TRANSACTION READ ONLY"))
                snapshot_id = snapshot.execute(text("SELECT pg_export_snapshot()")).scalar_one()
                expected = snapshot.execute(text("SELECT id,content FROM af_artifacts ORDER BY id")).all()
                expected_ids = [row.id for row in expected]
                expected_hashes = {row.id: hashlib.sha256(bytes(row.content)).hexdigest() for row in expected}
                begin.set()
                self.assertTrue(first.wait(10))
                self.assertFalse(failures, failures)
                at_dump_start = len(written)
                dump = Path(self.directory.name) / "owned-online.dump"
                binaries = fixture.pg_tools()
                self.postgres_command(binaries[0], self.source,
                    ["--format=custom", "--no-owner", "--no-acl", "--snapshot", snapshot_id, "--file", str(dump)])
                commits_during_dump = len(written) - at_dump_start
                self.assertGreater(commits_during_dump, 0, "Actual commits must overlap pg_dump")
                # Original repeatable-read connection remains open until dump completes.
                self.assertEqual(snapshot.execute(text("SELECT id FROM af_artifacts ORDER BY id")).scalars().all(), expected_ids)
        finally:
            stop.set()
            begin.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures, failures)
        self.assertTrue(written)
        self.postgres_command(binaries[1], self.target,
            ["--no-owner", "--no-acl", "--exit-on-error", str(dump)])
        restored_client, restored, _ = self.app(self.target, "online-target-empty-workspace")
        rows = restored.sql("SELECT id,content FROM af_artifacts ORDER BY id")
        self.assertEqual([row["id"] for row in rows], expected_ids)
        self.assertEqual({row["id"]: hashlib.sha256(bytes(row["content"])).hexdigest() for row in rows}, expected_hashes)
        self.assertIn(before["id"], expected_ids)
        self.assertFalse(set(written) & set(expected_ids))
        recovered = restored.task(unknown["id"], "alice")
        self.assertEqual(recovered["admission"], "unknown")
        self.assertIsNone(recovered["run_id"])
        self.assertFalse(recovered["terminal"])
        self.assertEqual(restored.sql("SELECT state FROM af_disk_holds WHERE task_id=:id", id=unknown["id"])[0]["state"], "HELD")
        original_run = store.task(task)["run_id"]
        self.assertEqual(restored.task(task)["run_id"], original_run)
        self.assertEqual(restored.native_db.get_job(original_run)["status"], "completed")
        self.login(restored_client)
        replay = restored_client.post("/api/factory/instances", json={"planId": unknown_plan, "requestId": unknown["request_id"]})
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["id"], unknown["id"])
        self.assertIsNone(restored.task(unknown["id"])["run_id"], "Recovery must not resubmit UNKNOWN")
        evidence = {"schema": 1, "snapshot": "exported repeatable-read snapshot", "confirmedBeforeCutRestored": len(expected_ids),
            "confirmedAfterCutExcluded": len(written), "commitsDuringDump": commits_during_dump,
            "unknownAdmissionHeld": True, "duplicateRunCreated": False, "externalWorkspaceRestored": False,
            "PITRProven": False, "productionRPOOrRTOProven": False}
        destination = os.getenv("FACTORY_ONLINE_RESTORE_EVIDENCE")
        if destination:
            Path(destination).write_text(json.dumps(evidence, indent=2) + "\n")

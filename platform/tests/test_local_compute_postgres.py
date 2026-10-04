# pyright: reportMissingImports=false
"""Actual Factory/Postgres service + actual owned workspace allocation."""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.local_compute import LocalWorkspaceProvider
from agent_factory.resources import PersistentResourceService
import test_resource_capacity_postgres as fixtures


@unittest.skipUnless(os.name == "posix" and os.getenv("FACTORY_TEST_DATABASE_URL"),
                     "Requires POSIX real workspace and isolated PostgreSQL")
class LocalComputePostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ResourceCapacityPostgresTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.start()
        self.root = Path(self.fixture.workspace.name) / "allocated"
        self.root.mkdir()
        self.provider = LocalWorkspaceProvider(self.fixture.store, self.root)
        self.targets = {key: replace(target, provider=self.provider, synthetic_fixture=False)
                        for key, target in self.fixture.targets.items()}
        self.service = PersistentResourceService(self.fixture.store, self.fixture.auth, self.targets)
        self.task = self.fixture.task("alice")

    def allocate(self):
        return asyncio.run(self.service.allocate("alice", "first-ref", self.task, str(uuid4()), self.fixture.limits()))

    def reopened(self, root=None):
        provider = LocalWorkspaceProvider(self.fixture.other.store, root or self.root)
        targets = {key: replace(target, provider=provider) for key, target in self.targets.items()}
        return PersistentResourceService(self.fixture.other.store, self.fixture.auth, targets)

    def test_actual_pg_journal_native_task_restart_cancel_and_release(self):
        lease = self.allocate()
        self.assertEqual(lease["state"], "ACCEPTED")
        path = self.root / lease["id"]
        self.assertTrue((path / ".allocation.json").is_file())
        self.assertEqual(len(self.fixture.store.sql("SELECT id FROM af_compute_allocations")), 1)
        restarted = self.reopened()
        self.assertEqual(asyncio.run(restarted.reconcile("alice", lease["id"]))["state"], "ACCEPTED")
        asyncio.run(restarted.cancel("alice", lease["id"]))
        cancelled = asyncio.run(restarted.reconcile("alice", lease["id"]))
        self.assertEqual(cancelled["state"], "CANCEL_CONFIRMED")
        self.assertTrue(cancelled["capacityHeld"])
        self.assertTrue(path.exists())
        released = asyncio.run(restarted.reclaim("alice", lease["id"]))
        self.assertEqual(released["state"], "RECLAIMED")
        self.assertFalse(released["capacityHeld"])
        self.assertFalse(path.exists())
        self.assertEqual(asyncio.run(restarted.reclaim("alice", lease["id"]))["state"], "RECLAIMED")

    def test_unknown_filesystem_ack_reconciles_original_without_new_allocation(self):
        with patch("agent_factory.local_compute.os.fsync", side_effect=OSError("synthetic lost filesystem ack")):
            lease = self.allocate()
        self.assertEqual(lease["state"], "UNKNOWN")
        self.assertTrue(lease["capacityHeld"])
        restarted = self.reopened()
        with patch("agent_factory.local_compute.os.mkdir", side_effect=AssertionError("must not allocate again")):
            self.assertEqual(asyncio.run(restarted.reconcile("alice", lease["id"]))["state"], "ACCEPTED")
        self.assertEqual(len(self.fixture.store.sql("SELECT id FROM af_compute_allocations")), 1)
        asyncio.run(restarted.cancel("alice", lease["id"]))
        asyncio.run(restarted.reconcile("alice", lease["id"]))
        self.assertEqual(asyncio.run(restarted.reclaim("alice", lease["id"]))["state"], "RECLAIMED")

    def test_foreign_workspace_and_rebound_provider_never_release_original(self):
        lease = self.allocate()
        wrong = self.root.parent / "different-root"; wrong.mkdir()
        with self.assertRaises(HTTPException) as caught:
            self.reopened(wrong).inspect("alice", lease["id"])
        self.assertEqual(caught.exception.status_code, 409)
        asyncio.run(self.service.cancel("alice", lease["id"]))
        asyncio.run(self.service.reconcile("alice", lease["id"]))
        foreign = self.root / lease["id"] / "runtime-owned.txt"
        foreign.write_text("must retain")
        held = asyncio.run(self.service.reclaim("alice", lease["id"]))
        self.assertTrue(held["capacityHeld"])
        self.assertNotEqual(held["state"], "RECLAIMED")
        self.assertEqual(foreign.read_text(), "must retain")
        self.assertTrue(asyncio.run(self.reopened().reconcile("alice", lease["id"]))["capacityHeld"])

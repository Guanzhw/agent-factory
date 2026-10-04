"""Real disposable directories + SQLite journal; no process/network allocation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text

from agent_factory.local_compute import LocalWorkspaceProvider

LIMITS = {"cpu": 1, "memoryMb": 64, "diskMb": 1, "seconds": 10}
FP = "a" * 64


class Backend:
    revision = "synthetic-runtime-v1"
    def __init__(self):
        self.calls = []; self.state = "RUNNING"; self.lost = False; self.released = False
    def allocate(self, record):
        self.calls.append("allocate")
        if self.lost: raise OSError("synthetic lost acknowledgement")
        return self.inspect(record)
    def inspect(self, record):
        return {"state": self.state, "allStopped": self.state == "CANCEL_CONFIRMED", "released": self.released}
    def cancel(self, record):
        self.calls.append("cancel"); self.state = "CANCEL_CONFIRMED"
        return self.inspect(record)
    def reclaim(self, record):
        self.calls.append("reclaim"); self.released = True
        return self.inspect(record)


@unittest.skipUnless(os.name == "posix", "Descriptor-pinned POSIX workspace backend")
class LocalComputeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.base = Path(folder.name); self.root = self.base / "owned"; self.root.mkdir()
        engine = create_engine("sqlite:///" + str(self.base / "journal.sqlite"))
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE af_compute_allocations(id TEXT PRIMARY KEY,owner_id TEXT,body TEXT)"))
        self.store = SimpleNamespace(engine=engine)
        self.provider = LocalWorkspaceProvider(self.store, self.root)

    async def test_real_directory_restart_cancel_and_positive_release_are_separate(self):
        first = await self.provider.allocate("lease1", "alice", FP, LIMITS)
        self.assertEqual(first["state"], "ACCEPTED")
        self.assertTrue((self.root / "lease1" / ".allocation.json").is_file())
        self.assertFalse(first["enforcement"]["kernelQuotas"])
        self.assertNotIn(str(self.root), json.dumps(first))
        reopened = LocalWorkspaceProvider(self.store, self.root)
        self.assertEqual(reopened.configuration_fingerprint, self.provider.configuration_fingerprint)
        self.assertEqual(await reopened.allocate("lease1", "alice", FP, LIMITS), first)
        cancelled = await reopened.cancel("lease1", "alice")
        self.assertTrue(cancelled["capacityHeld"])
        self.assertFalse(cancelled["released"])
        self.assertTrue((self.root / "lease1").exists())
        released = await reopened.reclaim("lease1", "alice")
        self.assertEqual(released["state"], "RECLAIMED")
        self.assertTrue(released["released"])
        self.assertFalse((self.root / "lease1").exists())
        self.assertEqual(await reopened.reclaim("lease1", "alice"), released)

    async def test_lost_allocate_ack_never_replays_and_new_id_cannot_evade_hold(self):
        with patch("agent_factory.local_compute.os.fsync", side_effect=OSError("lost fs ack")):
            result = await self.provider.allocate("lease1", "alice", FP, LIMITS)
        self.assertEqual(result["state"], "UNKNOWN")
        reopened = LocalWorkspaceProvider(self.store, self.root)
        self.assertEqual((await reopened.allocate("lease1", "alice", FP, LIMITS))["state"], "UNKNOWN")
        with self.assertRaises(ValueError): await reopened.allocate("lease2", "alice", FP, LIMITS)
        self.assertEqual((await reopened.inspect("lease1", "alice"))["state"], "ACCEPTED")
        await reopened.cancel("lease1", "alice")
        self.assertEqual((await reopened.reclaim("lease1", "alice"))["state"], "RECLAIMED")

    async def test_journal_precedes_filesystem_and_absence_never_releases_unknown(self):
        with patch("agent_factory.local_compute.os.mkdir", side_effect=OSError("fixture failure")):
            self.assertEqual((await self.provider.allocate("lease1", "alice", FP, LIMITS))["state"], "UNKNOWN")
        result = await LocalWorkspaceProvider(self.store, self.root).inspect("lease1", "alice")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertTrue(result["capacityHeld"])
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(ValueError): await self.provider.reclaim("lease1", "alice")

    async def test_owner_fingerprint_limits_and_path_rebinding_refused(self):
        await self.provider.allocate("lease1", "alice", FP, LIMITS)
        for operation in (self.provider.inspect("lease1", "bob"),
                          self.provider.allocate("lease1", "alice", "b" * 64, LIMITS),
                          self.provider.allocate("../escape", "alice", FP, LIMITS),
                          self.provider.allocate("lease1", "alice", FP, {**LIMITS, "cpu": 2})):
            with self.assertRaises(ValueError): await operation
        other = self.base / "other"; other.mkdir()
        changed = LocalWorkspaceProvider(self.store, other)
        self.assertNotEqual(changed.configuration_fingerprint, self.provider.configuration_fingerprint)
        with self.assertRaises(ValueError): await changed.inspect("lease1", "alice")
        link = self.base / "link"; link.symlink_to(self.root)
        with self.assertRaises(OSError): LocalWorkspaceProvider(self.store, link)
        with self.assertRaises(ValueError):
            await LocalWorkspaceProvider(self.store, self.root, Backend()).inspect("lease1", "alice")

    async def test_nonprovider_files_symlinks_hardlinks_and_directories_are_never_deleted(self):
        for index, kind in enumerate(("file", "symlink", "hardlink", "directory")):
            lease = "lease" + str(index); fp = str(index) * 64
            await self.provider.allocate(lease, "alice", fp, LIMITS)
            await self.provider.cancel(lease, "alice")
            extra = self.root / lease / "foreign"
            target = self.base / ("source" + str(index)); target.write_text("retain")
            if kind == "file": extra.write_text("retain")
            elif kind == "symlink": extra.symlink_to(target)
            elif kind == "hardlink": os.link(target, extra)
            else: extra.mkdir()
            result = await self.provider.reclaim(lease, "alice")
            self.assertFalse(result["released"])
            self.assertTrue(result["capacityHeld"])
            self.assertTrue(extra.exists())
            self.assertEqual(target.read_text(), "retain")

    async def test_lost_release_is_read_reconciled_without_second_effect(self):
        await self.provider.allocate("lease1", "alice", FP, LIMITS)
        await self.provider.cancel("lease1", "alice")
        with patch("agent_factory.local_compute.os.rmdir", side_effect=OSError("lost cleanup")):
            result = await self.provider.reclaim("lease1", "alice")
        self.assertFalse(result["released"])
        result = await self.provider.inspect("lease1", "alice")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertTrue(result["capacityHeld"])
        (self.root / "lease1").rmdir()
        self.assertTrue((await self.provider.inspect("lease1", "alice"))["released"])

    async def test_concurrent_identical_reservations_allocate_once(self):
        def allocate(_):
            return asyncio.run(LocalWorkspaceProvider(self.store, self.root).allocate("lease1", "alice", FP, LIMITS))
        original = os.mkdir
        with patch("agent_factory.local_compute.os.mkdir", wraps=original) as mkdir:
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(allocate, range(3)))
        self.assertEqual(len(results), 3)
        self.assertEqual(mkdir.call_count, 1)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    async def test_allocation_cancel_release_cannot_overtake_pending_filesystem_effect(self):
        entered, proceed = threading.Event(), threading.Event()
        original = os.mkdir
        def delayed(*args, **kwargs):
            entered.set()
            if not proceed.wait(2): raise TimeoutError("fixture latch")
            return original(*args, **kwargs)
        other = LocalWorkspaceProvider(self.store, self.root)
        with patch("agent_factory.local_compute.os.mkdir", side_effect=delayed):
            allocation = asyncio.create_task(self.provider.allocate("lease1", "alice", FP, LIMITS))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            cancel = asyncio.create_task(other.cancel("lease1", "alice"))
            await asyncio.sleep(.03)
            self.assertFalse(cancel.done())
            proceed.set()
            self.assertEqual((await allocation)["state"], "ACCEPTED")
            self.assertEqual((await cancel)["state"], "CANCEL_CONFIRMED")
        result = await other.reclaim("lease1", "alice")
        self.assertTrue(result["released"])
        self.assertFalse((self.root / "lease1").exists())

    async def test_symlink_replacement_of_allocated_namespace_never_deletes_target(self):
        await self.provider.allocate("lease1", "alice", FP, LIMITS)
        await self.provider.cancel("lease1", "alice")
        original = self.root / "lease1"
        original.rename(self.root / "held-original")
        foreign = self.base / "foreign"; foreign.mkdir(); (foreign / "keep").write_text("retain")
        original.symlink_to(foreign)
        self.assertEqual((await self.provider.inspect("lease1", "alice"))["state"], "UNKNOWN")
        with self.assertRaises(ValueError): await self.provider.reclaim("lease1", "alice")
        self.assertEqual((foreign / "keep").read_text(), "retain")
        self.assertTrue((self.root / "held-original" / ".allocation.json").exists())

    async def test_guard_rechecks_authority_after_waiting_for_root_lock(self):
        allowed = True
        calls = []
        def guard():
            calls.append("guard")
            if not allowed: raise PermissionError("fixture revoked")
        with self.provider._operation_lock():
            task = asyncio.create_task(self.provider.allocate_guarded("lease1", "alice", FP, LIMITS, before_effect=guard))
            await asyncio.sleep(.03)
            self.assertEqual(calls, [])
            allowed = False
        with self.assertRaises(PermissionError): await task
        self.assertEqual(calls, ["guard"])
        self.assertFalse((self.root / "lease1").exists())
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM af_compute_allocations")).scalar(), 0)

    async def test_cancelled_waiting_allocator_never_creates_late_workspace(self):
        finished = threading.Event()
        original = self.provider._guarded_allocation
        calls = []
        def observed(*args):
            try: return original(*args)
            finally: finished.set()
        with patch.object(self.provider, "_guarded_allocation", side_effect=observed):
            with self.provider._operation_lock():
                task = asyncio.create_task(self.provider.allocate_guarded("lease1", "alice", FP, LIMITS,
                    before_effect=lambda: calls.append("guard")))
                await asyncio.sleep(.03)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            self.assertTrue(await asyncio.to_thread(finished.wait, 2))
        self.assertEqual(calls, [])
        self.assertFalse((self.root / "lease1").exists())
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM af_compute_allocations")).scalar(), 0)

    async def test_async_guard_cannot_bypass_synchronous_authority_contract(self):
        async def incorrect_guard():
            raise PermissionError("never silently skip")
        with self.assertRaises(ValueError):
            await self.provider.allocate_guarded("lease1", "alice", FP, LIMITS, before_effect=incorrect_guard)
        self.assertFalse((self.root / "lease1").exists())
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM af_compute_allocations")).scalar(), 0)

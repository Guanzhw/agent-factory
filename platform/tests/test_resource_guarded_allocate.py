# pyright: reportMissingImports=false
"""Offline allocation authority callback after a controlled provider wait boundary."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from fastapi import HTTPException

from agent_factory.resources import ComputePool, PersistentResourceService, RemoteTarget
from test_resources_contract import AuthFixture, DiskStoreFixture


class CurrentTaskStore(DiskStoreFixture):
    def task(self, task_id, owner=None):
        value = super().task(task_id, owner)
        return {**value, **json.loads(value["body"])}


class GuardedProvider:
    def __init__(self):
        self.wait_change = lambda: None
        self.entered = self.callbacks = self.effects = self.legacy_calls = 0
        self.denied_status = None
        self.capacity_namespace: str | None = None

    async def inspect(self, lease_id, owner):
        raise AssertionError("No reconciliation is requested in this fixture")

    async def cancel(self, lease_id, owner):
        raise AssertionError("No cancellation effect is requested in this fixture")

    async def reclaim(self, lease_id, owner):
        raise AssertionError("No reclaim effect is requested in this fixture")

    async def allocate(self, lease_id, owner, fingerprint, limits):
        self.legacy_calls += 1
        raise AssertionError("Guarded provider must not fall back to unguarded allocation")

    async def allocate_guarded(self, lease_id, owner, fingerprint, limits, *, before_effect):
        self.entered += 1
        # Deterministic stand-in for changes during an awaited provider lock.
        self.wait_change()
        self.callbacks += 1
        try:
            before_effect()
        except HTTPException as error:
            self.denied_status = error.status_code
            raise
        self.effects += 1
        return {"leaseId": lease_id, "ownerId": owner, "fingerprint": fingerprint, "state": "RUNNING"}


class GuardedResourceAllocationTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, pooled):
        directory = tempfile.TemporaryDirectory(prefix="guarded-resource-")
        self.addCleanup(directory.cleanup)
        store = CurrentTaskStore(Path(directory.name) / "fixture.sqlite")
        self.addCleanup(store.engine.dispose)
        auth, provider = AuthFixture(), GuardedProvider()
        pool = ComputePool("controlled-pool", 2, 2048, 1024) if pooled else None
        target = RemoteTarget("Controlled allocation", "compute", frozenset({"alice"}),
            provider=provider, synthetic_fixture=True, capacity_pool=pool)
        service = PersistentResourceService(store, auth, {"compute-ref": target})
        return store, auth, provider, target, service, store.add_task("alice")

    async def run_case(self, change, *, pooled, expected_status=None):
        store, auth, provider, target, service, task = self.fixture(pooled)
        def change_after_wait():
            if change == "revoke":
                auth.revoked.add("alice")
            elif change == "cancel":
                store.sql("UPDATE fixture_tasks SET body=:body WHERE id=:id",
                    body=json.dumps({"cancel_requested": True}), id=task)
            elif change == "target":
                service.targets["compute-ref"] = replace(target, configuration_revision="changed")
            elif change == "pool":
                service.targets["compute-ref"] = replace(target,
                    capacity_pool=ComputePool("controlled-pool", 1, 2048, 1024))
            elif change == "namespace":
                provider.capacity_namespace = "a" * 64
        provider.wait_change = change_after_wait
        lease = await service.allocate("alice", "compute-ref", task, "one-request",
            {"cpu": 1, "memoryMb": 512, "diskMb": 256, "seconds": 30})
        self.assertEqual((provider.entered, provider.callbacks, provider.legacy_calls), (1, 1, 0))
        self.assertEqual(provider.denied_status, expected_status)
        self.assertEqual(provider.effects, 0 if expected_status else 1)
        self.assertEqual(lease["state"], "UNKNOWN" if expected_status else "RUNNING")
        self.assertTrue(lease["capacityHeld"])
        rows = store.sql("SELECT body FROM af_leases")
        self.assertEqual(len(rows), 1)
        persisted = json.loads(rows[0]["body"])
        self.assertEqual(persisted["id"], lease["id"])
        self.assertEqual(persisted["state"], lease["state"])
        self.assertTrue(persisted["capacityHeld"])
        # Restore only fixture observations to prove the already committed
        # request is a read on retry; it must never issue a second allocation.
        auth.revoked.clear()
        service.targets["compute-ref"] = target
        if change == "namespace":
            provider.capacity_namespace = None
        if change == "cancel":
            with self.assertRaises(HTTPException) as stopped:
                await service.allocate("alice", "compute-ref", task, "one-request",
                    {"cpu": 1, "memoryMb": 512, "diskMb": 256, "seconds": 30})
            self.assertEqual(stopped.exception.status_code, 409)
        else:
            repeated = await service.allocate("alice", "compute-ref", task, "one-request",
                {"cpu": 1, "memoryMb": 512, "diskMb": 256, "seconds": 30})
            self.assertEqual(repeated["id"], lease["id"])
        self.assertEqual((provider.entered, provider.callbacks), (1, 1))

    async def test_normal_guarded_path_calls_before_effect_once_with_or_without_pool(self):
        for pooled in (False, True):
            with self.subTest(pooled=pooled):
                await self.run_case("none", pooled=pooled)

    async def test_revocation_during_provider_wait_blocks_effect(self):
        for pooled in (False, True):
            with self.subTest(pooled=pooled):
                await self.run_case("revoke", pooled=pooled, expected_status=403)

    async def test_task_cancellation_during_provider_wait_blocks_effect(self):
        for pooled in (False, True):
            with self.subTest(pooled=pooled):
                await self.run_case("cancel", pooled=pooled, expected_status=409)

    async def test_target_revision_replacement_during_wait_blocks_effect(self):
        for pooled in (False, True):
            with self.subTest(pooled=pooled):
                await self.run_case("target", pooled=pooled, expected_status=409)

    async def test_pool_capacity_replacement_during_wait_blocks_effect(self):
        await self.run_case("pool", pooled=True, expected_status=409)

    async def test_provider_namespace_change_during_wait_blocks_effect(self):
        await self.run_case("namespace", pooled=True, expected_status=409)


if __name__ == "__main__":
    unittest.main()

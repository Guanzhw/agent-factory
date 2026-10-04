"""Shared compute-pool admission using synthetic providers and durable SQLite.

This checks arithmetic/lifecycle contracts, not PostgreSQL locking or OS quotas.
"""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.resources import ComputePool, PersistentResourceService, RemoteTarget
from agent_factory.store import canonical
from test_resources_contract import AuthFixture, ComputeProviderFixture, DiskStoreFixture


class ComputePoolDefinitionTests(unittest.TestCase):
    def test_exact_positive_integer_caps_and_bounded_pool_identity(self):
        valid = dict(pool_id='department-pool', cpu=32, memory_mb=65536, disk_mb=102400,
                     max_leases=20, max_owner_leases=2)
        pool = ComputePool(**valid)
        with self.assertRaises(FrozenInstanceError):
            setattr(pool, 'cpu', 64)
        for field in ('cpu', 'memory_mb', 'disk_mb', 'max_leases', 'max_owner_leases'):
            for bad in (True, False, 0, -1, 1.5, '2', None):
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    ComputePool(**{**valid, field: bad})
        with self.assertRaises(ValueError):
            ComputePool(**{**valid, "max_leases": 1, "max_owner_leases": 2})
        for bad in ('', 'contains spaces', '../pool', 'x' * 129, None, True):
            with self.subTest(pool_id=bad), self.assertRaises(ValueError):
                ComputePool(**{**valid, 'pool_id': bad})

    def test_pool_only_applies_to_compute_targets(self):
        pool = ComputePool('pool', 2, 2048, 1024)
        for axis in ('runtime', 'a2a'):
            with self.subTest(axis=axis), self.assertRaises(ValueError):
                RemoteTarget('Fixture', axis, frozenset({'alice'}), base_url='http://127.0.0.1:1',
                             synthetic_fixture=True, capacity_pool=pool)
        with self.assertRaises(ValueError):
            RemoteTarget('Fixture', 'compute', frozenset({'alice'}), capacity_pool={'cpu': 2})


class ResourceCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'resources.sqlite'
        self.store = DiskStoreFixture(self.path)
        self.addCleanup(self.store.engine.dispose)
        self.auth = AuthFixture()
        self.provider = ComputeProviderFixture()
        self.pool = ComputePool('shared-pool', 8, 8192, 8192, max_leases=8, max_owner_leases=4)

    def isolated_store(self):
        self.store = DiskStoreFixture(Path(self.temp.name) / (str(uuid4()) + ".sqlite"))
        self.addCleanup(self.store.engine.dispose)

    def target(self, pool=None, **changes):
        return RemoteTarget('Synthetic compute', 'compute', frozenset({'alice', 'bob'}),
            provider=self.provider, synthetic_fixture=True, max_leases=20,
            max_cpu=8, max_memory_mb=8192, max_disk_mb=8192, max_seconds=300,
            capacity_pool=pool, **changes)

    def service(self, pool=None):
        target = self.target(self.pool if pool is None else pool)
        return PersistentResourceService(self.store, self.auth, {'first': target, 'alias': target})

    async def allocate(self, service, *, owner='alice', ref='first', limits=None, task=None, request=None):
        return await service.allocate(owner, ref, task or self.store.add_task(owner), request or str(uuid4()),
            limits or {'cpu': 1, 'memoryMb': 1024, 'diskMb': 1024, 'seconds': 30})

    async def denied(self, service, expected=429, **kwargs):
        before = self.provider.allocations
        with self.assertRaises(HTTPException) as raised:
            await self.allocate(service, **kwargs)
        self.assertEqual(raised.exception.status_code, expected)
        self.assertEqual(self.provider.allocations, before, 'Denied admission must not invoke provider')

    async def test_cpu_memory_and_disk_sum_cross_owner_and_reference(self):
        for field, name in (('cpu', 'cpu'), ('memory_mb', 'memoryMb'), ('disk_mb', 'diskMb')):
            with self.subTest(dimension=field):
                self.isolated_store()
                pool = replace(self.pool, pool_id='pool-' + field, **{field: 2 if field == 'cpu' else 2048})
                service = self.service(pool)
                first = {'cpu': 1, 'memoryMb': 1024, 'diskMb': 1024, 'seconds': 30}
                await self.allocate(service, limits=first)
                over = {**first, name: 2 if name == 'cpu' else 2048}
                await self.denied(service, owner='bob', ref='alias', limits=over)

    async def test_pool_and_per_owner_lease_caps_are_independent(self):
        service = self.service(replace(self.pool, max_leases=2, max_owner_leases=1))
        await self.allocate(service)
        await self.denied(service, ref='alias')
        await self.allocate(service, owner='bob', ref='alias')
        await self.denied(service, owner='bob')
        self.assertEqual(self.provider.allocations, 2)
        self.isolated_store()
        service = self.service(replace(self.pool, max_leases=2, max_owner_leases=2))
        await self.allocate(service)
        await self.allocate(service, owner='bob', ref='alias')
        # Owner has one remaining slot, but the shared pool has none.
        await self.denied(service)

    async def test_all_unreleased_states_and_expired_deadline_retain_capacity(self):
        states = ('RESERVED', 'ACCEPTED', 'RUNNING', 'PAUSED', 'UNKNOWN', 'COMPLETED',
                  'FAILED', 'CANCEL_CONFIRMED', 'CANCEL_REQUESTED', 'RECLAIMING')
        for state in states:
            with self.subTest(state=state):
                self.isolated_store()
                service = self.service(replace(self.pool, pool_id='pool-' + state, max_leases=1, max_owner_leases=1))
                lease = await self.allocate(service)
                body = service._update('alice', lease['id'], state, {'deadlineAt': '2000-01-01T00:00:00+00:00'})
                self.assertTrue(body['capacityHeld'])
                self.assertTrue(service.inspect('alice', lease['id'])['expired'])
                await self.denied(service, owner='bob', ref='alias')

    async def test_only_confirmed_provider_release_restores_shared_capacity(self):
        service = self.service(replace(self.pool, max_leases=1, max_owner_leases=1))
        lease = await self.allocate(service)
        service._update('alice', lease['id'], 'COMPLETED')
        await self.denied(service, owner='bob', ref='alias')
        self.provider.release_confirmed = False
        await service.reclaim('alice', lease['id'])
        await self.denied(service, owner='bob', ref='alias')
        self.provider.release_confirmed = True
        released = await service.reconcile('alice', lease['id'])
        self.assertEqual(released['state'], 'RECLAIMED')
        self.assertFalse(released['capacityHeld'])
        self.provider.release_confirmed = False
        await self.allocate(service, owner='bob', ref='alias')
        self.assertEqual(self.provider.allocations, 2)

    async def test_restart_idempotency_keeps_original_unknown_and_pool_snapshot(self):
        service = self.service()
        task, request = self.store.add_task(), str(uuid4())
        self.provider.lose_ack = True
        lease = await self.allocate(service, task=task, request=request)
        self.assertEqual(lease['state'], 'UNKNOWN')
        self.assertEqual(lease['poolId'], self.pool.pool_id)
        self.assertEqual(lease['poolLimits'], {'cpu': 8, 'memoryMb': 8192, 'diskMb': 8192,
                                             'maxLeases': 8, 'maxOwnerLeases': 4})
        self.assertRegex(lease['poolFingerprint'], r'^[a-f0-9]{64}$')
        reopened = DiskStoreFixture(self.path)
        self.addCleanup(reopened.engine.dispose)
        other = PersistentResourceService(reopened, self.auth, service.targets)
        repeated = await self.allocate(other, task=task, request=request)
        self.assertEqual(repeated['id'], lease['id'])
        self.assertEqual(repeated['poolFingerprint'], lease['poolFingerprint'])
        self.assertEqual(self.provider.allocations, 1)
        await self.denied(other, expected=409, task=task, ref='alias')

    async def test_conflicting_pool_definitions_fail_during_registry_construction(self):
        with self.assertRaises(ValueError):
            PersistentResourceService(self.store, self.auth, {'first': self.target(self.pool),
                'alias': self.target(replace(self.pool, cpu=4))})
        self.assertEqual(self.provider.allocations, 0)

    async def test_restart_shrink_pool_rebinding_and_removal_never_hide_old_hold(self):
        service = self.service()
        lease = await self.allocate(service)
        for changed in (replace(self.pool, cpu=4), replace(self.pool, pool_id='replacement'), None):
            with self.subTest(pool=changed):
                restarted = PersistentResourceService(self.store, self.auth,
                    {'first': self.target(changed), 'alias': self.target(changed)})
                await self.denied(restarted, expected=409)
                held = restarted.inspect('alice', lease['id'])
                self.assertTrue(held['capacityHeld'])
                self.assertEqual(held['poolId'], self.pool.pool_id)
        # A new alias of the same pool cannot evade a persisted definition mismatch.
        restarted = PersistentResourceService(self.store, self.auth,
            {'new-alias': self.target(replace(self.pool, memory_mb=4096))})
        await self.denied(restarted, expected=409, ref='new-alias', owner='bob')

    async def test_legacy_unpooled_reference_cap_and_idempotency_remain(self):
        target = replace(self.target(), max_leases=1)
        service = PersistentResourceService(self.store, self.auth, {'first': target, 'alias': target})
        task, request = self.store.add_task(), str(uuid4())
        lease = await self.allocate(service, task=task, request=request)
        self.assertEqual((await self.allocate(service, task=task, request=request))['id'], lease['id'])
        self.assertIsNone(lease.get('poolId'))
        await self.denied(service, owner='bob')
        # Historical unpooled semantics remain per-reference, with no invented pool.
        await self.allocate(service, owner='bob', ref='alias')
        self.assertEqual(self.provider.allocations, 2)

    async def test_body_capacityheld_false_cannot_override_unreleased_state(self):
        service = self.service(replace(self.pool, max_leases=1, max_owner_leases=1))
        lease = await self.allocate(service)
        altered = {**lease, 'capacityHeld': False}
        self.store.sql('UPDATE af_leases SET body=:body WHERE id=:id', body=canonical(altered), id=lease['id'])
        await self.denied(service, owner='bob', ref='alias')

    async def test_provider_namespace_rejects_conflicting_pool_aliases(self):
        self.provider.capacity_namespace = "a" * 64
        for alias_pool in (replace(self.pool, pool_id="other-pool"), None):
            with self.subTest(pool=alias_pool), self.assertRaises(ValueError):
                PersistentResourceService(self.store, self.auth, {
                    "first": self.target(self.pool), "alias": self.target(alias_pool)})
        self.assertEqual(self.provider.allocations, 0)

    async def test_provider_namespace_survives_restart_and_reference_rename(self):
        self.provider.capacity_namespace = "a" * 64
        service = self.service()
        lease = await self.allocate(service)
        self.assertEqual(lease["providerNamespace"], "a" * 64)
        for changed in (replace(self.pool, pool_id="other-pool"), None):
            with self.subTest(pool=changed):
                restarted = PersistentResourceService(self.store, self.auth,
                    {"renamed-ref": self.target(changed)})
                await self.denied(restarted, expected=409, ref="renamed-ref", owner="bob")
        # Keep the old reference installed for explicitly authorized cleanup.
        held = service.inspect("alice", lease["id"])
        self.assertTrue(held["capacityHeld"])
        service._update("alice", lease["id"], "COMPLETED")
        self.provider.release_confirmed = True
        released = await service.reclaim("alice", lease["id"])
        self.assertEqual(released["state"], "RECLAIMED")
        restarted = PersistentResourceService(self.store, self.auth,
            {"renamed-ref": self.target(replace(self.pool, pool_id="other-pool"))})
        await self.allocate(restarted, ref="renamed-ref", owner="bob")

    async def test_initial_cancel_refuses_reservation_before_provider_dispatch(self):
        service = self.service()
        task_id = self.store.add_task()
        original = self.store.task
        def canceled_task(identifier, owner=None):
            return {**original(identifier, owner), "cancel_requested": True}
        with patch.object(self.store, "task", side_effect=canceled_task):
            await self.denied(service, expected=409, task=task_id)
        self.assertEqual(self.store.sql("SELECT * FROM af_leases"), [])
        self.assertEqual(self.provider.allocations, 0)

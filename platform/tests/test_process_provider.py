"""SQLite admission plus real disposable directories; process effects mocked."""
import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, text

from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
from agent_factory.process_provider import ProcessResourceProvider
from agent_factory.store import canonical


class FakeProcess:
    records = {}
    created = 0
    launched = 0
    fail_create = False
    fail_launch_ack = False
    create_observer: Mock | None = None

    def __init__(self, path):
        self.path = str(path)

    @classmethod
    def create(cls, path, *, owner_id, task_id, request_id, spec, limits):
        if cls.create_observer:
            cls.create_observer()
        cls.created += 1
        path.write_text('synthetic custody')
        path.chmod(0o600)
        if cls.fail_create:
            raise OSError('synthetic acknowledgement loss')
        cls.records[str(path)] = {"id": 'custody-fixture', "ownerId": owner_id, "taskId": task_id,
            "requestId": request_id, "limits": asdict(limits), "state": 'PREPARED', "stoppedProof": False,
            "specSha256": hashlib.sha256(json.dumps({"spec": asdict(spec), "limits": asdict(limits)},
                sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "identitySha256": 'a' * 64, "rootPin": {"fixture": True}}
        return cls(path)

    def inspect(self, *, owner_id):
        value = dict(self.records[self.path])
        if value['ownerId'] != owner_id:
            raise ValueError('synthetic owner mismatch')
        if value.get('stoppedProof'):
            value.setdefault('stopReceipt', {'kind': 'original-group-stopped'})
        return value

    def launch(self, *, owner_id, before_effect):
        before_effect()
        type(self).launched += 1
        self.records[self.path]['state'] = 'RUNNING'
        if self.fail_launch_ack:
            raise OSError('synthetic acknowledgement loss')
        return self.inspect(owner_id=owner_id)

    def cancel(self, *, owner_id):
        kind = 'never-dispatched' if self.records[self.path]['state'] == 'PREPARED' else 'original-group-stopped'
        self.records[self.path].update(state='CANCELLED', stoppedProof=True, stopReceipt={'kind': kind})
        return self.inspect(owner_id=owner_id)


@unittest.skipUnless(sys.platform == 'linux', 'Linux-only bounded process provider')
class ProcessProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.base = Path(folder.name); self.root = self.base / 'custody'; self.root.mkdir(mode=0o700)
        engine = create_engine('sqlite:///' + str(self.base / 'admission.sqlite'))
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE af_leases(id TEXT PRIMARY KEY,owner_id TEXT,body TEXT)'))
            conn.execute(text('CREATE TABLE af_process_allocations(id TEXT PRIMARY KEY,owner_id TEXT,body TEXT)'))
            conn.execute(text('CREATE TABLE af_process_runs(task_id TEXT,effect_key TEXT,owner_id TEXT,native_run_id TEXT,lease_id TEXT UNIQUE,body TEXT,PRIMARY KEY(task_id,effect_key))'))
        self.store = SimpleNamespace(engine=engine)
        self.spec = ProcessSpec('/synthetic/program', 'a' * 64, ('synthetic-public-公开',))
        self.limits = ProcessLimits()
        self.provider = ProcessResourceProvider(self.store, self.root, self.spec, self.limits)
        self.lease = {'id': 'lease1', 'ownerId': 'alice', 'localTaskId': 'task1', 'planId': 'plan1',
            'nativeRunId': 'run1', 'requestId': 'request1', 'connectionRef': 'operator-process', 'poolId': 'pool1',
            'fingerprint': 'b' * 64, 'targetFingerprint': 'c' * 64, 'poolFingerprint': 'd' * 64,
            'planHash': 'e' * 64, 'providerNamespace': self.provider.capacity_namespace,
            'limits': {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 3}}
        self.mapping()
        FakeProcess.records = {}; FakeProcess.created = 0; FakeProcess.launched = 0
        FakeProcess.fail_create = False; FakeProcess.fail_launch_ack = False; FakeProcess.create_observer = None
        self.addCleanup(patch.stopall)
        patch('agent_factory.process_provider.BoundedProcessAdapter', FakeProcess).start()

    def mapping(self):
        value = self.lease
        body = {'taskId': value['localTaskId'], 'nativeRunId': value['nativeRunId'], 'planId': value['planId'],
            'ownerId': value['ownerId'], 'leaseId': value['id'], 'targetRef': value['connectionRef'],
            'planHash': value['planHash'], 'requestId': value['requestId'], 'leaseFingerprint': value['fingerprint']}
        with self.store.engine.begin() as conn:
            conn.execute(text('INSERT INTO af_leases VALUES(:id,:owner,:body)'),
                {'id': value['id'], 'owner': value['ownerId'], 'body': canonical(value)})
            conn.execute(text('INSERT INTO af_process_runs VALUES(:task,:effect,:owner,:run,:lease,:body)'),
                {'task': value['localTaskId'], 'effect': 'bounded-process-run-v1', 'owner': value['ownerId'],
                 'run': value['nativeRunId'], 'lease': value['id'], 'body': canonical(body)})

    def count(self):
        with self.store.engine.connect() as conn:
            return conn.execute(text('SELECT COUNT(*) FROM af_process_allocations')).scalar_one()

    async def allocate(self, provider=None):
        return await (provider or self.provider).allocate_bound(self.lease, before_effect=lambda: None)

    def reopened(self):
        return ProcessResourceProvider(self.store, self.root, self.spec, self.limits)

    def process(self):
        return FakeProcess.records[str(self.root / 'lease1' / 'custody.sqlite')]

    async def test_durable_bound_allocation_reopen_terminal_hold_explicit_reclaim(self):
        FakeProcess.create_observer = Mock(side_effect=lambda: self.assertEqual(self.count(), 1))
        result = await self.allocate()
        self.assertEqual(result['state'], 'RUNNING')
        self.assertEqual(result['processBinding']['nativeRunId'], 'run1')
        self.assertFalse(result['enforcement']['aggregateQuota'])
        self.assertIsNone(result['stopEvidence'])
        self.assertNotIn(str(self.root), canonical(result))
        reopened = self.reopened()
        self.assertEqual((await self.allocate(reopened))['providerJobId'], result['providerJobId'])
        self.process().update(state='COMPLETED', stoppedProof=True)
        terminal = await reopened.inspect('lease1', 'alice')
        self.assertEqual(terminal['state'], 'COMPLETED'); self.assertTrue(terminal['capacityHeld'])
        self.assertFalse(terminal['released'])
        released = await reopened.reclaim('lease1', 'alice')
        self.assertEqual(released['state'], 'RECLAIMED'); self.assertFalse(released['capacityHeld'])
        self.assertTrue((self.root / 'lease1' / 'custody.sqlite').is_file())
        self.assertEqual((await self.allocate(reopened))['state'], 'RECLAIMED')
        self.assertEqual((FakeProcess.created, FakeProcess.launched), (1, 1))

    async def test_missing_native_mapping_budgets_and_unbound_calls_have_no_effects(self):
        with self.assertRaisesRegex(ValueError, 'LEASE_CONTEXT_REQUIRED'):
            await self.provider.allocate('lease1', 'alice', 'b' * 64, self.lease['limits'])
        for key, value in [('memoryMb', 127), ('seconds', 2), ('cpu', 0), ('diskMb', 0)]:
            lease = {**self.lease, 'limits': {**self.lease['limits'], key: value}}
            with self.assertRaises(ValueError):
                await self.provider.allocate_bound(lease, before_effect=lambda: None)
        with self.store.engine.begin() as conn:
            conn.execute(text('DELETE FROM af_process_runs'))
        with self.assertRaises(ValueError):
            await self.allocate()
        self.assertEqual(self.count(), 0); self.assertEqual(list(self.root.iterdir()), [])

    async def test_unknown_create_never_replayed_or_bypassed_with_new_lease(self):
        FakeProcess.fail_create = True
        result = await self.allocate()
        self.assertEqual(result['state'], 'UNKNOWN'); self.assertTrue(result['capacityHeld'])
        await self.allocate(self.reopened())
        for action in ('inspect', 'cancel', 'reclaim'):
            self.assertEqual((await getattr(self.reopened(), action)('lease1', 'alice'))['state'], 'UNKNOWN')
        with self.assertRaises(ValueError):
            await self.provider.allocate_bound({**self.lease, 'id': 'new-lease'}, before_effect=lambda: None)
        self.assertEqual((FakeProcess.created, FakeProcess.launched), (1, 0))

    async def test_lost_launch_ack_only_original_inspection_and_cancel_can_reconcile(self):
        FakeProcess.fail_launch_ack = True
        self.assertEqual((await self.allocate())['state'], 'UNKNOWN')
        reopened = self.reopened()
        self.assertEqual((await reopened.inspect('lease1', 'alice'))['state'], 'RUNNING')
        stopped = await reopened.cancel('lease1', 'alice')
        self.assertTrue(stopped['allStopped']); self.assertTrue(stopped['capacityHeld'])
        self.assertEqual((await reopened.reclaim('lease1', 'alice'))['state'], 'RECLAIMED')
        self.assertEqual((FakeProcess.created, FakeProcess.launched), (1, 1))

    async def test_complete_binding_owner_spec_and_original_journal_pin_cannot_change(self):
        await self.allocate()
        for key in ('ownerId', 'nativeRunId', 'planId', 'requestId', 'targetFingerprint', 'poolFingerprint'):
            lease = {**self.lease, key: 'f' * 64 if key.endswith('Fingerprint') else 'other'}
            with self.subTest(field=key), self.assertRaises(ValueError):
                await self.provider.allocate_bound(lease, before_effect=lambda: None)
        with self.assertRaises(ValueError):
            await self.provider.inspect('lease1', 'bob')
        changed = ProcessResourceProvider(self.store, self.root, replace(self.spec, argv=('changed',)), self.limits)
        with self.assertRaises(ValueError):
            await changed.inspect('lease1', 'alice')
        self.process().update(id='foreign', state='COMPLETED', stoppedProof=True)
        result = await self.reopened().reclaim('lease1', 'alice')
        self.assertEqual(result['state'], 'UNKNOWN'); self.assertTrue(result['capacityHeld'])

    async def test_missing_or_symlinked_custody_is_unknown_not_release(self):
        await self.allocate()
        path = self.root / 'lease1' / 'custody.sqlite'
        original = self.root / 'lease1' / 'original.sqlite'
        path.rename(original); path.symlink_to(original)
        result = await self.reopened().reclaim('lease1', 'alice')
        self.assertEqual(result['state'], 'UNKNOWN'); self.assertTrue(original.is_file())
        path.unlink()
        self.assertEqual((await self.reopened().inspect('lease1', 'alice'))['state'], 'UNKNOWN')

    async def test_missing_stop_proof_and_running_reclaim_hold_capacity(self):
        await self.allocate()
        self.assertTrue((await self.provider.reclaim('lease1', 'alice'))['capacityHeld'])
        self.process().update(state='COMPLETED', stoppedProof=False)
        result = await self.provider.reclaim('lease1', 'alice')
        self.assertEqual(result['state'], 'UNKNOWN'); self.assertTrue(result['capacityHeld'])

    async def test_authority_is_rechecked_after_lock_and_before_launch(self):
        callback = Mock(side_effect=[None, PermissionError('synthetic revoked')])
        result = await self.provider.allocate_bound(self.lease, before_effect=callback)
        self.assertEqual(callback.call_count, 2); self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(FakeProcess.launched, 0)
        self.assertEqual((await self.provider.cancel('lease1', 'alice'))['state'], 'CANCEL_CONFIRMED')

    async def test_cancelled_waiter_and_revoked_authority_do_not_create_late_effect(self):
        waiting = threading.Event()
        original = self.provider._root_guard._operation_lock
        from contextlib import contextmanager
        @contextmanager
        def latch():
            waiting.set()
            with original():
                yield
        with original(), patch.object(self.provider._root_guard, '_operation_lock', latch):
            work = asyncio.create_task(self.allocate())
            self.assertTrue(await asyncio.to_thread(waiting.wait, 1))
            work.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await work
        # Joining the same root lock waits until the abandoned thread passed its fence.
        await asyncio.to_thread(self.provider._root_guard._serialized, lambda: None)
        self.assertEqual(self.count(), 0); self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(PermissionError):
            await self.provider.allocate_bound(self.lease, before_effect=Mock(side_effect=PermissionError('revoked')))
        self.assertEqual(self.count(), 0)

    async def test_original_server_lease_and_native_mapping_are_checked_before_any_effect(self):
        forged = {**self.lease, 'poolFingerprint': 'f' * 64}
        with self.assertRaises(ValueError):
            await self.provider.allocate_bound(forged, before_effect=lambda: None)
        with self.store.engine.begin() as conn:
            conn.execute(text("UPDATE af_process_runs SET native_run_id='foreign-run'"))
        with self.assertRaises(ValueError):
            await self.allocate()
        self.assertEqual(self.count(), 0); self.assertEqual(FakeProcess.created, 0)

    async def test_rebound_or_replaced_root_never_operates_on_old_custody(self):
        await self.allocate()
        retained = self.base / 'retained'
        self.root.rename(retained); self.root.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            await self.provider.cancel('lease1', 'alice')
        with self.assertRaises(ValueError):
            await self.reopened().reclaim('lease1', 'alice')
        self.assertTrue((retained / 'lease1' / 'custody.sqlite').is_file())
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(FakeProcess.launched, 1)

    async def test_failed_execution_outcome_survives_explicit_reclaim_and_restart(self):
        await self.allocate()
        self.process().update(state='LIMIT_STOPPED', stoppedProof=True, exitCode=-9)
        terminal = await self.provider.inspect('lease1', 'alice')
        self.assertEqual(terminal['state'], 'FAILED')
        self.assertEqual(terminal['executionStatus'], 'LIMIT_STOPPED')
        self.assertTrue(terminal['capacityHeld'])
        result = await self.reopened().reclaim('lease1', 'alice')
        self.assertEqual(result['state'], 'RECLAIMED')
        self.assertEqual(result['executionStatus'], 'LIMIT_STOPPED')
        self.assertEqual(result['exitCode'], -9)
        result = await self.reopened().inspect('lease1', 'alice')
        self.assertEqual((result['executionStatus'], result['exitCode']), ('LIMIT_STOPPED', -9))

    async def test_mapping_lock_wait_rechecks_cancellation_and_authority_before_dispatch(self):
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                entered, release, revoked, cancelled = (threading.Event() for _ in range(4))
                original = self.provider._verify_mapping
                dispatch = Mock()
                def waiting_mapping(conn, binding):
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError('synthetic latch')
                    original(conn, binding)
                def authority():
                    if revoked.is_set():
                        raise PermissionError('synthetic revoked')
                def launch():
                    self.provider._dispatch_authority(self.lease, cancelled, authority)
                    dispatch()
                with patch.object(self.provider, '_verify_mapping', waiting_mapping):
                    work = asyncio.create_task(asyncio.to_thread(launch))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                        (cancelled if cancel else revoked).set()
                    finally:
                        release.set()
                    with self.assertRaises(asyncio.CancelledError if cancel else PermissionError):
                        await work
                dispatch.assert_not_called()
                self.assertEqual(FakeProcess.launched, 0)

    async def test_async_authority_and_traversal_fail_closed(self):
        async def bad_guard():
            return None
        with self.assertRaises(ValueError):
            await self.provider.allocate_bound(self.lease, before_effect=bad_guard)
        for field in ('id', 'localTaskId', 'nativeRunId'):
            with self.assertRaises(ValueError):
                await self.provider.allocate_bound({**self.lease, field: '../foreign'}, before_effect=lambda: None)
        self.assertEqual(self.count(), 0)


if __name__ == '__main__':
    unittest.main()

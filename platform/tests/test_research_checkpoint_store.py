"""Synthetic checkpoint custody with real bounded files; no GPU/process/PG."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent_factory.research_checkpoint import write_checkpoint
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.store import digest


@unittest.skipUnless(os.name == 'posix', 'Requires private POSIX checkpoint files')
class ResearchCheckpointStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.objects = Path(temporary.name)
        self.identifier = digest({'task': 'task1', 'key': 'research-checkpoint-v1'})
        self.root = self.objects / self.identifier
        self.root.mkdir(mode=0o700)
        info = self.root.stat()
        self.pin = {'device': info.st_dev, 'inode': info.st_ino}
        self.binding = {'ownerId': 'alice', 'taskId': 'task1', 'nativeRunId': 'run1', 'planId': 'plan1',
            'planFingerprint': 'a'*64, 'leaseId': 'lease1', 'providerJobId': 'job1',
            'variantSha256': 'b'*64, 'manifestSha256': 'c'*64}
        self.plan = {'id': 'plan1', 'fingerprint': 'a'*64}
        self.task = {'id': 'task1', 'owner_id': 'alice', 'run_id': 'run1', 'plan_id': 'plan1',
                     'terminal': False, 'cancel_requested': False}
        self.lease = {'id': 'lease1', 'ownerId': 'alice', 'localTaskId': 'task1', 'nativeRunId': 'run1',
            'planId': 'plan1', 'planHash': digest(self.plan), 'providerJobId': 'job1', 'connectionRef': 'target1',
            'state': 'RECLAIMED', 'capacityHeld': False, 'executionStatus': 'COMPLETED', 'exitCode': 0,
            'stopEvidence': {'allStopped': True}, 'gpuEvidence': {'state': 'RELEASED'},
            'executionGuard': {'manifestSha256': 'c'*64, 'variantSha256': 'b'*64}}
        self.proof = {'manifestSha256': 'c'*64, 'variantSha256': 'b'*64, 'checkpoint': None,
            'evaluationContractSha256': None, 'descriptorSha256': 'd'*64, 'sourceSha256': 'e'*64}
        self.provider = Mock()
        self.provider.read_launch_proof.return_value = self.proof
        self.target = SimpleNamespace(provider=self.provider, synthetic_fixture=True)
        self.runtime = Mock()
        self.runtime._custody.side_effect = lambda _lease: (self.lease, self.target, self.task, None)
        self.runtime._config.return_value = ('target1', {'artifactLimits': {'checkpointBytes': 4096}}, 'b'*64)
        self.resources = Mock()
        self.resources.execution_runtime.return_value = self.runtime
        self.auth, self.store, self.storage = Mock(), Mock(), Mock()
        self.store.plan.return_value = self.plan
        self.store.task.side_effect = lambda *_args: deepcopy(self.task)
        self.store.settings = SimpleNamespace(storage_low_water_bytes=100)
        self.store.transaction.side_effect = lambda: nullcontext()
        self.held = 1024
        self.update_rows = 1
        self.sql_hook = None
        self.lock_hook = None
        self.events = []
        self.retention_held = False
        self.free = 100000
        self.store.sql.side_effect = self.sql
        self.storage.objects = self.objects
        self.storage.root_id = 'storage-root'
        self.storage._lock = Mock(side_effect=self.retention_lock)
        self.storage._directory.return_value = self.root
        self.object_row = {'task_id': 'task1', 'root_id': 'storage-root', 'state': 'AVAILABLE', 'evidence': True,
            'identity': {'device': info.st_dev, 'directoryInode': info.st_ino}}
        self.storage._object.side_effect = lambda owner, _id: self.object_row
        self.storage.filesystems.side_effect = lambda: [{'freeBytes': self.free}]
        self.artifacts = []
        self.contents = {}
        self.store.artifacts.side_effect = lambda task: deepcopy(self.artifacts)
        self.store.artifact.side_effect = lambda task, artifact: (deepcopy(self.artifacts[0]), self.contents[artifact])
        self.store.artifact_write.side_effect = self.write_artifact
        self.service = ResearchCheckpointStore(self.store, self.auth, self.resources, self.storage)
        patcher = patch('agent_factory.research_checkpoint_store.manifest_fingerprint', return_value='c'*64)
        patcher.start()
        self.addCleanup(patcher.stop)

    @contextmanager
    def retention_lock(self, _identifier):
        self.events.append('retention-enter')
        self.retention_held = True
        try:
            if self.lock_hook is not None:
                self.lock_hook()
            yield
        finally:
            self.retention_held = False
            self.events.append('retention-exit')

    def sql(self, statement, **params):
        if self.sql_hook is not None:
            self.sql_hook(statement)
        if 'pg_advisory_xact_lock' in statement:
            self.events.append('admission')
        if 'FROM af_tasks' in statement and 'FOR UPDATE' in statement:
            self.events.append('task-lock')
            return [deepcopy(self.task)]
        if statement.startswith('SELECT body FROM af_process_allocations'):
            return [{'body': {'processPin': {'id': 'job1'}, 'binding': deepcopy(self.lease)}}]
        if statement.startswith('SELECT bytes'):
            if 'FOR UPDATE' in statement: self.events.append('hold-lock')
            return [{'bytes': self.held}]
        if statement.startswith('SELECT COALESCE'):
            return [{'n': self.held}]
        if statement.startswith('UPDATE af_disk_holds'):
            self.events.append('hold-update')
            if self.update_rows:
                self.held = params['bytes']
                return [{'task_id': 'task1', 'bytes': self.held}]
            return []
        return []

    def write_artifact(self, task, name, raw, *, metadata):
        item = {'id': 'artifact1', 'name': name, 'jobId': task, 'provenance': metadata,
                'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.artifacts.append(deepcopy(item))
        self.contents['artifact1'] = raw
        return item

    def produce(self):
        return write_checkpoint(self.root, 'checkpoint.safetensors',
            {'weight': {'dtype': 'F32', 'shape': [2], 'data_offsets': [0, 8]}}, [b'\0'*8],
            root_identity=self.pin, binding=self.binding, max_bytes=4096, before_effect=lambda: None)

    def test_reserve_original_job_and_disk_hold_only_grow(self):
        result = self.service.reserve(self.binding, disk_bytes=8192)
        self.assertEqual(self.held, 8192)
        self.assertEqual(result['rootIdentity'], self.pin)
        self.assertEqual(result['basename'], 'checkpoint.safetensors')
        self.service.reserve(self.binding, disk_bytes=4096)
        self.assertEqual(self.held, 8192)
        self.runtime.guard_lease.assert_called()
        with self.assertRaises(ValueError):
            self.service.reserve(self.binding | {'providerJobId': 'replacement'}, disk_bytes=8192)

    def test_reserve_capacity_and_revocation_deny_before_directory_effect(self):
        self.free = 1100
        with self.assertRaises(ValueError):
            self.service.reserve(self.binding, disk_bytes=8192)
        self.storage._directory.assert_not_called()
        self.assertEqual(self.held, 1024)
        self.auth.require.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            self.service.reserve(self.binding, disk_bytes=8192)
        self.storage._directory.assert_not_called()

    def test_completed_import_and_virtual_identity_use_real_tensor_file_not_stdout(self):
        produced = self.produce()
        artifact = self.service.import_completed('alice', 'lease1')
        metadata, identity = self.service.identity('task1', artifact['id'], 4096)
        self.assertEqual(identity, produced['identity'])
        self.assertEqual(metadata['provenance']['providerJobId'], 'job1')
        self.assertNotEqual(identity['sha256'], artifact['sha256'])
        self.provider.read_completed_output.assert_not_called()

    def test_lost_import_ack_replays_original_reference_without_second_write(self):
        self.produce()
        def lost(*args, **kwargs):
            self.write_artifact(*args, **kwargs)
            raise RuntimeError('lost ack')
        self.store.artifact_write.side_effect = lost
        with self.assertRaises(RuntimeError):
            self.service.import_completed('alice', 'lease1')
        recovered = self.service.import_completed('alice', 'lease1')
        self.assertEqual(recovered['id'], 'artifact1')
        self.store.artifact_write.assert_called_once()

    def test_stop_gpu_and_owner_mismatch_refuse_import(self):
        self.produce()
        for field, invalid in (('state', 'UNKNOWN'), ('capacityHeld', True), ('executionStatus', 'FAILED'),
                               ('exitCode', True), ('stopEvidence', {'allStopped': False}),
                               ('gpuEvidence', {'state': 'UNKNOWN'}), ('ownerId', 'bob')):
            old = self.lease[field]
            self.lease[field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.service.import_completed('alice', 'lease1')
            self.lease[field] = old
        self.store.artifact_write.assert_not_called()

    def test_retention_root_and_file_drift_refuse_existing_reference(self):
        self.produce()
        self.service.import_completed('alice', 'lease1')
        for patch_value in ({'state': 'QUARANTINED'}, {'root_id': 'different'},
                            {'identity': {'device': self.pin['device'], 'directoryInode': self.pin['inode']+1}}):
            original = deepcopy(self.object_row)
            self.object_row.update(patch_value)
            with self.subTest(patch=patch_value), self.assertRaises(ValueError):
                self.service.identity('task1', 'artifact1', 4096)
            self.object_row.clear(); self.object_row.update(original)
        path = self.root / 'checkpoint.safetensors'
        path.chmod(0o600)
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + b'x')
        with self.assertRaises(ValueError):
            self.service.identity('task1', 'artifact1', 4096)

    def test_revocation_rechecked_before_publish_and_on_identity(self):
        self.produce()
        self.auth.require.side_effect = [None, PermissionError('revoked')]
        with self.assertRaises(PermissionError):
            self.service.import_completed('alice', 'lease1')
        self.store.artifact_write.assert_not_called()
        self.auth.require.side_effect = None
        self.service.import_completed('alice', 'lease1')
        self.auth.require.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            self.service.identity('task1', 'artifact1', 4096)

    def test_changed_harness_or_checkpoint_reference_never_republishes(self):
        self.produce()
        self.service.import_completed('alice', 'lease1')
        self.proof['descriptorSha256'] = '0'*64
        with self.assertRaises(ValueError):
            self.service.identity('task1', 'artifact1', 4096)
        with self.assertRaises(ValueError):
            self.service.import_completed('alice', 'lease1')
        self.store.artifact_write.assert_called_once()

    def test_identity_revocation_after_stream_hash_returns_no_identity(self):
        self.produce()
        self.service.import_completed('alice', 'lease1')
        original_open = self.service._open

        @contextmanager
        def revoke_after_hash(*args):
            with original_open(*args) as opened:
                self.auth.require.side_effect = PermissionError('revoked during stream')
                yield opened

        with patch.object(self.service, '_open', revoke_after_hash), self.assertRaises(PermissionError):
            self.service.identity('task1', 'artifact1', 4096)

    def test_launch_proof_changed_during_stream_refuses_identity_and_import(self):
        self.produce()
        self.service.import_completed('alice', 'lease1')
        original_open = self.service._open

        @contextmanager
        def change_after_hash(*args):
            with original_open(*args) as opened:
                changed = deepcopy(self.proof)
                changed['descriptorSha256'] = '0'*64
                self.provider.read_launch_proof.return_value = changed
                yield opened

        for operation in (lambda: self.service.identity('task1', 'artifact1', 4096),
                          lambda: self.service.import_completed('alice', 'lease1')):
            self.provider.read_launch_proof.return_value = self.proof
            with patch.object(self.service, '_open', change_after_hash), self.assertRaises(ValueError):
                operation()
        self.store.artifact_write.assert_called_once()


    def test_reserve_rechecks_retention_and_admission_windows_before_directory_or_chmod(self):
        for boundary in ('retention', 'admission'):
            for change in ('revocation', 'cancel', 'terminal'):
                with self.subTest(boundary=boundary, change=change):
                    self.task.update(terminal=False, cancel_requested=False)
                    self.held = 1024; self.events.clear(); self.store.sql.reset_mock()
                    self.storage._directory.reset_mock(); self.auth.require.reset_mock(side_effect=True)
                    self.store.require_plan_execution.reset_mock(side_effect=True)
                    revoked = False; denial = PermissionError('synthetic authority ended'); triggered = False
                    def check(*_args, **_kwargs):
                        if revoked: raise denial
                    def mutate():
                        nonlocal revoked, triggered
                        if triggered: return
                        triggered = True
                        if change == 'revocation': revoked = True
                        elif change == 'cancel': self.task['cancel_requested'] = True
                        else: self.task['terminal'] = True
                    self.auth.require.side_effect = check
                    self.store.require_plan_execution.side_effect = check
                    self.lock_hook = mutate if boundary == 'retention' else None
                    self.sql_hook = (lambda statement: mutate() if 'pg_advisory_xact_lock' in statement else None) if boundary == 'admission' else None
                    expected = PermissionError if change == 'revocation' else ValueError
                    with patch('agent_factory.research_checkpoint_store.os.fchmod', create=True) as chmod:
                        with self.assertRaises(expected) as raised:
                            self.service.reserve(self.binding, disk_bytes=8192)
                        if change == 'revocation': self.assertIs(raised.exception, denial)
                        self.assertTrue(triggered)
                        self.storage._directory.assert_not_called(); chmod.assert_not_called()
                    self.assertNotIn('hold-update', self.events)
                    self.assertEqual(self.held, 1024)
                    self.assertFalse(self.retention_held)

    def test_reserve_zero_row_update_cannot_create_or_chmod_directory(self):
        for held, requested in ((1024, 8192), (8192, 4096)):
            with self.subTest(held=held, requested=requested):
                self.held = held; self.update_rows = 0
                self.store.sql.reset_mock(); self.storage._directory.reset_mock()
                with patch('agent_factory.research_checkpoint_store.os.fchmod', create=True) as chmod:
                    with self.assertRaises(ValueError):
                        self.service.reserve(self.binding, disk_bytes=requested)
                    self.storage._directory.assert_not_called(); chmod.assert_not_called()
                updates = [call.args[0] for call in self.store.sql.call_args_list if call.args[0].startswith('UPDATE af_disk_holds')]
                self.assertEqual(len(updates), 1)
                self.assertIn('RETURNING', updates[0])
                self.assertEqual(self.held, held)

    def test_reserve_lock_order_holds_owned_task_and_hold_before_effect(self):
        @contextmanager
        def transaction():
            self.assertTrue(self.retention_held)
            self.events.append('transaction-enter')
            yield
            self.events.append('transaction-exit')
        def directory(*_args, **_kwargs):
            self.assertTrue(self.retention_held)
            self.events.append('directory')
            return self.root
        self.store.transaction.side_effect = transaction
        self.storage._directory.side_effect = directory
        self.service.reserve(self.binding, disk_bytes=8192)
        required = ['retention-enter', 'transaction-enter', 'admission', 'task-lock', 'hold-lock', 'hold-update', 'directory']
        self.assertEqual([event for event in self.events if event in required], required)
        task_queries = [call for call in self.store.sql.call_args_list if 'FROM af_tasks' in call.args[0] and 'FOR UPDATE' in call.args[0]]
        self.assertEqual(len(task_queries), 1)
        self.assertIn('owner_id', task_queries[0].args[0])
        self.assertIn('alice', task_queries[0].kwargs.values())
        holds = [call.args[0] for call in self.store.sql.call_args_list if call.args[0].startswith('SELECT bytes')]
        self.assertEqual(len(holds), 1); self.assertIn('FOR UPDATE', holds[0])
        self.assertFalse(self.retention_held)


    def test_reserve_object_lookup_authority_loss_prevents_chmod(self):
        denial = PermissionError('synthetic authority ended at object lookup')
        def revoke_object(*_args):
            self.auth.require.side_effect = denial
            return self.object_row
        self.storage._object.side_effect = revoke_object
        with patch('agent_factory.research_checkpoint_store.os.fchmod', create=True) as chmod:
            with self.assertRaises(PermissionError) as raised:
                self.service.reserve(self.binding, disk_bytes=8192)
            self.assertIs(raised.exception, denial)
            self.storage._directory.assert_called_once()
            chmod.assert_not_called()
        self.assertFalse(self.retention_held)

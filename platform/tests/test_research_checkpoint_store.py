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
        self.store.task.return_value = self.task
        self.store.settings = SimpleNamespace(storage_low_water_bytes=100)
        self.store.transaction.side_effect = lambda: nullcontext()
        self.held = 1024
        self.free = 100000
        self.store.sql.side_effect = self.sql
        self.storage.objects = self.objects
        self.storage.root_id = 'storage-root'
        self.storage._lock = Mock(side_effect=lambda _id: nullcontext())
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

    def sql(self, statement, **params):
        if statement.startswith('SELECT body FROM af_process_allocations'):
            return [{'body': {'processPin': {'id': 'job1'}, 'binding': deepcopy(self.lease)}}]
        if statement.startswith('SELECT bytes'):
            return [{'bytes': self.held}]
        if statement.startswith('SELECT COALESCE'):
            return [{'n': self.held}]
        if statement.startswith('UPDATE af_disk_holds'):
            self.held = params['bytes']
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

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
from agent_factory.research_preparation_store import ResearchPreparationStore
from agent_factory.store import digest


@unittest.skipUnless(os.name == 'posix', 'Requires private POSIX checkpoint files')
class ResearchPreparationStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.objects = Path(temporary.name)
        self.identifier = digest({'task': 'task1', 'key': 'research-tokenizer-preparation-v1'})
        self.root = self.objects / self.identifier
        self.root.mkdir(mode=0o700)
        info = self.root.stat()
        self.pin = {'device': info.st_dev, 'inode': info.st_ino}
        self.binding = {'ownerId': 'alice', 'taskId': 'task1', 'nativeRunId': 'run1', 'planId': 'plan1',
            'planFingerprint': 'a'*64, 'leaseId': 'lease1', 'providerJobId': 'job1',
            'variantSha256': 'e'*64, 'manifestSha256': 'c'*64}
        self.plan = {'id': 'plan1', 'fingerprint': 'a'*64}
        self.task = {'id': 'task1', 'owner_id': 'alice', 'run_id': 'run1', 'plan_id': 'plan1',
                     'terminal': False, 'cancel_requested': False}
        self.lease = {'id': 'lease1', 'ownerId': 'alice', 'localTaskId': 'task1', 'nativeRunId': 'run1',
            'planId': 'plan1', 'fingerprint': '8'*64, 'targetFingerprint': '9'*64, 'planHash': digest(self.plan), 'providerJobId': 'job1', 'connectionRef': 'target1',
            'state': 'RECLAIMED', 'capacityHeld': False, 'executionStatus': 'COMPLETED', 'exitCode': 0,
            'stopEvidence': {'allStopped': True}, 'gpuEvidence': {'state': 'RELEASED'},
            'executionGuard': {'manifestSha256': 'c'*64, 'variantSha256': 'e'*64}}
        self.record = {'processPin': {'id': 'job1', 'identitySha256': '7'*64},
            'binding': deepcopy(self.lease), 'configurationFingerprint': '6'*64, 'released': False}
        self.record['bindingHash'] = digest(self.record['binding'])
        self.proof = {'schema': 1, 'evidenceKind': 'research-tokenizer-preparation-v1',
            'manifestSha256': 'c'*64, 'variantSha256': 'e'*64, 'descriptorSha256': 'd'*64, 'sourceSha256': 'e'*64,
            'leaseBindingSha256': self.record['bindingHash'], 'processIdentitySha256': '7'*64, 'executionVerified': False}
        self.provider = Mock()
        self.provider.configuration_fingerprint = '6'*64
        self.provider.read_launch_proof.return_value = self.proof
        self.target = SimpleNamespace(provider=self.provider, synthetic_fixture=True)
        self.runtime = Mock()
        self.runtime._custody.side_effect = lambda _lease: (self.lease, self.target, self.task, None)
        self.runtime._config.return_value = ('target1', {'artifactLimits': {'checkpointBytes': 4096}}, 'b'*64)
        self.resources = Mock()
        self.resources.execution_runtime.return_value = self.runtime
        self.resources._authorize.return_value = self.target
        self.resources._target_fingerprint.return_value = '9'*64
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
        self.service = ResearchPreparationStore(self.store, self.auth, self.resources, self.storage,
            preparation_manifest_sha256='c'*64, source_sha256='e'*64)

    def sql(self, statement, **params):
        if statement.startswith('SELECT * FROM af_tasks'):
            return [deepcopy(self.task)]
        if statement.startswith('SELECT body FROM af_process_allocations'):
            return [{'body': deepcopy(self.record)}]
        if statement.startswith('SELECT * FROM af_process_runs'):
            return [{'lease_id': 'lease1', 'owner_id': 'alice', 'native_run_id': 'run1'}]
        if statement.startswith('SELECT bytes'):
            return [{'bytes': self.held}]
        if statement.startswith('SELECT COALESCE'):
            return [{'n': self.held}]
        if statement.startswith('UPDATE af_disk_holds'):
            self.held = params['bytes']
            return [{'bytes': self.held}]
        return []

    def write_artifact(self, task, name, raw, *, metadata):
        item = {'id': 'artifact1', 'name': name, 'jobId': task, 'provenance': metadata,
                'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.artifacts.append(deepcopy(item))
        self.contents['artifact1'] = raw
        return item

    def produce(self):
        return write_checkpoint(self.root, 'token-bytes.safetensors',
            {'token_bytes': {'dtype': 'I32', 'shape': [2], 'data_offsets': [0, 8]}}, [b'\0'*8],
            root_identity=self.pin, binding=self.binding, max_bytes=4096, before_effect=lambda: None)

    def test_reserve_original_job_and_disk_hold_only_grow(self):
        result = self.service.reserve('alice', 'lease1', disk_bytes=8192)
        self.assertEqual(self.held, 8192)
        self.assertEqual(result['destination']['rootIdentity'], self.pin)
        self.assertEqual(result['destination']['basename'], 'token-bytes.safetensors')
        self.service.reserve('alice', 'lease1', disk_bytes=4096)
        self.assertEqual(self.held, 8192)
        self.runtime.guard_lease.assert_called()
        with self.assertRaises(ValueError):
            self.service.reserve('bob', 'lease1', disk_bytes=8192)

    def test_reserve_capacity_and_revocation_deny_before_directory_effect(self):
        self.free = 1100
        with self.assertRaises(ValueError):
            self.service.reserve('alice', 'lease1', disk_bytes=8192)
        self.storage._directory.assert_not_called()
        self.assertEqual(self.held, 1024)
        self.auth.require.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            self.service.reserve('alice', 'lease1', disk_bytes=8192)
        self.storage._directory.assert_not_called()

    def test_reserve_rechecks_revoke_and_cancel_after_retention_lock(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                self.auth.require.side_effect = None
                self.task['cancel_requested'] = False

                @contextmanager
                def enter(_identifier):
                    if cancelled:
                        self.task['cancel_requested'] = True
                    else:
                        self.auth.require.side_effect = PermissionError('revoked')
                    yield

                self.storage._lock.side_effect = enter
                with self.assertRaises((ValueError, PermissionError)):
                    self.service.reserve('alice', 'lease1', disk_bytes=8192)
                self.storage._directory.assert_not_called()
                self.assertEqual(self.held, 1024)

    def test_reserve_rechecks_revoke_cancel_and_terminal_after_admission_wait(self):
        for mutation in ('revoke', 'cancel_requested', 'terminal'):
            with self.subTest(mutation=mutation):
                self.auth.require.side_effect = None
                self.task.update(cancel_requested=False, terminal=False)

                def sql(statement, **params):
                    if 'pg_advisory_xact_lock' in statement:
                        if mutation == 'revoke':
                            self.auth.require.side_effect = PermissionError('revoked')
                        else:
                            self.task[mutation] = True
                    return self.sql(statement, **params)

                self.store.sql.side_effect = sql
                with self.assertRaises((ValueError, PermissionError)):
                    self.service.reserve('alice', 'lease1', disk_bytes=8192)
                self.storage._directory.assert_not_called()
                self.assertEqual(self.held, 1024)

    def test_reserve_missing_hold_update_ack_denies_directory(self):
        def sql(statement, **params):
            if statement.startswith('UPDATE af_disk_holds'):
                self.assertIn('RETURNING bytes', statement)
                return []
            return self.sql(statement, **params)

        self.store.sql.side_effect = sql
        with self.assertRaises(ValueError):
            self.service.reserve('alice', 'lease1', disk_bytes=8192)
        self.storage._directory.assert_not_called()

    def test_reserve_rechecks_before_chmod_and_before_return(self):
        def revoke_object(*_args):
            self.auth.require.side_effect = PermissionError('revoked')
            return self.object_row

        self.storage._object.side_effect = revoke_object
        with patch('agent_factory.research_preparation_store.os.fchmod') as chmod:
            with self.assertRaises(PermissionError):
                self.service.reserve('alice', 'lease1', disk_bytes=8192)
            chmod.assert_not_called()
        self.auth.require.side_effect = None
        self.storage._object.side_effect = lambda *_args: self.object_row
        with patch('agent_factory.research_preparation_store.os.fsync',
                   side_effect=lambda _fd: setattr(self.auth.require, 'side_effect', PermissionError('revoked'))):
            with self.assertRaises(PermissionError):
                self.service.reserve('alice', 'lease1', disk_bytes=8192)

    def test_completed_import_and_virtual_identity_use_real_tensor_file_not_stdout(self):
        produced = self.produce()
        artifact = self.service.import_completed('alice', 'lease1')
        metadata, identity = self.service.identity('alice', 'task1', artifact['id'], 4096)
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
                               ('ownerId', 'bob')):
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
                self.service.identity('alice', 'task1', 'artifact1', 4096)
            self.object_row.clear(); self.object_row.update(original)
        path = self.root / 'token-bytes.safetensors'
        path.chmod(0o600)
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + b'x')
        with self.assertRaises(ValueError):
            self.service.identity('alice', 'task1', 'artifact1', 4096)

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
            self.service.identity('alice', 'task1', 'artifact1', 4096)

    def test_changed_harness_or_checkpoint_reference_never_republishes(self):
        self.produce()
        self.service.import_completed('alice', 'lease1')
        self.proof['descriptorSha256'] = '0'*64
        with self.assertRaises(ValueError):
            self.service.identity('alice', 'task1', 'artifact1', 4096)
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
            self.service.identity('alice', 'task1', 'artifact1', 4096)

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

        for operation in (lambda: self.service.identity('alice', 'task1', 'artifact1', 4096),
                          lambda: self.service.import_completed('alice', 'lease1')):
            self.provider.read_launch_proof.return_value = self.proof
            with patch.object(self.service, '_open', change_after_hash), self.assertRaises(ValueError):
                operation()
        self.store.artifact_write.assert_called_once()

    def test_input_pin_is_owned_token_bytes_not_arbitrary_checkpoint(self):
        self.produce()
        artifact = self.service.import_completed('alice', 'lease1')
        pin = self.service.input_pin('alice', 'task1', artifact['id'])
        self.assertEqual(pin['binding'], self.binding)
        self.assertEqual(pin['basename'], 'token-bytes.safetensors')
        self.assertEqual(pin['rootIdentity'], self.pin)
        with self.assertRaises(ValueError):
            self.service.input_pin('bob', 'task1', artifact['id'])

    def test_general_model_tensor_is_not_preparation_artifact(self):
        write_checkpoint(self.root, 'token-bytes.safetensors',
            {'weight': {'dtype': 'F32', 'shape': [2], 'data_offsets': [0, 8]}}, [b'\0'*8],
            root_identity=self.pin, binding=self.binding, max_bytes=4096, before_effect=lambda: None)
        with self.assertRaises(ValueError):
            self.service.import_completed('alice', 'lease1')
        self.store.artifact_write.assert_not_called()

    def test_wrong_preparation_proof_rejected(self):
        self.produce()
        for key, value in (('evidenceKind', 'research_checkpoint_reference'), ('schema', True),
                           ('leaseBindingSha256', '0'*64), ('processIdentitySha256', '0'*64),
                           ('sourceSha256', '0'*64), ('executionVerified', True)):
            old = self.proof[key]; self.proof[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.service.import_completed('alice', 'lease1')
            self.proof[key] = old
        self.store.artifact_write.assert_not_called()

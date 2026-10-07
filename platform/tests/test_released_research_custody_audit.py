"""Read-only recovery audit rejects altered original chains without dispatch."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/audit_released_research_custody.py'
spec = importlib.util.spec_from_file_location('released_custody_audit', SCRIPT)
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@unittest.skipUnless(sys.platform == 'linux', 'Linux custody contract')
class ReleasedCustodyAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        directory = root / 'lease'
        directory.mkdir(mode=0o700)
        self.path = directory / 'custody.sqlite'
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE custody(singleton INTEGER PRIMARY KEY,body TEXT NOT NULL)')
        self.path.chmod(0o600)
        d = helper.digest
        plan = {'id': 'plan', 'ownerId': 'owner', 'steps': []}
        self.pins = {'schema': 1, 'taskId': 'task', 'ownerId': 'owner', 'planId': 'plan',
                     'planHash': d(plan), 'requestId': 'request', 'nativeRunId': 'native', 'leaseId': 'lease',
                     'providerRoot': str(root), 'rootIdentity': [root.stat().st_dev, root.stat().st_ino],
                     'spec': {'interpreter': '/usr/bin/python'}, 'limits': {'wall_seconds': 60},
                     'gpuBinding': {'schema': 1, 'deviceId': '1' * 64, 'receiverNamespace': '2' * 64,
                                    'policy': 'exclusive-factory-lease', 'quotaEnforced': False,
                                    'deviceIsolationEnforced': False},
                     'sourceSha256': 'a' * 64, 'manifestSha256': 'b' * 64, 'observerSha256': 'c' * 64,
                     'requiredIsolation': []}
        pins = self.pins
        namespace = d({'namespace': 'process-custody-v1', 'root': d({'namespace': 'local-workspace-v1',
                        'root': str(root), 'rootIdentity': pins['rootIdentity']})})
        binding = dict(zip(helper.BINDINGS, ['lease', 'owner', 'd' * 64, 'task', 'plan', 'native',
                       'lease-request', 'target', d(plan), 'e' * 64, 'pool', 'f' * 64,
                       namespace, {'cpu': 1}, 'research-process-run-v1',
                       {'manifestSha256': pins['manifestSha256']}, pins['gpuBinding']], strict=True))
        info, di = self.path.stat(), directory.stat()
        body = {'schema': 1, 'id': 'journal', 'ownerId': 'owner', 'taskId': 'task',
                'requestId': 'lease-request', 'spec': pins['spec'], 'limits': pins['limits'],
                'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'rootPin': {'directoryDevice': di.st_dev, 'directoryInode': di.st_ino,
                            'fileDevice': info.st_dev, 'fileInode': info.st_ino, 'path': str(self.path)},
                'specSha256': d({'spec': pins['spec'], 'limits': pins['limits']}, ascii=True),
                'guardian': None, 'child': None, 'state': 'CANCELLED', 'stoppedProof': True, 'capacityHeld': False}
        body['identitySha256'] = d({key: body[key] for key in helper.IDENTITY}, ascii=True)
        body['stopReceipt'] = {'kind': 'never-dispatched', 'journalId': 'journal',
            'identitySha256': body['identitySha256'], 'bootId': body['bootId'], 'guardian': None,
            'child': None, 'exitCode': None, 'groupStopped': True}
        self.body = body
        self.write_body()
        process_pin = {key: body[key] for key in helper.PROCESS_PIN}
        observation = d({'neverDispatched': True, 'processPin': process_pin,
                         'stopReceipt': body['stopReceipt'], 'binding': d(binding)})
        config = d({'base': d({'namespace': namespace, 'spec': pins['spec'], 'limits': pins['limits'],
                              'revision': 'process-provider-v1'}), 'revision': 'research-local-provider-v1',
                    **{key: pins[key] for key in ('gpuBinding', 'sourceSha256', 'manifestSha256', 'observerSha256')}})
        record = {'binding': binding, 'bindingHash': d(binding), 'configurationFingerprint': config,
                  'directoryIdentity': [di.st_dev, di.st_ino], 'journalIdentity': [info.st_dev, info.st_ino],
                  'processPin': process_pin, 'state': 'RECLAIMED', 'released': True, 'allStopped': True,
                  'stopKind': 'never-dispatched', 'executionStatus': 'CANCELLED', 'gpuReleaseObservationSha256': observation}
        gpu_keys = ('id', 'ownerId', 'localTaskId', 'nativeRunId', 'planId', 'fingerprint', 'gpuBinding')
        lease = {**binding, 'state': 'RECLAIMED', 'capacityHeld': False, 'cancelAck': 'unknown', 'releaseAck': 'unknown',
                 'processBinding': {'taskId': 'task', 'nativeRunId': 'native', 'planId': 'plan', 'bindingFingerprint': d(binding)},
                 'providerJobId': 'journal', 'stopEvidence': {'allStopped': True, 'kind': 'never-dispatched'},
                 'executionStatus': 'CANCELLED',
                 'gpuEvidence': {'schema': 1, 'bindingFingerprint': d({k: binding[k] for k in gpu_keys}),
                     'state': 'RELEASED', 'releaseProof': {'kind': 'never-dispatched',
                     'processBindingFingerprint': d(binding), 'deviceObservationSha256': observation}}}
        task = {'id': 'task', 'owner_id': 'owner', 'plan_id': 'plan', 'request_id': 'request',
                'run_id': 'native', 'fingerprint': d({'planId': 'plan', 'planHash': d(plan)})}
        ticket = {'id': 'native', 'session_id': 'task', 'user_id': 'owner', 'component_type': 'agent',
                  'component_id': 'factory-executor', 'idempotency_key': d({'owner': 'owner', 'task': 'task', 'request': 'request'}, ascii=True),
                  'payload': {'kwargs': {'session_state': {'factory_envelope': {'plan_ref': 'plan',
                      'user_id': 'owner', 'task_id': 'task', 'request_id': 'request'}}}}}
        mapping = {'task_id': 'task', 'owner_id': 'owner', 'native_run_id': 'native', 'lease_id': 'lease',
                   'effect_key': 'research-process-run-v1', 'body': {'taskId': 'task', 'nativeRunId': 'native',
                   'planId': 'plan', 'ownerId': 'owner', 'leaseId': 'lease', 'targetRef': 'target',
                   'planHash': d(plan), 'requestId': 'lease-request', 'leaseFingerprint': binding['fingerprint']}}
        self.evidence = {'schema': 1, 'nativeSession': None, 'lease': lease, 'provider': record, 'mapping': mapping,
                         'task': task, 'plan': {'id': 'plan', 'owner_id': 'owner', 'hash': d(plan), 'body': plan}, 'ticket': ticket}

    def write_body(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute('DELETE FROM custody')
            conn.execute('INSERT INTO custody VALUES(1,?)', (json.dumps(self.body),))

    def check(self, expected=True):
        result = helper.audit(self.evidence, self.pins, self.path)
        self.assertEqual(result['releasedCustodyConsistent'], expected)
        self.assertFalse(result['replayRequired'])
        self.assertFalse(result['issuerAuthenticated'])
        self.assertFalse(result['newAttemptReady'])
        return result

    def test_positive_unknown_acks_read_only(self):
        before = (self.path.read_bytes(), self.path.stat(), set(self.path.parent.iterdir()))
        self.check()
        after = (self.path.read_bytes(), self.path.stat(), set(self.path.parent.iterdir()))
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1].st_mtime_ns, after[1].st_mtime_ns)
        self.assertEqual(before[1].st_ino, after[1].st_ino)
        self.assertEqual(before[2], after[2])

    def test_wrong_original_fields(self):
        mutations = [(['task', 'request_id'], 'other'), (['plan', 'body', 'id'], 'other'),
            (['ticket', 'idempotency_key'], '0' * 64), (['ticket', 'id'], 'other'),
            (['ticket', 'payload', 'kwargs', 'session_state', 'factory_envelope', 'task_id'], 'other'),
            (['provider', 'configurationFingerprint'], '0' * 64),
            (['lease', 'gpuEvidence', 'releaseProof', 'deviceObservationSha256'], '0' * 64),
            (['provider', 'allStopped'], False), (['lease', 'providerJobId'], 'other'),
            (['lease', 'processBinding', 'taskId'], 'other'), (['lease', 'stopEvidence', 'allStopped'], False),
            (['provider', 'executionStatus'], 'RUNNING'), (['lease', 'capacityHeld'], True)]
        original = copy.deepcopy(self.evidence)
        for keys, value in mutations:
            with self.subTest(keys=keys):
                self.evidence = copy.deepcopy(original)
                target = self.evidence
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.check(False)

    def test_independent_configuration_pins(self):
        self.pins['sourceSha256'] = '0' * 64
        self.check(False)

    def test_changed_boot_and_guardian(self):
        for key, value in [('bootId', 'different'), ('guardian', {'pid': 1})]:
            with self.subTest(key=key):
                original = copy.deepcopy(self.body)
                self.body[key] = value
                self.write_body()
                self.check(False)
                self.body = original

    def test_symlink_and_wal_rejected(self):
        moved = self.path.with_name('original.sqlite')
        self.path.rename(moved)
        self.path.symlink_to(moved)
        self.check(False)
        self.path.unlink()
        moved.rename(self.path)
        with sqlite3.connect(self.path) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
        self.check(False)

    def test_incomplete_and_safe_cli(self):
        del self.evidence['ticket']
        self.check(False)
        response = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), 'SECRET-SENTINEL'],
                                  text=True, capture_output=True, check=False)
        self.assertEqual(response.returncode, 2)
        self.assertEqual(response.stderr, '')
        self.assertNotIn('SECRET-SENTINEL', response.stdout)
        self.assertEqual(json.loads(response.stdout)['code'], 'UNKNOWN')

    def test_runtime_pure_validators_accept_same_receipts(self):
        # Independent source contracts, no provider construction or inspect/write.
        from agent_factory.process_enforcement import _digest, _identity, spec_contract, valid_stop
        from agent_factory.gpu_custody import evidence_fingerprint, validate_gpu_evidence
        self.check()
        self.assertEqual(self.body['identitySha256'], _digest(_identity(self.body)))
        self.assertEqual(self.body['specSha256'], _digest(spec_contract(self.body['spec'], self.body['limits'])))
        self.assertTrue(valid_stop(self.body))
        lease = self.evidence['lease']
        self.assertEqual(lease['gpuEvidence']['bindingFingerprint'], evidence_fingerprint(lease))
        snapshot = {**lease, 'released': True}
        self.assertEqual(validate_gpu_evidence(lease, snapshot), lease['gpuEvidence'])

    def test_native_session_requires_original_run(self):
        self.evidence['nativeSession'] = {'user_id': 'owner', 'agent_id': 'factory-executor',
            'runs': [{'run_id': 'native', 'agent_id': 'factory-executor'}]}
        self.check()
        self.evidence['nativeSession']['runs'][0]['run_id'] = 'other'
        self.check(False)

    def test_fifo_and_view_rejected(self):
        fifo = self.path.with_name('fifo')
        os.mkfifo(fifo)
        with self.assertRaises(helper.Rejected):
            helper.load_json(fifo)
        with sqlite3.connect(self.path) as conn:
            conn.execute('DROP TABLE custody')
            conn.execute('CREATE VIEW custody AS SELECT 1 AS singleton, 2 AS body')
        self.check(False)

    def test_requires_isolated_bytecode_disabled_cli(self):
        response = subprocess.run([sys.executable, str(SCRIPT)], text=True, capture_output=True, check=False)
        self.assertEqual(response.returncode, 2)
        self.assertEqual(response.stderr, '')
        self.assertEqual(json.loads(response.stdout)['code'], 'UNKNOWN')

    def test_sidecar_and_duplicate_json_rejected(self):
        Path(str(self.path) + '-journal').write_bytes(b'')
        self.check(False)
        with self.assertRaises(helper.Rejected):
            helper.decode('{"schema":1,"schema":1}')


if __name__ == '__main__':
    unittest.main()

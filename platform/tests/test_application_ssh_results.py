"""Read-only SSH evidence projection contracts; no remote calls or native queue."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from agent_factory.application_runs import ApplicationRuns
from agent_factory.ssh_process_contract import OPERATION_PIN, LAUNCH_ADAPTER_ID, WAIT_ADAPTER_ID, LAUNCH_TOOL, WAIT_TOOL
from agent_factory.ssh_process_provider import EFFECT
from agent_factory.store import canonical, digest


class ApplicationSSHResultsTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'materials': [], 'materialRefs': [], 'tools': [LAUNCH_TOOL, WAIT_TOOL],
                     'executionBindings': {'tools': []}}
        for adapter, name in ((LAUNCH_ADAPTER_ID, LAUNCH_TOOL), (WAIT_ADAPTER_ID, WAIT_TOOL)):
            pin = {'id': adapter, 'version': 1, 'sha256': digest(adapter)}
            runtime = {'adapterId': adapter, 'revision': '1'}
            self.plan['materials'].append({**pin, 'kind': 'tool', 'runtimeBinding': runtime})
            self.plan['materialRefs'].append(pin)
            self.plan['executionBindings']['tools'].append({**runtime, 'toolName': name, 'materialRef': pin,
                'connection': {'ref': 'private-connection'}, 'config': {'profileSha256': 'a'*64}})
        launch = self.plan['executionBindings']['tools'][0]
        target = 'ssh-' + digest({'actor': 'alice', 'material': launch['materialRef'],
            'connection': launch['connection'], 'profile': 'a'*64})
        self.lease = {'id': 'lease', 'ownerId': 'alice', 'localTaskId': 'task', 'nativeRunId': 'run',
            'planId': 'plan', 'planHash': digest(self.plan), 'executionGuard': {'operationId': 'operation'},
            'executionEffect': EFFECT, 'providerJobId': 'remote-journal-job',
            'processBinding': {'taskId': 'task', 'nativeRunId': 'run', 'planId': 'plan', 'bindingFingerprint': 'b'*64},
            'executionStatus': 'COMPLETED', 'exitCode': 0,
            'stopEvidence': {'allStopped': True, 'kind': 'original-root-reaped-and-no-live-process-group-members'},
            'connectionRef': target, 'fingerprint': 'c'*64, 'targetFingerprint': 'd'*64,
            'requestId': 'original-request', 'state': 'RECLAIMED', 'axis': 'compute'}
        self.operation = {'id': 'operation', 'taskId': 'task', 'nativeRunId': 'run', 'planId': 'plan',
            'planSha256': digest(self.plan), 'adapterPin': OPERATION_PIN, 'closed': True,
            'observation': {'allStopped': True, 'state': 'COMPLETED', 'output': None}}
        self.store = Mock()
        self.store.task.side_effect = self.task
        self.store.plan.side_effect = lambda *args: self.plan
        self.store.workflow.read.side_effect = lambda *args: self.operation
        resources = SimpleNamespace(store=self.store, _body=lambda value: value)
        self.store.process_runtime.resources = resources
        self.store.sql.side_effect = self.sql
        self.blobs = {}
        self.archive()
        self.store.artifacts.side_effect = lambda task: [meta for meta, _ in self.blobs.values()]
        self.store.artifact.side_effect = self.artifact
        self.auth = Mock()
        self.service = ApplicationRuns(SimpleNamespace(store=self.store, auth=self.auth))

    def task(self, identifier, owner):
        if owner != 'alice':
            raise HTTPException(404, 'Task not found')
        return {'id': 'task', 'run_id': 'run', 'plan_id': 'plan'}

    def sql(self, query, **kwargs):
        target_id = digest({'owner': self.lease['ownerId'], 'connectionRef': self.lease['connectionRef']})
        if 'FROM af_leases' in query:
            return [{**{key: self.lease[key] for key in ('id', 'fingerprint', 'state')},
                'owner_id': self.lease['ownerId'], 'request_id': self.lease['requestId'],
                'target_id': target_id, 'body': deepcopy(self.lease)}]
        if 'FROM af_resources' in query:
            return [{'owner_id': 'alice', 'body': {'id': target_id, **{key: self.lease[key]
                for key in ('ownerId', 'connectionRef', 'axis', 'targetFingerprint')}}}]
        self.fail('Unexpected write or query: ' + query)

    def archive(self, *, never=False):
        self.blobs.clear()
        provenance = {'kind': 'ssh-process', 'operationId': 'operation', 'leaseId': 'lease',
            'providerJobId': self.lease['providerJobId'], 'nativeRunId': 'run', 'planId': 'plan',
            'executionStatus': self.lease['executionStatus'], 'verificationStatus': 'unverified'}
        def save(identifier, raw, role):
            meta = {'id': identifier, 'jobId': 'task', 'sha256': hashlib.sha256(raw).hexdigest(),
                'name': 'name-is-not-authority', 'provenance': {**provenance, 'evidenceRole': role}}
            self.blobs[identifier] = (meta, raw)
            return {'taskId': 'task', 'artifactId': identifier, 'sha256': meta['sha256']}
        output = None if never else save('output', b'synthetic original output', 'output')
        receipt = {key: self.lease[key] for key in ('providerJobId', 'processBinding', 'executionStatus',
                    'exitCode', 'stopEvidence')}
        receipt.update(schema=1, kind='ssh-process', operationId='operation', taskId='task', runId='run',
            planId='plan', leaseId='lease', allStopped=True,
            outputState='never_dispatched' if never else 'artifact', output=output)
        save('receipt', canonical(receipt).encode(), 'receipt')

    def artifact(self, task, identifier):
        if task != 'task' or identifier not in self.blobs:
            raise HTTPException(404, 'Artifact not found')
        meta, raw = self.blobs[identifier]
        if hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise HTTPException(409, 'Artifact integrity check failed')
        return deepcopy(meta), raw

    def read(self, owner='alice', task='task', run='run', operation='operation'):
        return self.service.ssh_results(owner, task, run, operation)

    def test_original_archive_is_detached_private_and_only_reads(self):
        result = self.read()
        self.assertEqual(result['receipt']['providerJobId'], 'remote-journal-job')
        self.assertEqual(result['operationId'], 'operation')
        self.assertEqual(len(result['materials']), 2)
        self.assertEqual(result['artifacts'][0]['artifactId'], 'output')
        self.assertNotIn('private-connection', json.dumps(result))
        result['receipt']['processBinding']['taskId'] = 'changed'
        self.assertEqual(self.read()['receipt']['processBinding']['taskId'], 'task')
        allowed = {'task', 'plan', 'workflow.read', 'artifacts', 'artifact', 'sql'}
        self.assertTrue(all(call[0] in allowed for call in self.store.mock_calls), self.store.mock_calls)

    def test_member_owner_alias_run_and_foreign_operation_are_rejected(self):
        for args in [('bob', 'task', 'run', 'operation'), ('alice', 'run', 'run', 'operation'),
                     ('alice', 'task', 'wrong', 'operation'), ('alice', 'task', 'run', 'foreign')]:
            with self.subTest(args=args), self.assertRaises(HTTPException):
                self.read(*args)
        self.auth.require_member.side_effect = HTTPException(403, 'disabled')
        with self.assertRaises(HTTPException):
            self.read()

    def test_operation_lease_material_and_archive_mismatches_are_rejected(self):
        mutations = [lambda: self.operation.update(closed=False),
            lambda: self.operation.update(adapterPin={**OPERATION_PIN, 'revision': '2'}),
            lambda: self.lease['executionGuard'].update(operationId='foreign'),
            lambda: self.lease.update(providerJobId='foreign'),
            lambda: self.lease['stopEvidence'].update(kind='unproved'),
            lambda: self.lease['processBinding'].update(nativeRunId='foreign'),
            lambda: self.plan['executionBindings']['tools'][1].update(revision='2'),
            lambda: self.blobs['output'][0]['provenance'].update(operationId='foreign'),
            lambda: self.blobs.pop('output')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.setUp()
                mutate()
                with self.assertRaises(HTTPException):
                    self.read()

    def test_stopped_negative_result_reads_archive_without_success_output(self):
        for status, state in [('FAILED', 'FAILED'), ('CANCELLED', 'CANCELLED'), ('LIMIT_STOPPED', 'FAILED')]:
            with self.subTest(status=status):
                self.lease.update(executionStatus=status, exitCode=1)
                self.operation['observation'].update(state=state, output=None)
                self.archive()
                self.assertEqual(self.read()['receipt']['executionStatus'], status)

    def test_never_dispatched_requires_exact_stop_proof_and_no_output(self):
        self.lease.update(executionStatus='CANCELLED', exitCode=None,
            stopEvidence={'allStopped': True, 'kind': 'never-dispatched'})
        self.operation['observation'].update(state='CANCELLED', output=None)
        self.archive(never=True)
        self.assertEqual(self.read()['artifacts'], [])
        self.lease['stopEvidence']['kind'] = 'original-root-reaped-and-no-live-process-group-members'
        self.archive(never=True)
        with self.assertRaises(HTTPException):
            self.read()

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from agent_factory.ssh_operation_runtime import SSHOperationRuntime


class SSHOperationProjectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = SSHOperationRuntime(SimpleNamespace(), SimpleNamespace(auth=None), None, {})
        self.body = {'id': 'original-operation', 'taskId': 'original-child'}
        self.lease = {'id': 'original-lease', 'executionGuard': {'operationId': self.body['id']},
                      'state': 'RECLAIMED', 'executionStatus': 'COMPLETED'}
        self.runtime._original = Mock(return_value={'lease_id': self.lease['id']})
        self.runtime._custody = Mock(side_effect=lambda _: (self.lease, None, None, None))
        self.runtime.observe_lease = AsyncMock(side_effect=lambda _: self.lease)
        self.receipt = {'kind': 'ssh-process', 'taskId': 'original-child', 'runId': 'original-run',
            'leaseId': self.lease['id'], 'providerJobId': 'remote-journal',
            'executionStatus': 'COMPLETED', 'exitCode': 0,
            'output': {'taskId': 'original-child', 'artifactId': 'archived-log', 'sha256': 'a' * 64}}
        self.runtime._archive = AsyncMock(side_effect=lambda _: self.receipt)

    async def test_success_preserves_distinct_operation_lease_and_remote_identities(self):
        result = await self.runtime._observe(self.body)
        self.assertEqual(result['handle']['id'], 'original-operation')
        self.assertEqual(result['output']['leaseId'], 'original-lease')
        self.assertEqual(result['output']['providerJobId'], 'remote-journal')
        self.assertEqual(result['output']['artifacts'], [self.receipt['output']])

    async def test_stopped_negative_results_are_archived_without_nonconforming_output(self):
        for status, expected in (('FAILED', 'FAILED'), ('LIMIT_STOPPED', 'FAILED'), ('CANCELLED', 'CANCELLED')):
            self.receipt['executionStatus'] = status
            result = await self.runtime._observe(self.body)
            self.assertEqual(result['state'], expected)
            self.assertTrue(result['allStopped'])
            self.assertIsNone(result['output'])
        self.assertEqual(self.runtime._archive.await_count, 3)

    async def test_unknown_or_absent_original_never_allocates_or_closes(self):
        self.lease.update(state='UNKNOWN', executionStatus='UNKNOWN')
        self.assertFalse((await self.runtime._observe(self.body))['allStopped'])
        self.runtime._original.return_value = None
        self.assertEqual((await self.runtime._observe(self.body))['state'], 'UNKNOWN')
        self.runtime._archive.assert_not_awaited()

    async def test_archive_failure_does_not_return_terminal_custody(self):
        self.runtime._archive.side_effect = OSError('synthetic archive unavailable')
        with self.assertRaises(OSError):
            await self.runtime._observe(self.body)

    async def test_foreign_operation_lease_rejected_before_observation(self):
        self.lease['executionGuard']['operationId'] = 'foreign-operation'
        with self.assertRaises(HTTPException):
            await self.runtime._observe(self.body)
        self.runtime.observe_lease.assert_not_awaited()


class SSHPersonalTargetTests(unittest.TestCase):
    def setUp(self):
        from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
        from agent_factory.resources import ComputePool
        from agent_factory.ssh_operation_runtime import SSHTrainingProfile
        from agent_factory.ssh_process_contract import LAUNCH_ADAPTER_ID, LAUNCH_TOOL
        self.profile = SSHTrainingProfile(ProcessSpec('/bin/train', 'a' * 64, ()), ProcessLimits(),
            '/runtime/python', ComputePool('configured', 2, 2048, 1024))
        self.pin = {'ref': 'original-connection', 'version': 1, 'revision': '1',
                    'fingerprint': 'b' * 64}
        self.spec = {'toolName': LAUNCH_TOOL, 'adapterId': LAUNCH_ADAPTER_ID, 'revision': '1',
            'materialRef': {'id': 'train-tool', 'version': '1', 'sha256': 'c' * 64},
            'config': {'connectionName': 'compute', 'profileId': 'fixed',
                       'profileSha256': self.profile.fingerprint}, 'connection': self.pin}
        self.connections = SimpleNamespace(preflight=Mock(),
            inspect=Mock(return_value={'registrationRef': 'personal-server'}))
        self.store = SimpleNamespace(execution_bindings=SimpleNamespace(
            manifest=Mock(return_value={'tools': [self.spec]}), connections=self.connections))
        self.resources = SimpleNamespace(auth=None, register_target=Mock())
        self.server = SimpleNamespace(validate=lambda: None, host_key='synthetic-host-key', name='selected',
            allowed_root='/private/runs', pin=lambda: 'd' * 64)
        self.personal = SimpleNamespace(server=Mock(return_value=self.server), lease=Mock())
        self.runtime = SSHOperationRuntime(self.store, self.resources, self.personal, {'fixed': self.profile})
        self.task = {'id': 'child', 'run_id': 'native-run', 'owner_id': 'alice',
                     'plan_id': 'plan', 'request_id': 'request'}

    def test_original_connection_pin_checked_before_personal_ssh_target_registration(self):
        ref = self.runtime.ensure_target(self.task, {})
        self.connections.preflight.assert_called_once_with('alice', 'original-connection',
            expected_kind='environment', expected_revision='1', expected_fingerprint='b' * 64,
            expected_version=1, required_capabilities=('ssh:execute',), task_id='child',
            expected_adapter_ref='owner-ssh-server-v1')
        self.personal.server.assert_called_once_with('alice', 'personal-server', required_capability='ssh:execute')
        target = self.resources.register_target.call_args.args[1]
        target.provider.exchange.lease_for('inspect')
        self.personal.lease.assert_called_once_with(self.server, required_capability='ssh:execute')
        self.assertEqual(target.owners, frozenset({'alice'}))
        self.assertEqual(self.resources.register_target.call_args.args[0], ref)
        self.assertNotEqual(ref, self.runtime._selected({**self.task, 'owner_id': 'bob'}, {})[2])

    def test_changed_profile_or_revoked_connection_never_registers_target(self):
        self.spec['config']['profileSha256'] = 'e' * 64
        with self.assertRaises(HTTPException):
            self.runtime.ensure_target(self.task, {})
        self.personal.server.assert_not_called()
        self.spec['config']['profileSha256'] = self.profile.fingerprint
        self.connections.preflight.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            self.runtime.ensure_target(self.task, {})
        self.resources.register_target.assert_not_called()


class SSHPreparedArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_never_launched_journal_archives_explicit_absence_then_reclaims(self):
        from contextlib import nullcontext
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from agent_factory.process_enforcement import BoundedProcessAdapter
        from agent_factory.resources import PersistentResourceService
        from agent_factory.ssh_process_contract import encoded, MAX_REQUEST_BYTES
        from agent_factory.ssh_process_helper import handle
        import test_ssh_process_provider as provider_fixtures

        fixture = provider_fixtures.SSHProcessProviderTests()
        fixture.setUp()
        with TemporaryDirectory() as folder:
            fixture.provider.server.allowed_root = folder
            sent = fixture.provider._request(fixture.lease, 'submit')
            directory = Path(folder) / fixture.lease['id']
            directory.mkdir(mode=0o700)
            descriptor = {key: sent[key] for key in ('protocol', 'binding', 'root', 'spec', 'limits')}
            (directory / 'binding.json').write_bytes(encoded(descriptor, MAX_REQUEST_BYTES))
            journal = BoundedProcessAdapter.create(directory / 'custody.sqlite', owner_id='alice',
                task_id=fixture.lease['localTaskId'], request_id=fixture.lease['requestId'],
                spec=fixture.provider.spec, limits=fixture.provider.limits)
            self.assertEqual(journal.inspect(owner_id='alice')['state'], 'PREPARED')
            fixture.provider.exchange = lambda request, **_: handle(request)
            stopped = await fixture.provider.cancel(fixture.lease['id'], 'alice')
            self.assertEqual(stopped['stopEvidence']['kind'], 'never-dispatched')
            self.assertFalse((directory / 'custody.output').exists())
            fixture.lease.update(PersistentResourceService.process_snapshot(fixture.lease, stopped),
                                 state=stopped['state'])
            artifacts = {}
            def write(task, name, raw, media, provenance):
                identity = 'artifact-' + str(len(artifacts))
                metadata = {'id': identity, 'name': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                            'provenance': provenance}
                artifacts[identity] = (metadata, raw)
                return metadata
            store = SimpleNamespace(transaction=nullcontext,
                workflow=SimpleNamespace(_lock_task=lambda *args: None),
                artifacts=lambda task: [a[0] for a in artifacts.values()],
                artifact=lambda task, identity: artifacts[identity], artifact_write=write)
            runtime = SSHOperationRuntime(store, SimpleNamespace(auth=None), None, {})
            runtime._custody = lambda key: (fixture.lease, SimpleNamespace(provider=fixture.provider), None, None)
            receipt = await runtime._archive(fixture.lease)
            self.assertEqual(receipt['outputState'], 'never_dispatched')
            self.assertIsNone(receipt['output'])
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(await runtime._archive(fixture.lease), receipt)
            released = await fixture.provider.reclaim(fixture.lease['id'], 'alice')
            self.assertTrue(released['released'])
            self.assertEqual(released['state'], 'RECLAIMED')
            self.assertEqual(journal.inspect(owner_id='alice')['child'], None)

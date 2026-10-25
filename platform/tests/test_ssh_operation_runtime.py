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
        self.profile = SSHTrainingProfile(ProcessSpec('/bin/train', 'a' * 64, (), path_style='posix'), ProcessLimits(),
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
        self.assertNotEqual(ref, self.runtime.ensure_target({**self.task, 'owner_id': 'bob'}, {}))

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


    def input_profile(self, *, max_length=100, argv=()):
        from dataclasses import replace
        from agent_factory.ssh_operation_runtime import SSHTrainingProfile
        profile = SSHTrainingProfile(replace(self.profile.spec, argv=argv), self.profile.limits,
            self.profile.interpreter, self.profile.pool,
            input_schema={'type': 'object', 'properties': {'condition': {'type': 'string', 'maxLength': max_length}},
                          'required': ['condition'], 'additionalProperties': False}, input_argument='--experiment-json')
        self.runtime.profiles['fixed'] = profile
        self.spec['config']['profileSha256'] = profile.fingerprint
        return profile

    def test_distinct_experiment_inputs_reach_fixed_argv_without_shell_or_pool_split(self):
        import json
        profile = self.input_profile()
        values = [{'condition': 'first'}, {'condition': '\"; $(not-a-command) \n second'}]
        refs = [self.runtime.ensure_target(self.task, {}, item) for item in values]
        targets = [call.args[1] for call in self.resources.register_target.call_args_list]
        self.assertNotEqual(refs[0], refs[1])
        self.assertEqual(targets[0].capacity_pool, targets[1].capacity_pool)
        for target, value in zip(targets, values):
            self.assertEqual(target.provider.spec.executable, profile.spec.executable)
            self.assertEqual(target.provider.spec.argv[-2], '--experiment-json')
            self.assertEqual(json.loads(target.provider.spec.argv[-1]), value)
            self.assertEqual(len(target.provider.spec.argv), 2)

    def test_input_schema_and_complete_argv_limits_fail_before_any_ssh_target(self):
        from agent_factory.process_enforcement import ProcessEnforcementError
        self.input_profile(max_length=16000)
        for value in ({'unknown': 'field'}, {'condition': 1}, {'condition': 'x' * 9000}):
            with self.subTest(value=str(value)[:40]), self.assertRaises((ValueError, ProcessEnforcementError)):
                self.runtime.ensure_target(self.task, {}, value)
        self.input_profile(argv=tuple('arg' for _ in range(31)))
        with self.assertRaises(ProcessEnforcementError):
            self.runtime.ensure_target(self.task, {}, {'condition': 'small'})
        self.personal.server.assert_not_called()
        self.resources.register_target.assert_not_called()

    def test_profile_requires_schema_argument_pair_and_fixed_profile_rejects_input(self):
        from dataclasses import replace
        with self.assertRaises(HTTPException):
            replace(self.profile, input_argument='--unexpected')
        with self.assertRaises(HTTPException):
            self.profile.prepare({'condition': 'not-declared'})

    def test_restore_uses_persisted_original_inputs_and_rejects_modified_receipt(self):
        from agent_factory.store import digest
        self.input_profile()
        values = {'condition': 'original'}
        reference = self.runtime.ensure_target(self.task, {}, values)
        original_input = {'targetRef': reference, 'callId': 'call-1', 'inputs': values}
        operation = {'adapterPin': self.runtime.pin, 'taskId': self.task['id'],
                     'nativeRunId': self.task['run_id'], 'inputs': original_input,
                     'inputsSha256': digest(original_input)}
        lease = {'connectionRef': reference, 'executionEffect': self.runtime.effect_key,
            'localTaskId': self.task['id'], 'planId': 'plan', 'nativeRunId': self.task['run_id'],
            'planHash': digest({}), 'executionGuard': {'operationId': 'operation'}}
        self.store.sql = Mock(return_value=[{'body': lease}])
        self.store.task, self.store.plan = Mock(return_value=self.task), Mock(return_value={})
        self.store.workflow = SimpleNamespace(_load=Mock(return_value=operation), _identity=Mock())
        self.resources._body = lambda value: value
        target = self.resources.register_target.call_args.args[1]
        self.resources.targets = {reference: target}
        self.assertIs(self.runtime.restore_target('alice', reference), target)
        recovered = self.resources.register_target.call_args.args[1]
        self.assertEqual(recovered.provider.spec.argv, target.provider.spec.argv)
        operation['inputs']['inputs'] = {'condition': 'replacement'}
        before = self.resources.register_target.call_count
        with self.assertRaises(HTTPException):
            self.runtime.restore_target('alice', reference)
        self.assertEqual(self.resources.register_target.call_count, before)


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


class SSHLaunchPreflightTests(unittest.IsolatedAsyncioTestCase):
    setUp = SSHPersonalTargetTests.setUp

    def prepare_launch(self):
        self.store.settings = SimpleNamespace(experiment_output_bytes=65536)
        self.store.authorize_tool = Mock()
        self.store.task, self.store.plan = Mock(return_value=self.task), Mock(return_value={})
        self.store.sql = Mock(return_value=[])
        self.store.workflow = SimpleNamespace(start=AsyncMock(return_value={'id': 'original-operation'}), read=Mock())
        self.resources.targets = {}
        def register(reference, target):
            self.resources.targets[reference] = target
            return target
        self.resources.register_target.side_effect = register
        self.resources._authorize = lambda owner, reference: self.resources.targets[reference]
        self.resources._provider = lambda target: target.provider
        return self.runtime._context(self.task)

    @staticmethod
    def capabilities():
        from agent_factory.ssh_process_contract import PROTOCOL
        return {'protocol': PROTOCOL, 'platform': 'linux', 'rootReady': True,
            'fork': True, 'proc': True, 'rlimits': True, 'processCustody': True,
            'scheduler': False, 'gpuAllocation': False, 'automaticInstallation': False,
            'isolation': {'aggregateQuota': False, 'hostileCodeSandbox': False, 'networkIsolation': False}}

    async def test_capabilities_precede_original_intent_with_read_only_root_request(self):
        from unittest.mock import patch
        context = self.prepare_launch()
        actions = []
        def exchange(transport, value, *, before_effect):
            before_effect()
            actions.append(value['action'])
            self.assertEqual(value['root'], self.server.allowed_root)
            self.assertEqual(set(value), {'protocol', 'action', 'root'})
            return self.capabilities()
        async def start(*args, **kwargs):
            actions.append('intent')
            self.assertTrue(kwargs['retain_inputs'])
            return {'id': 'original-operation'}
        self.store.workflow.start.side_effect = start
        with patch('agent_factory.ssh_process_provider.SSHProcessTransport.__call__', exchange):
            await self.runtime.launch(context, 'original-call', {})
        self.assertEqual(actions, ['capabilities', 'intent'])

    async def test_missing_helper_version_or_mechanism_creates_no_intent(self):
        from unittest.mock import patch
        context = self.prepare_launch()
        failures = [FileNotFoundError('synthetic helper absent'),
                    {**self.capabilities(), 'protocol': 'wrong'},
                    {**self.capabilities(), 'rlimits': False},
                    {**self.capabilities(), 'rootReady': False}]
        for failure in failures:
            def exchange(transport, value, *, before_effect):
                if isinstance(failure, Exception):
                    raise failure
                return failure
            with self.subTest(failure=failure), patch(
                    'agent_factory.ssh_process_provider.SSHProcessTransport.__call__', exchange):
                with self.assertRaisesRegex(ValueError, 'SSH_PROCESS_PREFLIGHT_UNAVAILABLE'):
                    await self.runtime.launch(context, 'original-call', {})
        self.store.workflow.start.assert_not_awaited()

    async def test_original_unknown_replay_skips_preflight_and_target_recreation(self):
        from unittest.mock import patch
        context = self.prepare_launch()
        self.store.sql.return_value = [{'id': 'original-operation'}]
        self.store.workflow.read.return_value = {'stepId': 'ssh-process-launch'}
        self.store.settings.experiment_output_bytes = 1024
        original = {'id': 'original-operation', 'closed': False, 'observation': None}
        self.store.workflow.start.return_value = original
        with patch('agent_factory.ssh_process_provider.SSHProcessTransport.__call__',
                   side_effect=AssertionError('Original replay must not preflight')):
            self.assertIs(await self.runtime.launch(context, 'original-call', {}), original)
        self.resources.register_target.assert_not_called()

    async def test_output_archive_boundaries_precede_all_new_effects(self):
        from dataclasses import replace
        from unittest.mock import patch
        from agent_factory.process_enforcement import ResearchProcessLimits, ResearchProcessSpec
        from agent_factory.ssh_process_contract import OUTPUT_BYTES
        context = self.prepare_launch()
        cases = [
            (65535, self.profile.limits, False),
            (65536, self.profile.limits, True),
            (65536, ResearchProcessLimits(output_bytes=65536), True),
            (65536, ResearchProcessLimits(output_bytes=65537), False),
            (OUTPUT_BYTES * 2, ResearchProcessLimits(output_bytes=OUTPUT_BYTES), True),
            (OUTPUT_BYTES * 2, ResearchProcessLimits(output_bytes=OUTPUT_BYTES + 1), False),
            (65536, ResearchProcessLimits(), False),
        ]
        for local_limit, limits, accepted in cases:
            with self.subTest(local_limit=local_limit, limits=limits, accepted=accepted):
                process_spec = self.profile.spec
                if isinstance(limits, ResearchProcessLimits):
                    process_spec = ResearchProcessSpec('/bin/train', 'a' * 64, (), path_style='posix',
                        working_directory='/private/work', working_directory_identity=(1, 2),
                        environment=tuple((name, '1') for name in (
                            'HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE')))
                profile = replace(self.profile, spec=process_spec, limits=limits)
                self.runtime.profiles['fixed'] = profile
                self.spec['config']['profileSha256'] = profile.fingerprint
                self.store.settings.experiment_output_bytes = local_limit
                self.resources.register_target.reset_mock()
                self.store.workflow.start.reset_mock()
                with patch('agent_factory.ssh_process_provider.SSHProcessTransport.__call__',
                           return_value=self.capabilities()) as transport:
                    if accepted:
                        await self.runtime.launch(context, 'original-call', {})
                        self.store.workflow.start.assert_awaited_once()
                        self.assertEqual(transport.call_args.args[0]['action'], 'capabilities')
                    else:
                        with self.assertRaisesRegex(ValueError, 'SSH_PROCESS_OUTPUT_LIMIT_UNSUPPORTED'):
                            await self.runtime.launch(context, 'original-call', {})
                        transport.assert_not_called()
                        self.resources.register_target.assert_not_called()
                        self.store.workflow.start.assert_not_awaited()

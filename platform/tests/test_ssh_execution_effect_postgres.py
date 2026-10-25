"""Original lease metadata contract, not SSH/native execution acceptance."""
import os
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from agent_factory.resources import ComputePool, PersistentResourceService, RemoteTarget
import test_process_runtime_postgres as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class SSHExecutionEffectPostgresTests(unittest.TestCase):
    setUp = fixtures.ProcessRuntimeTransactionPostgresTests.setUp

    def service(self, effect):
        runtime = SimpleNamespace(validate_execution=lambda *args: self.validations.append(args))
        target = RemoteTarget('Metadata-only fixture', 'compute', frozenset({'alice'}),
            provider=fixtures.MustNotAllocate(), synthetic_fixture=True,
            capacity_pool=ComputePool('effect-metadata', 1, 128, 1, max_leases=1, max_owner_leases=1))
        resources = PersistentResourceService(self.store, SimpleNamespace(require_member=lambda *args: None), {'fixed': target})
        if effect == 'bounded-process-run-v1':
            self.store.process_runtime = runtime
        else:
            resources.execution_runtimes[effect] = runtime
        return resources

    def reserve(self, effect, requirement=None):
        self.validations = []
        resources = self.service(effect)
        execution = {'nativeRunId': self.run_id, 'effectKey': effect}
        if requirement is not None:
            execution['requirement'] = requirement
        args = ('alice', 'fixed', self.task['id'], 'exact-original-request',
                {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 1})
        first, created = resources._reserve(*args, execution=execution)
        self.assertTrue(created)
        self.assertEqual(first['executionEffect'], effect)
        if requirement is None:
            self.assertNotIn('executionGuard', first)
        else:
            self.assertEqual(first['executionGuard'], requirement)
        reopened = self.service(effect)
        again, created = reopened._reserve(*args, execution=execution)
        self.assertFalse(created)
        self.assertEqual(again, first)
        self.assertEqual(len(self.validations), 2)
        self.assertEqual(len(self.store.sql('SELECT id FROM af_leases')), 1)
        self.assertEqual(len(self.store.sql('SELECT lease_id FROM af_process_runs')), 1)

    def test_new_ssh_effect_keeps_original_operation_guard_on_restart(self):
        self.reserve('ssh-process-run-v1', {'operationId': 'original-operation'})

    def test_existing_bounded_effect_has_no_invented_guard(self):
        self.reserve('bounded-process-run-v1')

    def test_unregistered_effect_is_rejected_before_reservation(self):
        self.validations = []
        resources = self.service('ssh-process-run-v1')
        with self.assertRaises(HTTPException) as denied:
            resources._reserve('alice', 'fixed', self.task['id'], 'unknown-effect',
                {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 1},
                execution={'nativeRunId': self.run_id, 'effectKey': 'unregistered'})
        self.assertEqual(denied.exception.detail, 'PROCESS_EXECUTION_EFFECT_UNSUPPORTED')
        self.assertEqual(self.validations, [])
        self.assertEqual(self.store.sql('SELECT id FROM af_leases'), [])

    def test_original_operation_cancel_uses_persistent_claim_and_stopped_journal(self):
        self.exercise_original_cancel_and_archive()

    def test_public_reclaim_holds_until_original_archive_then_inspect_releases(self):
        self.exercise_original_cancel_and_archive(public_reclaim=True)

    def exercise_original_cancel_and_archive(self, *, public_reclaim=False):
        """Actual claim/observe/archive SQL; native authority is an explicit fixture port."""
        import asyncio
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec
        from agent_factory.ssh_operation_runtime import SSHOperationRuntime
        from agent_factory.ssh_process_contract import encoded, MAX_REQUEST_BYTES
        from agent_factory.ssh_process_helper import handle
        from agent_factory.ssh_process_provider import SSHProcessProvider, EFFECT
        with TemporaryDirectory() as folder:
            server = SimpleNamespace(validate=lambda: None, host_key='synthetic-host-key',
                pin=lambda: 'a' * 64, allowed_root=folder)
            provider = SSHProcessProvider(server, target_ref='fixed',
                spec=ProcessSpec('/bin/not-launched', 'b' * 64, (), path_style='posix'), limits=ProcessLimits(),
                exchange=lambda value, **_: handle(value), read_lease=lambda owner, key: current(),
                archive_original=lambda owner, key: runtime._archive(current()))
            target = RemoteTarget('Real stopped journal fixture', 'compute', frozenset({'alice'}),
                provider=provider, max_seconds=33,
                capacity_pool=ComputePool('original-stop', 1, 128, 1, max_leases=1, max_owner_leases=1))
            resources = PersistentResourceService(self.store, SimpleNamespace(require_member=lambda *args: None),
                                                   {'fixed': target})
            resources.execution_runtimes[EFFECT] = SimpleNamespace(validate_execution=lambda *args: None)
            lease, _ = resources._reserve('alice', 'fixed', self.task['id'], 'original-cancel-request',
                {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 33},
                execution={'nativeRunId': self.run_id, 'effectKey': EFFECT,
                           'requirement': {'operationId': 'original-operation'}})
            def current():
                return resources._body(self.store.sql('SELECT body FROM af_leases WHERE id=:id',
                                                     id=lease['id'])[0]['body'])
            request = provider._request(lease, 'submit')
            directory = Path(folder) / lease['id']
            directory.mkdir(mode=0o700)
            (directory / 'binding.json').write_bytes(encoded({k: request[k]
                for k in ('protocol', 'binding', 'root', 'spec', 'limits')}, MAX_REQUEST_BYTES))
            journal = BoundedProcessAdapter.create(directory / 'custody.sqlite', owner_id='alice',
                task_id=self.task['id'], request_id=lease['requestId'], spec=provider.spec, limits=provider.limits)
            self.store.workflow = SimpleNamespace(_load=lambda *args: {'cancelRequested': True},
                                                  _lock_task=lambda *args: None)
            runtime = SSHOperationRuntime(self.store, resources, None, {})
            runtime._custody = lambda key: (current(), target, self.task, {'status': 'running'})
            resources.execution_runtimes[EFFECT] = runtime
            if public_reclaim:
                from unittest.mock import AsyncMock, patch
                cancelled = asyncio.run(provider.cancel(lease['id'], 'alice'))
                resources._observe('alice', lease['id'], cancelled)
                with patch.object(runtime, '_archive', AsyncMock(side_effect=OSError('fixture archive unavailable'))):
                    failed = asyncio.run(resources.reclaim('alice', lease['id']))
                self.assertNotEqual(failed['state'], 'RECLAIMED')
                self.assertTrue(failed['capacityHeld'])
                self.assertEqual(failed['releaseAck'], 'unknown')
                self.assertEqual(self.store.artifacts(self.task['id']), [])
                stopped = asyncio.run(runtime.observe_lease(lease['id']))
            else:
                stopped = asyncio.run(runtime.observe_lease(lease['id']))
                self.assertEqual(stopped['cancellationReason'], 'OPERATION_CANCEL_REQUESTED')
                self.assertTrue(stopped['cancelRequested'])
            self.assertEqual(stopped['state'], 'RECLAIMED')
            self.assertFalse(stopped['capacityHeld'])
            self.assertEqual(journal.inspect(owner_id='alice')['stopReceipt']['kind'], 'never-dispatched')
            self.assertFalse((directory / 'custody.output').exists())
            artifacts = self.store.artifacts(self.task['id'])
            self.assertEqual(len(artifacts), 1)
            receipt = __import__('json').loads(self.store.artifact(self.task['id'], artifacts[0]['id'])[1])
            self.assertEqual(receipt['outputState'], 'never_dispatched')
            self.assertIsNone(receipt['output'])
            again = asyncio.run(runtime.observe_lease(lease['id']))
            self.assertEqual(again['id'], lease['id'])
            self.assertEqual(len(self.store.artifacts(self.task['id'])), 1)

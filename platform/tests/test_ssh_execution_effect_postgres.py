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

"""Cancellation at storage preparation must preserve exact dispatch custody."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agno.run import RunContext
from fastapi import HTTPException

from agent_factory_research import tools
import test_factory_postgres as fixture
from test_runtime_contract import ContractStore  # pyright: ignore[reportMissingImports]


class SyntheticStorageCancelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = SimpleNamespace(runtime_directory=Path(self.directory.name) / 'runtime',
            experiment_timeout_seconds=1, experiment_output_bytes=65536)
        self.store = ContractStore(mode='experiment')
        self.context = RunContext(run_id='storage-native-run', session_id='storage-task', user_id='test-user')
        self.store.bind_run(self.context)
        self.function = tools.build_tools(self.settings, self.store)['run_experiment']
        self.key = (self.context.run_id, 'experiment:bounded-sort-v1')

    async def invoke(self):
        return await self.function.entrypoint(experiment='bounded-sort-v1', run_context=self.context)

    async def test_persisted_cancel_while_storage_is_preparing_settles_never_dispatched_effect(self):
        entered, release = threading.Event(), threading.Event()
        denied = HTTPException(409, 'Stopped tasks cannot create storage')

        def prepare_storage(*args):
            self.assertEqual(self.store.effects[self.key]['status'], 'unknown')
            entered.set()
            if not release.wait(10):
                raise AssertionError('Test did not release storage preparation')
            self.assertTrue(self.store.cancellation_requested(self.context.run_id))
            raise denied

        self.store.storage = SimpleNamespace(directory=Mock(side_effect=prepare_storage))
        with patch.object(tools.subprocess, 'Popen') as launch:
            pending = asyncio.create_task(self.invoke())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 10))
                self.store.cancelled = True
            finally:
                release.set()
            with self.assertRaises(HTTPException) as raised:
                await pending
            launch.assert_not_called()
        self.assertIs(raised.exception, denied)
        self.assertEqual(self.store.effects[self.key], {'status': 'done', 'result': {
            'cancelled': True, 'cleanupComplete': True,
            'runtimeId': 'local-python-bounded-v1', 'dispatchState': 'never-dispatched'}})
        self.assertFalse(self.store.artifacts)
        self.assertFalse(any(event['type'] in {'compute_started', 'compute_stopped', 'effect_unknown'}
                             for event in self.store.events))
        self.assertTrue(any(event['type'] == 'compute_cancelled' for event in self.store.events))

    async def test_storage_denied_without_persisted_cancel_remains_unknown(self):
        self.store.storage = SimpleNamespace(directory=Mock(side_effect=HTTPException(409, 'Storage unavailable')))
        with patch.object(tools.subprocess, 'Popen') as launch:
            with self.assertRaises(HTTPException):
                await self.invoke()
            launch.assert_not_called()
        self.assert_unknown()

    async def test_persisted_cancel_cannot_settle_an_unacknowledged_launch(self):
        def ambiguous_launch(*args, **kwargs):
            self.store.cancelled = True
            raise HTTPException(409, 'Synthetic launch acknowledgement lost')

        with patch.object(tools.subprocess, 'Popen', side_effect=ambiguous_launch) as launch:
            with self.assertRaises(HTTPException):
                await self.invoke()
            launch.assert_called_once()
        self.assert_unknown()

    async def test_never_dispatched_without_cleanup_proof_remains_unknown(self):
        def incomplete_outcome(*args):
            self.store.cancelled = True
            return {'ok': False, 'error': HTTPException(409, 'Incomplete adapter proof'),
                    'cleanupComplete': False, 'neverDispatched': True}

        with patch.object(tools, '_experiment_outcome', side_effect=incomplete_outcome), \
             patch.object(tools.subprocess, 'Popen') as launch:
            with self.assertRaises(HTTPException):
                await self.invoke()
            launch.assert_not_called()
        self.assert_unknown()

    async def test_postdispatch_failure_with_cancel_and_cleanup_is_not_never_dispatched(self):
        process = Mock(pid=12345, returncode=1)
        process.poll.return_value = 1
        process.wait.return_value = 1

        def failed_process(*args, **kwargs):
            self.store.cancelled = True
            return process

        with patch.object(tools.subprocess, 'Popen', side_effect=failed_process) as launch, \
             patch.object(tools, '_WindowsJob'), patch.object(tools.os, 'killpg', create=True):
            with self.assertRaisesRegex(RuntimeError, 'Bounded experiment failed'):
                await self.invoke()
            launch.assert_called_once()
        process.wait.assert_called_once_with(timeout=2)
        self.assertTrue(any(event['type'] == 'compute_stopped' for event in self.store.events))
        self.assert_unknown()

    def assert_unknown(self):
        self.assertEqual(self.store.effects[self.key]['status'], 'unknown')
        self.assertIsNone(self.store.effects[self.key]['result'])
        self.assertFalse(self.store.artifacts)
        self.assertTrue(any(event['type'] == 'effect_unknown' for event in self.store.events))
        self.assertFalse(any(event['type'] == 'compute_cancelled' for event in self.store.events))


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class SyntheticStorageCancelPostgresTests(unittest.TestCase):
    login = fixture.FactoryPostgresTests.login
    plan = fixture.FactoryPostgresTests.plan
    submit = fixture.FactoryPostgresTests.submit
    wait = fixture.FactoryPostgresTests.wait

    @classmethod
    def setUpClass(cls):
        fixture.FactoryPostgresTests.setUpClass.__func__(cls)
        cls.store = cls.app.app.state.factory['store']

    @classmethod
    def tearDownClass(cls):
        fixture.FactoryPostgresTests.tearDownClass.__func__(cls)

    def test_cancel_between_effect_reservation_and_storage_allocation_has_positive_stop_proof(self):
        self.login()
        plan, _ = self.plan('Evaluate the controlled sorting candidate', 'experiment')
        task, _ = self.submit(plan)
        task_id = task['id']
        self.addCleanup(lambda: self.client.post(f'/api/factory/jobs/{task_id}/cancel'))
        detail = self.wait(task_id, {'waiting_approval'})
        approval = detail['job']['approvalDetail']
        run_id = self.store.task(task_id)['run_id']
        entered, release = threading.Event(), threading.Event()
        original = self.store.storage.directory
        denied = []

        def prepare_storage(identifier, key, **kwargs):
            if identifier == run_id and key == 'synthetic-runtime':
                self.assertEqual(self.store.effects(task_id)[0]['status'], 'UNKNOWN')
                entered.set()
                if not release.wait(10):
                    raise AssertionError('Test did not release storage preparation')
                self.assertTrue(self.store.cancellation_requested(run_id))
                try:
                    return original(identifier, key, **kwargs)
                except HTTPException as error:
                    denied.append((error.status_code, error.detail))
                    raise
            return original(identifier, key, **kwargs)

        with patch.object(self.store.storage, 'directory', side_effect=prepare_storage), \
             patch.object(tools.subprocess, 'Popen') as launch:
            try:
                response = self.client.post(f'/api/factory/jobs/{task_id}/approve', json={
                    'requirementId': approval['id'], 'version': approval['version'], 'approved': True})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(entered.wait(10), 'Native continuation did not reach storage preparation')
                response = self.client.post(f'/api/factory/jobs/{task_id}/cancel')
                self.assertEqual(response.status_code, 200, response.text)
            finally:
                release.set()
            detail = self.wait(task_id, {'canceled'})
            launch.assert_not_called()
        self.assertEqual(denied, [(409, 'Stopped tasks cannot create storage')])
        self.assertTrue(self.store.task(task_id)['terminal'])
        effects = self.store.effects(task_id)
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]['status'], 'CANCELLED')
        self.assertEqual(effects[0]['result'], {'cancelled': True, 'cleanupComplete': True,
            'runtimeId': 'local-python-bounded-v1', 'dispatchState': 'never-dispatched'})
        self.assertFalse(any(event['type'] in {'compute_started', 'compute_stopped', 'effect_unknown'}
                             for event in detail['events']))
        self.assertTrue(detail['snapshot']['delegation']['allStopped'])


if __name__ == '__main__':
    unittest.main()

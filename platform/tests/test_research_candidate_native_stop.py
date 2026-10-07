"""Native stop orchestration unit tests: no worker start, process, DB or model."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

_spec = importlib.util.spec_from_file_location('native_stop_under_test',
    Path(__file__).resolve().parents[2] / 'scripts/research_candidate_native_stop.py')
assert _spec is not None and _spec.loader is not None
subject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(subject)


class NativeStopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.expected = dict(ownerId='alice', taskId='task-original', nativeRunId='run-original',
            planId='plan-original', requestId='request-original')
        self.task = dict(owner_id='alice', id='task-original', run_id='run-original',
            plan_id='plan-original', request_id='request-original', cancel_requested=True)
        self.plan = dict(application='research-process-fixture-v1', applicationRef={'id': 'research-process-fixture-v1'},
            mode='controlled-fixture', tools=['research_process_run'], capabilities=['compute:local'])
        self.before = dict(id='run-original', status='paused', persistedRunStatus='paused')
        self.after = dict(id='run-original', status='cancelled', persistedRunStatus='cancelled')
        self.store = SimpleNamespace(task=Mock(return_value=self.task), plan=Mock(return_value=self.plan),
            sql=Mock(return_value=[{'count': 0}]), native_db=Mock(),
            lifecycle_observer=SimpleNamespace(_binding=Mock(side_effect=[self.before, self.after])))
        self.state = {'store': self.store, 'auth': SimpleNamespace(require=Mock())}
        self.worker = Mock(acancel_queued=AsyncMock(return_value=True), start=AsyncMock())
        self.addCleanup(patch.stopall)
        self.worker_class = patch.object(subject, 'QueueWorker', return_value=self.worker).start()
        self.agent = patch.object(subject, 'Agent').start()
        self.queue = patch.object(subject, 'resolve_queue_store', return_value=Mock()).start()

    async def test_waiting_original_cancelled_without_start_or_provision(self):
        result = await subject.cancel_native_original(self.state, 'task-original', self.expected)
        self.assertTrue(result['nativeCleanupConfirmed'])
        self.worker.acancel_queued.assert_awaited_once_with('run-original')
        self.worker.start.assert_not_called()
        self.assertFalse(self.worker_class.call_args.kwargs['auto_provision'])
        self.agent.assert_called_once_with(id='factory-executor', db=self.store.native_db, telemetry=False)
        resolver = self.worker_class.call_args.args[1]
        self.assertIs(resolver('agent', 'factory-executor'), self.agent.return_value)
        with self.assertRaises(ValueError):
            resolver('agent', 'other')

    async def test_mismatch_or_missing_cancel_intent_never_constructs_worker(self):
        for change in ({'run_id': 'another'}, {'cancel_requested': False}):
            with self.subTest(change=change):
                self.store.task.return_value = {**self.task, **change}
                with self.assertRaises(ValueError):
                    await subject.cancel_native_original(self.state, 'task-original', self.expected)
        self.worker_class.assert_not_called()

    async def test_descendant_or_unresolved_intent_refuses_cancel(self):
        self.store.sql.return_value = [{'count': 1}]
        with self.assertRaises(ValueError):
            await subject.cancel_native_original(self.state, 'task-original', self.expected)
        self.worker_class.assert_not_called()

    async def test_running_or_missing_persisted_row_retains_unknown(self):
        for ticket in ({**self.before, 'status': 'running'}, {**self.before, 'persistedRunStatus': None}):
            self.store.lifecycle_observer._binding.side_effect = None
            self.store.lifecycle_observer._binding.return_value = ticket
            result = await subject.cancel_native_original(self.state, 'task-original', self.expected)
            self.assertFalse(result['nativeCleanupConfirmed'])
        self.worker_class.assert_not_called()

    async def test_ticket_cancelled_without_run_proof_is_not_success(self):
        self.store.lifecycle_observer._binding.side_effect = [self.before, {**self.after, 'persistedRunStatus': 'paused'}]
        result = await subject.cancel_native_original(self.state, 'task-original', self.expected)
        self.assertFalse(result['nativeCleanupConfirmed'])

    async def test_completed_or_failed_native_outcomes_preserved_without_cancel(self):
        for status, persisted, outcome in (('completed', 'completed', 'completed'), ('failed', 'error', 'failed')):
            self.store.lifecycle_observer._binding.side_effect = None
            self.store.lifecycle_observer._binding.return_value = dict(id='run-original', status=status, persistedRunStatus=persisted)
            result = await subject.cancel_native_original(self.state, 'task-original', self.expected)
            self.assertTrue(result['nativeCleanupConfirmed'])
            self.assertEqual(result['terminalStatus'], outcome)
        self.worker_class.assert_not_called()

    async def test_already_cancelled_is_read_only_and_requires_both_records(self):
        self.store.lifecycle_observer._binding.side_effect = [self.after]
        result = await subject.cancel_native_original(self.state, 'task-original', self.expected)
        self.assertTrue(result['nativeCleanupConfirmed'])
        self.worker_class.assert_not_called()


if __name__ == '__main__':
    unittest.main()

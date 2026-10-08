"""Synthetic effect custody at the exact subprocess boundary; never spawn compute."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agno.exceptions import RunCancelledException
from agno.run import RunContext

from agent_factory import tools
from test_runtime_contract import ContractStore  # pyright: ignore[reportMissingImports]


class SyntheticPredispatchCancelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = SimpleNamespace(runtime_directory=Path(self.directory.name) / 'runtime',
            experiment_timeout_seconds=1, experiment_output_bytes=65536)
        self.store = ContractStore(mode='experiment')
        self.context = RunContext(run_id='synthetic-native-run', session_id='synthetic-task', user_id='test-user')
        self.store.bind_run(self.context)
        self.limits = Mock(return_value=SimpleNamespace(runtime_id='local-python-bounded-v1', timeout_seconds=1,
            output_bytes=65536, memory_bytes=128 * 1024**2, process_limit=1, cpu_percent=10))
        self.store.execution_bindings = SimpleNamespace(environment_limits=self.limits)
        self.function = tools.build_tools(self.settings, self.store)['run_experiment']
        self.key = (self.context.run_id, 'experiment:bounded-sort-v1')

    async def invoke(self):
        return await self.function.entrypoint(experiment='bounded-sort-v1', run_context=self.context)

    def assert_unknown(self):
        self.assertEqual(self.store.effects[self.key]['status'], 'unknown')
        self.assertIsNone(self.store.effects[self.key]['result'])
        self.assertFalse(self.store.artifacts)
        self.assertTrue(any(event['type'] == 'effect_unknown' for event in self.store.events))
        self.assertFalse(any(event['type'] == 'compute_cancelled' for event in self.store.events))

    async def test_environment_cancellation_before_dispatch_settles_original_effect(self):
        cancelled = RunCancelledException('Synthetic cancellation before process dispatch')
        def cancel_in_limits(*args):
            # This boundary is reached only after the durable effect reservation.
            self.assertEqual(self.store.effects[self.key]['status'], 'unknown')
            self.store.cancelled = True
            raise cancelled
        self.limits.side_effect = cancel_in_limits
        with patch.object(tools.subprocess, 'Popen') as launch:
            with self.assertRaises(RunCancelledException) as raised:
                await self.invoke()
            launch.assert_not_called()
        self.assertIs(raised.exception, cancelled)
        self.limits.assert_called_once()
        effect = self.store.effects[self.key]
        self.assertEqual(effect['status'], 'done')
        self.assertEqual(effect['result'], {'cancelled': True, 'cleanupComplete': True,
            'runtimeId': 'local-python-bounded-v1', 'dispatchState': 'never-dispatched'})
        self.assertFalse(self.store.artifacts)
        self.assertFalse(any(event['type'] in {'compute_started', 'compute_stopped', 'effect_unknown'}
                             for event in self.store.events))
        self.assertTrue(any(event['type'] == 'compute_cancelled' for event in self.store.events))

    async def test_cancellation_inside_launch_with_no_receipt_remains_unknown(self):
        with patch.object(tools.subprocess, 'Popen', side_effect=RunCancelledException('Synthetic ambiguous launch')) as launch:
            with self.assertRaises(RunCancelledException):
                await self.invoke()
            launch.assert_called_once()
            with self.assertRaisesRegex(RuntimeError, 'UNKNOWN effect'):
                await self.invoke()
            launch.assert_called_once()
        self.assert_unknown()
        self.assertFalse(any(event['type'] == 'compute_stopped' for event in self.store.events))

    async def test_reused_cancellation_proof_cannot_settle_an_ambiguous_new_launch(self):
        reused = RunCancelledException('Synthetic reused cancellation instance')
        setattr(reused, 'compute_cleanup_complete', True)
        setattr(reused, 'compute_never_dispatched', True)
        with patch.object(tools.subprocess, 'Popen', side_effect=reused) as launch:
            with self.assertRaises(RunCancelledException) as raised:
                await self.invoke()
            launch.assert_called_once()
        self.assertIs(raised.exception, reused)
        self.assertFalse(getattr(reused, 'compute_cleanup_complete'))
        self.assertFalse(getattr(reused, 'compute_never_dispatched'))
        self.assert_unknown()

    async def test_predispatch_generic_failure_is_not_fabricated_cancelled_success(self):
        self.limits.side_effect = PermissionError('Synthetic current authority denied')
        with patch.object(tools.subprocess, 'Popen') as launch:
            with self.assertRaises(PermissionError):
                await self.invoke()
            launch.assert_not_called()
        self.assert_unknown()

    async def dispatched_cancel(self, *, cleanup_fails):
        process = Mock(pid=12345, returncode=-15)
        process.poll.return_value = None
        if cleanup_fails:
            process.wait.side_effect = tools.subprocess.TimeoutExpired('synthetic-owned-process', timeout=2)
        else:
            process.wait.return_value = -15
        def dispatched(*args, **kwargs):
            self.store.cancelled = True
            return process
        # Both OS branches are mocked; no real process, job object, or signal.
        with patch.object(tools.subprocess, 'Popen', side_effect=dispatched) as launch, \
             patch.object(tools, '_WindowsJob'), patch.object(tools.os, 'killpg', create=True):
            expected = (RunCancelledException, tools.subprocess.TimeoutExpired) if cleanup_fails else RunCancelledException
            with self.assertRaises(expected):
                await self.invoke()
            launch.assert_called_once()
        self.assertTrue(any(event['type'] == 'compute_started' for event in self.store.events))
        self.assertFalse(self.store.artifacts)
        return process

    async def test_postdispatch_cleanup_failure_keeps_unknown_effect(self):
        process = await self.dispatched_cancel(cleanup_fails=True)
        self.assertEqual(process.wait.call_count, 2)
        self.assert_unknown()
        self.assertFalse(any(event['type'] == 'compute_stopped' for event in self.store.events))

    async def test_postdispatch_positive_cleanup_is_not_never_dispatched(self):
        process = await self.dispatched_cancel(cleanup_fails=False)
        process.wait.assert_called_once_with(timeout=2)
        effect = self.store.effects[self.key]
        self.assertEqual(effect['status'], 'done')
        self.assertTrue(effect['result']['cancelled'])
        self.assertTrue(effect['result']['cleanupComplete'])
        self.assertNotIn('dispatchState', effect['result'])
        self.assertTrue(any(event['type'] == 'compute_stopped' for event in self.store.events))
        self.assertFalse(any(event['type'] == 'effect_unknown' for event in self.store.events))


if __name__ == '__main__':
    unittest.main()

"""Command-handle recovery uses original durable facts; no real provider in these tests."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import unittest

from agno.exceptions import StopAgentRun
from agno.run import RunContext

from research.session_commands import ResearchCommands, EFFECT_KEY


class ResearchCommandRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.context = RunContext(user_id='alice', session_id='child', run_id='original-run')
        self.execution = {'id': 'session', 'ownerId': 'alice'}
        self.pin = {'kind': 'workflow', 'id': 'research-command', 'revision': '1', 'sha256': 'original'}
        self.plan = {'mode': 'command', 'nativeComponent': self.pin,
            'inputValues': {'sessionId': 'session', 'sessionContext': '{"argv":["original-command"]}'},
            'delegation': {'parentTaskId': 'parent'}}
        self.store = SimpleNamespace(task=Mock(return_value={'id': 'child', 'plan_id': 'plan'}),
            plan=Mock(return_value=self.plan), effect_reserve=Mock(), effects=Mock(),
            native_workflows=SimpleNamespace(pin=Mock(return_value=self.pin)))
        sessions = SimpleNamespace(store=self.store, authorize_tool=Mock(return_value=self.execution))
        self.tools = SimpleNamespace(_workspace=Mock(return_value=self.root), _run=AsyncMock())
        self.commands = ResearchCommands(self.tools, sessions)

    def test_reopened_unknown_original_does_not_dispatch_a_replacement_process(self):
        self.store.effect_reserve.return_value = {'status': 'unknown'}
        with self.assertRaises(StopAgentRun):
            asyncio.run(self.commands.execute(self.context))
        self.tools._run.assert_not_awaited()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_reopened_completed_original_reads_its_receipt_without_executing(self):
        output = {'exitCode': 0, 'stdout': 'once', 'stopped': True}
        self.store.effect_reserve.return_value = {'status': 'done', 'result': {'output': output}}
        self.assertEqual(asyncio.run(self.commands.execute(self.context)), output)
        self.tools._run.assert_not_awaited()

    def test_read_handle_can_expand_a_preview_from_original_output_files(self):
        directory = self.commands._directory(self.execution, 'child')
        directory.mkdir()
        text = 'full output\n' * 5000
        (directory / 'stdout.txt').write_text(text)
        (directory / 'stderr.txt').write_text('actual stderr')
        self.store.effects.return_value = [{'effect_key': 'original-run:' + EFFECT_KEY, 'status': 'DONE',
            'result': {'outcome': 'completed', 'output': {'stdout': 'old preview', 'stderr': '',
                'truncated': True, 'exitCode': 0, 'stopped': True}}}]
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('must read only bounded head/tail')):
            preview = asyncio.run(self.commands.read(self.context, {'processId': 'child', 'max_output_tokens': 10}))
        self.assertTrue(preview['truncated'])
        self.assertEqual(preview['status'], 'completed')
        full = asyncio.run(self.commands.read(self.context, {'processId': 'child', 'max_output_tokens': 100000}))
        self.assertEqual(full['stdout'], text)
        self.assertEqual(full['stderr'], 'actual stderr')
        self.assertNotIn('truncated', full)
        self.assertEqual(full['processId'], preview['processId'])
        self.tools._run.assert_not_awaited()

    def test_handle_from_another_session_does_not_read_its_output(self):
        self.plan['inputValues']['sessionId'] = 'other-session'
        with self.assertRaises(PermissionError):
            asyncio.run(self.commands.read(self.context, {'processId': 'child'}))
        self.store.effects.assert_not_called()

    def test_nonzero_exit_is_failed_even_with_confirmed_receipt(self):
        self.store.effects.return_value = [{'effect_key': 'original-run:' + EFFECT_KEY, 'status': 'DONE',
            'result': {'outcome': 'completed', 'output': {'exitCode': 7, 'stopped': True}}}]
        result = asyncio.run(self.commands.read(self.context, {'processId': 'child'}))
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['stopped'])

    def test_restarted_reader_preserves_unknown_and_never_dispatches(self):
        self.store.task.return_value.update(run_id='original-run')
        self.store.effects.return_value = [{'effect_key': 'original-run:' + EFFECT_KEY, 'status': 'UNKNOWN'}]
        self.store.lifecycle_observer = SimpleNamespace(inspect_subtree=AsyncMock(return_value={
            'parent': {'nativeStatus': 'running', 'stopped': False}}))
        self.store.native_db = SimpleNamespace(get_job=Mock(return_value={'status': 'running', 'attempt': 2}))
        result = asyncio.run(self.commands.read(self.context, {'processId': 'child'}))
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['stopped'])
        self.tools._run.assert_not_awaited()

    def test_cancelled_native_status_without_stop_evidence_stays_unknown(self):
        self.store.effects.return_value = []
        facts = {'nativeStatus': 'cancelled', 'stopped': False}
        self.store.lifecycle_observer = SimpleNamespace(inspect_subtree=AsyncMock(return_value={'parent': facts}))
        result = asyncio.run(self.commands.read(self.context, {'processId': 'child'}))
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['stopped'])
        facts['stopped'] = True
        result = asyncio.run(self.commands.read(self.context, {'processId': 'child'}))
        self.assertEqual(result['status'], 'cancelled')
        self.assertTrue(result['stopped'])

    def test_read_refreshes_binding_created_during_observation(self):
        self.store.task.side_effect = [
            {'id': 'child', 'plan_id': 'plan', 'run_id': None},
            {'id': 'child', 'plan_id': 'plan', 'run_id': 'original-run'}]
        self.store.effects.return_value = [{'effect_key': 'original-run:' + EFFECT_KEY, 'status': 'UNKNOWN'}]
        self.store.lifecycle_observer = SimpleNamespace(inspect_subtree=AsyncMock(return_value={
            'parent': {'nativeStatus': 'running', 'stopped': False}}))
        self.store.native_db = SimpleNamespace(get_job=Mock(return_value={'status': 'running', 'attempt': 1}))
        result = asyncio.run(self.commands.read(self.context, {'processId': 'child'}))
        self.assertEqual(result['status'], 'running')
        self.store.native_db.get_job.assert_called_once_with('original-run')
        self.tools._run.assert_not_awaited()

    def test_read_refreshes_receipt_after_native_ticket_becomes_terminal(self):
        self.store.task.return_value.update(run_id='original-run')
        self.store.effects.side_effect = [
            [{'effect_key': 'original-run:' + EFFECT_KEY, 'status': 'UNKNOWN'}],
            [{'effect_key': 'original-run:' + EFFECT_KEY, 'status': 'DONE',
              'result': {'outcome': 'completed', 'output': {'exitCode': 0, 'stopped': True}}}]]
        self.store.lifecycle_observer = SimpleNamespace(inspect_subtree=AsyncMock(return_value={
            'parent': {'nativeStatus': 'completed', 'stopped': True}}))
        self.store.native_db = SimpleNamespace(get_job=Mock(return_value={'status': 'completed', 'attempt': 1}))
        result = asyncio.run(self.commands.read(self.context, {'processId': 'child'}))
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['stopped'])
        self.tools._run.assert_not_awaited()

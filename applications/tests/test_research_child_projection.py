"""Child mode comes from its native plan, never from goal text."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from research.session_subagents import ResearchSubagents


class ChildProjectionTests(unittest.TestCase):
    def test_command_mode_comes_from_plan(self):
        service = ResearchSubagents.__new__(ResearchSubagents)
        service.store = SimpleNamespace(plan=Mock(return_value={
            'mode': 'command', 'normalizedGoal': 'Long arbitrary argv'}))
        child = {'id': 'child', 'run_id': 'run', 'plan_id': 'plan', 'owner_id': 'alice'}
        group = {'allStopped': False, 'unknown': False, 'parent': {'displayStatus': 'running'}}
        self.assertEqual(service._projection(child, group)['mode'], 'command')
        service.store.plan.return_value = {'mode': 'autonomous', 'normalizedGoal': 'Run command: python'}
        self.assertEqual(service._projection(child, group)['mode'], 'autonomous')

    def test_command_result_uses_original_completed_receipt_not_native_text(self):
        output = {'exitCode': 7, 'stopped': True, 'stdout': 'observed', 'stderr': 'error',
                  'stdoutPath': '.command/stdout.txt', 'stderrPath': '.command/stderr.txt'}
        effect = {'effect_key': 'run:research-command-process', 'status': 'DONE',
                  'result': {'outcome': 'completed', 'output': output}}
        service = ResearchSubagents.__new__(ResearchSubagents)
        service.store = SimpleNamespace(plan=Mock(return_value={'mode': 'command',
            'nativeComponent': {'id': 'research-command'}, 'normalizedGoal': 'command'}),
            effects=Mock(return_value=[effect]))
        child = {'id': 'child', 'run_id': 'run', 'plan_id': 'plan', 'owner_id': 'alice'}
        group = {'allStopped': False, 'unknown': False, 'parent': {'displayStatus': 'running'}}
        projected = service._projection(child, group)
        self.assertEqual(projected['commandResult'], {**output, 'status': 'failed'})
        self.assertEqual(projected['status'], 'running')
        effect['status'] = 'UNKNOWN'
        self.assertNotIn('commandResult', service._projection(child, group))


class ChildWaitObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolved_requirements_do_not_hide_the_next_pending_wait(self):
        from unittest.mock import AsyncMock

        def requirement(identifier, **extra):
            return {'id': identifier, 'tool_execution': {'tool_name': 'research_wait_child',
                'tool_call_id': identifier, 'tool_args': {'childTaskId': 'child-' + identifier},
                'external_execution_required': True, **extra}}
        resolved_tool = requirement('old-tool', result='original result')
        resolved_requirement = {**requirement('old-requirement'), 'external_execution_result': 'original result'}
        pending = requirement('pending')
        service = ResearchSubagents.__new__(ResearchSubagents)
        service.store = SimpleNamespace(native_db=SimpleNamespace(get_job=Mock(return_value={'status': 'paused'})))
        service.commands = SimpleNamespace(bridge=SimpleNamespace(detail=AsyncMock(return_value={
            'run': {'requirements': [resolved_tool, resolved_requirement, pending]}})), submit=AsyncMock())
        service._linked = Mock(return_value={'id': 'child-pending'})
        observer = SimpleNamespace(inspect_subtree=AsyncMock(return_value={'allStopped': True, 'unknown': False}))
        await service.observe_waits(observer, {'id': 'root', 'owner_id': 'alice', 'run_id': 'original-run',
                                             'terminal': False, 'cancel_requested': False})
        service._linked.assert_called_once_with({'id': 'root', 'owner_id': 'alice', 'run_id': 'original-run',
            'terminal': False, 'cancel_requested': False}, pending)
        service.commands.submit.assert_awaited_once()
        self.assertEqual(service.commands.submit.call_args.args[2].requirementId, 'pending')

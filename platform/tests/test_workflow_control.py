"""Portable control boundary tests: actual SQLite journals, inert adapters/native bridge."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agno.exceptions import RunCancelledException
from fastapi import HTTPException

from agent_factory.lifecycle_observer import FactoryLifecycleObserver
from agent_factory.workflow_control import WorkflowCommand, WorkflowControl
from agent_factory.workflow_service import WorkflowService
import test_workflow_service as fixture_module


class WorkflowControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixture = fixture_module.WorkflowTests('test_original_inputs_dependencies_and_command_replay')
        self.fixture = fixture
        self.addCleanup(lambda: fixture.resources.close())
        fixture.setUp()
        self.store, self.service, self.runtime = fixture.store, fixture.service, fixture.runtime
        self.task, self.ctx, self.auth = fixture.task, fixture.ctx, fixture.auth
        self.task.update(request_id='request', admission='accepted')
        self.store.plan = Mock(side_effect=lambda *args: deepcopy(fixture.plan))
        self.store.require_plan_execution = Mock()
        self.store.execution_bindings = SimpleNamespace(recheck=Mock())
        self.store.delegation = SimpleNamespace(consume_tool_budget=Mock())
        self.store.has_failures = Mock(return_value=False)
        self.store.effects = Mock(return_value=[])
        self.store.workflow = self.service
        self.requirement = {'id': 'original-requirement', 'tool_execution': {
            'tool_name': 'workflow_wait', 'tool_args': {'stageId': 'A'},
            'external_execution_required': True, 'result': None, 'tool_call_id': 'original-call'}}
        self.native_snapshot = {'queue': {'id': 'native', 'session_id': 'task', 'user_id': 'alice',
            'component_type': 'agent', 'component_id': 'factory-executor', 'status': 'paused'},
            'run': {'run_id': 'native', 'session_id': 'task', 'user_id': 'alice',
                'agent_id': 'factory-executor', 'status': 'paused'}}
        def snapshot(*args):
            value = deepcopy(self.native_snapshot)
            value['run']['requirements'] = [deepcopy(self.requirement)]
            return value
        self.bridge = SimpleNamespace(detail=AsyncMock(side_effect=snapshot))
        self.commands = SimpleNamespace(submit=AsyncMock(return_value={'decisionRecorded': True}))
        self.control = WorkflowControl(self.service, SimpleNamespace(store=self.store, auth=self.auth, bridge=self.bridge, commands=self.commands))

    async def test_completion_is_stable_across_other_stage_progress(self):
        await self.service.choose(self.ctx, 'A', 'stage-a')
        first = await self.control.completion(self.task, deepcopy(self.requirement))
        await self.service.choose(self.ctx, 'B', 'stage-b')
        second = await self.control.completion(self.task, deepcopy(self.requirement))
        self.assertEqual(first, second)
        self.assertEqual(set(first), {'schema', 'workflowId', 'nativeRunId', 'stageId', 'requirementId', 'ready'})
        self.assertTrue(first['ready'])

    async def test_completion_rechecks_authority_requirement_and_stage(self):
        self.runtime.outcome = 'RUNNING'
        await self.service.choose(self.ctx, 'A', 'stage-a')
        with self.assertRaises(ValueError): await self.control.completion(self.task, deepcopy(self.requirement))
        saved = deepcopy(self.requirement)
        self.requirement['tool_execution']['tool_call_id'] = 'changed'
        with self.assertRaises(ValueError): await self.control.completion(self.task, saved)
        self.store.require_plan_execution.side_effect = HTTPException(403, 'controlled revoke')
        with self.assertRaises(HTTPException): await self.control.completion(self.task, saved)
        self.commands.submit.assert_not_awaited()

    async def test_command_replay_preserves_one_original_start_and_conflict_denied(self):
        command = WorkflowCommand(commandId='resume-original', action='resume', stageId='A', version=0)
        first = await self.control.submit('alice', 'task', command)
        second = await self.control.submit('alice', 'task', command)
        self.assertEqual(first, second)
        self.assertEqual(len(self.runtime.starts), 1)
        self.assertEqual(self.commands.submit.await_count, 1)
        with self.assertRaises(ValueError):
            await self.control.submit('alice', 'task', command.model_copy(update={'stageId': 'B'}))
        with self.assertRaises(PermissionError): await self.control.submit('bob', 'task', command)

    async def test_lost_ack_repeat_never_dispatches_again(self):
        self.runtime.lost = True
        command = WorkflowCommand(commandId='resume-lost-ack', action='resume', stageId='A', version=0)
        first = await self.control.submit('alice', 'task', command)
        self.assertEqual(first['status'], 'unknown')
        await self.control.submit('alice', 'task', command)
        self.assertEqual(len(self.runtime.starts), 1)
        self.assertTrue(self.service.task_held('task'))
        self.commands.submit.assert_not_awaited()

    async def test_configuration_removed_restart_retains_custody(self):
        self.runtime.outcome = 'RUNNING'
        await self.service.choose(self.ctx, 'A', 'stage-a')
        restored = WorkflowService(self.store, self.auth, definitions={}, runtimes={})
        self.assertTrue(restored.task_held('task'))
        self.assertEqual(restored.for_task('alice', 'task')['stages']['A']['state'], 'RUNNING')
        try:
            await restored.cancel_task('alice', 'task')
        except (KeyError, ValueError):
            pass  # Missing old adapter cannot supply positive stop evidence.
        self.assertTrue(restored.task_held('task'))
        self.store.workflow = restored
        observer = FactoryLifecycleObserver(self.store, self.auth, None, lambda: None)
        observer._binding = Mock(return_value={'status': 'completed', 'persistedRunStatus': 'completed'})
        self.assertFalse(observer._facts(self.task)['stopped'])

    async def test_native_completed_unfinished_workflow_requires_cleanup(self):
        observer = FactoryLifecycleObserver(self.store, self.auth, None, lambda: None)
        self.assertEqual(observer._reason(self.task, {'status': 'completed'}), 'native-ended-unfinished-workflow')
        self.assertTrue(await self.service.cancel_task('alice', 'task'))
        self.assertIsNone(observer._reason(self.task, {'status': 'completed'}))

    async def test_lost_ack_receipt_recovers_only_after_original_observation(self):
        self.runtime.lost = True
        command = WorkflowCommand(commandId='recover-original', action='resume', stageId='A', version=0)
        self.assertEqual((await self.control.submit('alice', 'task', command))['status'], 'unknown')
        self.assertEqual((await self.control.receipt('alice', 'task', command.commandId))['status'], 'unknown')
        body = self.service.for_task('alice', 'task')
        await self.service.reconcile(self.ctx, 'A', 'read-original-operation', expected_version=body['version'])
        self.assertEqual((await self.control.receipt('alice', 'task', command.commandId))['status'], 'completed')
        self.assertEqual(len(self.runtime.starts), 1)
        self.commands.submit.assert_not_awaited()
        self.assertIn({'action': 'reconcile', 'stageId': 'A'}, self.control.snapshot('alice', 'task')['allowedActions'])

    async def test_stale_preflight_rejection_is_durable_without_effects(self):
        command = WorkflowCommand(commandId='stale-original', action='resume', stageId='A', version=999)
        first = await self.control.submit('alice', 'task', command)
        self.assertEqual(first['status'], 'rejected')
        self.assertEqual(await self.control.submit('alice', 'task', command), first)
        self.assertEqual(await self.control.receipt('alice', 'task', command.commandId), first)
        self.assertEqual(self.runtime.starts, [])
        self.store.delegation.consume_tool_budget.assert_not_called()
        self.commands.submit.assert_not_awaited()

    async def test_cancel_receipt_recovers_original_native_proof_without_redispatch(self):
        self.commands.submit.side_effect = ConnectionError('controlled acknowledgement loss')
        self.commands.recover = AsyncMock(side_effect=[{'commandId': 'cancel-original', 'decisionRecorded': False},
            {'commandId': 'cancel-original', 'decisionRecorded': True, 'stopConfirmed': False}])
        command = WorkflowCommand(commandId='cancel-original', action='cancel')
        self.assertEqual((await self.control.submit('alice', 'task', command))['status'], 'unknown')
        self.assertEqual((await self.control.receipt('alice', 'task', command.commandId))['status'], 'unknown')
        receipt = await self.control.receipt('alice', 'task', command.commandId)
        self.assertEqual(receipt['status'], 'completed')
        self.assertTrue(receipt['nativeContinuation']['decisionRecorded'])
        self.assertFalse(receipt['nativeContinuation']['stopConfirmed'])
        self.assertEqual(self.commands.recover.await_count, 2)
        self.commands.recover.assert_awaited_with('alice', 'task', 'cancel-original')
        self.assertEqual(self.commands.submit.await_count, 1)
        self.assertEqual(self.runtime.starts, [])

    async def test_http_resume_requires_original_native_paused_stage_before_any_debit(self):
        original = deepcopy(self.native_snapshot)
        for index, mutation in enumerate(('running', 'wrong-stage', 'wrong-run', 'wrong-owner')):
            self.native_snapshot = deepcopy(original)
            self.requirement['tool_execution']['tool_args'] = {'stageId': 'A'}
            if mutation == 'running':
                self.native_snapshot['queue']['status'] = 'running'
                self.native_snapshot['run']['status'] = 'running'
            elif mutation == 'wrong-stage':
                self.requirement['tool_execution']['tool_args'] = {'stageId': 'B'}
            elif mutation == 'wrong-run':
                self.native_snapshot['queue']['id'] = 'different-native'
            else:
                self.native_snapshot['run']['user_id'] = 'bob'
            with self.subTest(mutation=mutation):
                command = WorkflowCommand(commandId='invalid-paused-' + str(index), action='resume', stageId='A', version=0)
                result = await self.control.submit('alice', 'task', command)
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(self.runtime.starts, [])
                self.store.delegation.consume_tool_budget.assert_not_called()
                self.commands.submit.assert_not_awaited()

    async def test_http_resume_rechecks_pause_at_effect_boundary(self):
        calls = 0
        original = self.bridge.detail.side_effect
        def advance(*args):
            nonlocal calls
            calls += 1
            value = original(*args)
            if calls > 1:
                value['queue']['status'] = 'running'
                value['run']['status'] = 'running'
            return value
        self.bridge.detail.side_effect = advance
        command = WorkflowCommand(commandId='pause-changed-before-effect', action='resume', stageId='A', version=0)
        result = await self.control.submit('alice', 'task', command)
        self.assertIn(result['status'], {'unknown', 'rejected'})
        self.assertGreaterEqual(calls, 2)
        self.assertEqual(self.runtime.starts, [])
        self.store.delegation.consume_tool_budget.assert_not_called()
        self.commands.submit.assert_not_awaited()

    async def test_external_wait_debits_original_tool_id_only_in_mutating_wrapper(self):
        original = deepcopy(self.requirement)
        await self.control.completion(self.task, original)
        self.store.delegation.consume_tool_budget.assert_not_called()
        first = await self.control.complete_external(self.task, original)
        second = await self.control.complete_external(self.task, original)
        self.assertEqual(first, second)
        calls = self.store.delegation.consume_tool_budget.call_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            context, identifier, tool = call.args
            self.assertEqual((context.session_id, context.run_id, context.user_id), ('task', 'native', 'alice'))
            self.assertEqual((identifier, tool), ('original-call', 'workflow_wait'))
        # This mock proves stable key forwarding, not actual ledger deduplication.
        self.assertEqual(original, self.requirement)
        self.commands.submit.assert_not_awaited()
        self.assertEqual(self.runtime.starts, [])

    async def test_external_wait_budget_denial_cannot_return_tool_result(self):
        original = deepcopy(self.requirement)
        self.store.delegation.consume_tool_budget.side_effect = PermissionError('controlled budget exhausted')
        with self.assertRaises(PermissionError):
            await self.control.complete_external(self.task, original)
        self.assertIsNone(original['tool_execution']['result'])
        self.assertEqual(original, self.requirement)
        self.commands.submit.assert_not_awaited()
        self.assertEqual(self.runtime.starts, [])

    async def test_acknowledged_unknown_keeps_receipt_and_never_continues_or_restarts(self):
        self.runtime.outcome = 'UNKNOWN'
        command = WorkflowCommand(commandId='acknowledged-unknown', action='resume', stageId='A', version=0)
        first = await self.control.submit('alice', 'task', command)
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(first['workflow']['stages']['A']['state'], 'UNKNOWN')
        self.assertIsNotNone(first['workflow']['stages']['A']['operationId'])
        self.assertEqual(await self.control.submit('alice', 'task', command), first)
        self.assertEqual((await self.control.receipt('alice', 'task', command.commandId))['status'], 'unknown')
        self.assertEqual(len(self.runtime.starts), 1)
        self.assertTrue(self.service.task_held('task'))
        self.commands.submit.assert_not_awaited()

    async def test_cancelled_or_revoked_snapshot_preserves_read_only_body(self):
        before = self.service.for_task('alice', 'task')
        self.task['cancel_requested'] = True
        for error in (None, RunCancelledException('controlled cancellation'), PermissionError('controlled revoked')):
            with self.subTest(error=type(error).__name__):
                self.store.require_plan_execution.side_effect = error
                result = self.control.snapshot('alice', 'task')
                self.assertTrue(result['available'])
                self.assertEqual(result['workflow'], before)
                self.assertEqual(result['allowedActions'], [])
                self.assertEqual(self.service.for_task('alice', 'task'), before)
                self.assertEqual(self.runtime.starts, [])
                self.store.delegation.consume_tool_budget.assert_not_called()
                self.commands.submit.assert_not_awaited()

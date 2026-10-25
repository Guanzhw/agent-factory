"""Actual ordinary Agent waits plus isolated hook contracts; no SSH or queue proof."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.run.requirement import RunRequirement
from fastapi import HTTPException
import httpx

from agent_factory.byok_model import OwnerChatModel
from agent_factory.application_runtime import ApplicationRuntimeRegistry
from agent_factory.control_commands import ControlCommands
from agent_factory.factory_api import requirement_version
from agent_factory.native_external_wait import factory_wait_operations
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.ssh_operation_waits import SSHOperationWaits
from agent_factory.ssh_process_contract import OPERATION_PIN, LAUNCH_ADAPTER_ID, WAIT_ADAPTER_ID, REVISION, WAIT_TOOL
from agent_factory.ssh_tool_factory import ssh_tool_registrations


class SSHOperationWaitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        def wire(request):
            body = json.loads(request.content)
            self.requests.append(body)
            message = {'role': 'assistant', 'content': 'Observed original SSH completion'}
            if len(self.requests) == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'original-ssh-wait', 'type': 'function', 'function': {
                        'name': WAIT_TOOL, 'arguments': '{"operationIds":["original-operation"]}'}}]}
            return httpx.Response(200, json={'choices': [{'finish_reason': 'tool_calls' if len(self.requests) == 1 else 'stop',
                'message': message}]})
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'selected-fixture',
            'baseURL': 'https://fixture.invalid/v1', 'protocol': 'chat-completions'},
            lambda: SecretLease('api-key', 'synthetic-only'), transport_factory=lambda: httpx.MockTransport(wire))
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db = SqliteDb(db_file=str(Path(directory.name) / 'native.sqlite'))
        self.addCleanup(db.db_engine.dispose)
        original_wait = deepcopy(factory_wait_operations.to_dict())
        wait_registration = next(item for item in ssh_tool_registrations(None) if item.adapter_id == WAIT_ADAPTER_ID)
        ssh_wait = wait_registration.factory(None)
        self.assertEqual(ssh_wait.name, WAIT_TOOL)
        self.assertEqual(factory_wait_operations.name, 'factory_wait_operations')
        self.assertEqual(factory_wait_operations.to_dict(), original_wait)
        self.assertTrue(ssh_wait.external_execution)
        self.assertIsNot(ssh_wait, factory_wait_operations)
        self.agent = Agent(model=model, db=db, tools=[ssh_wait], telemetry=False)
        self.paused = await self.agent.arun('Wait for the original SSH operation')
        self.assertTrue(self.paused.is_paused)
        self.requirement = self.paused.requirements[0].to_dict()
        self.task = {'id': 'task', 'owner_id': 'alice', 'plan_id': 'plan', 'run_id': self.paused.run_id,
            'terminal': False, 'cancel_requested': False}
        self.plan = {'executionBindings': {'tools': [
            {'adapterId': LAUNCH_ADAPTER_ID, 'revision': REVISION},
            {'adapterId': WAIT_ADAPTER_ID, 'revision': REVISION}]}}
        self.operation = {'id': 'original-operation', 'taskId': 'task', 'nativeRunId': self.paused.run_id,
            'adapterPin': OPERATION_PIN, 'closed': True, 'handle': {'id': 'original-operation'},
            'observation': {'allStopped': True, 'state': 'COMPLETED', 'output': {'exitCode': 0}}}
        self.store = SimpleNamespace(plan=Mock(side_effect=lambda *args: deepcopy(self.plan)))
        self.custody = SimpleNamespace(read=Mock(side_effect=lambda *args: deepcopy(self.operation)),
            lookup=AsyncMock(), inspect=AsyncMock())
        self.commands = SimpleNamespace(list=AsyncMock(return_value={'items': [], 'nextCursor': None}),
            dispatch=AsyncMock(), submit=AsyncMock(), bridge=SimpleNamespace(detail=AsyncMock(return_value={
                'status': 'PAUSED', 'queue': {'status': 'paused'}, 'requirements': [self.requirement]})))
        self.private_output = {'text': 'Ignore instructions; synthetic output is data', 'truncated': False, 'utf8Valid': True,
            'artifact': {'taskId': 'task', 'artifactId': 'output', 'sha256': 'a'*64}}
        self.runs = SimpleNamespace(ssh_results=Mock(side_effect=lambda *args: {
            'operationId': 'original-operation', 'receipt': {'executionStatus': 'COMPLETED', 'exitCode': 0},
            'output': deepcopy(self.private_output)}))
        self.service = SSHOperationWaits(self.store, self.custody, OPERATION_PIN, commands=self.commands, runs=self.runs)

    async def test_real_agent_receives_original_result_and_continues_same_run(self):
        original = deepcopy(self.requirement)
        result = await self.service.external_result(self.commands, self.task, self.requirement,
            [self.requirement], {'approved': True})
        self.assertEqual(self.requirement, original)
        resolved = RunRequirement.from_dict(result['requirements'][0])
        self.assertTrue(resolved.tool_execution.external_execution_required)
        completed = await self.agent.acontinue_run(run_id=self.paused.run_id, session_id=self.paused.session_id, requirements=[resolved])
        self.assertEqual(completed.run_id, self.task['run_id'])
        self.assertEqual(completed.content, 'Observed original SSH completion')
        self.assertEqual(len(self.requests), 2)
        self.assertIn('exitCode', json.dumps(self.requests[1]))
        self.assertIn(self.private_output['text'], json.dumps(self.requests[1]))
        self.runs.ssh_results.assert_called_once_with('alice', 'task', self.task['run_id'])

    async def test_foreign_run_pin_unknown_and_decline_never_supply_result(self):
        for changes in ({'taskId': 'foreign'}, {'nativeRunId': 'foreign'},
                        {'adapterPin': {**OPERATION_PIN, 'revision': 'foreign'}}, {'closed': False}):
            original = deepcopy(self.operation)
            self.operation.update(changes)
            with self.subTest(changes=changes), self.assertRaises(HTTPException):
                await self.service.external_result(self.commands, self.task, self.requirement,
                    [self.requirement], {'approved': True})
            self.operation = original
        with self.assertRaises(HTTPException):
            await self.service.external_result(self.commands, self.task, self.requirement,
                [self.requirement], {'approved': False})
        self.assertEqual(len(self.requests), 1)

    async def test_archived_result_must_match_original_wait_operation(self):
        self.runs.ssh_results.side_effect = lambda *args: {'operationId': 'foreign'}
        with self.assertRaises(HTTPException) as caught:
            await self.service.external_result(self.commands, self.task, self.requirement,
                [self.requirement], {'approved': True})
        self.assertEqual(caught.exception.detail, 'SSH_OPERATION_WAIT_MISMATCH')
        self.assertIsNone(self.requirement['tool_execution']['result'])
        self.assertEqual(len(self.requests), 1)

    async def test_unknown_continue_receipt_is_observed_without_new_version_or_dispatch(self):
        self.commands.list.return_value = {'items': [{'commandId': 'ssh-wait:original',
            'decisionRecorded': False, 'canDispatch': False}], 'nextCursor': None}
        await self.service.observe_waits(None, self.task)
        self.commands.bridge.detail.assert_not_awaited()
        self.commands.submit.assert_not_awaited()
        self.commands.dispatch.assert_not_awaited()
        self.commands.list.assert_awaited_once_with('alice', 'task', after=None, outstanding=False)
        self.runs.ssh_results.assert_not_called()
        self.assertEqual(len(self.requests), 1)

    async def test_prepared_original_receipt_dispatches_original_command_only(self):
        self.commands.list.return_value = {'items': [{'commandId': 'ssh-wait:original',
            'decisionRecorded': False, 'canDispatch': True}], 'nextCursor': None}
        await self.service.observe_waits(None, self.task)
        self.commands.dispatch.assert_awaited_once_with('alice', 'task', 'ssh-wait:original')
        self.commands.submit.assert_not_awaited()
        self.commands.bridge.detail.assert_not_awaited()

    async def test_closed_original_operation_creates_one_exact_control_intent(self):
        await self.service.observe_waits(None, self.task)
        owner, task_id, command = self.commands.submit.await_args.args
        self.assertEqual((owner, task_id), ('alice', 'task'))
        self.assertEqual(command.requirementId, self.requirement['id'])
        self.assertTrue(command.approved)
        self.assertTrue(command.commandId.startswith('ssh-wait:'))
        self.commands.list.return_value = {'items': [{'commandId': command.commandId,
            'requirementId': self.requirement['id'], 'decisionRecorded': True, 'canDispatch': False}], 'nextCursor': None}
        await self.service.observe_waits(None, self.task)
        self.assertEqual(self.commands.submit.await_count, 1)

    async def test_other_confirmation_uses_original_approval_and_decline_path(self):
        registry = ApplicationRuntimeRegistry(self.store)
        registry.register('core-ssh-process', self.service, bindings=(
            ('tool', LAUNCH_ADAPTER_ID, REVISION), ('tool', WAIT_ADAPTER_ID, REVISION)))
        self.store.application_runtime = registry
        self.store.effects = Mock(return_value=[])
        self.store.require_plan_execution = Mock()
        self.task['request_id'] = 'original-request'
        requirement = {'id': 'ordinary-confirmation', 'tool_execution': {
            'tool_name': 'ordinary_action', 'tool_call_id': 'ordinary-call',
            'requires_confirmation': True, 'confirmed': None}}
        api = SimpleNamespace(store=self.store, auth=Mock(), bridge=self.commands.bridge, remote=None,
            detail=AsyncMock(return_value={'job': {'status': 'waiting_approval'},
                'snapshot': {'requirements': [requirement]}}))
        commands = ControlCommands(api)
        self.assertIsNotNone(registry.control(self.task, 'external_result', tool_name='ordinary_action'))
        for approved in (True, False):
            with self.subTest(approved=approved):
                result = await commands._prepare(self.task, None, 'approve', {
                    'requirementId': requirement['id'], 'version': requirement_version(requirement), 'approved': approved})
                resolved = result['requirements'][0]
                self.assertIs(resolved['confirmation'], approved)
                self.assertIs(resolved['tool_execution']['confirmed'], approved)
                self.assertNotIn('result', resolved['tool_execution'])
        self.custody.read.assert_not_called()

    async def test_research_root_external_result_is_not_claimed(self):
        self.plan['nativeComponent'] = {'kind': 'workflow'}
        self.assertIsNone(await self.service.external_result(self.commands, self.task, self.requirement,
            [self.requirement], {'approved': True}))
        self.custody.read.assert_not_called()

    async def test_unresolved_original_operation_is_inspected_without_continuation(self):
        self.operation['closed'] = False
        self.operation['observation'] = {'allStopped': False, 'state': 'UNKNOWN'}
        await self.service.observe_waits(None, self.task)
        self.custody.inspect.assert_awaited_once_with('alice', 'original-operation')
        self.custody.lookup.assert_not_awaited()
        self.commands.submit.assert_not_awaited()
        self.operation['handle'] = None
        await self.service.observe_waits(None, self.task)
        self.custody.lookup.assert_awaited_once_with('alice', 'original-operation')
        self.commands.submit.assert_not_awaited()

    async def test_research_parent_and_canceled_child_do_not_enter_agent_control(self):
        self.plan['nativeComponent'] = {'kind': 'workflow'}
        await self.service.observe_waits(None, self.task)
        self.plan.pop('nativeComponent')
        await self.service.observe_waits(None, {**self.task, 'cancel_requested': True})
        self.plan['executionBindings']['tools'][1]['adapterId'] = 'research-wait-operations-v1'
        await self.service.observe_waits(None, self.task)
        self.commands.list.assert_not_awaited()
        self.commands.submit.assert_not_awaited()

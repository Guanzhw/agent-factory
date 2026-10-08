"""Native requirement commands with real SQLite Store/journals and inert bridges.

No custom workflow graph, queue execution, PostgreSQL or model is used here.
"""
from contextvars import ContextVar
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock

from agno.exceptions import RunCancelledException
from agno.workflow.types import StepRequirement
from fastapi import HTTPException
from sqlalchemy import create_engine

from agent_factory.store import Store, canonical, digest
from agent_factory.workflow_contracts import WorkflowAcknowledgementUnknown
from agent_factory.workflow_control import WorkflowCommand, WorkflowControl
from agent_factory.workflow_operations import OperationCustody


class SQLiteStore(Store):
    """Only JSONB cast/driver decoding differ; Store SQL/task/plan/effects are real."""
    def __init__(self, path):
        self.engine = create_engine('sqlite:///' + str(path))
        self._connection = ContextVar('native_workflow_test_connection', default=None)
        self.authority = Mock()
        self.require_plan_execution = self.authority
        self.delegation = SimpleNamespace(consume_tool_budget=Mock())

    def sql(self, statement, **parameters):
        for name in ('body', 'result'):
            statement = statement.replace('CAST(:' + name + ' AS JSONB)', ':' + name)
        rows = super().sql(statement, **parameters)
        for row in rows:
            for name in ('body', 'result'):
                if isinstance(row.get(name), str):
                    row[name] = json.loads(row[name])
        return rows


class Runtime:
    def __init__(self):
        self.starts = []
        self.lookups = []
        self.inspections = []

    async def start(self, context, operation_id, inputs):
        self.starts.append(operation_id)
        raise WorkflowAcknowledgementUnknown()

    async def lookup(self, context, operation_id):
        self.lookups.append(operation_id)
        return {'schema': 1, 'operationId': operation_id,
            'handle': {'adapterId': 'controlled', 'revision': '1', 'id': operation_id},
            'state': 'COMPLETED', 'allStopped': True, 'output': {'controlled': True}, 'failure': None}

    async def inspect(self, context, handle):
        self.inspections.append(handle)
        return await self.lookup(context, handle['id'])

    async def cancel(self, context, handle):
        return {'schema': 1, 'operationId': handle['id'], 'handle': handle,
            'state': 'UNKNOWN', 'allStopped': False, 'output': None, 'failure': None}


class WorkflowControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = SQLiteStore(Path(directory.name) / 'metadata.db')
        self.addCleanup(self.store.engine.dispose)
        self.store.sql('CREATE TABLE af_tasks(id TEXT PRIMARY KEY,owner_id TEXT,run_id TEXT,plan_id TEXT,request_id TEXT,cancel_requested BOOLEAN,terminal BOOLEAN)')
        self.store.sql("INSERT INTO af_tasks VALUES('task','alice','native','plan','request',FALSE,FALSE)")
        self.store.sql('CREATE TABLE af_plans(id TEXT PRIMARY KEY,owner_id TEXT,body JSONB,hash TEXT)')
        self.plan = {'id': 'plan', 'ownerId': 'alice', 'nativeComponent': {'kind': 'workflow',
                     'id': 'controlled-workflow', 'revision': '1', 'sha256': 'a' * 64}}
        self.store.sql('INSERT INTO af_plans VALUES(:id,:owner,:body,:hash)', id='plan', owner='alice',
                       body=canonical(self.plan), hash=digest(self.plan))
        self.store.sql('CREATE TABLE af_effects(effect_key TEXT PRIMARY KEY,task_id TEXT,run_id TEXT,fingerprint TEXT,status TEXT,result JSONB)')
        self.runtime = Runtime()
        def authority(owner, permission):
            if owner != 'alice': raise HTTPException(403, 'CONTROLLED_OWNER_DENIED')
        self.auth = SimpleNamespace(require=authority)
        self.pin = {'adapterId': 'controlled', 'revision': '1', 'configFingerprint': 'b' * 64}
        self.service = OperationCustody(self.store, self.auth, runtimes={('controlled', '1', 'b' * 64): self.runtime})
        self.requirement = StepRequirement(step_id='review', step_name='Review', requires_confirmation=True).to_dict()
        self.native = {'run_id': 'native', 'workflow_id': 'controlled-workflow', 'status': 'paused',
                       'step_results': [], 'queue': {'status': 'paused'}, 'step_requirements': [self.requirement]}
        self.bridge = SimpleNamespace(detail=AsyncMock(side_effect=lambda *args: deepcopy(self.native)), continue_run=AsyncMock())
        self.commands = SimpleNamespace(submit=AsyncMock(), recover=AsyncMock())
        self.api = SimpleNamespace(store=self.store, auth=self.auth, bridge=self.bridge, commands=self.commands)
        self.control: Any = WorkflowControl(self.service, self.api)

    async def decision(self, identifier='decision'):
        view = (await self.control.snapshot('alice', 'task'))['workflow']
        return WorkflowCommand(commandId=identifier, action='decide', version=view['version'],
                               requirementId=view['requirements'][0]['id'], approved=True)

    async def external(self):
        task = self.store.task('task', 'alice')
        operation = await self.service.start(self.control.context(task), 'original-step', 'slot', self.pin, {})
        self.requirement = StepRequirement(step_id='wait', requires_executor_input=True,
            executor_requirements=[{'id': 'native-requirement', 'tool_execution': {
                'tool_call_id': 'original-native-call', 'tool_name': 'factory_wait_operations',
                'tool_args': {'operationIds': [operation['id']]}, 'external_execution_required': True,
                'result': None}}]).to_dict()
        self.native['step_requirements'] = [self.requirement]
        view = (await self.control.snapshot('alice', 'task'))['workflow']
        return operation, WorkflowCommand(commandId='reconcile', action='reconcile',
                                          version=view['version'], operationId=operation['id'])

    async def test_original_version_owner_and_changed_payload(self):
        command = await self.decision()
        with self.assertRaises(HTTPException):
            await self.control.submit('bob', 'task', command)
        with self.assertRaises(HTTPException):
            await self.control.submit('alice', 'task', command.model_copy(update={'version': 'f' * 64}))
        self.assertEqual(self.store.sql('SELECT * FROM af_native_workflow_commands'), [])
        def accept(*args):
            self.native['queue']['payload'] = {'continue': {'step_requirements': deepcopy(args[3])}}
        self.bridge.continue_run.side_effect = accept
        first = await self.control.submit('alice', 'task', command)
        self.assertEqual(first['status'], 'completed')
        # Reopen controller over the same durable journal; no second native effect.
        restored = WorkflowControl(self.service, self.api)
        self.assertEqual((await restored.submit('alice', 'task', command))['status'], 'completed')
        with self.assertRaises(HTTPException):
            await restored.submit('alice', 'task', command.model_copy(update={'approved': False}))
        self.assertEqual(self.bridge.continue_run.await_count, 1)
        self.store.delegation.consume_tool_budget.assert_not_called()

    async def test_lost_ack_without_handle_uses_original_lookup_never_start(self):
        operation, command = await self.external()
        self.assertIsNone(operation['handle'])
        result = await self.control.submit('alice', 'task', command)
        self.assertEqual(result['status'], 'unknown')  # no native queue receipt supplied
        await self.control.submit('alice', 'task', command)
        self.assertEqual(self.runtime.starts, [operation['id']])
        self.assertEqual(self.runtime.lookups, [operation['id']])
        self.assertEqual(self.runtime.inspections, [])
        self.assertTrue(self.service.read('alice', operation['id'])['closed'])
        self.assertEqual(self.bridge.continue_run.await_count, 1)
        args = self.store.delegation.consume_tool_budget.call_args.args
        self.assertEqual(args[1:], ('native-wait:' + digest({'stepId': 'wait', 'toolCallId': 'original-native-call'}), 'factory_wait_operations'))
        self.assertEqual(self.store.delegation.consume_tool_budget.call_count, 1)

    async def test_final_original_requirement_change_blocks_continue_and_debit(self):
        _, command = await self.external()
        calls = 0
        def native_read(*args):
            nonlocal calls
            calls += 1
            value = deepcopy(self.native)
            if calls >= 3:
                value['step_requirements'][0]['executor_requirements'][0]['tool_execution']['tool_call_id'] = 'replacement'
            return value
        self.bridge.detail.side_effect = native_read
        receipt = await self.control.submit('alice', 'task', command)
        self.assertEqual(receipt['status'], 'unknown')
        self.bridge.continue_run.assert_not_awaited()
        self.store.delegation.consume_tool_budget.assert_not_called()
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_cancel_unknown_recovers_original_receipt_after_lost_ack(self):
        command = WorkflowCommand(commandId='original-cancel', action='cancel')
        captured = []
        async def cancel(*args):
            captured.append(self.control._load('alice', 'task', 'original-cancel'))
            raise ConnectionError('controlled acknowledgement loss')
        self.commands.submit.side_effect = cancel
        self.commands.recover.return_value = {'state': 'UNKNOWN', 'decisionRecorded': False, 'stopConfirmed': False}
        result = await self.control.submit('alice', 'task', command)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(captured[0]['cancelCommand'], 'original-cancel')
        self.commands.recover.return_value = {'decisionRecorded': True, 'stopConfirmed': False}
        self.assertEqual((await self.control.receipt('alice', 'task', command.commandId))['status'], 'recorded')
        self.commands.recover.return_value = {'decisionRecorded': True, 'stopConfirmed': True}
        self.assertEqual((await self.control.receipt('alice', 'task', command.commandId))['status'], 'completed')
        self.commands.recover.assert_awaited_with('alice', 'task', 'original-cancel')
        self.assertEqual(self.commands.submit.await_count, 1)
        self.bridge.continue_run.assert_not_awaited()

    async def test_inner_cancel_unknown_is_not_completed(self):
        self.commands.submit.return_value = {'decisionRecorded': True, 'stopConfirmed': False}
        self.commands.recover.return_value = {'decisionRecorded': True, 'stopConfirmed': False}
        result = await self.control.submit('alice', 'task', WorkflowCommand(commandId='cancel', action='cancel'))
        self.assertEqual(result['status'], 'recorded')
        self.assertNotEqual(result['status'], 'completed')

    async def test_run_cancelled_authority_still_returns_read_only_view(self):
        self.store.authority.side_effect = RunCancelledException('controlled cancellation')
        view = await self.control.snapshot('alice', 'task')
        self.assertTrue(view['available'])
        self.assertEqual(view['allowedActions'], [{'action': 'cancel'}])
        self.assertEqual(self.store.sql('SELECT * FROM af_native_workflow_commands'), [])
        self.bridge.continue_run.assert_not_awaited()

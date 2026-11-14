"""An unknown operation blocks its replay, not unrelated native tool calls."""
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import AsyncMock

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.tools.function import FunctionCall

from agent_factory.personal_tool_contract import PersonalToolAdapter, ToolDescriptor, ToolInvocationError
from agent_factory.personal_tool_execution import personal_tool_function


class Effects:
    def __init__(self):
        self.rows = {}
        self.cancelled = False
        self.personal_tools: Any = None

    def effect_reserve(self, run, key, request):
        if key in self.rows:
            return self.rows[key]
        self.rows[key] = {'status': 'unknown', 'result': None}
        return {'status': 'new'}

    def effect_complete(self, run, key, receipt):
        self.rows[key] = {'status': 'done', 'result': receipt}

    def effects(self, task):
        return [{'effect_key': 'run:' + key, 'status': 'UNKNOWN'} for key in self.rows]

    def event(self, *args):
        pass

    def task(self, task, owner):
        return {'id': 'task', 'run_id': 'run'}

    def task_for_context(self, context):
        return self.task(context.run_id, context.user_id)

    def cancellation_requested(self, run):
        return self.cancelled


async def call(function, context, identifier, **arguments):
    function._run_context = context
    result = await FunctionCall(function=function, call_id=identifier, arguments=arguments).aexecute()
    if result.status != 'success':
        raise AssertionError(result.error)
    assert isinstance(result.result, dict)
    return result.result


class UnknownToolOutcome(unittest.IsolatedAsyncioTestCase):
    async def test_personal_unknown_keeps_other_calls_available_without_replay(self):
        store = Effects()
        context = RunContext(run_id='run', session_id='task', user_id='owner')
        descriptor = ToolDescriptor(adapter_id='sample', revision='1', tool_name='sample', description='Sample',
            input_schema={'type': 'object', 'properties': {'operation': {'type': 'string'}},
                          'required': ['operation']}, transport='mcp', credential_provider_id='sample',
            credential_destination='sample', capabilities=('tool:invoke',))
        adapter = SimpleNamespace(descriptor=descriptor, invoke=AsyncMock(side_effect=[
            ToolInvocationError('ACK_UNKNOWN', outcome='unknown', stopped=False), {'observed': True}]))
        service = SimpleNamespace(adapters={'sample': adapter})
        store.personal_tools = service
        handle = SimpleNamespace(configuration={'registrationRef': 'ref', 'revision': '1'},
            adapter=adapter, service=service, requesting_actor='owner', check_authorized=lambda: None)
        function = personal_tool_function(cast(PersonalToolAdapter, adapter), store, handle, context)
        first = await call(function, context, 'write', arguments={'operation': 'write'})
        self.assertEqual(first['outcome'], 'unknown')
        self.assertEqual(first['effectKey'], 'run:personal-tool:write')
        repeated = await call(function, context, 'write', arguments={'operation': 'write'})
        self.assertEqual(repeated['outcome'], 'unknown')
        self.assertEqual(adapter.invoke.await_count, 1)
        self.assertEqual(await call(function, context, 'inspect', arguments={'operation': 'inspect'}), {'observed': True})
        store.cancelled = True
        with self.assertRaises(RunCancelledException):
            await call(function, context, 'stopped', arguments={'operation': 'inspect'})

    async def test_read_only_errors_and_stop_remain_visible_without_effects(self):
        store = Effects()
        context = RunContext(run_id='run', session_id='task', user_id='owner')
        descriptor = ToolDescriptor(adapter_id='reader', revision='1', tool_name='reader', description='Read',
            input_schema={'type': 'object', 'properties': {}}, transport='mcp',
            credential_provider_id='reader', credential_destination='reader', capabilities=('tool:invoke',),
            read_only=True)
        events = []
        store.event = lambda *args: events.append(args)
        adapter = SimpleNamespace(descriptor=descriptor, invoke=AsyncMock(side_effect=[
            ToolInvocationError('READ_FAILED', outcome='failed', stopped=True, output='file missing'),
            ToolInvocationError('READ_DISCONNECTED', outcome='unknown', stopped=False),
            ToolInvocationError('READ_CLEANUP_FAILED', outcome='failed', stopped=False, output='cleanup diagnostic'),
            {'observed': True}, ToolInvocationError('READ_CANCELLED', outcome='cancelled', stopped=True)]))
        service = SimpleNamespace(adapters={'reader': adapter})
        store.personal_tools = service
        handle = SimpleNamespace(configuration={'registrationRef': 'ref', 'revision': '1'},
            adapter=adapter, service=service, requesting_actor='owner', check_authorized=lambda: None)
        function = personal_tool_function(cast(PersonalToolAdapter, adapter), store, handle, context)
        function._run_context = context
        failed = await FunctionCall(function=function, call_id='failed', arguments={'arguments': {}}).aexecute()
        self.assertNotEqual(failed.status, 'success')
        self.assertIn('file missing', str(failed.error))
        uncertain = await call(function, context, 'disconnected', arguments={})
        self.assertEqual(uncertain['outcome'], 'unknown')
        self.assertNotIn('effectKey', uncertain)
        self.assertIn('You may read again', uncertain['message'])
        cleanup = await call(function, context, 'cleanup', arguments={})
        self.assertEqual((cleanup['outcome'], cleanup['stopped'], cleanup['output']),
                         ('failed', False, 'cleanup diagnostic'))
        self.assertIn('You may read again', cleanup['message'])
        self.assertEqual(await call(function, context, 'retry', arguments={}), {'observed': True})
        with self.assertRaises(RunCancelledException):
            await call(function, context, 'adapter-cancelled', arguments={})
        self.assertEqual([event[3].get('outcome') for event in events if event[1] == 'tool_finished'],
                         ['failed', 'unknown', 'failed', 'completed', 'cancelled'])
        self.assertEqual(store.rows, {})
        store.cancelled = True
        with self.assertRaises(RunCancelledException):
            await call(function, context, 'stopped', arguments={})
        self.assertEqual(adapter.invoke.await_count, 5)

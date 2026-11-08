"""An unknown operation blocks its replay, not unrelated native tool calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import AsyncMock, patch

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.tools.function import FunctionCall

from agent_factory.personal_tool_contract import PersonalToolAdapter, ToolDescriptor, ToolInvocationError
from agent_factory.personal_tool_execution import personal_tool_function
from research.session_tools import ResearchSessionTools


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
        return {'run_id': 'run'}

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
    async def test_research_unknown_keeps_reads_available_without_replay(self):
        store = Effects()
        context = RunContext(run_id='run', session_id='task', user_id='owner')
        def authorize(*_):
            if store.cancelled:
                raise RunCancelledException('stopped')
            return {'ownerId': 'owner', 'id': 'session', 'turnId': 'turn'}
        with TemporaryDirectory() as directory:
            tools = ResearchSessionTools(workspace_root=Path(directory))
            tools.sessions = SimpleNamespace(store=store, authorize_tool=authorize)
            workspace = tools._workspace(authorize())
            (workspace / 'note.txt').write_text('independent evidence')
            command = tools._function(store, context, 'research_run')
            with patch.object(tools, '_run', new=AsyncMock(side_effect=ToolInvocationError(
                    'COMMAND_ACK_UNKNOWN', outcome='unknown', stopped=False))) as run:
                first = await call(command, context, 'command', argv=['echo', 'value'])
                self.assertEqual(first['outcome'], 'unknown')
                self.assertFalse(first['stopped'])
                self.assertEqual(first['effectKey'], 'run:research-session-tool:command')
                repeated = await call(command, context, 'command', argv=['echo', 'value'])
                self.assertEqual(repeated['outcome'], 'unknown')
                self.assertEqual(run.await_count, 1)
                listing = await call(tools._function(store, context, 'research_read_file'), context, 'read', path='note.txt')
                self.assertEqual(listing['text'], 'independent evidence')
                store.cancelled = True
                with self.assertRaises(RunCancelledException):
                    await call(command, context, 'after-stop', argv=['echo', 'value'])

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

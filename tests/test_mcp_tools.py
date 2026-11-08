"""Personal tool discovery and calls through a local MCP HTTP server and Agno."""
import asyncio
from contextlib import nullcontext
from dataclasses import replace
import socket
from types import SimpleNamespace
import unittest

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.tools.function import FunctionCall
from jsonschema import Draft202012Validator
from mcp import types
from mcp.server.lowlevel import Server
import uvicorn

from agent_factory.personal_mcp import MCPToolAdapter, discover_mcp_tools
from agent_factory.personal_tool_contract import ToolDescriptor
from agent_factory.personal_tools import PersonalTools
from test_tool_unknown import Effects


class MCPToolsJourney(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.dispatched = asyncio.Event()
        self.schema = {'type': 'object', 'properties': {'mode': {'$ref': '#/$defs/mode'}},
            '$defs': {'mode': {'type': 'string'}}, 'required': ['mode'],
            'additionalProperties': {'type': 'string'}}

        async def listing(ctx, params):
            return types.ListToolsResult(tools=[types.Tool(name=name, description=name, input_schema=self.schema)
                for name in ('first', 'second')])

        async def execute(ctx, params):
            self.received.append((params.name, params.arguments))
            if params.arguments['mode'] == 'wait':
                self.dispatched.set()
                await asyncio.sleep(60)
            failed = params.arguments['mode'] == 'fail'
            return types.CallToolResult(content=[types.TextContent(type='text', text='diagnostic' if failed else 'ok')],
                structured_content={'remote': params.name, 'arguments': params.arguments}, is_error=failed)

        app = Server('fixture', on_list_tools=listing, on_call_tool=execute).streamable_http_app()
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        self.addCleanup(listener.close)
        self.url = f'http://127.0.0.1:{listener.getsockname()[1]}/mcp'
        self.server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        task = asyncio.create_task(self.server.serve(sockets=[listener]))
        async def shutdown():
            self.server.should_exit = True
            await asyncio.wait_for(task, 10)
        self.addAsyncCleanup(shutdown)
        while not self.server.started:
            if task.done():
                await task
            await asyncio.sleep(.01)
        discovered = await discover_mcp_tools(self.url)
        self.assertEqual({item['name'] for item in discovered}, {'first', 'second'})
        self.context = RunContext(run_id='run', session_id='task', user_id='owner')
        self.store = Effects()
        service = object.__new__(PersonalTools)
        self.store.personal_tools = service
        service.connections = SimpleNamespace(store=self.store, _read=lambda: nullcontext(None))
        service.adapters = {}
        handles, resources = {}, []
        for item in discovered:
            descriptor = ToolDescriptor(adapter_id=item['name'], revision='1', tool_name='same',
                description=item['description'], input_schema=item['inputSchema'], transport='mcp',
                credential_provider_id='fixture', credential_destination=self.url, capabilities=('tool:invoke',))
            adapter = MCPToolAdapter(descriptor, url=self.url, remote_tool_name=item['name'])
            service.adapters[item['name']] = adapter
            handles[item['name']] = SimpleNamespace(configuration={'registrationRef': item['name'], 'revision': '1'},
                adapter=adapter, service=service, requesting_actor='owner', check_authorized=lambda: None,
                resolve_credential=lambda **_: None)
            resources.append({'toolName': 'same', 'ownerId': 'owner', 'registrationRef': item['name'],
                              'adapterId': item['name'], 'available': True})
        service.list = lambda _: resources
        service.ensure_registered = lambda _: None
        service.binding = lambda conn, owner, ref: SimpleNamespace(opaque_handle=handles[ref])
        self.service = service

    async def call(self, function, identifier, arguments):
        function._run_context = self.context
        return await FunctionCall(function=function, call_id=identifier, arguments={'arguments': arguments}).aexecute()

    async def test_same_names_reserved_arguments_and_identity(self):
        functions = self.service.functions('owner', self.context)
        self.assertEqual(len({function.name for function in functions}), 2)
        self.assertEqual(functions[0].name, 'same')
        reserved = self.service.functions('owner', self.context, reserved_names=['same'])
        self.assertEqual(len({function.name for function in reserved}), 2)
        self.assertNotIn('same', [function.name for function in reserved])
        self.assertEqual([function.name for function in reserved],
            [function.name for function in self.service.functions('owner', self.context, reserved_names=['same'])])
        arguments = {key: key + '-business' for key in ('fc', 'run_context', '_agno_run_context',
                     '_agno_agent', '_agno_team', 'arguments')}
        arguments['mode'] = 'ok'
        for index, function in enumerate(reserved):
            Draft202012Validator(function.parameters).validate({'arguments': arguments})
            result = await self.call(function, str(index), arguments)
            self.assertEqual(result.status, 'success')
            self.assertEqual(result.result['structuredContent'],
                {'remote': ('first', 'second')[index], 'arguments': arguments})
        self.assertEqual(len(self.received), 2)
        # Explicit properties are accepted too; the server above uses additionalProperties.
        descriptor = self.service.adapters['first'].descriptor
        replace(descriptor, input_schema={'type': 'object', 'properties':
            {key: {'type': 'string'} for key in arguments}})
        reserved[0]._run_context = RunContext(run_id='run', session_id='task', user_id='other')
        denied = await FunctionCall(function=reserved[0], call_id='wrong-owner',
            arguments={'arguments': arguments}).aexecute()
        self.assertEqual(denied.status, 'failure')
        self.assertEqual(len(self.received), 2)

    async def test_failure_then_continue_and_stop_are_not_success(self):
        function = self.service.functions('owner', self.context)[0]
        invalid = await self.call(function, 'invalid', {'mode': 12})
        self.assertEqual(invalid.status, 'failure')
        self.assertEqual(self.received, [])
        failed = await self.call(function, 'failed', {'mode': 'fail'})
        self.assertEqual(failed.status, 'failure')
        self.assertIn('diagnostic', failed.error)
        self.assertEqual((await self.call(function, 'continue', {'mode': 'ok'})).status, 'success')
        active = asyncio.create_task(self.call(function, 'cancelled', {'mode': 'wait'}))
        await asyncio.wait_for(self.dispatched.wait(), 5)
        active.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await active
        self.assertEqual(self.store.rows['personal-tool:cancelled']['status'], 'unknown')
        before = len(self.received)
        repeated = await self.call(function, 'cancelled', {'mode': 'wait'})
        self.assertEqual(repeated.result['outcome'], 'unknown')
        self.assertEqual(len(self.received), before)
        self.store.cancelled = True
        with self.assertRaises(RunCancelledException):
            await self.call(function, 'after-stop', {'mode': 'ok'})
        self.assertEqual(len(self.received), before)

"""Personal tool discovery and calls through a local MCP HTTP server and Agno."""
import asyncio
from contextlib import AsyncExitStack, nullcontext
from dataclasses import replace
import json
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

from agent_factory.personal_mcp import MCPRunConnections, MCPToolAdapter, discover_mcp_tools
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocation
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.personal_tools import PersonalTools
from test_tool_unknown import Effects


class MCPToolsJourney(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received, self.requests = [], []
        self.dispatched = asyncio.Event()
        self.connecting, self.continue_handshake = asyncio.Event(), asyncio.Event()
        self.schema = {'type': 'object', 'properties': {'mode': {'$ref': '#/$defs/mode'}},
            '$defs': {'mode': {'type': 'string'}}, 'required': ['mode'],
            'additionalProperties': {'type': 'string'}}

        async def listing(ctx, params):
            return types.ListToolsResult(tools=[types.Tool(name=name, description=name, input_schema=self.schema,
                output_schema={'type': 'object', 'properties': {'remote': {'type': 'string'},
                    'arguments': {'type': 'object'}}, 'required': ['remote', 'arguments']})
                for name in ('first', 'second')])

        async def execute(ctx, params):
            self.received.append((params.name, params.arguments))
            if params.arguments['mode'] == 'wait':
                self.dispatched.set()
                await asyncio.sleep(60)
            failed = params.arguments['mode'] == 'fail'
            return types.CallToolResult(content=[types.TextContent(type='text', text='diagnostic' if failed else 'ok')],
                structured_content={'remote': 12 if params.arguments['mode'] == 'bad-schema' else params.name,
                                    'arguments': params.arguments}, is_error=failed)

        app = Server('fixture', on_list_tools=listing, on_call_tool=execute).streamable_http_app()
        async def traced(scope, receive, send):
            if scope['type'] != 'http':
                return await app(scope, receive, send)
            body = bytearray()
            async def read():
                message = await receive()
                if message['type'] == 'http.request':
                    body.extend(message.get('body', b''))
                    if not message.get('more_body') and body:
                        data = json.loads(body)
                        self.requests.append((scope['method'], dict(scope['headers']), data))
                        if (data.get('method') == 'initialize' and
                                dict(scope['headers']).get(b'authorization') == b'Bearer held-handshake'):
                            self.connecting.set()
                            await self.continue_handshake.wait()
                return message
            if scope['method'] == 'DELETE':
                self.requests.append(('DELETE', dict(scope['headers']), {}))
            await app(scope, read, send)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        self.addCleanup(listener.close)
        self.url = f'http://127.0.0.1:{listener.getsockname()[1]}/mcp'
        self.server = uvicorn.Server(uvicorn.Config(traced, log_level='error', access_log=False))
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

    async def test_run_connection_reuses_parallel_calls_and_closes_on_error(self):
        handle = self.service.binding(None, 'owner', 'first').opaque_handle
        handle.resolve_credential = lambda **_: SecretLease('fixture', 'fixture-token')
        before = len([r for r in self.requests if r[2].get('method') == 'initialize'])
        with self.assertRaisesRegex(ValueError, 'run failed'):
            async with AsyncExitStack() as stack:
                connections = MCPRunConnections()
                stack.push_async_callback(connections.close)
                functions = self.service.functions('owner', self.context, mcp_connections=connections)
                first, second = await asyncio.gather(
                    self.call(functions[0], 'parallel-one', {'mode': 'ok'}),
                    self.call(functions[0], 'parallel-two', {'mode': 'ok'}))
                self.assertEqual((first.status, second.status), ('success', 'success'))
                self.assertEqual((await self.call(functions[0], 'remote-error', {'mode': 'fail'})).status, 'failure')
                malformed = await self.call(functions[0], 'bad-schema', {'mode': 'bad-schema'})
                self.assertEqual(malformed.result['outcome'], 'unknown')
                self.assertEqual((await self.call(functions[0], 'recover', {'mode': 'ok'})).status, 'success')
                self.assertEqual(len([r for r in self.requests if r[2].get('method') == 'initialize']), before + 1)
                calls = [r for r in self.requests if r[2].get('method') == 'tools/call']
                identifiers = {r[1].get(b'mcp-session-id') for r in calls}
                self.assertEqual(len(identifiers), 1)
                self.assertNotIn(None, identifiers)
                self.assertTrue(all(r[1].get(b'authorization') == b'Bearer fixture-token' for r in calls))
                self.assertTrue(all(r[1].get(b'mcp-protocol-version') == b'2025-11-25' for r in calls))
                raise ValueError('run failed')
        self.assertTrue(any(r[0] == 'DELETE' and r[1].get(b'mcp-session-id') in identifiers for r in self.requests))

    async def test_run_connections_separate_owners_resources_and_revisions(self):
        before = len([r for r in self.requests if r[2].get('method') == 'initialize'])
        async with AsyncExitStack() as stack:
            connections = MCPRunConnections()
            stack.push_async_callback(connections.close)
            functions = self.service.functions('owner', self.context, mcp_connections=connections)
            for index, function in enumerate(functions):
                self.assertEqual((await self.call(function, 'resource-' + str(index), {'mode': 'ok'})).status, 'success')
            handle = self.service.binding(None, 'owner', 'first').opaque_handle
            handle.configuration = {**handle.configuration, 'revision': '2'}
            renewed = self.service.functions('owner', self.context, mcp_connections=connections)[0]
            self.assertEqual((await self.call(renewed, 'revision-two', {'mode': 'ok'})).status, 'success')
            adapter = self.service.adapters['first']
            other = ToolInvocation(owner_id='other', connection_ref='first', connection_revision='1',
                call_id='other-owner', arguments={'mode': 'ok'},
                run_context=RunContext(run_id='other-run', session_id='other-task', user_id='other'),
                check_authorized=lambda: None, resolve_credential=lambda: None, mcp_connections=connections)
            self.assertEqual((await adapter.invoke(other))['structuredContent']['remote'], 'first')
            self.assertEqual(len([r for r in self.requests if r[2].get('method') == 'initialize']), before + 4)
        calls = [r for r in self.requests if r[2].get('method') == 'tools/call']
        self.assertEqual(len({r[1][b'mcp-session-id'] for r in calls}), 4)

    async def test_native_agent_closes_connections_on_completion_error_and_cancellation(self):
        from http.server import ThreadingHTTPServer
        import threading
        from agent_factory.byok_model import OwnerChatModel
        from agent_factory.runtime import build_runtime
        from test_native_model import Endpoint, chunk, reply

        server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        server.requests, server.hold = [], None
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config = {'provider': 'openai-compatible', 'model': 'fixture',
                  'baseURL': f'http://127.0.0.1:{server.server_port}/v1'}
        self.store.personal_models = SimpleNamespace(model_for=lambda *args, **kwargs:
            OwnerChatModel(config, lambda: None))
        self.store.bind_run = lambda _: None
        plan = {'normalizedGoal': 'Use the configured MCP tool', 'connectionRefs': {'model': 'fixture'}}
        self.store.resolve_run = lambda _: plan
        self.store.plan = lambda *args: plan
        for mode in ('complete', 'error', 'cancel'):
            with self.subTest(mode=mode):
                server.requests.clear()
                self.dispatched.clear()
                self.store.rows.clear()
                before = len([r for r in self.requests if r[2].get('method') == 'initialize'])
                def answer(body):
                    number = len(server.requests)
                    if mode == 'error' and number > 1:
                        return 503, {'error': {'message': 'fixture model failure'}}
                    if number <= 2:
                        return 200, [chunk({'role': 'assistant', 'tool_calls': [{
                            'index': 0, 'id': mode + str(number), 'type': 'function',
                            'function': {'name': 'same', 'arguments': json.dumps({'arguments':
                                {'mode': 'wait' if mode == 'cancel' else 'ok'}})}}]}), chunk({}, 'tool_calls')]
                    return 200, reply('MCP calls finished')
                server.answer = answer
                run_id = 'native-' + mode
                self.store.task = lambda task, owner: {'run_id': run_id, 'plan_id': 'plan'}
                agent, _ = build_runtime(self.store, None)
                async def run():
                    return await agent.arun('Use the tool twice', run_id=run_id,
                        session_id='task', user_id='owner')
                task = asyncio.create_task(run())
                if mode == 'cancel':
                    await asyncio.wait_for(self.dispatched.wait(), 5)
                    task.cancel()
                try:
                    result = await asyncio.wait_for(task, 10)
                except asyncio.CancelledError:
                    self.assertEqual(mode, 'cancel')
                    result = None
                if mode == 'complete':
                    self.assertEqual(result.status.value, 'COMPLETED')
                    self.assertEqual(len(server.requests), 3)
                elif mode == 'error':
                    self.assertEqual(result.status.value, 'ERROR')
                opened = [r for r in self.requests if r[2].get('method') == 'initialize']
                self.assertEqual(len(opened), before + 1)
                self.assertEqual(agent._mcp_tools_initialized_on_run, [])
                calls = [r for r in self.requests if r[2].get('method') == 'tools/call'
                         and r[2].get('params', {}).get('arguments', {}).get('mode') ==
                         ('wait' if mode == 'cancel' else 'ok')]
                session_id = calls[-1][1][b'mcp-session-id']
                self.assertTrue(any(r[0] == 'DELETE' and r[1].get(b'mcp-session-id') == session_id
                                    for r in self.requests))

    async def test_slow_first_connection_does_not_block_another_resource(self):
        handle = self.service.binding(None, 'owner', 'first').opaque_handle
        handle.resolve_credential = lambda **_: SecretLease('fixture', 'held-handshake')
        async with AsyncExitStack() as stack:
            connections = MCPRunConnections()
            stack.push_async_callback(connections.close)
            functions = self.service.functions('owner', self.context, mcp_connections=connections)
            slow = asyncio.create_task(self.call(functions[0], 'slow-resource', {'mode': 'ok'}))
            try:
                await asyncio.wait_for(self.connecting.wait(), 5)
                quick = await asyncio.wait_for(self.call(functions[1], 'other-resource', {'mode': 'ok'}), 5)
                self.assertEqual(quick.status, 'success')
                self.assertFalse(slow.done())
                await connections.close()
            finally:
                self.continue_handshake.set()
                late = await slow
            self.assertEqual(late.status, 'failure')
            self.assertEqual(self.received, [('second', {'mode': 'ok'})])
            self.assertEqual(len([r for r in self.requests if r[0] == 'DELETE']), 3)

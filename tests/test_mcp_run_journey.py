"""Real queue and browser journey for configured MCP connections and native Stop."""
import asyncio
from http.server import ThreadingHTTPServer
import json
import socket
import threading
import time
import unittest

from mcp import types
from mcp.server.lowlevel import Server
from playwright.sync_api import expect
import uvicorn

import test_chat_journey as journey
from test_native_model import Endpoint, chunk, reply


class MCPQueueJourney(unittest.TestCase):
    setUpClass = classmethod(journey.ChatJourney.setUpClass.__func__)
    setUp = journey.ChatJourney.setUp
    post = journey.ChatJourney.post
    session = journey.ChatJourney.session
    wait_for = journey.ChatJourney.wait_for
    send = journey.ChatJourney.send

    def test_queue_reuses_connections_reconfiguration_and_stop(self):
        requests, called = [], []
        waiting, stopped = threading.Event(), threading.Event()
        schema = {'type': 'object', 'properties': {'wait': {'type': 'boolean'}}}
        async def listing(ctx, params):
            return types.ListToolsResult(tools=[types.Tool(name='read_fixture', input_schema=schema)])
        async def execute(ctx, params):
            called.append(params.arguments)
            if params.arguments.get('wait'):
                waiting.set()
                try:
                    await asyncio.sleep(600)
                finally:
                    stopped.set()
            return types.CallToolResult(content=[types.TextContent(type='text', text='fixture value 42')])
        mcp_app = Server('queue-fixture', on_list_tools=listing, on_call_tool=execute).streamable_http_app()
        async def traced(scope, receive, send):
            if scope['type'] != 'http':
                return await mcp_app(scope, receive, send)
            if scope['method'] == 'DELETE':
                requests.append(('DELETE', dict(scope['headers'])))
            body = bytearray()
            async def read():
                message = await receive()
                if message['type'] == 'http.request':
                    body.extend(message.get('body', b''))
                    if not message.get('more_body') and body:
                        requests.append((json.loads(body).get('method'), dict(scope['headers'])))
                return message
            await mcp_app(scope, read, send)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        self.addCleanup(listener.close)
        url = f'http://127.0.0.1:{listener.getsockname()[1]}/mcp'
        server = uvicorn.Server(uvicorn.Config(traced, log_level='error', access_log=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        def shutdown():
            server.should_exit = True
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.addCleanup(shutdown)
        deadline = time.monotonic() + 10
        while not server.started:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        discovered = self.context.request.post(self.origin + '/api/factory/personal-tools/discover',
            data={'url': url}, headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf})
        self.assertTrue(discovered.ok, discovered.text())
        discovery = discovered.json()
        resource = {'transport': 'mcp', 'toolName': 'read_fixture', 'description': 'Read fixture value',
                    'url': url, 'remoteToolName': 'read_fixture', 'inputSchema': discovery['tools'][0]['inputSchema'],
                    'readOnly': True}
        configured = self.post('/personal-tools/resources', resource)
        model = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        model.requests, model.hold = [], None
        def answer(body):
            outputs = [message for message in body['messages'] if message['role'] == 'tool']
            user_text = next(message['content'] for message in reversed(body['messages']) if message['role'] == 'user')
            if len(outputs) < 2:
                return 200, [chunk({'role': 'assistant', 'tool_calls': [{'index': 0,
                    'id': 'read-' + str(len(outputs)), 'type': 'function', 'function': {'name': 'read_fixture',
                    'arguments': json.dumps({'arguments': {'wait': user_text == 'MCP Stop'}})}}]}), chunk({}, 'tool_calls')]
            return 200, reply('MCP 两次读取完成。')
        model.answer = answer
        threading.Thread(target=model.serve_forever, daemon=True).start()
        self.addCleanup(model.server_close)
        self.addCleanup(model.shutdown)
        self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'mcp-queue',
            'baseURL': f'http://127.0.0.1:{model.server_port}/v1'})
        self.page.reload()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='mcp-queue', exact=True).click()
        self.send('MCP 两次读取')
        first = self.wait_for(lambda value: value['turns'][-1]['status'] == 'completed')
        self.assertEqual(len(called), 2)
        calls = [headers[b'mcp-session-id'] for method, headers in requests if method == 'tools/call']
        self.assertEqual(len(set(calls)), 1)
        self.assertEqual(sum(method == 'initialize' for method, _ in requests), 2)  # discovery + native run
        self.assertTrue(any(method == 'DELETE' and headers.get(b'mcp-session-id') == calls[-1]
                            for method, headers in requests))
        expect(self.page.locator('.rs-turn')).to_contain_text('MCP 两次读取完成。')
        self.post('/personal-tools/' + configured['registrationRef'] + '/revoke', {})
        self.post('/personal-tools/resources', resource)
        self.post('/research/sessions/' + first['id'] + '/turns', {'text': 'MCP Stop'})
        self.assertTrue(waiting.wait(10))
        self.post('/research/sessions/' + first['id'] + '/stop', {})
        final = self.wait_for(lambda value: len(value['turns']) == 2 and value['turns'][-1]['status'] == 'canceled')
        self.assertTrue(stopped.wait(5))
        calls = [headers[b'mcp-session-id'] for method, headers in requests if method == 'tools/call']
        self.assertEqual(len(calls), 3)
        self.assertNotEqual(calls[0], calls[-1])
        self.assertTrue(any(method == 'DELETE' and headers.get(b'mcp-session-id') == calls[-1]
                            for method, headers in requests))
        self.page.reload()
        expect(self.page.locator('.rs-turn')).to_have_count(2)
        self.assertEqual(final['turns'][0]['status'], 'completed')

"""Feature regressions through Agno and an actual local HTTP model endpoint."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread
from types import SimpleNamespace
import unittest

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.media import Image, File
from agno.models.message import Message
from pydantic import BaseModel

from agent_factory.byok_model import OwnerChatModel


def chunk(delta, finish=None):
    return {'id': 'local', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fixture',
        'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}


def reply(content):
    return [chunk({'role': 'assistant', 'content': content}), chunk({}, 'stop')]


class Endpoint(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((body, dict(self.headers)))
        status, payload = self.server.answer(body)
        self.send_response(status)
        self.send_header('Content-Type', 'text/event-stream' if isinstance(payload, list) else 'application/json')
        self.end_headers()
        try:
            if isinstance(payload, list):
                for value in payload:
                    self.wfile.write(('data: ' + json.dumps(value) + '\n\n').encode())
                    self.wfile.flush()
                    if self.server.hold is not None:
                        self.server.started.set()
                        self.server.hold.wait(5)
                self.wfile.write(b'data: [DONE]\n\n')
            else:
                self.wfile.write(json.dumps(payload).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


class NativeOwnerModel(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        self.server.requests, self.server.hold = [], None
        self.server.started = Event()
        self.server.answer = lambda _: (200, reply('done'))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = {'provider': 'openai-compatible', 'model': 'fixture',
            'baseURL': f'http://127.0.0.1:{self.server.server_port}/v1'}

    async def asyncTearDown(self):
        if self.server.hold:
            self.server.hold.set()
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join()

    async def test_native_structured_multimodal_and_compressed_content_reach_provider(self):
        class Answer(BaseModel):
            count: int
        self.server.answer = lambda _: (200, reply('{"count":42}'))
        model = OwnerChatModel(self.config, lambda: None)
        agent = Agent(model=model, output_schema=Answer, telemetry=False)
        result = await agent.arun('read this', images=[Image(url='https://example.invalid/image.png')],
            files=[File(content=b'result=42', filename='result.txt', mime_type='text/plain')])
        self.assertEqual(result.content.count, 42)
        request = self.server.requests[-1][0]
        self.assertEqual(request['response_format']['type'], 'json_schema')
        parts = next(message['content'] for message in request['messages'] if message['role'] == 'user')
        self.assertEqual({part['type'] for part in parts}, {'text', 'image_url', 'file'})
        self.assertNotIn('max_tokens', request)
        self.assertNotIn('parallel_tool_calls', request)
        await model.ainvoke([Message(role='tool', tool_call_id='call_result', content='original-large-result',
            compressed_content='summary=42')], compress_tool_results=True, response_format={'type': 'json_object'})
        self.assertEqual(self.server.requests[-1][0]['messages'][-1]['content'], 'summary=42')
        self.assertEqual(self.server.requests[-1][0]['response_format'], {'type': 'json_object'})

    async def test_native_tool_loop_preserves_reasoning_and_order_without_private_replay_record(self):
        events = []
        async def text(value, response_id): events.append(('text', value, response_id))
        async def thought(value, response_id): events.append(('thought', value, response_id))
        def diagnose() -> str:
            """Return an ordinary command failure for analysis."""
            events.append(('tool', 'exit 7', ''))
            return 'exit 7: missing input'
        def answer(body):
            if not any(message['role'] == 'tool' for message in body['messages']):
                return 200, [chunk({'role': 'assistant', 'reasoning_content': 'inspect'}),
                    chunk({'role': None, 'content': 'running'}),
                    chunk({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_diagnose',
                        'type': 'function', 'function': {'name': 'diagnose', 'arguments': '{}'}}]}),
                    chunk({}, 'tool_calls')]
            return 200, reply('continue after exit 7')
        self.server.answer = answer
        model = OwnerChatModel(self.config, lambda: None, on_text=text, on_reasoning=thought)
        result = await Agent(model=model, tools=[diagnose], telemetry=False).arun('diagnose and continue')
        self.assertTrue(result.content.endswith('continue after exit 7'))
        messages = self.server.requests[-1][0]['messages']
        assistant = next(message for message in messages if message.get('tool_calls'))
        self.assertEqual(assistant['reasoning_content'], 'inspect')
        self.assertIn('exit 7', next(message['content'] for message in messages if message['role'] == 'tool'))
        self.assertEqual([(kind, text) for kind, text, _ in events],
            [('thought', 'inspect'), ('text', 'running'), ('tool', 'exit 7'), ('text', 'continue after exit 7')])
        self.assertEqual(events[0][2], events[1][2])
        self.assertNotEqual(events[1][2], events[-1][2])

    async def test_each_request_refreshes_owner_credentials_redacts_errors_and_cancel_is_not_success(self):
        lease, checks, events = SimpleNamespace(password='owner-one'), [], []
        async def text(value, _): events.append(value)
        model = OwnerChatModel(self.config, lambda: lease, recheck=lambda: checks.append(True), on_text=text)
        await model.ainvoke([Message(role='user', content='first')])
        lease.password = 'owner-two'
        model._on_text = None  # Auxiliary compression/summarization does not enter chat.
        await model.ainvoke([Message(role='user', content='second')])
        self.assertEqual([headers['Authorization'] for _, headers in self.server.requests],
            ['Bearer owner-one', 'Bearer owner-two'])
        self.assertEqual(len(checks), 4)
        self.assertEqual(events, ['done'])
        self.server.answer = lambda _: (503, {'error': {'message': 'owner-two private body'}})
        with self.assertRaisesRegex(ModelProviderError, '^PERSONAL_MODEL_HTTP_503$'):
            await model.ainvoke([Message(role='user', content='fail')])
        self.assertEqual(len(self.server.requests), 3)  # No automatic SDK retry.
        self.server.answer = lambda _: (200, reply('partial'))
        self.server.hold = Event()
        task = asyncio.create_task(model.ainvoke([Message(role='user', content='stop')]))
        self.assertTrue(await asyncio.to_thread(self.server.started.wait, 3))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        self.server.hold.set()
        await model.ainvoke([Message(role='user', content='continue')])
        self.assertEqual(len(self.server.requests), 5)
        def revoked():
            raise RuntimeError('private owner revocation detail')
        model._recheck = revoked
        with self.assertRaisesRegex(ModelProviderError, '^PERSONAL_MODEL_REQUEST_FAILED_RUNTIMEERROR$'):
            await model.ainvoke([Message(role='user', content='revoked before request')])
        self.assertEqual(len(self.server.requests), 5)
        model._recheck = lambda: None
        def revoke_after_request(_):
            model._recheck = revoked
            return 200, reply('must not become a successful result')
        self.server.answer = revoke_after_request
        with self.assertRaisesRegex(ModelProviderError, '^PERSONAL_MODEL_REQUEST_FAILED_RUNTIMEERROR$'):
            await model.ainvoke([Message(role='user', content='revoked during request')])
        self.assertEqual(len(self.server.requests), 6)

    async def test_responses_keeps_all_reasoning_items_and_phase(self):
        output = [{'id': 'reason-one', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'cipher-one'},
            {'id': 'reason-two', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'cipher-two'},
            {'id': 'answer', 'type': 'message', 'role': 'assistant', 'phase': 'commentary',
             'content': [{'type': 'output_text', 'text': 'working'}]}]
        self.server.answer = lambda _: (200, {'status': 'completed', 'output': output})
        model = OwnerChatModel({**self.config, 'protocol': 'responses'}, lambda: None)
        result = await model.ainvoke([Message(role='user', content='first')])
        await model.ainvoke([Message(role='user', content='first'),
            Message(role='assistant', content=result.content, provider_data=result.provider_data),
            Message(role='user', content='continue')])
        items = self.server.requests[-1][0]['input']
        self.assertEqual([item['encrypted_content'] for item in items if item.get('type') == 'reasoning'],
            ['cipher-one', 'cipher-two'])
        self.assertEqual(next(item['phase'] for item in items if item.get('type') == 'message'), 'commentary')

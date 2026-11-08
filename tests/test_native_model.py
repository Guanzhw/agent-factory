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
from agno.run.base import RunStatus
from agno.tools.function import Function
from pydantic import BaseModel

from agent_factory.byok_model import OwnerChatModel
from agent_factory.runtime import build_runtime


def chunk(delta, finish=None):
    return {'id': 'local', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fixture',
        'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}


def reply(content):
    return [chunk({'role': 'assistant', 'content': content}), chunk({}, 'stop')]


def responses_reply(content):
    output = [{'id': 'message-one', 'type': 'message', 'role': 'assistant', 'status': 'completed',
        'content': [{'type': 'output_text', 'text': content, 'annotations': []}]}]
    return [{'type': 'response.output_text.delta', 'delta': content},
        {'type': 'response.completed', 'response': {'id': 'response-one', 'status': 'completed', 'output': output}}]


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

    async def test_runtime_dispatch_forwards_native_json_mode_and_media_to_selected_owner(self):
        class Answer(BaseModel):
            count: int
        self.server.answer = lambda _: (200, reply('{"count":42}'))
        bound, selections = {}, []
        plan = {'connectionRefs': {'model': 'configured-owner-model'}, 'normalizedGoal': 'read input'}
        def bind(context):
            bound.update(run_id=context.run_id, plan_id='plan-one')
            return plan
        def select(owner, reference, context, **_):
            selections.append((owner, reference, context.session_id))
            return OwnerChatModel(self.config, lambda: SimpleNamespace(password='owner-one'))
        store = SimpleNamespace(bind_run=bind, resolve_run=lambda _: plan,
            task=lambda *_: bound, task_for_context=lambda _: bound, plan=lambda *_: plan, cancellation_requested=lambda _: False,
            personal_models=SimpleNamespace(model_for=select))
        executor, _ = build_runtime(store, None)
        result = await executor.arun('read input', session_id='task-one', user_id='owner-one',
            output_schema=Answer, images=[Image(url='https://example.invalid/image.png')])
        self.assertEqual(result.content.count, 42)
        request, headers = self.server.requests[-1]
        self.assertEqual(request['response_format'], {'type': 'json_object'})
        self.assertEqual(headers['Authorization'], 'Bearer owner-one')
        self.assertEqual(selections, [('owner-one', 'configured-owner-model', 'task-one')])
        user = next(message for message in request['messages'] if message['role'] == 'user')
        self.assertEqual({part['type'] for part in user['content']}, {'text', 'image_url'})

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
        for protocol in ('chat-completions', 'responses'):
            self.server.requests.clear()
            self.server.started.clear()
            self.server.hold = None
            frames = responses_reply if protocol == 'responses' else reply
            self.server.answer = lambda _: (200, frames('done'))
            lease, checks, events = SimpleNamespace(password='owner-one'), [], []
            async def text(value, _): events.append(value)
            model = OwnerChatModel({**self.config, 'protocol': protocol}, lambda: lease, recheck=lambda: checks.append(True), on_text=text)
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
            self.server.answer = lambda _: (200, frames('partial'))
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
                return 200, frames('must not become a successful result')
            self.server.answer = revoke_after_request
            with self.assertRaisesRegex(ModelProviderError, '^PERSONAL_MODEL_REQUEST_FAILED_RUNTIMEERROR$'):
                await model.ainvoke([Message(role='user', content='revoked during request')])
            self.assertEqual(len(self.server.requests), 6)

    async def test_responses_runtime_keeps_media_nullable_tools_and_exact_continuation(self):
        bound, called = {}, []
        plan = {'connectionRefs': {'model': 'responses-model'}, 'normalizedGoal': 'inspect'}
        def inspect_result(value: str | None = None) -> str:
            """Inspect a nullable value."""
            called.append(value)
            return 'exit 7: continue analysis'
        tool = Function.from_callable(inspect_result)
        tool.parameters['properties']['value'] = {'type': ['string', 'null']}
        tool.skip_entrypoint_processing = True
        output = [{'id': 'reason-one', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'cipher-one'},
            {'id': 'commentary', 'type': 'message', 'role': 'assistant', 'phase': 'commentary',
                'content': [{'type': 'output_text', 'text': 'inspect first'}]},
            {'id': 'reason-two', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'cipher-two'},
            {'id': 'fc_probe', 'type': 'function_call', 'call_id': 'call_probe',
                'name': 'inspect_result', 'arguments': '{"value":null}', 'status': 'completed'}]
        def answer(body):
            if any(item.get('type') == 'function_call_output' for item in body['input']):
                return 200, responses_reply('{"count":42}')
            return 200, [{'type': 'response.output_text.delta', 'delta': 'inspect first'},
                {'type': 'response.completed', 'response': {'status': 'completed', 'output': output}}]
        self.server.answer = answer
        def bind(context):
            bound.update(run_id=context.run_id, plan_id='plan-one')
            return plan
        selected = []
        def select(owner, reference, context, **_):
            selected.append((owner, reference, context.session_id))
            return OwnerChatModel({**self.config, 'protocol': 'responses'},
                lambda: SimpleNamespace(password='responses-owner'))
        store = SimpleNamespace(bind_run=bind, resolve_run=lambda _: plan,
            task=lambda *_: bound, task_for_context=lambda _: bound, plan=lambda *_: plan, cancellation_requested=lambda _: False,
            personal_models=SimpleNamespace(model_for=select), research_tools=SimpleNamespace(functions=lambda _: [tool]))
        executor, _ = build_runtime(store, None)
        class Answer(BaseModel):
            count: int
        result = await executor.arun('inspect', session_id='responses-task', user_id='responses-owner',
            output_schema=Answer, images=[Image(url='https://example.invalid/image.png')],
            files=[File(content=b'42', filename='result.txt', mime_type='text/plain')])
        self.assertEqual(result.content.count, 42)
        self.assertEqual(called, [None])
        self.assertEqual(selected, [('responses-owner', 'responses-model', 'responses-task')])
        first, last = self.server.requests[0][0], self.server.requests[-1][0]
        self.assertEqual(first['text']['format'], {'type': 'json_object'})
        self.assertEqual(first['tools'][0]['parameters']['properties']['value']['type'], ['string', 'null'])
        self.assertEqual(tool.parameters['properties']['value']['type'], ['string', 'null'])
        user = next(item for item in first['input'] if item.get('role') == 'user')
        self.assertEqual({part['type'] for part in user['content']}, {'input_text', 'input_image', 'input_file'})
        replay = [item for item in last['input'] if item.get('type') in {'reasoning', 'message', 'function_call'}]
        self.assertEqual([item['id'] for item in replay], [item['id'] for item in output])
        self.assertEqual(replay[1]['phase'], 'commentary')
        self.assertEqual([item['encrypted_content'] for item in replay if item['type'] == 'reasoning'],
            ['cipher-one', 'cipher-two'])
        result_item = next(item for item in last['input'] if item.get('type') == 'function_call_output')
        self.assertEqual(result_item['call_id'], 'call_probe')
        self.assertIn('exit 7', result_item['output'])
        self.assertFalse(last['store'])
        self.assertNotIn('previous_response_id', last)
        self.assertNotIn('max_output_tokens', last)
        self.server.answer = lambda _: (200, responses_reply('{"count":42}'))
        await select('responses-owner', 'responses-model', SimpleNamespace(session_id='responses-task')).ainvoke(
            [Message(role='user', content='schema')], response_format=Answer)
        self.assertEqual(self.server.requests[-1][0]['text']['format']['type'], 'json_schema')
        called.clear()
        self.server.answer = lambda _: (200, {'status': 'incomplete', 'output': output})
        failed = await executor.arun('incomplete must not run a tool', session_id='responses-task', user_id='responses-owner')
        self.assertEqual(failed.status, RunStatus.error)
        self.assertEqual(called, [])
        self.server.answer = lambda _: (200, responses_reply('partial'))
        self.server.started.clear()
        self.server.hold = Event()
        task = asyncio.create_task(executor.arun('stop', session_id='responses-task', user_id='responses-owner'))
        self.assertTrue(await asyncio.to_thread(self.server.started.wait, 3))
        task.cancel()
        try:
            stopped = await asyncio.wait_for(task, 2)
            self.assertEqual(stopped.status, RunStatus.cancelled)
        except asyncio.CancelledError:
            pass
        self.server.hold.set()
        self.assertEqual(called, [])

    async def test_responses_legacy_calls_and_results_share_ids_across_complete_history(self):
        self.server.answer = lambda _: (200, responses_reply('continued'))
        model = OwnerChatModel({**self.config, 'protocol': 'responses'}, lambda: None, session_id='same-session')
        for origin in ('foreign', 'missing', 'same'):
            messages = []
            for number in range(2):
                identifier = f'call_old_{number}'
                output = [{'type': 'function_call', 'id': f'fc_original_{number}', 'call_id': identifier,
                    'name': 'inspect_result', 'arguments': '{}', 'status': 'completed'}]
                saved = {'scope': model._scope if origin == 'same' else 'old-scope', 'session': 'same-session',
                    'continuation': {'output': output}}
                messages.extend([Message(role='assistant', tool_calls=[{'id': identifier, 'type': 'function',
                    'function': {'name': 'inspect_result', 'arguments': '{}'}}],
                    provider_data=None if origin == 'missing' else {'owner_model_continuation': saved}),
                    Message(role='tool', tool_call_id=identifier, content=f'result-{number}')])
            await model.ainvoke(messages)
            items = self.server.requests[-1][0]['input']
            calls = [item['call_id'] for item in items if item.get('type') == 'function_call']
            results = [item['call_id'] for item in items if item.get('type') == 'function_call_output']
            self.assertEqual(calls, results, origin)
            self.assertEqual(len(set(calls)), 2, origin)
            self.assertEqual([item['output'] for item in items if item.get('type') == 'function_call_output'],
                ['result-0', 'result-1'])
            if origin == 'same':
                self.assertEqual(calls, ['call_old_0', 'call_old_1'])
                self.assertEqual([item['id'] for item in items if item.get('type') == 'function_call'],
                    ['fc_original_0', 'fc_original_1'])
            self.assertEqual(messages[0].tool_calls[0]['id'], 'call_old_0')
            self.assertEqual(messages[1].tool_call_id, 'call_old_0')

    async def test_responses_keeps_all_reasoning_items_and_phase(self):
        output = [{'id': 'reason-one', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'cipher-one'},
            {'id': 'reason-two', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'cipher-two'},
            {'id': 'answer', 'type': 'message', 'role': 'assistant', 'phase': 'commentary',
             'content': [{'type': 'output_text', 'text': 'working'}]}]
        self.server.answer = lambda _: (200, {'status': 'completed', 'output': output})
        model = OwnerChatModel({**self.config, 'protocol': 'responses'}, lambda: None)
        result = await model.ainvoke([Message(role='user', content='first')])
        # Existing saved tasks also carry canonical message fields beside their original output.
        record = result.provider_data['owner_model_continuation']
        record['message'] = {'role': 'assistant', 'content': result.content}
        record['continuation']['message'] = record['message']
        await model.ainvoke([Message(role='user', content='first'),
            Message(role='assistant', content=result.content, provider_data=result.provider_data),
            Message(role='user', content='continue')])
        items = self.server.requests[-1][0]['input']
        self.assertEqual([item['encrypted_content'] for item in items if item.get('type') == 'reasoning'],
            ['cipher-one', 'cipher-two'])
        self.assertEqual(next(item['phase'] for item in items if item.get('type') == 'message'), 'commentary')
        another = OwnerChatModel({**self.config, 'protocol': 'responses'}, lambda: None)
        await another.ainvoke([Message(role='assistant', content=result.content, provider_data=result.provider_data),
            Message(role='user', content='continue in another session')])
        self.assertNotIn('cipher-', json.dumps(self.server.requests[-1][0]['input']))

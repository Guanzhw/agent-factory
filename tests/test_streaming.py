"""Ordered provider segments and durable aggregation, using synthetic responses."""
import asyncio
from contextvars import ContextVar
import json
import os
import threading
import unittest
from uuid import uuid4

import httpx
from openai import AsyncOpenAI
from agno.models.message import Message
from sqlalchemy import create_engine, make_url, text
from unittest.mock import patch

from agent_factory.byok_model import OwnerChatModel
from agent_factory.model_stream import read_model_stream
from agent_factory.store import Store


class Frames(httpx.AsyncByteStream):
    def __init__(self, values, gate=None):
        self.values, self.gate = values, gate

    async def __aiter__(self):
        for index, value in enumerate(self.values):
            yield ('data: ' + json.dumps(value) + '\n\n').encode()
            if index == 0 and self.gate is not None:
                await self.gate.wait()
        yield b'data: [DONE]\n\n'


def chat_chunk(delta, finish=None):
    return {'id': 'synthetic', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fixture',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}


class ProviderStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_persistence_does_not_flush_same_segment_twice(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        written = []
        def write(value):
            written.append(value)
            if len(written) == 1:
                started.set()
                release.wait(5)
                finished.set()
        async def reasoning(value):
            await asyncio.to_thread(write, value)
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'},
            stream=Frames([chat_chunk({'role': 'assistant', 'reasoning_content': 'one'})], asyncio.Event()))
        task = asyncio.create_task(read_model_stream(response, 'chat-completions', on_reasoning=reasoning))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        self.assertTrue(await asyncio.to_thread(finished.wait, 2))
        self.assertEqual(written, ['one'])

    async def test_chat_segments_flush_during_provider_wait_and_preserve_native_reasoning(self):
        gate = asyncio.Event()
        values = [chat_chunk({'role': 'assistant', 'reasoning_content': '思考一'}),
            chat_chunk({'role': None, 'content': '正文一'}),
            chat_chunk({'role': 'assistant', 'reasoning_content': '思考二'}),
            chat_chunk({'content': '正文二'}), chat_chunk({}, 'stop')]
        events = []
        async def content(value):
            events.append(('content', value))
        async def reasoning(value):
            events.append(('reasoning', value))
            gate.set()
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Frames(values, gate))
        raw = await asyncio.wait_for(read_model_stream(response, 'chat-completions', content, reasoning), 2)
        self.assertEqual(raw['choices'][0]['message']['role'], 'assistant')
        self.assertEqual(events, [('reasoning', '思考一'), ('content', '正文一'),
                                  ('reasoning', '思考二'), ('content', '正文二')])
        model = OwnerChatModel({'provider': 'openai', 'baseURL': 'https://api.openai.com/v1',
                                'model': 'fixture'}, lambda: None)
        parsed = model._parse_provider_response(raw)
        self.assertEqual(parsed.content, '正文一正文二')
        self.assertEqual(parsed.reasoning_content, '思考一思考二')

    async def test_stream_rejects_an_explicit_non_assistant_role(self):
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'},
            stream=Frames([chat_chunk({'role': 'user', 'content': 'invalid'})]))
        with self.assertRaisesRegex(ValueError, 'PERSONAL_MODEL_STREAM_ROLE'):
            await read_model_stream(response, 'chat-completions')

    async def test_responses_segments_and_plain_content_have_no_invented_reasoning(self):
        output = [{'id': 'reason-1', 'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': '考虑'}]},
            {'id': 'message-1', 'type': 'message', 'role': 'assistant',
             'content': [{'type': 'output_text', 'text': '答案'}]}]
        values = [{'type': 'response.reasoning_summary_text.delta', 'delta': '考虑'},
                  {'type': 'response.output_text.delta', 'delta': '答案'},
                  {'type': 'response.completed', 'response': {'status': 'completed', 'output': output}}]
        events = []
        async def content(value): events.append(('content', value))
        async def reasoning(value): events.append(('reasoning', value))
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Frames(values))
        raw = await read_model_stream(response, 'responses', content, reasoning)
        self.assertEqual(events, [('reasoning', '考虑'), ('content', '答案')])
        model = OwnerChatModel({'provider': 'openai', 'baseURL': 'https://api.openai.com/v1',
            'model': 'fixture', 'protocol': 'responses'}, lambda: None)
        replay = model._parse_provider_response(raw).provider_data['owner_model_continuation']['continuation']['output']
        self.assertEqual(replay[0], output[0])
        events.clear()
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'},
            stream=Frames([chat_chunk({'role': 'assistant', 'content': 'x'}) for _ in range(1001)]
                          + [chat_chunk({}, 'stop')]))
        await read_model_stream(response, 'chat-completions', content, reasoning)
        self.assertEqual(''.join(value for kind, value in events), 'x' * 1001)
        self.assertTrue(all(kind == 'content' for kind, _ in events))
        self.assertLess(len(events), 1001)

    async def test_native_stream_does_not_duplicate_completed_content_or_reasoning(self):
        model = OwnerChatModel({'provider': 'openai', 'baseURL': 'https://api.openai.com/v1',
                                'model': 'fixture'}, lambda: None)
        final = model._parse_provider_response({'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': '答案', 'reasoning_content': '考虑'}}]})
        async def request(messages, *, on_text, on_reasoning, **kwargs):
            await on_reasoning('考虑')
            await on_text('答案')
            return final
        with patch.object(model, '_request', request):
            chunks = [value async for value in model.ainvoke_stream([Message(role='user', content='你好')])]
        self.assertEqual(''.join(value.content or '' for value in chunks), '答案')
        self.assertEqual(''.join(value.reasoning_content or '' for value in chunks), '考虑')
        self.assertIsNotNone(chunks[-1].provider_data)

    async def test_json_provider_exposes_only_returned_segments_in_output_order(self):
        client = httpx.AsyncClient
        response = {'status': 'completed', 'output': [
            {'id': 'r1', 'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': '考虑一'}]},
            {'id': 'm1', 'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '答一'}]},
            {'id': 'r2', 'type': 'reasoning', 'summary': [], 'content': [{'type': 'reasoning_text', 'text': '考虑二'}]},
            {'id': 'm2', 'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '答二'}]}]}
        events = []
        async def content(value, response_id): events.append(('content', value, response_id))
        async def reasoning(value, response_id): events.append(('reasoning', value, response_id))
        model = OwnerChatModel({'provider': 'openai', 'baseURL': 'https://api.openai.com/v1',
            'model': 'fixture', 'protocol': 'responses'}, lambda: None, on_text=content, on_reasoning=reasoning)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
        with patch('agent_factory.byok_model.AsyncOpenAI',
                lambda **kwargs: AsyncOpenAI(http_client=client(transport=transport), **kwargs)):
            result = await model.ainvoke([Message(role='user', content='你好')])
        self.assertEqual([(kind, value) for kind, value, _ in events], [('reasoning', '考虑一'),
            ('content', '答一'), ('reasoning', '考虑二'), ('content', '答二')])
        self.assertEqual(len({response_id for _, _, response_id in events}), 1)
        self.assertEqual((result.content, result.reasoning_content), ('答一答二', '考虑一考虑二'))

    async def test_incomplete_stream_keeps_real_partial_segments(self):
        events = []
        async def reasoning(value): events.append(value)
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'},
            stream=Frames([chat_chunk({'role': 'assistant', 'reasoning_content': '未完成的思考'})]))
        with self.assertRaisesRegex(ValueError, 'PERSONAL_MODEL_STREAM_INCOMPLETE'):
            await read_model_stream(response, 'chat-completions', on_reasoning=reasoning)
        self.assertEqual(events, ['未完成的思考'])


class StoredStreaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ['FACTORY_TEST_DATABASE_URL'])
        cls.admin = create_engine(url, isolation_level='AUTOCOMMIT')
        cls.database = 'factory_regression_' + uuid4().hex
        with cls.admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE {cls.database}'))
        def cleanup():
            with cls.admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE {cls.database} WITH (FORCE)'))
            cls.admin.dispose()
        cls.addClassCleanup(cleanup)
        cls.store = object.__new__(Store)
        cls.store.engine = create_engine(url.set(database=cls.database))
        cls.addClassCleanup(cls.store.engine.dispose)
        cls.store._connection = ContextVar('stream_test_connection', default=None)
        cls.store.task = lambda identifier: {'id': identifier}
        cls.store.sql('CREATE TABLE af_events (id BIGSERIAL PRIMARY KEY, task_id TEXT NOT NULL, '
                      'type TEXT NOT NULL, message TEXT NOT NULL, data JSONB NOT NULL, created_at TEXT NOT NULL)')

    def test_adjacent_segments_merge_but_tools_and_responses_preserve_order_and_unknown(self):
        store, task = self.store, uuid4().hex
        store.model_delta(task, 'model_reasoning_delta', '思', 'response-1')
        first = store.events(task)[0]
        store.model_delta(task, 'model_reasoning_delta', '考', 'response-1')
        merged = store.events(task)[0]
        self.assertEqual((merged['id'], merged['createdAt']), (first['id'], first['createdAt']))
        self.assertGreaterEqual(merged['data']['updatedAt'], first['data']['updatedAt'])
        self.assertEqual(merged['data']['text'], '思考')
        store.model_delta(task, 'model_content_delta', '先查工具', 'response-1')
        store.event(task, 'tool_started', '调用工具', {'callId': 'call-1'})
        store.event(task, 'tool_finished', '结果未知', {'callId': 'call-1', 'outcome': 'unknown'})
        store.model_delta(task, 'model_reasoning_delta', '继续考虑', 'response-2')
        store.model_delta(task, 'model_content_delta', '最终', 'response-2')
        store.model_delta(task, 'model_content_delta', '回答', 'response-2')
        events = store.events(task)
        self.assertEqual([event['type'] for event in events], ['model_reasoning_delta', 'model_content_delta',
            'tool_started', 'tool_finished', 'model_reasoning_delta', 'model_content_delta'])
        self.assertEqual(events[-1]['data']['responseId'], 'response-2')
        self.assertEqual(events[-1]['data']['text'], '最终回答')
        self.assertEqual(events[3]['data']['outcome'], 'unknown')
        store.event(task, 'model_content_delta', '旧历史', {'responseId': 'legacy', 'text': '旧正文'})
        self.assertEqual(store.events(task)[-1]['data']['text'], '旧正文')

"""Actual chunked SSE through the owner adapter and native Agno tool loop."""
import asyncio
import json
import unittest

import httpx
from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.message import Message

from agent_factory.byok_model import OwnerChatModel
from agent_factory.personal_remote_provider import SecretLease


def chunk(delta, reason=None):
    return {'id': 'fixture-response', 'object': 'chat.completion.chunk', 'created': 1,
        'model': 'fixture-model', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': reason}]}


class Chunks(httpx.AsyncByteStream):
    def __init__(self, values):
        self.values = values

    async def __aiter__(self):
        for value in self.values:
            yield ('data: ' + (value if isinstance(value, str) else json.dumps(value)) + '\n\n').encode()
            await asyncio.sleep(0)


class OwnerModelStreamTests(unittest.IsolatedAsyncioTestCase):
    def model(self, wire, on_text=None):
        return OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://fixture.invalid/v1'}, lambda: None,
            transport_factory=lambda: httpx.MockTransport(wire), on_text=on_text)

    async def test_native_parallel_calls_and_progress_before_completion(self):
        requests, progress, executed = [], [], []
        both_started = asyncio.Event()

        async def observe(text, response_id):
            progress.append(text)

        def wire(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertTrue(body['stream'])
            self.assertNotIn('max_tokens', body)
            self.assertNotIn('parallel_tool_calls', body)
            if len(requests) == 1:
                values = [chunk({'role': 'assistant', 'content': 'Checking ', 'tool_calls': [
                    {'index': i, 'id': 'call-' + str(i), 'type': 'function',
                     'function': {'name': 'inspect_fixture', 'arguments': '{"value":'}} for i in range(2)]}),
                    chunk({'tool_calls': [{'index': i, 'function': {'arguments': str(i) + '}'}} for i in range(2)]}, 'tool_calls'), '[DONE]']
            else:
                self.assertEqual(len([m for m in body['messages'] if m['role'] == 'tool']), 2)
                values = [chunk({'role': 'assistant', 'content': 'Both '}), chunk({'role': 'assistant', 'content': 'done'}, 'stop'), '[DONE]']
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks(values))

        async def inspect_fixture(value: int):
            executed.append(value)
            if len(executed) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 2)
            return str(value)

        result = await Agent(model=self.model(wire, observe), tools=[inspect_fixture]).arun('Inspect both')
        self.assertIn('Both done', result.content)
        self.assertEqual(sorted(executed), [0, 1])
        self.assertEqual(progress, ['Checking ', 'Both ', 'done'])

    async def test_partial_stream_is_not_success_and_is_not_replayed(self):
        requests = []
        def wire(request):
            requests.append(request)
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                stream=Chunks([chunk({'role': 'assistant', 'content': 'unfinished'})]))
        with self.assertRaises(ModelProviderError):
            await self.model(wire).ainvoke([Message(role='user', content='test')])
        self.assertEqual(len(requests), 1)

    async def test_native_async_stream_yields_before_provider_finishes_and_close_cancels(self):
        closed = []
        class Waiting(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield ('data: ' + json.dumps(chunk({'role': 'assistant', 'content': 'first'})) + '\n\n').encode()
                await asyncio.Event().wait()
            async def aclose(self):
                closed.append(True)
        model = self.model(lambda request: httpx.Response(200,
            headers={'content-type': 'text/event-stream'}, stream=Waiting()))
        stream = model.ainvoke_stream([Message(role='user', content='test')])
        first = await asyncio.wait_for(anext(stream), 2)
        self.assertEqual(first.content, 'first')
        await stream.aclose()
        self.assertEqual(closed, [True])

    async def test_responses_stream_preserves_complete_reasoning_continuation(self):
        from test_model_protocol_execution import response_output
        final = response_output()
        seen = []
        async def observe(text, response_id):
            seen.append(text)
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://fixture.invalid/v1', 'protocol': 'responses'}, lambda: None,
            transport_factory=lambda: httpx.MockTransport(lambda request: httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, stream=Chunks([
                    {'type': 'response.output_text.delta', 'delta': 'synthetic completion'},
                    {'type': 'response.completed', 'response': final}]))), on_text=observe)
        result = await model.ainvoke([Message(role='user', content='test')])
        self.assertEqual(result.content, 'synthetic completion')
        self.assertEqual(seen, ['synthetic completion'])
        self.assertEqual(result.provider_data['owner_model_continuation']['continuation']['output'], final['output'])

    async def test_credentials_split_across_chunks_are_never_published(self):
        seen = []
        async def observe(text, response_id):
            seen.append(text)
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://fixture.invalid/v1'}, lambda: SecretLease('api-key', 'synthetic-private-key'),
            transport_factory=lambda: httpx.MockTransport(lambda request: httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, stream=Chunks([
                    chunk({'role': 'assistant', 'content': 'prefix synthetic-'}),
                    chunk({'content': 'private-key'}, 'stop'), '[DONE]']))), on_text=observe)
        with self.assertRaisesRegex(ModelProviderError, 'REMOTE_CREDENTIAL_ECHO_REJECTED'):
            await model.ainvoke([Message(role='user', content='test')])
        self.assertEqual(''.join(seen), 'prefix ')

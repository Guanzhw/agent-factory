"""Per-request tool authority using actual Agno and synthetic HTTP."""
import asyncio
import json
import unittest

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.message import Message
import httpx

from agent_factory.byok_model import OwnerChatModel
from agent_factory.personal_remote_provider import SecretLease


def reply(protocol, name=None):
    if protocol == 'chat-completions':
        message = {'role': 'assistant', 'content': 'safe text'}
        if name:
            message = {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'call-1', 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}]}
        return {'choices': [{'finish_reason': 'tool_calls' if name else 'stop', 'message': message}]}
    output = [{'type': 'function_call', 'id': 'fc_1', 'call_id': 'call-1', 'name': name,
        'arguments': '{}', 'status': 'completed'}] if name else [{'type': 'message', 'id': 'msg_1',
        'role': 'assistant', 'status': 'completed', 'content': [
            {'type': 'output_text', 'text': 'safe text', 'annotations': []}]}]
    return {'status': 'completed', 'output': output}


def declared(name):
    return [{'type': 'function', 'function': {'name': name, 'parameters': {'type': 'object', 'properties': {}}}}]


def model(protocol, wire):
    return OwnerChatModel({'provider': 'openai-compatible', 'model': 'selected-fixture',
        'baseURL': 'https://fixture.invalid/v1', 'protocol': protocol},
        lambda: SecretLease('api-key', 'synthetic-only'), transport_factory=lambda: httpx.MockTransport(wire))


class ByokToolAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_free_actual_agent_rejects_train_in_one_request_and_accepts_text(self):
        for protocol in ('chat-completions', 'responses'):
            for tool_name in ('train', None):
                with self.subTest(protocol=protocol, tool_name=tool_name):
                    requests = []
                    def wire(request):
                        requests.append(json.loads(request.content))
                        if len(requests) > 1:
                            raise RuntimeError('bounded fixture prevents an unknown-tool loop')
                        return httpx.Response(200, json=reply(protocol, tool_name))
                    agent = Agent(model=model(protocol, wire), tools=[], telemetry=False)
                    result = await agent.arun('Read evidence only')
                    self.assertEqual(len(requests), 1)
                    self.assertFalse(requests[0].get('tools'))
                    self.assertFalse(result.tools)
                    if tool_name:
                        self.assertEqual(result.status.value, 'ERROR')
                        self.assertEqual(result.content, 'PERSONAL_MODEL_TOOL_NOT_DECLARED')
                    else:
                        self.assertEqual(result.content, 'safe text')

    async def test_existing_safe_response_errors_are_not_changed_to_transport_failure(self):
        cases = [
            ('chat-completions', {'choices': [{'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': None, 'refusal': 'private refusal'}}]}, 'REFUSAL'),
            ('responses', {'status': 'completed', 'output': [{'type': 'refusal'}]}, 'REFUSAL'),
            ('responses', {'status': 'completed', 'output': []}, 'EMPTY_OUTPUT'),
        ]
        for protocol, response, code in cases:
            with self.subTest(protocol=protocol, code=code):
                selected = model(protocol, lambda request: httpx.Response(200, json=response))
                with self.assertRaisesRegex(ModelProviderError, '^PERSONAL_MODEL_' + code + '$'):
                    await selected.ainvoke([Message(role='user', content='fixture')])

    async def test_concurrent_same_model_requests_use_only_their_own_declarations(self):
        for protocol in ('chat-completions', 'responses'):
            with self.subTest(protocol=protocol):
                first_arrived = asyncio.Event()
                both_arrived = asyncio.Event()
                async def wire(request):
                    body = json.loads(request.content)
                    name = body['tools'][0]['function']['name'] if protocol == 'chat-completions' else body['tools'][0]['name']
                    if name == 'inspect':
                        first_arrived.set()
                        await both_arrived.wait()
                    else:
                        await first_arrived.wait()
                        both_arrived.set()
                    return httpx.Response(200, json=reply(protocol, 'inspect'))
                selected = model(protocol, wire)
                message = [Message(role='user', content='fixture')]
                good, bad = await asyncio.gather(selected.ainvoke(message, tools=declared('inspect')),
                    selected.ainvoke(message, tools=declared('train')), return_exceptions=True)
                self.assertEqual(good.tool_calls[0]['function']['name'], 'inspect')
                self.assertIsInstance(bad, ModelProviderError)
                self.assertEqual(str(bad), 'PERSONAL_MODEL_TOOL_NOT_DECLARED')

    async def test_async_stream_delegation_rejects_undeclared_and_preserves_declared(self):
        for protocol in ('chat-completions', 'responses'):
            selected = model(protocol, lambda request: httpx.Response(200, json=reply(protocol, 'inspect')))
            with self.assertRaisesRegex(ModelProviderError, 'PERSONAL_MODEL_TOOL_NOT_DECLARED'):
                async for _ in selected.ainvoke_stream([Message(role='user', content='fixture')]):
                    self.fail('Undeclared tool response must not be yielded')
            values = [value async for value in selected.ainvoke_stream(
                [Message(role='user', content='fixture')], tools=declared('inspect'))]
            self.assertEqual(len(values), 1)
            self.assertEqual(values[0].tool_calls[0]['function']['name'], 'inspect')

    def test_sync_invoke_and_stream_share_the_same_boundary(self):
        for protocol in ('chat-completions', 'responses'):
            selected = model(protocol, lambda request: httpx.Response(200, json=reply(protocol, 'inspect')))
            for invoke in (selected.invoke, lambda messages, **kwargs: list(selected.invoke_stream(messages, **kwargs))[0]):
                with self.assertRaisesRegex(ModelProviderError, 'PERSONAL_MODEL_TOOL_NOT_DECLARED'):
                    invoke([Message(role='user', content='fixture')])
                self.assertEqual(invoke([Message(role='user', content='fixture')], tools=declared('inspect'))
                    .tool_calls[0]['function']['name'], 'inspect')

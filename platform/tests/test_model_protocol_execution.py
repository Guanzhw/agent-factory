"""Offline owner model protocol execution; synthetic responses and credentials only."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.message import Message
import httpx

from agent_factory.byok_model import OwnerChatModel, PinnedChatTransport
from agent_factory.owner_runtime_broker import OwnerModelCallError, OwnerRuntimeBroker
from agent_factory.personal_remote_provider import SecretLease


def response_output(*, tool=False):
    output = [{'type': 'reasoning', 'id': 'rs_synthetic', 'summary': [],
        'encrypted_content': 'synthetic-encrypted-reasoning'}]
    if tool:
        output.append({'type': 'function_call', 'id': 'fc_synthetic', 'call_id': 'call_synthetic',
            'name': 'checksum_fixture', 'arguments': '{}', 'status': 'completed'})
    else:
        output.append({'type': 'message', 'id': 'msg_synthetic_output', 'role': 'assistant',
            'status': 'completed', 'content': [{'type': 'output_text', 'text': 'synthetic completion', 'annotations': []}]})
    return {'id': 'resp_synthetic', 'object': 'response', 'status': 'completed', 'output': output}


class OwnerProtocolExecutionTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.calls = []
        self.config = {'ownerId': 'synthetic-owner', 'reference': 'synthetic-model-ref', 'revision': 'model-r1',
            'credentialRef': 'synthetic-credential-ref', 'credentialRevision': 'credential-r1',
            'provider': 'openai-compatible', 'model': 'gpt-6-luna', 'protocol': 'responses',
            'baseURL': 'https://opencode.ai/inference/go/v1'}
        self.revoked = False
        self.answer = response_output()

    def wire(self, request):
        self.calls.append(request)
        return httpx.Response(200, json=self.answer)

    def check(self):
        if self.revoked: raise ValueError('SYNTHETIC_REVOKED')

    def model(self):
        return OwnerChatModel(self.config, lambda: SecretLease('api-key', 'synthetic-private-key'),
            transport_factory=lambda: httpx.MockTransport(self.wire), recheck=self.check,
            session_id='af-plan-syntheticprotocol')

    def broker(self, **kwargs):
        handle = SimpleNamespace(owner='synthetic-owner', body=dict(self.config), check=self.check,
            credential=lambda: SecretLease('api-key', 'synthetic-private-key'),
            service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(self.wire)))
        return OwnerRuntimeBroker(Path(self.folder.name) / 'model.sock', handle, **kwargs)

    def test_agno_responses_runs_native_function_loop_with_reasoning_and_optional_usage(self):
        self.answer = response_output(tool=True)
        original = self.wire
        def wire(request):
            result = original(request)
            self.answer = response_output()
            return result
        self.wire = wire
        def checksum_fixture(): return 'synthetic-checksum'
        result = asyncio.run(Agent(model=self.model(), tools=[checksum_fixture], markdown=False).arun('synthetic task'))
        self.assertEqual(result.content, 'synthetic completion')
        self.assertEqual(len(self.calls), 2)
        first, second = [json.loads(request.content) for request in self.calls]
        self.assertEqual(str(self.calls[0].url), 'https://opencode.ai/inference/go/v1/responses')
        self.assertEqual(first['model'], 'gpt-6-luna')
        self.assertFalse(first['store']); self.assertFalse(first['stream'])
        self.assertEqual(first['max_output_tokens'], 4096)
        self.assertIn('reasoning.encrypted_content', first['include'])
        self.assertEqual(first['tools'][0]['type'], 'function')
        self.assertEqual(first['tools'][0]['name'], 'checksum_fixture')
        types = [item.get('type') for item in second['input']]
        self.assertLess(types.index('reasoning'), types.index('function_call'))
        self.assertLess(types.index('function_call'), types.index('function_call_output'))
        self.assertEqual(next(item for item in second['input'] if item.get('type') == 'reasoning')['encrypted_content'],
            'synthetic-encrypted-reasoning')
        self.assertEqual(next(item for item in second['input'] if item.get('type') == 'function_call_output')['output'],
            'synthetic-checksum')
        self.assertEqual(self.calls[0].headers['x-opencode-session'], self.calls[1].headers['x-opencode-session'])

    def test_broker_responses_returns_cc_and_replays_only_same_session_tool_continuation(self):
        broker = self.broker(); self.answer = response_output(tool=True)
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}],
            'tools': [{'type': 'function', 'function': {'name': 'checksum_fixture', 'parameters': {'type': 'object'}}}],
            'tool_choice': {'type': 'function', 'function': {'name': 'checksum_fixture'}}}
        first = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
        self.assertEqual(first['choices'][0]['finish_reason'], 'tool_calls')
        self.assertNotIn('synthetic-encrypted-reasoning', json.dumps(first))
        outgoing = json.loads(self.calls[0].content)
        self.assertEqual(outgoing['tool_choice'], {'type': 'function', 'name': 'checksum_fixture'})
        next_body = {**body, 'messages': [*body['messages'], first['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call_synthetic', 'content': 'synthetic-checksum'}]}
        self.answer = response_output()
        answer = broker.native_completion(next_body, 'ses_synthetic0001', 'msg_synthetic0001')
        self.assertEqual(answer['choices'][0]['message']['content'], 'synthetic completion')
        self.assertIn('reasoning', [item.get('type') for item in json.loads(self.calls[1].content)['input']])
        self.assertEqual(broker.native_completion(next_body, 'ses_synthetic0001', 'msg_synthetic0001'), answer)
        with self.assertRaises(OwnerModelCallError) as caught:
            broker.native_completion(next_body, 'ses_synthetic0002', 'msg_synthetic0001')
        self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        self.assertEqual(len(self.calls), 2)

    def test_agno_continuation_survives_reconstruction_but_not_credential_revision_change(self):
        self.answer = response_output(tool=True)
        first = asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic task')]))
        assistant = Message(role='assistant', content=first.content, tool_calls=first.tool_calls,
            provider_data=first.provider_data)
        messages = [Message(role='user', content='synthetic task'), assistant,
            Message(role='tool', tool_call_id='call_synthetic', content='synthetic-checksum')]
        self.answer = response_output()
        self.assertEqual(asyncio.run(self.model().ainvoke(messages)).content, 'synthetic completion')
        self.config['credentialRevision'] = 'credential-r2'
        with self.assertRaises(ModelProviderError): asyncio.run(self.model().ainvoke(messages))
        self.assertEqual(len(self.calls), 2)

    def test_broker_responses_unknown_is_not_redispatched(self):
        def wire(request):
            self.calls.append(request)
            raise httpx.ReadTimeout('synthetic timeout')
        self.wire = wire
        broker = self.broker()
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
        diagnostics = []
        for _ in range(2):
            with self.assertRaises(OwnerModelCallError) as caught:
                broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
            self.assertEqual(caught.exception.code, 'OWNER_MODEL_CALL_UNCONFIRMED')
            diagnostics.append(caught.exception.diagnostic_id)
        self.assertEqual(diagnostics[0], diagnostics[1]); self.assertEqual(len(self.calls), 1)

    def test_two_function_rounds_work_in_both_protocols_and_execution_paths(self):
        for protocol in ('chat-completions', 'responses'):
            for execution in ('agno', 'broker'):
                with self.subTest(protocol=protocol, execution=execution):
                    self.calls = []
                    self.config.update(protocol=protocol,
                        model='gpt-6-luna' if protocol == 'responses' else 'deepseek-flash')
                    def wire(request):
                        self.calls.append(request)
                        turn = len(self.calls)
                        if protocol == 'responses':
                            payload = response_output(tool=turn < 3)
                            if turn < 3:
                                payload['output'][0]['id'] = f'rs_synthetic{turn}'
                                payload['output'][1].update(id=f'fc_synthetic{turn}', call_id=f'call_synthetic{turn}')
                        else:
                            message = {'role': 'assistant', 'content': 'synthetic completion'}
                            if turn < 3:
                                message.update(content=None, tool_calls=[{'type': 'function', 'id': f'call_synthetic{turn}',
                                    'function': {'name': 'checksum_fixture', 'arguments': '{}'}}])
                            payload = {'choices': [{'message': message, 'finish_reason': 'tool_calls' if turn < 3 else 'stop'}]}
                        return httpx.Response(200, json=payload)
                    self.wire = wire
                    if execution == 'agno':
                        def checksum_fixture(): return 'synthetic-checksum'
                        answer = asyncio.run(Agent(model=self.model(), tools=[checksum_fixture], markdown=False).arun('synthetic task'))
                        self.assertEqual(answer.content, 'synthetic completion')
                    else:
                        broker = self.broker()
                        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}],
                            'tools': [{'type': 'function', 'function': {'name': 'checksum_fixture', 'parameters': {'type': 'object'}}}]}
                        for turn in range(1, 4):
                            answer = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
                            if turn < 3:
                                body['messages'].extend([answer['choices'][0]['message'],
                                    {'role': 'tool', 'tool_call_id': f'call_synthetic{turn}', 'content': 'synthetic-checksum'}])
                        self.assertEqual(answer['choices'][0]['message']['content'], 'synthetic completion')
                    self.assertEqual(len(self.calls), 3)
                    self.assertTrue(all(json.loads(request.content)['parallel_tool_calls'] is False for request in self.calls))
                    if protocol == 'responses':
                        final_input = json.loads(self.calls[2].content)['input']
                        self.assertEqual([item['id'] for item in final_input if item.get('type') == 'reasoning'],
                            ['rs_synthetic1', 'rs_synthetic2'])

    def test_broker_continuation_cannot_cross_credential_revision_or_owner(self):
        broker = self.broker(); self.answer = response_output(tool=True)
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
        answer = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
        body['messages'].extend([answer['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call_synthetic', 'content': 'synthetic-checksum'}])
        broker.handle.body['credentialRevision'] = 'credential-r2'
        with self.assertRaises(OwnerModelCallError) as caught:
            broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0002')
        self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        broker.handle.body['credentialRevision'] = 'credential-r1'
        broker.handle.owner = 'another-synthetic-owner'
        with self.assertRaises(OwnerModelCallError) as caught:
            broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0003')
        self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        self.assertEqual(len(self.calls), 1)

    def test_both_paths_reject_secret_echo_in_encrypted_reasoning(self):
        self.answer = response_output(tool=True)
        self.answer['output'][0]['encrypted_content'] = 'synthetic-private-key'
        with self.assertRaises(ModelProviderError):
            asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic task')]))
        broker = self.broker()
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
        for _ in range(2):
            with self.assertRaises(OwnerModelCallError) as caught:
                broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
            self.assertEqual(caught.exception.code, 'OWNER_MODEL_CALL_UNCONFIRMED')
        self.assertEqual(broker.continuations, {})
        self.assertEqual(len(self.calls), 2)

    def test_both_paths_preserve_chat_completions_tool_choice_for_current_go(self):
        self.config.update(model='deepseek-flash', protocol='chat-completions')
        self.answer = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'synthetic'}}]}
        tools = [{'type': 'function', 'function': {'name': 'checksum_fixture', 'parameters': {'type': 'object'}}}]
        choice = {'type': 'function', 'function': {'name': 'checksum_fixture'}}
        asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic')], tools=tools, tool_choice=choice))
        asyncio.run(self.broker().completion({'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic'}],
            'tools': tools, 'tool_choice': choice}, 'ses_synthetic0001'))
        for request in self.calls:
            self.assertEqual(str(request.url), 'https://opencode.ai/inference/go/v1/chat/completions')
            self.assertEqual(json.loads(request.content)['tool_choice'], choice)
            self.assertEqual(json.loads(request.content)['model'], 'deepseek-flash')
            self.assertIn('x-opencode-session', request.headers)

    def test_responses_pin_target_hostname_and_reject_wrong_protocol_route(self):
        calls = []
        async def run():
            transport = PinnedChatTransport('https://opencode.ai', base_path='/inference/go/v1', protocol='responses')
            await transport.transport.aclose()
            transport.transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json={}))
            transport.probe.addresses = lambda destination: ['93.184.216.34']
            async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                await client.post('https://opencode.ai/inference/go/v1/responses', json={})
                with self.assertRaises(ValueError):
                    await client.post('https://opencode.ai/inference/go/v1/chat/completions', json={})
        asyncio.run(run())
        self.assertEqual(str(calls[0].url), 'https://93.184.216.34/inference/go/v1/responses')
        self.assertEqual(calls[0].headers['host'], 'opencode.ai')
        self.assertEqual(calls[0].extensions['sni_hostname'], 'opencode.ai')


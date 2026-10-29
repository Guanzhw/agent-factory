"""Controlled provider wire contract; no credentials or external network."""
import asyncio
import json
import unittest
from unittest.mock import patch

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.run import RunStatus
import httpx

from agent_factory.byok_model import OwnerChatModel, PinnedChatTransport, base_url
from agent_factory.personal_remote_provider import SecretLease


class ByokModelTests(unittest.TestCase):
    def test_owner_output_limit_reaches_both_protocols_without_per_call_override(self):
        for protocol, field in (('chat-completions', 'max_tokens'), ('responses', 'max_output_tokens')):
            for options, expected in (({}, 4096), ({'maxOutputTokens': 16384}, 16384)):
                with self.subTest(protocol=protocol, options=options):
                    requests = []
                    def wire(request):
                        requests.append(json.loads(request.content))
                        answer = ({'status': 'completed', 'output': [{'type': 'message', 'id': 'msg_fixture',
                            'role': 'assistant', 'status': 'completed', 'content': [
                                {'type': 'output_text', 'text': 'Synthetic final', 'annotations': []}]}]}
                            if protocol == 'responses' else {'choices': [{'finish_reason': 'stop',
                                'message': {'role': 'assistant', 'content': 'Synthetic final'}}]})
                        return httpx.Response(200, json=answer)
                    configuration = {'provider': 'openai-compatible', 'model': 'fixture-model',
                        'baseURL': 'https://models.example.com/v1', 'protocol': protocol, **options}
                    model = OwnerChatModel(configuration, lambda: None,
                        transport_factory=lambda: httpx.MockTransport(wire))
                    asyncio.run(model.ainvoke([Message(role='user', content='Synthetic goal')], max_tokens=1))
                    self.assertEqual(requests[0][field], expected)
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(configuration.get('maxOutputTokens'), options.get('maxOutputTokens'))

    def test_output_configuration_rejects_non_positive_integers_before_dispatch(self):
        from agent_factory.personal_models import ConfigureModel
        configuration = {'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://models.example.com/v1'}
        for value in (None, True, False, 0, -1, 1.5, '16384'):
            with self.subTest(value=value):
                values = {**configuration, 'maxOutputTokens': value}
                with self.assertRaises(ValueError):
                    ConfigureModel(**values, requestId='synthetic-output-config')
                with self.assertRaises(ValueError):
                    OwnerChatModel(values, lambda: self.fail('Invalid config must not resolve credentials'))

    def test_truncated_tool_response_is_not_executed_or_retried_with_larger_output_limit(self):
        requests, effects = [], []
        def edit_fixture():
            effects.append('edited')
            return 'edited'
        def wire(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'fixture-cutoff', 'type': 'function',
                    'function': {'name': 'edit_fixture', 'arguments': '{}'}}]}}]})
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://models.example.com/v1', 'maxOutputTokens': 16384}, lambda: None,
            transport_factory=lambda: httpx.MockTransport(wire))
        result = asyncio.run(Agent(model=model, tools=[edit_fixture]).arun('Synthetic edit'))
        self.assertEqual(result.status, RunStatus.error)
        self.assertIn('PERSONAL_MODEL_RESPONSE_REJECTED', str(result.content))
        self.assertEqual(effects, [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['max_tokens'], 16384)

    def test_explicit_original_go_thinking_option_is_scoped_and_keeps_output_bound(self):
        requests = []
        def wire(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'model':'longcat-2.5-preview-free', 'choices': [{'finish_reason':'stop','message':
                {'role':'assistant', 'content':'synthetic final'}}]})
        config = {'provider':'openai-compatible', 'model':'longcat-2.5-preview-free',
            'baseURL':'https://opencode.ai/zen/go/v1'}
        for mode in (None, 'disabled'):
            values = config if mode is None else {**config, 'thinkingMode':mode}
            model = OwnerChatModel(values, lambda: SecretLease('api-key','synthetic-key'),
                transport_factory=lambda:httpx.MockTransport(wire))
            asyncio.run(model.ainvoke([Message(role='user', content='synthetic')]))
        self.assertNotIn('thinking', requests[0])
        self.assertEqual(requests[1]['thinking'], {'type':'disabled'})
        self.assertTrue(all(r['max_tokens']==4096 and r['stream'] is False for r in requests))
        for change in ({'model':'different-model'}, {'baseURL':'https://other.example/v1'},
                {'thinkingMode':'enabled'}, {'thinkingMode':False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                OwnerChatModel({**config,'thinkingMode':'disabled',**change},
                    lambda: self.fail('Unsupported options must not resolve a credential'))

    def test_member_base_urls_preserve_custom_api_paths(self):
        self.assertEqual(base_url('https://opencode.ai/zen/go/v1'), 'https://opencode.ai/zen/go/v1')
        for url in ('https://other.example.com/zen/go/v1', 'http://localhost:8000/api',
                    'https://127.0.0.1:9000/v2', 'http://[::1]:8888', 'https://opencode.ai.evil.example/zen/go/v1'):
            with self.subTest(url=url): self.assertEqual(base_url(url), url)
        with self.assertRaises(ValueError): base_url('https://opencode.ai/zen/go/v1?key=fixture')

    def test_go_agent_headers_and_tools_use_the_selected_model_without_retries(self):
        requests = []
        def wire(request):
            requests.append(request)
            return httpx.Response(200, json={'model': 'deepseek-flash',
                'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'synthetic answer'}}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15}})
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'deepseek-flash',
            'baseURL': 'https://opencode.ai/inference/go/v1'}, lambda: SecretLease('api-key', 'synthetic-key'),
            transport_factory=lambda: httpx.MockTransport(wire))
        for _ in range(2): asyncio.run(model.ainvoke([Message(role='user', content='synthetic')]))
        self.assertEqual(len(requests), 2)
        self.assertEqual(str(requests[0].url), 'https://opencode.ai/inference/go/v1/chat/completions')
        self.assertTrue(requests[0].headers['user-agent'].startswith('agent-factory/'))
        self.assertEqual(requests[0].headers['x-opencode-session'], requests[1].headers['x-opencode-session'])
        self.assertNotIn('synthetic-key', requests[0].headers['x-opencode-session'])
        self.assertEqual(json.loads(requests[0].content)['model'], 'deepseek-flash')

    def test_go_conversation_id_can_survive_model_reconstruction_for_an_immutable_plan(self):
        requests = []
        def wire(request):
            requests.append(request)
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'synthetic completion'}}]})
        for _ in range(2):
            model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
                'baseURL': 'https://opencode.ai/zen/go/v1'}, lambda: SecretLease('api-key', 'synthetic-key'),
                transport_factory=lambda: httpx.MockTransport(wire), session_id='af-plan-syntheticfixture')
            asyncio.run(model.ainvoke([Message(role='user', content='synthetic')]))
        self.assertEqual([r.headers['x-opencode-session'] for r in requests], ['af-plan-syntheticfixture'] * 2)

    def test_go_pinned_transport_approves_only_its_exact_chat_route(self):
        async def run():
            transport = PinnedChatTransport('https://opencode.ai', base_path='/zen/go/v1')
            try:
                for url in ('https://opencode.ai/v1/chat/completions', 'https://opencode.ai/zen/go/v1/models',
                            'https://other.example.com/zen/go/v1/chat/completions'):
                    with self.assertRaises(ValueError): await transport.handle_async_request(httpx.Request('POST', url))
            finally: await transport.aclose()
            other = PinnedChatTransport('https://other.example.com', base_path='/zen/go/v1')
            await other.aclose()
        asyncio.run(run())

    def model(self, handler, credential=None):
        return OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://models.example.com/v1'},
            credential or (lambda: SecretLease('api-key', 'synthetic-test-password')),
            transport_factory=lambda: httpx.MockTransport(handler))

    def test_native_agno_tool_loop_and_single_call_without_usage(self):
        seen = []
        def wire(request):
            self.assertEqual(str(request.url), 'https://models.example.com/v1/chat/completions')
            self.assertEqual(request.headers['authorization'], 'Bearer synthetic-test-password')
            body = json.loads(request.content); seen.append(body)
            self.assertFalse(body['stream'])
            self.assertEqual(body['model'], 'fixture-model')
            result = {'role': 'assistant', 'content': 'fixture completion'}
            finish = 'stop'
            if len(seen) == 1:
                finish = 'tool_calls'
                result = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'fixture-call',
                    'type': 'function', 'function': {'name': 'checksum_fixture', 'arguments': '{}'}}]}
            return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': result}]})
        def checksum_fixture(): return 'fixture-checksum'
        model = self.model(wire)
        result = asyncio.run(Agent(model=model, tools=[checksum_fixture], markdown=False).arun('Check synthetic fixture'))
        self.assertEqual(result.content, 'fixture completion')
        self.assertEqual(len(seen), 2)
        self.assertTrue(any(m['role'] == 'tool' and m['content'] == 'fixture-checksum' for m in seen[1]['messages']))
        self.assertNotIn('synthetic-test-password', repr(model))

    def test_no_environment_fallback_and_sanitized_errors_and_echo(self):
        calls = []
        def unavailable(): raise ValueError('synthetic-test-password')
        def wire(request):
            calls.append(request)
            return httpx.Response(200, json={'choices': [], 'secret': 'synthetic-test-password'})
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic-environment-forbidden'}):
            with self.assertRaises(ModelProviderError) as error:
                asyncio.run(self.model(wire, unavailable).ainvoke([Message(role='user', content='fixture')]))
        self.assertEqual(calls, [])
        self.assertNotIn('synthetic-test-password', str(error.exception))
        with self.assertRaises(ModelProviderError):
            asyncio.run(self.model(wire).ainvoke([Message(role='user', content='fixture')]))
        self.assertEqual(len(calls), 1)

    def test_unsupported_protocols_urls_redirects_and_multimodal(self):
        for url in ('ftp://models.example.com/v1', 'https://user:pass@models.example.com/v1',
            'https://models.example.com/v1?api_key=synthetic', 'https://models.example.com/v1/../../'):
            with self.subTest(url=url), self.assertRaises(ValueError): base_url(url)
        model = self.model(lambda request: httpx.Response(302, headers={'location': 'https://other.example.com'}))
        with self.assertRaises(ModelProviderError): asyncio.run(model.ainvoke([Message(role='user', content='fixture')]))
        with self.assertRaises(ModelProviderError): asyncio.run(model.ainvoke([Message(role='user', content=['bad-format'])]))

    def test_pinned_destination_and_tls_hostname(self):
        observed = []
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                observed.append(request)
                return httpx.Response(200, json={})
        async def run():
            transport = PinnedChatTransport('https://models.example.com')
            await transport.transport.aclose()
            transport.transport = Wire()
            checks = []
            transport.before_send = lambda: checks.append('current-owner')
            transport.probe.addresses = lambda destination: ['93.184.216.34']
            async with httpx.AsyncClient(transport=transport) as client:
                await client.post('https://models.example.com/v1/chat/completions', json={'fixture': True})
                with self.assertRaises(ValueError): await client.post('https://other.example.com/v1/chat/completions')
                self.assertEqual(checks, ['current-owner'])
                def denied(): raise PermissionError('Owner revoked during DNS')
                transport.before_send = denied
                with self.assertRaises(PermissionError):
                    await client.post('https://models.example.com/v1/chat/completions', json={})
        asyncio.run(run())
        self.assertEqual(str(observed[0].url), 'https://93.184.216.34/v1/chat/completions')
        self.assertEqual(observed[0].headers['host'], 'models.example.com')
        self.assertEqual(observed[0].extensions['sni_hostname'], 'models.example.com')

    def test_async_cancellation_closes_transport_without_retry(self):
        closed, calls = [], []
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                calls.append(request)
                await asyncio.Event().wait()
            async def aclose(self): closed.append(True)
        async def run():
            model = self.model(lambda request: httpx.Response(200))
            model._transport_factory = Wire
            task = asyncio.create_task(model.ainvoke([Message(role='user', content='fixture')]))
            while not calls: await asyncio.sleep(.001)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        asyncio.run(run())
        self.assertEqual(len(calls), 1)
        self.assertEqual(closed, [True])

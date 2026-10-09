"""Controlled provider wire contract; no credentials or external network."""
import asyncio
import json
import unittest
from unittest.mock import patch

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.message import Message
import httpx

from agent_factory.byok_model import OwnerChatModel, PinnedChatTransport, base_url
from agent_factory.personal_remote_provider import SecretLease


class ByokModelTests(unittest.TestCase):
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
        for url in ('http://models.example.com/v1', 'https://127.0.0.1/v1',
            'https://models.example.com/v2', 'https://user:pass@models.example.com/v1',
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

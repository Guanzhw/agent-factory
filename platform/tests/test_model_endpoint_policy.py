"""Shared endpoint security, using synthetic values and in-memory transports."""
import asyncio
import unittest
from unittest.mock import patch

import httpx

from agent_factory.model_endpoint_policy import (
    GO_BASE, GO_CURRENT_BASE, GO_OPENAI_BASE, base_url, chat_headers, generation_options,
)
from agent_factory.model_transport import PinnedChatTransport, read_response_json
from agent_factory.personal_remote_provider import SecretLease


class ModelEndpointPolicyTests(unittest.TestCase):
    def test_member_endpoint_addresses_and_custom_paths_are_normalized(self):
        for value in ('https://models.example.com/v1', GO_BASE, GO_CURRENT_BASE, GO_OPENAI_BASE,
                'https://opencode.ai.evil.example/inference/go/v1',
                'https://other.example/inference/go/v1', 'https://opencode.ai/inference/other/v1',
                'https://127.0.0.1/v1', 'https://[::1]/v1', 'http://models.example/v1',
                'https://models.example:8443/v1', 'http://192.168.1.25:8000/custom/api',
                'http://localhost:8080/custom/inference'):
            with self.subTest(value=value):
                self.assertEqual(base_url(value + '/'), value)
        self.assertEqual(base_url(GO_CURRENT_BASE + '//'), GO_CURRENT_BASE)

    def test_malformed_urls_credentials_and_ambiguous_paths_are_rejected(self):
        for value in (GO_CURRENT_BASE + '?key=synthetic', GO_CURRENT_BASE + '#fragment',
                'https://user:synthetic@models.example/v1', 'ftp://models.example/v1',
                'https:///v1', 'https://models.example:65536/v1',
                'https://models.example:0/v1', 'https://[::1/v1',
                'https://models.example/v1/../other', 'https://models.example/./v1',
                'https://models.example/a b', 'https://models.example/v1' + chr(10)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                base_url(value)

    def test_headers_are_exact_provider_policy_independent_of_protocol(self):
        lease = SecretLease('api-key', 'synthetic-policy-secret')
        for base in (GO_BASE, GO_CURRENT_BASE, GO_OPENAI_BASE):
            headers = chat_headers(base, lease, 'fixture-session')
            self.assertEqual(headers['x-opencode-session'], 'fixture-session')
            self.assertTrue(headers['User-Agent'].startswith('agent-factory/'))
            with self.assertRaises(ValueError):
                chat_headers(base, lease, lease.password)
        for base in ('https://models.example/v1',
                'https://opencode.ai.evil.example/inference/go/v1', 'https://other.example/inference/go/v1'):
            self.assertEqual(chat_headers(base, lease, None),
                {'Authorization': 'Bearer synthetic-policy-secret', 'Accept-Encoding': 'identity'})

    def test_legacy_extension_is_not_migrated_to_new_endpoint_or_protocol(self):
        old = {'baseURL': GO_BASE, 'model': 'longcat-2.5-preview-free', 'thinkingMode': 'disabled'}
        self.assertEqual(generation_options(old), {'thinking': {'type': 'disabled'}})
        for changes in ({'baseURL': GO_CURRENT_BASE}, {'protocol': 'responses'}, {'model': 'gpt-6-luna'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                generation_options({**old, **changes})

    def test_both_routes_pin_tls_identity_recheck_owner_and_never_use_environment(self):
        async def run():
            for protocol, suffix in [('chat-completions', '/chat/completions'), ('responses', '/responses')]:
                observed, order = [], []
                def wire(request):
                    order.append('wire')
                    observed.append(request)
                    return httpx.Response(200, json={})
                with patch.dict('os.environ', {'HTTPS_PROXY': 'http://forbidden.invalid:1',
                        'SSL_CERT_FILE': '/nonexistent-policy-test'}):
                    transport = PinnedChatTransport('https://opencode.ai', base_path='/inference/go/v1',
                        protocol=protocol, before_send=lambda: order.append('owner'),
                        on_dispatch=lambda: order.append('dispatch'))
                await transport.transport.aclose()
                transport.transport = httpx.MockTransport(wire)
                def addresses(destination):
                    order.append('dns')
                    self.assertEqual(destination, 'https://opencode.ai')
                    return ['93.184.216.34']
                transport.probe.addresses = addresses
                async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                    await client.post(GO_CURRENT_BASE + suffix, json={'fixture': True})
                    self.assertEqual(order, ['dns', 'owner', 'dispatch', 'wire'])
                    self.assertEqual(str(observed[0].url), 'https://93.184.216.34/inference/go/v1' + suffix)
                    self.assertEqual(observed[0].headers['host'], 'opencode.ai')
                    self.assertEqual(observed[0].extensions['sni_hostname'], 'opencode.ai')
                    def revoked():
                        raise PermissionError('synthetic revocation during DNS')
                    transport.before_send = revoked
                    with self.assertRaises(PermissionError):
                        await client.post(GO_CURRENT_BASE + suffix, json={})
                    for url in (GO_CURRENT_BASE + '/models', GO_BASE + suffix,
                            GO_CURRENT_BASE + ('/responses' if protocol == 'chat-completions' else '/chat/completions')):
                        with self.assertRaises(ValueError):
                            await client.post(url, json={})
                    self.assertEqual(len(observed), 1)
        asyncio.run(run())

    def test_response_limits_and_credential_echo_are_shared(self):
        async def run():
            lease = SecretLease('api-key', 'synthetic-policy-secret')
            valid = httpx.Response(200, json={'choices': []})
            self.assertEqual(await read_response_json(valid, lease), {'choices': []})
            for response in (httpx.Response(302), httpx.Response(200, content=b'{broken'),
                    httpx.Response(200, content=b' ' * 1_048_577),
                    httpx.Response(200, json={'content': lease.password})):
                with self.assertRaises(ValueError):
                    await read_response_json(response, lease)
        asyncio.run(run())

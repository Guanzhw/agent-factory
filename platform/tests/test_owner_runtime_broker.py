"""Synthetic model transport; no native research engine or network here."""
import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import httpx

from agent_factory.owner_runtime_broker import OwnerRuntimeBroker
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.platform_openresearch import _UnixHTTP


class OwnerRuntimeBrokerTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.revoked, self.calls = False, []
        self.answer = {'choices': [{'message': {'role': 'assistant', 'content': 'Synthetic native response'}, 'finish_reason': 'stop'}]}
        def wire(request):
            self.calls.append(request)
            return httpx.Response(200, json=self.answer)
        def check():
            if self.revoked: raise ValueError('synthetic-private-key')
        self.handle = SimpleNamespace(body={'baseURL': 'https://models.example.com/v1', 'model': 'owner-selected-model'},
            service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(wire)), check=check,
            credential=lambda: SecretLease('api-key', 'synthetic-private-key'))
        self.broker = OwnerRuntimeBroker(Path(self.folder.name) / 'broker.sock', self.handle)

    def test_original_harness_wire_is_pinned_to_owner_model_without_key_in_local_body(self):
        body = {'model': 'owner-model', 'stream': True,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Synthetic native input'}]}]}
        value = asyncio.run(self.broker.completion(body))
        self.assertEqual(value['choices'][0]['message']['content'], 'Synthetic native response')
        outgoing = json.loads(self.calls[0].content)
        self.assertEqual(outgoing['model'], 'owner-selected-model')
        self.assertFalse(outgoing['stream'])
        self.assertEqual(outgoing['messages'][0]['content'], 'Synthetic native input')
        self.assertEqual(self.calls[0].headers['Authorization'], 'Bearer synthetic-private-key')
        self.assertNotIn('synthetic-private-key', json.dumps(body))
        self.assertNotIn('synthetic-private-key', repr(self.broker))

    def test_rotation_revocation_echo_and_multimodal_fail_closed(self):
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'Synthetic input'}]}
        self.revoked = True
        with self.assertRaises(ValueError): asyncio.run(self.broker.completion(body))
        self.assertEqual(self.calls, [])
        self.revoked = False; self.answer['secret'] = 'synthetic-private-key'
        with self.assertRaises(ValueError): asyncio.run(self.broker.completion(body))
        calls = len(self.calls)
        body['messages'][0]['content'] = [{'type': 'image_url', 'image_url': 'https://example.com/private.png'}]
        with self.assertRaises(ValueError): asyncio.run(self.broker.completion(body))
        self.assertEqual(len(self.calls), calls)
        self.assertFalse(self.broker.authorized('foreign-capability'))
        self.broker.deadline = 0
        self.assertFalse(self.broker.authorized(self.broker.capability))

    @unittest.skipUnless(sys.platform == 'linux', 'Pinned platform package uses Linux private sockets')
    def test_long_private_workspace_socket_stream_and_sanitized_revocation(self):
        directory = Path(self.folder.name) / ('workspace-' + 'a' * 80) / ('owner-' + 'b' * 40)
        directory.mkdir(mode=0o700, parents=True)
        broker = OwnerRuntimeBroker(directory / 'broker.sock', self.handle)
        broker.start(); self.addCleanup(broker.close)
        self.assertGreater(len(str(broker.path)), 108)
        def call(token, text='Synthetic local wire'):
            client = _UnixHTTP(broker.path)
            try:
                client.request('POST', '/v1/chat/completions', body=json.dumps({'model': 'owner-model', 'stream': True,
                    'messages': [{'role': 'user', 'content': text}]}),
                    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                response = client.getresponse()
                return response.status, response.read().decode()
            finally: client.close()
        self.assertEqual(call('foreign-capability')[0], 401)
        self.assertEqual(call('foreign-capability', 'Synthetic unauthorized body ' * 4096)[0], 401)
        self.assertEqual(self.calls, [])
        status, value = call(broker.capability)
        self.assertEqual(status, 200)
        self.assertIn('Synthetic native response', value); self.assertIn('[DONE]', value)
        self.assertNotIn('synthetic-private-key', value)
        self.revoked = True
        status, value = call(broker.capability)
        self.assertEqual(status, 502); self.assertNotIn('synthetic-private-key', value)

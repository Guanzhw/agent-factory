"""Synthetic upstream wire shapes; no harness, model, secret or external server."""
import asyncio
import inspect
import json
import sqlite3
import unittest
from typing import Any, cast
from unittest.mock import patch

import httpx

from agent_factory.orx_research_session import (OpenResearchSessionHTTP, OrxSessionError,
    OrxSessionUnknown, OrxSessionCancelled)


def session(**changes):
    return {'id': 'chat_original', 'projectId': 'project_original', 'harness': 'opencode',
        'model': 'fixture/model', 'busy': False, 'archived': False,
        'contextUsage': {'usedTokens': 12345}, **changes}


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE intents(key TEXT PRIMARY KEY, body TEXT)')
        self.requests = []
        self.handler: Any = None

    def commit(self, *, intent):
        with self.assertRaises(TypeError):
            intent['key'] = 'cannot-mutate'
        self.db.execute('INSERT INTO intents VALUES(?,?)', (intent['key'], json.dumps(dict(intent))))
        self.db.commit()

    async def wire(self, request):
        self.requests.append(request)
        self.assertEqual(request.url.host, '127.0.0.1')
        self.assertEqual(request.url.port, 38123)
        self.assertNotIn('authorization', request.headers)
        self.assertNotIn('cookie', request.headers)
        if request.method == 'GET' and request.url.path == '/api/chat/sessions':
            self.assertEqual(request.url.params['projectId'], 'project_original')
            return httpx.Response(200, json={'sessions': [session()]})
        if request.method == 'POST':
            self.assertEqual(self.db.execute('SELECT count(*) FROM intents').fetchone()[0], 1)
        value = self.handler(request)
        return await value if inspect.isawaitable(value) else value

    def client(self):
        return OpenResearchSessionHTTP(38123, project_id='project_original', harness='opencode',
            model='fixture/model', transport=httpx.MockTransport(self.wire))

    async def test_request_diagnostics_separate_timeout_status_json_and_reader_shape(self):
        cases = [
            ('timeout', lambda request: (_ for _ in ()).throw(httpx.ReadTimeout('synthetic-sensitive')),
             'request', None, 'ReadTimeout'),
            ('status', lambda request: httpx.Response(503, json={'private': 'synthetic-sensitive'}),
             'headers', 503, None),
            ('json', lambda request: httpx.Response(200, content=b'not-json', headers={'content-type': 'application/json'}),
             'json', 200, None),
            ('shape', lambda request: httpx.Response(200, json={'messages': [], 'queued': [], 'activeLeafId': 'ahead'}),
             'shape', None, None),
        ]
        for name, handler, phase, status, error_type in cases:
            self.handler = handler
            with self.subTest(name=name), self.assertRaises(OrxSessionError) as caught:
                await self.client().read_messages('chat_original')
            details = dict(cast(dict, caught.exception.session_diagnostic))
            self.assertEqual(details['route'], 'messages')
            self.assertEqual(details['phase'], phase)
            self.assertEqual(details['httpStatus'], status)
            if error_type:
                self.assertEqual(details['errorType'], error_type)
            self.assertNotIn('synthetic-sensitive', json.dumps(details))
            self.assertNotIn('chat_original', json.dumps(details))

    async def test_create_pins_exact_identity_and_never_promotes_context_usage(self):
        def handler(request):
            self.assertEqual(json.loads(request.content), {'projectId': 'project_original', 'harness': 'opencode', 'model': 'fixture/model'})
            return httpx.Response(200, json={'session': session()})
        self.handler = handler
        value = await self.client().create_session(key='create-original', commit_intent=self.commit)
        self.assertEqual(value['id'], 'chat_original')
        self.assertFalse(value['usageKnown'])
        self.assertFalse(value['stoppedProof'])
        self.assertNotIn('contextUsage', value)
        self.assertEqual(len(self.requests), 1)

    async def test_lost_create_ack_unknown_and_new_transport_cannot_blind_recreate(self):
        def lost(request):
            raise httpx.ReadError('private response and credential-like text')
        self.handler = lost
        with self.assertRaises(OrxSessionUnknown) as caught:
            await self.client().create_session(key='create-original', commit_intent=self.commit)
        self.assertEqual(str(caught.exception), 'ORX_SESSION_ACK_UNKNOWN')
        self.assertEqual(caught.exception.intent['operation'], 'create')
        self.assertIsNone(caught.exception.intent['sessionId'])
        with self.assertRaises(sqlite3.IntegrityError):
            await self.client().create_session(key='create-original', commit_intent=self.commit)
        self.assertEqual(len(self.requests), 1)

    async def test_post_cancellation_retains_unknown_intent_and_native_cancel_type(self):
        async def cancelled(request):
            raise asyncio.CancelledError()
        self.handler = cancelled
        with self.assertRaises(OrxSessionCancelled) as caught:
            await self.client().create_session(key='create-original', commit_intent=self.commit)
        self.assertIsInstance(caught.exception, asyncio.CancelledError)
        self.assertEqual(caught.exception.intent['key'], 'create-original')
        self.assertEqual(len(self.requests), 1)

    async def test_create_wrong_model_or_project_ack_is_unknown_not_adopted(self):
        for changed in ({'model': 'other/model'}, {'projectId': 'other-project'}, {'harness': 'codex'}):
            self.db.execute('DELETE FROM intents'); self.db.commit()
            self.handler = lambda request: httpx.Response(200, json={'session': session(**changed)})
            with self.subTest(changed=changed), self.assertRaises(OrxSessionUnknown):
                await self.client().create_session(key='create-original', commit_intent=self.commit)

    async def test_rename_title_requires_committed_intent_and_exact_readback(self):
        def handler(request):
            self.assertEqual(request.method, 'PATCH')
            self.assertEqual(json.loads(request.content), {'title': 'Factory research'})
            self.assertEqual(self.db.execute('SELECT count(*) FROM intents').fetchone()[0], 1)
            return httpx.Response(200, json={'session': session(title='Factory research')})
        self.handler = handler
        result = await self.client().rename_session('chat_original', 'Factory research', key='rename', commit_intent=self.commit)
        self.assertEqual(result['title'], 'Factory research')
        with self.assertRaises(sqlite3.IntegrityError):
            await self.client().rename_session('chat_original', 'Factory research', key='rename', commit_intent=self.commit)

    async def test_message_preserves_client_turn_and_separates_upstream_turn_id(self):
        def handler(request):
            self.assertEqual(request.url.path, '/api/chat/sessions/chat_original/message')
            self.assertEqual(json.loads(request.content), {'text': 'public synthetic goal', 'clientTurnId': 'client-original'})
            return httpx.Response(200, json={'ok': True, 'turn': {'turnId': 'turn_original', 'queued': False, 'existing': False}})
        self.handler = handler
        value = await self.client().send_message('chat_original', 'public synthetic goal', client_turn_id='client-original',
            key='message-original', commit_intent=self.commit)
        self.assertEqual(value['clientTurnId'], 'client-original')
        self.assertEqual(value['turnId'], 'turn_original')
        intent = json.loads(self.db.execute('SELECT body FROM intents').fetchone()[0])
        self.assertEqual(intent['sessionId'], 'chat_original')
        self.assertEqual(intent['clientTurnId'], 'client-original')
        self.assertNotIn('public synthetic goal', json.dumps(intent))

    async def test_message_queued_ack_uses_client_identity_and_is_not_completion(self):
        self.handler = lambda request: httpx.Response(200, json={'ok': True,
            'turn': {'turnId': 'client-original', 'queued': True, 'existing': True}})
        value = await self.client().send_message('chat_original', 'goal', client_turn_id='client-original',
            key='message-original', commit_intent=self.commit)
        self.assertTrue(value['queued'])
        self.assertFalse(value['stoppedProof'])

    async def test_interrupt_ack_is_not_positive_stop_proof(self):
        self.handler = lambda request: httpx.Response(200, json={'ok': True})
        value = await self.client().interrupt('chat_original', key='cancel-original', commit_intent=self.commit)
        self.assertEqual(value, {'sessionId': 'chat_original', 'interruptAcknowledged': True, 'stoppedProof': False})

    async def test_messages_have_scope_readback_and_bounded_untrusted_transcript(self):
        rows = [{'id': 'msg_original', 'role': 'assistant', 'parts': [{'id': 'p1', 'type': 'text', 'text': 'Synthetic answer'}],
            'createdAt': 1, 'completedAt': 2, 'parentId': None}]
        self.handler = lambda request: httpx.Response(200, json={'messages': rows, 'queued': [], 'activeLeafId': 'msg_original'})
        value = await self.client().read_messages('chat_original')
        self.assertEqual(value['messages'], rows)
        self.assertEqual([r.url.path for r in self.requests], ['/api/chat/sessions',
            '/api/chat/sessions/chat_original/messages', '/api/chat/sessions'])
        self.assertFalse(value['usageKnown'])

    async def test_redirect_error_oversize_duplicate_json_never_retried(self):
        replies = [httpx.Response(302, headers={'location': 'https://unrelated.invalid/'}),
            httpx.Response(429, json={'error': 'private quota message'}),
            httpx.Response(200, content=b'{"session":{},"overflow":1e400}', headers={'content-type': 'application/json'}),
            httpx.Response(200, content=b'{"session":{},"session":{}}', headers={'content-type': 'application/json'}),
            httpx.Response(200, content=b'x' * (2 * 1024**2 + 1), headers={'content-type': 'application/json'})]
        for response in replies:
            self.db.execute('DELETE FROM intents'); self.db.commit()
            self.requests.clear()
            self.handler = lambda request: response
            with self.assertRaises(OrxSessionUnknown):
                await self.client().create_session(key='original', commit_intent=self.commit)
            self.assertEqual(len(self.requests), 1)

    async def test_missing_or_async_commit_denies_before_http(self):
        async def async_commit(**kwargs):
            raise AssertionError('must never run')
        for callback in (None, async_commit):
            with self.assertRaises(OrxSessionError):
                await self.client().create_session(key='original', commit_intent=cast(Any, callback))
        self.assertEqual(self.requests, [])

    async def test_sse_filters_global_events_and_always_requires_snapshot_resync(self):
        raw = (b'event: chat.busy\ndata: {"sessionId":"other","busy":true}\n\n'
               b'event: chat.message\ndata: {"sessionId":"chat_original",\n'
               b'data: "message":{"private":"not forwarded"}}\n\n'
               b'event: resync.required\ndata: {}\n\n')
        self.handler = lambda request: httpx.Response(200, content=raw, headers={'content-type': 'text/event-stream'})
        value = await self.client().events('chat_original')
        self.assertEqual(value, {'events': [{'type': 'chat.message', 'sessionId': 'chat_original'}], 'resyncRequired': True})

    async def test_request_hash_pins_configured_scope_not_only_path(self):
        intents = []
        def commit(*, intent):
            intents.append(dict(intent)); self.commit(intent=intent)
        for model in ('fixture/model', 'fixture/other'):
            self.db.execute('DELETE FROM intents'); self.db.commit()
            self.handler = lambda request: httpx.Response(200, json={'session': session(model=model)})
            client = OpenResearchSessionHTTP(38123, project_id='project_original', harness='opencode',
                model=model, transport=httpx.MockTransport(self.wire))
            await client.create_session(key='original', commit_intent=commit)
        self.assertNotEqual(intents[0]['requestHash'], intents[1]['requestHash'])

    def test_operator_port_and_identity_reject_url_or_path_injection(self):
        for port in ('https://outside.invalid', True, 0, 65536):
            with self.assertRaises(OrxSessionError):
                OpenResearchSessionHTTP(cast(Any, port), project_id='p', harness='opencode', model='fixture/model')
        with self.assertRaises(OrxSessionError):
            OpenResearchSessionHTTP(38123, project_id='../outside', harness='opencode', model='fixture/model')
        with patch.dict('os.environ', {'HTTP_PROXY': 'http://unreachable.invalid', 'OPENCODE_GO': 'synthetic-unused'}, clear=True):
            client = self.client()._client()
            self.assertFalse(client.trust_env)
            self.assertFalse(client.follow_redirects)

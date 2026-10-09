"""Native ORX wire shapes + real ordinary command persistence; synthetic only."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool

from agent_factory.connections import ConnectionService
from agent_factory.personal_agent_sessions import PersonalAgentSessions
from agent_factory.personal_agent_transport import PERSONAL_CONTRACT
from agent_factory.personal_orx_transport import (
    PERSONAL_ORX_PROVIDER_ID, PersonalOrxProvider, PersonalOrxHTTPS, PersonalOrxHandle,
)
from agent_factory.personal_remote_provider import SecretLease, RemoteConnectionError
from test_personal_agent_sessions import Auth, Secrets


class NativeOrxWire:
    allows = staticmethod(PersonalOrxHTTPS.allows)
    def __init__(self):
        self.calls = []; self.drop = None; self.before_address = None; self.public = False; self.echo = None
        self.rows = {'chat_original': {'id': 'chat_original', 'projectId': 'native-project',
            'harness': 'opencode', 'model': 'owner/model', 'permissionMode': 'default',
            'planMode': False, 'reasoningLevel': 'medium', 'serviceTier': None,
            'busy': False, 'archived': False, 'title': 'Original native research'}}
        self.messages = {'chat_original': []}
        self.prompts = 0
        self.queued_ack = False
    def addresses(self, destination):
        if self.before_address: self.before_address()
        return ['93.184.216.34']
    def request(self, destination, address, method, path, lease, payload=None):
        assert self.allows(method, path, payload)
        self.calls.append((method, path, deepcopy(payload), lease is not None))
        if lease is None and not self.public: return 401, None
        route = urlsplit(path).path
        if route == '/api/health': value = {'ok': True, 'version': '0.2.13', 'dashboardProtocol': 2, 'instanceId': 'native-instance'}
        elif route == '/api/projects/native-project': value = {'project': {'id': 'native-project', 'name': 'Original native project', 'repoPath': '/native/repo'}}
        elif route == '/api/chat/sessions' and method == 'GET':
            assert parse_qs(urlsplit(path).query) == {'projectId': ['native-project']}
            value = {'sessions': list(self.rows.values())}
        elif route == '/api/chat/sessions' and method == 'POST':
            assert payload['projectId'] == 'native-project'
            sid = 'chat_created_' + str(len(self.rows))
            self.rows[sid] = {'id': sid, **deepcopy(payload), 'busy': False, 'archived': False, 'title': None}
            self.messages[sid] = []
            value = {'session': self.rows[sid]}
        else:
            sid = route.split('/')[4]
            if method == 'PATCH':
                self.rows[sid]['title'] = payload['title']; value = {'session': self.rows[sid]}
            elif route.endswith('/messages'):
                values = self.messages[sid]
                value = {'messages': values, 'queued': [], 'activeLeafId': values[-1]['id'] if values else None}
            elif route.endswith('/message'):
                assert set(payload) == {'text', 'clientTurnId'}
                self.prompts += 1
                user_id, answer_id = 'msg_native_user_' + str(self.prompts), 'msg_native_answer_' + str(self.prompts)
                prior = self.messages[sid][-1]['id'] if self.messages[sid] else None
                self.messages[sid].extend([
                    {'id': user_id, 'role': 'user', 'parentId': prior, 'createdAt': self.prompts * 10, 'completedAt': self.prompts * 10,
                     'parts': [{'id': 'part-native-user', 'type': 'text', 'text': payload['text']}]},
                    {'id': answer_id, 'role': 'assistant', 'parentId': user_id, 'createdAt': self.prompts * 10 + 1,
                     'completedAt': self.prompts * 10 + 2, 'parts': [
                         {'id': 'part-native-reasoning', 'type': 'reasoning', 'text': 'not a user-visible artifact'},
                         {'id': 'part-native-tool', 'type': 'tool', 'tool': 'owner-tool', 'state': {'status': 'completed', 'output': 'Native tool result'}},
                         {'id': 'part-native-answer', 'type': 'text', 'text': 'Native answer ' + str(self.prompts)}]}])
                value = {'ok': True, 'turn': {'turnId': payload['clientTurnId'] if self.queued_ack else 'turn_native_' + str(self.prompts),
                    'queued': self.queued_ack, 'existing': False}}
            elif route.endswith('/interrupt'): value = {'ok': True}
            else: raise AssertionError('Unsupported fixture route')
        if self.echo == route:
            value['echo'] = 'synthetic-test-password'
        if self.drop == path:
            self.drop = None
            raise RemoteConnectionError('Synthetic lost response')
        return 200, deepcopy(value)


class PersonalOrxTests(unittest.TestCase):
    def setUp(self):
        self.wire, self.secrets, self.auth = NativeOrxWire(), Secrets(), Auth()
        self.provider = PersonalOrxProvider(self.secrets, transport=self.wire)
        self.config = {'origin': 'https://runtime.example.com', 'credentialRef': 'synthetic-reference',
            'credentialRevision': 'r1', 'projectId': 'native-project', 'authMode': 'bearer'}
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        md = MetaData()
        Table('af_audit', md, Column('id', Integer, primary_key=True), Column('actor_id', String),
            Column('action', String), Column('target_id', String), Column('body', JSON), Column('created_at', String))
        md.create_all(self.engine)
        self.connections = ConnectionService(SimpleNamespace(engine=self.engine), self.auth,
            personal_providers={PERSONAL_ORX_PROVIDER_ID: self.provider}, clock=lambda: datetime(2026,10,8,tzinfo=timezone.utc))
        remote = self.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID, self.config, 'configure-orx')
        self.connections.personal.verify('alice', remote['registrationRef'], 'verify-orx')
        self.bound = self.connections.bind('alice', remote['registrationRef'], 'bind-orx')
        self.admission_allowed = True
        def admission(owner, intent):
            if not self.admission_allowed: raise HTTPException(403, 'Original native mandate revoked')
            return {'planId': 'controlled-plan', 'taskId': 'controlled-task', 'nativeRunId': 'controlled-run',
                'executionContract': PERSONAL_CONTRACT}
        self.admission = admission
        self.service = PersonalAgentSessions(self.connections, admission=admission)
    def handle(self):
        return self.connections.resolve('alice', self.bound['ref'], 'orx',
            expected_adapter_ref=PERSONAL_ORX_PROVIDER_ID, required_capabilities=['session:read'])
    def attach(self):
        return self.service.attach('alice', self.bound['ref'], 'native-project', 'chat_original', 'attach-native')
    def posts(self): return [c for c in self.wire.calls if c[0] in {'POST', 'PATCH'}]

    def test_true_native_existing_attach_multiturn_tool_transcript_and_interrupt(self):
        project = self.service.project('alice', self.bound['ref'])
        self.assertEqual(project['namespace'], 'native-openresearch')
        self.assertEqual(project['upstreamOrxProjectId'], 'native-project')
        choices = self.service.native_sessions('alice', self.bound['ref'])
        self.assertEqual(choices['sessions'][0]['nativeSessionId'], 'chat_original')
        attached = self.attach(); sid = attached['session']['id']
        self.assertEqual(self.posts(), [])
        first = self.service.prompt('alice', sid, 'Investigate with my native tools', 'first-native-turn')
        self.assertEqual(first['state'], 'acknowledged')
        self.assertEqual(first['result']['nativeTurnId'], 'turn_native_1')
        self.assertIsNone(first['result']['nativeMessageId'])
        observed = self.service.inspect('alice', sid, refresh=True)
        self.assertIsNone(observed['activeRequestId'])
        self.assertEqual(observed['observation']['correlationSource'], 'inferred-transcript-delta')
        self.assertFalse(observed['observation']['exactTurnVerified'])
        self.assertFalse(observed['stopVerified'])
        answer = observed['observation']['messages'][-1]
        self.assertEqual(answer['events'][0]['tool'], 'owner-tool')
        self.assertEqual(answer['events'][-1]['text'], 'Native answer 1')
        self.assertNotIn('not a user-visible artifact', json.dumps(observed))
        self.assertEqual(answer['usage'], {})
        second = self.service.prompt('alice', sid, 'Continue the original native research', 'second-native-turn')
        self.assertEqual(second['state'], 'acknowledged')
        self.service.inspect('alice', sid, refresh=True)
        interrupted = self.service.interrupt('alice', sid, 'interrupt-native')
        self.assertFalse(interrupted['result']['stopVerified'])
        self.assertEqual(len(self.wire.rows), 1)
        self.assertTrue(all(c[1].startswith('/api/') for c in self.wire.calls))
        self.assertFalse(any(c[1] == '/api/projects' for c in self.posts()))

    def test_unknown_ack_never_adopts_resembling_transcript_or_resends_after_restart(self):
        sid = self.attach()['session']['id']
        self.wire.drop = '/api/chat/sessions/chat_original/message'
        result = self.service.prompt('alice', sid, 'Original request', 'unknown-native')
        self.assertEqual(result['state'], 'ack_unknown')
        original_count = len(self.posts())
        restarted = PersonalAgentSessions(self.connections, admission=self.admission)
        observed = restarted.inspect('alice', sid, refresh=True)
        self.assertEqual(observed['activeRequestId'], 'unknown-native')
        self.assertEqual(observed['observation']['messages'][-1]['events'][-1]['text'], 'Native answer 1')
        restarted.prompt('alice', sid, 'Original request', 'unknown-native')
        self.assertEqual(len(self.posts()), original_count)
        with self.assertRaises(HTTPException): restarted.prompt('alice', sid, 'Do not guess completion', 'new-request')

    def test_baseline_history_rewrite_or_truncation_cannot_clear_active_turn(self):
        sid = self.attach()['session']['id']
        self.service.prompt('alice', sid, 'First context', 'first')
        self.service.inspect('alice', sid, refresh=True)
        self.service.prompt('alice', sid, 'Next context', 'next')
        self.wire.messages['chat_original'][0]['parts'][0]['text'] = 'Rewritten original history'
        self.assertEqual(self.service.inspect('alice', sid, refresh=True)['activeRequestId'], 'next')
        self.wire.messages['chat_original'].pop(0)
        self.assertEqual(self.service.inspect('alice', sid, refresh=True)['activeRequestId'], 'next')

    def test_concurrent_or_running_native_tool_observation_is_not_completion(self):
        sid = self.attach()['session']['id']
        self.service.prompt('alice', sid, 'Original tools', 'tool-turn')
        self.wire.messages['chat_original'][-1]['parts'][1]['state']['status'] = 'running'
        self.assertEqual(self.service.inspect('alice', sid, refresh=True)['activeRequestId'], 'tool-turn')
        self.wire.messages['chat_original'][-1]['parts'][1]['state']['status'] = 'completed'
        extra = deepcopy(self.wire.messages['chat_original'][-1]); extra['id'] = 'concurrent-native-answer'
        self.wire.messages['chat_original'].append(extra)
        self.assertEqual(self.service.inspect('alice', sid, refresh=True)['activeRequestId'], 'tool-turn')

    def test_queued_ack_does_not_mislabel_client_id_as_native_turn(self):
        sid = self.attach()['session']['id']
        self.wire.queued_ack = True
        result = self.service.prompt('alice', sid, 'Queued race', 'queued-turn')
        self.assertIsNone(result['result']['nativeTurnId'])
        self.assertEqual(self.service.inspect('alice', sid, refresh=True)['activeRequestId'], 'queued-turn')

    def test_mutation_requires_fresh_admission_after_dns(self):
        self.attach()
        handle = self.handle()
        self.wire.before_address = lambda: setattr(self, 'admission_allowed', False)
        with self.assertRaises(HTTPException):
            handle.call('POST', '/api/chat/sessions/chat_original/message',
                {'text': 'Denied before native send', 'clientTurnId': 'original-client-turn'},
                before_send=lambda: self.admission('alice', {}))
        self.assertEqual(self.posts(), [])

    def test_connection_revoked_inside_before_send_cannot_transmit(self):
        handle = self.handle()
        with self.assertRaises(Exception):
            handle.prompt_session('chat_original', 'Must not send', None, None,
                before_send=lambda: setattr(self.secrets, 'enabled', False))
        self.assertEqual(self.posts(), [])

    def test_remote_default_model_stays_upstream_and_creation_requires_explicit_template(self):
        self.wire.rows['chat_original']['model'] = None
        native = self.handle().session('chat_original')
        self.assertEqual(native['modelSelection'], 'remote-default')
        self.assertIsNone(native['model'])
        with self.assertRaises(RemoteConnectionError):
            self.handle().create_session('No implicit model choice', before_send=lambda: None)
        self.assertEqual(self.posts(), [])

    def test_explicit_native_template_creation_preserves_options_without_project_creation(self):
        handle = PersonalOrxHandle(self.provider, 'alice', {**self.config, 'sessionTemplateId': 'chat_original'}, lambda _: None)
        result = handle.create_session('Named native session', before_send=lambda: None)
        self.assertTrue(result['nativeSessionId'].startswith('chat_created_'))
        create = next(c for c in self.posts() if c[1] == '/api/chat/sessions')
        self.assertEqual(create[2]['model'], 'owner/model')
        self.assertEqual(create[2]['harness'], 'opencode')
        self.assertEqual(create[2]['reasoningLevel'], 'medium')
        self.assertEqual(result['titleUpdate'], 'acknowledged')
        self.assertFalse(any(c[1] == '/api/projects' for c in self.posts()))

    def test_bearer_basic_modes_and_narrow_route_contract(self):
        credential = SecretLease('owner', 'service-token')
        bearer = PersonalOrxHTTPS(auth_mode='bearer')
        basic = PersonalOrxHTTPS(auth_mode='basic-proxy')
        self.assertEqual(bearer.authorization_header(credential), 'Bearer service-token')
        self.assertTrue(basic.authorization_header(credential).startswith('Basic '))
        for method, path, payload in [('POST', '/api/projects', {}), ('POST', '/api/chat/sessions/id/respond', {}),
                ('GET', '/api/chat/sessions?scope=all', None), ('GET', '/api/chat/sessions?projectId=x&projectId=y', None),
                ('GET', '//169.254.169.254/api/health', None), ('GET', '/api/project-path/status', None),
                ('PATCH', '/api/chat/sessions/id', {'permissionMode': 'bypass'}), ('GET', '/api/chat/sessions?malformed', None)]:
            self.assertFalse(bearer.allows(method, path, payload), path)
        self.assertTrue(bearer.anonymous_allowed('GET', '/api/health'))
        self.assertFalse(bearer.anonymous_allowed('GET', '/api/projects'))

    def test_successful_native_auth_echo_is_rejected_before_transcript_persistence(self):
        sid = self.attach()['session']['id']
        self.service.prompt('alice', sid, 'Native response with adversarial metadata', 'echo-turn')
        self.wire.echo = '/api/chat/sessions/chat_original/messages'
        with self.assertRaises(Exception) as caught:
            self.service.inspect('alice', sid, refresh=True)
        self.assertNotIn('synthetic-test-password', str(caught.exception))
        self.assertIsNone(self.service.inspect('alice', sid)['observation'])
        self.assertNotIn('synthetic-test-password', json.dumps(self.service.request_result('alice', 'echo-turn')))

    def test_successful_verification_cannot_persist_native_service_secret_echo(self):
        self.wire.echo = '/api/health'
        with self.assertRaises(RemoteConnectionError) as caught:
            self.provider.verify('alice', self.config)
        self.assertNotIn('synthetic-test-password', str(caught.exception))
        self.assertEqual(str(caught.exception), 'REMOTE_CREDENTIAL_ECHO_REJECTED')

    def test_provider_never_accepts_an_unauthenticated_or_unsupported_server(self):
        self.wire.public = True
        with self.assertRaises(RemoteConnectionError): self.provider.verify('alice', self.config)
        with self.assertRaises(RemoteConnectionError): self.provider.verify('bob', self.config)
        for changes in ({'authMode': 'implicit'}, {'origin': 'http://localhost'}, {'arbitraryModelKey': 'blocked'}):
            with self.assertRaises(RemoteConnectionError): self.provider.configure({**self.config, **changes})

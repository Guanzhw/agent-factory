"""Real local HTTP wire, synthetic OpenCode contract only; no live model/ORX claim."""
from copy import deepcopy
import base64
from datetime import datetime, timezone
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool

from agent_factory.connections import ConnectionService
from agent_factory.personal_agent_sessions import PersonalAgentSessions, project_messages
from agent_factory.personal_agent_transport import (PERSONAL_PROVIDER_ID, PERSONAL_CONTRACT,
    PersonalOpenCodeServeProvider, PersonalAgentTransport)
from agent_factory.personal_remote_provider import SecretLease, RemoteConnectionError


class Auth:
    enabled = True
    def require(self, owner, action):
        if not self.enabled: raise HTTPException(403, 'denied')


class Secrets:
    enabled = True
    def authorize(self, **scope):
        return self.enabled and scope == dict(owner='alice', reference='synthetic-reference',
            revision='r1', destination='https://runtime.example.com')
    def resolve(self, **scope):
        if not self.authorize(**scope): raise ValueError('synthetic secret never surface')
        return SecretLease('opencode', 'synthetic-test-password')


class Probe:
    def addresses(self, destination): return ['93.184.216.34']
    def get(self, destination, address, path, lease=None):
        if lease is None: return 401, None
        return 200, {'/global/health': {'healthy': True, 'version': '1.2.3'},
            '/project/current': {'id': 'native-project'}, '/agent': [{'name': 'build'}]}[path]


class Sessions(unittest.TestCase):
    def setUp(self):
        self.wire = []; self.remote = {}; self.drop = None
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): self.handle_call('GET')
            def do_POST(self): self.handle_call('POST')
            def handle_call(self, method):
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                body = json.loads(raw) if raw else None
                fixture.wire.append((method, self.path, body))
                if self.headers.get('Authorization') is None:
                    self.send_response(401); self.end_headers(); return
                status = 200
                if self.path == '/project/current': value = {'id': 'native-project'}
                elif self.path == '/session' and method == 'GET':
                    value = [{'id': sid, 'projectID': 'native-project'} for sid in fixture.remote]
                elif self.path == '/session' and method == 'POST':
                    sid = 'ses_' + str(len(fixture.remote) + 1)
                    fixture.remote[sid] = []
                    value = {'id': sid, 'projectID': 'native-project'}
                else:
                    sid = self.path.split('/')[2]
                    if self.path.endswith('/prompt_async'):
                        # Real wire fixture preserves original history across turns.
                        mid = body['messageID']; aid = 'msg_assistant_' + str(len(fixture.remote[sid]))
                        fixture.remote[sid].extend([
                            {'info': {'id': mid, 'sessionID': sid, 'role': 'user'}, 'parts': [
                                {'type': 'text', 'sessionID': sid, 'messageID': mid, 'text': body['parts'][0]['text']}]},
                            {'info': {'id': aid, 'sessionID': sid, 'role': 'assistant', 'parentID': mid,
                                'time': {'completed': 42}, 'finish': 'tool-calls', 'cost': 0.007, 'tokens': {'input': 11, 'output': 7}},
                             'parts': [{'type': 'tool', 'sessionID': sid, 'messageID': aid, 'tool': 'fixture',
                                'state': {'status': 'completed', 'output': 'synthetic tool result'}},
                                {'type': 'text', 'sessionID': sid, 'messageID': aid, 'text': 'synthetic tool commentary'}]},
                            {'info': {'id': aid + '_final', 'sessionID': sid, 'role': 'assistant',
                                'parentID': mid, 'finish': 'stop', 'time': {'completed': 43}},
                             'parts': [{'type': 'text', 'sessionID': sid, 'messageID': aid + '_final',
                                 'text': 'synthetic turn result'}]}])
                        status, value = 204, None
                    elif self.path.endswith('/abort'): value = True
                    elif self.path.endswith('/message'): value = fixture.remote[sid]
                    else: value = {'id': sid, 'projectID': 'native-project'}
                if fixture.drop == self.path:
                    fixture.drop = None
                    self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
                self.send_response(status); self.send_header('Content-Type', 'application/json'); self.end_headers()
                if status != 204: self.wfile.write(json.dumps(value).encode())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.patch = patch('agent_factory.personal_agent_transport._PinnedHTTPS',
            side_effect=lambda host, address: http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        md = MetaData()
        Table('af_audit', md, Column('id', Integer, primary_key=True), Column('actor_id', String),
            Column('action', String), Column('target_id', String), Column('body', JSON), Column('created_at', String))
        md.create_all(self.engine)
        self.auth, self.secrets = Auth(), Secrets()
        transport = PersonalAgentTransport()
        transport.addresses = lambda destination: ['93.184.216.34']
        self.provider = PersonalOpenCodeServeProvider(self.secrets, probe=Probe(), transport=transport)
        self.connections = ConnectionService(SimpleNamespace(engine=self.engine), self.auth,
            personal_providers={PERSONAL_PROVIDER_ID: self.provider}, clock=lambda: datetime(2026,10,8,tzinfo=timezone.utc))
        remote = self.connections.personal.configure('alice', PERSONAL_PROVIDER_ID,
            {'origin': 'https://runtime.example.com', 'credentialRef': 'synthetic-reference',
                'credentialRevision': 'r1', 'projectId': 'native-project'}, 'configure')
        self.registration = remote['registrationRef']
        self.connections.personal.verify('alice', self.registration, 'verify')
        self.bound = self.connections.bind('alice', self.registration, 'bind')
        self.admissions = []
        def admission(owner, intent):
            self.admissions.append(deepcopy(intent))
            return {'planId': 'synthetic-plan', 'taskId': 'synthetic-task', 'nativeRunId': 'synthetic-run',
                'executionContract': PERSONAL_CONTRACT}
        self.admission = admission
        self.service = PersonalAgentSessions(self.connections, admission=admission)

    def create(self, request='create'):
        return self.service.create('alice', self.bound['ref'], 'native-project', request)

    def test_real_wire_multiturn_tool_result_unknown_restart_and_interrupt(self):
        created = self.create(); sid = created['session']['id']; remote = created['session']['nativeSessionId']
        self.assertEqual(created['state'], 'acknowledged')
        self.assertEqual(self.admissions[0], self.admissions[1])
        first = self.service.prompt('alice', sid, 'first synthetic turn', 'turn1')
        self.assertEqual(first['state'], 'acknowledged')
        with self.assertRaises(HTTPException): self.service.prompt('alice', sid, 'overlap', 'overlap')
        observation = self.service.inspect('alice', sid, refresh=True)['observation']
        self.assertEqual(observation['messages'][1]['events'][0]['type'], 'tool')
        self.assertEqual(observation['messages'][1]['usage']['cost'], 0.007)
        self.assertFalse(observation['trustedMetering'])
        self.drop = '/session/' + remote + '/prompt_async'
        unknown = self.service.prompt('alice', sid, 'second with original context', 'turn2')
        self.assertEqual(unknown['state'], 'ack_unknown')
        posts = len([c for c in self.wire if c[0] == 'POST'])
        self.service = PersonalAgentSessions(self.connections, admission=self.admission)
        replay = self.service.prompt('alice', sid, 'second with original context', 'turn2')
        self.assertEqual(replay['state'], 'ack_unknown')
        self.assertEqual(posts, len([c for c in self.wire if c[0] == 'POST']))
        seen = self.service.inspect('alice', sid, refresh=True)
        self.assertEqual(len(seen['observation']['messages']), 6)
        self.assertEqual(self.service.request_result('alice', 'turn2')['state'], 'result_observed')
        stopped = self.service.interrupt('alice', sid, 'interrupt')
        self.assertEqual(stopped['session']['state'], 'interrupt_requested_stop_unverified')
        self.assertFalse(stopped['session']['stopVerified'])
        self.assertIsNone(stopped['session']['upstreamOrxProjectId'])
        self.assertTrue(all('model' not in (body or {}) for method, path, body in self.wire))

    def test_unknown_create_never_reposts_or_adopts_title(self):
        self.drop = '/session'
        result = self.create()
        self.assertIsNone(result['session']['nativeSessionId'])
        posts = len(self.wire)
        self.service = PersonalAgentSessions(self.connections, admission=self.admission)
        self.create()
        self.service.inspect('alice', result['session']['id'], refresh=True)
        self.assertEqual(posts, len(self.wire))
        self.assertEqual(len(self.remote), 1)

    def test_owner_scope_revoke_rotation_and_current_grant_fences(self):
        result = self.create(); sid = result['session']['id']
        for operation in (lambda: self.service.inspect('bob', sid),
                lambda: self.service.request_result('bob', 'create')):
            with self.assertRaises(HTTPException): operation()
        self.secrets.enabled = False
        posts = len(self.wire)
        with self.assertRaises(HTTPException): self.service.prompt('alice', sid, 'x', 'turn')
        self.assertEqual(posts, len(self.wire))
        self.secrets.enabled = True
        self.connections.revoke('alice', self.bound['ref'], 'revoke')
        with self.assertRaises(HTTPException): self.service.prompt('alice', sid, 'x', 'turn')
        self.assertEqual(posts, len(self.wire))
        self.assertEqual(self.service.inspect('alice', sid)['nativeSessionId'], 'ses_1')

    def test_admission_failure_and_changed_identity_never_post(self):
        self.service.admission = lambda owner, intent: {'executionContract': 'managed'}
        with self.assertRaises(HTTPException): self.create()
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire))
        count = [0]
        def changing(owner, intent):
            count[0] += 1
            return {**self.admission(owner, intent), 'nativeRunId': str(count[0])}
        self.service.admission = changing
        self.assertEqual(self.create()['state'], 'ack_unknown')
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire))

    def test_revocation_between_admission_and_wire_blocks_post(self):
        calls = [0]
        def revoke(owner, intent):
            calls[0] += 1
            result = self.admission(owner, intent)
            if calls[0] == 2:
                self.connections.revoke('alice', self.bound['ref'], 'revoke-before-wire')
            return result
        self.service.admission = revoke
        result = self.create()
        self.assertEqual(result['state'], 'ack_unknown')
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire))

    def test_durable_intent_exists_before_wire_and_body_never_carries_keys(self):
        original = self.provider.transport.request
        def checked(destination, address, method, path, lease, payload=None):
            if method == 'POST':
                record = self.service._command('alice', 'create')
                self.assertIsNotNone(record)
                self.assertEqual(record['state'], 'ack_unknown')
                self.assertEqual(record['identity']['executionContract'], PERSONAL_CONTRACT)
                self.assertEqual(set(payload), {'title'})
            return original(destination, address, method, path, lease, payload)
        self.provider.transport.request = checked
        self.assertEqual(self.create()['state'], 'acknowledged')

    def test_narrow_scope_reads_but_handle_cannot_escalate_to_post(self):
        pin = self.connections.bind('alice', self.registration, 'read-only-bind',
            capabilities=['project:read', 'session:read'])
        handle = self.connections.resolve('alice', pin['ref'], 'environment',
            required_capabilities=['project:read'])
        self.assertEqual(handle.project()['nativeProjectId'], 'native-project')
        for path in ('/session', '/session/ses_1/prompt_async', '/session/ses_1/abort'):
            with self.assertRaises(HTTPException): handle.call('POST', path, {})
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire))

    def test_completed_tool_message_does_not_complete_turn(self):
        created = self.create(); sid = created['session']['id']; remote = created['session']['nativeSessionId']
        self.service.prompt('alice', sid, 'tool progress', 'tool-turn')
        final = self.remote[remote].pop()
        observed = self.service.inspect('alice', sid, refresh=True)
        self.assertEqual(observed['activeRequestId'], 'tool-turn')
        self.assertFalse(observed['observation']['messages'][-1]['terminalResult'])
        with self.assertRaises(HTTPException): self.service.prompt('alice', sid, 'overlap', 'overlap')
        self.remote[remote].append(final)
        self.assertIsNone(self.service.inspect('alice', sid, refresh=True)['activeRequestId'])

    def test_attach_original_session_is_read_only_and_reuses_mapping(self):
        self.remote['ses_original'] = []
        discovery = self.service.native_sessions('alice', self.bound['ref'])
        self.assertEqual(discovery['sessions'][0]['nativeSessionId'], 'ses_original')
        self.service.admission = lambda owner, intent: self.fail('Local read-only attach must not manufacture task')
        attached = self.service.attach('alice', self.bound['ref'], 'native-project', 'ses_original', 'attach1')
        self.assertIsNone(attached['factoryIdentity'])
        self.assertIsNone(attached['session']['factoryIdentity'])
        again = self.service.attach('alice', self.bound['ref'], 'native-project', 'ses_original', 'attach2')
        self.assertEqual(attached['session']['id'], again['session']['id'])
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire))
        other = self.connections.bind('alice', self.registration, 'second-binding')
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_CONNECTION_REBIND_REQUIRED'):
            self.service.attach('alice', other['ref'], 'native-project', 'ses_original', 'attach3')

    def test_cancelled_native_admission_during_dns_never_posts(self):
        live = [True]
        committed_dns = [0]
        original = self.provider.transport.addresses
        def dns(destination):
            # Trigger only after immutable effect intent exists (mutation DNS).
            record = self.service._command('alice', 'create')
            if record is not None:
                committed_dns[0] += 1
                if committed_dns[0] >= 2: live[0] = False
            return original(destination)
        self.provider.transport.addresses = dns
        def admission(owner, intent):
            if not live[0]: raise HTTPException(409, 'NATIVE_TASK_CANCELLED')
            return self.admission(owner, intent)
        self.service.admission = admission
        result = self.create()
        self.assertEqual(result['state'], 'ack_unknown')
        self.assertFalse(any(method == 'POST' for method, _, _ in self.wire))

    def test_observed_callback_runs_after_committed_original_result(self):
        observed = []
        def callback(owner, request_id):
            record = self.service._command(owner, request_id)
            self.assertEqual(record['state'], 'result_observed')
            observed.append(request_id)
        self.service.observed = callback
        sid = self.create()['session']['id']
        self.service.prompt('alice', sid, 'first', 'prompt-observed')
        self.service.inspect('alice', sid, refresh=True)
        self.assertEqual(observed, ['prompt-observed'])
        original = self.service.request_result('alice', 'prompt-observed')['result']['observationEvidence']
        self.assertEqual(original['correlationSource'], 'native-message-parent-id')
        self.assertFalse(original['stopVerified'])
        self.service.inspect('alice', sid, refresh=True)
        self.assertEqual(self.service.request_result('alice', 'prompt-observed')['result']['observationEvidence'], original)

    def test_duplicate_attach_with_real_pool_size_one_never_nested_checks(self):
        folder = TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'synthetic-pool.db'
        target = sqlite3.connect(path)
        source = self.engine.raw_connection()
        try: source.driver_connection.backup(target)
        finally: source.close(); target.close()
        single = create_engine('sqlite:///' + str(path), pool_size=1, max_overflow=0, pool_timeout=.1)
        self.addCleanup(single.dispose)
        self.engine = single
        self.connections.store.engine = single
        original = self.service._handle
        def checked(*args, **kwargs):
            self.assertEqual(single.pool.checkedout(), 0, 'Authorization called while metadata connection held')
            return original(*args, **kwargs)
        self.service._handle = checked
        self.remote['ses_original'] = []
        first = self.service.attach('alice', self.bound['ref'], 'native-project', 'ses_original', 'single-attach1')
        second = self.service.attach('alice', self.bound['ref'], 'native-project', 'ses_original', 'single-attach2')
        self.assertEqual(first['session']['id'], second['session']['id'])
        self.assertEqual(single.pool.checkedout(), 0)

    def test_authenticated_wire_echo_never_enters_observation_storage(self):
        created = self.create(); sid = created['session']['id']; remote = created['session']['nativeSessionId']
        self.service.prompt('alice', sid, 'ordinary prompt', 'clean-prompt')
        self.remote[remote][1]['parts'][0]['state']['output'] = 'echo synthetic-test-password must be rejected'
        with self.assertRaisesRegex(RemoteConnectionError, 'REMOTE_CREDENTIAL_ECHO_REJECTED'):
            self.service.inspect('alice', sid, refresh=True)
        self.assertIsNone(self.service.inspect('alice', sid)['observation'])
        with self.engine.connect() as conn:
            for table in (self.service.sessions, self.service.commands):
                self.assertNotIn('synthetic-test-password', json.dumps([dict(r) for r in conn.execute(table.select()).mappings()]))

    def test_injected_transport_password_basic_and_bearer_echo_are_rejected(self):
        encoded = base64.b64encode(b'opencode:synthetic-test-password').decode()
        for echoed in ('synthetic-test-password', encoded, 'Basic ' + encoded, 'Bearer synthetic-test-password'):
            self.provider.transport.request = lambda *args, echo=echoed, **kwargs: (200, {
                'id': 'native-project', 'nested': [{'remoteField': echo}]})
            with self.assertRaisesRegex(RemoteConnectionError, 'REMOTE_CREDENTIAL_ECHO_REJECTED'):
                self.service.project('alice', self.bound['ref'])
        self.provider.transport.request = lambda *args, **kwargs: (200, {
            'id': 'native-project', 'nested': {'synthetic-test-password': 'even object keys'}})
        with self.assertRaisesRegex(RemoteConnectionError, 'REMOTE_CREDENTIAL_ECHO_REJECTED'):
            self.service.project('alice', self.bound['ref'])

    def test_fixed_paths_no_shared_credentials_and_no_redirects(self):
        transport = PersonalAgentTransport(); lease = SecretLease('fixture', 'fixture')
        for method, path in [('POST', '/auth/openai'), ('POST', '/config'), ('POST', '/session/x/shell'),
                ('GET', '/session/x/../../auth'), ('DELETE', '/session/x')]:
            with self.assertRaises(RemoteConnectionError):
                transport.request('https://runtime.example.com', '93.184.216.34', method, path, lease, {})

    def test_mismatched_session_message_identity_rejected(self):
        with self.assertRaises(HTTPException): project_messages([
            {'info': {'id': 'm', 'sessionID': 'wrong', 'role': 'assistant'}, 'parts': []}], 'ses_1')

if __name__ == '__main__': unittest.main()

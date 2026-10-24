"""Shared invocation uses owner custody and immediately observes withdrawal."""
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool

from agno.models.message import Message
from agent_factory.byok_model import OwnerChatModel, PROVIDER_ID as MODEL_PROVIDER
from agent_factory.connections import ConnectionService
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.model_endpoint_policy import model_origin
from agent_factory.personal_models import PersonalModels
from agent_factory.personal_remote_provider import PROVIDER_ID, OpenCodeServeProvider
from test_personal_remote_connections import Auth, Probe, Secrets


@contextmanager
def public_service():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            requests.append((self.path, self.headers.get('Authorization')))
            data = {'/global/health': {'healthy': True, 'version': '1.2.3'},
                '/project/current': {'id': 'public-project'}, '/agent': [{'name': 'build'}]}[self.path]
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, self.headers.get('Authorization'), body))
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({'choices': [{'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'public model response'}}]}).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', requests
    finally: server.shutdown(); server.server_close(); thread.join()


class ResourceSharingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        Table('af_audit', metadata, Column('id', Integer, primary_key=True), Column('actor_id', String),
            Column('action', String), Column('target_id', String), Column('body', JSON), Column('created_at', String))
        metadata.create_all(self.engine)
        self.store = SimpleNamespace(engine=self.engine, _connection=ContextVar('sharing-test', default=None))
        self.auth, self.probe = Auth(), Probe()
        self.connections = ConnectionService(self.store, self.auth, clock=lambda: datetime(2026, 10, 8, tzinfo=timezone.utc),
            personal_providers={PROVIDER_ID: OpenCodeServeProvider(Secrets(), probe=self.probe)})
        self.remote = self.connections.personal

    def test_team_remote_invokes_with_owner_secret_and_withdrawal_blocks_existing_handle(self):
        resource = self.remote.configure('alice', PROVIDER_ID, {'origin': 'https://runtime.example.com',
            'credentialRef': 'synthetic-vault-ref', 'credentialRevision': 'v1', 'projectId': 'project-fixture'}, uuid4().hex)
        ref = resource['registrationRef']
        self.remote.verify('alice', ref, uuid4().hex)
        self.assertEqual(self.remote.list('bob'), [])
        with self.assertRaises(HTTPException): self.connections.bind('bob', ref, uuid4().hex)
        self.remote.share('alice', ref, 'team', uuid4().hex)
        shared = self.remote.list('bob')[0]
        self.assertEqual((shared['ownerId'], shared['visibility'], shared['isOwner']), ('alice', 'team', False))
        self.assertEqual(shared['allowedActions'], ['inspect', 'bind'])
        self.assertNotIn('credentialRef', str(shared))
        for change in (lambda: self.remote.revoke('bob', ref, uuid4().hex),
                       lambda: self.remote.share('bob', ref, 'personal', uuid4().hex),
                       lambda: self.remote.verify('bob', ref, uuid4().hex)):
            with self.assertRaises(HTTPException): change()
        binding = self.connections.bind('bob', ref, uuid4().hex)
        handle = self.connections.resolve('bob', binding['ref'], 'environment')
        self.assertEqual(handle.owner, 'alice')
        self.assertEqual(handle.inspect_identity()['projectId'], 'project-fixture')
        self.remote.share('alice', ref, 'personal', uuid4().hex)
        self.assertEqual(self.remote.list('bob'), [])
        with self.assertRaises(HTTPException): handle.inspect_identity()
        with self.assertRaises(HTTPException): self.connections.resolve('bob', binding['ref'], 'environment')
        owner_binding = self.connections.bind('alice', ref, uuid4().hex)
        self.connections.resolve('alice', owner_binding['ref'], 'environment').inspect_identity()

    def model(self):
        vault = EncryptedCredentialVault(self.engine, b'f' * 32, {MODEL_PROVIDER: model_origin})
        vault.bind_read_context(self.store._connection)
        self.models = PersonalModels(self.store, self.auth, self.connections, vault)
        self.connections.owner_models = self.models
        credential = vault.create(owner='alice', provider_id=MODEL_PROVIDER, destination='https://model.example.com',
            username='api-key', password='synthetic-model-password', request_id=uuid4().hex)
        return self.models.configure('alice', {'provider': 'openai-compatible', 'baseURL': 'https://model.example.com/v1',
            'model': 'synthetic-model', 'credentialRef': credential['credentialRef'],
            'credentialRevision': credential['credentialRevision']}, uuid4().hex)

    def test_team_default_resolves_owner_credential_without_exposing_owner_refs(self):
        model = self.model(); ref = model['reference']
        self.assertEqual(self.models.list('bob'), [])
        self.models.share('alice', ref, 'team', uuid4().hex)
        public = self.models.list('bob')[0]
        self.assertFalse(public['isOwner'])
        self.assertNotIn('credentialRef', public)
        self.assertNotIn('credentialRevision', public)
        self.assertNotIn('connectionRef', public)
        with self.assertRaises(HTTPException): self.models.revoke('bob', ref, uuid4().hex)
        with self.assertRaises(HTTPException): self.models.share('bob', ref, 'personal', uuid4().hex)
        selected = self.models.set_default('bob', ref, uuid4().hex)
        self.assertNotEqual(selected['connectionRef'], model['connectionRef'])
        self.assertNotIn('credentialRef', self.models.default('bob'))
        handle = self.connections.resolve('bob', selected['connectionRef'], 'model')
        self.assertEqual((handle.actor, handle.owner), ('bob', 'alice'))
        self.assertEqual(handle.credential().password, 'synthetic-model-password')
        self.models.share('alice', ref, 'personal', uuid4().hex)
        with self.assertRaises(HTTPException): handle.credential()
        with self.assertRaises(HTTPException): self.models.default('bob')
        with self.assertRaises(HTTPException): self.connections.resolve('bob', selected['connectionRef'], 'model')
        self.assertEqual(self.connections.resolve('alice', model['connectionRef'], 'model').credential().password,
            'synthetic-model-password')

    def test_public_model_and_remote_invoke_real_http_without_vault_or_placeholder_secret(self):
        with public_service() as (url, requests):
            models = PersonalModels(self.store, self.auth, self.connections, None)
            self.connections.owner_models = models
            configured = models.configure('alice', {'provider': 'openai-compatible', 'baseURL': url + '/custom/api',
                'model': 'public-model'}, uuid4().hex)
            self.assertIsNone(configured['credentialRef'])
            models.share('alice', configured['reference'], 'team', uuid4().hex)
            selected = models.set_default('bob', configured['reference'], uuid4().hex)
            handle = self.connections.resolve('bob', selected['connectionRef'], 'model')
            native = OwnerChatModel(handle.body, handle.credential, recheck=handle.check)
            self.assertEqual(native.invoke([Message(role='user', content='hello')]).content, 'public model response')
            self.assertEqual(requests[0][0:2], ('/custom/api/chat/completions', None))
            self.assertEqual(requests[0][2]['model'], 'public-model')
            self.auth.disabled = True
            with self.assertRaises(Exception): native.invoke([Message(role='user', content='disabled')])
            self.assertEqual(len(requests), 1)
            self.auth.disabled = False
            models.share('alice', configured['reference'], 'personal', uuid4().hex)
            with self.assertRaises(Exception): native.invoke([Message(role='user', content='withdrawn')])
            self.assertEqual(len(requests), 1)
            provider = OpenCodeServeProvider(Secrets())
            self.connections.personal.providers[PROVIDER_ID] = provider
            remote = self.remote.configure('alice', PROVIDER_ID, {'origin': url, 'projectId': 'public-project'}, uuid4().hex)
            self.remote.verify('alice', remote['registrationRef'], uuid4().hex)
            self.remote.share('alice', remote['registrationRef'], 'team', uuid4().hex)
            bound = self.connections.bind('bob', remote['registrationRef'], uuid4().hex)
            remote_handle = self.connections.resolve('bob', bound['ref'], 'environment')
            self.assertEqual(remote_handle.inspect_identity()['projectId'], 'public-project')
            self.assertTrue(all(item[1] is None for item in requests))
            count = len(requests)
            self.auth.disabled = True
            with self.assertRaises(HTTPException): remote_handle.inspect_identity()
            self.assertEqual(len(requests), count)
            self.auth.disabled = False
            self.remote.revoke('alice', remote['registrationRef'], uuid4().hex)
            with self.assertRaises(HTTPException): remote_handle.inspect_identity()
            self.assertEqual(len(requests), count)

    def test_revoked_model_credential_and_disabled_member_reject_saved_handle(self):
        model = self.model(); ref = model['reference']
        self.models.share('alice', ref, 'team', uuid4().hex)
        selected = self.models.set_default('bob', ref, uuid4().hex)
        handle = self.connections.resolve('bob', selected['connectionRef'], 'model')
        self.auth.disabled = True
        with self.assertRaises(HTTPException): handle.credential()
        self.auth.disabled = False
        self.models.vault.revoke(owner='alice', reference=model['credentialRef'], revision=model['credentialRevision'], request_id=uuid4().hex)
        with self.assertRaises(HTTPException): handle.credential()
        with self.assertRaises(HTTPException): self.connections.resolve('bob', selected['connectionRef'], 'model')

    def test_credential_revocation_stops_cached_native_model_before_real_http(self):
        with public_service() as (url, requests):
            vault = EncryptedCredentialVault(self.engine, b'f' * 32, {MODEL_PROVIDER: model_origin})
            vault.bind_read_context(self.store._connection)
            models = PersonalModels(self.store, self.auth, self.connections, vault)
            self.connections.owner_models = models
            credential = vault.create(owner='alice', provider_id=MODEL_PROVIDER, destination=url,
                username='api-key', password='synthetic-owner-key', request_id=uuid4().hex)
            configured = models.configure('alice', {'provider': 'openai-compatible', 'baseURL': url + '/custom/api',
                'model': 'team-model', 'credentialRef': credential['credentialRef'],
                'credentialRevision': credential['credentialRevision']}, uuid4().hex)
            models.share('alice', configured['reference'], 'team', uuid4().hex)
            selected = models.set_default('bob', configured['reference'], uuid4().hex)
            handle = self.connections.resolve('bob', selected['connectionRef'], 'model')
            native = OwnerChatModel(handle.body, handle.credential, recheck=handle.check)
            native.invoke([Message(role='user', content='before revoke')])
            self.assertEqual(requests[0][1], 'Bearer synthetic-owner-key')
            vault.revoke(owner='alice', reference=credential['credentialRef'], revision=credential['credentialRevision'], request_id=uuid4().hex)
            with self.assertRaises(Exception): native.invoke([Message(role='user', content='after revoke')])
            self.assertEqual(len(requests), 1)

    def test_owner_configuration_change_requires_shared_default_reselection(self):
        original = self.model(); ref = original['reference']
        self.models.share('alice', ref, 'team', uuid4().hex)
        selected = self.models.set_default('bob', ref, uuid4().hex)
        self.models.configure('alice', {key: original[key] for key in
            ('provider', 'baseURL', 'model', 'credentialRef', 'credentialRevision')}, uuid4().hex, reference=ref)
        self.assertFalse(self.models.list('bob')[0]['isDefault'])
        with self.assertRaises(HTTPException): self.models.default('bob')
        current = self.models.set_default('bob', ref, uuid4().hex)
        self.assertNotEqual(current['connectionRef'], selected['connectionRef'])
        self.assertTrue(self.models.default('bob')['isDefault'])

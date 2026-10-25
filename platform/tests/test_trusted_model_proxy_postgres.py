"""Owned disposable PG + existing encrypted vault/auth; provider remains in memory."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.byok_model import PROVIDER_ID
from agent_factory.config import Settings
from agent_factory.credential_vault import EncryptedCredentialVault
from core_native_fixture import create_fixture_app as create_app
from agent_factory.personal_remote_provider import origin
from core_native_fixture import publish_owner_application
from agent_factory.application_runs import factory_request_id
from pg_fixture import IsolatedPostgres
from test_trusted_model_proxy import GatewayBackend, GENERIC_BASE, IP, PROTOCOL_PATHS, grant


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires independent disposable PostgreSQL')
class TrustedModelProxyPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        settings = Settings(db_url=self.database.url, workspace=Path(self.folder.name), max_workers=1,
            temporary_policy='member-self-service', owner_model_proxy_environment_id='fixture-environment',
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b's' * 32, {PROVIDER_ID: origin}))
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        publish_owner_application(self.state, author='manager')
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def request(self, method, path, values=None, *, owner='alice', status=200):
        response = self.client.request(method, '/api/factory'+path, json=values,
            headers={'Authorization':'Bearer '+self.auth._issue_native_token(owner)})
        self.assertEqual(response.status_code, status, response.text)
        self.assertNotIn('synthetic-vault-password', response.text)
        self.assertNotIn('synthetic-rotated-password', response.text)
        return response.json()

    def configure(self, *, base_url=None, protocol=None, suffix=''):
        base = base_url or 'https://opencode.ai/zen/go/v1'
        key = self.request('POST','/personal-credentials', {'requestId':'fixture-proxy-key'+suffix,
            'providerId':PROVIDER_ID,'destination':'https://'+urlsplit(base).netloc,'username':'api-key',
            'password':'synthetic-vault-password'},status=201)
        options = {'protocol': protocol} if protocol is not None else {}
        model = self.request('POST','/personal-models', {**options, 'requestId':'fixture-proxy-model'+suffix,
            'provider':'openai-compatible','baseURL':base,'model':'fixture-model',
            'credentialRef':key['credentialRef'],'credentialRevision':key['credentialRevision']},status=201)
        self.request('POST','/personal-models/'+model['reference']+'/default',{'requestId':'fixture-proxy-default'+suffix})
        if base_url is not None:
            options['base_url'] = base_url
        configuration = grant(model_reference=model['reference'],model_revision=model['revision'],
            credential_reference=model['credentialRef'],credential_revision=model['credentialRevision'], **options)
        self.store.personal_models.install_trusted_model_proxy(configuration)
        return model, configuration

    def test_generic_protocols_complete_native_task_with_existing_owner_vault(self):
        for protocol, path in PROTOCOL_PATHS.items():
            with self.subTest(protocol=protocol):
                model, configuration = self.configure(base_url=GENERIC_BASE, protocol=protocol, suffix='-'+protocol)
                backend = GatewayBackend(configuration, target_host='models.example.com', protocol=protocol)
                request_id = 'fixture-generic-proxy-research-' + protocol
                with patch('agent_factory.byok_model.PinnedHTTPSProbe.addresses', return_value=[IP]), \
                        patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend', return_value=backend):
                    self.request('POST', '/application-interface/v1/starts', {
                        'application': 'fixture-owner-checksum', 'mode': 'literature',
                        'connectionRefs': {'ownerModel': model['connectionRef']}, 'goal': 'Synthetic scoped model flow',
                        'requestId': request_id}, status=202)
                    task = self.store.task_for_request(factory_request_id(request_id), 'alice')
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        native = self.store.native_db.get_job(task['run_id']) or {}
                        if native.get('status') in {'completed', 'failed'}:
                            break
                        time.sleep(.05)
                self.assertEqual(native.get('status'), 'completed')
                self.assertEqual(len(backend.connections), 1)
                wire = b''.join(backend.writes)
                self.assertEqual(wire.count(b'POST '), 1)
                self.assertIn(f'CONNECT {IP}:443 HTTP/1.1\r\n'.encode(), wire)
                post = wire.split(b'POST ', 1)[1]
                self.assertTrue(post.startswith(f'/v1{path} HTTP/1.1\r\n'.encode()))
                headers, payload = post.split(b'\r\n\r\n', 1)
                self.assertIn(b'host: models.example.com', headers.lower())
                self.assertIn(b'authorization: Bearer synthetic-vault-password', headers)
                self.assertNotIn(b'x-opencode-session:', headers.lower())
                sent = json.loads(payload)
                self.assertEqual(sent['model'], 'fixture-model')
                self.assertIs(sent['stream'], False)
                if protocol == 'responses':
                    self.assertIs(sent['store'], False)
                    self.assertIn('input', sent)
                    self.assertNotIn('messages', sent)
                self.assertEqual([tls['server_hostname'] for tls in backend.tls], ['models.example.com'])
                with self.store.personal_models.db.read() as conn:
                    bound = self.store.personal_models.binding(conn, 'alice', model['reference'])
                self.assertEqual(bound.opaque_handle.body.get('protocol', 'chat-completions'), protocol)
                self.assertIs(bound.opaque_handle.trusted_proxy, configuration)

    def test_current_generic_handle_cannot_widen_grant_or_resolve_rotated_credential(self):
        model, configuration = self.configure(base_url=GENERIC_BASE, protocol='responses')
        service = self.store.personal_models
        with service.db.read() as conn:
            handle = service.binding(conn, 'alice', model['reference']).opaque_handle
        for changes in ({'base_url': 'https://opencode.ai/inference/go/v1'}, {'protocol': 'chat-completions'}):
            replacement = grant(model_reference=model['reference'], model_revision=model['revision'],
                credential_reference=model['credentialRef'], credential_revision=model['credentialRevision'],
                **{'base_url': GENERIC_BASE, 'protocol': 'responses', **changes})
            service.install_trusted_model_proxy(replacement)
            with self.subTest(changes=changes), patch.object(service.vault, 'resolve') as resolve:
                with self.assertRaises(HTTPException):
                    handle.credential()
                resolve.assert_not_called()
        service.install_trusted_model_proxy(configuration)
        self.request('POST', '/personal-credentials/'+model['credentialRef']+'/rotate',
            {'requestId': 'fixture-generic-proxy-rotate', 'credentialRevision': model['credentialRevision'],
             'username': 'api-key', 'password': 'synthetic-rotated-password'})
        with patch.object(service.vault, 'resolve') as resolve:
            with self.assertRaises(HTTPException):
                handle.credential()
            resolve.assert_not_called()

    def test_registered_agno_path_uses_existing_owner_vault_and_scoped_gateway(self):
        model, configuration = self.configure()
        backend = GatewayBackend(configuration)
        with patch('agent_factory.byok_model.PinnedHTTPSProbe.addresses',return_value=[IP]), \
                patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend',return_value=backend):
            self.request('POST','/application-interface/v1/starts', {
                'application': 'fixture-owner-checksum', 'mode': 'literature',
                'connectionRefs': {'ownerModel': model['connectionRef']}, 'goal': 'Synthetic scoped model flow',
                'requestId':'fixture-proxy-research'},status=202)
            task = self.store.task_for_request(factory_request_id('fixture-proxy-research'),'alice')
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                native = self.store.native_db.get_job(task['run_id']) or {}
                if native.get('status') in {'completed','failed'}:
                    break
                time.sleep(.05)
        self.assertEqual(native.get('status'),'completed')
        self.assertEqual(len(backend.connections),1)
        wire = b''.join(backend.writes)
        self.assertIn(b'authorization: Bearer synthetic-vault-password',wire)
        self.assertIn(('x-opencode-session: af-plan-'+task['plan_id']).encode(),wire)
        with self.store.personal_models.db.read() as conn:
            bound = self.store.personal_models.binding(conn,'alice',model['reference'])
        self.assertIs(bound.opaque_handle.trusted_proxy,configuration)

    def test_credential_rotation_and_route_revocation_fail_before_new_wire(self):
        model, configuration = self.configure()
        service = self.store.personal_models
        with service.db.read() as conn:
            handle = service.binding(conn,'alice',model['reference']).opaque_handle
        service.install_trusted_model_proxy(None)
        with self.assertRaises(HTTPException):
            handle.credential()
        service.install_trusted_model_proxy(configuration)
        self.request('POST','/personal-credentials/'+model['credentialRef']+'/rotate',
            {'requestId':'fixture-proxy-rotate','credentialRevision':model['credentialRevision'],
             'username':'api-key','password':'synthetic-rotated-password'})
        with self.assertRaises(HTTPException):
            handle.credential()

    def test_proxy_configuration_cannot_be_supplied_by_owner_http_input(self):
        model, configuration = self.configure()
        backend = GatewayBackend(configuration)
        self.request('POST','/personal-models',{'requestId':'fixture-proxy-http-denied',
            'provider':'openai-compatible','baseURL':model['baseURL'],'model':model['model'],
            'credentialRef':model['credentialRef'],'credentialRevision':model['credentialRevision'],
            'trustedProxy':{'proxy_url':'http://untrusted-owner.invalid'}},status=422)
        self.request('POST','/personal-models',{'requestId':'fixture-proxy-foreign-denied',
            'provider':'openai-compatible','baseURL':model['baseURL'],'model':model['model'],
            'credentialRef':model['credentialRef'],'credentialRevision':model['credentialRevision']},owner='bob',status=403)
        self.assertEqual(backend.connections,[])

"""Owned disposable PG + existing encrypted vault/auth; provider remains in memory."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.byok_model import PROVIDER_ID
from agent_factory_research.config import ResearchSettings as Settings
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory_server.main import create_app
from agent_factory.personal_remote_provider import origin
from agent_factory_research.personal_research import publish_application
from pg_fixture import IsolatedPostgres
from test_trusted_model_proxy import GatewayBackend, IP, grant


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires independent disposable PostgreSQL')
class TrustedModelProxyPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        settings = Settings(db_url=self.database.url, workspace=Path(self.folder.name), max_workers=1,
            temporary_policy='admin-review', owner_model_proxy_environment_id='fixture-environment',
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b's' * 32, {PROVIDER_ID: origin}))
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.auth.directory.upsert('fixture-reviewer', name='Synthetic reviewer')
        self.auth.authorization.assign('fixture-reviewer', 'factory-manager')
        publish_application(self.state, author='manager', reviewer='fixture-reviewer')
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

    def configure(self):
        key = self.request('POST','/personal-credentials', {'requestId':'fixture-proxy-key',
            'providerId':PROVIDER_ID,'destination':'https://opencode.ai','username':'api-key',
            'password':'synthetic-vault-password'},status=201)
        model = self.request('POST','/personal-models', {'requestId':'fixture-proxy-model',
            'provider':'openai-compatible','baseURL':'https://opencode.ai/zen/go/v1','model':'fixture-model',
            'credentialRef':key['credentialRef'],'credentialRevision':key['credentialRevision']},status=201)
        self.request('POST','/personal-models/'+model['reference']+'/default',{'requestId':'fixture-proxy-default'})
        configuration = grant(model_reference=model['reference'],model_revision=model['revision'],
            credential_reference=model['credentialRef'],credential_revision=model['credentialRevision'])
        self.store.personal_models.install_trusted_model_proxy(configuration)
        return model, configuration

    def test_registered_agno_path_uses_existing_owner_vault_and_scoped_gateway(self):
        model, configuration = self.configure()
        backend = GatewayBackend(configuration)
        with patch('agent_factory.byok_model.PinnedHTTPSProbe.addresses',return_value=[IP]), \
                patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend',return_value=backend):
            self.request('POST','/personal-research',{'topic':'Synthetic scoped model flow',
                'requestId':'fixture-proxy-research'},status=202)
            task = self.store.task_for_request('fixture-proxy-research','alice')
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

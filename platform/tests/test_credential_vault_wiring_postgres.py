"""Actual native auth/main/vault/remote wiring with synthetic credentials/probe."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.credential_vault import EncryptedCredentialVault, VaultSecretProvider
from agent_factory.main import create_app
from agent_factory.personal_remote_provider import PROVIDER_ID, OpenCodeServeProvider, origin
from pg_fixture import IsolatedPostgres
from test_personal_remote_connections import Probe


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class CredentialVaultWiringPostgresTests(unittest.TestCase):
    def test_secure_save_verify_bind_rotate_and_recover_through_real_main(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        probe = Probe()
        settings = Settings(db_url=database.url, workspace=Path(directory.name), max_workers=1,
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b's' * 32, {PROVIDER_ID: origin}),
            personal_connection_provider_factories={PROVIDER_ID: lambda vault: OpenCodeServeProvider(
                VaultSecretProvider(vault, PROVIDER_ID), probe=probe)})
        app = create_app(settings)
        state = app.app.state.factory
        store = state['store']
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.native_db.db_engine.dispose)
        with TestClient(app) as client:
            credentials = '/api/factory/personal-credentials'
            remotes = '/api/factory/personal-remotes'
            bindings = '/api/factory/user-connections'
            self.assertEqual(client.get(credentials + '/capabilities').status_code, 401)
            self.assertEqual(client.post('/api/factory/demo/login', json={'persona': 'alice'}).status_code, 200)
            self.assertEqual(client.get(credentials + '/capabilities').json(), {'enabled': True, 'providerIds': [PROVIDER_ID]})
            request = {'requestId': 'save-request', 'providerId': PROVIDER_ID,
                'destination': 'https://runtime.example.com', 'username': 'synthetic-user', 'password': 'synthetic-password'}
            response = client.post(credentials, json=request)
            self.assertEqual(response.status_code, 201, response.text)
            credential = response.json()
            self.assertNotIn('synthetic-password', response.text)
            self.assertEqual(client.get(credentials + '/requests/save-request').json(), credential)
            response = client.post(remotes, json={'requestId': 'configure-request', 'providerId': PROVIDER_ID,
                'origin': credential['destination'], 'credentialRef': credential['credentialRef'],
                'credentialRevision': credential['credentialRevision'], 'projectId': 'project-fixture'})
            self.assertEqual(response.status_code, 201, response.text)
            remote = response.json()
            response = client.post(remotes + '/' + remote['registrationRef'] + '/verify', json={'requestId': 'verify-request'})
            self.assertEqual(response.status_code, 200, response.text)
            response = client.post(bindings, json={'requestId': 'bind-request', 'registrationRef': remote['registrationRef'],
                'capabilities': ['runtime:health']})
            self.assertEqual(response.status_code, 201, response.text)
            bound = response.json()
            self.assertEqual(client.get(bindings + '/requests/bind-request').json()['connection']['ref'], bound['ref'])
            rotated = client.post(credentials + '/' + credential['credentialRef'] + '/rotate', json={
                'requestId': 'rotate-request', 'credentialRevision': credential['credentialRevision'],
                'username': 'synthetic-user', 'password': 'synthetic-new-password'})
            self.assertEqual(rotated.status_code, 200, rotated.text)
            with self.assertRaises(HTTPException):
                store.connections.resolve('alice', bound['ref'], 'environment', required_capabilities=['runtime:health'])
            self.assertNotIn('synthetic-password', str(store.sql('SELECT * FROM af_encrypted_credentials')))
            client.cookies.clear()
            self.assertEqual(client.post('/api/factory/demo/login', json={'persona': 'bob'}).status_code, 200)
            self.assertEqual(client.get(credentials + '/requests/save-request').status_code, 404)
            self.assertEqual(client.get(credentials).json(), [])
            self.assertEqual(client.get(remotes + '/requests/configure-request').status_code, 404)

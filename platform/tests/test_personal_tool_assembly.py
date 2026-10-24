"""Static core/deployment assembly with an inert adapter and disposable PostgreSQL.

These tests exercise installed routes and native owner authorization. They never
start a CLI, connect to an MCP server, or call a model.
"""
from dataclasses import fields, replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.connections import ConnectionService
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration
from agent_factory.main import create_app as create_core_app
from agent_factory.personal_remote_provider import origin
from agent_factory.personal_tool_contract import ToolDescriptor
from agent_factory_research.config import ResearchSettings
from agent_factory_research.connections_compatibility import ResearchConnectionService
from agent_factory_server.main import create_app as create_research_app, factory_state
from pg_fixture import IsolatedPostgres  # pyright: ignore[reportMissingImports]


class InertAdapter:
    def __init__(self):
        self.descriptor = ToolDescriptor(
            adapter_id='fixture.personal.inventory', revision='fixture-v1',
            tool_name='personal_inventory', description='Synthetic inventory metadata.',
            input_schema={'type': 'object', 'properties': {}, 'additionalProperties': False},
            transport='cli', credential_provider_id='fixture.inventory',
            credential_destination='https://inventory.example.com',
            capabilities=('inventory:read',), permission='inventory:read', read_only=True)
        self.calls = []

    async def invoke(self, invocation):
        self.calls.append(invocation.call_id)
        raise AssertionError('Assembly must not dispatch a personal tool')


class PersonalToolSettingsTests(unittest.TestCase):
    def test_adapter_registration_survives_core_to_research_reconstruction(self):
        adapter = InertAdapter()
        settings = Settings(db_url='postgresql://unused', personal_tool_adapters=(adapter,))
        research = ResearchSettings(**{field.name: getattr(settings, field.name) for field in fields(Settings)})
        reconstructed = replace(research)
        for configured in (settings, research, reconstructed):
            self.assertEqual(len(configured.runtime_adapters), 1)
            self.assertIs(configured.runtime_adapters[0], settings.runtime_adapters[0])
            installed = configured.runtime_adapters[0]
            self.assertEqual((installed.tool_name, installed.permissions),
                             ('personal_inventory', ('inventory:read',)))
        self.assertEqual(adapter.calls, [])

    def test_existing_operator_registration_is_preserved(self):
        adapter = InertAdapter()
        entry = AdapterRegistration('tool', 'fixture.existing', 'existing-v1', lambda _: None,
                                    tool_name='existing_tool', permissions=('existing:read',))
        settings = Settings(db_url='postgresql://unused', personal_tool_adapters=(adapter,),
                            runtime_adapters=[entry])
        self.assertIs(settings.runtime_adapters[0], entry)
        self.assertEqual(len(settings.runtime_adapters), 2)

    def test_conflicting_adapter_cannot_replace_an_installed_identity(self):
        adapter = InertAdapter()
        settings = Settings(db_url='postgresql://unused', personal_tool_adapters=(adapter,))
        with self.assertRaises(ValueError):
            replace(settings, personal_tool_adapters=(InertAdapter(),))
        with self.assertRaises(ValueError):
            Settings(db_url='postgresql://unused', personal_tool_adapters=(adapter, adapter))
        self.assertEqual(len(settings.runtime_adapters), 1)
        self.assertEqual(adapter.calls, [])


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class PersonalToolAssemblyPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.adapter = InertAdapter()
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.folder.name), max_workers=1,
            temporary_policy='member-self-service', personal_tool_adapters=(self.adapter,),
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b'a' * 32,
                {self.adapter.descriptor.credential_provider_id: origin}))

    def app(self, create_app):
        app = create_app(self.settings)
        state = factory_state(app)
        self.addCleanup(state['store'].engine.dispose)
        self.addCleanup(state['store'].native_db.db_engine.dispose)
        return app, state

    def request(self, client, method, path, body=None, *, expected=200, headers=None):
        response = client.request(method, '/api/factory' + path, json=body, headers=headers)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def login(self, client, owner='alice'):
        client.cookies.clear()
        self.request(client, 'POST', '/demo/login', {'persona': owner})

    def exercise(self, create_app, connection_type):
        app, state = self.app(create_app)
        store, connections = state['store'], state['connections']
        self.assertIs(type(connections), connection_type)
        self.assertIs(connections.personal_tools, store.personal_tools)
        self.assertIs(store.personal_tools.connections, connections)
        installed = [entry for entry in state['execution_bindings'].describe()
                     if entry['adapterId'] == self.adapter.descriptor.adapter_id]
        self.assertEqual(len(installed), 1)
        self.assertEqual(installed[0]['connectionKind'], 'tool')
        with TestClient(app) as client:
            for path in ('/personal-tools', '/personal-tools/descriptors'):
                self.request(client, 'GET', path, expected=401)
            self.login(client)
            descriptors = self.request(client, 'GET', '/personal-tools/descriptors')
            self.assertEqual([entry['adapterId'] for entry in descriptors], [self.adapter.descriptor.adapter_id])
            self.request(client, 'GET', '/personal-tools', expected=403,
                         headers={'X-Factory-Expected-Owner': 'bob'})
            credential = self.request(client, 'POST', '/personal-credentials', {
                'providerId': self.adapter.descriptor.credential_provider_id,
                'destination': self.adapter.descriptor.credential_destination,
                'username': 'fixture-user', 'password': 'synthetic-assembly-secret',
                'requestId': 'assembly-credential'}, expected=201)
            intent = {'adapterId': self.adapter.descriptor.adapter_id,
                'credentialRef': credential['credentialRef'],
                'credentialRevision': credential['credentialRevision'], 'requestId': 'assembly-configure'}
            configured = self.request(client, 'POST', '/personal-tools', intent, expected=201)
            self.assertEqual(configured['status'], 'configured')
            self.assertEqual(self.request(client, 'POST', '/personal-tools', intent, expected=201), configured)
            registration = configured['registrationRef']
            registrations = self.request(client, 'GET', '/user-connections/registrations')
            self.assertIn(registration, [entry['registrationRef'] for entry in registrations])
            bound = self.request(client, 'POST', '/user-connections', {
                'registrationRef': registration, 'requestId': 'assembly-bind'}, expected=201)
            handle = connections.resolve('alice', bound['ref'], 'tool',
                expected_revision=bound['revision'], expected_fingerprint=bound['fingerprint'],
                expected_version=bound['version'], expected_adapter_ref=self.adapter.descriptor.adapter_id,
                required_capabilities=self.adapter.descriptor.capabilities)
            handle.check_authorized()
            self.assertEqual(handle.resolve_credential().password, 'synthetic-assembly-secret')
            self.login(client, 'bob')
            self.assertEqual(self.request(client, 'GET', '/personal-tools'), [])
            self.request(client, 'GET', '/personal-tools/' + registration, expected=404)
            self.request(client, 'POST', '/personal-tools', intent, expected=403)
            self.request(client, 'POST', '/user-connections', {
                'registrationRef': registration, 'requestId': 'bob-bind'}, expected=404)
            self.login(client)
            self.request(client, 'POST', '/user-connections/' + bound['ref'] + '/revoke',
                         {'requestId': 'assembly-unbind'})
            with self.assertRaises(HTTPException) as denied:
                handle.resolve_credential()
            self.assertEqual(denied.exception.status_code, 409)
            self.assertIn('CONNECTION_REVOKED', str(denied.exception.detail))
            retained = self.request(client, 'GET', '/personal-tools/requests/assembly-configure')
            self.assertEqual(retained['tool']['registrationRef'], registration)
            public = json.dumps([descriptors, configured, registrations, bound, retained])
            self.assertNotIn('synthetic-assembly-secret', public)
            self.assertEqual(self.adapter.calls, [])
        # Deployment reconstructs Core Settings as ResearchSettings. Starting
        # again must preserve the exact registration and existing owner data.
        restarted, restarted_state = self.app(create_app)
        with TestClient(restarted) as client:
            self.login(client)
            self.assertEqual(self.request(client, 'GET', '/personal-tools/requests/assembly-configure'), retained)
            self.assertEqual(self.request(client, 'POST', '/personal-tools', intent, expected=201), configured)
            self.assertEqual(self.request(client, 'GET', '/user-connections/' + bound['ref'])['status'], 'revoked')
        self.assertEqual(len(self.settings.runtime_adapters), 1)
        self.assertEqual(len(restarted_state['settings'].runtime_adapters), 1)
        self.assertEqual(self.adapter.calls, [])

    def test_core_lifecycle_owner_registration_and_retained_handle_recheck(self):
        self.exercise(create_core_app, ConnectionService)

    def test_research_override_preserves_core_personal_tool_assembly(self):
        self.exercise(create_research_app, ResearchConnectionService)

    def exercise_binding_error_envelopes(self, create_app):
        configured = {}
        intents = {}
        credentials = {}
        app, _ = self.app(create_app)
        with TestClient(app) as client:
            self.login(client)
            for case in ('rotated', 'credential-revoked', 'tool-revoked', 'unavailable', 'changed'):
                credential = self.request(client, 'POST', '/personal-credentials', {
                    'providerId': self.adapter.descriptor.credential_provider_id,
                    'destination': self.adapter.descriptor.credential_destination,
                    'username': 'fixture-user', 'password': 'synthetic-envelope-secret',
                    'requestId': 'credential-' + case}, expected=201)
                credentials[case] = credential
                intents[case] = {'adapterId': self.adapter.descriptor.adapter_id,
                    'credentialRef': credential['credentialRef'],
                    'credentialRevision': credential['credentialRevision'], 'requestId': 'configure-' + case}
                configured[case] = self.request(client, 'POST', '/personal-tools', intents[case], expected=201)
            credential = credentials['rotated']
            rotated = self.request(client, 'POST', '/personal-credentials/' + credential['credentialRef'] + '/rotate', {
                'credentialRevision': credential['credentialRevision'], 'username': 'fixture-user',
                'password': 'synthetic-envelope-rotated', 'requestId': 'rotate-credential'})
            self.assertNotEqual(rotated['credentialRevision'], credential['credentialRevision'])
            credential = credentials['credential-revoked']
            self.request(client, 'POST', '/personal-credentials/' + credential['credentialRef'] + '/revoke', {
                'credentialRevision': credential['credentialRevision'], 'requestId': 'revoke-credential'})
            self.request(client, 'POST', '/personal-tools/' + configured['tool-revoked']['registrationRef'] + '/revoke',
                {'requestId': 'revoke-tool'})
            for case, code, status in (
                ('rotated', 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE', 'credential_unavailable'),
                ('credential-revoked', 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE', 'credential_unavailable'),
                ('tool-revoked', 'PERSONAL_TOOL_REVOKED', 'revoked'),
            ):
                with self.subTest(case=case):
                    self.assert_binding_error(client, configured[case], intents[case], code, status)

        # Operator configuration changes take effect through normal app restart;
        # no service registry, database record or HTTP response is patched.
        original_settings = self.settings
        changed_adapter = InertAdapter()
        changed_adapter.descriptor = replace(changed_adapter.descriptor, description='Changed static descriptor')
        for case, adapters, code, status in (
            ('unavailable', (), 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE', 'unavailable'),
            ('changed', (changed_adapter,), 'PERSONAL_TOOL_ADAPTER_CHANGED', 'adapter_changed'),
        ):
            with self.subTest(case=case):
                self.settings = replace(original_settings, personal_tool_adapters=adapters,
                    runtime_adapters=[] if adapters else original_settings.runtime_adapters)
                restarted, _ = self.app(create_app)
                with TestClient(restarted) as client:
                    self.login(client)
                    self.assert_binding_error(client, configured[case], intents[case], code, status)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(changed_adapter.calls, [])

    def assert_binding_error(self, client, original, intent, code, status):
        registration = original['registrationRef']
        request_id = 'bind-' + intent['requestId']
        for _ in range(2):
            denied = self.request(client, 'POST', '/user-connections', {
                'registrationRef': registration, 'requestId': request_id}, expected=409)
            self.assertEqual(denied, {'code': code, 'message': code})
            self.request(client, 'GET', '/user-connections/requests/' + request_id, expected=404)
            self.request(client, 'GET', '/personal-tools/requests/' + request_id, expected=404)
        self.assertEqual(self.request(client, 'GET', '/user-connections'), [])
        current = self.request(client, 'GET', '/personal-tools/' + registration)
        self.assertEqual(current['status'], status)
        self.assertFalse(current['available'])
        self.assertEqual(current['allowedActions'],
                         ['inspect'] if status == 'revoked' else ['inspect', 'revoke', 'sharing'])
        for key in ('registrationRef', 'ownerId', 'adapterId', 'revision', 'descriptorRevision',
                    'credentialRef', 'credentialRevision', 'createdAt'):
            self.assertEqual(current[key], original[key])
        retained = self.request(client, 'GET', '/personal-tools/requests/' + intent['requestId'])
        self.assertEqual(retained, {'requestId': intent['requestId'], 'action': 'tool.configure', 'tool': current})
        self.assertEqual(self.request(client, 'POST', '/personal-tools', intent, expected=201), current)
        registrations = self.request(client, 'GET', '/user-connections/registrations')
        projected = next(item for item in registrations if item['registrationRef'] == registration)
        self.assertFalse(projected['available'])
        self.assertEqual(projected['allowedActions'], ['inspect'])

    def test_core_binding_rejections_keep_fixed_http_codes_and_original_configure_receipts(self):
        self.exercise_binding_error_envelopes(create_core_app)

    def test_research_binding_rejections_keep_fixed_http_codes_and_original_configure_receipts(self):
        self.exercise_binding_error_envelopes(create_research_app)

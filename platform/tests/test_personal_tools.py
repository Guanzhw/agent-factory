"""Owner tool custody with real encrypted SQLite credentials; no adapter IO."""
from contextvars import ContextVar
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, inspect, select
from sqlalchemy.pool import StaticPool

from agent_factory.connections import ConnectionService, TrustedConnectionBinding
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.personal_remote_provider import origin
from agent_factory.personal_tool_contract import ToolDescriptor
from agent_factory.personal_tools import PersonalTools, personal_tool_router
from test_personal_remote_connections import Auth

PROVIDER = 'synthetic-tool-credential'
DESTINATION = 'https://tool.example.com'
USERNAME = 'synthetic-personal-tool-user'
PASSWORD = 'synthetic-personal-tool-password-only'
CAPABILITY = 'tool:synthetic-read'
ROOT = '/api/factory/personal-tools'


def descriptor(**changes):
    value = ToolDescriptor(adapter_id='synthetic-personal-tool-v1', revision='1',
        tool_name='synthetic_personal_lookup', description='Offline synthetic owner tool fixture',
        input_schema={'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 256}},
                      'required': ['query'], 'additionalProperties': False},
        transport='cli', credential_provider_id=PROVIDER, credential_destination=DESTINATION,
        capabilities=(CAPABILITY,), permission=CAPABILITY, read_only=True)
    return replace(value, **changes)


def adapter(**changes):
    return SimpleNamespace(descriptor=descriptor(**changes),
        invoke=AsyncMock(side_effect=AssertionError('Configuration must never invoke an adapter')))


class PersonalToolTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        Table('af_audit', metadata, Column('id', Integer, primary_key=True), Column('actor_id', String),
            Column('action', String), Column('target_id', String), Column('body', JSON), Column('created_at', String))
        metadata.create_all(self.engine)
        self.store = SimpleNamespace(engine=self.engine, _connection=ContextVar('tool-fixture-connection', default=None))
        self.auth = Auth()
        self.connections = ConnectionService(self.store, self.auth)
        self.vault = EncryptedCredentialVault(self.engine, b't' * 32, {PROVIDER: origin, 'other-tool-purpose': origin})
        self.vault.bind_read_context(self.store._connection)
        self.adapter = adapter()
        self.service = PersonalTools(self.connections, self.vault, (self.adapter,))
        self.credential = self.create_credential()
        self.app = FastAPI()
        self.app.include_router(personal_tool_router(self.auth, self.service))
        self.client = self.enterContext(TestClient(self.app))
        self.headers = {'x-fixture-owner': 'alice'}

    def create_credential(self, *, owner='alice', provider=PROVIDER, destination=DESTINATION, password=PASSWORD):
        return self.vault.create(owner=owner, provider_id=provider, destination=destination,
            username=USERNAME, password=password)

    def configure(self, *, owner='alice', credential=None, request_id='configure-tool', service=None):
        value = self.credential if credential is None else credential
        return (service or self.service).configure(owner, self.adapter.descriptor.adapter_id,
            value['credentialRef'], value['credentialRevision'], request_id)

    def binding(self, row, *, owner='alice', service=None):
        with self.connections._read() as conn:
            return (service or self.service).binding(conn, owner, row['registrationRef'])

    def body(self, **changes):
        return {'adapterId': self.adapter.descriptor.adapter_id,
            'credentialRef': self.credential['credentialRef'],
            'credentialRevision': self.credential['credentialRevision'], 'requestId': 'http-configure', **changes}

    def test_configure_describe_list_and_binding_authorize_without_resolving_or_invoking(self):
        with patch.object(self.vault, 'authorize', wraps=self.vault.authorize) as authorize, \
                patch.object(self.vault, 'resolve', side_effect=AssertionError('No secret resolution during setup')):
            row = self.configure()
            descriptions = self.service.describe('alice')
            self.assertEqual(self.service.list('alice'), [row])
            bound = self.binding(row)
            bound.opaque_handle.check_authorized()
        self.assertTrue(authorize.called)
        expected = {'owner': 'alice', 'reference': self.credential['credentialRef'],
            'revision': self.credential['credentialRevision'], 'provider_id': PROVIDER, 'destination': DESTINATION}
        self.assertTrue(all(call.kwargs == expected for call in authorize.call_args_list))
        self.assertEqual(row['status'], 'configured')
        for key, value in {'kind': 'tool', 'adapterId': self.adapter.descriptor.adapter_id,
                'descriptorRevision': '1', 'toolName': self.adapter.descriptor.tool_name, 'transport': 'cli',
                'credentialRef': self.credential['credentialRef'],
                'credentialRevision': self.credential['credentialRevision'],
                'capabilities': [CAPABILITY], 'expiresAt': None}.items():
            self.assertEqual(row[key], value)
        self.assertTrue(row['createdAt'])
        self.assertTrue(row['revision'])
        self.assertIn('bind', row['allowedActions'])
        self.assertIn('revoke', row['allowedActions'])
        self.assertIsInstance(bound, TrustedConnectionBinding)
        self.assertEqual((bound.owner, bound.kind, bound.adapter_ref, bound.revision),
            ('alice', 'tool', self.adapter.descriptor.adapter_id, row['revision']))
        self.assertEqual(bound.capabilities, frozenset({CAPABILITY}))
        self.assertTrue(bound.available)
        self.assertIs(bound.opaque_handle.adapter, self.adapter)
        self.assertIs(bound.opaque_handle.service, self.service)
        self.assertEqual(len(descriptions), 1)
        self.assertEqual(descriptions[0]['adapterId'], row['adapterId'])
        self.assertEqual(descriptions[0]['toolName'], row['toolName'])
        self.assertNotIn('credentialRef', descriptions[0])
        self.adapter.invoke.assert_not_called()

    def test_exact_owner_reference_revision_purpose_and_destination_are_required(self):
        invalid = [self.create_credential(owner='bob'),
            self.create_credential(provider='other-tool-purpose'),
            self.create_credential(destination='https://other.example.com'),
            self.credential | {'credentialRef': 'synthetic-missing-reference'},
            self.credential | {'credentialRevision': 'synthetic-stale-revision'}]
        with patch.object(self.vault, 'resolve', side_effect=AssertionError('Denied setup must not resolve')):
            for index, value in enumerate(invalid):
                with self.subTest(scope=index), self.assertRaises(HTTPException):
                    self.configure(credential=value, request_id='bad-scope-' + str(index))
            with self.assertRaises(HTTPException):
                self.configure(owner='bob')
        self.assertEqual(self.service.list('alice'), [])
        self.assertEqual(self.service.list('bob'), [])
        self.adapter.invoke.assert_not_called()

    def test_duplicate_request_restarts_recover_original_registration_and_conflicting_intent_fails(self):
        first = self.configure()
        self.assertEqual(self.configure(), first)
        reopened = PersonalTools(ConnectionService(self.store, self.auth), self.vault, (self.adapter,))
        self.assertEqual(self.configure(service=reopened), first)
        recovered = reopened.request_result('alice', 'configure-tool')
        self.assertEqual(recovered, {'requestId': 'configure-tool', 'action': 'tool.configure', 'tool': first})
        second = self.create_credential(password='synthetic-second-password')
        with self.assertRaises(HTTPException):
            self.configure(credential=second, service=reopened)
        self.assertEqual(reopened.list('alice'), [first])
        with self.assertRaises(HTTPException) as foreign:
            reopened.request_result('bob', 'configure-tool')
        self.assertEqual(foreign.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            reopened.request_result('alice', 'missing-request')
        self.adapter.invoke.assert_not_called()

    def test_revoke_replay_and_recovery_preserve_current_state_and_original_revision(self):
        original = self.configure()
        handle = self.binding(original).opaque_handle
        revoked = self.service.revoke('alice', original['registrationRef'], 'revoke-tool')
        self.assertEqual(revoked['status'], 'revoked')
        self.assertEqual(revoked['revision'], original['revision'])
        self.assertNotIn('bind', revoked['allowedActions'])
        self.assertEqual(self.service.revoke('alice', original['registrationRef'], 'revoke-tool'), revoked)
        self.assertEqual(self.configure(), revoked)
        self.assertEqual(self.service.request_result('alice', 'configure-tool')['tool'], revoked)
        self.assertEqual(self.service.request_result('alice', 'revoke-tool'),
            {'requestId': 'revoke-tool', 'action': 'tool.revoke', 'tool': revoked})
        with self.assertRaises(HTTPException):
            self.binding(original)
        with self.assertRaises(HTTPException):
            handle.check_authorized()
        with patch.object(self.vault, 'resolve', wraps=self.vault.resolve) as resolve:
            with self.assertRaises(HTTPException):
                handle.resolve_credential()
            resolve.assert_not_called()
        self.assertEqual(len(self.service.list('alice')), 1)

    def test_foreign_owner_cannot_bind_revoke_or_recover_and_equal_request_ids_are_isolated(self):
        alice = self.configure()
        bob_credential = self.create_credential(owner='bob', password='synthetic-bob-password')
        bob = self.configure(owner='bob', credential=bob_credential)
        self.assertNotEqual(alice['registrationRef'], bob['registrationRef'])
        self.assertEqual(self.service.list('alice'), [alice])
        self.assertEqual(self.service.list('bob'), [bob])
        for operation in (lambda: self.binding(alice, owner='bob'),
                          lambda: self.service.revoke('bob', alice['registrationRef'], 'foreign-revoke')):
            with self.assertRaises(HTTPException) as caught:
                operation()
            self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.service.request_result('bob', 'configure-tool')['tool'], bob)
        self.assertEqual(self.binding(alice).opaque_handle.resolve_credential().password, PASSWORD)
        self.assertEqual(self.binding(bob, owner='bob').opaque_handle.resolve_credential().password, 'synthetic-bob-password')

    def test_retained_handle_rechecks_current_credential_rotation_without_retargeting(self):
        row = self.configure()
        handle = self.binding(row).opaque_handle
        with patch.object(self.vault, 'resolve', wraps=self.vault.resolve) as resolve:
            self.assertEqual(handle.resolve_credential().password, PASSWORD)
            resolve.assert_called_once_with(owner='alice', reference=self.credential['credentialRef'],
                revision=self.credential['credentialRevision'], provider_id=PROVIDER, destination=DESTINATION)
        changed = self.vault.rotate(owner='alice', reference=self.credential['credentialRef'],
            revision=self.credential['credentialRevision'], username=USERNAME, password='synthetic-rotated-password')
        current = self.service.list('alice')[0]
        self.assertEqual(current['status'], 'credential_unavailable')
        self.assertEqual(current['credentialRevision'], self.credential['credentialRevision'])
        self.assertEqual(current['revision'], row['revision'])
        self.assertNotIn('bind', current['allowedActions'])
        with patch.object(self.vault, 'resolve', wraps=self.vault.resolve) as resolve:
            with self.assertRaises(HTTPException):
                handle.resolve_credential()
            resolve.assert_not_called()
        with self.assertRaises(HTTPException):
            self.binding(row)
        fresh = self.configure(credential=changed, request_id='configure-rotated')
        self.assertNotEqual(fresh['registrationRef'], row['registrationRef'])
        self.assertEqual(self.binding(fresh).opaque_handle.resolve_credential().password, 'synthetic-rotated-password')
        self.assertEqual(self.service.request_result('alice', 'configure-tool')['tool']['registrationRef'], row['registrationRef'])

    def test_revoked_credential_and_removed_vault_never_use_an_ambient_secret(self):
        row = self.configure()
        handle = self.binding(row).opaque_handle
        self.vault.revoke(owner='alice', reference=self.credential['credentialRef'], revision=self.credential['credentialRevision'])
        self.assertEqual(self.service.list('alice')[0]['status'], 'credential_unavailable')
        with self.assertRaises(HTTPException):
            handle.resolve_credential()
        disabled = PersonalTools(self.connections, None, (self.adapter,))
        with patch.dict('os.environ', {'API_KEY': PASSWORD, 'TOOL_API_KEY': PASSWORD, 'OPENAI_API_KEY': PASSWORD}):
            with self.assertRaises(HTTPException):
                self.configure(service=disabled, request_id='disabled-vault')
            with self.assertRaises(HTTPException):
                self.binding(row, service=disabled)
        self.assertEqual(disabled.list('alice')[0]['status'], 'credential_unavailable')
        self.adapter.invoke.assert_not_called()

    def test_adapter_removal_and_exact_descriptor_drift_invalidate_existing_configuration(self):
        row = self.configure()
        removed = PersonalTools(self.connections, self.vault, ())
        self.assertEqual(removed.list('alice')[0]['status'], 'unavailable')
        with self.assertRaises(HTTPException):
            self.binding(row, service=removed)
        changes = ({'revision': '2'}, {'tool_name': 'changed_tool'}, {'transport': 'mcp'},
            {'credential_provider_id': 'other-tool-purpose'}, {'credential_destination': 'https://other.example.com'},
            {'capabilities': ('tool:different',)}, {'permission': 'tool:different'}, {'read_only': False},
            {'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, {'timeout_seconds': 3.0}, {'max_output_bytes': 2048})
        for fields in changes:
            with self.subTest(fields=fields):
                changed = PersonalTools(self.connections, self.vault, (adapter(**fields),))
                current = changed.list('alice')[0]
                self.assertEqual(current['status'], 'adapter_changed')
                self.assertEqual(current['revision'], row['revision'])
                self.assertNotIn('bind', current['allowedActions'])
                with self.assertRaises(HTTPException):
                    self.binding(row, service=changed)

    def test_retained_handle_checks_live_adapter_descriptor_and_immutable_configuration(self):
        row = self.configure()
        handle = self.binding(row).opaque_handle
        self.assertEqual(handle.owner, 'alice')
        self.assertEqual(handle.configuration['registrationRef'], row['registrationRef'])
        with self.assertRaises(TypeError):
            handle.configuration['credentialRevision'] = 'different'
        self.service.adapters[self.adapter.descriptor.adapter_id] = adapter(revision='2')
        with self.assertRaises(HTTPException):
            handle.check_authorized()
        with self.assertRaises(HTTPException):
            handle.resolve_credential()

    def test_in_place_schema_drift_denies_retained_handle_before_secret_resolution(self):
        row = self.configure()
        handle = self.binding(row).opaque_handle
        self.adapter.descriptor.input_schema['properties']['query']['maxLength'] = 128
        self.assertEqual(self.service.list('alice')[0]['status'], 'adapter_changed')
        self.assertEqual(self.service.list('alice')[0]['revision'], row['revision'])
        with patch.object(self.vault, 'resolve', wraps=self.vault.resolve) as resolve:
            with self.assertRaises(HTTPException):
                handle.resolve_credential()
            with self.assertRaises(HTTPException):
                self.binding(row)
            resolve.assert_not_called()
        self.adapter.invoke.assert_not_called()

    def test_equal_python_values_cannot_replace_exact_json_schema_types(self):
        self.adapter.descriptor = descriptor(input_schema={'type': 'object',
            'properties': {'value': {'type': 'integer', 'enum': [1]}},
            'required': ['value'], 'additionalProperties': False})
        row = self.configure()
        handle = self.binding(row).opaque_handle
        with patch.object(self.vault, 'resolve', wraps=self.vault.resolve) as resolve:
            # Python considers True == 1 == 1.0, but these are different JSON contracts.
            for changed in (True, 1.0):
                with self.subTest(location='adapter', value=repr(changed)):
                    self.adapter.descriptor.input_schema['properties']['value']['enum'][0] = changed
                    self.assertEqual(self.service.list('alice')[0]['status'], 'adapter_changed')
                    with self.assertRaises(HTTPException):
                        handle.resolve_credential()
                    with self.assertRaises(HTTPException):
                        self.binding(row)
            self.adapter.descriptor.input_schema['properties']['value']['enum'][0] = 1
            self.assertEqual(self.service.list('alice')[0]['status'], 'configured')
            for changed in (True, 1.0):
                with self.subTest(location='retained-handle', value=repr(changed)):
                    handle.configuration['descriptor']['inputSchema']['properties']['value']['enum'][0] = changed
                    with self.assertRaises(HTTPException):
                        handle.resolve_credential()
            resolve.assert_not_called()
        self.adapter.invoke.assert_not_called()

    def test_chained_guards_retain_original_connection_authority_before_secret_resolution(self):
        handle = self.binding(self.configure()).opaque_handle
        first, second = Mock(), Mock()
        guarded = handle.guarded(first).guarded(second)
        self.assertEqual(guarded.resolve_credential().password, PASSWORD)
        self.assertTrue(first.called)
        self.assertTrue(second.called)
        for guard in (first, second):
            self.assertTrue(all(call.args == ((CAPABILITY,),) for call in guard.call_args_list))
        first.side_effect = HTTPException(403, 'synthetic-connection-revoked')
        with patch.object(self.vault, 'resolve', wraps=self.vault.resolve) as resolve:
            with self.assertRaises(HTTPException):
                guarded.resolve_credential()
            resolve.assert_not_called()

    def test_current_membership_allows_configuration_and_disabled_member_denies_retained_handle(self):
        row = self.configure()
        handle = self.binding(row).opaque_handle
        self.auth.reader = True
        self.assertIn('bind', self.service.list('alice')[0]['allowedActions'])
        self.assertEqual(self.configure(request_id='reader-configure')['status'], 'configured')
        self.assertEqual(handle.resolve_credential().password, PASSWORD)
        self.auth.disabled = True
        with patch.object(self.vault, 'resolve', wraps=self.vault.resolve) as resolve:
            with self.assertRaises(HTTPException):
                handle.resolve_credential()
            resolve.assert_not_called()
        for operation in (lambda: self.service.list('alice'), lambda: self.service.describe('alice'),
                          lambda: self.service.request_result('alice', 'configure-tool'),
                          lambda: self.configure(request_id='disabled-configure'),
                          lambda: self.service.revoke('alice', row['registrationRef'], 'disabled-revoke')):
            with self.assertRaises(HTTPException) as denied:
                operation()
            self.assertEqual(denied.exception.status_code, 403)

    def test_all_persisted_tables_and_public_representations_exclude_secret_values(self):
        row = self.configure()
        bound = self.binding(row)
        lease = bound.opaque_handle.resolve_credential()
        recovered = self.service.request_result('alice', 'configure-tool')
        reflected = MetaData()
        reflected.reflect(bind=self.engine)
        with self.engine.connect() as conn:
            persisted = {name: [dict(item) for item in conn.execute(select(table)).mappings()]
                for name, table in reflected.tables.items()}
        self.assertIn('af_encrypted_credentials', persisted)
        self.assertIn('af_personal_tools', persisted)
        self.assertTrue(persisted['af_encrypted_credentials'][0]['ciphertext'])
        for value in (persisted, row, recovered, bound, bound.opaque_handle, self.service, self.vault, lease):
            with self.subTest(kind=type(value).__name__):
                self.assertNotIn(PASSWORD, repr(value))
                self.assertNotIn(USERNAME, repr(value))
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(reflected.tables))

    def test_http_owner_scope_configuration_request_recovery_and_revoke(self):
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        configured = self.client.post(ROOT, headers=self.headers, json=self.body())
        self.assertEqual(configured.status_code, 201, configured.text)
        row = configured.json()
        self.assertEqual(row['status'], 'configured')
        self.assertEqual(self.client.get(ROOT, headers=self.headers).json(), [row])
        self.assertEqual(self.client.get(ROOT, headers={'x-fixture-owner': 'bob'}).json(), [])
        recovered = self.client.get(ROOT + '/requests/http-configure', headers=self.headers)
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()['tool'], row)
        self.assertEqual(self.client.get(ROOT + '/requests/http-configure', headers={'x-fixture-owner': 'bob'}).status_code, 404)
        description = self.client.get(ROOT + '/descriptors', headers=self.headers)
        self.assertEqual(description.status_code, 200, description.text)
        self.assertEqual(description.json(), self.service.describe('alice'))
        path = ROOT + '/' + row['registrationRef'] + '/revoke'
        self.assertEqual(self.client.post(path, headers={'x-fixture-owner': 'bob'}, json={'requestId': 'foreign'}).status_code, 404)
        revoked = self.client.post(path, headers=self.headers, json={'requestId': 'http-revoke'})
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()['status'], 'revoked')
        self.assertEqual(self.client.post(ROOT, headers=self.headers, json=self.body()).json()['status'], 'revoked')
        self.adapter.invoke.assert_not_called()

    def test_http_rejects_secret_owner_endpoint_and_process_arguments_without_echo(self):
        forbidden = ({'password': PASSWORD}, {'ownerId': PASSWORD}, {'command': PASSWORD}, {'argv': [PASSWORD]},
            {'endpoint': PASSWORD}, {'credentialRef': {'password': PASSWORD}}, {'adapterId': [PASSWORD]},
            {'requestId': PASSWORD * 500})
        with patch.object(self.vault, 'resolve', side_effect=AssertionError('Bad HTTP must not resolve')):
            for values in forbidden:
                with self.subTest(fields=list(values)):
                    response = self.client.post(ROOT, headers=self.headers, json=self.body(**values))
                    self.assertIn(response.status_code, {400, 422})
                    self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.service.list('alice'), [])
        self.adapter.invoke.assert_not_called()

    def test_http_malformed_oversized_and_invalid_duplicate_values_are_redacted(self):
        valid = json.dumps(self.body())
        for raw in ('{"password":"' + PASSWORD, valid[:-1] + ',"adapterId":"' + PASSWORD + '"}',
                    PASSWORD * 4000):
            with self.subTest(length=len(raw)):
                response = self.client.post(ROOT, headers=self.headers | {'content-type': 'application/json'}, content=raw)
                self.assertIn(response.status_code, {400, 422})
                self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.service.list('alice'), [])

    def test_credential_backend_failures_are_redacted_at_the_secret_boundary(self):
        for failure in (RuntimeError(PASSWORD), HTTPException(503, PASSWORD)):
            with self.subTest(kind=type(failure).__name__), patch.object(self.vault, 'authorize', side_effect=failure):
                response = self.client.post(ROOT, headers=self.headers, json=self.body())
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {'detail': 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE'})
                self.assertNotIn(PASSWORD, response.text)
        row = self.configure()
        handle = self.binding(row).opaque_handle
        with patch.object(self.vault, 'resolve', side_effect=RuntimeError(PASSWORD)):
            with self.assertRaises(HTTPException) as denied:
                handle.resolve_credential()
            self.assertEqual(denied.exception.status_code, 409)
            self.assertEqual(denied.exception.detail, 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE')
            recovered = self.client.get(ROOT + '/requests/configure-tool', headers=self.headers)
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()['tool'], row)
            self.assertNotIn(PASSWORD, recovered.text)

    def test_tool_request_recovery_cannot_read_other_connection_action_receipts(self):
        row = self.configure()
        self.connections.personal_tools = self.service
        bound = self.connections.bind('alice', row['registrationRef'], 'bind-tool', capabilities=[CAPABILITY])
        self.assertEqual(self.connections.request_result('alice', 'bind-tool')['connection']['ref'], bound['ref'])
        with self.assertRaises(HTTPException) as other_action:
            self.service.request_result('alice', 'bind-tool')
        self.assertEqual(other_action.exception.status_code, 404)
        with self.assertRaises(HTTPException) as other_action:
            self.connections.request_result('alice', 'configure-tool')
        self.assertEqual(other_action.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            self.service.revoke('alice', row['registrationRef'], 'configure-tool')
        self.assertEqual(self.service.list('alice'), [row])


if __name__ == '__main__':
    unittest.main()

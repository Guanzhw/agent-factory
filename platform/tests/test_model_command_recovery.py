"""Synthetic command-receipt regressions for the real owner model service.

Owned SQLite follows the portable metadata test convention. PersonalModels,
GovernedStorage, ConnectionService and HTTP routing are real; only identity and
credential metadata are fixtures. No credential value, model call, production
database or environment configuration is used. These sequential cases do not
prove PostgreSQL locking, concurrency, native execution or live compatibility.

Recovery and idempotent replay preserve the recorded command receipt independently
of the model's current projection.
"""
from contextvars import ContextVar
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, event, select

from agent_factory.byok_model import PROVIDER_ID
from agent_factory.connections import ConnectionService
from agent_factory.personal_models import PersonalModels, personal_model_router


class FixtureAuth:
    def __init__(self):
        self.denied = set()

    def user(self, request):
        owner = request.headers.get('x-fixture-owner')
        if owner not in {'alice', 'bob'}:
            raise HTTPException(401, 'SYNTHETIC_OWNER_REQUIRED')
        return {'id': owner}

    def require(self, owner, action):
        if owner not in {'alice', 'bob'} or (owner, action) in self.denied:
            raise HTTPException(403, 'SYNTHETIC_PERMISSION_DENIED')


class MetadataOnlyVault:
    """Exact synthetic scope checks; intentionally cannot provide a secret."""
    def __init__(self):
        self.unavailable = set()
        self.resolve_calls = 0

    def capabilities(self):
        return {'providerIds': [PROVIDER_ID]}

    def authorize(self, *, owner, reference, revision, provider_id, destination):
        return owner not in self.unavailable and (
            reference, revision, provider_id, destination
        ) == ('fixture-credential-' + owner, 'fixture-revision-v1', PROVIDER_ID, 'https://models.example.com')

    def resolve(self, **scope):
        self.resolve_calls += 1
        raise AssertionError('Metadata commands must never resolve credentials')


class ModelCommandRecoveryTests(unittest.TestCase):
    root = '/api/factory/personal-models'

    def make_engine(self):
        directory = TemporaryDirectory(prefix='model-command-recovery-')
        self.addCleanup(directory.cleanup)
        return create_engine('sqlite:///' + str(Path(directory.name) / 'owned-metadata.sqlite'))

    def setUp(self):
        self.engine = self.make_engine()
        self.addCleanup(self.engine.dispose)
        self.mutations = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}:
                self.mutations.append(statement)

        event.listen(self.engine, 'before_cursor_execute', observe)
        metadata = MetaData()
        self.audit = Table('af_audit', metadata, Column('id', Integer, primary_key=True),
            Column('actor_id', String), Column('action', String), Column('target_id', String),
            Column('body', JSON), Column('created_at', String))
        metadata.create_all(self.engine)
        store = SimpleNamespace(engine=self.engine, _connection=ContextVar('model-recovery-connection', default=None))
        self.auth, self.vault = FixtureAuth(), MetadataOnlyVault()
        self.connections = ConnectionService(store, self.auth)
        self.models = PersonalModels(store, self.auth, self.connections, self.vault,
            transport_factory=self.forbid_transport)
        self.connections.owner_models = self.models
        self.tables = (self.models.models, self.models.defaults, self.models.commands,
            self.connections.references, self.connections.versions, self.connections.commands, self.audit)
        app = FastAPI()
        app.include_router(personal_model_router(self.auth, self.models))
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def tearDown(self):
        self.assertEqual(self.vault.resolve_calls, 0)

    @staticmethod
    def forbid_transport():
        raise AssertionError('Metadata commands must never invoke a model transport')

    @staticmethod
    def configuration(owner='alice', model='fixture-model'):
        return {'provider': 'openai-compatible', 'baseURL': 'https://models.example.com/v1',
            'model': model, 'credentialRef': 'fixture-credential-' + owner,
            'credentialRevision': 'fixture-revision-v1'}

    def post(self, path, body, *, owner='alice', expected=200):
        response = self.client.post(self.root + path, json=body, headers={'x-fixture-owner': owner})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def get(self, path, *, owner='alice', expected=200):
        response = self.client.get(self.root + path, headers={'x-fixture-owner': owner})
        self.assertEqual(response.status_code, expected, response.text)
        if expected == 200:
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        return response.json()

    def configure(self, name, *, owner='alice', request_id=None):
        return self.post('', self.configuration(owner, name) | {
            'requestId': request_id or 'configure-' + owner + '-' + name}, owner=owner, expected=201)

    def set_default(self, model, request_id, *, owner='alice', expected=200):
        return self.post('/' + model['reference'] + '/default', {'requestId': request_id},
            owner=owner, expected=expected)

    def receipt(self, owner, request_id):
        # Independent persisted evidence to compare against the production API.
        with self.engine.connect() as conn:
            return conn.execute(select(self.models.commands.c.result).where(
                self.models.commands.c.actor_id == owner,
                self.models.commands.c.request_id == request_id)).scalar_one_or_none()

    def snapshot(self):
        with self.engine.connect() as conn:
            return {table.name: sorted(json.dumps(dict(row), sort_keys=True)
                for row in conn.execute(select(table)).mappings()) for table in self.tables}

    def assert_unchanged(self, before):
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations, [], 'Replay/rejection must not execute metadata mutations')

    def test_default_replay_recovers_original_receipt_after_another_default_command(self):
        first, second = self.configure('fixture-first'), self.configure('fixture-second')
        original = self.set_default(first, 'default-command-a')
        self.assertTrue(original['isDefault'])
        self.assertEqual(self.receipt('alice', 'default-command-a'), original)
        self.set_default(second, 'default-command-b')
        before = self.snapshot()
        self.mutations.clear()

        replay = self.set_default(first, 'default-command-a')

        self.assert_unchanged(before)
        self.assertEqual(self.models.default('alice')['reference'], second['reference'])
        self.assertEqual(self.receipt('alice', 'default-command-a'), original)
        self.assertEqual(replay, original,
            'Command A completed with isDefault=True. Its replay must recover that receipt; '
            'current default B is separate state and must remain unchanged.')
        receipt = self.get('/requests/default-command-a')
        self.assertEqual(set(receipt), {'ownerId', 'requestId', 'action', 'result', 'completedAt'})
        self.assertEqual(receipt['ownerId'], 'alice')
        self.assertEqual(receipt['requestId'], 'default-command-a')
        self.assertEqual(receipt['action'], 'model.default')
        self.assertEqual(receipt['result'], original)
        with self.engine.connect() as conn:
            completed_at = conn.execute(select(self.models.commands.c.created_at).where(
                self.models.commands.c.actor_id == 'alice',
                self.models.commands.c.request_id == 'default-command-a')).scalar_one()
        self.assertEqual(receipt['completedAt'], completed_at)
        self.assertEqual(self.get('/requests/default-command-a'), receipt)
        current = {model['reference']: model for model in self.get('')}
        self.assertFalse(current[first['reference']]['isDefault'])
        self.assertTrue(current[second['reference']]['isDefault'])
        self.assert_unchanged(before)

    def test_default_replay_without_intervening_change_is_read_only(self):
        model = self.configure('fixture-stable')
        original = self.set_default(model, 'stable-default-command')
        before = self.snapshot()
        self.mutations.clear()
        self.assertEqual(self.set_default(model, 'stable-default-command'), original)
        self.assertEqual(self.receipt('alice', 'stable-default-command'), original)
        self.assert_unchanged(before)

    def test_configure_replay_preserves_original_revision_after_reconfiguration(self):
        request_id = 'original-configure-command'
        original = self.configure('fixture-original', request_id=request_id)
        changed = self.post('/' + original['reference'] + '/configure',
            self.configuration(model='fixture-changed') | {'requestId': 'later-configure-command'})
        self.assertNotEqual(changed['revision'], original['revision'])
        before = self.snapshot()
        self.mutations.clear()

        replay = self.configure('fixture-original', request_id=request_id)

        self.assertEqual(replay, original)
        self.assertEqual(self.get('/requests/' + request_id)['result'], original)
        self.assertEqual(self.get(''), [changed])
        self.assert_unchanged(before)

    def test_omitted_and_explicit_chat_protocol_share_legacy_idempotency(self):
        for name, initial, retry in (
            ('omitted', {}, {'protocol': 'chat-completions'}),
            ('explicit', {'protocol': 'chat-completions'}, {}),
        ):
            with self.subTest(first=name):
                request_id = 'legacy-protocol-' + name
                values = self.configuration(model='fixture-' + name) | {'requestId': request_id}
                original = self.post('', values | initial, expected=201)
                self.assertNotIn('protocol', original)
                before = self.snapshot()
                self.mutations.clear()
                self.assertEqual(self.post('', values | retry, expected=201), original)
                self.assertEqual(self.get('/requests/' + request_id)['result'], original)
                self.assert_unchanged(before)

    def test_responses_protocol_is_persisted_and_change_of_protocol_conflicts(self):
        request_id = 'responses-protocol-command'
        values = self.configuration(model='fixture-responses') | {
            'protocol': 'responses', 'requestId': request_id}
        original = self.post('', values, expected=201)
        self.assertEqual(original['protocol'], 'responses')
        self.assertEqual(self.get(''), [original])
        before = self.snapshot()
        self.mutations.clear()
        self.assertEqual(self.post('', values, expected=201), original)
        self.assertEqual(self.get('/requests/' + request_id)['result'], original)
        failure = self.post('', values | {'protocol': 'chat-completions'}, expected=409)
        self.assertIn('IDEMPOTENCY_CONFLICT', failure['detail'])
        self.assert_unchanged(before)

    def test_invalid_or_explicit_null_protocol_is_rejected_before_any_write(self):
        for index, protocol in enumerate((None, 'unsupported-protocol', 42)):
            with self.subTest(protocol=protocol):
                request_id = 'invalid-protocol-command-' + str(index)
                values = self.configuration() | {'protocol': protocol}
                before = self.snapshot()
                self.mutations.clear()
                self.post('', values | {'requestId': request_id}, expected=422)
                with self.assertRaises(HTTPException) as failure:
                    self.models.configure('alice', values, request_id)
                self.assertEqual(failure.exception.status_code, 422)
                self.assertIsNone(self.receipt('alice', request_id))
                self.assert_unchanged(before)

    def test_capabilities_include_protocols_and_both_go_endpoints_without_invocation(self):
        before = self.snapshot()
        self.mutations.clear()
        capabilities = self.get('/capabilities')
        self.assertEqual(capabilities['protocols'], ['chat-completions', 'responses'])
        self.assertIn('https://opencode.ai/zen/go/v1', capabilities['additionalBaseURLs'])
        self.assertIn('https://opencode.ai/inference/go/v1', capabilities['additionalBaseURLs'])
        self.assertFalse(capabilities['liveCompatibilityVerified'])
        self.assert_unchanged(before)

    def test_revoke_replay_and_recovery_preserve_original_receipt_without_mutation(self):
        model = self.configure('fixture-revoked')
        path = '/' + model['reference'] + '/revoke'
        command = {'requestId': 'original-revoke-command'}
        original = self.post(path, command)
        self.assertEqual(original['status'], 'revoked')
        before = self.snapshot()
        self.mutations.clear()

        self.assertEqual(self.post(path, command), original)
        recovered = self.get('/requests/' + command['requestId'])
        self.assertEqual(recovered['action'], 'model.revoke')
        self.assertEqual(recovered['result'], original)
        self.assert_unchanged(before)

    def test_same_default_request_id_with_another_target_conflicts_without_mutation(self):
        first, second = self.configure('fixture-first'), self.configure('fixture-second')
        original = self.set_default(first, 'conflicting-default-command')
        before = self.snapshot()
        self.mutations.clear()
        failure = self.set_default(second, 'conflicting-default-command', expected=409)
        self.assertIn('IDEMPOTENCY_CONFLICT', failure['detail'])
        self.assertEqual(self.receipt('alice', 'conflicting-default-command'), original)
        self.assertEqual(self.models.default('alice')['reference'], first['reference'])
        self.assert_unchanged(before)

    def test_owner_scopes_command_ids_and_cannot_select_another_owners_model(self):
        alice_model = self.configure('fixture-alice')
        bob_model = self.configure('fixture-bob', owner='bob')
        alice_receipt = self.set_default(alice_model, 'shared-default-command')
        self.assertIsNone(self.receipt('bob', 'shared-default-command'))
        bob_receipt = self.set_default(bob_model, 'shared-default-command', owner='bob')
        self.assertEqual(self.receipt('alice', 'shared-default-command'), alice_receipt)
        self.assertEqual(self.receipt('bob', 'shared-default-command'), bob_receipt)
        before = self.snapshot()
        self.mutations.clear()
        self.set_default(alice_model, 'cross-owner-default-command', owner='bob', expected=404)
        self.assertIsNone(self.receipt('bob', 'cross-owner-default-command'))
        self.assertEqual(self.models.default('alice')['reference'], alice_model['reference'])
        self.assertEqual(self.models.default('bob')['reference'], bob_model['reference'])
        self.assert_unchanged(before)

    def test_recovery_is_owner_scoped_and_missing_receipts_are_read_only(self):
        alice = self.configure('fixture-alice', request_id='shared-configure-command')
        before = self.snapshot()
        self.mutations.clear()
        foreign = self.get('/requests/shared-configure-command', owner='bob', expected=404)
        unknown = self.get('/requests/unknown-configure-command', owner='bob', expected=404)
        self.assertEqual(foreign, {'detail': 'PERSONAL_MODEL_REQUEST_NOT_FOUND'})
        self.assertEqual(unknown, foreign)
        self.assert_unchanged(before)

        bob = self.configure('fixture-bob', owner='bob', request_id='shared-configure-command')
        before = self.snapshot()
        self.mutations.clear()
        for owner, original in (('alice', alice), ('bob', bob)):
            recovered = self.get('/requests/shared-configure-command', owner=owner)
            self.assertEqual(recovered['ownerId'], owner)
            self.assertEqual(recovered['result'], original)
        self.assert_unchanged(before)

    def test_recovery_requires_current_read_permission_but_not_run_permission(self):
        original = self.configure('fixture-readable', request_id='readable-configure-command')
        self.auth.denied.add(('alice', 'run'))
        before = self.snapshot()
        self.mutations.clear()
        self.assertEqual(self.get('/requests/readable-configure-command')['result'], original)
        self.auth.denied.add(('alice', 'read'))
        failure = self.get('/requests/readable-configure-command', expected=403)
        self.assertEqual(failure, {'detail': 'SYNTHETIC_PERMISSION_DENIED'})
        self.assert_unchanged(before)

    def test_initial_permission_or_credential_denial_has_no_command_receipt_or_writes(self):
        for denial in ('permission', 'credential'):
            with self.subTest(denial=denial):
                request_id = 'initial-denied-' + denial
                if denial == 'permission':
                    self.auth.denied.add(('alice', 'run'))
                else:
                    self.vault.unavailable.add('alice')
                before = self.snapshot()
                self.mutations.clear()
                try:
                    self.post('', self.configuration() | {'requestId': request_id}, expected=403)
                    self.assertIsNone(self.receipt('alice', request_id))
                    self.assert_unchanged(before)
                finally:
                    self.auth.denied.clear()
                    self.vault.unavailable.clear()

    def test_initial_schema_or_destination_rejection_has_no_command_receipt_or_writes(self):
        for name, changes in (
            ('schema', {'unexpectedOption': True}),
            ('destination', {'baseURL': 'https://models.example.com/unapproved-path'}),
        ):
            with self.subTest(rejection=name):
                request_id = 'initial-invalid-' + name
                before = self.snapshot()
                self.mutations.clear()
                self.post('', self.configuration() | changes | {'requestId': request_id}, expected=422)
                self.assertIsNone(self.receipt('alice', request_id))
                self.assert_unchanged(before)

    def test_configure_replay_403_does_not_mean_the_original_command_never_committed(self):
        request_id = 'configure-before-credential-change'
        original = self.configure('fixture-unavailable', request_id=request_id)
        self.assertEqual(self.receipt('alice', request_id), original)
        self.vault.unavailable.add('alice')
        before = self.snapshot()
        self.mutations.clear()

        failure = self.post('', self.configuration(model='fixture-unavailable') | {
            'requestId': request_id}, expected=403)

        self.assertEqual(failure['detail'], 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE')
        self.assertEqual(self.receipt('alice', request_id), original)
        current = self.models.list('alice')
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]['status'], 'credential_unavailable')
        recovered = self.get('/requests/' + request_id)
        self.assertEqual(recovered['action'], 'model.configure')
        self.assertEqual(recovered['result'], original)
        # Historical metadata remains readable even when custody is not installed.
        self.models.vault = None
        self.assertEqual(self.get('/requests/' + request_id), recovered)
        self.assert_unchanged(before)


if __name__ == '__main__':
    unittest.main()

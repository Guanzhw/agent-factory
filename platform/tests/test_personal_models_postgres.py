"""Real isolated PG, native AgentOS queue, owner identity and fake provider only."""
from fixture_identity import access_token
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx

from agent_factory.byok_model import ADAPTER_ID, PROVIDER_ID
from fixture_settings import Settings
from agent_factory.credential_vault import EncryptedCredentialVault
from core_native_fixture import create_fixture_app as create_app
from agent_factory.personal_remote_provider import origin
from core_native_fixture import publish_owner_application
from agent_factory.application_runs import factory_request_id
from agent_factory.main import create_app as create_core_app
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires independent disposable PostgreSQL')
class PersonalModelsPostgresTests(unittest.TestCase):
    def test_team_model_runs_native_task_as_requester_with_owner_custody_and_withdrawal(self):
        credential, model = self.configured()
        path = '/personal-models/' + model['reference']
        self.assertEqual(self.request('GET', '/personal-models', owner='bob'), [])
        self.request('POST', path + '/sharing', {'visibility': 'team', 'requestId': 'sharing-team-model'})
        visible = self.request('GET', '/personal-models', owner='bob')[0]
        self.assertEqual(visible['ownerId'], 'alice')
        self.assertNotIn('credentialRef', visible)
        self.assertNotIn('credentialRevision', visible)
        self.request('POST', path + '/sharing', {'visibility': 'personal', 'requestId': 'foreign-sharing-model'}, owner='bob', expected=404)
        selected = self.request('POST', path + '/default', {'requestId': 'sharing-bob-default'}, owner='bob')
        self.assertNotEqual(selected['connectionRef'], model['connectionRef'])
        self.start({'goal': 'Synthetic shared model', 'requestId': 'shared-native-task'}, owner='bob', expected=202)
        task = self.task_for_request('shared-native-task', 'bob')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            native = self.store.native_db.get_job(task['run_id']) or {}
            if native.get('status') in {'completed', 'failed'}: break
            time.sleep(.05)
        self.assertEqual(native.get('status'), 'completed', native)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0].headers['Authorization'], 'Bearer synthetic-test-password')
        self.assertEqual(self.request('GET', '/personal-credentials', owner='bob'), [])
        retained = self.store.connections.resolve('bob', selected['connectionRef'], 'model')
        self.auth.directory.set_disabled('bob', True)
        with self.assertRaises(HTTPException): retained.credential()
        with self.assertRaises(HTTPException): self.store.connections.resolve('bob', selected['connectionRef'], 'model')
        self.assertEqual(len(self.calls), 2)
        self.auth.directory.set_disabled('bob', False)
        self.request('POST', path + '/sharing', {'visibility': 'personal', 'requestId': 'withdraw-shared-model'})
        self.start({'goal': 'Withdrawn shared model', 'requestId': 'withdrawn-native-task'}, owner='bob', expected=409)
        self.assertEqual(len(self.calls), 2)
        with self.assertRaises(HTTPException): retained.credential()
        with self.assertRaises(HTTPException): self.store.connections.resolve('bob', selected['connectionRef'], 'model')

    def test_go_configuration_runs_through_the_registered_agno_executor_with_stable_plan_headers(self):
        credential = self.request('POST', '/personal-credentials', {'requestId': 'fixture-go-agent-key',
            'providerId': PROVIDER_ID, 'destination': 'https://opencode.ai',
            'username': 'api-key', 'password': 'synthetic-test-password'}, expected=201)
        model = self.request('POST', '/personal-models', {'provider': 'openai-compatible',
            'baseURL': 'https://opencode.ai/zen/go/v1', 'model': 'longcat-2.5-preview-free',
            'thinkingMode': 'disabled',
            'credentialRef': credential['credentialRef'], 'credentialRevision': credential['credentialRevision'],
            'requestId': 'fixture-go-agent-model'}, expected=201)
        self.request('POST', '/personal-models/' + model['reference'] + '/default', {'requestId': 'fixture-go-agent-default'})
        self.start({'goal': 'Synthetic tool-loop contract',
            'requestId': 'fixture-go-agent-run'}, expected=202)
        task = self.task_for_request('fixture-go-agent-run', 'alice')
        deadline = time.monotonic() + 30
        native = {}
        while time.monotonic() < deadline:
            native = self.store.native_db.get_job(task['run_id']) or {}
            if native.get('status') in {'completed', 'failed'}: break
            time.sleep(.05)
        self.assertEqual(native.get('status'), 'completed')
        self.assertEqual(len(self.calls), 2)
        for request in self.calls:
            self.assertEqual(str(request.url), 'https://opencode.ai/zen/go/v1/chat/completions')
            self.assertEqual(json.loads(request.content)['model'], 'longcat-2.5-preview-free')
            self.assertEqual(json.loads(request.content)['thinking'], {'type':'disabled'})
            self.assertEqual(json.loads(request.content)['max_tokens'], 4096)
            self.assertEqual(request.headers['x-opencode-session'], 'af-plan-' + task['plan_id'])

    def test_go_metadata_binds_exact_origin_without_invocation_and_rejects_wrong_custody(self):
        credential = self.request('POST', '/personal-credentials', {'requestId': 'fixture-go-key',
            'providerId': PROVIDER_ID, 'destination': 'https://opencode.ai',
            'username': 'api-key', 'password': 'synthetic-test-password'}, expected=201)
        body = {'provider': 'openai-compatible', 'baseURL': 'https://opencode.ai/zen/go/v1',
            'model': 'longcat-2.5-preview-free', 'credentialRef': credential['credentialRef'],
            'credentialRevision': credential['credentialRevision'], 'requestId': 'fixture-go-configure'}
        model = self.request('POST', '/personal-models', body, expected=201)
        self.assertEqual(model['baseURL'], body['baseURL'])
        self.assertEqual(self.request('POST', '/personal-models', body, expected=201), model)
        self.assertEqual(self.calls, [])
        self.request('POST', '/personal-models', {**body, 'requestId': 'fixture-go-foreign'}, owner='bob', expected=403)
        self.request('POST', '/personal-models', {**body, 'baseURL': 'https://other.example.com/v1',
            'requestId': 'fixture-go-destination'}, expected=403)

    def test_thinking_option_is_versioned_scoped_and_default_retry_compatible(self):
        credential=self.request('POST','/personal-credentials',{'requestId':'thinking-fixture-key',
            'providerId':PROVIDER_ID,'destination':'https://opencode.ai',
            'username':'api-key','password':'synthetic-test-password'},expected=201)
        values={'provider':'openai-compatible','baseURL':'https://opencode.ai/zen/go/v1',
            'model':'longcat-2.5-preview-free','credentialRef':credential['credentialRef'],
            'credentialRevision':credential['credentialRevision'],'requestId':'thinking-fixture-default'}
        original=self.request('POST','/personal-models',values,expected=201)
        self.assertNotIn('thinkingMode',original)
        self.assertEqual(self.request('POST','/personal-models',values|{'thinkingMode':'default'},expected=201),original)
        with self.store.personal_models.db.read() as conn:
            old=self.store.personal_models.binding(conn,'alice',original['reference']).opaque_handle
        changed=self.request('POST','/personal-models/'+original['reference']+'/configure',
            values|{'requestId':'thinking-fixture-change','thinkingMode':'disabled'},expected=200)
        self.assertEqual(changed['thinkingMode'],'disabled')
        self.assertNotEqual(changed['revision'],original['revision'])
        with self.assertRaises(HTTPException):old.check()
        self.request('POST','/personal-models',values|{'requestId':'thinking-foreign','thinkingMode':'disabled'},owner='bob',expected=403)
        self.request('POST','/personal-models',values|{'requestId':'thinking-wrong-model','thinkingMode':'disabled','model':'other'},expected=422)
        self.request('POST','/personal-models',values|{'requestId':'thinking-wrong-base','thinkingMode':'disabled','baseURL':'https://other.example.com/v1'},expected=422)
        self.assertEqual(self.calls,[])

    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.calls = []
        self.selected_connections = {}
        def wire(request):
            self.calls.append(request)
            body = json.loads(request.content)
            # A genuine native tool iteration, followed by a synthetic summary.
            tool_messages = [m for m in body['messages'] if m['role'] == 'tool']
            message, reason = {'role': 'assistant', 'content': 'Controlled BYOK checksum fixture completed.'}, 'stop'
            if not tool_messages:
                message, reason = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'checksum-fixture-call',
                    'type': 'function', 'function': {'name': 'checksum', 'arguments': '{"text":"synthetic checksum"}'}}]}, 'tool_calls'
            return httpx.Response(200, json={'choices': [{'finish_reason': reason, 'message': message}]})
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.folder.name), max_workers=1,
            temporary_policy='member-self-service',
            fee_management_enabled=self._testMethodName == 'test_legacy_enabled_host_byok_job_reads_without_commitment',
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b's' * 32, {PROVIDER_ID: origin}),
            owner_model_transport_factory=lambda: httpx.MockTransport(wire))
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.tokens = {owner: access_token(owner) for owner in ('alice', 'bob')}
        self.addCleanup(self.store.engine.dispose); self.addCleanup(self.store.native_db.db_engine.dispose)
        self.auth.directory.upsert('fixture-reviewer', name='Synthetic template publisher')
        publish_owner_application(self.state, author='manager')
        self.client = TestClient(self.app, base_url="https://testserver"); self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def request(self, method, path, body=None, *, owner='alice', expected=200, expected_owner=None):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.tokens[owner],
                **({'X-Factory-Expected-Owner': expected_owner} if expected_owner is not None else {})})
        self.assertEqual(response.status_code, expected, response.text)
        self.assertNotIn('synthetic-test-password', response.text)
        self.assertNotIn('synthetic-rotated-password', response.text)
        result = response.json()
        if response.status_code == 200 and method == 'POST' and path.startswith('/personal-models/') and path.endswith(('/default', '/configure')):
            self.selected_connections[owner] = result['connectionRef']
        return result

    def start(self, values, *, owner='alice', expected=202):
        # Model selection is explicit client input; core does not select defaults.
        connection = self.selected_connections.get(owner)
        return self.request('POST', '/application-interface/v1/starts', {
            'application': 'fixture-owner-checksum', 'mode': 'literature', **values,
            'connectionRefs': {'ownerModel': connection} if connection else {},
        }, owner=owner, expected=expected)

    def task_for_request(self, request_id, owner):
        return self.store.task_for_request(factory_request_id(request_id), owner)

    def configured(self):
        credential = self.request('POST', '/personal-credentials', {'requestId': 'fixture-save-key',
            'providerId': PROVIDER_ID, 'destination': 'https://models.example.com',
            'username': 'api-key', 'password': 'synthetic-test-password'}, expected=201)
        body = {'provider': 'openai-compatible', 'baseURL': 'https://models.example.com/v1', 'model': 'fixture-model',
            'credentialRef': credential['credentialRef'], 'credentialRevision': credential['credentialRevision'],
            'requestId': 'fixture-model-save'}
        model = self.request('POST', '/personal-models', body, expected=201)
        self.assertEqual(self.request('POST', '/personal-models', body, expected=201), model)
        self.request('POST', '/personal-models/' + model['reference'] + '/default', {'requestId': 'fixture-default'})
        self.assertEqual(self.calls, [])
        return credential, model

    def test_single_submit_native_queue_no_billing_no_admin_and_replay(self):
        self.assertIsNone(self.store.usage_ledger)
        error = self.start({'goal': 'Synthetic checksum', 'requestId': 'missing-model'}, expected=409)
        self.assertIn('Missing owner connection: ownerModel', error['message'])
        self.assertIn('fixture-owner-checksum', [item['id'] for item in self.store.applications.list_active('alice')])
        credential, model = self.configured()
        dispatch = AsyncMock(wraps=self.state['bridge'].submit)
        replacement = patch.object(self.state['bridge'], 'submit', dispatch)
        replacement.start(); self.addCleanup(replacement.stop)
        result = self.start({'goal': 'Synthetic checksum', 'requestId': 'research-submit'}, expected=202)
        task = self.task_for_request('research-submit', 'alice')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            native = self.store.native_db.get_job(task['run_id']) or {}
            if native.get('status') in {'completed', 'failed'}: break
            time.sleep(.05)
        self.assertEqual(native.get('status'), 'completed', native)
        self.assertEqual(len(self.calls), 2)
        plan = self.store.plan(task['plan_id'], 'alice')
        self.assertEqual(plan['executionBindings']['model']['adapterId'], ADAPTER_ID)
        self.assertNotIn('usageBudget', plan)
        self.assertEqual(plan['policy'], 'member-self-service')
        self.assertEqual(self.store.plan_policy.require_execution('alice', plan)['source'], 'member-self-service')
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
        replay = self.start({'goal': 'Synthetic checksum', 'requestId': 'research-submit'}, expected=202)
        self.assertEqual(replay['planId'], result['planId'])
        self.assertEqual(replay['job']['id'], task['id'])
        self.assertEqual(dispatch.await_count, 1)
        self.assertEqual(len(self.calls), 2)
        self.start({'goal': 'Different checksum', 'requestId': 'research-submit'}, expected=409)
        self.request('GET', '/application-interface/v1/starts/research-submit', owner='bob', expected=404)
        receipt = self.request('GET', '/application-interface/v1/starts/research-submit')
        self.assertEqual(receipt['taskId'], task['id'])
        self.assertEqual(receipt['runId'], task['run_id'])
        self.assertFalse(receipt['createsExecution'])
        self.assertFalse(receipt['automaticReplay'])
        self.assertNotIn('synthetic-test-password', str(self.store.sql('SELECT * FROM af_encrypted_credentials')))
        self.assertFalse(self.request('GET', '/status')['feeManagementEnabled'])
        # A separate production core starts empty; fixture registrations and
        # applications are supplied only by this test's explicit composition.
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as production_db, TemporaryDirectory() as directory:
            production = create_core_app(Settings(db_url=production_db.url, jwt_key='synthetic-production-fixture-signing-key', workspace=Path(directory)))
            state = production.app.state.factory
            production_store, production_auth = state['store'], state['auth']
            try:
                production_auth.directory.upsert('fixture-owner', name='Synthetic production owner')
                headers = {'Authorization': 'Bearer ' + access_token('fixture-owner')}
                with TestClient(production, base_url="https://testserver") as client:
                    response = client.post('/api/factory/application-interface/v1/starts', headers=headers,
                        json={'application': 'fixture-owner-checksum', 'mode': 'literature',
                            'goal': 'Do not substitute fixture applications', 'requestId': 'production-no-fixtures'})
                    self.assertEqual(response.status_code, 404, response.text)
                    self.assertEqual(response.json()['message'], 'Published application configuration not found')
                    self.assertEqual(production_store.applications.list_active('fixture-owner'), [])
                    self.assertEqual(production_store.materials(published_only=True), [])
                    self.assertEqual(production_store.tasks('fixture-owner'), [])
            finally:
                production_store.engine.dispose()
                production_store.native_db.db_engine.dispose()
        self.assertEqual(len(self.calls), 2)

    def test_owner_isolation_rotation_revoke_and_restart_without_secret_resolution(self):
        credential, model = self.configured()
        self.assertEqual(self.request('GET', '/personal-models', owner='bob'), [])
        self.request('POST', '/personal-models/' + model['reference'] + '/default', {'requestId': 'bob-default'}, owner='bob', expected=404)
        rotated = self.request('POST', '/personal-credentials/' + credential['credentialRef'] + '/rotate', {
            'requestId': 'rotate-fixture-key', 'credentialRevision': credential['credentialRevision'],
            'username': 'api-key', 'password': 'synthetic-rotated-password'})
        self.assertEqual(self.request('GET', '/personal-models')[0]['status'], 'credential_unavailable')
        with self.assertRaises(HTTPException): self.store.connections.resolve('alice', model['connectionRef'], 'model')
        self.start({'goal': 'No stale key use', 'requestId': 'stale-research'}, expected=409)
        body = {'provider': 'openai-compatible', 'baseURL': 'https://models.example.com/v1', 'model': 'fixture-model',
            'credentialRef': rotated['credentialRef'], 'credentialRevision': rotated['credentialRevision'],
            'requestId': 'fixture-reconfigure'}
        updated = self.request('POST', '/personal-models/' + model['reference'] + '/configure', body)
        self.assertNotEqual(updated['connectionRef'], model['connectionRef'])
        restarted = create_app(self.settings).app.state.factory['store']
        self.addCleanup(restarted.engine.dispose); self.addCleanup(restarted.native_db.db_engine.dispose)
        self.assertEqual(restarted.personal_models.default('alice')['connectionRef'], updated['connectionRef'])
        self.assertEqual(self.calls, [])
        handle = restarted.connections.resolve('alice', updated['connectionRef'], 'model')
        self.request('POST', '/personal-models/' + model['reference'] + '/revoke', {'requestId': 'revoke-fixture-model'})
        with self.assertRaises(HTTPException): handle.credential()
        with self.assertRaises(HTTPException): restarted.personal_models.default('alice')
        self.assertEqual(self.calls, [])

    def test_vault_lifecycle_blocks_future_use_preserves_native_task_context(self):
        credential, model = self.configured()
        old_handle = self.store.connections.resolve('alice', model['connectionRef'], 'model')
        self.start({'goal': 'Synthetic retained context',
            'requestId': 'credential-context-task'}, expected=202)
        task = self.task_for_request('credential-context-task', 'alice')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            native = self.store.native_db.get_job(task['run_id']) or {}
            if native.get('status') in {'completed', 'failed'}:
                break
            time.sleep(.05)
        self.assertEqual(native.get('status'), 'completed', native)
        self.assertEqual(len(self.calls), 2)
        # Background observation, not GET detail, persists completion. Keep the
        # existing native deadline and wait for its positive terminal record.
        while time.monotonic() < deadline:
            task = self.task_for_request('credential-context-task', 'alice')
            if task['terminal'] and task['body']['lastStatus'] == 'completed':
                break
            time.sleep(.05)
        self.assertTrue(task['terminal'], 'Observer must persist native stop before history capture')
        self.assertIsNotNone(task['body'].get('observedAt'))
        detail = self.request('GET', '/jobs/' + task['id'])
        self.assertEqual(detail['job']['status'], 'completed')
        task = self.task_for_request('credential-context-task', 'alice')
        self.assertEqual(task['body']['lastStatus'], 'completed')
        self.assertIsNone(self.store.usage_ledger)
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
        plan = self.store.plan(task['plan_id'], 'alice')
        events = self.store.events(task['id'])
        rotated = self.request('POST', '/personal-credentials/' + credential['credentialRef'] + '/rotate', {
            'requestId': 'context-rotate', 'credentialRevision': credential['credentialRevision'],
            'username': 'api-key', 'password': 'synthetic-rotated-password'}, expected_owner='alice')
        with self.assertRaises(HTTPException):
            old_handle.credential()
        self.start({'goal': 'No stale binding', 'requestId': 'context-stale'}, expected=409)
        updated = self.request('POST', '/personal-models/' + model['reference'] + '/configure', {
            'provider': model['provider'], 'baseURL': model['baseURL'], 'model': model['model'],
            'credentialRef': rotated['credentialRef'], 'credentialRevision': rotated['credentialRevision'],
            'requestId': 'context-rebind'}, expected_owner='alice')
        current_handle = self.store.connections.resolve('alice', updated['connectionRef'], 'model')
        self.request('POST', '/personal-credentials/' + rotated['credentialRef'] + '/revoke', {
            'requestId': 'context-revoke', 'credentialRevision': rotated['credentialRevision']}, expected_owner='alice')
        with self.assertRaises(HTTPException):
            current_handle.credential()
        self.start({'goal': 'No revoked binding', 'requestId': 'context-revoked'}, expected=409)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.store.plan(task['plan_id'], 'alice'), plan)
        retained = self.task_for_request('credential-context-task', 'alice')
        for key in ('id', 'owner_id', 'plan_id', 'run_id', 'body'):
            self.assertEqual(retained[key], task[key])
        self.assertEqual(self.store.native_db.get_job(task['run_id'])['status'], 'completed')
        self.assertTrue(all(event in self.store.events(task['id']) for event in events))
        persisted = json.dumps({'plan': plan, 'task': retained, 'events': self.store.events(task['id'])}, default=str)
        for secret in ('synthetic-test-password', 'synthetic-rotated-password'):
            self.assertNotIn(secret, persisted)
            self.assertTrue(all(secret not in request.content.decode() for request in self.calls))

    def test_legacy_enabled_host_byok_job_reads_without_commitment(self):
        # Legacy refers to the enabled billing ledger, not the plan admission policy.
        # Exercise actual startup accounting configuration, native admission and
        # public reads; a composition-only check cannot catch detail's inspect.
        self.assertIsNotNone(self.store.usage_ledger)
        self.assertTrue(self.request('GET', '/status')['feeManagementEnabled'])
        self.assertFalse(self.settings.platform_paid_models_enabled)
        self.configured()
        self.start({
            'goal': 'Synthetic legacy-host read fixture', 'requestId': 'legacy-byok-read'}, expected=202)
        task = self.task_for_request('legacy-byok-read', 'alice')
        plan = self.store.plan(task['plan_id'], 'alice')
        self.assertEqual(plan['policy'], 'member-self-service')
        self.assertNotIn('usageBudget', plan)
        progress = self.request('GET', '/jobs/' + task['id'])
        self.assertIsNone(progress['usageLedger'])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            native = self.store.native_db.get_job(task['run_id']) or {}
            if native.get('status') in {'completed', 'failed'}: break
            time.sleep(.05)
        self.assertEqual(native.get('status'), 'completed', native)
        # Native completion can precede durable accounting/stop observation.
        # Keep the same deadline; GET must not perform that finalization.
        while time.monotonic() < deadline:
            task = self.task_for_request('legacy-byok-read', 'alice')
            if task['terminal'] and task['body']['lastStatus'] == 'completed':
                break
            time.sleep(.05)
        self.assertTrue(task['terminal'], 'Observer must finalize before completed history is asserted')
        self.assertEqual(task['body']['lastStatus'], 'completed')
        detail = self.request('GET', '/jobs/' + task['id'])
        self.assertEqual(detail['job']['status'], 'completed')
        self.assertIsNone(detail['usageLedger'])
        self.assertTrue(detail['events'])
        self.assertTrue(detail['artifacts'])
        job_ids, cursor, seen = [], None, set()
        while True:
            page = self.request('GET', '/jobs?' + urlencode({
                'limit': 50, **({'cursor': cursor} if cursor else {})}))
            job_ids.extend(job['id'] for job in page['items'])
            cursor = page['nextCursor']
            if cursor is None:
                break
            self.assertNotIn(cursor, seen, 'History pagination repeated a cursor')
            seen.add(cursor)
        self.assertIn(task['id'], job_ids)
        self.request('GET', '/jobs/' + task['id'], owner='bob', expected=404)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_usage_accounts')[0]['n'], 0)
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_usage_attempts')[0]['n'], 0)

    def test_disabling_keeps_historical_ledger_rows_and_byok_needs_no_price(self):
        from agent_factory.usage_ledger import UsageLedger
        ledger = UsageLedger(self.store)
        before = self.store.sql('SELECT * FROM af_usage_policies ORDER BY revision')
        tariffs = self.store.sql('SELECT * FROM af_usage_prices ORDER BY id')
        restarted = create_app(self.settings).app.state.factory['store']
        self.addCleanup(restarted.engine.dispose); self.addCleanup(restarted.native_db.db_engine.dispose)
        self.assertIsNone(restarted.usage_ledger)
        self.assertEqual(restarted.sql('SELECT * FROM af_usage_policies ORDER BY revision'), before)
        self.assertEqual(restarted.sql('SELECT * FROM af_usage_prices ORDER BY id'), tariffs)
        self.configured()
        # Even a host retaining an enabled legacy ledger cannot charge BYOK.
        self.store.usage_ledger = ledger
        model = self.store.personal_models.default('alice')
        plan = self.store.composition.create_plan('alice', 'Synthetic BYOK ledger independence',
            'literature', 'fixture-owner-checksum', request_id='legacy-byok-plan',
            connection_refs={'ownerModel': model['connectionRef']})
        self.assertEqual(plan['status'], 'ready', plan)
        self.assertNotIn('usageBudget', plan)
        self.assertEqual(self.calls, [])

    def test_new_models_reuse_saved_credential_and_server_rechecks_scope_and_revision(self):
        credential = self.request('POST', '/personal-credentials', {'requestId': 'existing-key',
            'providerId': PROVIDER_ID, 'destination': 'https://models.example.com',
            'username': 'api-key', 'password': 'synthetic-test-password'}, expected=201, expected_owner='alice')
        body = {'provider': 'openai-compatible', 'baseURL': 'https://models.example.com/v1', 'model': 'fixture-model',
            'credentialRef': credential['credentialRef'], 'credentialRevision': credential['credentialRevision']}
        self.request('POST', '/personal-models', body | {'requestId': 'foreign-existing'}, owner='bob', expected_owner='bob', expected=403)
        for request_id, changed in [('wrong-origin', {'baseURL': 'https://other.example.com/v1'}),
                ('wrong-revision', {'credentialRevision': 'forged-revision'})]:
            self.request('POST', '/personal-models', body | changed | {'requestId': request_id}, expected_owner='alice', expected=403)
        self.assertEqual(self.request('GET', '/personal-models'), [])
        first = self.request('POST', '/personal-models', body | {'requestId': 'reuse-first'}, expected=201, expected_owner='alice')
        second = self.request('POST', '/personal-models', body | {'model': 'another-fixture-model', 'requestId': 'reuse-second'}, expected=201, expected_owner='alice')
        self.assertNotEqual(first['reference'], second['reference'])
        self.assertEqual(len(self.request('GET', '/personal-credentials')), 1)
        rotated = self.request('POST', '/personal-credentials/' + credential['credentialRef'] + '/rotate', {
            'requestId': 'reuse-rotate', 'credentialRevision': credential['credentialRevision'],
            'username': 'api-key', 'password': 'synthetic-rotated-password'})
        self.request('POST', '/personal-models', body | {'requestId': 'stale-existing'}, expected_owner='alice', expected=403)
        self.request('POST', '/personal-credentials/' + rotated['credentialRef'] + '/revoke', {
            'requestId': 'reuse-revoke', 'credentialRevision': rotated['credentialRevision']})
        self.request('POST', '/personal-models', body | {'credentialRevision': rotated['credentialRevision'],
            'requestId': 'revoked-existing'}, expected_owner='alice', expected=403)
        self.auth.directory.set_disabled('alice', True)
        self.request('POST', '/personal-models', body | {'requestId': 'permission-ended'}, expected_owner='alice', expected=403)
        self.assertEqual(self.calls, [])

    def test_rejected_secret_input_destination_and_current_permission(self):
        credential, model = self.configured()
        self.request('POST', '/personal-models', {'apiKey': 'synthetic-test-password'}, expected=422)
        body = {'provider': 'openai-compatible', 'baseURL': 'https://other.example.com/v1', 'model': 'fixture-model',
            'credentialRef': credential['credentialRef'], 'credentialRevision': credential['credentialRevision'],
            'requestId': 'wrong-destination'}
        self.request('POST', '/personal-models', body, expected=403)
        self.auth.directory.set_disabled('alice', True)
        self.start({'goal': 'Permission revoked', 'requestId': 'revoked-grant'}, expected=403)
        self.assertEqual(self.calls, [])

    def test_stale_tab_expected_owner_rejects_secret_and_metadata_before_any_write(self):
        before = self.request('GET', '/personal-credentials', owner='bob')
        # Models may be empty, so response-owner validation alone cannot help.
        self.request('POST', '/personal-credentials', {'requestId': 'stale-tab-fake-key',
            'providerId': PROVIDER_ID, 'destination': 'https://models.example.com',
            'username': 'api-key', 'password': 'synthetic-test-password'},
            owner='bob', expected_owner='alice', expected=403)
        self.assertEqual(self.request('GET', '/personal-credentials', owner='bob'), before)
        self.assertEqual(self.request('GET', '/personal-credentials'), [])
        credential, model = self.configured()
        for path, body in [('/personal-models', {'provider': 'openai-compatible',
                'baseURL': model['baseURL'], 'model': model['model'],
                'credentialRef': credential['credentialRef'], 'credentialRevision': credential['credentialRevision'], 'requestId': 'stale-model'}),
                ('/personal-models/' + model['reference'] + '/default', {'requestId': 'stale-default'}),
                ('/personal-models/' + model['reference'] + '/revoke', {'requestId': 'stale-revoke'}),
                ('/personal-credentials/' + credential['credentialRef'] + '/rotate',
                {'credentialRevision': credential['credentialRevision'], 'username': 'api-key',
                 'password': 'synthetic-rotated-password', 'requestId': 'stale-rotate'}),
                ('/personal-credentials/' + credential['credentialRef'] + '/revoke',
                 {'credentialRevision': credential['credentialRevision'], 'requestId': 'stale-vault-revoke'})]:
            self.request('POST', path, body, owner='bob', expected_owner='alice', expected=403)
        self.request('GET', '/personal-models', owner='bob', expected_owner='alice', expected=403)
        self.request('GET', '/personal-credentials', owner='bob', expected_owner='alice', expected=403)
        self.assertEqual(self.request('GET', '/personal-models', owner='bob'), [])
        self.assertEqual(self.request('GET', '/personal-credentials', owner='bob'), before)
        self.assertEqual(self.request('GET', '/personal-models')[0]['status'], 'configured')
        self.assertEqual(self.calls, [])

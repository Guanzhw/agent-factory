"""Real isolated PG, native AgentOS queue, owner identity and fake provider only."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx

from agent_factory.byok_model import ADAPTER_ID, PROVIDER_ID
from agent_factory.config import Settings
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.main import create_app
from agent_factory.personal_remote_provider import origin
from agent_factory.personal_research import publish_application
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires independent disposable PostgreSQL')
class PersonalModelsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.calls = []
        def wire(request):
            self.calls.append(request)
            body = json.loads(request.content)
            # A genuine native tool iteration, followed by a synthetic summary.
            tool_messages = [m for m in body['messages'] if m['role'] == 'tool']
            message, reason = {'role': 'assistant', 'content': 'Controlled BYOK research fixture completed.'}, 'stop'
            if not tool_messages:
                message, reason = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'research-fixture-call',
                    'type': 'function', 'function': {'name': 'literature_search', 'arguments': '{"query":"synthetic research"}'}}]}, 'tool_calls'
            return httpx.Response(200, json={'choices': [{'finish_reason': reason, 'message': message}]})
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.folder.name), max_workers=1,
            temporary_policy='admin-review',
            fee_management_enabled=self._testMethodName == 'test_legacy_enabled_host_byok_job_reads_without_commitment',
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b's' * 32, {PROVIDER_ID: origin}),
            owner_model_transport_factory=lambda: httpx.MockTransport(wire))
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose); self.addCleanup(self.store.native_db.db_engine.dispose)
        self.auth.directory.upsert('fixture-reviewer', name='Synthetic template publisher')
        self.auth.authorization.assign('fixture-reviewer', 'factory-manager')
        publish_application(self.state, author='manager', reviewer='fixture-reviewer')
        self.client = TestClient(self.app); self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def request(self, method, path, body=None, *, owner='alice', expected=200, expected_owner=None):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner),
                **({'X-Factory-Expected-Owner': expected_owner} if expected_owner is not None else {})})
        self.assertEqual(response.status_code, expected, response.text)
        self.assertNotIn('synthetic-test-password', response.text)
        self.assertNotIn('synthetic-rotated-password', response.text)
        return response.json()

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
        error = self.request('POST', '/personal-research', {'topic': 'Synthetic research', 'requestId': 'missing-model'}, expected=409)
        self.assertEqual(error['code'], 'PERSONAL_MODEL_SETUP_REQUIRED')
        self.assertTrue(self.request('GET', '/personal-research/capabilities')['applicationAvailable'])
        credential, model = self.configured()
        result = self.request('POST', '/personal-research', {'topic': 'Synthetic research', 'requestId': 'research-submit'}, expected=202)
        task = self.store.task_for_request('research-submit', 'alice')
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
        self.assertEqual(self.store.plan_policy.require_execution('alice', plan)['source'], 'owner-submission')
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
        replay = self.request('POST', '/personal-research', {'topic': 'Synthetic research', 'requestId': 'research-submit'}, expected=202)
        self.assertEqual(replay['planId'], result['planId'])
        self.assertEqual(len(self.calls), 2)
        self.request('POST', '/personal-research', {'topic': 'Different research', 'requestId': 'research-submit'}, expected=409)
        self.request('GET', '/personal-research/requests/research-submit', owner='bob', expected=404)
        self.request('GET', '/personal-research/requests/research-submit')
        self.assertNotIn('synthetic-test-password', str(self.store.sql('SELECT * FROM af_encrypted_credentials')))
        self.assertFalse(self.request('GET', '/status')['feeManagementEnabled'])
        # A separate real production-mode app has no automatic fixture template
        # or real tool provider. Do not change a demo database's deployment mode.
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as production_db, TemporaryDirectory() as directory:
            production = create_app(Settings(db_url=production_db.url, demo=False,
                jwt_key='synthetic-production-fixture-signing-key', workspace=Path(directory)))
            state = production.app.state.factory
            production_store, production_auth = state['store'], state['auth']
            try:
                production_auth.authorization.define_role('production-fixture-user', [
                    'agents:factory-executor:read', 'agents:factory-executor:run', 'components:read'])
                production_auth.directory.upsert('fixture-owner', name='Synthetic production owner')
                production_auth.authorization.assign('fixture-owner', 'production-fixture-user')
                headers = {'Authorization': 'Bearer ' + production_auth._issue_native_token('fixture-owner')}
                with TestClient(production) as client:
                    response = client.get('/api/factory/personal-research/capabilities', headers=headers)
                    self.assertEqual(response.status_code, 200, response.text)
                    support = response.json()
                    self.assertFalse(support['supported'])
                    self.assertFalse(support['applicationAvailable'])
                    self.assertEqual(support['unsupportedReason'], 'PERSONAL_RESEARCH_REAL_TOOLS_REQUIRED')
                    response = client.post('/api/factory/personal-research', headers=headers,
                        json={'topic': 'Do not substitute demo tools', 'requestId': 'production-no-real-tools'})
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(response.json()['code'], 'PERSONAL_RESEARCH_REAL_TOOLS_REQUIRED')
                    with self.assertRaises(HTTPException) as unavailable:
                        publish_application(state, author='fixture-owner', reviewer='other-fixture')
                    self.assertEqual(unavailable.exception.detail, 'PERSONAL_RESEARCH_DEMO_TEMPLATE_ONLY')
                    self.assertEqual(production_store.applications.list_active('fixture-owner'), [])
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
        self.request('POST', '/personal-research', {'topic': 'No stale key use', 'requestId': 'stale-research'}, expected=409)
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

    def test_legacy_enabled_host_byok_job_reads_without_commitment(self):
        # Exercise actual startup accounting configuration, native admission and
        # public reads; a composition-only check cannot catch detail's inspect.
        self.assertIsNotNone(self.store.usage_ledger)
        self.assertTrue(self.request('GET', '/status')['feeManagementEnabled'])
        self.assertFalse(self.settings.platform_paid_models_enabled)
        self.configured()
        self.request('POST', '/personal-research', {
            'topic': 'Synthetic legacy-host read fixture', 'requestId': 'legacy-byok-read'}, expected=202)
        task = self.store.task_for_request('legacy-byok-read', 'alice')
        plan = self.store.plan(task['plan_id'], 'alice')
        self.assertNotIn('usageBudget', plan)
        progress = self.request('GET', '/jobs/' + task['id'])
        self.assertIsNone(progress['usageLedger'])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            native = self.store.native_db.get_job(task['run_id']) or {}
            if native.get('status') in {'completed', 'failed'}: break
            time.sleep(.05)
        self.assertEqual(native.get('status'), 'completed', native)
        detail = self.request('GET', '/jobs/' + task['id'])
        self.assertEqual(detail['job']['status'], 'completed')
        self.assertIsNone(detail['usageLedger'])
        self.assertTrue(detail['events'])
        self.assertTrue(detail['artifacts'])
        self.assertIn(task['id'], [job['id'] for job in self.request('GET', '/jobs')])
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
            'literature', 'personal-research-v1', request_id='legacy-byok-plan',
            connection_refs={'ownerModel': model['connectionRef']})
        self.assertEqual(plan['status'], 'ready', plan)
        self.assertNotIn('usageBudget', plan)
        self.assertEqual(self.calls, [])

    def test_rejected_secret_input_destination_and_current_permission(self):
        credential, model = self.configured()
        self.request('POST', '/personal-models', {'apiKey': 'synthetic-test-password'}, expected=422)
        body = {'provider': 'openai-compatible', 'baseURL': 'https://other.example.com/v1', 'model': 'fixture-model',
            'credentialRef': credential['credentialRef'], 'credentialRevision': credential['credentialRevision'],
            'requestId': 'wrong-destination'}
        self.request('POST', '/personal-models', body, expected=403)
        self.auth.authorization.unassign('alice', 'factory-user')
        self.request('POST', '/personal-research', {'topic': 'Permission revoked', 'requestId': 'revoked-grant'}, expected=403)
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
                 'password': 'synthetic-rotated-password', 'requestId': 'stale-rotate'})]:
            self.request('POST', path, body, owner='bob', expected_owner='alice', expected=403)
        self.request('GET', '/personal-models', owner='bob', expected_owner='alice', expected=403)
        self.assertEqual(self.request('GET', '/personal-models', owner='bob'), [])
        self.assertEqual(self.request('GET', '/personal-credentials', owner='bob'), before)
        self.assertEqual(self.request('GET', '/personal-models')[0]['status'], 'configured')
        self.assertEqual(self.calls, [])

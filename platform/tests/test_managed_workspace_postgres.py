"""Required real-PG composition/review/admission tests; no ORX/model/process IO.

The dedicated no-skips gate must supply disposable PostgreSQL; portable jobs skip it.
Native source observation is a named fixture; managed provider execution is not
claimed by these tests. Unknown submit is deliberately injected at the bridge.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock
import unittest

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.managed_orx_attachment import ManagedORXSessionProvider
from agent_factory.managed_orx_profile import MODEL_ADAPTER, PROVIDER, exact_input_schema, model_registration, request_guard
from agent_factory.orx_research_broker import MODEL
from agent_factory.process_runtime_profile import registrations, TOOL_ID, ENVIRONMENT_ID, TOOL_NAME
from agent_factory.resources import RemoteTarget, ComputePool
from agent_factory.store import digest
from agent_factory.usage_ledger import PricingRevision, UsagePolicy
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ManagedWorkspacePostgresTests(unittest.TestCase):
    application: dict
    profile: dict

    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.pin = {'kind': 'orx', 'revision': '1', 'version': 1, 'fingerprint': 'b' * 64}
        self.contract = {'ownerId': 'alice', 'connectionRef': 'original-orx',
            'connectionFingerprint': 'b' * 64, 'connectionRevision': '1', 'connectionVersion': 1,
            'projectId': 'native-project', 'projectIdentityHash': 'c' * 64,
            'sessionId': 'original-session', 'profile': {'harness': 'opencode', 'model': 'factory/' + MODEL},
            'profileSha256': digest({'harness': 'opencode', 'model': 'factory/' + MODEL}),
            'modelRequests': 1, 'nativeTools': 'disabled', 'brokerModel': MODEL}
        provider = object.__new__(ManagedORXSessionProvider)
        provider._contract = self.contract
        provider.capacity_namespace, provider.configuration_fingerprint = 'e' * 64, 'f' * 64
        target = RemoteTarget('Fixture metadata only', 'compute', frozenset({'alice'}), provider=provider,
            capacity_pool=ComputePool('managed-probe-pool', 1, 128, 1), max_cpu=1, max_memory_mb=128,
            max_disk_mb=1, max_seconds=5)
        def installed_profiles(store, auth, resources):
            self.assertIs(store.process_runtime.resources, resources)
            auth.directory.upsert('probe-reviewer', name='Fixture independent reviewer')
            auth.authorization.assign('probe-reviewer', 'factory-manager')
            state = {'material_governance': store.material_governance, 'applications': store.applications}
            self.application = self.publish_application(state)
            self.profile = {'ownerId': 'alice', 'targetRef': 'probe-target', 'connectionPin': self.pin,
                'nativeProfileId': 'probe', 'sessionId': 'original-session', 'contractSha256': digest(self.contract),
                'applicationRef': {k: self.application[k] for k in ('id', 'version', 'sha256')}, 'mode': 'probe'}
            return {'probe': self.profile}
        # Explicit accounting compatibility fixture; no model/process IO is installed.
        settings = Settings(db_url=self.database.url, workspace=Path(directory.name), max_workers=1,
            fee_management_enabled=True, platform_paid_models_enabled=True,
            temporary_policy='admin-review', runtime_tool_contract='bounded-process-v1',
            policy_revision='managed-probe-fixture-plan-v1',
            material_policy_revision='managed-probe-fixture-material-v1',
            managed_orx_profiles_factory=installed_profiles,
            runtime_adapters=[*registrations(target_ref='probe-target'), model_registration('probe-target')],
            remote_targets={'probe-target': target},
            usage_policy=UsagePolicy(revision='probe-fixture-usage-v1', task_amount_micros=1000, user_amount_micros=10000),
            usage_pricing=(PricingRevision(MODEL_ADAPTER, '1', PROVIDER, MODEL, 'fixture-nominal-v1',
                input_micros_per_million=100, output_micros_per_million=100,
                request_guard=request_guard, accounting_basis='operator-nominal-not-invoice'),))
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.service = self.state['openresearch_workspace']
        self.assertIn('bounded_process_run', self.store.external_execution_handlers)
        project = {'id': 'attached-project', 'kind': 'native-openresearch', 'upstreamProjectId': 'native-project',
            'connectionRefs': {'workspace': 'original-orx'}, 'connectionPins': {'workspace': self.pin},
            'nativeProject': {'projectIdentityHash': 'c' * 64}}
        with self.service.db.write() as conn:
            conn.execute(self.service.projects.insert().values(id=project['id'], owner_id='alice',
                body=project, created_at='2026-01-01'))
        self.service.refresh_native_project = AsyncMock(return_value=project)
        adapter = Mock()
        adapter.describe.return_value = {'sessionProfiles': [{'id': 'probe', **self.contract['profile']}]}
        self.service._native_adapter = Mock(return_value=(adapter, self.pin))
        self.bridge = self.service.factory.bridge
        self.bridge.submit = AsyncMock(side_effect=TimeoutError('injected unknown native acknowledgment'))
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.root = '/api/factory/openresearch/projects/attached-project'

    def publish_application(self, state):
        governance, applications = state['material_governance'], state['applications']
        refs = []
        for kind, name, adapter in [('prompt', 'instructions', None), ('model', 'model', MODEL_ADAPTER),
                ('tool', TOOL_NAME, TOOL_ID), ('environment', 'environment', ENVIRONMENT_ID)]:
            identifier = 'managed-probe-test-' + name
            body = {'id': identifier, 'kind': kind, 'name': identifier, 'description': 'Controlled admission fixture',
                'content': 'Verify one original text-only attachment' if kind == 'prompt' else name, 'license': 'MIT', 'compatibility': ['agno:3.1.0'],
                'dependencies': [], 'permissions': ['compute:local'] if kind == 'tool' else [],
                'provenance': {'kind': 'original', 'notice': 'Synthetic metadata; no live provider verification'}}
            if adapter:
                body['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': {'targetRef': 'probe-target'}}
            material = governance.create_draft('manager', body, identifier + ':draft')
            review = governance.request_publication('manager', identifier, material['version'], identifier + ':review')
            governance.decide_publication('probe-reviewer', review['id'], True, identifier + ':approve')
            refs.append({k: material[k] for k in ('id', 'version', 'sha256')})
        app = applications.create_draft('manager', {'id': 'managed-probe-test', 'name': 'Managed probe fixture',
            'description': 'Admission/review only; not native research', 'defaultMode': 'probe', 'discoveryKeywords': [],
            'modes': {'probe': {'materialRefs': refs, 'capabilities': ['compute:local'], 'toolOrder': [TOOL_NAME],
                'inputSchema': exact_input_schema(self.contract), 'config': {}, 'connectionRequirements': [],
                'budget': {'toolCalls': 2, 'maxDepth': 1, 'maxChildren': 1, 'experimentSeconds': 5, 'outputBytes': 65536}}}}, 'probe-app-draft')
        review = applications.request_publication('manager', app['id'], app['version'], 'probe-app-review')
        applications.decide_publication('probe-reviewer', review['id'], True, 'probe-app-approve')
        return app

    def request(self, method, path, body=None, owner='alice'):
        return self.client.request(method, path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner)})

    def prepare(self):
        response = self.request('POST', self.root + '/sessions/prepare-managed',
            {'requestId': 'prepare-request', 'profileId': 'probe', 'goal': 'Verify the original attached session'})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_native_composition_review_required_and_original_unknown_recovery(self):
        session = self.prepare()
        self.assertEqual(session['plan']['inputValues'], {'managedAttachment': self.contract})
        self.assertEqual(session['state'], 'prepared')
        self.assertFalse(session['authorization']['executionAllowed'])
        self.assertEqual(self.store.sql('SELECT id FROM af_tasks'), [])
        self.assertEqual(self.store.sql('SELECT id FROM af_plan_reviews'), [])
        start = self.root + '/sessions/' + session['id'] + '/start'
        denied = self.request('POST', start, {'requestId': 'start-request'})
        self.assertIn(denied.status_code, (403, 409), denied.text)
        self.bridge.submit.assert_not_awaited()
        review = self.request('POST', '/api/factory/plan-reviews',
            {'requestId': 'review-request', 'planId': session['planId']})
        self.assertEqual(review.status_code, 201, review.text)
        approval = self.request('POST', '/api/factory/plan-reviews/' + review.json()['id'] + '/decision',
            {'requestId': 'approval-request', 'approved': True}, 'manager')
        self.assertEqual(approval.status_code, 200, approval.text)
        admitted = self.request('POST', start, {'requestId': 'start-request'})
        self.assertEqual(admitted.status_code, 202, admitted.text)
        original = admitted.json()
        self.assertEqual(original['admission'], 'unknown')
        self.assertIsNotNone(original['taskId'])
        retry = self.request('POST', start, {'requestId': 'retry-start-request'})
        self.assertEqual(retry.status_code, 202, retry.text)
        self.assertEqual(retry.json()['taskId'], original['taskId'])
        self.bridge.submit.assert_awaited_once()
        self.assertEqual(len(self.store.sql('SELECT id FROM af_tasks')), 1)
        self.assertEqual(self.request('GET', '/api/factory/openresearch/requests/start-request').json()['session']['taskId'], original['taskId'])
        self.assertEqual(self.request('GET', self.root + '/sessions/' + session['id'], owner='bob').status_code, 404)
        self.assertEqual(self.store.sql('SELECT id FROM af_leases'), [])

    def test_native_schema_rejects_user_proof_and_stale_installed_contract(self):
        invalid = self.request('POST', self.root + '/sessions/prepare-managed',
            {'requestId': 'prepare-request', 'profileId': 'probe', 'goal': 'Verify original session',
                'managedAttachment': self.contract})
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.service.managed_profiles['probe']['sessionId'] = 'replacement-session'
        profiles = self.request('GET', self.root + '/managed-profiles')
        self.assertEqual(profiles.status_code, 200, profiles.text)
        self.assertEqual(profiles.json(), [])
        response = self.request('POST', self.root + '/sessions/prepare-managed',
            {'requestId': 'prepare-request', 'profileId': 'probe', 'goal': 'Verify original session'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.store.sql('SELECT id FROM af_plans'), [])
        self.assertEqual(self.store.sql('SELECT id FROM af_openresearch_workspace_sessions'), [])
        self.bridge.submit.assert_not_awaited()

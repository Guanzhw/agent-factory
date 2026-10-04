# pyright: reportMissingImports=false
"""Persistent operator development profile, real native queue, no live providers."""
from contextlib import ExitStack
import os
import re
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.comparison_profile import APPLICATION_ID as COMPARISON
from agent_factory.config import Settings
from agent_factory.development_workflows import controlled_workflow_settings, initialize_controlled_fixtures, registration_refs
from agent_factory.literature_synthesis_profile import CONNECTION_NAME as MODEL_CONNECTION
from agent_factory.main import create_app
from agent_factory.pubmed_profile import APPLICATION_ID as SOURCE, CONNECTION_NAME as SOURCE_CONNECTION
from agent_factory.synthesis_runtime import APPLICATION_ID as SYNTHESIS
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated Linux PostgreSQL')
class DevelopmentWorkflowsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.outer = ExitStack()
        self.addCleanup(self.outer.close)
        self.database = self.outer.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        self.workspace = Path(self.outer.enter_context(TemporaryDirectory(prefix='development-workflows-pg-')))
        self.runtime = None
        self.addCleanup(self.stop)
        self.start(initialize=True)

    def start(self, *, initialize=False):
        runtime = ExitStack()
        self.runtime = runtime
        base = Settings(db_url=self.database.url, workspace=self.workspace, demo=True,
            development_mock_login=True, development_public_origin='https://127.0.0.1:3443',
            temporary_policy='admin-review', storage_task_reserve_bytes=8*1024*1024)
        settings = runtime.enter_context(controlled_workflow_settings(base))
        app = create_app(settings)
        self.state = app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        runtime.callback(self.store.engine.dispose)
        runtime.callback(self.store.native_db.db_engine.dispose)
        if initialize:
            initialize_controlled_fixtures(self.state)
        self.sessions = {}
        self.client = runtime.enter_context(TestClient(app, base_url='https://127.0.0.1:3443', follow_redirects=False))  # pyright: ignore[reportArgumentType]

    def stop(self):
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None

    def browser_owner(self, owner):
        origin = 'https://127.0.0.1:3443'
        self.client.cookies.clear()
        if owner not in self.sessions:
            started = self.client.post('/api/factory/auth/login', json={}, headers={'Origin': origin})
            self.assertEqual(started.status_code, 200, started.text)
            selector = self.client.get(started.json()['authorizationUrl'])
            form = {'persona': owner}
            for name in ('flow', 'csrf'):
                match = re.search('name="' + name + '" value="([A-Za-z0-9_-]{43})"', selector.text)
                assert match is not None
                form[name] = match.group(1)
            selected = self.client.post('/api/factory/dev-identity/select', data=form, headers={'Origin': origin})
            self.assertEqual(selected.status_code, 303, selected.text)
            callback = self.client.get(selected.headers['location'])
            self.assertEqual(callback.status_code, 303, callback.text)
            session = self.client.get('/api/factory/auth/session').json()
            self.sessions[owner] = (dict(self.client.cookies), session['csrfToken'])
        cookies, csrf = self.sessions[owner]
        self.client.cookies.clear()
        self.client.cookies.update(cookies)
        return {'Origin': origin, 'X-Factory-CSRF': csrf}

    def request(self, method, path, body=None, *, owner='alice', status=200):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers=self.browser_owner(owner))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def post(self, path, body=None, *, owner='alice', status=201):
        return self.request('POST', path, {'requestId': str(uuid4()), **(body or {})}, owner=owner, status=status)

    def application(self, identifier):
        return next(row for row in self.state['applications'].list_active('alice') if row['id'] == identifier)

    def connection(self, kind):
        registration = registration_refs('alice')[kind]
        return next(row for row in self.state['connections'].list('alice') if row['registrationRef'] == registration)

    def execute(self, application, mode, goal, **extra):
        selected = self.application(application)
        proposal = self.post('/compositions/proposals', {'applicationRef': {key: selected[key] for key in ('id', 'version', 'sha256')},
            'mode': mode, 'goal': goal, **extra})
        self.assertEqual(proposal['candidate']['status'], 'ready', proposal)
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept')
        self.post('/instances', {'planId': plan['id']}, status=409)
        review = self.post('/plan-reviews', {'planId': plan['id']})
        self.post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, owner='manager2', status=200)
        task = self.post('/instances', {'planId': plan['id']}, status=202)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            detail = self.request('GET', '/jobs/' + task['id'])
            if detail['job']['status'] in {'completed', 'failed', 'canceled', 'cancelled', 'unknown'}:
                self.assertEqual(detail['job']['status'], 'completed', detail)
                return task, detail
            time.sleep(.05)
        self.fail('DEVELOPMENT_WORKFLOW_TIMEOUT')

    def test_single_profile_source_snapshot_synthesis_and_comparison_with_separate_plan_reviews(self):
        source, detail = self.execute(SOURCE, 'bibliography', 'Inspect the synthetic development source.',
            connectionRefs={SOURCE_CONNECTION: self.connection('source')['ref']})
        self.assertEqual(detail['literatureEvidence']['evidenceKind'], 'controlled_literature_fixture')
        preview = self.request('GET', '/synthesis/sources/' + source['id'])
        snapshot = self.post('/synthesis/snapshots', {'sourceTaskId': source['id'],
            'sourceIds': [preview['projection']['sources'][0]['sourceId']],
            'question': 'Describe the synthetic excerpt without scientific claims.', 'expectedFingerprint': preview['fingerprint']})
        synthesis, result = self.execute(SYNTHESIS, 'controlled-fixture', snapshot['question'],
            sourceSnapshotRef={key: snapshot[key] for key in ('id', 'fingerprint')},
            connectionRefs={MODEL_CONNECTION: self.connection('model')['ref']})
        self.assertEqual(result['synthesisEvidence']['status'], 'ready')
        self.assertFalse(result['synthesisEvidence']['scientificConclusionVerified'])
        comparison, compared = self.execute(COMPARISON, 'linear-v1', 'Compare the fixed synthetic predictors.')
        self.assertEqual(compared['comparisonEvidence']['status'], 'ready')
        self.assertTrue(compared['comparisonEvidence']['executionVerified'])
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
        for task, body in ((source, detail), (synthesis, result), (comparison, compared)):
            self.request('GET', '/jobs/' + task['id'], owner='bob', status=404)
            for artifact in body['artifacts']:
                response = self.client.get('/api/factory/jobs/' + task['id'] + '/artifacts/' + artifact['id'],
                    headers=self.browser_owner('alice'))
                self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.store.tasks('alice')), 3)
        self.stop()
        self.start()
        for task in (source, synthesis, comparison):
            self.assertEqual(self.request('GET', '/jobs/' + task['id'])['job']['id'], task['id'])
        self.assertEqual(len(self.store.tasks('alice')), 3)
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)

    def test_bootstrap_replay_retains_original_versions_revocations_and_native_roles(self):
        before_apps = {row['id']: (row['version'], row['sha256']) for row in self.state['applications'].list_active('alice')}
        before_connections = self.state['connections'].list('alice')
        selected = self.connection('source')
        self.state['connections'].revoke('alice', selected['ref'], str(uuid4()))
        initialize_controlled_fixtures(self.state)
        self.assertEqual(len(self.state['connections'].list('alice')), len(before_connections))
        self.assertEqual(self.connection('source')['ref'], selected['ref'])
        self.assertEqual(self.connection('source')['status'], 'revoked')
        self.auth.authorization.unassign('bob', 'factory-user')
        self.stop()
        self.start()
        self.assertEqual({row['id']: (row['version'], row['sha256']) for row in self.state['applications'].list_active('alice')}, before_apps)
        self.assertEqual(self.connection('source')['ref'], selected['ref'])
        self.assertEqual(self.connection('source')['status'], 'revoked')
        with self.assertRaises(HTTPException):
            self.auth.require('bob', 'run')
        self.assertEqual(self.store.tasks('alice'), [])
        self.assertEqual(self.store.sql('SELECT id FROM af_process_allocations'), [])


if __name__ == '__main__':
    unittest.main()

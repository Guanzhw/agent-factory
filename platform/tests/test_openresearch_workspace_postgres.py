"""Real PostgreSQL/native-auth HTTP workspace metadata; no live ORX/provider."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.main import create_app
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class WorkspacePostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app(Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1))
        state = self.app.app.state.factory
        self.store = state['store']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.root = '/api/factory/openresearch'

    def login(self, owner):
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/factory/demo/login', json={'persona': owner}).status_code, 200)

    def test_native_auth_owner_project_persistence_and_no_fake_readiness(self):
        self.assertEqual(self.client.get(self.root + '/projects').status_code, 401)
        self.login('alice')
        self.assertEqual(self.client.get('/api/factory/personal-credentials/capabilities').json(),
            {'enabled': False, 'providerIds': []})
        request = {'requestId': 'project-request', 'name': 'Controlled workspace'}
        response = self.client.post(self.root + '/projects', json=request)
        self.assertEqual(response.status_code, 201, response.text)
        project = response.json()
        self.assertIsNone(project['upstreamProjectId'])
        self.assertEqual(project['kind'], 'factory-workspace')
        self.assertEqual(self.client.post(self.root + '/projects', json=request).json(), project)
        rows = self.store.sql('SELECT owner_id,body FROM af_openresearch_workspace_projects')
        self.assertEqual(rows[0]['owner_id'], 'alice')
        self.assertEqual(rows[0]['body']['id'], project['id'])
        self.assertFalse(self.client.get(self.root + '/capabilities').json()['liveEndToEndVerified'])
        self.login('bob')
        self.assertEqual(self.client.get(self.root + '/projects').json(), [])
        self.assertEqual(self.client.get(self.root + '/projects/' + project['id']).status_code, 404)
        self.assertEqual(self.client.get(self.root + '/projects/' + project['id'] + '/sessions').status_code, 404)

    def test_unavailable_workload_never_dispatches_or_claims_upstream_creation(self):
        self.login('alice')
        project = self.client.post(self.root + '/projects', json={'requestId': 'project-request', 'name': 'A'}).json()
        original = self.store.autoresearch.start
        self.store.autoresearch.start = AsyncMock()
        self.addCleanup(setattr, self.store.autoresearch, 'start', original)
        response = self.client.post(self.root + '/projects/' + project['id'] + '/sessions', json={
            'requestId': 'session-request', 'workloadPresetId': 'uninstalled', 'goal': 'A question'})
        self.assertEqual(response.status_code, 404, response.text)
        self.store.autoresearch.start.assert_not_awaited()
        self.assertEqual(self.store.sql('SELECT id FROM af_openresearch_workspace_sessions'), [])
        self.assertEqual(self.client.post(self.root + '/projects', json={
            'requestId': 'unsafe-request', 'name': 'A', 'password': 'not-a-real-secret'}).status_code, 422)

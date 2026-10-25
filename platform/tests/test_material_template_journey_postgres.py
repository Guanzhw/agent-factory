# pyright: reportMissingImports=false
"""Governed template copy to native synthetic literature; disposable PG only."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from agent_factory.applications import ApplicationDefinition
from agent_factory.config import Settings
from core_native_fixture import create_fixture_app as create_app
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class MaterialTemplateJourneyPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        workspace = tempfile.TemporaryDirectory(prefix='material-template-journey-')
        self.addCleanup(workspace.cleanup)
        self.app = create_app(Settings(db_url=database.url, workspace=Path(workspace.name), max_workers=1))
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(self.app).__enter__()  # pyright: ignore[reportArgumentType]
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self, actor):
        self.client.cookies.clear()
        self.post('/demo/login', {'persona': actor}, 200)

    def post(self, path, body, status=201):
        response = self.client.post('/api/factory' + path, json=body)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def command(self, **values):
        return {'requestId': str(uuid4()), **values}

    def draft(self):
        self.login('manager')
        response = self.client.get('/api/factory/applications/fixture-text/versions/1')
        self.assertEqual(response.status_code, 200, response.text)
        source = response.json()['application']
        definition = {key: deepcopy(source[key]) for key in ApplicationDefinition.model_fields}
        definition.update(id='department-literature-' + uuid4().hex[:10], name='部门受控文献模板',
            description='Synthetic governed template roundtrip, not scientific findings.',
            discoveryKeywords=['部门模板验收'], defaultForDiscovery=False, defaultMode='literature')
        definition['modes'] = {'literature': definition['modes']['literature']}
        mode = definition['modes']['literature']
        mode['config'] = {'askScopeBelowLength': 0, 'experimentDurationSeconds': 1}
        mode['budget'] = {'toolCalls': 2, 'maxDepth': 1, 'maxChildren': 1,
            'experimentSeconds': 3, 'outputBytes': 65536}
        pinned = deepcopy(mode['materialRefs'])
        material_rows = {row['id']: row for row in self.store.materials(published_only=True)}
        self.assertEqual({material_rows[ref['id']]['kind'] for ref in pinned},
            {'skill', 'tool', 'prompt', 'knowledge', 'model', 'environment'})
        draft = self.post('/applications/drafts', self.command(definition=definition))
        self.assertEqual(draft['modes']['literature']['materialRefs'], pinned)
        self.assertNotEqual(draft['id'], source['id'])
        return draft, definition

    def publish(self):
        draft, definition = self.draft()
        route = f"/applications/{draft['id']}/versions/{draft['version']}/publish"
        self.login('bob')
        self.post(route, self.command(), 404)
        self.login('manager')
        self.post(route, self.command(), 200)
        return draft, definition

    def accept(self, application):
        self.login('alice')
        discovered = self.client.get('/api/factory/applications')
        self.assertEqual(discovered.status_code, 200)
        self.assertIn(application['id'], str(discovered.json()))
        proposal = self.post('/compositions/proposals', self.command(goal='部门模板验收：整理明确标识的合成文献证据'))
        self.assertEqual(proposal['candidate']['applicationRef']['id'], application['id'])
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept', self.command())
        self.assertEqual(plan['application'], application['id'])
        return plan

    def test_copied_six_kind_template_direct_publication_native_artifact_and_withdrawal(self):
        application, definition = self.publish()
        plan = self.accept(application)
        original_plan = deepcopy(self.store.plan(plan['id'], 'alice'))
        self.assertEqual(plan['budget']['toolCalls'], definition['modes']['literature']['budget']['toolCalls'])
        request = self.command(planId=plan['id'])
        task = self.post('/instances', request, 202)
        deadline = time.monotonic() + 30
        detail = None
        while time.monotonic() < deadline:
            response = self.client.get('/api/factory/jobs/' + task['id'])
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail['job']['status'] in {'completed', 'failed', 'cancelled', 'unknown'}:
                break
            time.sleep(.05)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail['job']['status'], 'completed', detail)
        artifact = next(row for row in detail['artifacts'] if row['name'] == 'synthetic-literature.json')
        path = f"/api/factory/jobs/{task['id']}/artifacts/{artifact['id']}"
        raw = self.client.get(path)
        self.assertEqual(raw.status_code, 200)
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact['sha256'])
        self.assertEqual(raw.json()['evidenceKind'], 'synthetic')
        self.assertEqual(self.store.plan(plan['id'], 'alice'), original_plan)
        receipt = self.client.get('/api/factory/requests/' + request['requestId'])
        self.assertEqual(receipt.json()['taskId'], task['id'])
        self.login('bob')
        self.assertIn(self.client.get(path).status_code, {403, 404})
        self.assertIn(self.client.get('/api/factory/jobs/' + task['id']).status_code, {403, 404})
        self.post(f"/applications/{application['id']}/versions/{application['version']}/withdraw",
            self.command(reason='Foreign withdrawal'), 404)
        self.login('manager')
        self.post(f"/applications/{application['id']}/versions/{application['version']}/withdraw",
            self.command(reason='Synthetic withdrawal'), 200)
        self.login('alice')
        self.post('/instances', self.command(planId=plan['id']), 409)
        self.assertEqual(self.client.get(path).status_code, 200)

    def test_publication_rechecks_current_member_ownership_and_exact_material_pin(self):
        draft, definition = self.draft()
        self.login('bob')
        route = f"/applications/{draft['id']}/versions/{draft['version']}/publish"
        self.post(route, self.command(), 404)
        self.login('manager')
        self.auth.directory.set_disabled('manager', True)
        self.post(route, self.command(), 403)
        self.auth.directory.set_disabled('manager', False)
        self.post(route, self.command(), 200)
        invalid = deepcopy(definition)
        invalid['id'] = 'missing-exact-' + uuid4().hex[:8]
        invalid['modes']['literature']['materialRefs'][0]['sha256'] = 'f' * 64
        response = self.client.post('/api/factory/applications/drafts', json=self.command(definition=invalid))
        self.assertIn(response.status_code, {409, 422}, response.text)
        self.assertEqual(self.state['applications'].inspect('manager', draft['id'], draft['version'])['governance']['state'], 'published')

# pyright: reportMissingImports=false
"""Actual Factory HTTP/PG recovery; generated owners/materials, no model call."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_factory.composition_inbox import CompositionInboxService
import test_applications_composition as composition_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class CompositionInboxPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = composition_fixture.ApplicationCompositionPostgresTests('runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.application = self.fixture.publish_http()
        self.fixture.login('alice')

    def propose(self, goal='Text audit public inbox fixture'):
        response = self.fixture.client.post('/api/factory/compositions/proposals', json={
            'goal': goal, 'application': self.application['id'], 'mode': 'literature', 'requestId': str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_lost_reply_restart_http_discovery_original_plan_and_withdrawn_history(self):
        proposal = self.propose()
        response = self.fixture.client.post('/api/factory/compositions/proposals/' + proposal['id'] + '/accept',
                                            json={'requestId': str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        original = response.json()
        # Simulate returning with neither creation/acceptance key nor a browser pointer.
        self.fixture.stop(); self.fixture.start(); self.fixture.login('alice')
        with patch.object(self.fixture.composition, 'accept', side_effect=AssertionError('read must not accept')), \
             patch.object(self.fixture.composition, 'propose', side_effect=AssertionError('read must not create')):
            page = self.fixture.client.get('/api/factory/compositions/proposals')
            self.assertEqual(page.status_code, 200, page.text)
            self.assertEqual([item['id'] for item in page.json()['items']], [proposal['id']])
            path = '/api/factory/compositions/proposals/' + proposal['id'] + '/recovery'
            restored = self.fixture.client.get(path)
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()['plan'], original)
        self.fixture.apps.withdraw('bob', self.application['id'], self.application['version'], str(uuid4()), 'Synthetic inbox withdrawal')
        history = self.fixture.client.get(path)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()['plan'], original)
        self.assertFalse(history.json()['executionAuthorized'])
        denied = self.fixture.client.post('/api/factory/instances', json={'planId': original['id'], 'requestId': str(uuid4())})
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(self.fixture.store.sql('SELECT COUNT(*) AS count FROM af_tasks')[0]['count'], 0)
        self.fixture.login('bob')
        self.assertEqual(self.fixture.client.get(path).status_code, 404)
        self.assertEqual(self.fixture.client.get('/api/factory/compositions/proposals').json()['items'], [])

    def test_cursor_anchor_owner_and_fixed_window_survive_factory_restart(self):
        originals = [self.propose('Text audit public inbox ' + str(i)) for i in range(3)]
        service = CompositionInboxService(self.fixture.composition)
        first = service.list('alice', limit=1)
        self.fixture.stop(); self.fixture.start(); self.fixture.login('alice')
        newest = self.propose('Text audit after inbox boundary')
        service = CompositionInboxService(self.fixture.composition)
        ids = [first['items'][0]['id']]; cursor = first['nextCursor']
        while cursor:
            page = service.list('alice', after=cursor, limit=1)
            ids.extend(item['id'] for item in page['items']); cursor = page['nextCursor']
        self.assertEqual(set(ids), {item['id'] for item in originals})
        self.assertNotIn(newest['id'], ids)
        self.fixture.login('bob')
        response = self.fixture.client.get('/api/factory/compositions/proposals', params={'after': first['nextCursor']})
        self.assertEqual(response.status_code, 400, response.text)

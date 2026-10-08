# pyright: reportMissingImports=false
"""Read-only recovery with actual composition/governance and disposable SQLite."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from agent_factory.composition import CompositionService
from agent_factory.composition_inbox import CompositionInboxService
from agent_factory.store import digest
from test_applications_composition import ApplicationCompositionFixture, pin


class CompositionInboxTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ApplicationCompositionFixture('runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.publish()
        self.service = CompositionInboxService(self.fixture.composition)

    def propose(self, goal='Text audit synthetic public goal', owner='alice'):
        return self.fixture.composition.propose(owner, goal, application_ref=pin(self.app), request_id=str(uuid4()))

    def count(self, table):
        with self.fixture.store.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(table)).scalar_one()

    def test_lost_initial_reply_is_discovered_after_service_restart_without_write(self):
        saved = self.propose()
        composition = CompositionService(self.fixture.store, self.fixture.auth, self.fixture.applications, self.fixture.bindings, None)
        reopened = CompositionInboxService(composition)
        with patch.object(composition, 'propose', side_effect=AssertionError('no create')), \
             patch.object(composition, 'accept', side_effect=AssertionError('no accept')):
            page = reopened.list('alice')
            self.assertEqual([item['id'] for item in page['items']], [saved['id']])
            self.assertFalse(page['snapshot'])
            recovered = reopened.read('alice', saved['id'])
            self.assertEqual(recovered['proposal'], self.fixture.composition.inspect('alice', saved['id']))
            self.assertIsNone(recovered['plan']); self.assertFalse(recovered['executionAuthorized'])
        self.assertEqual(self.count(composition.proposals), 1)

    def test_accepted_original_plan_restores_without_accept_key_or_current_publication(self):
        proposal = self.propose()
        original = self.fixture.composition.accept('alice', proposal['id'], str(uuid4()))
        self.fixture.applications.withdraw('bob', self.app['id'], self.app['version'], str(uuid4()), 'synthetic withdrawal')
        with patch.object(self.fixture.composition, 'accept', side_effect=AssertionError('no reaccept')):
            page = self.service.list('alice')
            recovered = self.service.read('alice', proposal['id'])
        self.assertEqual(page['items'][0]['state'], 'accepted')
        self.assertEqual(recovered['plan'], original)
        self.assertTrue(recovered['historical']); self.assertFalse(recovered['executionAuthorized'])
        with self.assertRaises(HTTPException): self.fixture.applications.require_plan_current(original)
        self.assertEqual(self.count(self.fixture.store.plan_table), 1)

    def test_cursor_pages_have_fixed_ceiling_no_duplicates_and_no_newer_insert(self):
        originals = [self.propose('Text audit public ' + str(i)) for i in range(5)]
        first = self.service.list('alice', limit=2)
        newest = self.propose('Text audit later public input')
        ids = [item['id'] for item in first['items']]
        cursor = first['nextCursor']
        while cursor:
            page = self.service.list('alice', after=cursor, limit=2)
            ids.extend(item['id'] for item in page['items']); cursor = page['nextCursor']
        self.assertEqual(set(ids), {item['id'] for item in originals})
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(newest['id'], ids)
        self.assertIn(newest['id'], {item['id'] for item in self.service.list('alice')['items']})

    def test_owner_scope_cursor_and_detail_do_not_disclose_foreign_proposals(self):
        proposal = self.propose(); self.propose('Text audit second')
        cursor = self.service.list('alice', limit=1)['nextCursor']
        self.assertEqual(self.service.list('bob')['items'], [])
        with self.assertRaises(HTTPException) as detail: self.service.read('bob', proposal['id'])
        self.assertEqual(detail.exception.status_code, 404)
        for after in (cursor, 'invalid', 'x' * 2049):
            with self.assertRaises(HTTPException) as error: self.service.list('bob', after=after)
            self.assertEqual(error.exception.status_code, 400)

    def test_revision_history_and_current_state_remain_visible_within_page_window(self):
        proposal = self.propose()
        revised = self.fixture.composition.revise('alice', proposal['id'], 'Text audit revised public goal',
            application_ref=pin(self.app), request_id=str(uuid4()))
        self.fixture.composition.reject('alice', revised['id'], str(uuid4()))
        page = self.service.list('alice')
        states = {item['id']: item['state'] for item in page['items']}
        self.assertEqual(states, {proposal['id']: 'revised', revised['id']: 'rejected'})
        self.assertEqual(self.service.read('alice', proposal['id'])['proposal']['revisedBy'], revised['id'])

    def test_original_plan_relationship_and_row_integrity_cannot_be_swapped(self):
        proposal = self.propose()
        original = self.fixture.composition.accept('alice', proposal['id'], str(uuid4()))
        changed = deepcopy(original); changed['normalizedGoal'] = 'Text audit changed'
        with patch.object(self.fixture.store, 'plan', return_value=changed):
            with self.assertRaises(HTTPException): self.service.read('alice', proposal['id'])
        table = self.fixture.composition.proposals
        with self.fixture.store.engine.begin() as conn:
            body = deepcopy(proposal); body['candidate']['normalizedGoal'] = 'tampered'
            conn.execute(table.update().where(table.c.id == proposal['id']).values(body=body))
        with self.assertRaises(HTTPException): self.service.list('alice')

    def test_read_auth_current_and_bounded_inputs_no_side_effects(self):
        self.propose()
        for limit in (True, 0, -1, 51, 1.5):
            with self.assertRaises(HTTPException): self.service.list('alice', limit=limit)
        self.fixture.auth.authorization.unassign('alice', 'factory-user')
        with self.assertRaises(HTTPException): self.service.list('alice')
        self.assertEqual(self.count(self.fixture.composition.proposals), 1)

    def test_tampered_owner_bound_anchor_and_bounded_summary(self):
        first = self.propose('Text audit ' + 'x' * 1800); self.propose('Text audit second')
        page = self.service.list('alice', limit=1)
        self.assertEqual(len(page['items'][0]['goalPreview']), 160)
        self.assertNotIn('executionBindings', page['items'][0])
        table = self.fixture.composition.proposals
        with self.fixture.store.engine.begin() as conn:
            row = conn.execute(select(table).where(table.c.id == first['id'])).mappings().one()
            body = deepcopy(row['body']); body['createdAt'] = '2020-01-01T00:00:00+00:00'
            conn.execute(table.update().where(table.c.id == first['id']).values(body=body, hash=digest(body)))
        with self.assertRaises(HTTPException) as error: self.service.list('alice', after=page['nextCursor'])
        self.assertEqual(error.exception.status_code, 400)

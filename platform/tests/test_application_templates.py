"""Template discovery metadata, using owned synthetic data and no execution."""
import base64
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from agno.db.postgres import PostgresDb
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import OperationalError

from agent_factory.applications import ApplicationService
from agent_factory.store import digest
from pg_fixture import IsolatedPostgres
from test_applications_composition import ApplicationCompositionFixture, app_definition, pin


class ApplicationTemplateTests(ApplicationCompositionFixture):
    def seed_pages(self):
        """Direct metadata fixtures isolate paging from publication/adapter tests."""
        source = self.publish()
        with self.store.engine.begin() as conn:
            conn.execute(self.applications.states.update().values(bootstrap=True))
            for prefix, count, state, bootstrap, kind in (
                    ('a-draft', 110, 'draft', False, 'template'),
                    ('b-internal', 110, 'published', False, 'application'),
                    ('c-bootstrap', 110, 'published', True, 'template'),
                    ('z-template', 105, 'published', False, 'template')):
                for number in range(count):
                    body = {**deepcopy(source), 'id': f'{prefix}-{number:03}', 'version': 1}
                    body['sha256'] = digest({key: value for key, value in body.items() if key != 'sha256'})
                    conn.execute(self.applications.versions.insert().values(
                        id=body['id'], version=1, body=body, sha=body['sha256']))
                    conn.execute(self.applications.states.insert().values(id=body['id'], version=1,
                        author_id='manager', state=state, bootstrap=bootstrap, entry_kind=kind, updated_at=body['createdAt']))

    def test_published_filter_precedes_paging_and_discovery_has_no_hundred_row_cutoff(self):
        self.seed_pages()
        found, cursor = [], None
        while True:
            page = self.applications.list_templates('alice', after=cursor, limit=40)
            found.extend(item['id'] for item in page['items'])
            cursor = page['nextCursor']
            if cursor is None:
                break
        self.assertEqual(found, [f'z-template-{number:03}' for number in range(105)])
        self.assertEqual(len(self.applications.list_template_candidates('alice')), 105)
        values = self.composition._input('text audit', application=None, mode=None,
            material_choices=None, connection_refs=None, input_values=None, application_ref=None)
        chosen, selection = self.composition._application('alice', values)
        self.assertEqual(chosen['id'], 'z-template-000', 'Existing keyword ties still select by ID')
        self.assertEqual(selection['method'], 'approved-keyword-selection-v1')

    def test_pages_order_versions_and_withdrawal_is_not_a_snapshot(self):
        first = self.publish()
        revised = self.applications.revise('manager', first['id'], 1, app_definition(self.store), 'revise-page')
        self.applications.publish('manager', revised['id'], revised['version'], 'publish-page')
        with self.store.engine.begin() as conn:
            conn.execute(self.applications.states.update().where(self.applications.states.c.id != first['id']).values(bootstrap=True))
        page = self.applications.list_templates('alice', limit=1)
        self.assertEqual(page['items'], [revised])
        self.applications.withdraw('manager', first['id'], 1, 'withdraw-page')
        self.assertEqual(self.applications.list_templates('alice', after=page['nextCursor'], limit=1),
                         {'items': [], 'nextCursor': None})

    def test_internal_exact_refs_and_legacy_explicit_selection_remain_usable(self):
        application = self.publish()
        self.assertTrue(self.applications.mark_application_entry(pin(application)))
        self.assertNotIn(application, self.applications.list_templates('alice')['items'])
        self.assertIn(application, self.applications.list_active('alice'))
        self.assertEqual(self.applications.require_current(pin(application)), application)
        for arguments in ({'application': application['id']}, {'application_ref': pin(application)}):
            plan = self.composition.create_plan('alice', 'Text audit by explicit selection', 'literature', **arguments)
            self.assertEqual(plan['applicationRef'], pin(application))
        revised = self.applications.revise('manager', application['id'], 1, app_definition(self.store), 'internal-revise')
        self.assertEqual(self.applications.inspect('manager', revised['id'], revised['version'])['governance']['entry_kind'], 'application')

    def test_original_revision_retry_survives_marking_and_new_create_intent_is_distinct(self):
        definition = app_definition(self.store)
        parent = self.applications.create_draft('manager', definition, 'old-draft')
        child = self.applications.revise('manager', parent['id'], 1, definition, 'old-revision')
        self.applications.mark_application_entry(pin(parent))
        self.assertEqual(self.applications.create_draft('manager', definition, 'old-draft'), parent)
        self.assertEqual(self.applications.revise('manager', parent['id'], 1, definition, 'old-revision'), child)
        with self.assertRaisesRegex(HTTPException, 'IDEMPOTENCY_CONFLICT'):
            self.applications.create_draft('manager', definition, 'old-draft', entry_kind='application')
        self.assertEqual(self.applications.inspect('manager', parent['id'], 1)['application'], parent)

    def test_old_schema_adds_only_default_metadata_and_repeated_startup_is_safe(self):
        application = self.publish()
        with self.store.engine.begin() as conn:
            conn.execute(text('ALTER TABLE af_application_states DROP COLUMN entry_kind'))
        for _ in range(2):
            fresh = ApplicationService(self.store, self.auth)
            view = fresh.inspect('alice', application['id'], application['version'])
            self.assertEqual(view['application'], application)
            self.assertEqual(view['governance']['entry_kind'], 'template')
        with self.store.engine.connect() as conn:
            column = next(item for item in inspect(conn).get_columns('af_application_states') if item['name'] == 'entry_kind')
        self.assertFalse(column['nullable'])

    def test_missing_or_mismatched_pins_warn_without_marking_but_sql_failures_propagate(self):
        application = self.publish()
        for ref in ({**pin(application), 'id': 'missing'}, {**pin(application), 'sha256': 'a' * 64}):
            with self.assertLogs('agent_factory.applications', level='WARNING') as logs:
                self.assertFalse(self.applications.mark_application_entry(ref))
            self.assertIn('not marked', logs.output[0])
        self.assertEqual(self.applications.inspect('alice', application['id'], 1)['governance']['entry_kind'], 'template')
        with patch.object(self.applications, '_row', side_effect=OperationalError('test', {}, Exception('offline'))):
            with self.assertRaises(OperationalError):
                self.applications.mark_application_entry(pin(application))

    def test_malformed_cursors_and_unpublished_other_owner_are_not_exposed(self):
        draft = self.applications.create_draft('manager', app_definition(self.store), 'private-draft')
        self.assertNotIn(draft, self.applications.list_templates('alice')['items'])
        for value in ('not-base64!', base64.urlsafe_b64encode(json.dumps(['x', True]).encode()).decode(),
                      base64.urlsafe_b64encode(json.dumps({'id': 'x', 'version': 1}).encode()).decode()):
            with self.assertRaises(HTTPException) as raised:
                self.applications.list_templates('alice', after=value)
            self.assertEqual(raised.exception.status_code, 422)
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(self.applications.versions.c.body).where(
                self.applications.versions.c.id == draft['id'])).scalar_one(), draft)


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ApplicationTemplatePostgresTests(ApplicationTemplateTests):
    def setUp(self):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        db = PostgresDb(db_url=isolated.url)
        with patch('test_applications_composition.SqliteDb', return_value=db):
            super().setUp()
        self.store.engine = create_engine(isolated.url, pool_size=1, max_overflow=0, pool_timeout=3)
        self.addCleanup(self.store.engine.dispose)

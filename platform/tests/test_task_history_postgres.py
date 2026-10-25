"""Owner history through real HTTP/PostgreSQL; deterministic synthetic records."""
from fixture_identity import access_token
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from pg_fixture import IsolatedPostgres
from agent_factory.store import canonical
from fixture_settings import Settings
from core_native_fixture import create_fixture_app as create_app


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class TaskHistoryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.app = create_app(Settings(db_url=cls.database.url, workspace=Path(cls.workspace.name)))
        cls.state = cls.app.app.state.factory
        cls.store, cls.auth = cls.state['store'], cls.state['auth']
        cls.addClassCleanup(cls.store.engine.dispose)
        cls.addClassCleanup(cls.store.native_db.db_engine.dispose)
        cls.client = TestClient(cls.app, base_url="https://testserver").__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)
        cls.client.portal.call(cls.state['lifecycle_observer'].stop)
        cls.plan = cls.client.post('/api/factory/plans', headers=cls.headers(), json={
            'topic':'Synthetic history', 'mode':'literature', 'requestId':str(uuid4()), "application": "fixture-text"}).json()
        cls.identifiers = []
        for i in range(205):
            identifier = str(uuid4())
            cls.identifiers.append(identifier)
            cls.store.sql("""INSERT INTO af_tasks(id,owner_id,plan_id,request_id,fingerprint,admission,terminal,body)
                VALUES(:id,'alice',:plan,:request,'synthetic-history','rejected',TRUE,CAST(:body AS JSONB))""",
                id=identifier, plan=cls.plan['id'], request=str(uuid4()), body=canonical({
                    'createdAt':'2026-01-01T00:00:00+00:00', 'updatedAt':'2026-01-01T00:00:00+00:00', 'lastStatus':'failed'}))

    @classmethod
    def headers(cls, owner='alice'):
        return {'Authorization':'Bearer ' + access_token(owner)}

    def get(self, **params):
        response = self.client.get('/api/factory/jobs', headers=self.headers(), params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_205_tied_timestamps_complete_and_owner_bound(self):
        seen, cursor = [], None
        while True:
            page = self.get(**({'cursor':cursor} if cursor else {}))
            self.assertLessEqual(len(page['items']), 50)
            seen.extend(item['id'] for item in page['items'])
            self.assertTrue(all(item['observedAt'] is None for item in page['items']))
            cursor = page['nextCursor']
            if not cursor:
                break
            other = self.client.get('/api/factory/jobs', headers=self.headers('bob'), params={'cursor':cursor})
            self.assertEqual(other.status_code, 400, other.text)
        self.assertEqual(seen, sorted(self.identifiers, reverse=True))
        self.assertEqual(len(set(seen)), 205)
        self.assertEqual(self.client.get('/api/factory/jobs', headers=self.headers('bob')).json()['items'], [])

    def test_limits_and_forged_cursor(self):
        self.assertEqual(len(self.get(limit=100)['items']), 100)
        for limit in (0,101):
            self.assertEqual(self.client.get('/api/factory/jobs', headers=self.headers(), params={'limit':limit}).status_code, 422)
        cursor = self.get()['nextCursor']
        value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        value['createdAt'] = '2020-01-01T00:00:00+00:00'
        forged = base64.urlsafe_b64encode(canonical(value).encode()).decode()
        for invalid in ('garbage!', forged, 'e30', 'null'):
            self.assertEqual(self.client.get('/api/factory/jobs', headers=self.headers(), params={'cursor':invalid}).status_code, 400)

    def test_list_projection_and_detail_are_lifecycle_read_only(self):
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.store.engine, 'before_cursor_execute', capture)
        try:
            with mock.patch.object(self.state['bridge'], 'detail', side_effect=AssertionError('List read native detail')):
                page = self.get()
            history_selects = [s for s in statements if 'FROM af_tasks t JOIN af_plans' in s]
            self.assertEqual(len(history_selects), 1)
            self.assertFalse(any('af_effects' in s or 'af_events' in s for s in statements), statements)
            self.assertNotIn('definition', page['items'][0])
            response = self.client.get('/api/factory/jobs/' + self.identifiers[0], headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(any(s.lstrip().split()[0].upper() in {'UPDATE','INSERT','DELETE'} for s in statements), statements)
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', capture)

    def test_summary_observation_never_releases_or_reopens_capacity(self):
        task = self.store.task(self.identifiers[0], 'alice')
        before = task['body']
        self.store.observe_summary(task, 'running')
        self.assertEqual(self.store.task(task['id'])['body'], before)
        self.store.sql('UPDATE af_tasks SET terminal=FALSE WHERE id=:id', id=task['id'])
        try:
            self.store.observe_summary(task, 'unknown')
            current = self.store.task(task['id'])
            self.assertFalse(current['terminal'])
            self.assertEqual(current['body']['lastStatus'], 'unknown')
            self.assertIsNotNone(current['body']['observedAt'])
        finally:
            self.store.sql('UPDATE af_tasks SET terminal=TRUE,body=CAST(:body AS JSONB) WHERE id=:id', id=task['id'], body=canonical(before))

    def test_z_native_completion_waits_for_background_finalization_without_read_side_effects(self):
        plan = self.client.post('/api/factory/plans', headers=self.headers(), json={
            'topic': 'Actual checksum finalization fixture', 'mode': 'literature',
            'application': 'fixture-checksum', 'requestId': str(uuid4())}).json()
        response = self.client.post('/api/factory/instances', headers=self.headers(), json={
            'planId': plan['id'], 'requestId': str(uuid4())})
        self.assertEqual(response.status_code, 202, response.text)
        identifier = response.json()['id']
        task = self.store.task(identifier)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            native = self.store.native_db.get_job(task['run_id'])
            if native['status'] == 'completed':
                break
            time.sleep(.05)
        self.assertEqual(native['status'], 'completed', native)
        self.assertFalse(self.store.task(identifier)['terminal'])
        # A display-only observation may know native completion without owning
        # the durable stop proof. Neither list nor detail may release its hold.
        self.store.observe_summary(task, 'completed')
        before = self.store.task(identifier)
        detail = self.client.get('/api/factory/jobs/' + identifier, headers=self.headers()).json()
        self.assertEqual(detail['job']['status'], 'finalizing')
        self.assertEqual(next(item for item in self.get()['items'] if item['id'] == identifier)['status'], 'finalizing')
        self.assertEqual(self.store.task(identifier), before)
        observer = self.state['lifecycle_observer']
        self.client.portal.call(observer.start)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not self.store.task(identifier)['terminal']:
                time.sleep(.05)  # No detail or explicit reconcile drives this.
            current = self.store.task(identifier)
            self.assertTrue(current['terminal'], observer.last_result)
            self.assertEqual(current['body']['lastStatus'], 'completed')
            self.assertEqual(self.client.get('/api/factory/jobs/' + identifier, headers=self.headers()).json()['job']['status'], 'completed')
            self.assertEqual(next(item for item in self.get()['items'] if item['id'] == identifier)['status'], 'completed')
        finally:
            self.client.portal.call(observer.stop)

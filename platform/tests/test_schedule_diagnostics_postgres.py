# pyright: reportMissingImports=false
"""Real native claims and PG contention; diagnostics never replay an occurrence."""
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from agent_factory.catalog import create_plan
from agent_factory.config import Settings
from agent_factory.main import create_app
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class ScheduleDiagnosticsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        database = self.stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        workspace = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='schedule-diagnostics-'))
        settings = Settings(db_url=database.url, workspace=Path(workspace), max_workers=1, max_user_tasks=2)
        setattr(settings, 'schedule_poll_seconds', 3600)
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth, self.service = (self.state[key] for key in ('store', 'auth', 'schedules'))
        self.db = self.store.native_db
        self.stack.callback(self.store.engine.dispose)
        self.stack.callback(self.db.db_engine.dispose)
        self.client = self.stack.enter_context(TestClient(self.app))  # pyright: ignore[reportArgumentType]
        assert self.client.portal is not None
        self.portal = self.client.portal
        self.auth.authorization.unassign('bob', 'factory-user')
        self.auth.authorization.assign('bob', 'factory-manager')
        self.ids = []
        self.stack.callback(self.cleanup)

    def cleanup(self):
        self.auth.authorization.assign('manager', 'factory-manager')
        self.auth.directory.set_disabled('manager', False)
        for identifier in self.ids:
            self.service.set_enabled('manager', identifier, False)
            for occurrence in self.service.occurrences('manager', identifier):
                if occurrence['task_id']:
                    self.portal.call(self.service.cancel_occurrence, 'manager', identifier, occurrence['id'])

    def schedule(self):
        plan = create_plan(self.store, 'manager', 'diagnostic checksum fixture', 'literature', application='checksum')
        schedule = self.service.create('manager', plan['id'], 'diagnostic-' + uuid4().hex, '0 0 1 1 *')
        self.ids.append(schedule['id'])
        return schedule

    def claim(self, schedule):
        self.service.manager.update(schedule['id'], user_id='manager', next_run_at=int(time.time()) - 1)
        claimed = self.db.claim_due_schedule('diagnostic-fixture-' + uuid4().hex)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['id'], schedule['id'])
        return Schedule.from_dict(claimed)

    def execute_denied(self, claimed):
        with self.assertRaises(HTTPException):
            self.portal.call(self.service.execute, claimed, self.db)

    def get(self, path, *, owner='manager', status=200):
        response = self.client.get('/api/factory/schedule-management' + path,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner)})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def rows(self, identifier):
        return self.store.sql('SELECT * FROM af_schedule_diagnostics WHERE schedule_id=:id ORDER BY id', id=identifier)

    def effect_counts(self):
        return tuple(self.store.sql('SELECT count(*) AS n FROM ' + table)[0]['n']
            for table in ('af_tasks', 'af_schedule_occurrences', 'ai.agno_jobs'))

    def test_native_authority_loss_records_finite_denial_without_occurrence(self):
        for disable in (False, True):
            with self.subTest(disabled=disable):
                schedule = self.schedule()
                claim = self.claim(schedule)
                before = self.effect_counts()
                try:
                    if disable:
                        self.auth.directory.set_disabled('manager', True)
                    else:
                        self.auth.authorization.unassign('manager', 'factory-manager')
                    self.execute_denied(claim)
                finally:
                    self.auth.authorization.assign('manager', 'factory-manager')
                    self.auth.directory.set_disabled('manager', False)
                self.assertEqual(self.effect_counts(), before)
                rows = self.rows(schedule['id'])
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['reason_code'], 'AUTHORIZATION_DENIED')
                self.assertEqual(rows[0]['source'], 'native')

    def test_real_advisory_and_pool_contention_deduplicate_same_claim(self):
        schedule = self.schedule()
        claim = self.claim(schedule)
        before = self.effect_counts()
        with self.store.engine.connect() as holder:
            key = 'af_schedule:' + schedule['id']
            holder.execute(text('SELECT pg_advisory_lock(hashtext(:key))'), {'key': key})
            holder.commit()
            try:
                self.execute_denied(claim)
                first = self.rows(schedule['id'])
                self.execute_denied(claim)
                self.assertEqual(self.rows(schedule['id']), first)
            finally:
                holder.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': key})
                holder.commit()
        with self.service.lock_engine.connect():
            self.execute_denied(claim)
        self.assertEqual(self.effect_counts(), before)
        self.assertEqual(len(self.rows(schedule['id'])), 1)
        self.assertEqual(self.rows(schedule['id'])[0]['reason_code'], 'CLOCK_BUSY')
        current = self.db.get_schedule(schedule['id'])
        self.assertEqual(current['locked_by'], claim.locked_by)
        self.assertEqual(current['locked_at'], claim.locked_at)
        retained = self.rows(schedule['id'])
        with self.service.diagnostics.engine.connect(), self.service.lock_engine.connect():
            started = time.monotonic()
            self.execute_denied(claim)
            self.assertLess(time.monotonic() - started, 1, 'Diagnostic pool contention must remain bounded')
        self.assertEqual(self.rows(schedule['id']), retained)
        self.assertEqual(self.db.get_schedule(schedule['id'])['locked_by'], claim.locked_by)

    def test_claimed_pause_and_edit_denials_are_not_occurrences(self):
        for edit in (False, True):
            with self.subTest(edit=edit):
                schedule = self.schedule()
                claim = self.claim(schedule)
                before = self.effect_counts()
                if edit:
                    self.service.update('manager', schedule['id'], '0 1 1 1 *')
                else:
                    self.service.set_enabled('manager', schedule['id'], False)
                self.execute_denied(claim)
                self.assertEqual(self.effect_counts(), before)
                codes = {row['reason_code'] for row in self.rows(schedule['id'])}
                self.assertEqual(codes, {'CLAIM_CHANGED'} if edit else {'PAUSED'})

    def test_diagnostic_reads_are_owned_and_perform_no_mutation(self):
        schedule = self.schedule()
        claim = self.claim(schedule)
        self.service.set_enabled('manager', schedule['id'], False)
        self.execute_denied(claim)
        before = self.rows(schedule['id'])
        counts = self.effect_counts()
        sql = self.store.sql
        statements = []
        def track(statement, **parameters):
            statements.append(statement.lstrip().split(None, 1)[0].upper())
            return sql(statement, **parameters)
        with patch.object(self.store, 'sql', track), \
             patch.object(self.db, 'create_schedule_run', side_effect=AssertionError('GET wrote native history')), \
             patch.object(self.db, 'release_schedule', side_effect=AssertionError('GET released native claim')), \
             patch.object(self.service.diagnostics, 'record', side_effect=AssertionError('GET wrote diagnostics')):
            catalog = self.get('/diagnostic-schedules')
            self.assertIn(schedule['id'], [row['id'] for row in catalog['items']])
            for _ in range(2):
                projection = self.get('/' + schedule['id'] + '/diagnostics')
                self.assertEqual(projection['coverage'], 'retained-rejections-only')
                self.assertFalse(projection['snapshot'])
                self.assertEqual(projection['retention'], {'days': 30, 'maxRecords': 100})
            self.get('/' + schedule['id'] + '/diagnostics', owner='bob', status=404)
        self.assertTrue(set(statements) <= {'SELECT'})
        self.assertEqual(self.rows(schedule['id']), before)
        self.assertEqual(self.effect_counts(), counts)

    def test_original_accepted_occurrence_identity_survives_later_claim_denial(self):
        schedule = self.schedule()
        original = self.portal.call(self.service.trigger, 'manager', schedule['id'], str(uuid4()))
        self.assertEqual(original['status'], 'accepted')
        task = self.store.task(original['task_id'], 'manager')
        claim = self.claim(schedule)
        self.service.set_enabled('manager', schedule['id'], False)
        self.execute_denied(claim)
        self.get('/' + schedule['id'] + '/diagnostics')
        history = self.service.occurrences('manager', schedule['id'])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['id'], original['id'])
        self.assertEqual(history[0]['task_id'], original['task_id'])
        self.assertEqual(self.store.task(task['id'])['run_id'], task['run_id'])
        self.assertFalse(self.store.task(task['id'])['cancel_requested'])

    def test_retention_pagination_and_best_effort_never_change_admission(self):
        from datetime import datetime, timedelta, timezone
        from concurrent.futures import ThreadPoolExecutor
        from copy import copy
        schedule = self.schedule()
        claim = self.claim(schedule)
        diagnostics = self.service.diagnostics
        before = self.effect_counts()
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(lambda _: diagnostics.record(claim, 'same-claim', 'CLOCK_BUSY'), range(2)))
        self.assertEqual(len(self.rows(schedule['id'])), 1)
        foreign = copy(claim)
        foreign.user_id = 'bob'
        diagnostics.record(foreign, 'foreign', 'CLOCK_BUSY')
        self.assertEqual(len(self.rows(schedule['id'])), 1)
        fixed = datetime.now(timezone.utc)
        with patch('agent_factory.schedule_diagnostics.datetime') as clock:
            clock.now.return_value = fixed
            for number in range(105):
                diagnostics.record(claim, 'retention-' + str(number), 'CLOCK_BUSY')
            self.assertEqual(len(self.rows(schedule['id'])), 100)
            seen, cursor = [], None
            while True:
                page = self.get('/' + schedule['id'] + '/diagnostics' + ('?after=' + cursor if cursor else ''))
                seen.extend(row['id'] for row in page['items'])
                cursor = page['nextCursor']
                if cursor is None:
                    break
            self.assertEqual(len(seen), 100)
            self.assertEqual(len(set(seen)), 100)
            self.get('/' + schedule['id'] + '/diagnostics?after=' + seen[0], owner='bob', status=404)
            persisted = self.rows(schedule['id'])
            clock.now.return_value = fixed + timedelta(days=31)
            self.assertEqual(self.get('/' + schedule['id'] + '/diagnostics')['items'], [])
            self.assertEqual(self.rows(schedule['id']), persisted, 'GET must not prune expired records')
            diagnostics.record(claim, 'new-window', 'CLOCK_BUSY')
            self.assertEqual(len(self.rows(schedule['id'])), 1)
        with patch.object(diagnostics.engine, 'begin', side_effect=RuntimeError('Synthetic diagnostic storage failure')):
            diagnostics.record(claim, 'failed-observation', 'CLOCK_BUSY')
        self.assertEqual(self.effect_counts(), before)

    def test_current_read_only_grant_can_inspect_denial_but_not_editor(self):
        schedule = self.schedule()
        claim = self.claim(schedule)
        self.auth.authorization.set_role_scopes('diagnostic-reader', ['agents:factory-executor:read'])
        self.auth.authorization.unassign('manager', 'factory-manager')
        self.auth.authorization.assign('manager', 'diagnostic-reader')
        try:
            self.auth.require('manager', 'read')
            with self.assertRaises(HTTPException):
                self.auth.require('manager', 'run')
            self.execute_denied(claim)
            page = self.get('/' + schedule['id'] + '/diagnostics')
            self.assertEqual(page['items'][0]['reasonCode'], 'AUTHORIZATION_DENIED')
            self.get('/diagnostic-schedules')
            self.get('/' + schedule['id'], status=403)
            self.auth.authorization.unassign('manager', 'diagnostic-reader')
            self.get('/' + schedule['id'] + '/diagnostics', status=403)
            self.get('/diagnostic-schedules', status=403)
        finally:
            self.auth.authorization.unassign('manager', 'diagnostic-reader')
            self.auth.authorization.assign('manager', 'factory-manager')

    def test_pending_editor_is_not_recovered_by_diagnostics_and_cursor_is_schedule_scoped(self):
        schedule = self.schedule()
        claim = self.claim(schedule)
        self.service.set_enabled('manager', schedule['id'], False)
        self.execute_denied(claim)
        other = self.schedule()
        other_claim = self.claim(other)
        self.service.set_enabled('manager', other['id'], False)
        self.execute_denied(other_claim)
        other_cursor = self.rows(other['id'])[0]['id']
        management = self.state['schedule_management']
        projected = management.inspect('manager', schedule['id'])
        original = self.service.manager.enable
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError('Synthetic committed editor acknowledgement loss')
        with patch.object(self.service.manager, 'enable', lost):
            with self.assertRaises(HTTPException) as uncertain:
                management.mutate('manager', 'enabled', {'enabled': True, 'requestId': str(uuid4()),
                    'expectedDefinitionFingerprint': projected['definitionFingerprint']}, schedule['id'])
            self.assertEqual(uncertain.exception.status_code, 409)
        try:
            pending = self.store.sql('SELECT * FROM af_schedule_editor_commands WHERE schedule_id=:id', id=schedule['id'])
            self.assertTrue(any(row['status'] == 'pending' for row in pending))
            with patch.object(management, '_read_recover', side_effect=AssertionError('Diagnostic GET repaired editor')):
                self.get('/' + schedule['id'] + '/diagnostics')
                self.get('/diagnostic-schedules')
                self.get('/' + schedule['id'] + '/diagnostics?after=' + other_cursor, status=404)
            self.assertEqual(self.store.sql('SELECT * FROM af_schedule_editor_commands WHERE schedule_id=:id',
                id=schedule['id']), pending)
        finally:
            management.inspect('manager', schedule['id'])

    def test_diagnostic_storage_failure_preserves_original_execute_http_error(self):
        schedule = self.schedule()
        claim = self.claim(schedule)
        before = self.effect_counts()
        with self.service.lock_engine.connect():
            with self.assertRaises(HTTPException) as normal:
                self.portal.call(self.service.execute, claim, self.db)
            retained = self.rows(schedule['id'])
            with patch.object(self.service.diagnostics.engine, 'begin',
                    side_effect=RuntimeError('Synthetic diagnostic-only storage failure')):
                with self.assertRaises(HTTPException) as failed:
                    self.portal.call(self.service.execute, claim, self.db)
        self.assertEqual((failed.exception.status_code, failed.exception.detail),
            (normal.exception.status_code, normal.exception.detail))
        self.assertEqual(self.rows(schedule['id']), retained)
        self.assertEqual(self.effect_counts(), before)
        self.assertEqual(self.db.get_schedule(schedule['id'])['locked_by'], claim.locked_by)

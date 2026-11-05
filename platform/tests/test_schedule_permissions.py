"""Current native membership drive schedule writes and action projections."""
from contextlib import nullcontext

from fixture_auth import initialize_members
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.db.schemas.scheduler import Schedule
from agno.db.sqlite import SqliteDb
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agent_factory.auth import AuthService
from agent_factory.main import http_error
from agent_factory.schedule_management import ScheduleManagement
from agent_factory.scheduling import ENDPOINT, MANAGED_BY, SchedulingService
from agent_factory.store import digest


class ScheduleMemberPermissionTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        database = SqliteDb(db_file=str(Path(folder) / 'schedule-permissions.sqlite'))
        self.addCleanup(database.db_engine.dispose)
        settings = SimpleNamespace(jwt_key='synthetic-schedule-signing-key-0000000000',
            max_user_tasks=1, max_total_tasks=4)
        self.auth = AuthService(settings, database)
        initialize_members(self.auth)
        self.service = object.__new__(SchedulingService)
        self.service.auth, self.service.settings = self.auth, settings
        self.plan = {'id': 'owned-plan', 'ownerId': 'alice', 'fingerprint': 'original-plan'}
        self.service.store = SimpleNamespace(sql=Mock(return_value=[]), plan=Mock(return_value=self.plan))
        self.management = ScheduleManagement(self.service)

    def test_active_member_write_metadata_and_actions(self):
        self.auth.require_member('alice')
        self.service._require_write('alice')
        metadata = self.management.metadata('alice')
        self.assertEqual((metadata['ownerId'], metadata['canManage']), ('alice', True))
        for enabled in (False, True):
            schedule = Schedule(id='owned-schedule', user_id='alice', name='Owned fixture',
                cron_expr='0 0 1 1 *', timezone='Etc/UTC', endpoint=ENDPOINT,
                enabled=enabled, managed_by=MANAGED_BY)
            self.service._bound = Mock(return_value=(schedule,
                {'plan_id': self.plan['id'], 'plan_hash': digest(self.plan)}))
            projected = self.management._project('alice', schedule.id)
            self.assertEqual(projected['allowedActions'], ['edit', 'disable' if enabled else 'enable'])
            self.assertEqual(projected['ownerId'], 'alice')
            self.service._bound.assert_called_once_with(schedule.id, 'alice')

    def test_disabled_or_unregistered_member_cannot_manage_or_read_metadata(self):
        self.auth.directory.set_disabled('alice', True)
        for owner in ('alice', 'unregistered'):
            for operation in (self.service._require_write, self.management.metadata):
                with self.subTest(owner=owner, operation=operation.__name__):
                    with self.assertRaises(HTTPException) as denied:
                        operation(owner)
                    self.assertEqual(denied.exception.status_code, 403)

    def test_editor_marks_only_known_preintent_rejection(self):
        self.service._lock = Mock(return_value=nullcontext())
        self.service.db = Mock()
        self.service._plan = Mock(side_effect=HTTPException(409, 'INACTIVE_APPLICATION'))
        body = {'requestId': 'rejected-schedule', 'planId': self.plan['id'], 'name': 'Owned fixture',
                'cron': '0 0 1 1 *', 'timezone': 'Etc/UTC'}
        with self.assertRaises(HTTPException) as rejected:
            self.management.mutate('alice', 'create', body)
        self.assertEqual(rejected.exception.headers, {'X-Factory-Command-Rejected': 'true'})
        self.assertFalse(any('INSERT INTO af_schedule_editor_commands' in call.args[0]
                             for call in self.service.store.sql.call_args_list))
        self.service.db.create_schedule.assert_not_called()
        self.service._plan.side_effect = HTTPException(503, 'Directory unavailable')
        with self.assertRaises(HTTPException) as unavailable:
            self.management.mutate('alice', 'create', body)
        self.assertIsNone(unavailable.exception.headers)

    def test_native_editor_failure_stays_unknown_after_the_single_plan_check(self):
        self.service._lock = Mock(return_value=nullcontext())
        self.service._plan = Mock(return_value=self.plan)
        self.service.db = Mock()
        self.service.db.get_schedule_by_name.return_value = None
        self.service.db.create_schedule.side_effect = HTTPException(409, 'INACTIVE_APPLICATION')
        body = {'requestId': 'unknown-schedule', 'planId': self.plan['id'], 'name': 'Owned fixture',
                'cron': '0 0 1 1 *', 'timezone': 'Etc/UTC'}
        with self.assertRaises(HTTPException) as unknown:
            self.management.mutate('alice', 'create', body)
        self.assertEqual(unknown.exception.detail, 'SCHEDULE_EDITOR_UNKNOWN')
        self.assertIsNone(unknown.exception.headers)
        self.service._plan.assert_called_once_with(self.plan['id'], 'alice')
        self.service.db.create_schedule.assert_called_once()
        self.assertTrue(any('INSERT INTO af_schedule_editor_commands' in call.args[0]
                            for call in self.service.store.sql.call_args_list))

    def test_http_editor_prewrite_rejection_preserves_headers_for_both_detail_shapes(self):
        self.service._lock = Mock(return_value=nullcontext())
        self.service.db = Mock()
        self.service._plan = Mock()
        app = FastAPI()
        app.exception_handler(HTTPException)(http_error)

        @app.post('/schedule-command')
        def submit():
            return self.management.mutate('alice', 'create', {'requestId': 'rejected-http-command',
                'planId': self.plan['id'], 'name': 'Owned fixture', 'cron': '0 0 1 1 *', 'timezone': 'Etc/UTC'})

        details = [('INACTIVE_APPLICATION: withdrawn fixture',
                    {'message': 'INACTIVE_APPLICATION: withdrawn fixture', 'code': 'INACTIVE_APPLICATION'}),
                   ({'message': 'Withdrawn fixture', 'code': 'INACTIVE_APPLICATION'},
                    {'message': 'Withdrawn fixture', 'code': 'INACTIVE_APPLICATION'})]
        with TestClient(app) as client:
            for detail, expected in details:
                self.service._plan.side_effect = HTTPException(409, detail, headers={'X-Original': 'preserved'})
                with self.subTest(detail=detail):
                    response = client.post('/schedule-command')
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json(), expected)
                    self.assertEqual(response.headers.get('X-Factory-Command-Rejected'), 'true')
                    self.assertEqual(response.headers.get('X-Original'), 'preserved')
        self.service.db.create_schedule.assert_not_called()
        self.assertFalse(any('INSERT INTO af_schedule_editor_commands' in call.args[0]
                             for call in self.service.store.sql.call_args_list))

    def test_http_native_boundary_failure_never_claims_a_prewrite_rejection(self):
        self.service._lock = Mock(return_value=nullcontext())
        self.service._plan = Mock(return_value=self.plan)
        self.service.db = Mock()
        self.service.db.get_schedule_by_name.return_value = None
        self.service.db.create_schedule.side_effect = HTTPException(409, 'INACTIVE_APPLICATION')
        app = FastAPI()
        app.exception_handler(HTTPException)(http_error)

        @app.post('/schedule-command')
        def submit():
            return self.management.mutate('alice', 'create', {'requestId': 'unknown-http-command',
                'planId': self.plan['id'], 'name': 'Owned fixture', 'cron': '0 0 1 1 *', 'timezone': 'Etc/UTC'})

        with TestClient(app) as client:
            response = client.post('/schedule-command')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {'message': 'SCHEDULE_EDITOR_UNKNOWN', 'code': 'REQUEST_REJECTED'})
        self.assertNotIn('X-Factory-Command-Rejected', response.headers)
        self.service.db.create_schedule.assert_called_once()
        self.assertTrue(any('INSERT INTO af_schedule_editor_commands' in call.args[0]
                            for call in self.service.store.sql.call_args_list))

    def test_completed_command_recovers_without_touching_a_later_unknown_command(self):
        commands = {'completed-a': {'request_id': 'completed-a', 'schedule_id': 'owned-schedule', 'status': 'complete'},
                    'unknown-b': {'request_id': 'unknown-b', 'schedule_id': 'owned-schedule', 'status': 'pending'}}
        self.service._lock = Mock(return_value=nullcontext())
        self.service.store.sql.side_effect = lambda statement, **params: [commands[params['request']]]
        self.management._project = Mock(side_effect=HTTPException(409, 'SCHEDULE_EDITOR_UNKNOWN'))
        receipt = self.management.recover('alice', 'completed-a')
        self.assertEqual(receipt, {'ownerId': 'alice', 'scheduleId': 'owned-schedule',
            'commandId': 'completed-a', 'commandStatus': 'complete', 'schedule': None})
        self.assertEqual(commands['unknown-b']['status'], 'pending')
        self.assertTrue(all('SELECT' in call.args[0] for call in self.service.store.sql.call_args_list[1:]))
        for status in (403, 503):
            self.management._project.side_effect = HTTPException(status, 'Unavailable')
            with self.subTest(status=status), self.assertRaises(HTTPException) as rejected:
                self.management.recover('alice', 'completed-a')
            self.assertEqual(rejected.exception.status_code, status)

"""Current native member grants drive schedule writes and action projections."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.db.schemas.scheduler import Schedule
from agno.db.sqlite import SqliteDb
from fastapi import HTTPException

from agent_factory.auth import AuthService
from agent_factory.schedule_management import ScheduleManagement
from agent_factory.scheduling import ENDPOINT, MANAGED_BY, SchedulingService
from agent_factory.store import digest


class ScheduleMemberPermissionTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        database = SqliteDb(db_file=str(Path(folder) / 'schedule-permissions.sqlite'))
        self.addCleanup(database.db_engine.dispose)
        settings = SimpleNamespace(demo=True, jwt_key='synthetic-schedule-signing-key-0000000000',
            max_user_tasks=1, max_total_tasks=4)
        self.auth = AuthService(settings, database)
        self.auth.initialize_demo()
        self.service = object.__new__(SchedulingService)
        self.service.auth, self.service.settings = self.auth, settings
        self.plan = {'id': 'owned-plan', 'ownerId': 'alice', 'fingerprint': 'original-plan'}
        self.service.store = SimpleNamespace(sql=Mock(return_value=[]), plan=Mock(return_value=self.plan))
        self.management = ScheduleManagement(self.service)

    def test_member_write_metadata_and_actions_need_current_run_only(self):
        with self.assertRaises(HTTPException) as denied:
            self.auth.require('alice', 'components:write')
        self.assertEqual(denied.exception.status_code, 403)
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

    def test_revoked_or_disabled_member_cannot_manage_or_read_metadata(self):
        for revoked in (True, False):
            with self.subTest(revoked=revoked):
                if revoked:
                    self.auth.authorization.unassign('alice', 'factory-user')
                else:
                    self.auth.directory.set_disabled('alice', True)
                try:
                    for operation in (self.service._require_write, self.management.metadata):
                        with self.assertRaises(HTTPException) as denied:
                            operation('alice')
                        self.assertEqual(denied.exception.status_code, 403)
                finally:
                    self.auth.authorization.assign('alice', 'factory-user')
                    self.auth.directory.set_disabled('alice', False)

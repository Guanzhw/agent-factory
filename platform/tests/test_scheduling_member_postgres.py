"""Member schedule HTTP journeys on isolated PG with the offline checksum fixture."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_factory.schedule_contract import preview_schedule
from agent_factory_research.config import ResearchSettings
from agent_factory_server.main import create_app, factory_state
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class MemberSchedulingPostgresTests(unittest.TestCase):
    def setUp(self):
        database = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        workspace = self.enterContext(TemporaryDirectory(prefix='member-schedules-'))
        settings = ResearchSettings(db_url=database.url, workspace=Path(workspace), max_workers=1,
            max_user_tasks=1, temporary_policy='member-self-service')
        app = create_app(settings)
        self.state = factory_state(app)
        self.store, self.auth, self.service = (self.state[key] for key in ('store', 'auth', 'schedules'))
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = self.enterContext(TestClient(app))
        # Keep the original authenticated tokens across current grant/disabled changes.
        self.tokens = {owner: self.auth._issue_native_token(owner) for owner in ('alice', 'bob')}
        self.enterContext(patch('agent_factory.schedule_management.preview_schedule',
            side_effect=lambda cron, zone: preview_schedule(cron, zone, now_epoch=1893456000)))
        self.plan = self.request('POST', '/plans', self.command(topic='Offline scheduled checksum',
            application='checksum', mode='literature'), status=201)
        self.assertTrue(self.plan['authorization']['executionAllowed'])
        self.assertFalse(self.plan['authorization']['reviewRequired'])
        for owner in ('alice', 'bob'):
            self.auth.require_member(owner)

    @staticmethod
    def command(**body):
        return {'requestId': str(uuid4()), **body}

    def request(self, method, path, body=None, *, owner='alice', status=200):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.tokens[owner]})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def creation(self):
        return self.command(planId=self.plan['id'], name='member-' + uuid4().hex,
            cron='0 0 1 1 *', timezone='Etc/UTC')

    def enabled(self, schedule, enabled):
        return self.request('POST', '/schedule-management/' + schedule['id'] + '/enabled',
            self.command(enabled=enabled, expectedDefinitionFingerprint=schedule['definitionFingerprint']))

    def test_member_http_editor_and_schedule_actions_keep_original_receipts(self):
        metadata = self.request('GET', '/schedule-management/metadata')
        self.assertEqual((metadata['ownerId'], metadata['canManage']), ('alice', True))
        create = self.creation()
        schedule = self.request('POST', '/schedule-management', create, status=201)
        self.assertEqual(schedule['allowedActions'], ['edit', 'enable'])
        self.assertFalse(schedule['enabled'])
        self.assertEqual(self.request('POST', '/schedule-management', create, status=201), schedule)
        path = '/schedule-management/' + schedule['id']
        update = self.command(cron='0 3 1 1 *', timezone='Asia/Shanghai',
            expectedDefinitionFingerprint=schedule['definitionFingerprint'])
        changed = self.request('PATCH', path, update)
        self.assertEqual(self.request('PATCH', path, update), changed)
        self.assertEqual(self.request('GET', '/schedule-management/commands/' + update['requestId']), changed)
        self.request('PATCH', path, {**update, 'requestId': str(uuid4())}, status=409)
        enabled = self.enabled(changed, True)
        self.assertEqual(enabled['allowedActions'], ['edit', 'disable'])
        trigger = self.command()
        with patch.object(self.service.bridge, 'submit', wraps=self.service.bridge.submit) as submit:
            first = self.request('POST', '/schedules/' + schedule['id'] + '/trigger', trigger, status=202)
            repeated = self.request('POST', '/schedules/' + schedule['id'] + '/trigger', trigger, status=202)
        self.assertEqual(first['status'], 'accepted')
        self.assertEqual((first['id'], first['task_id'], first['request_id']),
            (repeated['id'], repeated['task_id'], repeated['request_id']))
        self.assertEqual(submit.await_count, 1)
        self.assertFalse(self.enabled(enabled, False)['enabled'])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            task = self.store.task(first['task_id'], 'alice')
            ticket = self.store.native_db.get_job(task['run_id']) if task['run_id'] else None
            if ticket and ticket['status'] in {'completed', 'failed', 'cancelled'}:
                self.assertEqual(ticket['status'], 'completed')
                break
            time.sleep(.05)
        else:
            self.fail('Offline native scheduled checksum did not finish')
        self.assertFalse(task['cancel_requested'])
        self.assertTrue(self.store.artifacts(task['id']))
        history = self.request('GET', path + '/occurrences')['items']
        self.assertEqual([(item['taskId'], item['nativeRunId']) for item in history], [(task['id'], task['run_id'])])
        self.assertEqual(self.request('GET', '/schedule-management/commands/' + create['requestId'])['id'], schedule['id'])
        # The older public route shares the same member/owner gate.
        native = self.request('POST', '/schedules', {key: value for key, value in self.creation().items()
            if key != 'requestId'}, status=201)
        native_path = '/schedules/' + native['id']
        updated = self.request('PATCH', native_path, {'cron': '0 4 1 1 *', 'timezone': 'Etc/UTC'})
        self.assertEqual(updated['cron_expr'], '0 4 1 1 *')
        self.assertFalse(self.request('POST', native_path + '/enabled', {'enabled': False})['enabled'])
        self.assertTrue(self.request('POST', native_path + '/enabled', {'enabled': True})['enabled'])
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_tasks')[0]['n'], 1)

    def test_current_run_and_plan_authority_and_cross_owner_are_rechecked(self):
        create = self.creation()
        schedule = self.enabled(self.request('POST', '/schedule-management', create, status=201), True)
        editor = '/schedule-management/' + schedule['id']
        native = '/schedules/' + schedule['id']
        update = self.command(cron='0 4 1 1 *', timezone='Etc/UTC',
            expectedDefinitionFingerprint=schedule['definitionFingerprint'])
        enable = self.command(enabled=False, expectedDefinitionFingerprint=schedule['definitionFingerprint'])
        operations = [('GET', editor, None), ('PATCH', editor, update), ('POST', editor + '/enabled', enable),
            ('GET', native, None), ('PATCH', native, {'cron': '0 4 1 1 *', 'timezone': 'Etc/UTC'}),
            ('POST', native + '/enabled', {'enabled': False}), ('POST', native + '/trigger', self.command()),
            ('GET', editor + '/occurrences', None),
            ('GET', '/schedule-management/commands/' + create['requestId'], None)]
        for method, path, body in operations:
            with self.subTest(owner='bob', path=path, method=method):
                self.request(method, path, body, owner='bob', status=404)
        self.request('POST', '/schedule-management', self.creation(), owner='bob', status=404)
        self.request('POST', '/schedules', {key: value for key, value in self.creation().items()
            if key != 'requestId'}, owner='bob', status=404)
        self.assertEqual(self.request('GET', '/schedule-management', owner='bob')['items'], [])
        self.auth.directory.set_disabled('alice', True)
        try:
            for method, path, body in [('GET', '/schedule-management/metadata', None),
                    ('POST', '/schedule-management', self.creation()), *operations]:
                with self.subTest(owner='disabled-alice', path=path, method=method):
                    self.request(method, path, body, status=403)
        finally:
            self.auth.directory.set_disabled('alice', False)
        self.assertEqual(self.request('GET', editor), schedule)
        self.assertFalse(self.enabled(schedule, False)['enabled'])
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_tasks')[0]['n'], 0)
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_schedule_occurrences')[0]['n'], 0)

    def test_member_lost_ack_and_unknown_trigger_never_redispatch(self):
        create = self.creation()
        original_create = self.service.db.create_schedule
        def lost_create(value):
            original_create(value)
            raise TimeoutError('Synthetic committed schedule acknowledgement loss')
        with patch.object(self.service.db, 'create_schedule', side_effect=lost_create) as native_create:
            self.request('POST', '/schedule-management', create, status=409)
            recovered = self.request('GET', '/schedule-management/commands/' + create['requestId'])
            self.assertEqual(self.request('POST', '/schedule-management', create, status=201), recovered)
            self.assertEqual(native_create.call_count, 1)
        self.assertEqual(recovered['requestId'], create['requestId'])
        schedule = self.enabled(recovered, True)
        request = self.command()
        path = '/schedules/' + schedule['id'] + '/trigger'
        with patch.object(self.service.bridge, 'submit', side_effect=TimeoutError('Synthetic admission loss')) as submit:
            first = self.request('POST', path, request, status=202)
            repeated = self.request('POST', path, request, status=202)
            self.assertEqual(first['status'], 'unknown')
            self.assertEqual(repeated['status'], 'unknown')
            self.assertEqual((first['id'], first['task_id'], first['request_id']),
                (repeated['id'], repeated['task_id'], repeated['request_id']))
            self.assertEqual(submit.await_count, 1)
            self.request('POST', path, request, owner='bob', status=404)
            rejected = self.request('POST', path, self.command(), status=202)
            self.assertEqual(rejected['status'], 'rejected')
            self.assertEqual(submit.await_count, 1)
        task = self.store.task(first['task_id'], 'alice')
        self.assertFalse(task['terminal'])
        self.assertIsNone(task['run_id'])
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_tasks')[0]['n'], 1)

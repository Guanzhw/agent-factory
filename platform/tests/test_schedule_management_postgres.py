# pyright: reportMissingImports=false
"""Native schedule editor commands on isolated PG; no wall-clock cron waiting."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.schedule_contract import preview_schedule
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class ScheduleManagementPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        workspace = tempfile.TemporaryDirectory(prefix='schedule-management-')
        self.addCleanup(workspace.cleanup)
        self.settings = Settings(db_url=self.database.url, workspace=Path(workspace.name),
            max_workers=1, max_user_tasks=1, temporary_policy='admin-review')
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store = self.state['store']
        self.auth = self.state['auth']
        self.service = self.state['schedules']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(self.app).__enter__()  # pyright: ignore[reportArgumentType]
        self.addCleanup(self.client.__exit__, None, None, None)
        assert self.client.portal is not None
        self.portal = self.client.portal
        self.auth.authorization.unassign('bob', 'factory-user')
        self.auth.authorization.assign('bob', 'factory-manager')
        # Future fixed preview avoids native due runs entirely; explicit trigger
        # still uses the real existing admission/native executor path.
        clock = patch('agent_factory.schedule_management.preview_schedule',
            side_effect=lambda cron, zone: preview_schedule(cron, zone, now_epoch=1893456000))
        clock.start(); self.addCleanup(clock.stop)
        self.plan = self.post('/plans', {'topic': 'Scheduled original checksum fixture',
            'application': 'checksum', 'mode': 'literature', 'requestId': str(uuid4())}, status=201)
        review = self.post('/plan-reviews', self.command(planId=self.plan['id']), status=201)
        self.post('/plan-reviews/' + review['id'] + '/decision', self.command(approved=True), owner='bob')

    def command(self, **body):
        return {'requestId': str(uuid4()), **body}

    def request(self, method, path, body=None, *, owner='manager', status=200):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner)})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def post(self, path, body=None, **kwargs):
        return self.request('POST', path, body, **kwargs)

    def create(self):
        body = self.command(planId=self.plan['id'], name='owned-' + uuid4().hex,
            cron='0 0 1 1 *', timezone='Etc/UTC')
        return self.post('/schedule-management', body, status=201), body

    def enabled(self, schedule, value):
        return self.post('/schedule-management/' + schedule['id'] + '/enabled',
            self.command(enabled=value, expectedDefinitionFingerprint=schedule['definitionFingerprint']))

    def wait_native(self, task):
        end = time.monotonic() + 20
        while time.monotonic() < end:
            value = self.store.task(task, 'manager')
            job = self.store.native_db.get_job(value['run_id']) if value['run_id'] else None
            if job and job['status'] in {'completed', 'failed', 'cancelled'}:
                self.assertEqual(job['status'], 'completed', job)
                return value
            time.sleep(.05)
        self.fail('Native scheduled checksum did not settle')

    def test_creation_lost_ack_exact_metadata_recovery_and_owner_isolation(self):
        original = self.service.db.create_schedule
        calls = []
        def lost(value):
            calls.append(value['id'])
            original(value)
            raise TimeoutError('Synthetic committed metadata acknowledgement loss')
        body = self.command(planId=self.plan['id'], name='lost-' + uuid4().hex, cron='0 0 1 1 *', timezone='Etc/UTC')
        with patch.object(self.service.db, 'create_schedule', lost):
            self.post('/schedule-management', body, status=409)
            stale_pending = self.store.sql('SELECT * FROM af_schedule_editor_commands WHERE owner_id=:owner AND request_id=:request',
                owner='manager', request=body['requestId'])[0]
            self.assertEqual(stale_pending['status'], 'pending')
            by_command = self.request('GET', '/schedule-management/commands/' + body['requestId'])
            self.assertFalse(by_command['enabled'])
            self.request('GET', '/schedule-management/commands/' + body['requestId'], owner='bob', status=404)
            listed = self.request('GET', '/schedule-management')
            self.assertEqual(len(listed['items']), 1)
            recovered = self.post('/schedule-management', body, status=201)
            self.assertEqual(by_command['id'], recovered['id'])
        self.assertEqual(calls, [recovered['id']])
        self.assertEqual(recovered['requestId'], body['requestId'])
        self.assertFalse(recovered['enabled'])
        enabled = self.enabled(recovered, True)
        paused = self.enabled(enabled, False)
        with self.service._lock(recovered['id']):
            self.state['schedule_management']._recover('manager', stale_pending)
        after_stale = self.request('GET', '/schedule-management/' + recovered['id'])
        self.assertEqual(after_stale['definitionFingerprint'], paused['definitionFingerprint'])
        self.assertEqual(after_stale['lastCommandId'], paused['lastCommandId'])
        self.post('/schedule-management', {**body, 'cron': '0 1 1 1 *'}, status=409)
        self.request('GET', '/schedule-management/' + recovered['id'], owner='bob', status=404)
        self.request('GET', '/schedule-management/' + recovered['id'] + '/occurrences', owner='bob', status=404)
        self.assertFalse(listed['snapshot'])
        native_enable = self.service.manager.enable
        def lost_enable(*args, **kwargs):
            native_enable(*args, **kwargs)
            raise TimeoutError('Synthetic committed enable acknowledgement loss')
        with patch.object(self.service.manager, 'enable', lost_enable):
            self.post('/schedule-management/' + recovered['id'] + '/enabled',
                self.command(enabled=True, expectedDefinitionFingerprint=paused['definitionFingerprint']), status=409)
        before_tasks = self.store.sql('SELECT count(*) AS count FROM af_tasks')[0]['count']
        for operation in (lambda: self.service.set_enabled('manager', recovered['id'], False),
                          lambda: self.service.update('manager', recovered['id'], '0 3 1 1 *', 'Etc/UTC')):
            with self.assertRaises(HTTPException) as blocked:
                operation()
            self.assertEqual(blocked.exception.status_code, 409)
            self.assertEqual(blocked.exception.detail, 'SCHEDULE_EDITOR_UNKNOWN: reconcile the original editor receipt')
        self.post('/schedules/' + recovered['id'] + '/trigger', self.command(), status=409)
        self.assertEqual(self.store.sql('SELECT count(*) AS count FROM af_tasks')[0]['count'], before_tasks)
        resolved = self.request('GET', '/schedule-management/' + recovered['id'])
        self.assertTrue(resolved['enabled'])
        self.assertFalse(self.enabled(resolved, False)['enabled'])

    def test_edit_cas_pause_resume_with_one_metadata_connection(self):
        # Real size-one pool plus independent editor lock pool: nested metadata
        # reads/writes must complete, without broad timeout or fake connection.
        old = self.store.engine
        small = create_engine(old.url, pool_size=1, max_overflow=0, pool_timeout=.2)
        self.store.engine = small
        try:
            schedule, _ = self.create()
            path = '/schedule-management/' + schedule['id']
            body = self.command(cron='0 2 1 1 *', timezone='Asia/Shanghai',
                expectedDefinitionFingerprint=schedule['definitionFingerprint'])
            changed = self.request('PATCH', path, body)
            self.assertNotEqual(changed['definitionFingerprint'], schedule['definitionFingerprint'])
            self.assertEqual(self.request('PATCH', path, body)['id'], schedule['id'])
            self.request('PATCH', path, {**body, 'requestId': str(uuid4())}, status=409)
            enabled = self.enabled(changed, True)
            self.assertTrue(enabled['enabled'])
            self.post(path + '/enabled', self.command(enabled='false',
                expectedDefinitionFingerprint=enabled['definitionFingerprint']), status=422)
            paused = self.enabled(enabled, False)
            self.assertFalse(paused['enabled'])
            self.assertEqual(self.enabled(paused, True)['planId'], self.plan['id'])
        finally:
            self.store.engine = old
            small.dispose()

    def test_pause_fences_stale_claim_without_cancelling_accepted_occurrence(self):
        schedule, _ = self.create()
        schedule = self.enabled(schedule, True)
        claimed, _ = self.service._bound(schedule['id'], 'manager')
        trigger = self.command()
        receipt = self.post('/schedules/' + schedule['id'] + '/trigger', trigger, status=202)
        self.enabled(schedule, False)
        with self.assertRaises(HTTPException) as denied:
            self.portal.call(self.service._fire, claimed, 'manual:stale-paused-claim', False)
        self.assertEqual(denied.exception.status_code, 409)
        task = self.wait_native(receipt['task_id'])
        self.assertFalse(task['cancel_requested'])
        history = self.request('GET', '/schedule-management/' + schedule['id'] + '/occurrences')
        self.assertEqual(len(history['items']), 1)
        self.assertEqual(history['items'][0]['nativeRunId'], task['run_id'])
        self.assertTrue(self.store.artifacts(task['id']))
        self.post('/schedules/' + schedule['id'] + '/trigger', self.command(), status=409)

    def test_unknown_without_native_ack_holds_budget_and_restart_never_replays(self):
        schedule, _ = self.create()
        schedule = self.enabled(schedule, True)
        real = self.service.bridge
        class NoAcknowledgement:
            calls = 0
            async def submit(self, *args):
                self.calls += 1
                raise TimeoutError('Synthetic unknown before native delivery')
            async def find_run(self, *args):
                return await real.find_run(*args)
        unknown = NoAcknowledgement()
        self.service.bridge = unknown
        try:
            command = self.command()
            path = '/schedules/' + schedule['id'] + '/trigger'
            first = self.post(path, command, status=202)
            self.assertEqual(first['status'], 'unknown')
            self.portal.call(self.service.stop)
            self.portal.call(self.service.start)
            repeated = self.post(path, command, status=202)
            self.assertEqual(first['task_id'], repeated['task_id'])
            self.assertEqual(unknown.calls, 1)
            self.assertFalse(self.store.task(first['task_id'])['terminal'])
            rejected = self.post(path, self.command(), status=202)
            self.assertEqual(rejected['status'], 'rejected')
            self.assertEqual(unknown.calls, 1)
            self.auth.authorization.unassign('manager', 'factory-manager')
            try:
                self.post(path, self.command(), status=403)
            finally:
                self.auth.authorization.assign('manager', 'factory-manager')
        finally:
            self.service.bridge = real

    def test_pending_editor_does_not_block_original_paused_occurrence_history_or_cancel(self):
        self.plan = self.post('/plans', {'topic': 'sort', 'application': 'research',
            'mode': 'literature', 'requestId': str(uuid4())}, status=201)
        review = self.post('/plan-reviews', self.command(planId=self.plan['id']), status=201)
        self.post('/plan-reviews/' + review['id'] + '/decision', self.command(approved=True), owner='bob')
        schedule, _ = self.create()
        schedule = self.enabled(schedule, True)
        accepted = self.post('/schedules/' + schedule['id'] + '/trigger', self.command(), status=202)
        deadline = time.monotonic() + 20
        original = None
        while time.monotonic() < deadline:
            original = self.store.task(accepted['task_id'], 'manager')
            job = self.service.db.get_job(original['run_id']) if original['run_id'] else None
            if job and job['status'] == 'paused':
                break
            time.sleep(.05)
        else:
            self.fail('Original scheduled native task did not pause')
        assert original is not None
        native_disable = self.service.manager.disable
        def lost_disable(*args, **kwargs):
            native_disable(*args, **kwargs)
            raise TimeoutError('Synthetic committed disable acknowledgement loss')
        with patch.object(self.service.manager, 'disable', lost_disable):
            self.post('/schedule-management/' + schedule['id'] + '/enabled',
                self.command(enabled=False, expectedDefinitionFingerprint=schedule['definitionFingerprint']), status=409)
        history_path = '/schedule-management/' + schedule['id'] + '/occurrences'
        history = self.request('GET', history_path)
        self.assertEqual(history['items'][0]['nativeRunId'], original['run_id'])
        self.request('GET', history_path, owner='bob', status=404)
        cancel_path = '/schedules/' + schedule['id'] + '/occurrences/' + accepted['id'] + '/cancel'
        self.post(cancel_path, {}, owner='bob', status=404)
        self.post(cancel_path, {})
        self.assertTrue(self.store.task(original['id'], 'manager')['cancel_requested'])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = self.service.db.get_job(original['run_id'])
            if job and job['status'] == 'cancelled':
                break
            time.sleep(.05)
        else:
            self.fail('Original native cancellation did not settle')
        current = self.store.task(original['id'], 'manager')
        self.assertEqual(current['run_id'], original['run_id'])
        self.assertEqual(current['plan_id'], original['plan_id'])
        self.post('/schedules/' + schedule['id'] + '/trigger', self.command(), status=409)
        self.assertEqual(len(self.request('GET', history_path)['items']), 1)
        self.assertEqual(self.store.sql('SELECT count(*) AS count FROM af_tasks')[0]['count'], 1)
        pending = self.store.sql("SELECT status FROM af_schedule_editor_commands WHERE schedule_id=:id ORDER BY request_id", id=schedule['id'])
        self.assertIn('pending', [row['status'] for row in pending])

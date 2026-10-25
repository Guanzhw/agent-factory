"""Actual native queue and orderly service-instance restart with synthetic provider.

This is not an OS crash test or real research/model-quality acceptance.
"""
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
import os
from threading import Event, Lock
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import text

from agent_factory.application_content import ContentPublication
from agent_factory.application_interface import ApplicationStart
from agent_factory.assistant_events import ContentEvent
from agent_factory.store import digest
from core_native_fixture import FixtureModel
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class OwnedNativeFinalizationQueuePostgresTests(unittest.TestCase):
    def setUp(self):
        self.fail_callback = True
        self.callback_entered = Event()
        self.model_calls, self.counter_lock = 0, Lock()
        self.deadline = time.time() + 120
        original_response = FixtureModel._response
        def counted_response(model, messages):
            with self.counter_lock:
                self.model_calls += 1
            return original_response(model, messages)
        model_patch = patch.object(FixtureModel, '_response', counted_response)
        model_patch.start()
        self.addCleanup(model_patch.stop)
        create_app = fixtures.create_app
        def constructed(settings):
            app = create_app(replace(settings, storage_low_water_bytes=1, storage_task_reserve_bytes=4096))
            state = app.app.state.factory
            store = state['store']
            store.sql('CREATE TABLE IF NOT EXISTS queue_fixture_completion(task_id TEXT PRIMARY KEY,run_id TEXT NOT NULL)')
            content, events = state['application_content'], state['assistant_events']

            @contextmanager
            def finalization_context(conn, task):
                self.assertIs(conn, store._connection.get())
                # Explicit concrete locks precede the core's usage settlement.
                with content.db.write(), events.db.write():
                    def finalize(completion):
                        self.assertEqual(completion['settlement']['state'], 'SETTLED')
                        conn.execute(text('INSERT INTO queue_fixture_completion(task_id,run_id) VALUES(:task,:run)'),
                            {'task': task['id'], 'run': task['run_id']})
                        publication = content.publish(task['owner_id'], ContentPublication(source={
                            'application': 'queue-fixture', 'record': task['id'], 'revision': '1'},
                            content={'result': task['body']['stoppedStatus'], 'evidenceKind': 'synthetic'},
                            visibility='team'), 'completion:' + task['id'])
                        events.emit(conn, task['owner_id'], ContentEvent(namespace='queue-fixture',
                            eventType='round.completed', contentId=publication['id'], candidates=[],
                            deadline=self.deadline), 'completion-event:' + task['id'])
                        self.callback_entered.set()
                        if self.fail_callback:
                            raise RuntimeError('Synthetic failure after completion and actual outbox writes')
                    yield finalize

            # Construction boundary: registration precedes TestClient entering any
            # native/observer lifespan, including the second service instance.
            store.application_runtime.register('queue-fixture-completion',
                SimpleNamespace(finalization_context=finalization_context),
                applications=(('synthetic-text-audit', 1),), finalizes=True)
            return app
        constructor_patch = patch.object(fixtures, 'create_app', side_effect=constructed)
        constructor_patch.start()
        self.addCleanup(constructor_patch.stop)
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_native_completion_callback_rollback_then_restart_finishes_original_once(self):
        fixture = self.fixture
        application = fixture.publish_http()
        scopes = fixture.store.local_budget_scopes
        caps = {'rounds': 1, 'toolCalls': 10, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        scopes.create_scope('alice', 'queue-completion-scope', digest({'fixture': 'explicit round'}), caps, self.deadline)
        with fixture.store.transaction() as conn:
            scopes.allocate(conn, 'alice', 'queue-completion-scope', 'queue-completion-allocation',
                digest({'fixture': 'original intent'}), caps)
        body = ApplicationStart(application=application['id'], applicationRef=fixtures.pin(application),
            mode='literature', goal='Perform a synthetic checksum audit', requestId='queue-completion-original')
        admitted = fixture.client.portal.call(partial(fixture.state['assistant_messages'].runs.start, 'alice', body,
            allocation_id='queue-completion-allocation'))
        task_id = admitted['job']['id']
        self.assertTrue(self.callback_entered.wait(15), 'native queue did not reach the completion callback')
        task = fixture.store.task(task_id, 'alice')
        run_id = task['run_id']
        self.assertIsNotNone(run_id)
        self.assertFalse(task['terminal'])
        self.assertEqual(task['body']['stoppedStatus'], 'completed')
        self.assertEqual(fixture.store.native_db.get_job(run_id)['status'], 'completed')
        fixture.login('alice')
        response = fixture.client.get('/api/factory/jobs/' + task_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['job']['status'], 'finalizing')
        self.assertEqual(fixture.store.sql('SELECT * FROM queue_fixture_completion'), [])
        self.assertEqual(fixture.store.sql('SELECT * FROM af_assistant_events'), [])
        self.assertEqual(fixture.store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=task_id)[0]['state'], 'HELD')
        self.assertEqual(scopes.inspect('alice', 'queue-completion-scope')['allocations'][0]['state'], 'BOUND')
        model_calls = self.model_calls
        self.assertGreater(model_calls, 0)

        fixture.stop()
        fixture.start()
        self.assertEqual(fixture.store.task(task_id)['run_id'], run_id)
        self.assertFalse(fixture.store.task(task_id)['terminal'])
        self.fail_callback = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not fixture.store.task(task_id)['terminal']:
            time.sleep(.05)
        self.assertTrue(fixture.store.task(task_id)['terminal'], 'original observer did not finalize after restart')
        self.assertEqual(fixture.store.task(task_id)['run_id'], run_id)
        self.assertEqual(self.model_calls, model_calls)
        self.assertEqual(len(fixture.store.tasks('alice')), 1)
        self.assertEqual(fixture.store.sql('SELECT * FROM queue_fixture_completion'), [{'task_id': task_id, 'run_id': run_id}])
        events = fixture.store.sql('SELECT id FROM af_assistant_events')
        self.assertEqual(len(events), 1)
        self.assertEqual(fixture.store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=task_id)[0]['state'], 'RELEASED')
        self.assertEqual(fixture.store.local_budget_scopes.inspect('alice', 'queue-completion-scope')['allocations'][0]['state'], 'SETTLED')
        fixture.client.portal.call(fixture.state['lifecycle_observer'].observe_root, task_id)
        self.assertEqual(fixture.store.sql('SELECT id FROM af_assistant_events'), events)
        self.assertEqual(self.model_calls, model_calls)

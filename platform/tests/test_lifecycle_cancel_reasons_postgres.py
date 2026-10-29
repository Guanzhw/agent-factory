"""Real PG cancellation causes and lock order; native model output is synthetic."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import os
from threading import Event, get_ident
import time
from types import SimpleNamespace
import unittest

from sqlalchemy import event, text

from agent_factory.application_interface import ApplicationStart
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class LifecycleCancelReasonsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.definition = self.fixture.publish_http()
        self.store = self.fixture.store
        self.observer = self.fixture.state['lifecycle_observer']
        self.fixture.client.portal.call(self.observer.stop)
        self.calls = []
        self.hooks = SimpleNamespace(mark_cancel=self.mark)
        self.store.application_runtime.register('cancel-cause-fixture', self.hooks,
            applications=[(self.definition['id'], self.definition['version'])])
        self.task = self.new_task('cancel-cause-origin')

    def new_task(self, request_id):
        body = ApplicationStart(requestId=request_id, application=self.definition['id'],
            applicationRef=fixtures.pin(self.definition), mode='literature', goal='Synthetic cancellation cause.')
        result = self.fixture.client.portal.call(partial(self.fixture.state['assistant_messages'].runs.start, 'alice', body))
        task = self.store.task(result['job']['id'], 'alice')
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            ticket = self.store.native_db.get_job(task['run_id'], strict=True)
            if ticket and ticket['status'] in {'completed', 'failed', 'cancelled'}:
                self.assertEqual(ticket['status'], 'completed')
                return self.store.task(task['id'], 'alice')
            time.sleep(.03)
        self.fail('Original native ticket did not finish: ' + str(ticket.get('status') if ticket else None))

    def mark(self, store, task_id, *, reason):
        self.assertIsNotNone(store._connection.get())
        self.calls.append((task_id, reason))
        store.event(task_id, 'fixture_cancel_hook', 'Synthetic same-transaction marker', {'reason': reason})

    def test_first_cleanup_cause_is_once_but_explicit_cancel_always_notifies(self):
        self.observer._mark_cancel(self.task, 'native-failure')
        current = self.store.task(self.task['id'])
        self.assertTrue(current['cancel_requested'])
        self.observer._mark_cancel(current, 'cancel-requested')
        self.observer._mark_cancel(current, 'current-authority-ended')
        self.assertEqual(self.calls, [(self.task['id'], 'native-failure')])
        cleanup = [item['data']['reason'] for item in self.store.events(self.task['id'])
                   if item['type'] == 'lifecycle_cleanup_requested']
        self.assertEqual(cleanup, ['native-failure'])
        self.store.request_cancel(self.task['id'])
        self.store.request_cancel(self.task['id'])
        self.assertEqual([reason for _, reason in self.calls],
                         ['native-failure', 'cancel-requested', 'cancel-requested'])

    def test_hook_failure_rolls_back_flag_cause_and_marker(self):
        def rejected(store, task_id, *, reason):
            self.mark(store, task_id, reason=reason)
            raise ValueError('Synthetic hook transaction rejection')
        self.hooks.mark_cancel = rejected
        for action in (lambda: self.observer._mark_cancel(self.task, 'native-failure'),
                       lambda: self.store.request_cancel(self.task['id'])):
            with self.subTest(action=len(self.calls)), self.assertRaisesRegex(ValueError, 'Synthetic hook'):
                action()
            self.assertFalse(self.store.task(self.task['id'])['cancel_requested'])
            self.assertFalse(any(item['type'] in {'fixture_cancel_hook', 'lifecycle_cleanup_requested', 'cancel_requested'}
                                 for item in self.store.events(self.task['id'])))

    def test_subtree_and_protocol_rejection_override_existing_cleanup_marker(self):
        self.observer._mark_cancel(self.task, 'native-failure')
        result = self.fixture.client.portal.call(self.observer.cancel_subtree, 'alice', self.task['id'])
        self.assertEqual(result['requested'], [self.task['id']])
        self.assertEqual(result['errors'], [])
        self.assertEqual(self.calls[-1], (self.task['id'], 'cancel-requested'))
        self.store.reject_model_protocol(SimpleNamespace(session_id=self.task['id'], user_id='alice',
            run_id=self.task['run_id']))
        self.assertEqual([reason for _, reason in self.calls],
                         ['native-failure', 'cancel-requested', 'cancel-requested'])
        self.assertTrue(any(item['type'] == 'protected_denied' for item in self.store.events(self.task['id'])))

    def test_admission_is_acquired_before_task_row_for_both_cancel_paths(self):
        for index, kind in enumerate(('observer', 'explicit')):
            with self.subTest(kind=kind):
                task = self.task if index == 0 else self.new_task('cancel-cause-second')
                attempted = Event()
                worker = {}

                def statement(conn, cursor, sql, params, context, many):
                    if get_ident() == worker.get('thread') and 'pg_advisory_xact_lock' in sql and 'af_admission' in sql:
                        worker['pid'] = conn.connection.driver_connection.info.backend_pid
                        attempted.set()

                def cancel():
                    worker['thread'] = get_ident()
                    if kind == 'observer':
                        self.observer._mark_cancel(task, 'native-failure')
                    else:
                        self.store.request_cancel(task['id'])

                event.listen(self.store.engine, 'before_cursor_execute', statement)
                try:
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        with self.store.engine.begin() as holder:
                            holder.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
                            holder_pid = holder.execute(text('SELECT pg_backend_pid()')).scalar_one()
                            pending = executor.submit(cancel)
                            self.assertTrue(attempted.wait(5), 'Cancellation never attempted admission lock')
                            deadline = time.monotonic() + 5
                            while time.monotonic() < deadline:
                                blockers = holder.execute(text('SELECT pg_blocking_pids(:pid)'),
                                    {'pid': worker['pid']}).scalar_one()
                                if holder_pid in blockers:
                                    break
                                time.sleep(.01)
                            else:
                                self.fail('Cancellation did not actually wait on the held admission lock')
                            # With the old row-before-admission order this NOWAIT
                            # read fails; the worker must not own this task row yet.
                            holder.execute(text('SELECT id FROM af_tasks WHERE id=:id FOR UPDATE NOWAIT'), {'id': task['id']})
                            self.assertFalse(pending.done())
                        pending.result(timeout=5)
                finally:
                    event.remove(self.store.engine, 'before_cursor_execute', statement)
                self.assertTrue(self.store.task(task['id'])['cancel_requested'])

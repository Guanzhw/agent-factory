# pyright: reportMissingImports=false
"""Real native workflow custody repair after deliberately injected legacy accounting damage.

Only terminal/released/reclaimed flags and explicit invalid-binding fixtures are
written directly. Workflow completion/cancellation evidence comes from original
HTTP/native execution and actual inert adapters, never fabricated SQL results.
No app lifespan is entered during repair: startup cannot dispatch operations.
"""
import os
from pathlib import Path
import unittest

from sqlalchemy import create_engine, text

from agent_factory.store import Store
from agent_factory.delegation import DelegationService
from agent_factory.workflow_service import WorkflowService
import test_workflow_native_postgres as native_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native workflow')
class WorkflowCustodyPostgresTests(unittest.TestCase):
    def setUp(self):
        # This nested fixture is plain TestCase, not IsolatedAsyncioTestCase.
        self.fixture = native_fixture.WorkflowNativePostgresTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.server = self.fixture.server
        self.engine = create_engine(self.server.configuration['dbUrl'])
        self.addCleanup(self.engine.dispose)

    def row(self, statement, **params):
        with self.engine.connect() as conn:
            return dict(conn.execute(text(statement), params).mappings().one())

    def accounting(self, task):
        identifier = task['id']
        return {'task': self.row('SELECT terminal,run_id,owner_id,plan_id FROM af_tasks WHERE id=:id', id=identifier),
            'disk': self.row('SELECT state FROM af_disk_holds WHERE task_id=:id', id=identifier),
            'root': self.row('SELECT reclaimed FROM af_delegation_roots WHERE root_id=:id', id=identifier)}

    def damage_legacy_accounting(self, task):
        # Explicit fault injection, not a scientific/native stop proof.
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE af_tasks SET terminal=TRUE WHERE id=:id'), {'id': task['id']})
            conn.execute(text("UPDATE af_disk_holds SET state='RELEASED' WHERE task_id=:id"), {'id': task['id']})
            conn.execute(text('UPDATE af_delegation_roots SET reclaimed=TRUE WHERE root_id=:id'), {'id': task['id']})
        self.assertTrue(self.accounting(task)['task']['terminal'])
        self.assertEqual(self.accounting(task)['disk']['state'], 'RELEASED')
        self.assertTrue(self.accounting(task)['root']['reclaimed'])

    def restart_without_dispatch(self):
        backend = native_fixture.DurableOperations(Path(self.server.configuration['workspace']) / 'controlled-operations.sqlite')
        before = backend.rows()
        settings = native_fixture.settings(self.server.configuration, backend)
        # Reopen actual metadata services only: no new native app/worker/lifespan.
        settings.workflow_definitions = {}; settings.workflow_runtimes = {}
        store = Store(self.server.configuration['dbUrl'], settings)
        self.addCleanup(store.engine.dispose)
        store.delegation = DelegationService(settings, store, None, None)
        store.workflow = WorkflowService(store, None, definitions={}, runtimes={})
        self.assertEqual(backend.rows(), before)
        return store

    def test_startup_reholds_exact_active_original_without_dispatch(self):
        task = self.fixture.start_task()
        original = self.fixture.paused(task)
        self.assertEqual(original['workflow']['status'], 'ACTIVE')
        self.server.stop()
        self.damage_legacy_accounting(task)
        store = self.restart_without_dispatch()
        after = self.accounting(task)
        self.assertFalse(after['task']['terminal'])
        self.assertEqual(after['disk']['state'], 'HELD')
        self.assertFalse(after['root']['reclaimed'])
        self.assertEqual(self.row('SELECT body FROM af_workflow_runs WHERE task_id=:id', id=task['id'])['body'], original['workflow'])
        self.assertEqual(after['task']['run_id'], original['task']['run_id'])
        # A single pooled connection must suffice inside an active Store transaction.
        store.engine.dispose()
        store.engine = create_engine(self.server.configuration['dbUrl'], pool_size=1, max_overflow=0, pool_timeout=1)
        self.addCleanup(store.engine.dispose)
        with store.transaction():
            self.assertTrue(store.workflow.task_held(task['id']))

    def test_startup_does_not_rehold_actual_completed_or_cancelled(self):
        completed = self.fixture.start_task()
        self.fixture.paused(completed)
        waiting = self.fixture.settle_parallel(completed)
        self.fixture.approve_review(completed, waiting)
        self.fixture.until(completed, lambda value: value['native']['status'] == 'completed'
            and value['workflow']['status'] == 'COMPLETED')
        cancelled = self.fixture.start_task()
        self.fixture.paused(cancelled)
        self.fixture.request('POST', '/jobs/' + cancelled['id'] + '/cancel', {})
        self.fixture.until(cancelled, lambda value: value['workflow']['status'] == 'CANCELLED'
            and value['native']['status'] == 'cancelled')
        self.server.stop()
        for task in (completed, cancelled): self.damage_legacy_accounting(task)
        self.restart_without_dispatch()
        for task in (completed, cancelled):
            with self.subTest(task=task['id']):
                after = self.accounting(task)
                self.assertTrue(after['task']['terminal'])
                self.assertEqual(after['disk']['state'], 'RELEASED')
                self.assertTrue(after['root']['reclaimed'])

    def test_startup_does_not_adopt_foreign_owner_or_native_run(self):
        task = self.fixture.start_task()
        self.fixture.paused(task)
        self.server.stop()
        original = self.row('SELECT owner_id,native_run_id FROM af_workflow_runs WHERE task_id=:id', id=task['id'])
        for field, invalid in (('owner_id', 'bob'), ('native_run_id', 'not-the-original-native-run')):
            with self.subTest(field=field):
                self.damage_legacy_accounting(task)
                with self.engine.begin() as conn:
                    conn.execute(text('UPDATE af_workflow_runs SET owner_id=:owner,native_run_id=:run WHERE task_id=:task'),
                        {'owner': invalid if field == 'owner_id' else original['owner_id'],
                         'run': invalid if field == 'native_run_id' else original['native_run_id'], 'task': task['id']})
                self.restart_without_dispatch()
                after = self.accounting(task)
                self.assertTrue(after['task']['terminal'])
                self.assertEqual(after['disk']['state'], 'RELEASED')
                self.assertTrue(after['root']['reclaimed'])

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
from agent_factory.workflow_operations import OperationCustody
import test_native_workflow_factory_postgres as native_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native workflow')
class WorkflowCustodyPostgresTests(unittest.TestCase):
    def setUp(self):
        # This nested fixture is plain TestCase, not IsolatedAsyncioTestCase.
        self.fixture = native_fixture.NativeWorkflowFactoryPostgresTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.server = self.fixture.server
        self.engine = create_engine(self.server.configuration['dbUrl'])
        self.addCleanup(self.engine.dispose)

    def row(self, statement, **params):
        with self.engine.connect() as conn:
            return dict(conn.execute(text(statement), params).mappings().one())

    def operations(self, task):
        with self.engine.connect() as conn:
            return [row['body'] for row in conn.execute(text(
                'SELECT body FROM af_external_operations WHERE task_id=:id ORDER BY id'),
                {'id': task['id']}).mappings()]

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
        settings = native_fixture.settings(self.server.configuration, backend, {})
        # Reopen actual metadata services only: no new native app/worker/lifespan.
        settings.native_workflows = (); settings.workflow_runtimes = {}
        store = Store(self.server.configuration['dbUrl'], settings)
        self.addCleanup(store.engine.dispose)
        # Constructor repair and later task_held share a single metadata pool.
        store.engine.dispose()
        store.engine = create_engine(self.server.configuration['dbUrl'], pool_size=1, max_overflow=0, pool_timeout=1)
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.dispose_root_locks)
        store.delegation = DelegationService(settings, store, None, None)
        store.workflow = OperationCustody(store, None, runtimes={})
        self.assertEqual(backend.rows(), before)
        return store

    def test_startup_reholds_exact_active_original_without_dispatch(self):
        task = self.fixture.start_task()
        original = self.fixture.paused(task)
        self.assertTrue(original['workflowHeld'])
        self.assertTrue(any(not record['closed'] for record in original['custody']))
        parent = self.fixture.start_task()
        self.fixture.paused(parent)
        self.fixture.command(parent, 'cancel')
        self.fixture.until(parent, lambda value: not value['workflowHeld'] and value['task']['terminal'])
        self.server.stop()
        # Explicit accounting topology fault fixture, not a claimed delegated
        # native execution. Both endpoint tasks/native IDs really exist.
        with self.engine.begin() as conn:
            conn.execute(text('INSERT INTO af_delegation_links '
                '(owner_id,parent_id,request_id,root_id,depth,fingerprint,plan_id,child_id,created_at) '
                'VALUES(:owner,:parent,:request,:parent,1,:fingerprint,:plan,:child,:created)'),
                {'owner': 'alice', 'parent': parent['id'], 'request': 'accounting-topology-fixture',
                 'fingerprint': 'a' * 64, 'plan': original['task']['plan_id'], 'child': task['id'],
                 'created': '2026-01-01T00:00:00+00:00'})
        self.damage_legacy_accounting(task)
        self.damage_legacy_accounting(parent)
        store = self.restart_without_dispatch()
        after = self.accounting(task)
        self.assertFalse(after['task']['terminal'])
        self.assertEqual(after['disk']['state'], 'HELD')
        self.assertFalse(after['root']['reclaimed'])
        ancestor = self.accounting(parent)
        self.assertFalse(ancestor['task']['terminal'])
        self.assertEqual(ancestor['disk']['state'], 'HELD')
        self.assertFalse(ancestor['root']['reclaimed'])
        self.assertEqual(self.operations(task), original['custody'])
        self.assertEqual(after['task']['run_id'], original['task']['run_id'])
        # A single pooled connection must suffice inside an active Store transaction.
        with store.transaction():
            self.assertTrue(store.workflow.task_held(task['id']))

    def test_startup_does_not_rehold_actual_completed_or_cancelled(self):
        completed = self.fixture.start_task()
        self.fixture.paused(completed)
        self.fixture.complete_operations(completed)
        view = self.fixture.view(completed)
        self.fixture.command(completed, 'decide', requirementId=view['requirements'][0]['id'], approved=True)
        self.fixture.until(completed, lambda value: value['native']['status'] == 'completed'
            and not value['workflowHeld'])
        cancelled = self.fixture.start_task()
        self.fixture.paused(cancelled)
        self.fixture.request('POST', '/jobs/' + cancelled['id'] + '/cancel', {})
        self.fixture.until(cancelled, lambda value: not value['workflowHeld'] and value['task']['terminal']
            and all(record['closed'] for record in value['custody']))
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
        original = self.row('SELECT DISTINCT owner_id,native_run_id FROM af_external_operations WHERE task_id=:id', id=task['id'])
        for field, invalid in (('owner_id', 'bob'), ('native_run_id', 'not-the-original-native-run')):
            with self.subTest(field=field):
                self.damage_legacy_accounting(task)
                with self.engine.begin() as conn:
                    conn.execute(text('UPDATE af_external_operations SET owner_id=:owner,native_run_id=:run WHERE task_id=:task'),
                        {'owner': invalid if field == 'owner_id' else original['owner_id'],
                         'run': invalid if field == 'native_run_id' else original['native_run_id'], 'task': task['id']})
                self.restart_without_dispatch()
                after = self.accounting(task)
                self.assertTrue(after['task']['terminal'])
                self.assertEqual(after['disk']['state'], 'RELEASED')
                self.assertTrue(after['root']['reclaimed'])

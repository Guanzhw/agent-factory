"""Actual SQLite budget rows; only PostgreSQL lock/ANY dialect seams substituted.

Workflow adapters and native snapshots are controlled fixtures, not real queue proof.
"""
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import bindparam, text

from agent_factory.delegation import DelegationService
from agent_factory.workflow_control import WorkflowControl
import test_workflow_control as control_fixture
import test_workflow_service as service_fixture


class SQLiteBudget:
    """Retain production SQL transactions/counts; translate only PG ANY."""
    def __init__(self, engine):
        self.engine = engine
        self.connection = None
        self.lock = RLock()

    @contextmanager
    def transaction(self):
        with self.engine.begin() as connection:
            self.connection = connection
            try:
                yield connection
            finally:
                self.connection = None

    @contextmanager
    def root_lock(self, root_id):
        with self.lock:
            yield

    def sql(self, query, **parameters):
        statement = text(query.replace('task_id=ANY(:ids)', 'task_id IN :ids'))
        if 'task_id IN :ids' in str(statement):
            statement = statement.bindparams(bindparam('ids', expanding=True))
        def execute(connection):
            result = connection.execute(statement, parameters)
            return [dict(row) for row in result.mappings()] if result.returns_rows else []
        if self.connection is not None:
            return execute(self.connection)
        with self.engine.begin() as connection:
            return execute(connection)


class ExternalBudgetLedgerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixture = control_fixture.WorkflowControlTests('test_completion_is_stable_across_other_stage_progress')
        def close_resources():
            inner = getattr(fixture, 'fixture', None)
            if inner is not None:
                inner.resources.close()
        self.addCleanup(close_resources)
        original_build = service_fixture.WorkflowTests.build
        def build(instance, stages, maximum=2):
            instance.plan.update(id='plan', status='ready', budget={'toolCalls': 1})
            original_build(instance, stages, maximum)
        with patch.object(service_fixture.WorkflowTests, 'build', build):
            fixture.setUp()
        self.f = fixture
        self.db = SQLiteBudget(fixture.store.engine)
        store = fixture.store
        original_task = store.task
        store.task = lambda identifier, owner: original_task('task' if identifier == 'native' else identifier, owner)
        store.sql, store.transaction = self.db.sql, self.db.transaction
        store.require_current_policy = Mock()
        store.material_governance = None
        store.native_db = SimpleNamespace(get_job=lambda identifier: deepcopy(fixture.native_snapshot['queue']))
        store.event = Mock()
        self.db.sql('CREATE TABLE af_tasks (id TEXT PRIMARY KEY)')
        self.db.sql('CREATE TABLE af_plans (id TEXT PRIMARY KEY)')
        self.db.sql("INSERT INTO af_tasks VALUES ('task')")
        self.db.sql("INSERT INTO af_plans VALUES ('plan')")
        self.reopen_ledger()
        store.delegation.initialize()

    def reopen_ledger(self):
        ledger = DelegationService(None, self.f.store, self.f.auth, self.f.bridge)
        ledger._root_lock = self.db.root_lock
        self.f.store.delegation = ledger
        self.f.control = WorkflowControl(self.f.service, self.f.control.api)

    def rows(self):
        return self.db.sql('SELECT * FROM af_delegation_tool_calls ORDER BY call_id')

    async def test_original_native_id_charged_once_across_prepare_and_recovery(self):
        f = self.f
        await f.service.choose(f.ctx, 'A', 'choose-original')
        for _ in range(2):
            await f.control.completion(f.task, deepcopy(f.requirement))
        self.assertEqual(self.rows(), [])
        first = await f.control.complete_external(f.task, deepcopy(f.requirement))
        self.reopen_ledger()
        self.assertEqual(await f.control.complete_external(f.task, deepcopy(f.requirement)), first)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual({key: rows[0][key] for key in ('task_id', 'call_id', 'root_id', 'tool_name')},
                         {'task_id': 'task', 'call_id': 'original-call', 'root_id': 'task', 'tool_name': 'workflow_wait'})
        # A new native tool call cannot borrow capacity consumed by the original.
        f.requirement['tool_execution']['tool_call_id'] = 'second-native-call'
        with self.assertRaises(PermissionError):
            await f.control.complete_external(f.task, deepcopy(f.requirement))
        self.assertEqual(self.rows(), rows)
        f.commands.submit.assert_not_awaited()

    async def test_unknown_lost_ack_retains_charge_and_custody_without_replay(self):
        f = self.f
        # First parked wait permits selecting A; its continuation is charged.
        await f.control.complete_external(f.task, deepcopy(f.requirement))
        f.runtime.lost = True
        with self.assertRaises(ConnectionError):
            await f.service.choose(f.ctx, 'A', 'original-dispatch')
        original = self.rows()
        self.reopen_ledger()
        with self.assertRaises(ValueError):
            await f.control.complete_external(f.task, deepcopy(f.requirement))
        setattr(f.runtime, 'lookup', None)
        self.assertFalse(await f.service.cancel_task('alice', 'task'))
        self.assertTrue(f.service.task_held('task'))
        self.assertEqual(self.rows(), original)
        self.assertFalse(self.db.sql('SELECT reclaimed FROM af_delegation_roots')[0]['reclaimed'])
        self.assertEqual(len(f.runtime.starts), 1)
        f.commands.submit.assert_not_awaited()

    async def test_unknown_before_first_completion_does_not_invent_a_charge(self):
        f = self.f
        f.runtime.lost = True
        with self.assertRaises(ConnectionError):
            await f.service.choose(f.ctx, 'A', 'original-dispatch')
        with self.assertRaises(ValueError):
            await f.control.complete_external(f.task, deepcopy(f.requirement))
        self.assertEqual(self.rows(), [])
        self.assertTrue(f.service.task_held('task'))
        self.assertEqual(len(f.runtime.starts), 1)

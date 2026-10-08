"""SQLite original-operation custody; no workflow graph or external execution."""
from contextlib import ExitStack
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import create_engine

from agent_factory.store import Store
from agent_factory.workflow_contracts import WorkflowAcknowledgementUnknown
from agent_factory.workflow_operations import OperationCustody

PIN = {'adapterId': 'synthetic-operation', 'revision': '1', 'configFingerprint': 'a' * 64}


class SQLiteStore(Store):
    """Use actual Store transaction/effect implementation with SQLite JSON SQL."""
    def __init__(self, path):
        self.engine = create_engine('sqlite:///' + str(path), pool_size=1, max_overflow=0, pool_timeout=.05)
        self._connection = ContextVar('operation_test_connection', default=None)
        self.authority_check = Mock()
        self.require_plan_execution = self.authority_check
        self.current_plan = {'id': 'plan', 'ownerId': 'alice', 'tools': ['approved-operation']}
        self.sql('CREATE TABLE af_tasks(id TEXT PRIMARY KEY,owner_id TEXT,run_id TEXT,plan_id TEXT,terminal BOOLEAN,cancel_requested BOOLEAN)')
        self.sql("INSERT INTO af_tasks VALUES('task','alice','native','plan',FALSE,FALSE)")
        self.sql('CREATE TABLE af_effects(effect_key TEXT PRIMARY KEY,task_id TEXT,run_id TEXT,fingerprint TEXT,status TEXT,result TEXT)')

    def sql(self, statement, **params):
        return super().sql(statement.replace('CAST(:result AS JSONB)', ':result'), **params)

    def task(self, identifier, owner=None):
        rows = self.sql('SELECT * FROM af_tasks WHERE (id=:id OR run_id=:id)', id=identifier)
        if len(rows) != 1 or (owner is not None and owner != rows[0]['owner_id']):
            raise HTTPException(404, 'NOT_FOUND')
        return rows[0]

    def plan(self, identifier, owner=None):
        if identifier != 'plan' or owner != 'alice':
            raise HTTPException(404, 'NOT_FOUND')
        return deepcopy(self.current_plan)


class Runtime:
    def __init__(self):
        self.starts = []
        self.records = {}
        self.error: Exception | None = None
        self.cancel_stopped = True
        self.on_start = lambda: None

    async def start(self, ctx, operation_id, inputs):
        self.on_start()
        self.starts.append((ctx, operation_id, deepcopy(inputs)))
        result = {'schema': 1, 'operationId': operation_id,
            'handle': {'adapterId': PIN['adapterId'], 'revision': '1', 'id': operation_id},
            'state': 'RUNNING', 'allStopped': False, 'output': None, 'failure': None}
        self.records[operation_id] = result
        if self.error:
            raise self.error
        return deepcopy(result)

    async def inspect(self, ctx, handle):
        return deepcopy(self.records[handle['id']])

    async def lookup(self, ctx, operation_id):
        return deepcopy(self.records.get(operation_id, {'schema': 1, 'operationId': operation_id,
            'handle': None, 'state': 'UNKNOWN', 'allStopped': False, 'output': None, 'failure': None}))

    async def cancel(self, ctx, handle):
        value = deepcopy(self.records[handle['id']])
        value.update(state='CANCELLED' if self.cancel_stopped else 'UNKNOWN', allStopped=self.cancel_stopped)
        self.records[handle['id']] = value
        return value


class OperationCustodyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.store = SQLiteStore(Path(directory) / 'operations.db')
        self.stack.callback(self.store.engine.dispose)
        self.runtime = Runtime()
        self.auth = SimpleNamespace(require=Mock())
        self.ctx = SimpleNamespace(user_id='alice', session_id='task', run_id='native')
        self.runtimes = {(PIN['adapterId'], '1', PIN['configFingerprint']): self.runtime}
        self.service = OperationCustody(self.store, self.auth, runtimes=self.runtimes)

    async def start(self, step='native-step-1', inputs=None):
        return await self.service.start(self.ctx, step, 'external-call', PIN, inputs or {'value': 1})

    async def test_intent_before_call_and_single_connection_transaction(self):
        def check():
            self.assertIsNone(self.store._connection.get())
            self.assertTrue(self.service.task_held('task'))
            self.assertEqual(self.store.sql('SELECT status FROM af_effects')[0]['status'], 'UNKNOWN')
        self.runtime.on_start = check
        first = await self.start()
        self.assertEqual(await self.start(), first)
        self.assertEqual(len(self.runtime.starts), 1)
        with self.store.transaction():
            self.assertTrue(self.service.task_held('task'))
        self.assertEqual(first['nativeRunId'], 'native')
        self.assertEqual(first['taskId'], 'task')

    async def test_restart_lost_ack_lookup_never_replays(self):
        self.runtime.error = WorkflowAcknowledgementUnknown()
        unknown = await self.start()
        self.assertIsNone(unknown['handle'])
        self.assertTrue(self.service.task_held('task'))
        self.service = OperationCustody(self.store, self.auth, runtimes=self.runtimes)
        self.assertEqual((await self.start())['id'], unknown['id'])
        found = await self.service.lookup('alice', unknown['id'])
        self.assertEqual(found['handle']['id'], unknown['id'])
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_ordinary_error_identity_preserved_and_no_replay(self):
        error = ConnectionError('synthetic')
        self.runtime.error = error
        with self.assertRaises(ConnectionError) as raised:
            await self.start()
        self.assertIs(raised.exception, error)
        self.assertTrue(self.service.task_held('task'))
        await self.start()
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_final_authority_fence_denies_after_intent_without_dispatch(self):
        self.store.authority_check.side_effect = [None, PermissionError('fresh denial')]
        with self.assertRaises(PermissionError):
            await self.start()
        self.assertEqual(self.runtime.starts, [])
        self.assertTrue(self.service.task_held('task'))
        self.store.authority_check.side_effect = None
        original = await self.start()
        self.assertIsNone(original['observation'])
        self.assertEqual(self.runtime.starts, [])
        unresolved = await self.service.cancel('alice', original['id'])
        self.assertFalse(unresolved['closed'], 'A missing lookup is not positive stop evidence')

    async def test_closed_flag_without_stop_observation_rejected(self):
        self.runtime.error = WorkflowAcknowledgementUnknown()
        original = await self.start()
        from agent_factory.store import canonical
        altered = {**original, 'closed': True}
        self.store.sql('UPDATE af_external_operations SET closed=TRUE,body=:body WHERE id=:id',
            body=canonical(altered), id=original['id'])
        with self.assertRaises(HTTPException):
            self.service.read('alice', original['id'])
        self.assertTrue(self.service.task_held('task'))

    async def test_changed_input_pin_owner_and_plan_rejected(self):
        original = await self.start()
        with self.assertRaises(ValueError):
            await self.start(inputs={'value': 2})
        with self.assertRaises(HTTPException):
            self.service.read('bob', original['id'])
        changed = {**PIN, 'configFingerprint': 'b' * 64}
        with self.assertRaises(ValueError):
            await self.service.start(self.ctx, 'native-step-1', 'external-call', changed, {'value': 1})
        self.store.current_plan['tools'] = ['different']
        with self.assertRaises(HTTPException):
            await self.service.cancel('alice', original['id'])
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_revoked_or_terminal_execution_still_allows_original_cleanup(self):
        original = await self.start()
        self.store.authority_check.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            await self.start('native-step-2')
        self.store.sql('UPDATE af_tasks SET cancel_requested=TRUE,terminal=TRUE')
        self.runtime.cancel_stopped = False
        first = await self.service.cancel('alice', original['id'])
        self.assertFalse(first['closed'])
        self.assertTrue(self.service.task_held('task'))
        self.assertEqual(self.store.sql('SELECT status FROM af_effects')[0]['status'], 'UNKNOWN')
        self.runtime.cancel_stopped = True
        self.assertTrue(await self.service.cancel_task('alice', 'task'))
        self.assertFalse(self.service.task_held('task'))
        self.assertEqual(self.store.sql('SELECT status FROM af_effects')[0]['status'], 'CANCELLED')
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_handle_substitution_and_unproved_stop_cannot_close(self):
        original = await self.start()
        result = self.runtime.records[original['id']]
        result['handle']['id'] = 'different'
        with self.assertRaises(ValueError):
            await self.service.inspect('alice', original['id'])
        result['handle']['id'] = original['id']
        result.update(state='COMPLETED', allStopped=False, output={'value': 2})
        with self.assertRaises(ValueError):
            await self.service.inspect('alice', original['id'])
        self.assertTrue(self.service.task_held('task'))

    async def test_late_running_snapshot_cannot_regress_positive_terminal(self):
        original = await self.start()
        old = deepcopy(self.runtime.records[original['id']])
        closed = await self.service.cancel('alice', original['id'])
        self.assertTrue(closed['closed'])
        self.assertEqual(self.service._accept(original, old), closed)
        self.assertFalse(self.service.task_held('task'))

    async def test_registry_drift_holds_and_independent_cancel_continues(self):
        first = await self.start()
        second = await self.start('native-step-2')
        self.runtime.records[first['id']]['handle']['id'] = 'bad'
        self.assertFalse(await self.service.cancel_task('alice', 'task'))
        self.assertTrue(self.service.read('alice', second['id'])['closed'])
        restarted = OperationCustody(self.store, self.auth, runtimes={})
        self.assertTrue(restarted.task_held('task'))
        with self.assertRaises(HTTPException):
            await restarted.cancel('alice', first['id'])


if __name__ == '__main__':
    unittest.main()

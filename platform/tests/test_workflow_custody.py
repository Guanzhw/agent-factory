"""Cross-boundary custody using the actual SQLite workflow journal and methods.

Native bridge and metadata SQL writes are controlled fixtures; no native/PG runs.
"""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.delegation import DelegationService, application_group_status
from agent_factory.store import Store, digest
import test_workflow_service as fixtures


class WorkflowCustodyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixture = fixtures.WorkflowTests('test_original_inputs_dependencies_and_command_replay')
        self.addCleanup(lambda: getattr(fixture, 'resources', SimpleNamespace(close=lambda: None)).close())
        fixture.setUp()
        self.f = fixture
        self.tasks: dict[str, dict[str, Any]] = {
            identifier: dict(fixture.task, id=identifier, run_id='native-' + identifier,
                             admission='accepted', body={'lastStatus': 'cancelled'})
            for identifier in ('parent', 'task')}
        self.link = {'owner_id': 'alice', 'parent_id': 'parent', 'child_id': 'task', 'depth': 1}
        self.reclaimed = False
        self.writes = []
        self.store: Any = SimpleNamespace(
            process_runtime=None, workflow=fixture.service, remote_scientific=None,
            storage=SimpleNamespace(release=Mock()), event=Mock(), sql=self.sql,
            task=lambda identifier, owner=None: deepcopy(self.tasks[identifier]),
            effects=lambda identifier: [], has_failures=lambda identifier: False,
            native_db=SimpleNamespace(get_job=lambda identifier: {
                'session_id': identifier.removeprefix('native-'), 'user_id': 'alice',
                'component_id': 'factory-executor', 'status': 'cancelled'}))
        self.bridge = SimpleNamespace(detail=AsyncMock(return_value={'queue': {'status': 'cancelled'}}))
        self.delegation = DelegationService(None, self.store, fixture.auth, self.bridge)

    def sql(self, query, **params):
        if query.startswith('WITH RECURSIVE'):
            return [deepcopy(self.link)] if params['parent'] == 'parent' else []
        if query.startswith('SELECT * FROM af_delegation_links WHERE child_id'):
            return [deepcopy(self.link)] if params['id'] == 'task' else []
        if query.startswith('UPDATE af_delegation_roots'):
            self.reclaimed = True
        elif query.startswith('UPDATE af_tasks'):
            self.tasks[params['id']]['terminal'] = params['terminal']
        else:
            raise AssertionError('Unexpected metadata operation')
        self.writes.append((query, deepcopy(params)))
        return []

    async def start_unknown(self):
        self.f.runtime.outcome = 'RUNNING'
        self.f.runtime.lost = True
        with self.assertRaises(ConnectionError):
            await self.f.service.choose(self.f.ctx, 'A', 'original-start')
        self.f.runtime.cancel_stopped = False
        self.assertFalse(await self.f.service.cancel_task('alice', 'task'))
        self.assertTrue(self.f.service.task_held('task'))

    async def prove_stopped(self):
        self.f.runtime.cancel_stopped = True
        self.assertTrue(await self.f.service.cancel_task('alice', 'task'))
        self.assertFalse(self.f.service.task_held('task'))
        self.assertEqual(len(self.f.runtime.starts), 1)

    async def test_observed_terminal_retains_storage_until_original_positive_stop(self):
        await self.start_unknown()
        # Also repair a stale terminal=True observation without releasing storage.
        self.tasks['task']['terminal'] = True
        Store._observed_locked(self.store, deepcopy(self.tasks['task']), 'cancelled', True)
        self.assertFalse(self.tasks['task']['terminal'])
        self.store.storage.release.assert_not_called()
        await self.prove_stopped()
        Store._observed_locked(self.store, deepcopy(self.tasks['task']), 'cancelled', True)
        self.assertTrue(self.tasks['task']['terminal'])
        self.store.storage.release.assert_called_once_with('task')

    async def test_native_cancelled_facts_unknown_until_workflow_stop(self):
        await self.start_unknown()
        facts = await self.delegation._facts(self.tasks['task'])
        self.assertEqual(facts['nativeStatus'], 'cancelled')
        self.assertTrue(facts['unknown'])
        self.assertTrue(facts['pending'])
        self.assertFalse(facts['stopped'])
        await self.prove_stopped()
        facts = await self.delegation._facts(self.tasks['task'])
        self.assertFalse(facts['unknown'])
        self.assertFalse(facts['pending'])
        self.assertTrue(facts['stopped'])

    async def test_pending_child_and_group_cannot_reclaim_from_native_terminal_alone(self):
        await self.start_unknown()
        self.assertTrue(self.delegation.has_pending_children('parent'))
        group = await self.delegation.inspect_group('alice', 'parent')
        self.assertTrue(group['unknown'])
        self.assertFalse(group['allStopped'])
        self.assertFalse(self.reclaimed)
        await self.prove_stopped()
        self.assertFalse(self.delegation.has_pending_children('parent'))
        group = await self.delegation.inspect_group('alice', 'parent')
        self.assertTrue(group['allStopped'])
        self.assertFalse(group['unknown'])
        self.assertTrue(self.reclaimed)

    async def test_admission_sweep_preserves_held_native_cancelled_task(self):
        await self.start_unknown()
        plan = {'id': 'plan', 'ownerId': 'alice'}
        old = {'id': 'duplicate', 'fingerprint': digest({'planId': 'plan', 'planHash': digest(plan)})}
        updates = []
        class Rows:
            def __init__(self, rows): self.rows = rows
            def mappings(self): return self
            def all(self): return self.rows
            def first(self): return self.rows[0] if self.rows else None
            def __iter__(self): return iter(self.rows)
        def execute(statement, parameters=None):
            query = str(statement)
            if query.startswith('SELECT pg_advisory'): return Rows([])
            if query.startswith('SELECT id,run_id FROM'): return Rows([self.tasks['task']])
            if query.startswith('SELECT id,run_id,terminal'): return Rows([self.tasks['task']])
            if query.startswith('SELECT effect_key'): return Rows([])
            if query.startswith('SELECT * FROM af_tasks WHERE owner_id'): return Rows([old])
            if query.startswith('UPDATE af_tasks SET terminal=TRUE'):
                updates.append(parameters)
                return Rows([])
            raise AssertionError('Unexpected admission SQL')
        self.store.transaction = lambda: nullcontext(SimpleNamespace(execute=execute))
        self.store.delegation = None
        self.assertEqual(Store.reserve_task(self.store, plan, 'duplicate-request'), (old, False))
        self.assertEqual(updates, [])
        self.store.storage.release.assert_not_called()
        await self.prove_stopped()
        self.assertEqual(Store.reserve_task(self.store, plan, 'duplicate-request'), (old, False))
        self.assertEqual(updates, [{'id': 'task'}])
        self.store.storage.release.assert_called_once_with('task')

    async def test_active_native_wait_preserves_known_workflow_continuation(self):
        self.f.runtime.outcome = 'RUNNING'
        await self.f.service.choose(self.f.ctx, 'A', 'original-start')
        self.assertTrue(self.f.service.task_held('task'))
        for status in ('paused', 'running', 'pending', 'queued'):
            with self.subTest(status=status):
                self.bridge.detail.return_value = {'queue': {'status': status}}
                facts = await self.delegation._facts(self.tasks['task'])
                self.assertTrue(facts['pending'])
                self.assertFalse(facts['stopped'])
                self.assertFalse(facts['unknown'])
                group = await self.delegation.inspect_group('alice', 'parent')
                self.assertFalse(group['unknown'])
                self.assertTrue(group['pending'])
                self.assertFalse(group['allStopped'])
                self.assertEqual(application_group_status('waiting_approval', group), 'waiting_approval')
                self.assertFalse(self.reclaimed)
        # Native termination still cannot turn workflow custody into stop proof.
        for status in ('completed', 'cancelled', 'error'):
            with self.subTest(status=status):
                self.bridge.detail.return_value = {'queue': {'status': status}}
                facts = await self.delegation._facts(self.tasks['task'])
                self.assertTrue(facts['unknown'])
                self.assertTrue(facts['pending'])
                self.assertFalse(facts['stopped'])
                group = await self.delegation.inspect_group('alice', 'parent')
                self.assertEqual(application_group_status('waiting_approval', group), 'unknown')
                self.assertFalse(group['allStopped'])
                self.assertFalse(self.reclaimed)
        self.assertEqual(len(self.f.runtime.starts), 1)

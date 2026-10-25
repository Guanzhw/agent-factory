"""Portable exact-owner composition and original-operation custody contracts."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import create_engine, text

from agent_factory.application_runtime import ApplicationRuntimeRegistry
from agent_factory.control_commands import ControlCommands
from agent_factory.factory_api import FactoryAPI
from agent_factory.lifecycle_observer import FactoryLifecycleObserver
from agent_factory.runtime_hooks import cancel_owned_runtime, effect_unresolved, runtime_custody_held
from agent_factory.store import Store


A = ('tool', 'alpha-runtime-v1', '1')
B = ('tool', 'beta-runtime-v1', '2')


def plan(*bindings):
    return {'applicationRef': {'id': 'member-published-app', 'version': 1}, 'executionBindings': {
        'tools': [{'adapterId': key[1], 'revision': key[2], 'toolName': key[1]} for key in bindings]}}


class Fixture:
    connection: Any
    transaction: Any
    sql: Any
    event: Any
    workflow: Any = None
    def __init__(self, selected=None):
        self.value = selected if selected is not None else plan(A)
        self.original = {'id': 'task', 'owner_id': 'alice', 'plan_id': 'plan', 'run_id': 'run'}
        self.rows = []
        self.application_runtime = ApplicationRuntimeRegistry(self)

    def task(self, identifier):
        if identifier not in {'task', 'run'}:
            raise HTTPException(404, 'original task missing')
        return self.original

    def plan(self, identifier, owner):
        assert (identifier, owner) == ('plan', 'alice')
        return self.value

    def effects(self, identifier):
        assert identifier == 'task'
        return self.rows


class ApplicationRuntimeTests(unittest.TestCase):
    def test_empty_registry_does_not_read_task_plan_or_effects(self):
        store = Fixture()
        store.task = Mock(side_effect=AssertionError('unexpected task read'))
        store.plan = Mock(side_effect=AssertionError('unexpected plan read'))
        store.effects = Mock(side_effect=AssertionError('unexpected effect read'))
        self.assertFalse(runtime_custody_held(store, 'task'))
        self.assertFalse(effect_unresolved({'effect_key': 'opaque-core-key', 'status': 'DONE'}, store))
        self.assertEqual(store.application_runtime.owners(store.original), ())

    def test_member_application_without_owned_runtime_retains_core_behavior(self):
        store = Fixture(plan())
        self.assertEqual(store.application_runtime.owners(store.original), ())
        self.assertFalse(runtime_custody_held(store, 'task'))
        self.assertFalse(effect_unresolved({'effect_key': 'run:core-operation', 'status': 'DONE'}, store))
        self.assertTrue(effect_unresolved({'effect_key': 'run:core-operation', 'status': 'UNKNOWN'}, store))

    def test_binding_revision_is_exact_and_application_display_name_is_irrelevant(self):
        store = Fixture()
        hooks = SimpleNamespace()
        store.application_runtime.register('alpha', hooks, bindings=(A,))
        self.assertEqual([owner.identifier for owner in store.application_runtime.owners(store.original)], ['alpha'])
        store.value['application'] = 'another-display-name'
        self.assertEqual(store.application_runtime.owners(store.original)[0].hooks, hooks)
        store.value['executionBindings']['tools'][0]['revision'] = '2'
        self.assertEqual(store.application_runtime.owners(store.original), ())

    def test_registration_conflicts_are_atomic_and_independent_of_install_order(self):
        store = Fixture()
        registry = store.application_runtime
        registry.register('alpha', object(), bindings=(A,), effects=('original-effect',))
        with self.assertRaises(ValueError):
            registry.register('beta', object(), bindings=(B,), effects=('original-effect',))
        registry.register('beta', object(), bindings=(B,))
        with self.assertRaises(ValueError):
            registry.register('gamma', object(), bindings=(A,))
        with self.assertRaises(ValueError):
            registry.register('alpha', object())

    def test_legacy_mapping_never_overrides_modern_binding(self):
        store = Fixture({'application': 'legacy-research'})
        registry = store.application_runtime
        registry.register('legacy', object(), legacy_applications=('legacy-research',))
        registry.register('beta', object(), bindings=(B,))
        self.assertEqual(registry.owners(store.original)[0].identifier, 'legacy')
        store.value.update(plan(B))
        self.assertEqual(registry.owners(store.original)[0].identifier, 'beta')
        store.value = {'application': 'legacy-research', **plan()}
        self.assertEqual(registry.owners(store.original), ())

    def test_declared_missing_owner_keeps_completed_effect_and_task_held(self):
        store = Fixture()
        store.application_runtime.register('uninstalled', None, bindings=(A,), effects=('launch',))
        self.assertTrue(runtime_custody_held(store, 'task'))
        self.assertTrue(effect_unresolved({'effect_key': 'run:launch', 'status': 'DONE'}, store))
        self.assertEqual(store.application_runtime.ended_reason(store.original), 'application-runtime-owner-unavailable')
        with self.assertRaises(HTTPException):
            store.application_runtime.control(store.original, 'external_result')

    def test_each_effect_uses_original_key_and_any_unstopped_owner_holds(self):
        store = Fixture(plan(A, B))
        stopped = {'alpha': True, 'beta': False}
        for name, binding in (('alpha', A), ('beta', B)):
            hooks = SimpleNamespace(effect_held=lambda effect, name=name: not stopped[name],
                task_held=lambda store, task, name=name: not stopped[name])
            store.application_runtime.register(name, hooks, bindings=(binding,), effects=(name + '-effect',))
        first = {'effect_key': 'run:alpha-effect', 'status': 'DONE'}
        second = {'effect_key': 'run:beta-effect', 'status': 'DONE'}
        self.assertFalse(effect_unresolved(first, store))
        self.assertTrue(effect_unresolved(second, store))
        self.assertTrue(runtime_custody_held(store, 'task'))
        stopped['beta'] = True
        self.assertFalse(effect_unresolved(second, store))
        self.assertFalse(runtime_custody_held(store, 'task'))
        store.original['run_id'] = 'replacement'
        self.assertTrue(effect_unresolved(first, store))

    def test_cancellation_and_observation_do_not_touch_unrelated_application(self):
        async def check(order):
            store = Fixture(plan(A))
            calls = []
            def hooks(name):
                async def cancel(store, task): calls.append(('cancel', name, task['id']))
                async def observe(observer, task): calls.append(('observe', name, task['id']))
                return SimpleNamespace(cancel=cancel, observe_waits=observe)
            for name, binding in order:
                store.application_runtime.register(name, hooks(name), bindings=(binding,))
            await cancel_owned_runtime(store, store.original)
            observer = cast(Any, SimpleNamespace(store=store, _group=lambda root: ([root], [])))
            await FactoryLifecycleObserver._observe_application_waits(observer, store.original)
            return calls
        forward = asyncio.run(check((('alpha', A), ('beta', B))))
        reverse = asyncio.run(check((('beta', B), ('alpha', A))))
        self.assertEqual(forward, [('cancel', 'alpha', 'task'), ('observe', 'alpha', 'task')])
        self.assertEqual(forward, reverse)

    def test_one_cancel_failure_does_not_skip_other_original_resource(self):
        store = Fixture(plan(A, B))
        calls = []
        async def failed(store, task):
            calls.append('alpha')
            raise RuntimeError('original resource unavailable')
        async def completed(store, task): calls.append('beta')
        async def workflow_cancel(owner, task): calls.append('workflow')
        store.workflow = SimpleNamespace(cancel_task=workflow_cancel, task_held=lambda task: False)
        store.application_runtime.register('alpha', SimpleNamespace(cancel=failed, task_held=lambda *args: True), bindings=(A,))
        store.application_runtime.register('beta', SimpleNamespace(cancel=completed), bindings=(B,))
        with self.assertRaises(RuntimeError):
            asyncio.run(cancel_owned_runtime(store, store.original))
        # Independent app owners all receive cancellation; preserve the
        # established outer workflow step's prerequisite of successful cleanup.
        self.assertEqual(calls, ['alpha', 'beta'])
        self.assertTrue(runtime_custody_held(store, 'task'))

    def test_independent_job_fields_merge_but_shared_status_conflicts(self):
        store = Fixture(plan(A, B))
        def hooks(key):
            async def project(api, task, plan, snapshot, events, job, wait):
                job['definition']['runtimePolicy'][key] = True
                job['allowedActions'].append(key)
                return {}, None
            return SimpleNamespace(project_detail=project)
        for name, binding in (('alpha', A), ('beta', B)):
            store.application_runtime.register(name, hooks(name), bindings=(binding,))
        job = {'definition': {'runtimePolicy': {}}, 'allowedActions': ['inspect'], 'status': 'running'}
        asyncio.run(store.application_runtime.project_detail(None, store.original, store.value, {}, [], job, {}))
        self.assertEqual(job['definition']['runtimePolicy'], {'alpha': True, 'beta': True})
        self.assertEqual(job['allowedActions'], ['inspect', 'alpha', 'beta'])
        for owner in store.application_runtime.owners(store.original):
            async def conflict(api, task, plan, snapshot, events, job, wait, name=owner.identifier):
                job['status'] = name
                return {}, None
            owner.hooks.project_detail = conflict
        with self.assertRaises(HTTPException):
            asyncio.run(store.application_runtime.project_detail(None, store.original, store.value, {}, [], job, {}))

    def test_projection_uses_each_owners_wait_and_rejects_collisions(self):
        store = Fixture(plan(A, B))
        def hooks(name):
            async def project(api, task, plan, snapshot, events, job, wait):
                self.assertEqual(wait, name)
                return {name: {'originalTask': task['id']}}, None
            return SimpleNamespace(waiting_control=lambda api, task, snapshot: (name, name == 'alpha'), project_detail=project)
        for name, key in (('beta', B), ('alpha', A)):
            store.application_runtime.register(name, hooks(name), bindings=(key,))
        api = cast(Any, SimpleNamespace(store=store))
        waits, waiting = FactoryAPI._waiting_control(api, store.original, {})
        self.assertTrue(waiting)
        evidence, evaluation = asyncio.run(FactoryAPI._project_detail(api, store.original, store.value, {}, [], {}, waits))
        self.assertEqual(evidence, {'alpha': {'originalTask': 'task'}, 'beta': {'originalTask': 'task'}})
        self.assertIsNone(evaluation)
        async def conflict(*args): return {'alpha': {}}, None
        store.application_runtime.owners(store.original)[1].hooks.project_detail = conflict
        with self.assertRaises(HTTPException):
            asyncio.run(FactoryAPI._project_detail(api, store.original, store.value, {}, [], {}, waits))

    def test_control_uses_exact_original_tool_and_rejects_ambiguous_recovery(self):
        store = Fixture(plan(A, B))
        calls = []
        def hooks(name):
            async def external(*args): calls.append(name); return {'owner': name}
            return SimpleNamespace(external_result=external, completed_launch=lambda *args: name,
                claim_external_result=lambda *args: calls.append('claim-' + name))
        for name, key in (('alpha', A), ('beta', B)):
            store.application_runtime.register(name, hooks(name), bindings=(key,))
        commands = cast(Any, SimpleNamespace(store=store))
        result = asyncio.run(ControlCommands._external_result(commands, store.original,
            {'tool_execution': {'tool_name': B[1]}}, [], {'approved': True}))
        self.assertEqual(result, {'owner': 'beta'})
        self.assertEqual(calls, ['beta'])
        ControlCommands._claim_external_result(commands, store.original, {})
        self.assertEqual(calls, ['beta'])
        ControlCommands._claim_external_result(commands, store.original, {}, tool_name=B[1])
        self.assertEqual(calls, ['beta', 'claim-beta'])
        with self.assertRaises(HTTPException):
            ControlCommands._completed_launch(commands, store.original)

    def test_cancel_marker_rolls_back_with_task_in_same_transaction(self):
        store = Fixture()
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE af_tasks(id TEXT PRIMARY KEY,cancel_requested BOOLEAN)'))
            conn.execute(text("INSERT INTO af_tasks VALUES('task',FALSE)"))
            conn.execute(text('CREATE TABLE marker(task TEXT)'))
        @contextmanager
        def transaction():
            with engine.begin() as conn:
                store.connection = conn
                yield conn
        store.transaction = transaction
        store.sql = lambda query, **values: store.connection.execute(text(query), values)
        store.event = lambda *args: None
        def mark_cancel(actual, identifier):
            actual.sql('INSERT INTO marker VALUES(:task)', task=identifier)
            raise ValueError('controlled marker failure')
        store.application_runtime.register('alpha', SimpleNamespace(mark_cancel=mark_cancel), bindings=(A,))
        with self.assertRaises(ValueError):
            Store.request_cancel(cast(Any, store), 'task')
        with engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT cancel_requested FROM af_tasks')).scalar(), 0)
            self.assertEqual(conn.execute(text('SELECT COUNT(*) FROM marker')).scalar(), 0)

    def test_conflicting_summary_states_stay_unknown_without_mutation(self):
        store = Fixture(plan(A, B))
        before = deepcopy(store.original)
        for name, key, status in (('alpha', A, 'waiting_approval'), ('beta', B, 'waiting_input')):
            store.application_runtime.register(name, SimpleNamespace(summary_status=lambda *args, status=status: status), bindings=(key,))
        observer = cast(Any, SimpleNamespace(store=store))
        self.assertEqual(FactoryLifecycleObserver._summary_status(observer, store.original, 'running'), 'unknown')
        self.assertEqual(store.original, before)

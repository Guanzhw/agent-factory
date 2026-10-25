"""Real PG/ledger/storage finalization with controlled, identity-checked native tickets.

The provider is the existing synthetic Agno primitive fixture; no live model or
native queue execution is claimed. The consumer writes only same-transaction SQL.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import asyncio
from threading import Barrier, Event
from types import SimpleNamespace
from dataclasses import replace
import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from agent_factory.application_runtime import ApplicationRuntimeRegistry
from agent_factory.lifecycle_observer import FactoryLifecycleObserver
from agent_factory.storage_governance import StorageGovernance
from agent_factory.store import canonical, digest, now
from agent_factory.usage_ledger import UsageEvidence
from core_native_fixture import build_tools
import test_local_budget_scopes_postgres as fixtures


class CompletionConsumer:
    def __init__(self, store):
        self.store, self.failure = store, None
        self.calls = 0

    @contextmanager
    def finalization_context(self, conn, task):
        if conn is not self.store._connection.get():
            raise AssertionError('Consumer did not borrow the original transaction')
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('synthetic_completion_namespace'))"))
        def finalize(completion):
            self.calls += 1
            conn.execute(text('INSERT INTO fixture_completions(task_id,body) VALUES(:id,CAST(:body AS JSONB))'),
                         {'id': task['id'], 'body': canonical(completion)})
            conn.execute(text('INSERT INTO fixture_outbox(task_id) VALUES(:id)'), {'id': task['id']})
            if self.failure == 'callback':
                raise RuntimeError('Synthetic completion callback failed after outbox write')
        yield finalize
        if self.failure == 'exit':
            raise RuntimeError('Synthetic completion context failed before commit')


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class OwnedNativeFinalizationPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.LocalBudgetScopesPostgresTests('runTest')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.fixture, self.store, self.scopes = self.base.fixture, self.base.store, self.base.scopes
        self.store.settings = replace(self.store.settings, storage_low_water_bytes=1, storage_task_reserve_bytes=4096)
        self.store.storage = StorageGovernance(self.store, self.fixture.auth)
        self.store.sql('CREATE TABLE fixture_completions(task_id TEXT PRIMARY KEY,body JSONB NOT NULL)')
        self.store.sql('CREATE TABLE fixture_outbox(task_id TEXT PRIMARY KEY)')
        self.consumer = CompletionConsumer(self.store)
        self.register_consumer()
        self.tickets = {}
        for replacement in (patch.object(self.fixture.db, 'get_job', side_effect=lambda key, **kwargs: self.tickets.get(key)),
                            patch.object(self.fixture.db, 'get_session', return_value=None)):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.observer = self.new_observer()
        self.base.scope(); self.base.allocate()

    def register_consumer(self):
        self.store.application_runtime = ApplicationRuntimeRegistry(self.store)
        self.store.application_runtime.register('synthetic-completion', self.consumer,
            bindings=(('model', 'controlled-ledger-model-v1', '1'),), finalizes=True)

    def new_observer(self):
        return FactoryLifecycleObserver(self.store, self.fixture.auth, self.fixture.db, lambda: None)

    def root(self, *, accepted=True):
        plan = self.fixture.plan(extra={'tools': ['checksum']})
        task, context = self.fixture.task(plan, accepted=False)
        with self.store.transaction() as conn:
            self.scopes.bind_root(conn, 'alice', 'round-1', task['id'], digest(plan))
        self.store.sql('INSERT INTO af_delegation_roots(root_id,owner_id) VALUES(:id,:owner)', id=task['id'], owner='alice')
        if accepted:
            self.store.accept(task['id'], context.run_id)
            self.tickets[context.run_id] = {
                'id': context.run_id, 'session_id': task['id'], 'user_id': 'alice',
                'component_type': 'agent', 'component_id': 'factory-executor',
                'idempotency_key': digest({'owner': 'alice', 'task': task['id'], 'request': task['request_id']}),
                'status': 'completed', 'payload': {'kwargs': {'session_state': context.session_state}}}
        return self.store.task(task['id']), context, plan

    def observe(self, task):
        return self.observer._observe_stopped(self.store.task(task['id']))

    def assert_pending(self, task):
        current = self.store.task(task['id'])
        self.assertFalse(current['terminal'])
        self.assertEqual(self.store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=task['id'])[0]['state'], 'HELD')
        self.assertFalse(self.store.sql('SELECT reclaimed FROM af_delegation_roots WHERE root_id=:id', id=task['id'])[0]['reclaimed'])
        self.assertEqual(self.store.sql('SELECT * FROM fixture_completions'), [])
        self.assertEqual(self.store.sql('SELECT * FROM fixture_outbox'), [])
        self.assertEqual(self.scopes.inspect('alice', 'scope')['allocations'][0]['state'], 'BOUND')

    def assert_completed(self, task, children=()):
        self.assertTrue(self.store.task(task['id'])['terminal'])
        self.assertEqual(self.store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=task['id'])[0]['state'], 'RELEASED')
        self.assertTrue(self.store.sql('SELECT reclaimed FROM af_delegation_roots WHERE root_id=:id', id=task['id'])[0]['reclaimed'])
        rows = self.store.sql('SELECT body FROM fixture_completions')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['body']['task']['id'], task['id'])
        self.assertEqual(rows[0]['body']['settlement']['state'], 'SETTLED')
        self.assertEqual([entry['id'] for entry in rows[0]['body']['group']], [task['id'], *(child['id'] for child in children)])
        self.assertEqual(self.store.sql('SELECT task_id FROM fixture_outbox'), [{'task_id': task['id']}])
        self.assertEqual(self.scopes.inspect('alice', 'scope')['allocations'][0]['state'], 'SETTLED')

    def test_unknown_usage_retains_holds_then_original_evidence_finishes_once_after_reopen(self):
        task, context, _ = self.root()
        self.fixture.options['scenario'] = 'unknown'
        retained = self.fixture.selected(context)
        self.fixture.invoke(retained)
        held = self.scopes.inspect('alice', 'scope')['usage']
        facts = self.observe(task)
        self.assertTrue(facts[task['id']]['groupStopped'])
        self.assertFalse(facts[task['id']]['finalizationCommitted'])
        self.assert_pending(task)
        self.assertEqual(self.store.task(task['id'])['body']['stoppedStatus'], 'completed')
        self.assertEqual(self.scopes.inspect('alice', 'scope')['usage'], held)
        with self.assertRaises(HTTPException) as rejected_model:
            self.fixture.invoke(retained)
        self.assertIn('NATIVE_EXECUTION_STOPPED', rejected_model.exception.detail)
        with self.assertRaises(HTTPException) as rejected_tool:
            build_tools(self.fixture.settings, self.store)['checksum']('no new work', context)
        self.assertIn('NATIVE_EXECUTION_STOPPED', rejected_tool.exception.detail)
        history = self.store.task_history('alice')['items'][0]
        self.assertEqual((history['status'], history['executionStatus'], history['finalizationPending']),
                         ('finalizing', 'completed', True))
        self.assertEqual(self.fixture.records, ['unknown'])
        self.assertEqual(self.store.effects(task['id']), [])
        # Reconstruct metadata consumers/observer, retaining the original PG identity.
        self.consumer = CompletionConsumer(self.store)
        self.register_consumer()
        self.observer = self.new_observer()
        with self.assertRaises(HTTPException):
            self.fixture.selected(context)
        attempt = self.fixture.projection(task)['attempts'][0]
        self.base.ledger.finish_attempt(attempt['id'], UsageEvidence(3, 2, 'original-authoritative-observation'))
        self.assertTrue(self.observe(task)[task['id']]['finalizationCommitted'])
        self.assert_completed(task)
        settled = self.scopes.inspect('alice', 'scope')['usage']
        self.observe(task)
        self.assertEqual(self.consumer.calls, 1)
        self.assertEqual(self.scopes.inspect('alice', 'scope')['usage'], settled)
        self.assertEqual(self.fixture.records, ['unknown'])

    def test_callback_and_context_exit_failures_rollback_terminal_storage_settlement_and_outbox(self):
        task, context, _ = self.root()
        self.fixture.invoke(self.fixture.selected(context))
        original_usage = self.scopes.inspect('alice', 'scope')['usage']
        for failure in ('callback', 'exit'):
            with self.subTest(failure=failure):
                self.consumer.failure = failure
                with self.assertRaisesRegex(RuntimeError, 'Synthetic completion'):
                    self.observe(task)
                self.assert_pending(task)
                self.assertEqual(self.store.task(task['id'])['body']['stoppedStatus'], 'completed')
                self.assertEqual(self.scopes.inspect('alice', 'scope')['usage'], original_usage)
        self.consumer.failure = None
        self.observe(task)
        self.assert_completed(task)
        self.assertEqual(self.fixture.records, ['success'])

    def test_real_reserve_capacity_scan_does_not_bypass_declared_completion(self):
        task, _, _ = self.root()
        other_plan = self.fixture.plan()
        self.store.reserve_task(other_plan, str(uuid4()))
        self.assert_pending(task)
        self.assertEqual(self.consumer.calls, 0)
        self.observe(task)
        self.assert_completed(task)

    def test_real_admission_failure_preserves_rejected_task_for_transactional_completion(self):
        task, _, _ = self.root(accepted=False)
        self.store.admission_failed(task['id'], 'Synthetic rejection before native dispatch')
        self.assertEqual(self.store.task(task['id'])['admission'], 'rejected')
        self.assert_pending(task)
        facts = self.observe(task)
        self.assertTrue(facts[task['id']]['groupStopped'])
        self.assert_completed(task)
        self.assertEqual(self.store.task(task['id'])['body']['stoppedStatus'], 'failed')
        self.assertEqual(self.fixture.records, [])

    def test_missing_completion_hook_cannot_release_original_holds(self):
        task, _, _ = self.root()
        self.store.application_runtime = ApplicationRuntimeRegistry(self.store)
        self.store.application_runtime.register('synthetic-completion', None,
            bindings=(('model', 'controlled-ledger-model-v1', '1'),), finalizes=True)
        self.assertIsNotNone(self.store.completion_context(task))
        self.observe(task)
        self.assert_pending(task)
        self.register_consumer()
        self.observe(task)
        self.assert_completed(task)

    def test_stopped_success_survives_later_scope_cancel_and_retained_context_denial(self):
        task, context, _ = self.root()
        self.fixture.options['scenario'] = 'unknown'
        self.fixture.invoke(self.fixture.selected(context))
        self.observe(task)
        self.scopes.cancel('alice', 'scope')
        with self.assertRaises(HTTPException):
            self.fixture.selected(context)
        self.observe(task)
        self.assertEqual(self.store.task(task['id'])['body']['stoppedStatus'], 'completed')
        self.assertFalse(self.store.task(task['id'])['cancel_requested'])
        history = self.store.task_history('alice')['items'][0]
        self.assertEqual((history['status'], history['executionStatus']), ('finalizing', 'completed'))
        attempt = self.fixture.projection(task)['attempts'][0]
        self.base.ledger.finish_attempt(attempt['id'], UsageEvidence(3, 2, 'original-authoritative-observation'))
        self.observe(task)
        self.assert_completed(task)
        self.assertEqual(self.store.task_history('alice')['items'][0]['executionStatus'], 'completed')

    def test_failed_native_category_survives_callback_rollback(self):
        task, _, _ = self.root()
        self.tickets[task['run_id']]['status'] = 'failed'
        self.consumer.failure = 'callback'
        with self.assertRaisesRegex(RuntimeError, 'Synthetic completion'):
            self.observe(task)
        self.assert_pending(task)
        history = self.store.task_history('alice')['items'][0]
        self.assertEqual((history['status'], history['executionStatus'], history['finalizationPending']),
                         ('finalizing', 'failed', True))
        self.consumer.failure = None
        self.observe(task)
        self.assert_completed(task)
        history = self.store.task_history('alice')['items'][0]
        self.assertEqual((history['status'], history['executionStatus'], history['finalizationPending']),
                         ('failed', 'failed', False))

    def child(self, root):
        binding = {'rootTaskId': root['id'], 'parentTaskId': root['id'], 'depth': 1}
        plan = self.fixture.plan(extra={'tools': ['checksum'], 'delegation': binding})
        child, context = self.fixture.task(plan)
        self.store.sql("""INSERT INTO af_delegation_links
            (owner_id,parent_id,request_id,root_id,depth,fingerprint,plan_id,child_id,created_at)
            VALUES(:owner,:parent,:request,:root,1,:fingerprint,:plan,:child,:created)""",
            owner='alice', parent=root['id'], request=str(uuid4()), root=root['id'],
            fingerprint=digest(binding), plan=plan['id'], child=child['id'], created=now())
        self.tickets[context.run_id] = {
            'id': context.run_id, 'session_id': child['id'], 'user_id': 'alice',
            'component_type': 'agent', 'component_id': 'factory-executor',
            'idempotency_key': digest({'owner': 'alice', 'task': child['id'], 'request': child['request_id']}),
            'status': 'completed', 'payload': {'kwargs': {'session_state': context.session_state}}}
        return child

    def test_child_group_rolls_back_together_and_parent_allocation_settles_once(self):
        task, context, _ = self.root()
        child = self.child(task)
        self.fixture.invoke(self.fixture.selected(context))
        held = self.scopes.inspect('alice', 'scope')['usage']
        self.consumer.failure = 'callback'
        with self.assertRaisesRegex(RuntimeError, 'Synthetic completion'):
            self.observe(task)
        self.assert_pending(task)
        self.assertFalse(self.store.task(child['id'])['terminal'])
        self.assertEqual(self.store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=child['id'])[0]['state'], 'HELD')
        self.assertEqual(self.scopes.inspect('alice', 'scope')['usage'], held)
        self.consumer.failure = None
        self.observe(task)
        self.assert_completed(task, [child])
        self.assertTrue(self.store.task(child['id'])['terminal'])
        self.assertEqual(self.store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=child['id'])[0]['state'], 'RELEASED')
        settled = self.scopes.inspect('alice', 'scope')
        self.assertEqual(len(settled['allocations']), 1)
        self.assertEqual(settled['usage']['settled_tokens'], 5)
        self.observe(task)
        self.assertEqual(self.scopes.inspect('alice', 'scope'), settled)
        self.assertEqual(len(self.store.sql('SELECT task_id FROM fixture_outbox')), 1)

    def test_two_observers_and_reserve_share_commit_without_duplicate_outbox(self):
        task, _, _ = self.root()
        other_plan = self.fixture.plan()
        entered, release = Event(), Event()
        contenders = Barrier(3)
        original = self.consumer.finalization_context
        @contextmanager
        def paused(conn, root):
            with original(conn, root) as complete:
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('Completion test barrier was not released')
                yield complete
        second_observer = self.new_observer()
        def observe_again():
            contenders.wait(10)
            return second_observer._observe_stopped(self.store.task(task['id']))
        def reserve():
            contenders.wait(10)
            return self.store.reserve_task(other_plan, 'concurrent-reservation')
        with patch.object(self.consumer, 'finalization_context', paused), ThreadPoolExecutor(max_workers=3) as workers:
            first = workers.submit(self.observe, task)
            try:
                self.assertTrue(entered.wait(10))
                second = workers.submit(observe_again)
                admission = workers.submit(reserve)
                contenders.wait(10)
                # Committed reads outside the paused completion transaction retain custody.
                self.assert_pending(task)
            finally:
                release.set()
            self.assertTrue(first.result(timeout=15)[task['id']]['finalizationCommitted'])
            self.assertTrue(second.result(timeout=15)[task['id']]['finalizationCommitted'])
            other, fresh = admission.result(timeout=15)
            self.assertTrue(fresh)
            self.assertNotEqual(other['id'], task['id'])
        self.assert_completed(task)
        self.assertEqual(len(self.store.sql('SELECT task_id FROM fixture_outbox')), 1)
        self.assertEqual(len(self.store.tasks('alice')), 2)

    def test_actual_delegation_create_rejects_new_child_after_positive_stop(self):
        task, context, _ = self.root()
        self.fixture.options['scenario'] = 'unknown'
        self.fixture.invoke(self.fixture.selected(context))
        self.observe(task)
        self.assert_pending(task)
        dispatch = AsyncMock()
        self.store.delegation.bridge = SimpleNamespace(submit=dispatch)
        with self.assertRaises(HTTPException) as rejected:
            asyncio.run(self.store.delegation.create('alice', task['id'], 'No extra experiment', 'direct', 'after-stop-child'))
        self.assertEqual(rejected.exception.status_code, 409)
        dispatch.assert_not_called()
        self.assertEqual(self.store.sql('SELECT child_id FROM af_delegation_links'), [])
        self.assertEqual([item['id'] for item in self.store.tasks('alice')], [task['id']])
        self.assertEqual(self.fixture.records, ['unknown'])

"""Real PG scope accounting with controlled Agno provider primitives; no paid IO."""
from concurrent.futures import ThreadPoolExecutor
import os
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import event, select

from agent_factory.delegation import DelegationService
from agent_factory.local_budget_scopes import LocalBudgetScopes
from agent_factory.store import digest, now
from agent_factory.usage_ledger import UsageEvidence
import test_usage_ledger_postgres as usage_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class LocalBudgetScopesPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = usage_fixture.UsageLedgerPostgresTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.ledger = self.fixture.store, self.fixture.ledger
        self.addCleanup(self.store.dispose_root_locks)
        self.delegation = DelegationService(self.fixture.settings, self.store, self.fixture.auth, None)
        self.delegation.initialize()
        self.store.delegation = self.delegation
        self.scopes = LocalBudgetScopes(self.store, self.ledger)
        self.store.local_budget_scopes = self.scopes
        self.deadline = time.time() + 300

    def caps(self, rounds=1, tools=2, tokens=10, amount=16):
        return {'rounds': rounds, 'toolCalls': tools, 'tokenLimit': tokens,
                'amountMicros': amount if tokens is not None else None,
                'currency': 'USD' if tokens is not None else None}

    def scope(self, caps=None):
        return self.scopes.create_scope('alice', 'scope', digest({'original': 'commitment'}),
                                        caps or self.caps(rounds=3, tools=8, tokens=30, amount=48), self.deadline)

    def allocate(self, identity='round-1', caps=None, intent=None):
        with self.store.transaction() as conn:
            return self.scopes.allocate(conn, 'alice', 'scope', identity,
                                       intent or digest({'round': identity}), caps or self.caps())

    def root(self, allocation='round-1', plan=None):
        plan = plan or self.fixture.plan()
        task, context = self.fixture.task(plan, accepted=False)
        with self.store.transaction() as conn:
            self.scopes.bind_root(conn, 'alice', allocation, task['id'], digest(plan))
        self.store.accept(task['id'], context.run_id)
        return self.store.task(task['id']), context, plan

    def ended(self, task):
        self.store.observed(self.store.task(task['id']), 'completed', True)

    def account(self, identity):
        with self.store.transaction(read_only=True) as conn:
            return dict(conn.execute(select(self.ledger.accounts).where(
                self.ledger.accounts.c.id == identity)).mappings().one())

    def test_concurrent_duplicate_allocation_holds_once_and_conflicts(self):
        self.scope()
        with ThreadPoolExecutor(max_workers=4) as workers:
            values = list(workers.map(lambda _: self.allocate(), range(4)))
        self.assertTrue(all(value == values[0] for value in values))
        state = self.scopes.inspect('alice', 'scope')
        self.assertEqual((state['allocatedRounds'], state['heldToolCalls']), (1, 2))
        self.assertEqual(state['usage']['held_tokens'], 10)
        with self.assertRaises(HTTPException) as caught:
            self.allocate(intent=digest({'changed': True}))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.scopes.inspect('alice', 'scope'), state)

    def test_concurrent_distinct_allocations_respect_whole_scope_hold(self):
        self.scope(self.caps(rounds=4, tools=8, tokens=10, amount=16))
        def allocate(identity):
            try:
                self.allocate(identity)
                return 'accepted'
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(allocate, ('one', 'two')))
        self.assertCountEqual(results, ['accepted', 429])
        self.assertEqual(self.scopes.inspect('alice', 'scope')['allocatedRounds'], 1)

    def test_actual_provider_settles_round_once_without_double_scope_hold(self):
        self.scope(self.caps(rounds=3, tools=6, tokens=14, amount=23))
        self.allocate()
        task, context, _ = self.root()
        self.fixture.invoke(self.fixture.selected(context))
        self.assertEqual(self.fixture.records, ['success'])
        scope_before = self.scopes.inspect('alice', 'scope')
        self.assertEqual(scope_before['usage'], {'held_tokens': 10, 'held_amount': 16,
                                               'settled_tokens': 0, 'settled_amount': 0})
        account = self.account('local-round:round-1')
        self.assertEqual((account['held_tokens'], account['settled_tokens'], account['settled_amount']), (0, 5, 7))
        attempts = self.store.sql('SELECT body FROM af_usage_attempts')
        self.assertIn('local-round:round-1', attempts[0]['body']['accountIds'])
        self.assertNotIn('local-scope:scope', attempts[0]['body']['accountIds'])
        self.ended(task)
        statement = self.scopes.settle('alice', 'round-1')
        self.assertEqual((statement['state'], statement['settledTokens'], statement['settledAmountMicros']), ('SETTLED', 5, 7))
        state = self.scopes.inspect('alice', 'scope')
        self.assertEqual(self.scopes.settle('alice', 'round-1'), statement)
        self.assertEqual(self.scopes.inspect('alice', 'scope'), state)
        with self.assertRaises(HTTPException) as caught:
            self.allocate('round-2')  # Actual 5 + new full commitment 10 exceeds 14.
        self.assertEqual(caught.exception.status_code, 429)
        self.allocate('round-2', self.caps(tokens=9, amount=16))
        self.assertEqual(self.scopes.inspect('alice', 'scope')['usage']['held_tokens'], 9)

    def test_unknown_attempt_remains_held_until_original_usage_is_settled(self):
        self.scope(); self.allocate()
        task, context, _ = self.root()
        self.fixture.options['scenario'] = 'unknown'
        self.fixture.invoke(self.fixture.selected(context))
        self.ended(task)
        self.assertEqual(self.scopes.settle('alice', 'round-1')['state'], 'HELD')
        attempt = self.fixture.projection(task)['attempts'][0]
        self.assertEqual(attempt['state'], 'UNKNOWN')
        self.ledger.finish_attempt(attempt['id'], UsageEvidence(3, 2, 'original-authoritative-observation'))
        self.assertEqual(self.scopes.settle('alice', 'round-1')['state'], 'SETTLED')
        self.assertEqual(self.fixture.records, ['unknown'])

    def test_unmetered_scope_still_holds_unknown_native_attempt(self):
        self.scope(self.caps(rounds=2, tools=4, tokens=None))
        self.allocate(caps=self.caps(tokens=None))
        task, context, _ = self.root()
        self.fixture.options['scenario'] = 'unknown'
        self.fixture.invoke(self.fixture.selected(context))
        self.ended(task)
        self.assertEqual(self.scopes.settle('alice', 'round-1')['state'], 'HELD')

    def test_original_task_and_plan_cannot_be_rebound(self):
        self.scope(); self.allocate()
        plan = self.fixture.plan()
        task, _ = self.fixture.task(plan, accepted=False)
        with self.store.transaction() as conn:
            initial = self.scopes.bind_root(conn, 'alice', 'round-1', task['id'], digest(plan))
            self.assertEqual(self.scopes.bind_root(conn, 'alice', 'round-1', task['id'], digest(plan)), initial)
        with self.assertRaises(HTTPException) as duplicate:
            self.fixture.task(plan, accepted=False)
        self.assertEqual(duplicate.exception.detail, 'LOCAL_BUDGET_REQUEST_PLAN_CONFLICT')
        other_plan = self.fixture.plan()
        other, _ = self.fixture.task(other_plan, accepted=False)
        for task_id, sha in ((other['id'], digest(other_plan)), (task['id'], '0' * 64)):
            with self.assertRaises(HTTPException) as caught, self.store.transaction() as conn:
                self.scopes.bind_root(conn, 'alice', 'round-1', task_id, sha)
            self.assertEqual(caught.exception.detail, 'LOCAL_BUDGET_BINDING_CONFLICT')
        self.allocate('round-2')
        active, _ = self.fixture.task(self.fixture.plan())
        with self.assertRaises(HTTPException) as caught, self.store.transaction() as conn:
            self.scopes.bind_root(conn, 'alice', 'round-2', active['id'], digest(self.store.plan(active['plan_id'], 'alice')))
        self.assertEqual(caught.exception.detail, 'LOCAL_BUDGET_ORIGINAL_ROOT_REQUIRED')

    def test_unknown_effect_and_pending_child_keep_full_commitment(self):
        self.scope(); self.allocate()
        task, context, _ = self.root()
        self.store.effect_reserve(context.run_id, 'original-tool', {'input': 'synthetic'})
        self.ended(task)
        self.assertEqual(self.scopes.settle('alice', 'round-1')['state'], 'HELD')
        self.store.effect_complete(context.run_id, 'original-tool', {'allStopped': True})
        self.ended(task)
        child_plan = self.fixture.plan(extra={'delegation': {'parentTaskId': task['id'], 'rootTaskId': task['id'], 'depth': 1}})
        self.store.sql('INSERT INTO af_delegation_links VALUES(:owner,:parent,:request,:root,:depth,:fp,:plan,:child,:at)',
            owner='alice', parent=task['id'], request='child-request', root=task['id'], depth=1,
            fp='original-child-intent', plan=child_plan['id'], child=None, at=now())
        self.assertEqual(self.scopes.settle('alice', 'round-1')['state'], 'HELD')
        self.assertEqual(self.scopes.inspect('alice', 'scope')['usage']['held_tokens'], 10)
        child, _ = self.fixture.task(child_plan)
        self.store.sql('UPDATE af_delegation_links SET child_id=:child WHERE parent_id=:parent',
                       child=child['id'], parent=task['id'])
        self.assertEqual(self.scopes.settle('alice', 'round-1')['state'], 'HELD')
        self.ended(child)
        self.assertEqual(self.scopes.settle('alice', 'round-1')['state'], 'SETTLED')

    def test_deadline_cancel_and_scope_tool_budget_use_original_native_call(self):
        self.scope(self.caps(rounds=2, tools=2, tokens=None))
        self.allocate(caps=self.caps(tools=1, tokens=None))
        task, context, _ = self.root(plan=self.fixture.plan(extra={'tools': ['controlled-tool']}))
        stamp = int(time.time())
        self.fixture.db.enqueue_job({'id': context.run_id, 'component_type': 'agent', 'component_id': 'factory-executor',
            'job_type': 'run', 'session_id': task['id'], 'user_id': 'alice', 'payload': {}, 'status': 'queued',
            'attempt': 0, 'max_attempts': 1, 'available_at': stamp, 'created_at': stamp})
        first = self.delegation.consume_tool_budget(context, 'original-call', 'controlled-tool')
        self.assertTrue(first['charged'])
        self.assertFalse(self.delegation.consume_tool_budget(context, 'original-call', 'controlled-tool')['charged'])
        with self.assertRaises(HTTPException) as caught:
            self.delegation.consume_tool_budget(context, 'new-call', 'controlled-tool')
        self.assertEqual(caught.exception.detail, 'LOCAL_BUDGET_TOOL_CALLS_EXHAUSTED')
        with patch('agent_factory.local_budget_scopes.time.time', return_value=self.deadline + 1):
            with self.assertRaises(HTTPException):
                self.fixture.invoke(self.fixture.selected(context))
        self.assertEqual(self.fixture.records, [])
        self.scopes.cancel('alice', 'scope')
        with self.assertRaises(HTTPException):
            self.allocate('round-2', self.caps(tokens=None))
        with self.assertRaises(HTTPException):
            self.fixture.invoke(self.fixture.selected(context))
        self.assertEqual(self.scopes.inspect('alice', 'scope')['heldToolCalls'], 1)

    def test_inspect_is_postgres_read_only_and_never_settles(self):
        self.scope(); self.allocate()
        task, _, _ = self.root()
        self.ended(task)
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.strip().upper())
        event.listen(self.store.engine, 'before_cursor_execute', capture)
        try:
            before = self.scopes.inspect('alice', 'scope')
            self.assertEqual(self.scopes.inspect('alice', 'scope'), before)
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', capture)
        self.assertTrue(any('READ ONLY' in statement for statement in statements))
        self.assertFalse(any(statement.startswith(('INSERT', 'UPDATE', 'DELETE')) for statement in statements))
        self.assertEqual(before['allocations'][0]['state'], 'BOUND')
        self.assertEqual(before['usage']['held_tokens'], 10)

    def test_byok_cannot_bind_metered_scope_but_unmetered_caps_are_explicit(self):
        from agent_factory.byok_model import ADAPTER_ID
        self.scope(); self.allocate()
        # Bind-only archived plan fixture: no BYOK account/model is invoked.
        plan = self.fixture.plan(legacy=True, extra={'executionBindings': {'model': {'adapterId': ADAPTER_ID}}})
        task, _ = self.fixture.task(plan, accepted=False)
        with self.assertRaises(HTTPException) as caught, self.store.transaction() as conn:
            self.scopes.bind_root(conn, 'alice', 'round-1', task['id'], digest(plan))
        self.assertEqual(caught.exception.detail, 'LOCAL_BUDGET_METERING_UNAVAILABLE')
        with self.assertRaises(HTTPException):
            self.scopes.create_scope('alice', 'invalid', 'a' * 64,
                self.caps(tokens=None) | {'amountMicros': 1}, self.deadline)

"""Additional PG allocation boundaries, using controlled usage, not live ORX."""
import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.store import digest
from agent_factory.usage_ledger import UsageEvidence
import test_local_budget_scopes_postgres as scopes_fixture
import test_usage_ledger_postgres as usage_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class LocalBudgetScopeBoundaryPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = scopes_fixture.LocalBudgetScopesPostgresTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.store, self.scopes, self.ledger = self.base.store, self.base.scopes, self.base.ledger
        self.provider = self.base.fixture

    def test_conflicting_usage_after_scope_settlement_cannot_rewrite_charge(self):
        self.base.scope(); self.base.allocate()
        task, context, plan = self.base.root()
        attempt = self.ledger.begin_attempt(context, plan, usage_fixture.ControlledModel(self.provider.records))
        evidence = UsageEvidence(3, 2, 'original-scope-evidence')
        self.ledger.finish_attempt(attempt, evidence)
        self.base.ended(task)
        statement = self.scopes.settle('alice', 'round-1')
        before = self.scopes.inspect('alice', 'scope')
        round_account = self.base.account('local-round:round-1')
        with self.assertRaises(HTTPException) as caught:
            self.ledger.finish_attempt(attempt, UsageEvidence(3, 3, 'conflicting-scope-evidence'))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn('USAGE_SETTLEMENT_CONFLICT', caught.exception.detail)
        self.assertEqual(self.scopes.settle('alice', 'round-1'), statement)
        self.assertEqual(self.scopes.inspect('alice', 'scope'), before)
        self.assertEqual(self.base.account('local-round:round-1'), round_account)
        self.assertEqual((statement['settledTokens'], statement['settledAmountMicros']), (5, 7))

    def test_actual_overage_transfers_in_full_and_denies_new_round(self):
        self.base.scope(self.base.caps(rounds=2, tools=4, tokens=10, amount=16))
        self.base.allocate()
        task, context, plan = self.base.root()
        attempt = self.ledger.begin_attempt(context, plan, usage_fixture.ControlledModel(self.provider.records))
        self.ledger.finish_attempt(attempt, UsageEvidence(12, 3, 'actual-overage'))
        self.base.ended(task)
        statement = self.scopes.settle('alice', 'round-1')
        self.assertEqual((statement['settledTokens'], statement['settledAmountMicros']), (15, 18))
        before = self.scopes.inspect('alice', 'scope')
        self.assertEqual(before['usage'], dict(held_tokens=0, held_amount=0, settled_tokens=15, settled_amount=18))
        with self.assertRaises(HTTPException) as caught:
            self.base.allocate('round-2')
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(self.scopes.inspect('alice', 'scope'), before)
        self.assertEqual(before['allocatedRounds'], 1)
        self.assertEqual(len(before['allocations']), 1)

    def test_revoked_member_original_response_still_settles_scope(self):
        self.base.scope(); self.base.allocate()
        task, context, _ = self.base.root()
        self.provider.options['after'] = lambda: self.provider.auth.directory.set_disabled('alice', True)
        model = self.provider.selected(context)
        with self.assertRaises(HTTPException):
            self.provider.invoke(model)
        self.assertEqual(self.provider.records, ['success'])
        self.base.ended(task)
        statement = self.scopes.settle('alice', 'round-1')
        self.assertEqual((statement['settledTokens'], statement['settledAmountMicros']), (5, 7))
        before = self.scopes.inspect('alice', 'scope')
        with self.assertRaises(HTTPException):
            self.provider.invoke(model)
        self.assertEqual(self.provider.records, ['success'])
        self.assertEqual(self.scopes.inspect('alice', 'scope'), before)
        self.assertEqual(before['usage']['held_tokens'], 0)

    def test_successor_budget_and_deadline_rejection_leave_no_free_intent(self):
        # Synthetic driver evidence isolates the PG activity/allocation transaction.
        # Actual recipe artifacts are covered by test_research_iterations_postgres.
        from agent_factory_research.research_iterations import IterationPreset, ResearchIterations
        from agent_factory_research.services import ResearchServices
        from agent_factory_research import research_iterations as iterations_module

        contexts, reservations = {}, []
        def reserve(owner, activity, round):
            plan = self.provider.plan()
            task, context = self.provider.task(plan, accepted=False)
            contexts[task['id']] = context
            reservations.append(task['id'])
            return dict(taskId=task['id'], planId=plan['id'], planSha256=digest(plan))

        async def dispatch(owner, round):
            self.store.accept(round['taskId'], contexts[round['taskId']].run_id)

        async def observe(owner, round):
            baseline = round['baselineSource']
            pins = {key: baseline[key] for key in ('datasetSha256', 'evaluatorSha256')}
            return dict(state='stopped', taskId=round['taskId'], runId=contexts[round['taskId']].run_id,
                evaluation=dict(pins, artifactId='controlled-evaluation', sha256='e' * 64,
                    metric='mean_squared_error', baselineValue=16, candidateValue=0,
                    baselineSourceSha256=baseline['sha256'], candidateSourceSha256='f' * 64),
                sourcePin=dict(pins, kind='sourceArtifact', ownerId=owner, taskId=round['taskId'],
                    artifactId='controlled-source', sha256='f' * 64))

        async def cancel(owner, round):
            self.fail('No running successor exists to cancel')

        preset = IterationPreset('controlled', 'alice', 'controlled-preset', {},
            dict(kind='reviewedSeed', sha256='a' * 64, datasetSha256='b' * 64,
                 evaluatorSha256='c' * 64, metricValue=16), self.base.caps(), 10)
        service = ResearchIterations(self.store, self.provider.auth,
            research=ResearchServices(factory_store=self.store, installed=True), presets={'controlled': preset},
            round_driver=SimpleNamespace(reserve=reserve, dispatch=dispatch, observe=observe, cancel=cancel))
        initial = asyncio.run(service.start('alice', 'controlled', 'Improve controlled fixture', 'original-request',
            caps=self.base.caps(rounds=2, tools=4, tokens=14, amount=23), deadline=self.base.deadline))
        activity, round = initial['activity']['id'], initial['rounds'][0]
        self.provider.invoke(self.provider.selected(contexts[round['taskId']]))
        self.base.ended(self.store.task(round['taskId']))
        ready = asyncio.run(service.reconcile('alice', activity))
        self.assertEqual(ready['activity']['status'], 'ready')
        original_tasks = self.store.sql('SELECT id FROM af_tasks ORDER BY id')
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(service.advance('alice', activity, round['id'], 'insufficient-budget'))
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(service.inspect('alice', activity), ready)
        self.assertEqual(self.store.sql('SELECT id FROM af_tasks ORDER BY id'), original_tasks)
        with self.store.transaction(read_only=True) as conn:
            self.assertEqual(len(conn.execute(select(service.rounds)).all()), 1)
            self.assertEqual(len(conn.execute(select(self.scopes.allocations)).all()), 1)
        with patch.object(iterations_module, 'time', SimpleNamespace(time=lambda: self.base.deadline - 1)):
            final = asyncio.run(service.advance('alice', activity, round['id'], 'deadline-boundary'))
        self.assertEqual(final['activity']['stopReason'], 'deadline')
        self.assertEqual(final['activity']['deadline'], self.base.deadline)
        self.assertEqual(final['rounds'], ready['rounds'])
        self.assertEqual(final['budget'], ready['budget'])
        self.assertEqual(reservations, [round['taskId']])
        self.assertEqual(self.store.sql('SELECT id FROM af_tasks ORDER BY id'), original_tasks)

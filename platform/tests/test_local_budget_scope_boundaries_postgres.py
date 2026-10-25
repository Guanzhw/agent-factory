"""Additional PG allocation boundaries, using controlled usage, not live ORX."""
import os
import unittest

from fastapi import HTTPException

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

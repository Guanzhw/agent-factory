"""Real SQLite member policy; synthetic remote journal/link, no native launch."""
from agent_factory_research.services import services_for
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.db.sqlite import SqliteDb
from fastapi import HTTPException
from agent_factory.plan_policy import PlanPolicyConfig
from agent_factory_research.policy_compatibility import ResearchPlanPolicyService as PlanPolicyService
from agent_factory.store import Store
from test_plan_policy import MetadataFixture, historical_review


class RemoteScientificPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = SqliteDb(db_file=str(Path(self.temp.name) / 'metadata.sqlite'))
        self.settings = SimpleNamespace(demo=True, temporary_policy='member-self-service')
        self.store = MetadataFixture(self.db, self.settings)
        self.auth = SimpleNamespace(require_member=Mock())
        self.policy = PlanPolicyService(self.store, self.auth,
            PlanPolicyConfig(revision='member-policy-v1'),
            clock=lambda: datetime(2026, 10, 7, tzinfo=timezone.utc))
        self.parent_plan = self.store.add()
        self.child_plan = self.store.add(delegation={'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': 1})
        self.parent = {'id': 'parent', 'owner_id': 'alice', 'plan_id': self.parent_plan['id'], 'run_id': 'original-parent-run'}
        self.child = {'id': 'child', 'owner_id': 'alice', 'plan_id': self.child_plan['id'], 'run_id': None,
                      'cancel_requested': False, 'terminal': False, 'admission': 'accepted'}
        self.tasks = {'parent': self.parent, 'child': self.child}
        def task(identifier, owner):
            result = self.tasks[identifier]
            if result['owner_id'] != owner:
                raise HTTPException(404, 'OWNED_TASK_REQUIRED')
            return deepcopy(result)
        self.store.task = task
        self.store.has_failures = Mock(return_value=False)
        self.link = {'child_id': 'child', 'owner_id': 'alice', 'parent_id': 'parent', 'root_id': 'parent',
                     'depth': 1, 'plan_id': self.child_plan['id']}
        self.store.delegation = SimpleNamespace(_link=Mock(side_effect=lambda _: deepcopy(self.link)),
            _mandate=Mock(return_value=('parent', [self.parent_plan])))
        self.envelope = {'fixedSyntheticEnvelope': True}
        services_for(self.store).remote_scientific = SimpleNamespace(
            _row=Mock(return_value={'parent_id': 'parent', 'body': {'envelope': self.envelope}}),
            validate_source=Mock())
        self.store.auth = self.auth
        self.store.plan_policy = self.policy
        self.store.execution_guards = {}

    def tearDown(self):
        self.db.db_engine.dispose()
        self.temp.cleanup()

    def execute(self, **kwargs):
        return self.policy.require_execution('alice', self.child_plan, scientific_child_id='child', **kwargs)

    def test_exact_journal_link_uses_member_execution_without_native_context(self):
        result = self.execute()
        self.assertTrue(result['allowed'])
        self.assertEqual(result['source'], 'member-self-service')
        self.assertIsNone(result['reviewId'])
        self.assertEqual(result['planId'], self.child_plan['id'])
        services_for(self.store).remote_scientific.validate_source.assert_called_with(self.child_plan, self.envelope)
        self.store.delegation._mandate.assert_called_with('alice', self.parent)

    def test_missing_or_changed_journal_link_and_child_native_identity_deny(self):
        for key, value in [('run_id', 'unexpected-native'), ('plan_id', 'wrong-plan')]:
            with self.subTest(key=key):
                original = self.child[key]; self.child[key] = value
                with self.assertRaises(HTTPException): self.execute()
                self.child[key] = original
        with self.assertRaises(HTTPException): self.execute(run_context=SimpleNamespace())
        for key in ('parent_id', 'root_id', 'depth', 'owner_id', 'child_id', 'plan_id'):
            old = self.link[key]; self.link[key] = 'changed'
            with self.subTest(key=key), self.assertRaises(HTTPException): self.execute()
            self.link[key] = old
        services_for(self.store).remote_scientific.validate_source.side_effect = HTTPException(409, 'JOURNAL_CHANGED')
        with self.assertRaises(HTTPException): self.execute()

    def test_current_child_cancel_terminal_failure_and_boolean_depth_deny(self):
        for key in ('cancel_requested', 'terminal'):
            self.child[key] = True
            with self.subTest(key=key), self.assertRaises(HTTPException): self.execute()
            self.child[key] = False
        self.store.has_failures.return_value = True
        with self.assertRaises(HTTPException): self.execute()
        self.store.has_failures.return_value = False
        self.link['depth'] = True
        with self.assertRaises(HTTPException): self.execute()

    def test_parent_scope_budget_and_current_mandate_still_deny(self):
        for change in ({'tools': []}, {'capabilities': []},
                       {'budget': {**self.parent_plan['budget'], 'toolCalls': 1}}):
            ancestor = self.store.add(**change)
            self.store.delegation._mandate.return_value = ('parent', [ancestor])
            with self.subTest(change=change):
                with self.assertRaises(HTTPException) as raised:
                    self.execute()
                self.assertIn(raised.exception.status_code, (403, 409))
        self.store.delegation._mandate.side_effect = HTTPException(403, 'CURRENT_PARENT_REVOKED')
        with self.assertRaises(HTTPException): self.execute()

    def test_store_installed_guards_receive_no_fabricated_context_and_cannot_be_bypassed(self):
        guard = Mock(side_effect=HTTPException(403, 'CURRENT_BINDING_DENIED'))
        self.store.execution_guards['binding'] = guard
        with self.assertRaises(HTTPException):
            Store.require_plan_execution(self.store, 'alice', self.child_plan, scientific_child_id='child')
        guard.assert_called_once_with('alice', self.child_plan, None, None)
        guard.side_effect = None
        checked = Store.require_plan_execution(self.store, 'alice', self.child_plan, scientific_child_id='child')
        self.assertIs(checked['binding'], guard)
        self.auth.require_member.side_effect = HTTPException(403, 'CURRENT_OWNER_REVOKED')
        with self.assertRaises(HTTPException): self.execute()

    def test_non_delegated_plan_cannot_use_scientific_metadata_identity(self):
        with self.assertRaises(HTTPException) as raised:
            self.policy.require_execution('alice', self.parent_plan, scientific_child_id='child')
        self.assertEqual(raised.exception.status_code, 409)
        services_for(self.store).remote_scientific._row.assert_not_called()
        self.store.delegation._mandate.assert_not_called()

    def test_missing_journal_service_or_link_denies_before_execution(self):
        service = services_for(self.store).remote_scientific
        services_for(self.store).remote_scientific = None
        with self.assertRaises(HTTPException): self.execute()
        services_for(self.store).remote_scientific = service
        service._row.side_effect = HTTPException(404, 'ORIGINAL_JOURNAL_MISSING')
        with self.assertRaises(HTTPException): self.execute()
        service._row.side_effect = None
        self.store.delegation._link.side_effect = None
        self.store.delegation._link.return_value = None
        with self.assertRaises(HTTPException): self.execute()
        self.store.delegation._mandate.assert_not_called()

    def test_expired_historical_parent_review_does_not_gate_current_member(self):
        historical = historical_review(self.policy, self.parent_plan, decision='approved')
        self.assertTrue(self.execute()['allowed'])
        self.policy.clock = lambda: datetime(2026, 10, 9, tzinfo=timezone.utc)
        self.assertTrue(self.execute()['allowed'])
        review = self.policy.inspect('alice', historical['id'])
        self.assertTrue(review['expired'])
        self.assertFalse(review['approvalEffective'])
        self.auth.require_member.side_effect = HTTPException(403, 'CURRENT_MEMBER_DISABLED')
        with self.assertRaises(HTTPException): self.execute()

    def test_all_installed_guards_run_with_absent_native_context(self):
        first, second = Mock(), Mock(side_effect=HTTPException(403, 'SECOND_GUARD_DENIED'))
        self.store.execution_guards.update(first=first, second=second)
        with self.assertRaises(HTTPException):
            Store.require_plan_execution(self.store, 'alice', self.child_plan, scientific_child_id='child')
        for guard in (first, second):
            guard.assert_called_once_with('alice', self.child_plan, None, None)

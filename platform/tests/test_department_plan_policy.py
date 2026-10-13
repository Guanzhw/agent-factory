"""Department submission, immutable migration, and current native identity."""
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from agno.db.sqlite import SqliteDb
from fastapi import HTTPException

from agent_factory.auth import AuthService
from agent_factory.plan_policy import PlanPolicyConfig, PlanPolicyService
from test_plan_policy import MetadataFixture


class DepartmentPlanPolicyTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = SqliteDb(db_file=str(Path(folder.name) / 'department.sqlite'))
        self.addCleanup(self.db.db_engine.dispose)
        self.settings = SimpleNamespace(demo=True, jwt_key=secrets.token_urlsafe(48))
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        self.store = MetadataFixture(self.db, self.settings)

    def test_default_accepts_every_registered_application_and_workflow_without_review(self):
        service = PlanPolicyService(self.store, self.auth)
        self.assertEqual(service.current()['name'], 'member-self-service')
        for app, component in [('department-analysis', None), ('new-application', None),
                               ('department-workflow', {'kind': 'workflow', 'id': 'fixture-workflow'})]:
            plan = self.store.add(application=app, nativeComponent=component, policy='member-self-service')
            status = service.status('alice', plan)
            self.assertTrue(status['executionAllowed'])
            self.assertFalse(status['reviewRequired'])
            self.assertFalse(status['reviewRequestSupported'])
            self.assertEqual(status['approval']['source'], 'member-self-service')
            with self.assertRaises(HTTPException) as readonly:
                service.request_review('alice', plan['id'], app)
            self.assertEqual(readonly.exception.status_code, 410)
        self.assertEqual(service.list_reviews('alice'), [])

    def test_migration_preserves_decisions_and_never_releases_old_plans(self):
        legacy = PlanPolicyService(self.store, self.auth, PlanPolicyConfig(name='admin-review', revision='old'))
        plans, reviews = [], []
        for index, approved in enumerate([None, False, True]):
            plan = self.store.add(policy='admin-review')
            review = legacy.request_review('alice', plan['id'], 'legacy-' + str(index))
            if approved is not None:
                legacy.decide('manager', review['id'], approved, 'decision-' + str(index))
            plans.append(plan); reviews.append(review)
        service = PlanPolicyService(self.store, self.auth)
        self.assertEqual([r['decision'] for r in service.list_reviews('alice')].count('approved'), 1)
        for plan, review in zip(plans, reviews):
            status = service.status('alice', plan)
            self.assertFalse(status['executionAllowed'])
            self.assertIn('LEGACY_PLAN_READ_ONLY', status['reason'])
            with self.assertRaises(HTTPException) as readonly:
                service.decide('manager', review['id'], True, 'new-decision')
            self.assertEqual(readonly.exception.status_code, 410)
        self.assertTrue(service.status('alice', self.store.add(policy='member-self-service'))['executionAllowed'])
        # New defaults do not bypass tool authority, disabled users or ownership.
        for changes in [{'tools': ['shell']}, {'capabilities': ['agent_os:admin']}, {'status': 'blocked'}]:
            self.assertFalse(service.status('alice', self.store.add(policy='member-self-service', **changes))['executionAllowed'])
        with self.assertRaises(HTTPException): service.require_execution('bob', plans[0])
        self.auth.directory.set_disabled('alice', True)
        with self.assertRaises(HTTPException): service.require_execution('alice', plans[0])

    def test_configuration_upgrade_cannot_change_tool_contract_or_undo_emergency_stop(self):
        PlanPolicyService(self.store, self.auth, PlanPolicyConfig(name='unset', revision='emergency'))
        with self.assertRaises(ValueError): PlanPolicyService(self.store, self.auth)
        legacy = PlanPolicyService(self.store, self.auth, PlanPolicyConfig(name='unset', revision='emergency'))
        legacy.replace_configuration(PlanPolicyConfig(name='admin-review', revision='old'), expected_revision='emergency')
        with self.assertRaises(ValueError):
            PlanPolicyService(self.store, self.auth, PlanPolicyConfig(tool_contract='registered-runtime-v1'))
        self.assertEqual(legacy.current()['revision'], 'old')

    def test_component_author_is_not_an_administrator(self):
        self.auth.authorization.define_role('component-author', ['components:write', 'agents:factory-executor:run'])
        self.auth.directory.upsert('author', name='Department author')
        self.auth.authorization.assign('author', 'component-author')
        self.assertEqual(self.auth.identity('author')['role'], 'user')
        with self.assertRaises(HTTPException): self.auth.require('author', 'agent_os:admin')


if __name__ == '__main__':
    unittest.main()

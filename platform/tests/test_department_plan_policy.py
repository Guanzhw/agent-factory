"""Department submission, immutable migration, and current native identity."""
from fixture_auth import initialize_members
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
        self.settings = SimpleNamespace(jwt_key=secrets.token_urlsafe(48))
        self.auth = AuthService(self.settings, self.db)
        initialize_members(self.auth)
        self.store = MetadataFixture(self.db, self.settings)

    def test_default_accepts_every_application_and_workflow_without_review(self):
        service = PlanPolicyService(self.store, self.auth)
        for app, component in [("department-analysis", None), ("new-application", None),
                               ("department-workflow", {"kind": "workflow", "id": "fixture-workflow"})]:
            plan = self.store.add(application=app, nativeComponent=component,
                tools=["member_created_tool"], capabilities=["tool:invoke"], policy="member-self-service")
            status = service.status("alice", plan)
            self.assertTrue(status["executionAllowed"])
            self.assertFalse(status["reviewRequired"])
            self.assertFalse(status["reviewRequestSupported"])
        self.assertEqual(service.list_reviews("alice"), [])

    def test_old_configuration_tables_are_preserved_but_not_execution_inputs(self):
        from sqlalchemy import Column, JSON, MetaData, String, Table, select
        old_configs = Table("af_plan_policy_configs", MetaData(), Column("revision", String, primary_key=True),
            Column("policy_hash", String), Column("body", JSON))
        old_configs.metadata.create_all(self.store.engine)
        original = {"revision": "old-review", "policy_hash": "original-hash",
                    "body": {"name": "unset", "review_ttl_seconds": 3600}}
        with self.store.engine.begin() as conn:
            conn.execute(old_configs.insert().values(**original))
        service = PlanPolicyService(self.store, self.auth)
        plan = self.store.add(policy="admin-review")
        self.assertTrue(service.require_execution("alice", plan)["allowed"])
        with self.store.engine.connect() as conn:
            self.assertEqual(dict(conn.execute(select(old_configs)).mappings().one()), original)
        with self.assertRaises(ValueError): PlanPolicyConfig(name="admin-review")

    def test_current_membership_and_owner_are_the_authority(self):
        service = PlanPolicyService(self.store, self.auth)
        plan = self.store.add()
        self.auth.require_member("alice")
        with self.assertRaises(HTTPException): self.auth.require_account_admin("alice")
        with self.assertRaises(HTTPException): service.require_execution("bob", plan)
        self.auth.directory.set_disabled("alice", True)
        with self.assertRaises(HTTPException): service.require_execution("alice", plan)

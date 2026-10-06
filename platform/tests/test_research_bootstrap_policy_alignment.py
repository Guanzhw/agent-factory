"""Real SQLite governance constructors expose control/canonical policy drift.

No PostgreSQL, native worker, provider or model executes. Historical defaults are
retained as explicit negative fixtures; the actual CLI must align both policies.
"""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import importlib.util
import io
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import Mock

from agno.db.sqlite import SqliteDb
from agent_factory.material_governance import GovernanceConfig, MaterialGovernance
from agent_factory.plan_policy import PlanPolicyConfig, PlanPolicyService
from agent_factory.research_bootstrap_assembly import development_settings
from test_material_governance import PortableMetadata

spec = importlib.util.spec_from_file_location('alignment_control', Path(__file__).parents[2] / 'scripts/bootstrap_research_control.py')
assert spec is not None and spec.loader is not None
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def governance(settings):
    return GovernanceConfig(review_mode=settings.material_review_mode,
        revision=settings.material_policy_revision, tool_contract=settings.runtime_tool_contract)


def policy(settings):
    return PlanPolicyConfig(name=settings.temporary_policy, revision=settings.policy_revision,
        review_ttl_seconds=settings.plan_review_ttl_seconds, tool_contract=settings.runtime_tool_contract)


@unittest.skipUnless(os.name == 'posix', 'Control launcher requires private POSIX files')
class BootstrapPolicyAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        dsn = root / 'synthetic-dsn'
        dsn.write_text('postgresql+psycopg://fixture:synthetic-only@127.0.0.1:65432/synthetic'); dsn.chmod(0o600)
        factory, serve = Mock(return_value=object()), Mock()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = control.main(['--database-url-file', str(dsn), '--workspace', str(root / 'workspace'),
                '--port', '3101', '--ack-local-development', '--ack-dedicated-database'],
                build_application=factory, serve=serve)
        self.assertEqual(code, 0)
        self.actual = factory.call_args.args[0]
        self.canonical = development_settings(self.actual)
        self.db = SqliteDb(db_file=str(root / 'owned.sqlite'))
        self.addCleanup(self.db.db_engine.dispose)
        self.store = PortableMetadata(self.db, self.actual)

    def legacy(self):
        return replace(self.actual, material_policy_revision='material-governance-v1',
            policy_revision='plan-policy-v1', runtime_tool_contract='legacy-v1',
            plan_review_ttl_seconds=3600)

    def test_legacy_control_material_revision_conflicts_with_canonical(self):
        MaterialGovernance(self.store, None, governance(self.legacy()))
        with self.assertRaisesRegex(ValueError, '^Material governance configuration differs from persisted current revision$'):
            MaterialGovernance(self.store, None, governance(self.canonical))

    def test_legacy_control_plan_revision_conflicts_with_canonical(self):
        PlanPolicyService(self.store, None, policy(self.legacy()))
        with self.assertRaisesRegex(ValueError, '^Configured policy differs from persisted current revision; reconcile operator configuration$'):
            PlanPolicyService(self.store, None, policy(self.canonical))

    def test_shared_development_settings_can_reopen_both_governance_services(self):
        for _ in range(2):
            MaterialGovernance(self.store, None, governance(self.canonical))
            PlanPolicyService(self.store, None, policy(self.canonical))

    def test_actual_control_entry_then_canonical_reopens_without_policy_migration(self):
        MaterialGovernance(self.store, None, governance(self.actual))
        PlanPolicyService(self.store, None, policy(self.actual))
        MaterialGovernance(self.store, None, governance(self.canonical))
        PlanPolicyService(self.store, None, policy(self.canonical))
        self.assertEqual(governance(self.actual), governance(self.canonical))
        self.assertEqual(policy(self.actual), policy(self.canonical))

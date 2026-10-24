"""Control settings and runtime services reopen without persisted review gates."""
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
from sqlalchemy import text
from agent_factory.material_governance import GovernanceConfig, MaterialGovernance
from agent_factory.plan_policy import PlanPolicyConfig, PlanPolicyService
from agent_factory_research.research_bootstrap_assembly import development_settings
from test_material_governance import PortableMetadata

spec = importlib.util.spec_from_file_location('alignment_control', Path(__file__).parents[4] / 'scripts/bootstrap_research_control.py')
assert spec is not None and spec.loader is not None
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def governance(settings):
    return GovernanceConfig(review_mode=settings.material_review_mode,
        revision=settings.material_policy_revision, tool_contract=settings.runtime_tool_contract)


def policy(settings):
    return PlanPolicyConfig(name=settings.temporary_policy, revision=settings.policy_revision,
        tool_contract=settings.runtime_tool_contract)


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

    def test_control_and_canonical_settings_select_member_execution(self):
        self.assertEqual(self.actual.temporary_policy, 'member-self-service')
        self.assertEqual(self.actual.material_review_mode, 'member-self-service')
        self.assertEqual(governance(self.actual), governance(self.canonical))
        self.assertEqual(policy(self.actual), policy(self.canonical))

    def test_current_runtime_settings_can_change_revision_without_rebinding_history(self):
        for revision in ('prior-runtime-v1', 'current-runtime-v2'):
            settings = replace(self.actual, policy_revision=revision, material_policy_revision=revision)
            material = MaterialGovernance(self.store, None, governance(settings))
            plans = PlanPolicyService(self.store, None, policy(settings))
            self.assertEqual(material.current()['revision'], revision)
            self.assertEqual(plans.current()['revision'], revision)

    def test_historical_policy_rows_remain_unchanged_when_services_reopen(self):
        with self.store.engine.begin() as conn:
            conn.execute(text('CREATE TABLE af_plan_policy_state (id TEXT, revision TEXT)'))
            conn.execute(text("INSERT INTO af_plan_policy_state VALUES ('current','historical-admin-review')"))
            conn.execute(text('CREATE TABLE af_material_governance_current (id TEXT, revision TEXT)'))
            conn.execute(text("INSERT INTO af_material_governance_current VALUES ('current','historical-separate-admin')"))
        for _ in range(2):
            MaterialGovernance(self.store, None, governance(self.canonical))
            PlanPolicyService(self.store, None, policy(self.canonical))
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT revision FROM af_plan_policy_state')).scalar(), 'historical-admin-review')
            self.assertEqual(conn.execute(text('SELECT revision FROM af_material_governance_current')).scalar(), 'historical-separate-admin')

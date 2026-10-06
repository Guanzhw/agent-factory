"""Real SQLite read-only diagnostics; no Store, PostgreSQL or initialization."""
from contextlib import nullcontext
from unittest.mock import Mock, patch
from dataclasses import asdict
import json
from types import SimpleNamespace
import unittest

from sqlalchemy import create_engine, event, text
from agent_factory.material_governance import GovernanceConfig
from agent_factory.plan_policy import PlanPolicyConfig
from agent_factory.research_bootstrap_database_preflight import database_preflight


def settings():
    return SimpleNamespace(demo=True, material_review_mode='separate-admin',
        material_policy_revision='task-research-bootstrap-v1', runtime_tool_contract='research-bootstrap-v1',
        source_synthesis_enabled=False, temporary_policy='admin-review', policy_revision='task-research-bootstrap-v1',
        plan_review_ttl_seconds=86400)


class DatabasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        self.settings = settings()

    def seed(self, *, legacy=False):
        material = GovernanceConfig() if legacy else GovernanceConfig(revision=self.settings.material_policy_revision, tool_contract=self.settings.runtime_tool_contract)
        policy = PlanPolicyConfig() if legacy else PlanPolicyConfig(revision=self.settings.policy_revision,
            tool_contract=self.settings.runtime_tool_contract, review_ttl_seconds=86400)
        with self.engine.begin() as conn:
            for statement in ('CREATE TABLE af_bootstrap (id TEXT PRIMARY KEY, mode TEXT)',
                'CREATE TABLE af_material_governance_current (id TEXT PRIMARY KEY, revision TEXT)',
                'CREATE TABLE af_material_governance_configs (revision TEXT PRIMARY KEY, hash TEXT, body TEXT)',
                'CREATE TABLE af_plan_policy_state (id TEXT PRIMARY KEY, revision TEXT)',
                'CREATE TABLE af_plan_policy_configs (revision TEXT PRIMARY KEY, policy_hash TEXT, body TEXT)'):
                conn.execute(text(statement))
            conn.execute(text("INSERT INTO af_bootstrap VALUES ('mode','demo')"))
            for state, table, column, config in (
                ('af_material_governance_current', 'af_material_governance_configs', 'hash', material),
                ('af_plan_policy_state', 'af_plan_policy_configs', 'policy_hash', policy)):
                conn.execute(text(f"INSERT INTO {state} VALUES ('current',:revision)"), {'revision': config.revision})
                conn.execute(text(f'INSERT INTO {table} (revision,{column},body) VALUES (:revision,:hash,:body)'),
                    {'revision': config.revision, 'hash': config.fingerprint, 'body': json.dumps(asdict(config))})

    def preflight(self):
        statements = []
        def only_reads(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
            self.assertIn(statement.lstrip().split()[0].upper(), {'SELECT', 'PRAGMA'})
        event.listen(self.engine, 'before_cursor_execute', only_reads)
        try:
            report = database_preflight(self.engine, self.settings)
        finally:
            event.remove(self.engine, 'before_cursor_execute', only_reads)
        self.assertTrue(statements)
        return report, {row['field']: row for row in report['checks']}

    def test_empty_database_is_not_initialized_without_creating_tables(self):
        report, rows = self.preflight()
        self.assertEqual(report['status'], 'NOT_CHECKED')
        self.assertEqual(rows['bootstrap.mode']['code'], 'NOT_INITIALIZED')
        self.assertEqual(rows['material.current']['code'], 'NOT_INITIALIZED')
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM sqlite_master WHERE type='table'")).scalar(), 0)

    def test_canonical_database_passes_without_writes(self):
        self.seed()
        report, _ = self.preflight()
        self.assertEqual(report['status'], 'PASS', report)
        public = json.dumps(report)
        self.assertNotIn(self.settings.policy_revision, public)
        self.assertNotIn('sqlite', public)

    def test_legacy_revisions_both_reported_without_rebinding(self):
        self.seed(legacy=True)
        report, rows = self.preflight()
        self.assertEqual(report['status'], 'BLOCKED')
        for field in ('material.current', 'plan.current'):
            self.assertEqual(rows[field]['code'], 'CURRENT_REVISION_MISMATCH')
        self.assertEqual(rows['material.currentConfig']['status'], 'PASS')
        self.assertEqual(rows['plan.currentConfig']['status'], 'PASS')
        self.assertEqual(rows['plan.expectedConfig']['code'], 'NOT_REGISTERED')
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM af_plan_policy_configs')).scalar(), 1)

    def test_mode_and_both_hash_mismatches_accumulate(self):
        self.seed()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE af_bootstrap SET mode='production'"))
            conn.execute(text("UPDATE af_material_governance_configs SET hash='private-bad-hash'"))
            conn.execute(text("UPDATE af_plan_policy_configs SET policy_hash='private-bad-hash'"))
        report, rows = self.preflight()
        for field in ('bootstrap.mode', 'material.currentConfig', 'plan.currentConfig'):
            self.assertEqual(rows[field]['status'], 'BLOCKED')
        self.assertNotIn('private-bad-hash', json.dumps(report))

    def test_same_revision_valid_but_different_body_cannot_rebind(self):
        self.seed()
        changed = PlanPolicyConfig(revision=self.settings.policy_revision, tool_contract=self.settings.runtime_tool_contract, review_ttl_seconds=3600)
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE af_plan_policy_configs SET body=:body,policy_hash=:hash'),
                {'body': json.dumps(asdict(changed)), 'hash': changed.fingerprint})
        _, rows = self.preflight()
        self.assertEqual(rows['plan.currentConfig']['status'], 'PASS')
        self.assertEqual(rows['plan.expectedConfig']['status'], 'BLOCKED')

    def test_invalid_policy_body_and_orphan_registration_fail_closed(self):
        self.seed()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE af_plan_policy_configs SET body=:body"), {'body': '{"name":"private-bad-enum"}'})
            conn.execute(text('DELETE FROM af_material_governance_configs'))
        report, rows = self.preflight()
        self.assertEqual(rows['plan.policyEnum']['status'], 'BLOCKED')
        self.assertEqual(rows['material.currentConfig']['code'], 'CURRENT_CONFIG_MISSING')
        self.assertNotIn('private-bad-enum', json.dumps(report))

    def test_missing_and_extra_current_rows_are_distinct(self):
        self.seed()
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM af_plan_policy_state'))
            conn.execute(text("INSERT INTO af_material_governance_current VALUES ('unexpected','private-revision')"))
        _, rows = self.preflight()
        self.assertEqual(rows['plan.current']['code'], 'NOT_INITIALIZED')
        self.assertEqual(rows['material.current']['code'], 'CURRENT_ROW_INVALID')

    def test_postgres_transaction_declares_read_only_before_inspection(self):
        connection = Mock()
        connection.begin.return_value = nullcontext()
        engine = Mock()
        engine.dialect.name = 'postgresql'
        engine.connect.return_value = nullcontext(connection)
        inspector = Mock()
        inspector.has_table.return_value = False
        def inspected(actual):
            self.assertIs(actual, connection)
            self.assertEqual(str(connection.execute.call_args.args[0]),
                             'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            return inspector
        with patch('agent_factory.research_bootstrap_database_preflight.inspect', side_effect=inspected):
            report = database_preflight(engine, self.settings)
        self.assertEqual(report['status'], 'NOT_CHECKED')
        connection.execute.assert_called_once()

    def test_invalid_settings_do_not_hide_persisted_mode(self):
        self.seed()
        self.settings.temporary_policy = 'private-unsupported'
        report, rows = self.preflight()
        self.assertEqual(rows['settings.plan']['status'], 'BLOCKED')
        self.assertEqual(rows['bootstrap.mode']['status'], 'PASS')
        self.assertNotIn('private-unsupported', json.dumps(report))

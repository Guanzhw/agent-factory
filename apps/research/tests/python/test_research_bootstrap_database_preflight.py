"""Read-only SQLite probes of existing execution records and database mode."""
import json
from types import SimpleNamespace
import unittest

from sqlalchemy import create_engine, event, inspect, text
from agent_factory_research.research_bootstrap_database_preflight import database_preflight


def settings():
    return SimpleNamespace(demo=True)


def seed_database(engine):
    statements = (
        'CREATE TABLE af_bootstrap (id TEXT PRIMARY KEY, mode TEXT)',
        'CREATE TABLE af_plans (id TEXT, owner_id TEXT, body TEXT, hash TEXT)',
        'CREATE TABLE af_tasks (id TEXT, owner_id TEXT, plan_id TEXT, request_id TEXT, fingerprint TEXT, run_id TEXT, admission TEXT, terminal BOOLEAN, cancel_requested BOOLEAN, body TEXT)',
        'CREATE TABLE af_effects (effect_key TEXT, task_id TEXT, run_id TEXT, fingerprint TEXT, status TEXT, result TEXT)',
        'CREATE TABLE af_artifacts (id TEXT, task_id TEXT, body TEXT, content BYTEA)',
        'CREATE TABLE af_resources (id TEXT, owner_id TEXT, body TEXT)',
        'CREATE TABLE af_leases (id TEXT, owner_id TEXT, target_id TEXT, request_id TEXT, fingerprint TEXT, state TEXT, body TEXT)',
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO af_bootstrap VALUES ('mode','demo')"))


class DatabasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        self.settings = settings()

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

    def test_empty_database_stays_uninitialized(self):
        report, rows = self.preflight()
        self.assertEqual(report['status'], 'NOT_CHECKED')
        self.assertEqual(rows['bootstrap.mode']['code'], 'NOT_INITIALIZED')
        self.assertEqual(inspect(self.engine).get_table_names(), [])

    def test_execution_schema_passes_without_policy_registration(self):
        seed_database(self.engine)
        report, _ = self.preflight()
        self.assertEqual(report['status'], 'PASS', report)
        self.assertIs(report['executionVerified'], False)
        self.assertNotIn('plan.current', json.dumps(report))

    def test_historical_review_rows_remain_readable_and_do_not_gate_start(self):
        seed_database(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text('CREATE TABLE af_plan_policy_configs (revision TEXT, policy_hash TEXT, body TEXT)'))
            conn.execute(text("INSERT INTO af_plan_policy_configs VALUES ('legacy', 'historical', 'unparsed review body')"))
        report, _ = self.preflight()
        self.assertEqual(report['status'], 'PASS', report)
        with self.engine.connect() as conn:
            self.assertEqual(tuple(conn.execute(text('SELECT * FROM af_plan_policy_configs')).one()),
                             ('legacy', 'historical', 'unparsed review body'))

    def test_mode_mismatch_blocks_without_exposing_row(self):
        seed_database(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE af_bootstrap SET mode='private-mode'"))
        report, rows = self.preflight()
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertEqual(rows['bootstrap.mode']['code'], 'MODE_MISMATCH')
        self.assertNotIn('private-mode', json.dumps(report))

    def test_missing_execution_table_is_reported_without_repair(self):
        seed_database(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text('DROP TABLE af_artifacts'))
        report, rows = self.preflight()
        self.assertEqual(report['status'], 'NOT_CHECKED')
        self.assertEqual(rows['schema.af_artifacts']['code'], 'NOT_INITIALIZED')
        self.assertNotIn('af_artifacts', inspect(self.engine).get_table_names())

    def test_incomplete_execution_table_blocks(self):
        seed_database(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text('DROP TABLE af_tasks'))
            conn.execute(text('CREATE TABLE af_tasks (id TEXT)'))
        report, rows = self.preflight()
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertEqual(rows['schema.af_tasks']['code'], 'REQUIRED_COLUMNS_MISSING')

    def test_missing_mode_row_requires_initialization(self):
        seed_database(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM af_bootstrap'))
        report, rows = self.preflight()
        self.assertEqual(report['status'], 'NOT_CHECKED')
        self.assertEqual(rows['bootstrap.mode']['code'], 'NOT_INITIALIZED')

    def test_invalid_demo_mode_is_reported(self):
        seed_database(self.engine)
        self.settings.demo = 'private-mode'
        report, rows = self.preflight()
        self.assertEqual(rows['settings.mode']['code'], 'MODE_INVALID')
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertNotIn('private-mode', json.dumps(report))

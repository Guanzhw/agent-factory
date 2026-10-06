"""Conditional real-PG read-only diagnostics, confined to one owned schema."""
from dataclasses import asdict
import json
import os
import re
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from agent_factory.material_governance import GovernanceConfig
from agent_factory.plan_policy import PlanPolicyConfig
from agent_factory.research_bootstrap_database_preflight import database_preflight
import test_research_bootstrap_database_preflight as fixture  # pyright: ignore[reportMissingImports]

_TABLES = ('af_bootstrap', 'af_material_governance_current', 'af_material_governance_configs',
           'af_plan_policy_state', 'af_plan_policy_configs')


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires explicit loopback PostgreSQL fixture')
class DatabasePreflightPostgresTests(unittest.TestCase):
    def setUp(self):
        url = make_url(os.environ['FACTORY_TEST_DATABASE_URL'])
        if url.host not in {'127.0.0.1', 'localhost', '::1'} or url.get_backend_name() != 'postgresql':
            raise ValueError('POSTGRES_FIXTURE_LOOPBACK_REQUIRED')
        self.schema = 'af_preflight_' + uuid4().hex
        self.admin = create_engine(url)
        self.addCleanup(self.admin.dispose)
        self.created = False
        self.addCleanup(self.drop_owned_schema)
        with self.admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.created = True
        # No public fallback: all unqualified production reads resolve only in
        # this generated schema. PostgreSQL still resolves its own pg_catalog.
        self.engine = create_engine(url, connect_args={'options': '-c search_path=' + self.schema})
        self.addCleanup(self.engine.dispose)
        self.settings = fixture.settings()
        with self.engine.begin() as conn:
            for statement in ('CREATE TABLE af_bootstrap (id TEXT PRIMARY KEY, mode TEXT)',
                'CREATE TABLE af_material_governance_current (id TEXT PRIMARY KEY, revision TEXT)',
                'CREATE TABLE af_material_governance_configs (revision TEXT PRIMARY KEY, hash TEXT, body JSONB)',
                'CREATE TABLE af_plan_policy_state (id TEXT PRIMARY KEY, revision TEXT)',
                'CREATE TABLE af_plan_policy_configs (revision TEXT PRIMARY KEY, policy_hash TEXT, body JSONB)'):
                conn.execute(text(statement))
            conn.execute(text("INSERT INTO af_bootstrap VALUES ('mode','demo')"))
        self.register(GovernanceConfig(revision=self.settings.material_policy_revision,
            tool_contract=self.settings.runtime_tool_contract), 'material')
        self.register(PlanPolicyConfig(revision=self.settings.policy_revision,
            tool_contract=self.settings.runtime_tool_contract, review_ttl_seconds=86400), 'plan')

    def drop_owned_schema(self):
        if not self.created:
            return
        if not re.fullmatch('af_preflight_[a-f0-9]{32}', self.schema):
            raise ValueError('OWNED_SCHEMA_REQUIRED')
        with self.admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    def register(self, config, kind):
        state, table, column = (
            ('af_material_governance_current', 'af_material_governance_configs', 'hash') if kind == 'material'
            else ('af_plan_policy_state', 'af_plan_policy_configs', 'policy_hash'))
        with self.engine.begin() as conn:
            conn.execute(text(f'INSERT INTO {table} (revision,{column},body) VALUES (:revision,:hash,CAST(:body AS JSONB))'),
                {'revision': config.revision, 'hash': config.fingerprint, 'body': json.dumps(asdict(config))})
            conn.execute(text(f"INSERT INTO {state} VALUES ('current',:revision) ON CONFLICT (id) DO UPDATE SET revision=EXCLUDED.revision"),
                         {'revision': config.revision})

    def rows(self):
        with self.engine.connect() as conn:
            return {table: [dict(row) for row in conn.execute(text(f'SELECT * FROM {table} ORDER BY 1')).mappings()]
                    for table in _TABLES}

    def probe(self):
        observations, statements = [], []
        def before(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
            self.assertIn(statement.lstrip().split()[0].upper(), {'SELECT', 'SET'})
        def after(conn, _cursor, statement, _params, _context, _many):
            if statement == "SET LOCAL lock_timeout = '1000ms'":
                # Direct DBAPI SHOW avoids recursive SQLAlchemy event hooks and
                # observes the exact same live transaction as the preflight.
                cursor = conn.connection.cursor()
                try:
                    values = {}
                    for name in ('transaction_read_only', 'transaction_isolation', 'statement_timeout', 'lock_timeout'):
                        cursor.execute('SHOW ' + name)
                        values[name] = cursor.fetchone()[0]
                    observations.append(values)
                finally:
                    cursor.close()
        event.listen(self.engine, 'before_cursor_execute', before)
        event.listen(self.engine, 'after_cursor_execute', after)
        try:
            report = database_preflight(self.engine, self.settings)
        finally:
            event.remove(self.engine, 'before_cursor_execute', before)
            event.remove(self.engine, 'after_cursor_execute', after)
        self.assertEqual(observations, [{'transaction_read_only': 'on', 'transaction_isolation': 'repeatable read',
            'statement_timeout': '5s', 'lock_timeout': '1s'}])
        self.assertTrue(any('octet_length(CAST(body AS TEXT))<=65536' in statement for statement in statements))
        return report

    def test_jsonb_current_compatibility_and_legacy_mismatches_are_read_only(self):
        before = self.rows()
        report = self.probe()
        self.assertEqual(report['status'], 'PASS', report)
        self.assertIs(report['executionVerified'], False)
        self.assertEqual(self.rows(), before)

        self.register(GovernanceConfig(), 'material')
        self.register(PlanPolicyConfig(), 'plan')
        before = self.rows()
        report = self.probe()
        rows = {row['field']: row for row in report['checks']}
        self.assertEqual(report['status'], 'BLOCKED')
        for kind in ('material', 'plan'):
            self.assertEqual(rows[kind + '.current']['code'], 'CURRENT_REVISION_MISMATCH')
            self.assertEqual(rows[kind + '.currentConfig']['status'], 'PASS')
        self.assertEqual(self.rows(), before)

        with self.engine.begin() as conn:
            conn.execute(text('UPDATE af_plan_policy_configs SET body=CAST(:body AS JSONB) WHERE revision=:revision'),
                {'body': json.dumps({'oversized': 'x' * 65536}), 'revision': self.settings.policy_revision})
        before = self.rows()
        report = self.probe()
        rows = {row['field']: row for row in report['checks']}
        self.assertEqual(rows['plan.expectedConfig']['code'], 'CONFIG_BODY_INVALID')
        self.assertEqual(self.rows(), before)

"""Real PostgreSQL schema inspection in a generated, isolated namespace."""
import json
import os
import re
import tempfile
from pathlib import Path
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from agent_factory_research.config import ResearchSettings as Settings
from agent_factory.store import Store
from agent_factory_research.research_bootstrap_database_preflight import database_preflight


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
        url = url.update_query_dict({'options': '-c search_path=' + self.schema})
        self.engine = create_engine(url)
        self.addCleanup(self.engine.dispose)
        root = tempfile.TemporaryDirectory(); self.addCleanup(root.cleanup)
        self.settings = Settings(db_url=url.render_as_string(hide_password=False), workspace=Path(root.name))
        store = Store(self.settings.db_url, self.settings)
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.dispose_root_locks)

    def drop_owned_schema(self):
        if not self.created:
            return
        if not re.fullmatch('af_preflight_[a-f0-9]{32}', self.schema):
            raise ValueError('OWNED_SCHEMA_REQUIRED')
        with self.admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    def probe(self):
        observations = []
        def before(_conn, _cursor, statement, _params, _context, _many):
            self.assertIn(statement.lstrip().split()[0].upper(), {'SELECT', 'SET'})
        def after(conn, _cursor, statement, _params, _context, _many):
            if statement == "SET LOCAL lock_timeout = '1000ms'":
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
        return report

    def test_real_store_schema_passes_without_policy_tables(self):
        report = self.probe()
        self.assertEqual(report['status'], 'PASS', report)
        self.assertIs(report['executionVerified'], False)

    def test_historical_policy_body_is_preserved_without_becoming_a_gate(self):
        with self.engine.begin() as conn:
            conn.execute(text('CREATE TABLE af_plan_policy_configs (body JSONB)'))
            conn.execute(text('INSERT INTO af_plan_policy_configs VALUES (CAST(:body AS JSONB))'),
                         {'body': json.dumps({'name': 'admin-review', 'review_ttl_seconds': 1})})
        self.assertEqual(self.probe()['status'], 'PASS')
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT body FROM af_plan_policy_configs')).scalar(),
                             {'name': 'admin-review', 'review_ttl_seconds': 1})

    def test_missing_search_path_namespace_blocks_without_public_fallback(self):
        url = make_url(self.settings.db_url).update_query_dict({'options': '-c search_path=af_missing_' + uuid4().hex})
        engine = create_engine(url)
        try:
            report = database_preflight(engine, self.settings)
        finally:
            engine.dispose()
        self.assertEqual(report['status'], 'BLOCKED')
        rows = {row['field']: row for row in report['checks']}
        self.assertEqual(rows['namespace']['code'], 'NAMESPACE_UNAVAILABLE')
        self.assertEqual(rows['schema.af_tasks']['code'], 'NOT_INITIALIZED')

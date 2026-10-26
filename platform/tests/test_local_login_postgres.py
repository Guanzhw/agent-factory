"""Local password/native-member HTTP boundary on disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from agno.db.postgres import PostgresDb
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from agent_factory.auth import AuthService
from agent_factory.browser_auth import BrowserSessionService, SESSION_COOKIE
from agent_factory.config import Settings
from agent_factory.local_login import LocalPasswords, main
from agent_factory.main import create_app
from pg_fixture import IsolatedPostgres

ORIGIN = 'https://testserver'


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class LocalLoginPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        workspace = TemporaryDirectory(prefix='factory-local-login-')
        self.addCleanup(workspace.cleanup)
        self.settings = Settings(db_url=database.url, workspace=Path(workspace.name),
            jwt_key=secrets.token_urlsafe(40), local_login_origin=ORIGIN, max_workers=1,
            storage_task_reserve_bytes=8 * 1024 * 1024)
        self.native = PostgresDb(db_url=database.url, id='factory-native-postgres')
        self.addCleanup(self.native.db_engine.dispose)
        self.auth = AuthService(self.settings, self.native)
        self.passwords = LocalPasswords(self.native.db_engine, self.auth.directory)
        self.password = secrets.token_urlsafe(24)
        for owner in ('alice', 'bob'):
            self.passwords.create(owner, self.password)

    def client(self):
        app = create_app(self.settings)
        state = app.app.state.factory
        self.addCleanup(state['store'].engine.dispose)
        self.addCleanup(state['store'].native_db.db_engine.dispose)
        client = TestClient(app, base_url=ORIGIN, follow_redirects=False).__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client, state

    def login(self, client, owner='alice', password=None):
        return client.post('/api/factory/auth/local-login', json={'username': owner,
            'password': self.password if password is None else password}, headers={'Origin': ORIGIN})

    def test_new_account_concurrency_and_interrupted_hash_write_never_adopt_existing_owner(self):
        def create():
            try:
                self.passwords.create('concurrent', self.password)
                return 'created'
            except ValueError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: create(), range(2))), ['conflict', 'created'])

        def fail_insert(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith('INSERT INTO af_local_passwords'):
                raise RuntimeError('Interrupted before local credential commit')
        event.listen(self.native.db_engine, 'before_cursor_execute', fail_insert)
        try:
            with self.assertRaises(RuntimeError):
                self.passwords.create('interrupted', self.password)
        finally:
            event.remove(self.native.db_engine, 'before_cursor_execute', fail_insert)
        self.assertIsNotNone(self.auth.directory.get('interrupted'))
        with self.assertRaises(ValueError):
            self.passwords.create('interrupted', self.password)
        client, state = self.client()
        self.assertEqual(self.login(client, 'interrupted').status_code, 401)
        self.assertEqual(state['store'].sql("SELECT id FROM af_browser_auth WHERE kind='session'"), [])

    def test_real_member_sessions_failure_logout_restart_and_owner_artifact_isolation(self):
        client, state = self.client()
        store = state['store']
        for owner, password in [('alice', secrets.token_urlsafe(24)), ('missing', self.password)]:
            self.assertEqual(self.login(client, owner, password).status_code, 401)
        self.assertEqual(store.sql("SELECT id FROM af_browser_auth WHERE kind='session'"), [])
        self.assertEqual(self.login(client).status_code, 200)
        self.assertEqual(client.get('/api/factory/session').json()['id'], 'alice')
        token = client.cookies.get(SESSION_COOKIE)
        service = BrowserSessionService(store, self.auth, local_login_origin=ORIGIN)
        self.assertEqual(service.session(token)['owner'], 'alice')
        plan = store.save_plan({'id': str(uuid4()), 'ownerId': 'alice', 'syntheticFixture': True})
        task, _ = store.reserve_task(plan, 'local-login-' + str(uuid4()))
        artifact = store.artifact_write(task['id'], 'synthetic.txt', b'Synthetic private evidence', 'text/plain')
        path = f"/api/factory/jobs/{task['id']}/artifacts/{artifact['id']}"
        self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(client.post('/api/factory/auth/logout', headers={'Origin': ORIGIN}).status_code, 403)
        csrf = client.get('/api/factory/auth/session').json()['csrfToken']
        self.assertEqual(client.post('/api/factory/auth/logout',
            headers={'Origin': ORIGIN, 'X-Factory-CSRF': csrf}).status_code, 204)
        client.cookies.set(SESSION_COOKIE, token)
        self.assertFalse(client.get('/api/factory/auth/session').json()['authenticated'])
        client.cookies.clear()
        self.assertEqual(self.login(client, 'bob').status_code, 200)
        self.assertEqual(client.get(path).status_code, 404)
        self.assertEqual(client.get('/api/factory/session', headers={'X-Factory-Expected-Owner': 'alice'}).status_code, 403)
        self.auth.directory.set_disabled('bob', True)
        self.assertEqual(client.get('/api/factory/session').status_code, 403)
        client.cookies.clear()
        self.assertEqual(self.login(client, 'bob').status_code, 401)

    def test_cli_rejects_retained_demo_database_before_native_or_credential_writes(self):
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database:
            engine = create_engine(database.url)
            try:
                with engine.begin() as conn:
                    conn.execute(text('CREATE TABLE af_bootstrap(id TEXT PRIMARY KEY,mode TEXT NOT NULL)'))
                    conn.execute(text("INSERT INTO af_bootstrap VALUES('mode','demo')"))
                def snapshot():
                    with engine.connect() as conn:
                        tables = conn.execute(text("SELECT table_schema,table_name FROM information_schema.tables WHERE table_schema IN ('public','ai') ORDER BY 1,2")).all()
                        return tables, conn.execute(text('SELECT * FROM af_bootstrap')).all()
                before = snapshot()
                with patch.dict(os.environ, {'FACTORY_DATABASE_URL': database.url,
                        'FACTORY_JWT_KEY': self.settings.jwt_key}), patch('sys.stdin.isatty', return_value=True), \
                        patch('getpass.getpass', return_value=self.password), redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(main(['new-member']), 1)
                self.assertNotIn(self.password, error.getvalue())
                self.assertEqual(snapshot(), before)
            finally:
                engine.dispose()

    def test_cli_owner_collision_preserves_native_metadata_and_roles(self):
        self.auth.directory.upsert('external-owner', metadata={'retained': 'external identity'})
        before = self.auth.directory.get('external-owner')
        with patch.dict(os.environ, {'FACTORY_DATABASE_URL': self.settings.db_url,
                'FACTORY_JWT_KEY': self.settings.jwt_key}), patch('sys.stdin.isatty', return_value=True), \
                patch('getpass.getpass', return_value=self.password), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['external-owner']), 1)
        self.assertEqual(self.auth.directory.get('external-owner'), before)
        self.assertEqual(self.auth.account_roles.roles_of('external-owner'), [])


if __name__ == '__main__':
    unittest.main()

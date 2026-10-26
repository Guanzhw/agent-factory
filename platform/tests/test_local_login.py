"""Local-password boundary against real native users and disposable SQLite."""
import asyncio
import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.db.sqlite import SqliteDb
from fastapi import HTTPException
import httpx
from sqlalchemy import create_engine, text
from starlette.responses import JSONResponse

from agent_factory.auth import AuthService
from agent_factory.browser_auth import BrowserAuthBridge, BrowserSessionService, SESSION_COOKIE
from agent_factory.config import Settings
from agent_factory.local_login import LocalPasswords
from browser_identity_fixture import BrowserIdentityFixture

ORIGIN = 'https://factory.example.test'


class LocalLoginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.native = SqliteDb(db_file=str(Path(temporary.name) / 'native.sqlite'))
        self.addCleanup(self.native.db_engine.dispose)
        self.auth = AuthService(SimpleNamespace(jwt_key=secrets.token_urlsafe(40)), self.native)
        self.engine = create_engine('sqlite:///' + str(Path(temporary.name) / 'credentials.sqlite'))
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(text('CREATE TABLE af_browser_auth(id TEXT PRIMARY KEY,kind TEXT,body TEXT)'))
        self.passwords = LocalPasswords(self.engine, self.auth.directory)
        self.password = secrets.token_urlsafe(24)
        self.passwords.create('alice', self.password)
        self.passwords.create('bob', self.password)
        self.store = SimpleNamespace(engine=self.engine)
        self.service = BrowserSessionService(self.store, self.auth, local_login_origin=ORIGIN)

        async def protected(scope, receive, send):
            import jwt
            headers = dict(scope['headers'])
            token = headers.get(b'authorization', b'').decode().removeprefix('Bearer ')
            owner = jwt.decode(token, self.auth._key, algorithms=['HS256'], audience=self.auth.audience)['sub']
            expected = headers.get(b'x-factory-expected-owner', owner.encode()).decode()
            await JSONResponse({'id': owner}, status_code=200 if expected == owner else 403)(scope, receive, send)

        self.protected = protected
        self.bridge = BrowserAuthBridge(protected, self.service)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.bridge), base_url=ORIGIN)
        self.addAsyncCleanup(self.client.aclose)

    async def login(self, owner='alice', **changes):
        return await self.client.post('/api/factory/auth/local-login',
            json={'username': owner, 'password': self.password, **changes}, headers={'Origin': ORIGIN})

    async def test_salted_storage_collision_and_failed_creation_do_not_adopt_identity(self):
        with self.engine.connect() as conn:
            hashes = conn.execute(text('SELECT password_hash FROM af_local_passwords ORDER BY owner')).scalars().all()
        self.assertEqual(len(hashes), 2)
        self.assertTrue(all(value.startswith('$argon2id$') and self.password not in value for value in hashes))
        self.assertTrue(hashes[0] != hashes[1])
        self.assertEqual(self.auth.identity('alice')['role'], 'user')
        self.assertNotIn(self.password, json.dumps(self.auth.directory.get('alice')))
        self.auth.directory.upsert('existing-oidc')
        for owner in ('alice', 'existing-oidc'):
            with self.assertRaises(ValueError):
                self.passwords.create(owner, secrets.token_urlsafe(24))
        await asyncio.to_thread(self.passwords.verify, 'alice', self.password)
        with patch.object(self.auth.directory, 'upsert', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                self.passwords.create('interrupted', self.password)
        with self.assertRaises(HTTPException):
            self.passwords.verify('interrupted', self.password)

    async def test_bad_password_unknown_disabled_and_origin_never_issue_sessions(self):
        self.auth.directory.set_disabled('bob', True)
        for owner, password in [('alice', secrets.token_urlsafe(24)), ('unknown', self.password), ('bob', self.password)]:
            response = await self.login(owner, password=password)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('set-cookie', response.headers)
        response = await self.client.post('/api/factory/auth/local-login',
            json={'username': 'alice', 'password': self.password}, headers={'Origin': 'https://other.example.test'})
        self.assertEqual(response.status_code, 403)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM af_browser_auth WHERE kind='session'")).scalar_one(), 0)

    async def test_session_restart_csrf_logout_and_current_member(self):
        config = (await self.client.get('/api/factory/auth/config')).json()
        self.assertTrue(config['enabled'] and config['localLoginEnabled'])
        self.assertFalse(config['oidcEnabled'])
        self.assertEqual((await self.login()).status_code, 200)
        cookie = self.client.cookies.get(SESSION_COOKIE)
        self.assertTrue(cookie)
        session = (await self.client.get('/api/factory/auth/session')).json()
        self.assertTrue(session['authenticated'])
        response = await self.client.get('/protected')
        self.assertEqual(response.json(), {'id': 'alice'})
        self.assertEqual((await self.client.post('/protected', headers={'Origin': ORIGIN})).status_code, 403)
        self.assertEqual((await self.client.post('/protected', headers={'Origin': ORIGIN, 'X-Factory-CSRF': session['csrfToken']})).status_code, 200)
        reopened = BrowserSessionService(self.store, self.auth, local_login_origin=ORIGIN)
        self.assertEqual(reopened.session(cookie)['owner'], 'alice')
        self.assertEqual((await self.client.post('/api/factory/auth/logout',
            headers={'Origin': ORIGIN, 'X-Factory-CSRF': session['csrfToken']})).status_code, 204)
        with self.assertRaises(HTTPException):
            reopened.session(cookie)
        self.assertEqual((await self.login()).status_code, 200)
        self.auth.directory.set_disabled('alice', True)
        self.assertFalse((await self.client.get('/api/factory/auth/session')).json()['authenticated'])

    async def test_account_switch_revokes_previous_cookie_and_never_accepts_public_native_jwt(self):
        self.assertEqual((await self.login()).status_code, 200)
        previous = self.client.cookies.get(SESSION_COOKIE)
        self.assertEqual((await self.login('bob')).status_code, 200)
        self.assertEqual((await self.client.get('/protected')).json(), {'id': 'bob'})
        self.assertEqual((await self.client.get('/protected', headers={'X-Factory-Expected-Owner': 'alice'})).status_code, 403)
        with self.assertRaises(HTTPException):
            self.service.session(previous)
        self.client.cookies.clear()
        token = self.auth._issue_native_token('alice')
        self.assertEqual((await self.client.get('/protected', headers={'Authorization': 'Bearer ' + token})).status_code, 401)

    async def test_explicit_login_modes_and_origin_configuration(self):
        settings = {'db_url': 'postgresql://unused', 'jwt_key': self.auth._key}
        for origin in ('http://127.0.0.1:3100', ORIGIN + '/', ORIGIN + '?query', 'https://user@host'):
            with self.assertRaises(ValueError):
                Settings(**settings, local_login_origin=origin)
        oidc = BrowserIdentityFixture(redirect_uri=ORIGIN + '/api/factory/auth/callback').config()
        with self.assertRaises(ValueError):
            Settings(**settings, browser_oidc=oidc, local_login_origin='https://different.example.test')
        Settings(**settings, browser_oidc=oidc, local_login_origin=ORIGIN)
        service = BrowserSessionService(self.store, self.auth, oidc, local_login_origin=ORIGIN)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=BrowserAuthBridge(self.protected, service)), base_url=ORIGIN) as client:
            config = (await client.get('/api/factory/auth/config')).json()
            self.assertTrue(config['oidcEnabled'] and config['localLoginEnabled'])
        self.assertEqual((await self.client.post('/api/factory/auth/login', json={}, headers={'Origin': ORIGIN})).status_code, 405)
        self.assertEqual((await self.login()).status_code, 200)
        with self.assertRaises(HTTPException):
            service.session(self.client.cookies.get(SESSION_COOKIE))


if __name__ == '__main__':
    unittest.main()

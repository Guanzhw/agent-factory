"""Real create_app/native PostgreSQL with test-only external OIDC protocol fixture.

HTTPS ASGI scheme is simulated; these tests do not prove deployed TLS. No live
IdP/provider, host changes or alternate browser session implementation. A local
synthetic HTML document supplies the static route fixture; actual React navigation
is verified separately by the real HTTPS browser acceptance.
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlsplit
from typing import cast

from starlette.types import ASGIApp

from fastapi.testclient import TestClient

from agent_factory.browser_auth import SESSION_COOKIE
from fixture_settings import Settings
from browser_identity_fixture import BrowserIdentityFixture
from agent_factory.browser_oidc import BrowserCodeExchanger
from fixture_auth import initialize_members
from agent_factory.main import create_app
from pg_fixture import IsolatedPostgres  # pyright: ignore[reportMissingImports]

ORIGIN = "https://127.0.0.1:3443"


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated loopback PostgreSQL")
class DevelopmentLoginPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory(prefix="development-login-postgres-")
        self.addCleanup(directory.cleanup)
        self.idp = BrowserIdentityFixture(redirect_uri=ORIGIN + '/api/factory/auth/callback')
        config = replace(self.idp.config(), subject_owners={
            (self.idp.issuer, 'subject-' + owner): owner for owner in ('alice', 'bob', 'manager', 'manager2')})
        settings = Settings(db_url=database.url, workspace=Path(directory.name), max_workers=1,
            browser_oidc=config,
            storage_task_reserve_bytes=8*1024*1024)
        # Backend CI intentionally has no frontend build. Supply a disposable
        # document through the real FileResponse route instead of depending on
        # an unrelated local dist/ directory or mocking an HTTP success.
        static_root = Path(directory.name) / "web-fixture"
        (static_root / "dist").mkdir(parents=True)
        (static_root / "dist" / "index.html").write_text("<!doctype html><title>Synthetic external OIDC login fixture</title>", encoding="utf-8")
        settings.web_directory = static_root / "dist"
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        initialize_members(self.auth)
        self.auth.directory.upsert('manager2', name='Second manager')
        self.auth.account_roles.assign('manager2', 'factory-manager')
        self.state['browser_auth'].exchanger = BrowserCodeExchanger(config, transport=self.idp.transport)
        self.identity_client = TestClient(self.idp.app, base_url=self.idp.issuer, follow_redirects=False)
        self.addCleanup(self.identity_client.close)
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(cast(ASGIApp, self.app), base_url=ORIGIN, follow_redirects=False).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def select(self, persona, client=None):
        client = client or self.client
        started = client.post("/api/factory/auth/login", json={}, headers={"Origin": ORIGIN})
        self.assertEqual(started.status_code, 200, started.text)
        if persona == 'cancel':
            query = parse_qs(urlsplit(started.json()['authorizationUrl']).query)
            return client.get('/api/factory/auth/callback?' + urlencode({'state': query['state'][0], 'error': 'access_denied'}))
        self.idp.subject = 'subject-' + persona
        selected = self.identity_client.get(started.json()['authorizationUrl'])
        self.assertEqual(selected.status_code, 302, selected.text)
        return selected

    def login(self, persona, client=None):
        client = client or self.client
        callback = self.select(persona, client)
        finished = client.get(callback.headers["location"])
        self.assertEqual(finished.status_code, 303, finished.text)
        self.assertEqual(finished.headers["location"], "/")
        session = client.get("/api/factory/auth/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertTrue(session.json()["authenticated"])
        identity = client.get("/api/factory/session")
        self.assertEqual(identity.status_code, 200, identity.text)
        self.assertEqual(identity.json()["id"], persona)
        return session.json()["csrfToken"]

    def test_cancel_then_login_repeated_navigation_csrf_logout_and_new_login(self):
        config = self.client.get("/api/factory/auth/config")
        self.assertEqual(config.status_code, 200)
        self.assertTrue(config.json()["enabled"])
        cancelled = self.select("cancel")
        self.assertIn("signin_failed", cancelled.headers["location"])
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.assertEqual(self.store.sql("SELECT id FROM af_browser_auth WHERE kind='session'"), [])
        csrf = self.login("alice")
        opaque = self.client.cookies.get(SESSION_COOKIE)
        for _ in range(3):
            document = self.client.get("/")
            self.assertEqual(document.status_code, 200)
            self.assertIn("Synthetic external OIDC login fixture", document.text)
            self.assertEqual(self.client.get("/api/factory/session").json()["id"], "alice")
            self.assertEqual(self.client.cookies.get(SESSION_COOKIE), opaque)
        self.assertEqual(len(self.store.sql("SELECT id FROM af_browser_auth WHERE kind='session'")), 1)
        denied = self.client.post("/api/factory/auth/logout", headers={"Origin": ORIGIN})
        self.assertEqual(denied.status_code, 403)
        signed_out = self.client.post("/api/factory/auth/logout", headers={"Origin": ORIGIN, "X-Factory-CSRF": csrf})
        self.assertEqual(signed_out.status_code, 204, signed_out.text)
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.assertEqual(self.client.get("/api/factory/session").status_code, 401)
        self.login("bob")
        rows = self.store.sql("SELECT body FROM af_browser_auth")
        self.assertNotIn(opaque, json.dumps(rows, default=str))
        self.assertEqual(len(self.store.sql("SELECT id FROM af_browser_auth WHERE kind='session'")), 2)

    def test_current_revocation_disablement_owner_isolation_and_distinct_managers(self):
        self.login("alice")
        plan = self.store.save_plan({"id": str(uuid4()), "ownerId": "alice", "syntheticFixture": True})
        task, _ = self.store.reserve_task(plan, "development-login-" + str(uuid4()))
        artifact = self.store.artifact_write(task["id"], "synthetic.txt", b"Synthetic Alice-owned evidence", "text/plain")
        path = f"/api/factory/jobs/{task['id']}/artifacts/{artifact['id']}"
        self.assertEqual(self.client.get(path).status_code, 200)
        other = TestClient(cast(ASGIApp, self.app), base_url=ORIGIN, follow_redirects=False)
        self.addCleanup(other.close)
        self.login("bob", other)
        self.assertEqual(other.get(path).status_code, 404)
        self.auth.directory.set_disabled("alice", True)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.assertIn(self.client.get("/api/factory/session").status_code, (401, 403))
        self.client.cookies.clear()
        callback = self.select("alice")
        denied = self.client.get(callback.headers["location"])
        self.assertIn("signin_failed", denied.headers["location"])
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        for manager in ("manager", "manager2"):
            self.client.cookies.clear()
            self.login(manager)
            self.assertEqual(self.client.get("/api/factory/session").json()["role"], "manager")
            self.auth.require_account_admin(manager)
        self.assertEqual(other.get("/api/factory/session").json()["id"], "bob")


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated loopback PostgreSQL")
class UnconfiguredPublicIdentityPostgresTests(unittest.TestCase):
    def test_no_idp_keeps_health_but_rejects_internal_tokens_and_legacy_cookie(self):
        from agent_factory.config import Settings as ProductSettings
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory(prefix='no-idp-postgres-')
        self.addCleanup(directory.cleanup)
        app = create_app(ProductSettings(db_url=database.url, workspace=Path(directory.name),
            jwt_key='synthetic-explicit-native-key-at-least-32bytes', max_workers=1))
        state = app.app.state.factory
        store, auth = state['store'], state['auth']
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.native_db.db_engine.dispose)
        self.assertEqual(list(auth.directory.ids()), [])
        initialize_members(auth)
        with TestClient(app, base_url=ORIGIN) as client:
            self.assertEqual(client.get('/api/health').status_code, 200)
            self.assertFalse(client.get('/api/factory/auth/config').json()['enabled'])
            token = auth._issue_native_token('alice')
            for headers in ({'Authorization': 'Bearer ' + token}, {'Cookie': 'factory_demo_session=' + token}):
                self.assertEqual(client.get('/api/factory/session', headers=headers).status_code, 401)
            response = client.portal.call(state['bridge']._request, 'GET', '/api/factory/session', 'alice')
            self.assertEqual(response['id'], 'alice')


if __name__ == "__main__":
    unittest.main()

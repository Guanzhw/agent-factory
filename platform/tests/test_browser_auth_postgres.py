"""Synthetic HTTPS-scheme browser identity against isolated native PostgreSQL.

ASGI scheme is not evidence of deployed TLS. No real identity or provider calls.
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.browser_oidc import BrowserCodeExchanger
from agent_factory.browser_auth import BrowserSessionService
from browser_identity_fixture import BrowserIdentityFixture
from pg_fixture import IsolatedPostgres

ORIGIN = "https://testserver"


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class BrowserAuthPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        workspace = TemporaryDirectory(prefix="factory-browser-identity-")
        self.addCleanup(workspace.cleanup)
        self.idp = BrowserIdentityFixture()
        self.settings = Settings(db_url=database.url, workspace=Path(workspace.name), demo=False,
            jwt_key="synthetic-browser-native-signing-key-more-than-32bytes", browser_oidc=self.idp.config(),
            max_workers=1, storage_task_reserve_bytes=8 * 1024 * 1024)
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.service = self.state["browser_auth"]
        self.service.exchanger = BrowserCodeExchanger(self.idp.config(), transport=self.idp.transport)
        self.auth.authorization.define_role("browser-fixture-user", ["agents:factory-executor:read",
            "agents:factory-executor:run", "components:read", "registry:read", "sessions:read", "filesystem:read"])
        for owner in ("alice", "bob"):
            self.auth.directory.upsert(owner, name="Synthetic " + owner)
            self.auth.authorization.assign(owner, "browser-fixture-user")
        self.client = TestClient(self.app, base_url=ORIGIN, follow_redirects=False).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.identity_client = TestClient(self.idp.app, base_url=self.idp.issuer, follow_redirects=False)
        self.addCleanup(self.identity_client.close)

    def begin(self):
        response = self.client.post("/api/factory/auth/login", json={}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        authorize = self.identity_client.get(response.json()["authorizationUrl"])
        self.assertEqual(authorize.status_code, 302, authorize.text)
        url = urlsplit(authorize.headers["location"])
        return url.path + "?" + url.query

    def login(self, subject="subject-alice"):
        self.idp.subject = subject
        callback = self.begin()
        response = self.client.get(callback)
        self.assertIn(response.status_code, (302, 303), response.text)
        self.assertEqual(response.headers["location"], "/")
        session = self.client.get("/api/factory/auth/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertTrue(session.json()["authenticated"])
        return callback, session.json()["csrfToken"]

    def test_pkce_callback_replay_cookie_security_csrf_and_logout(self):
        callback, csrf = self.login()
        self.assertEqual(self.idp.exchanges, 1)
        replay = self.client.get(callback)
        self.assertIn("signin_failed", replay.headers["location"])
        self.assertEqual(self.idp.exchanges, 1, "Consumed state must not redeem another code")
        # Replay may clear the session: obtain a fresh flow before CSRF checks.
        _, csrf = self.login()
        cookies = list(self.client.cookies.jar)
        session_cookie = next(cookie for cookie in cookies if cookie.name == "__Host-factory_session")
        self.assertTrue(session_cookie.secure)
        self.assertEqual(session_cookie.path, "/")
        self.assertIn("HttpOnly", session_cookie._rest)
        self.assertNotIn("__Host-factory_flow", [cookie.name for cookie in cookies])
        for headers in ({"Origin": ORIGIN}, {"Origin": "https://other.example.test", "X-Factory-CSRF": csrf}):
            response = self.client.post("/api/factory/auth/logout", json={}, headers=headers)
            self.assertEqual(response.status_code, 403, response.text)
        response = self.client.post("/api/factory/auth/logout", json={},
            headers={"Origin": ORIGIN, "X-Factory-CSRF": csrf})
        self.assertTrue(response.is_success, response.text)
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.assertEqual(self.client.get("/api/factory/session").status_code, 401)

    def test_current_sql_revocation_disablement_missing_owner_and_owner_isolation(self):
        self.login()
        plan = self.store.save_plan({"id": str(uuid4()), "ownerId": "alice", "syntheticFixture": True})
        task, _ = self.store.reserve_task(plan, "browser-" + str(uuid4()))
        artifact = self.store.artifact_write(task["id"], "synthetic.txt", b"Synthetic Alice artifact", "text/plain")
        path = f"/api/factory/jobs/{task['id']}/artifacts/{artifact['id']}"
        self.assertEqual(self.client.get(path).status_code, 200)
        self.auth.authorization.unassign("alice", "browser-fixture-user")
        self.assertEqual(self.client.get(path).status_code, 403)
        self.auth.directory.set_disabled("alice", True)
        self.assertIn(self.client.get("/api/factory/session").status_code, (401, 403))
        self.client.cookies.clear()
        self.login("subject-bob")
        self.assertEqual(self.client.get(path).status_code, 404)
        self.client.cookies.clear()
        self.idp.subject = "subject-missing"
        response = self.client.get(self.begin())
        self.assertIn("signin_failed", response.headers["location"])
        self.assertIsNone(self.auth.directory.get("missing"))

    def test_wrong_state_and_lost_callback_cookie_never_repeat_exchange(self):
        callback = self.begin()
        wrong = callback.rsplit("state=", 1)[0] + "state=not-the-original-state"
        response = self.client.get(wrong)
        self.assertIn("signin_failed", response.headers["location"])
        self.assertEqual(self.idp.exchanges, 0)
        callback = self.begin()
        response = self.client.get(callback)
        self.assertEqual(response.headers["location"], "/")
        self.assertEqual(self.idp.exchanges, 1)
        # Simulate a lost response/session cookie: replay cannot remint credentials.
        self.client.cookies.clear()
        self.client.get(callback)
        self.assertEqual(self.idp.exchanges, 1)
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])

    def test_restart_preserves_flow_session_then_expiry_and_config_drift_deny(self):
        callback = self.begin()
        original = self.service
        restarted = BrowserSessionService(self.store, self.auth, self.idp.config(), original.exchanger)
        self.app.service = restarted
        response = self.client.get(callback)
        self.assertEqual(response.headers["location"], "/")
        self.assertEqual(self.idp.exchanges, 1)
        token = self.client.cookies.get("__Host-factory_session")
        self.app.service = BrowserSessionService(self.store, self.auth, self.idp.config(), original.exchanger)
        self.assertTrue(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.assertEqual(self.client.get("/api/factory/session").json()["id"], "alice")
        rows = self.store.sql("SELECT id,kind,body FROM af_browser_auth")
        self.assertNotIn(token, json.dumps(rows, default=str))
        self.app.service = BrowserSessionService(self.store, self.auth,
            self.idp.config(max_auth_age_seconds=120), original.exchanger)
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.app.service = BrowserSessionService(self.store, self.auth, self.idp.config(), original.exchanger,
            clock=lambda: original.clock() + 901)
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.assertEqual(self.idp.exchanges, 1)

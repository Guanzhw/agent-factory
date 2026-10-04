"""Real create_app/native PostgreSQL with in-process development mock OIDC.

HTTPS ASGI scheme is simulated; these tests do not prove deployed TLS. No live
IdP/provider, host changes or alternate browser session implementation.
"""
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from typing import cast

from starlette.types import ASGIApp

from fastapi.testclient import TestClient

from agent_factory.browser_auth import SESSION_COOKIE
from agent_factory.config import Settings
from agent_factory.development_identity import PREFIX
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
        settings = Settings(db_url=database.url, workspace=Path(directory.name), max_workers=1,
            development_mock_login=True, development_public_origin=ORIGIN,
            temporary_policy="admin-review", storage_task_reserve_bytes=8*1024*1024)
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(cast(ASGIApp, self.app), base_url=ORIGIN, follow_redirects=False).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def select(self, persona, client=None):
        client = client or self.client
        started = client.post("/api/factory/auth/login", json={}, headers={"Origin": ORIGIN})
        self.assertEqual(started.status_code, 200, started.text)
        selector = client.get(started.json()["authorizationUrl"])
        self.assertEqual(selector.status_code, 200, selector.text)
        form = {"persona": persona}
        for name in ("flow", "csrf"):
            match = re.search('name="' + name + '" value="([A-Za-z0-9_-]{43})"', selector.text)
            assert match is not None
            form[name] = match.group(1)
        selected = client.post(PREFIX + "/select", data=form, headers={"Origin": ORIGIN})
        self.assertEqual(selected.status_code, 303, selected.text)
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
        self.assertIn("signin_cancelled", cancelled.headers["location"])
        self.assertFalse(self.client.get("/api/factory/auth/session").json()["authenticated"])
        self.assertEqual(self.store.sql("SELECT id FROM af_browser_auth WHERE kind='session'"), [])
        csrf = self.login("alice")
        opaque = self.client.cookies.get(SESSION_COOKIE)
        for _ in range(3):
            self.assertEqual(self.client.get("/").status_code, 200)
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
        self.auth.authorization.unassign("alice", "factory-user")
        self.assertEqual(self.client.get(path).status_code, 403)
        self.auth.directory.set_disabled("alice", True)
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
            self.auth.require(manager, "agent_os:admin")
        self.assertEqual(other.get("/api/factory/session").json()["id"], "bob")


if __name__ == "__main__":
    unittest.main()

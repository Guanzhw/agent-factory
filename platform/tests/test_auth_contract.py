"""Actual native authorization contracts; no provider/network calls or fake ACL store."""
from contextvars import Context
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.session.agent import AgentSession
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.authz import AuthorizationContext
from agno.os.authz._request_scope import request_scope
from fastapi import HTTPException, Request
import httpx
import jwt

from agent_factory.demo_model import DemoModel
from agent_factory.auth import AUDIENCE, AuthService, CookieBridge, DEMO_COOKIE
from agent_factory.native_bridge import INTERNAL_NATIVE, NativeBridge


class NativeAuthContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.settings = SimpleNamespace(demo=True, jwt_key=secrets.token_urlsafe(48))
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "native-auth.sqlite"))
        self.addCleanup(self.db.db_engine.dispose)
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        self.native = AgentOS(id="agent-factory", db=self.db, agents=[Agent(id="factory-executor", db=self.db, model=DemoModel())],
                              **self.auth.agentos_kwargs(),
                              mcp=False, scheduler=False, telemetry=False).get_app()

        @self.native.get("/api/test/me")
        def me(request: Request):
            return self.auth.user(request)

        @self.native.post("/api/test/protected")
        def protected(request: Request):
            user = self.auth.user(request)
            self.auth.require(user["id"], "run")
            return {"allowed": True}

        @self.native.get("/api/test/context")
        def internal_context(request: Request):
            return {"id": self.auth.user(request)["id"], "internal": INTERNAL_NATIVE.get()}

        self.app = CookieBridge(self.native, self.settings)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test.local")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.db.db_engine.dispose()
        self.directory.cleanup()

    def bearer(self, persona):
        return {"Authorization": "Bearer " + self.auth.issue_demo_token(persona)}

    async def test_native_verification_and_cookie_bridge(self):
        self.assertEqual((await self.client.get("/api/test/me")).status_code, 401)
        verified = await self.client.get("/api/test/me", headers=self.bearer("alice"))
        self.assertEqual(verified.json(), {"id": "alice", "name": "Alice", "role": "user"})
        token = self.auth.issue_demo_token("bob")
        cookie = {"Cookie": f"{DEMO_COOKIE}={token}"}
        self.assertEqual((await self.client.get("/api/test/me", headers=cookie)).json()["id"], "bob")
        # Explicit bearer must take precedence over a cookie.
        self.assertEqual((await self.client.get("/api/test/me", headers={**cookie, **self.bearer("alice")})).json()["id"], "alice")
        self.assertEqual((await self.client.get("/api/test/me", headers={"Cookie": f"{DEMO_COOKIE}=forged"})).status_code, 401)

    async def test_current_revocation_and_startup_do_not_restore_grants(self):
        token = self.bearer("alice")
        self.assertEqual((await self.client.post("/api/test/protected", headers=token)).status_code, 200)
        self.auth.authorization.unassign("alice", "factory-user")
        self.auth.initialize_demo()
        self.assertEqual(self.auth.authorization.roles_of("alice"), [])
        with self.assertRaises(HTTPException) as denied:
            self.auth.require("alice", "run")
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual((await self.client.post("/api/test/protected", headers=token)).status_code, 403)

    async def test_user_disablement_is_current_and_preserved(self):
        token = self.bearer("bob")
        self.auth.directory.set_disabled("bob", True)
        self.auth.initialize_demo()
        with self.assertRaises(HTTPException) as denied:
            self.auth.require("bob", "run")
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual((await self.client.get("/api/test/me", headers=token)).status_code, 403)

    async def test_token_scopes_cannot_enlarge_managed_rights(self):
        valid = jwt.decode(self.auth.issue_demo_token("alice"), self.settings.jwt_key, algorithms=["HS256"], audience=AUDIENCE)
        valid["scopes"] = ["agent_os:admin"]
        valid["roles"] = ["manager"]
        token = jwt.encode(valid, self.settings.jwt_key, algorithm="HS256")
        response = await self.client.post("/components", json={"name": "Denied", "component_type": "agent"},
                                          headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 403)
        created = await self.client.post("/components", json={"name": "Manager draft", "component_type": "agent"},
                                        headers=self.bearer("manager"))
        self.assertEqual(created.status_code, 201, created.text)

    async def test_production_has_no_demo_setup_or_cookie_identity(self):
        production = SimpleNamespace(demo=False, jwt_key=self.settings.jwt_key)
        auth = AuthService(production, self.db)
        auth.initialize_demo()
        with self.assertRaises(HTTPException) as disabled:
            auth.issue_demo_token("manager")
        self.assertEqual(disabled.exception.status_code, 404)
        transport = httpx.ASGITransport(app=CookieBridge(self.native, production))
        async with httpx.AsyncClient(transport=transport, base_url="http://test.local") as client:
            cookie = {"Cookie": f"{DEMO_COOKIE}={self.auth.issue_demo_token('manager')}"}
            self.assertEqual((await client.get("/api/test/me", headers=cookie)).status_code, 401)
        with self.assertRaises(ValueError):
            AuthService(SimpleNamespace(demo=False, jwt_key=""), self.db)

    async def test_cookie_mutations_reject_explicit_cross_origin(self):
        cookie = {"Cookie": f"{DEMO_COOKIE}={self.auth.issue_demo_token('alice')}", "Origin": "http://other.local"}
        self.assertEqual((await self.client.post("/api/test/protected", headers=cookie)).status_code, 403)
        cookie["Origin"] = "http://test.local"
        self.assertEqual((await self.client.post("/api/test/protected", headers=cookie)).status_code, 200)

    async def test_bridge_rejects_cross_user_plan_before_native_submission(self):
        bridge = NativeBridge(self.settings, self.db, self.auth)
        bridge.attach(self.native)
        with self.assertRaises(HTTPException) as denied:
            await bridge.submit({"id": "plan", "ownerId": "bob", "task_id": "00000000-0000-0000-0000-000000000001"}, "alice", "request")
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException) as malformed:
            await bridge.continue_run("run", "session", "alice", [{"tool_execution": {}}])
        self.assertEqual(malformed.exception.status_code, 400)

    async def test_bridge_context_is_process_owned_and_reset(self):
        bridge = NativeBridge(self.settings, self.db, self.auth)
        bridge.attach(self.native)
        external = await self.client.get("/api/test/context", headers={**self.bearer("alice"), "X-Internal-Native": "true"})
        self.assertFalse(external.json()["internal"])
        internal = await bridge._request("GET", "/api/test/context", "alice")
        self.assertEqual(internal, {"id": "alice", "internal": True})
        self.assertFalse(INTERNAL_NATIVE.get())
        with self.assertRaises(HTTPException):
            await bridge._request("GET", "/nonexistent", "alice")
        self.assertFalse(INTERNAL_NATIVE.get())

    async def test_native_cancel_requires_owned_query_session(self):
        self.db.upsert_session(AgentSession(session_id="cancel-session", agent_id="factory-executor", user_id="alice",
                                            runs=[RunOutput(run_id="cancel-run", agent_id="factory-executor",
                                                            session_id="cancel-session", user_id="alice")]))
        self.db.upsert_run(RunOutput(run_id="cancel-run", agent_id="factory-executor",
                                     session_id="cancel-session", user_id="alice"),
                           session_id="cancel-session", user_id="alice", run_index=0)
        bridge = NativeBridge(self.settings, self.db, self.auth)
        bridge.attach(self.native)
        self.assertEqual(await bridge.cancel_run("cancel-run", "cancel-session", "alice"), {})
        with self.assertRaises(HTTPException) as cross_user:
            await bridge.cancel_run("cancel-run", "cancel-session", "bob")
        self.assertEqual(cross_user.exception.status_code, 404)

    async def test_demo_token_matches_cookie_lifetime(self):
        claims = jwt.decode(self.auth.issue_demo_token("alice"), self.settings.jwt_key, algorithms=["HS256"], audience=AUDIENCE)
        self.assertEqual(claims["exp"] - claims["iat"], 3600)

    async def test_effect_boundary_discards_earlier_request_policy_cache(self):
        context = AuthorizationContext(principal_id="alice", resource_type="agents",
                                       resource_id="factory-executor", action="run")
        with request_scope():
            self.assertTrue(self.auth.authorization.provider.check(context))
            # Separate context models an operator changing SQL policy on another
            # request while this request still carries its earlier memoization.
            Context().run(self.auth.authorization.unassign, "alice", "factory-user")
            with self.assertRaises(HTTPException) as denied:
                self.auth.require("alice", "run")
            self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

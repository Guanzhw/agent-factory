"""Actual native authorization contracts; no provider/network calls or fake ACL store."""
from contextvars import Context
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.session.agent import AgentSession
from agno.db.sqlite import SqliteDb
from agno.db.schemas.service_accounts import ServiceAccount
from agno.os import AgentOS
from agno.os.authz import AuthorizationContext
from agno.os.authz._request_scope import request_scope
from agno.workflow import Workflow
from agno.os.service_accounts import generate_token
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import httpx
import jwt
from starlette.websockets import WebSocketDisconnect

from core_native_fixture import FixtureModel as DemoModel
from agent_factory.auth import AUDIENCE, AuthService, CookieBridge, DEMO_COOKIE, MemberTokenBoundary
from agent_factory.accounts import account_router
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
                              workflows=[Workflow(id="added-after-members", db=self.db,
                                                  steps=[Agent(id="workflow-step", model=DemoModel())])],
                              **self.auth.agentos_kwargs(),
                              mcp=False, scheduler=False, telemetry=False).get_app()
        self.native.add_middleware(MemberTokenBoundary)
        self.native.include_router(account_router(self.auth))

        @self.native.get("/api/test/me")
        def me(request: Request):
            return self.auth.user(request)

        @self.native.post("/api/test/protected")
        def protected(request: Request):
            user = self.auth.user(request)
            self.auth.require_member(user["id"])
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

    async def test_active_members_need_no_legacy_resource_grants(self):
        token = self.bearer("alice")
        self.assertEqual((await self.client.post("/api/test/protected", headers=token)).status_code, 200)
        self.auth.account_roles.unassign("alice", "factory-user")
        self.auth.initialize_demo()
        self.assertEqual(self.auth.account_roles.roles_of("alice"), [])
        self.auth.require_member("alice")
        self.assertEqual((await self.client.post("/api/test/protected", headers=token)).status_code, 200)

    async def test_user_disablement_is_current_and_preserved(self):
        token = self.bearer("bob")
        self.auth.directory.set_disabled("bob", True)
        self.auth.initialize_demo()
        with self.assertRaises(HTTPException) as denied:
            self.auth.require_member("bob")
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual((await self.client.get("/api/test/me", headers=token)).status_code, 403)

    async def test_members_create_components_but_token_claims_cannot_manage_accounts(self):
        valid = jwt.decode(self.auth.issue_demo_token("alice"), self.settings.jwt_key, algorithms=["HS256"], audience=AUDIENCE)
        valid["scopes"] = ["agent_os:admin"]
        valid["roles"] = ["manager"]
        token = jwt.encode(valid, self.settings.jwt_key, algorithm="HS256")
        response = await self.client.post("/components", json={"name": "Member component", "component_type": "agent"},
                                          headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 201, response.text)
        denied = await self.client.get("/api/factory/accounts", headers={"Authorization": "Bearer " + token})
        self.assertEqual(denied.status_code, 403, denied.text)
        for persona in ("alice", "manager"):
            response = await self.client.get("/users", headers=self.bearer(persona))
            self.assertEqual(response.status_code, 403, response.text)

    async def test_every_member_can_discover_and_run_workflows_added_after_account_creation(self):
        for persona in ("alice", "manager"):
            listed = await self.client.get("/workflows", headers=self.bearer(persona))
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertIn("added-after-members", listed.text)
            detail = await self.client.get("/workflows/added-after-members", headers=self.bearer(persona))
            self.assertEqual(detail.status_code, 200, detail.text)
            ran = await self.client.post("/workflows/added-after-members/runs", data={"message": "hello", "stream": "false"},
                                         headers=self.bearer(persona))
            self.assertEqual(ran.status_code, 200, ran.text)

    async def test_account_admin_boundary_and_current_membership(self):
        self.assertEqual((await self.client.get("/api/factory/accounts", headers=self.bearer("alice"))).status_code, 403)
        admin = self.bearer("manager")
        created = await self.client.post("/api/factory/accounts", json={"id": "new-member", "name": "New member"}, headers=admin)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertFalse(created.json()["accountAdmin"])
        self.auth.require_member("new-member")
        enabled_token = {"Authorization": "Bearer " + self.auth._issue_native_token("new-member")}
        updated = await self.client.patch("/api/factory/accounts/new-member", json={"disabled": True}, headers=admin)
        self.assertEqual(updated.status_code, 200, updated.text)
        duplicate = await self.client.post("/api/factory/accounts", json={"id": "new-member"}, headers=admin)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        renamed = await self.client.patch("/api/factory/accounts/new-member", json={"name": "Renamed"}, headers=admin)
        self.assertTrue(renamed.json()["disabled"])
        self.assertEqual((await self.client.get("/api/test/me", headers=enabled_token)).status_code, 403)
        self.auth.account_roles.unassign("manager", "factory-manager")
        self.auth.initialize_demo()
        self.assertEqual((await self.client.get("/api/factory/accounts", headers=admin)).status_code, 403)
        self.auth.require_member("manager")

    async def test_administrator_keeps_native_session_isolation(self):
        # Old installations may retain the former global resource scope. It is
        # storage history and never grants native authority through this provider.
        self.auth.account_roles.set_role_scopes("factory-manager", [("agent_os:admin", "allow")])
        self.db.upsert_session(AgentSession(session_id="alice-private", agent_id="factory-executor", user_id="alice"))
        denied = await self.client.get("/sessions/alice-private", headers=self.bearer("manager"))
        self.assertIn(denied.status_code, {403, 404}, denied.text)
        scoped = await self.client.get("/sessions", params={"user_id": "alice"}, headers=self.bearer("manager"))
        self.assertEqual(scoped.status_code, 200, scoped.text)
        self.assertEqual(scoped.json()["data"], [])

    async def test_account_admin_flag_changes_are_effective_on_existing_tokens(self):
        alice = self.bearer("alice")
        manager = self.bearer("manager")
        promoted = await self.client.patch("/api/factory/accounts/alice", json={"accountAdmin": True}, headers=manager)
        self.assertTrue(promoted.json()["accountAdmin"])
        self.assertEqual((await self.client.get("/api/factory/accounts", headers=alice)).status_code, 200)
        demoted = await self.client.patch("/api/factory/accounts/alice", json={"accountAdmin": False}, headers=manager)
        self.assertFalse(demoted.json()["accountAdmin"])
        self.assertEqual((await self.client.get("/api/factory/accounts", headers=alice)).status_code, 403)
        self.assertEqual((await self.client.post("/api/test/protected", headers=alice)).status_code, 200)

    async def test_account_api_validates_external_inputs(self):
        admin = self.bearer("manager")
        for payload in ({"id": "factory-manager"}, {"id": "__internal"},
                        {"id": "someone", "roles": ["agent_os:admin"]}):
            response = await self.client.post("/api/factory/accounts", json=payload, headers=admin)
            self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.patch("/api/factory/accounts/alice", json={"disabled": None}, headers=admin)
        self.assertEqual(response.status_code, 422, response.text)

    async def test_native_global_admin_probe_and_machine_account_apis_are_closed(self):
        provider = self.auth.authorization.provider
        for persona in ("alice", "manager"):
            self.assertFalse(provider.check(AuthorizationContext(principal_id=persona, resource_type="*",
                                                                resource_id="*", action="*")))
            # A wildcard resource ID remains ordinary all-component visibility.
            self.assertEqual(provider.accessible_resource_ids(AuthorizationContext(principal_id=persona,
                             resource_type="workflows", action="read")), {"*"})
            minted = await self.client.post("/service-accounts", headers=self.bearer(persona), json={
                "name": "escalation-" + persona, "allow_privileged_scopes": True,
                "scopes": [{"scope": "agent_os:admin", "effect": "allow"}]})
            self.assertEqual(minted.status_code, 403, minted.text)
            listed = await self.client.get("/service-accounts", headers=self.bearer(persona))
            self.assertEqual(listed.status_code, 403, listed.text)

    async def test_native_schema_administration_is_denied_before_migration_dispatch(self):
        with patch("agno.os.routers.database.MigrationManager") as migrate:
            for persona in ("alice", "manager"):
                headers = self.bearer(persona)
                config = await self.client.get("/config", headers=headers)
                self.assertEqual(config.status_code, 200, config.text)
                for path in ("/databases/all/migrate", f"/databases/{self.db.id}/migrate"):
                    denied = await self.client.post(path, headers=headers, params={"target_version": "0.0.0"})
                    self.assertEqual(denied.status_code, 403, denied.text)
            migrate.assert_not_called()

    async def test_persisted_native_admin_pat_cannot_escape_member_disablement_or_owner_isolation(self):
        token, token_hash, token_prefix = generate_token()
        self.db.create_service_account(ServiceAccount(id="old-pat", name="legacy-alice", token_hash=token_hash,
            token_prefix=token_prefix, scopes=["agent_os:admin"], user_id="alice", created_by="alice").to_dict())
        self.db.upsert_session(AgentSession(session_id="bob-private", agent_id="factory-executor", user_id="bob"))
        for disabled in (False, True):
            self.auth.directory.set_disabled("alice", disabled)
            for credential in ("Bearer " + token, token, "bearer   " + token + "  "):
                response = await self.client.get("/sessions/bob-private", headers={"Authorization": credential})
                self.assertEqual(response.status_code, 401, response.text)

    async def test_native_websocket_member_auth_and_disabled_actions_reject_pat_frames(self):
        token, token_hash, token_prefix = generate_token()
        self.db.create_service_account(ServiceAccount(id="old-ws-pat", name="legacy-ws-alice", token_hash=token_hash,
            token_prefix=token_prefix, scopes=["agent_os:admin"], user_id="alice", created_by="alice").to_dict())
        alice_jwt = self.auth._issue_native_token("alice")
        with TestClient(self.native) as client:
            with client.websocket_connect("/workflows/ws") as socket:
                self.assertEqual(socket.receive_json()["event"], "connected")
                socket.send_json({"action": "authenticate", "token": alice_jwt})
                self.assertEqual(socket.receive_json()["event"], "authenticated")
                self.assertEqual(socket.receive_json()["user_id"], "alice")
                socket.send_json({"action": "ping"})
                self.assertEqual(socket.receive_json()["event"], "pong")
                self.auth.directory.set_disabled("alice", True)
                socket.send_json({"action": "start-workflow", "workflow_id": "added-after-members", "message": "must not run"})
                self.assertEqual(socket.receive_json(), {"event": "error", "error": "User is disabled"})
            for current_disabled in (False, True):
                self.auth.directory.set_disabled("alice", current_disabled)
                for first_identity in (None, "manager"):
                    with client.websocket_connect("/workflows/ws") as socket:
                        self.assertEqual(socket.receive_json()["event"], "connected")
                        if first_identity is not None:
                            socket.send_json({"action": "authenticate", "token": self.auth._issue_native_token(first_identity)})
                            self.assertEqual(socket.receive_json()["event"], "authenticated")
                            self.assertEqual(socket.receive_json()["user_id"], first_identity)
                        socket.send_json({"action": "authenticate", "token": token})
                        with self.assertRaises(WebSocketDisconnect) as closed:
                            socket.receive_json()
                        self.assertEqual(closed.exception.code, 1008)

    async def test_legacy_custom_admin_migration_preserves_accounts_and_demotion_across_restart(self):
        for owner in ("legacy-custom", "legacy-disabled"):
            self.auth.directory.upsert(owner, name=owner, metadata={"retained": "synthetic"})
        self.auth.directory.set_disabled("legacy-disabled", True)
        self.auth.account_roles.set_role_scopes("custom-old-administrator", [("agent_os:admin", "allow")])
        for owner in ("legacy-custom", "legacy-disabled"):
            self.auth.account_roles.assign(owner, "custom-old-administrator")
        restarted = AuthService(self.settings, self.db)
        restarted.require_account_admin("legacy-custom")
        disabled = restarted.directory.get("legacy-disabled")
        self.assertTrue(disabled["disabled"])
        self.assertEqual(disabled["metadata"]["retained"], "synthetic")
        with self.assertRaises(HTTPException):
            restarted.require_account_admin("legacy-disabled")
        # Remove only the new account flag; former resource policy is retained.
        restarted.account_roles.unassign("legacy-custom", "factory-manager")
        again = AuthService(self.settings, self.db)
        with self.assertRaises(HTTPException) as demoted:
            again.require_account_admin("legacy-custom")
        self.assertEqual(demoted.exception.status_code, 403)
        again.require_member("legacy-custom")

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

    async def test_effect_boundary_reads_disablement_after_earlier_request_check(self):
        context = AuthorizationContext(principal_id="alice", resource_type="agents",
                                       resource_id="factory-executor", action="run")
        with request_scope():
            self.assertTrue(self.auth.authorization.provider.check(context))
            # Separate context models an operator changing SQL policy on another
            # request while this request still carries its earlier memoization.
            Context().run(self.auth.directory.set_disabled, "alice", True)
            with self.assertRaises(HTTPException) as denied:
                self.auth.require_member("alice")
            self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

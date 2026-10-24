"""Native Agno identity, durable queue and account migration on isolated PG."""
import os
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.db.schemas.service_accounts import ServiceAccount
from agno.job_queue import QueueConfig
from agno.os import AgentOS
from agno.os.service_accounts import generate_token
from agno.session.agent import AgentSession
from agno.workflow import Workflow
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent_factory.accounts import account_router
from agent_factory.auth import AuthService, MemberTokenBoundary
from agent_factory_research.demo_model import DemoModel
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class TeamMembershipPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        self.db = PostgresDb(db_url=database.url, id="team-membership-native")
        self.addCleanup(self.db.db_engine.dispose)
        self.settings = SimpleNamespace(demo=True, jwt_key="synthetic-team-native-key-more-than-32-bytes")
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        native = AgentOS(id="team-membership", db=self.db,
            agents=[Agent(id="new-member-component", db=self.db, model=DemoModel())],
            workflows=[Workflow(id="new-member-workflow", db=self.db, steps=[Agent(model=DemoModel())])],
            queue=QueueConfig(durable=True, max_concurrency=1),
            **self.auth.agentos_kwargs(), mcp=False, scheduler=False, telemetry=False).get_app()
        native.add_middleware(MemberTokenBoundary)
        native.include_router(account_router(self.auth))
        self.client = TestClient(native).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def headers(self, owner):
        return {"Authorization": "Bearer " + self.auth._issue_native_token(owner)}

    def test_member_and_account_admin_run_new_native_components_and_workflows(self):
        for owner in ("alice", "manager"):
            headers = self.headers(owner)
            for path in ("/agents/new-member-component/runs", "/workflows/new-member-workflow/runs"):
                response = self.client.post(path, headers=headers, data={"message": "synthetic hello", "stream": "false"})
                self.assertEqual(response.status_code, 200, response.text)
            created = self.client.post("/components", headers=headers,
                json={"name": owner + " component", "component_type": "agent"})
            self.assertEqual(created.status_code, 201, created.text)
        alice = self.headers("alice")
        self.auth.directory.set_disabled("alice", True)
        denied = self.client.post("/agents/new-member-component/runs", headers=alice,
                                  data={"message": "must not run", "stream": "false"})
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_native_global_surfaces_and_persisted_pat_do_not_bypass_accounts(self):
        self.assertIsNotNone(self.client.app.state.queue_worker)
        self.db.upsert_session(AgentSession(session_id="bob-private", agent_id="new-member-component", user_id="bob",
                                            created_at=int(time.time()), updated_at=int(time.time())))
        for owner in ("alice", "manager"):
            headers = self.headers(owner)
            for path in ("/queue/jobs", "/queue/jobs/other-job", "/service-accounts", "/users"):
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
            minted = self.client.post("/service-accounts", headers=headers, json={"name": "bad-" + owner,
                "allow_privileged_scopes": True, "scopes": [{"scope": "agent_os:admin", "effect": "allow"}]})
            self.assertEqual(minted.status_code, 403, minted.text)
            denied = self.client.get("/sessions/bob-private", headers=headers)
            self.assertEqual(denied.status_code, 404, denied.text)
            with patch("agno.os.routers.database.MigrationManager") as migrate:
                for path in ("/databases/all/migrate", f"/databases/{self.db.id}/migrate"):
                    denied = self.client.post(path, headers=headers, params={"target_version": "0.0.0"})
                    self.assertEqual(denied.status_code, 403, denied.text)
                migrate.assert_not_called()
        token, token_hash, token_prefix = generate_token()
        self.db.create_service_account(ServiceAccount(id="historical-admin", name="historical-alice",
            token_hash=token_hash, token_prefix=token_prefix, scopes=["agent_os:admin"],
            created_by="alice", user_id="alice").to_dict())
        self.auth.directory.set_disabled("alice", True)
        for path in ("/sessions/bob-private", "/queue/jobs"):
            denied = self.client.get(path, headers={"Authorization": "Bearer " + token})
            self.assertEqual(denied.status_code, 401, denied.text)
        with self.client.websocket_connect("/workflows/ws") as socket:
            self.assertEqual(socket.receive_json()["event"], "connected")
            socket.send_json({"action": "authenticate", "token": token})
            with self.assertRaises(WebSocketDisconnect) as denied:
                socket.receive_json()
            self.assertEqual(denied.exception.code, 1008)

    def test_native_member_websocket_executes_with_own_identity(self):
        with self.client.websocket_connect("/workflows/ws") as socket:
            self.assertEqual(socket.receive_json()["event"], "connected")
            socket.send_json({"action": "authenticate", "token": self.auth._issue_native_token("alice")})
            self.assertEqual(socket.receive_json()["event"], "authenticated")
            self.assertEqual(socket.receive_json()["user_id"], "alice")
            socket.send_json({"action": "start-workflow", "workflow_id": "new-member-workflow",
                              "message": "synthetic websocket run", "user_id": "bob"})
            queued = socket.receive_json()
            self.assertEqual(queued["event"], "queued", queued)
            self.assertEqual(self.db.get_job(queued["run_id"])["user_id"], "alice")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.db.get_job(queued["run_id"])
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(.05)
        self.assertEqual(job["status"], "completed", job)

    def test_custom_legacy_admin_migrates_once_and_demotion_persists(self):
        for owner in ("legacy-admin", "legacy-disabled"):
            self.auth.directory.upsert(owner, metadata={"retained": "synthetic"})
        self.auth.directory.set_disabled("legacy-disabled", True)
        self.auth.account_roles.set_role_scopes("former-custom-admin", [("agent_os:admin", "allow")])
        for owner in ("legacy-admin", "legacy-disabled"):
            self.auth.account_roles.assign(owner, "former-custom-admin")
        restarted = AuthService(self.settings, self.db)
        restarted.require_account_admin("legacy-admin")
        self.assertTrue(restarted.directory.get("legacy-disabled")["disabled"])
        self.assertEqual(restarted.directory.get("legacy-disabled")["metadata"]["retained"], "synthetic")
        manager = self.headers("manager")
        legacy = {"Authorization": "Bearer " + restarted._issue_native_token("legacy-admin")}
        self.assertEqual(self.client.get("/api/factory/accounts", headers=legacy).status_code, 200)
        demoted = self.client.patch("/api/factory/accounts/legacy-admin", headers=manager, json={"accountAdmin": False})
        self.assertEqual(demoted.status_code, 200, demoted.text)
        again = AuthService(self.settings, self.db)
        with self.assertRaises(HTTPException):
            again.require_account_admin("legacy-admin")
        self.assertEqual(self.client.get("/api/factory/accounts", headers=legacy).status_code, 403)


if __name__ == "__main__":
    unittest.main()

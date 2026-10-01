"""Actual installed Agno cancellation schema and current-owner regression.

This controlled ASGI target uses real native JWT, managed SQL policy, session/run
storage and cancellation intent. No model, worker, remote host or experiment is
started. It proves native request compatibility, not Factory-to-Factory dispatch
or confirmed external process cleanup. Factory native ingress remains closed.
"""
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.run.cancel import acleanup_run, ais_cancelled
from agno.session.agent import AgentSession
from fastapi import HTTPException
import httpx

from agent_factory.auth import AuthService
from agent_factory.demo_model import DemoModel
from agent_factory.main import NativeIngress
from agent_factory.resources import NativeAgnoHTTP, RemoteTarget


class NativeRemoteCancelContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.settings = SimpleNamespace(demo=True, jwt_key=secrets.token_urlsafe(48))
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "native-cancel.sqlite"))
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        agent = Agent(id="factory-executor", db=self.db, model=DemoModel(), telemetry=False)
        self.app = AgentOS(id="native-cancel-schema-fixture", agents=[agent], db=self.db,
                           **self.auth.agentos_kwargs(), mcp=False, scheduler=False,
                           telemetry=False).get_app()
        self.session_id, self.run_id = str(uuid4()), str(uuid4())
        run = RunOutput(run_id=self.run_id, session_id=self.session_id,
                        user_id="alice", agent_id="factory-executor")
        self.db.upsert_session(AgentSession(session_id=self.session_id, user_id="alice",
                                           agent_id="factory-executor", runs=[run]))
        self.db.upsert_run(run, session_id=self.session_id, user_id="alice", run_index=0)
        self.target = RemoteTarget("Controlled native ASGI schema target", "runtime",
                                   frozenset({"alice", "bob"}), base_url="http://native.cancel.fixture",
                                   headers=self.bearer, transport=httpx.ASGITransport(app=self.app),
                                   synthetic_fixture=True)
        self.adapter = NativeAgnoHTTP(self.target)
        self.lease = {"remoteRunId": self.run_id, "remoteSessionId": self.session_id}

    def bearer(self, owner):
        return {"Authorization": "Bearer " + self.auth.issue_demo_token(owner)}

    async def asyncTearDown(self):
        await acleanup_run(self.run_id)
        self.db.db_engine.dispose()
        self.directory.cleanup()

    async def test_form_session_is_rejected_without_cancellation_intent(self):
        async with httpx.AsyncClient(transport=self.target.transport,
                                     base_url=self.target.base_url) as client:
            response = await client.post(self.adapter.run_path(self.run_id) + "/cancel",
                                         headers=self.bearer("alice"),
                                         data={"session_id": self.session_id})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(await ais_cancelled(self.run_id))

    async def test_adapter_query_session_records_actual_native_intent(self):
        self.assertFalse(await ais_cancelled(self.run_id))
        acknowledgement = await self.adapter.cancel("alice", self.lease)
        self.assertEqual(acknowledgement, {})
        self.assertTrue(await ais_cancelled(self.run_id))
        # Intent is the asserted evidence; there is no executing process here.

    async def test_cross_owner_wrong_session_and_revocation_precede_intent(self):
        with self.assertRaises(HTTPException) as cross_owner:
            await self.adapter.cancel("bob", self.lease)
        self.assertEqual(cross_owner.exception.status_code, 404)
        wrong_session = {**self.lease, "remoteSessionId": str(uuid4())}
        with self.assertRaises(HTTPException) as wrong_binding:
            await self.adapter.cancel("alice", wrong_session)
        self.assertEqual(wrong_binding.exception.status_code, 404)
        self.auth.authorization.unassign("alice", "factory-user")
        with self.assertRaises(HTTPException) as revoked:
            await self.adapter.cancel("alice", self.lease)
        self.assertEqual(revoked.exception.status_code, 403)
        self.assertFalse(await ais_cancelled(self.run_id))

    async def test_correct_native_query_does_not_bypass_factory_ingress(self):
        self.app.add_middleware(NativeIngress)
        with self.assertRaises(HTTPException) as denied:
            await self.adapter.cancel("alice", self.lease)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertFalse(await ais_cancelled(self.run_id))


if __name__ == "__main__":
    unittest.main()

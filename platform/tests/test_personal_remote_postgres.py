"""Opt-in native SQL authorization + owner remote HTTP lifecycle.

Runs only against the existing disposable-loopback PostgreSQL CI service.
Remote IO and secret backends remain controlled synthetic fixtures.
"""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.auth import EXECUTOR_ID
from agent_factory.config import Settings
from agent_factory.connections import ConnectionService
from agent_factory.main import create_app
from agent_factory.personal_remote_provider import OpenCodeServeProvider, PROVIDER_ID
from pg_fixture import IsolatedPostgres
from test_personal_remote_connections import Probe, Secrets


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class PersonalRemotePostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.secrets, self.probe = Secrets(), Probe()
        self.providers = {PROVIDER_ID: OpenCodeServeProvider(self.secrets, probe=self.probe)}
        settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1)
        settings.personal_connection_providers = self.providers
        self.app = create_app(settings)
        state = self.app.app.state.factory
        self.store, self.auth, self.service = state["store"], state["auth"], state["connections"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.root = "/api/factory/personal-remotes"

    def login(self, owner):
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/factory/demo/login", json={"persona": owner}).status_code, 200)

    def test_actual_http_auth_scope_bind_restart_and_native_grant_revocation(self):
        self.assertEqual(self.client.get(self.root).status_code, 401)
        self.login("alice")
        payload = {"providerId": PROVIDER_ID, "origin": "https://runtime.example.com",
            "credentialRef": "synthetic-vault-ref", "credentialRevision": "v1", "projectId": "project-fixture",
            "requestId": uuid4().hex}
        created = self.client.post(self.root, json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        reference = created.json()["registrationRef"]
        verified = self.client.post(f"{self.root}/{reference}/verify", json={"requestId": uuid4().hex})
        self.assertEqual(verified.status_code, 200, verified.text)
        bound_response = self.client.post("/api/factory/user-connections", json={
            "registrationRef": reference, "requestId": uuid4().hex, "capabilities": ["runtime:health"]})
        self.assertEqual(bound_response.status_code, 201, bound_response.text)
        bound = bound_response.json()
        self.assertEqual(self.service.preflight("alice", bound["ref"], "environment")["status"], "active")
        restarted = ConnectionService(self.store, self.auth, personal_providers=self.providers)
        self.assertEqual(restarted.preflight("alice", bound["ref"], "environment")["fingerprint"], bound["fingerprint"])
        self.login("bob")
        self.assertEqual(self.client.get(f"{self.root}/{reference}").status_code, 404)
        self.assertEqual(self.client.post(f"{self.root}/{reference}/verify", json={"requestId": uuid4().hex}).status_code, 404)
        self.assertEqual(self.client.post(self.root, json=payload | {"requestId": uuid4().hex}).status_code, 403)
        self.login("alice")
        self.auth.authorization.define_role("personal-remote-reader", [f"agents:{EXECUTOR_ID}:read", "components:read", "sessions:read"])
        self.auth.authorization.set_role("alice", "personal-remote-reader")
        with self.assertRaises(HTTPException) as denied:
            restarted.resolve("alice", bound["ref"], "environment")
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(self.client.post(f"{self.root}/{reference}/verify", json={"requestId": uuid4().hex}).status_code, 403)
        revoked = self.client.post(f"{self.root}/{reference}/revoke", json={"requestId": uuid4().hex})
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(revoked.json()["status"], "revoked")
        config = self.store.sql("SELECT body FROM af_personal_remote_configs")
        self.assertNotIn("synthetic-only-password", str(config))
        self.assertNotIn("synthetic-only-password", str(self.store.sql("SELECT body FROM af_audit")))


if __name__ == "__main__":
    unittest.main()

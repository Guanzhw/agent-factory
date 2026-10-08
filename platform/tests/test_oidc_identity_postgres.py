"""Production ASGI identity boundary with synthetic RSA subjects and isolated PG.

Task/artifact fixtures below exercise persisted owner isolation, not execution or
an actual identity provider. No discovery, provider calls, or real identities.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.demo_model import DemoModel
from agent_factory.execution_bindings import AdapterRegistration
from agent_factory.usage_ledger import PricingRevision
from pg_fixture import IsolatedPostgres
from test_oidc_identity import ISSUER, RSAFixture


@dataclass
class OIDCLocalFixtureModel(DemoModel):
    id: str = "oidc-native-local-fixture-v1"
    provider: str = "oidc-local-fixture"


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class OIDCIdentityPostgresTests(RSAFixture, unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        workspace = TemporaryDirectory(prefix="factory-oidc-synthetic-")
        self.addCleanup(workspace.cleanup)
        settings = Settings(
            db_url=database.url, workspace=Path(workspace.name), demo=False,
            jwt_key="synthetic-oidc-native-signing-key-at-least-32-bytes",
            oidc_identity=self.config(subject_owners={
                (ISSUER, "subject-123"): "alice", (ISSUER, "subject-bob"): "bob",
                (ISSUER, "subject-unprovisioned"): "unprovisioned",
                (ISSUER, "subject-author"): "fixture-author",
                (ISSUER, "subject-reviewer"): "fixture-reviewer",
            }), runtime_adapters=[AdapterRegistration("model", "oidc-native-local-fixture-v1", "1",
                lambda _: OIDCLocalFixtureModel(), demo_only=False)],
            usage_pricing=(PricingRevision("oidc-native-local-fixture-v1", "1", "oidc-local-fixture",
                "oidc-native-local-fixture-v1", "zero-local-v1", local_model_type=OIDCLocalFixtureModel),),
            max_workers=1, storage_task_reserve_bytes=8 * 1024 * 1024,
        )
        self.app = create_app(settings)
        state = self.app.app.state.factory
        self.store, self.auth = state["store"], state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        # Production startup does not provision users. Only this fixture does so.
        self.assertIsNone(self.auth.directory.get("alice"))
        self.assertIsNone(self.auth.directory.get("manager"))
        self.auth.authorization.define_role("oidc-fixture-user", [
            "agents:factory-executor:read", "agents:factory-executor:run",
            "components:read", "registry:read", "sessions:read", "filesystem:read",
        ])
        for owner in ("alice", "bob"):
            self.auth.directory.upsert(owner, name="Synthetic " + owner)
            self.auth.authorization.assign(owner, "oidc-fixture-user")
        self.client = TestClient(self.app, base_url="https://testserver").__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def bearer(self, subject="subject-123", **claims):
        return {"Authorization": "Bearer " + self.token(self.claims(sub=subject, **claims))}

    def test_fixed_subject_mapping_missing_and_disabled_users_do_not_provision(self):
        valid = self.client.get("/api/factory/session", headers=self.bearer(
            name="Forged name", owner="bob", roles=["manager"], scopes=["agent_os:admin"]))
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json(), {"id": "alice", "name": "Synthetic alice", "role": "user"})
        for subject, owner in (("unknown-subject", "unknown-subject"),
                               ("subject-unprovisioned", "unprovisioned")):
            with self.subTest(subject=subject):
                response = self.client.get("/api/factory/session", headers=self.bearer(subject))
                self.assertEqual(response.status_code, 401, response.text)
                self.assertIsNone(self.auth.directory.get(owner))
        self.auth.directory.set_disabled("alice", True)
        denied = self.client.get("/api/factory/session", headers=self.bearer())
        self.assertEqual(denied.status_code, 401, denied.text)
        self.assertTrue(self.auth.directory.get("alice")["disabled"])
        self.assertIsNone(self.auth.directory.get("manager"))

    def test_sql_revocation_and_external_internal_token_boundary(self):
        bearer = self.bearer(scope="agent_os:admin", scopes=["agent_os:admin"], roles=["manager"])
        allowed = self.client.get("/api/factory/materials", headers=bearer)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        forbidden = self.client.post("/components", headers=bearer,
                                     json={"name": "Must not publish", "component_type": "agent"})
        self.assertEqual(forbidden.status_code, 403, forbidden.text)
        internal = self.auth._issue_native_token("alice")
        rejected = self.client.get("/api/factory/session", headers={"Authorization": "Bearer " + internal})
        self.assertEqual(rejected.status_code, 401, rejected.text)
        self.auth.authorization.unassign("alice", "oidc-fixture-user")
        self.assertEqual(self.auth.authorization.roles_of("alice"), [])
        revoked = self.client.get("/api/factory/materials", headers=bearer)
        self.assertEqual(revoked.status_code, 403, revoked.text)
        # Reusing the same verified external token cannot restore SQL grants.
        self.assertEqual(self.auth.authorization.roles_of("alice"), [])
        self.assertEqual(self.client.get("/api/factory/materials", headers=self.bearer("subject-bob")).status_code, 200)

    def test_owner_scoped_task_receipt_and_artifact_download(self):
        # Metadata-only fixture: no native run is submitted or model constructed.
        plan = self.store.save_plan({"id": str(uuid4()), "ownerId": "alice", "syntheticFixture": True})
        request_id = "oidc-fixture-" + str(uuid4())
        task, fresh = self.store.reserve_task(plan, request_id)
        self.assertTrue(fresh)
        raw = b"Public synthetic OIDC owner-isolation fixture."
        artifact = self.store.artifact_write(task["id"], "synthetic.txt", raw, "text/plain")
        receipt_url = "/api/factory/requests/" + request_id
        artifact_url = f"/api/factory/jobs/{task['id']}/artifacts/{artifact['id']}"
        alice, bob = self.bearer(), self.bearer("subject-bob")
        receipt = self.client.get(receipt_url, headers=alice)
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json()["taskId"], task["id"])
        self.assertIsNone(receipt.json()["runId"])
        download = self.client.get(artifact_url, headers=alice)
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, raw)
        self.assertEqual(download.headers["X-Content-SHA256"], hashlib.sha256(raw).hexdigest())
        for path in (receipt_url, artifact_url, f"/api/factory/jobs/{task['id']}"):
            with self.subTest(path=path):
                denied = self.client.get(path, headers=bob)
                self.assertEqual(denied.status_code, 404, denied.text)
                self.assertNotIn(raw.decode(), denied.text)
        self.assertEqual(self.store.task(task["id"])["owner_id"], "alice")
        self.assertIsNone(self.store.task(task["id"])["run_id"])

    def test_external_rsa_to_governed_native_queue_checksum_receipt_and_ledger(self):
        state = self.app.app.state.factory
        self.auth.authorization.define_role("oidc-fixture-admin", ["agent_os:admin"])
        for owner in ("fixture-author", "fixture-reviewer"):
            self.auth.directory.upsert(owner, name="Synthetic publication administrator")
            self.auth.authorization.assign(owner, "oidc-fixture-admin")
        governance, applications = state["material_governance"], state["applications"]
        refs = []
        for kind, adapter, permission in (
            ("model", "oidc-native-local-fixture-v1", []),
            ("environment", "local-bounded-environment-v1", []),
            ("tool", "native-checksum-v1", ["checksum:read"]),
        ):
            identifier = "oidc-fixture-" + kind
            item = governance.create_draft("fixture-author", {
                "id": identifier, "kind": kind, "name": "Synthetic OIDC " + kind,
                "description": "Local synthetic identity-to-native-queue acceptance only.",
                "content": "checksum" if kind == "tool" else kind,
                "license": "MIT", "compatibility": ["agno:3.1.0"], "dependencies": [],
                "permissions": permission, "runtimeBinding": {"adapterId": adapter, "revision": "1", "config": {}},
                "provenance": {"kind": "original", "notice": "Synthetic test fixture, not a production provider."},
            }, str(uuid4()))
            review = governance.request_publication("fixture-author", identifier, item["version"], str(uuid4()))
            governance.decide_publication("fixture-reviewer", review["id"], True, str(uuid4()))
            refs.append({key: item[key] for key in ("id", "version", "sha256")})
        app = applications.create_draft("fixture-author", {
            "id": "oidc-native-checksum", "name": "Synthetic OIDC checksum", "description": "Local acceptance fixture",
            "defaultMode": "checksum", "discoveryKeywords": [], "modes": {"checksum": {
                "materialRefs": refs, "capabilities": ["checksum:read"], "toolOrder": ["checksum"],
                "config": {}, "connectionRequirements": [],
                "budget": {"toolCalls": 1, "maxDepth": 1, "maxChildren": 1,
                           "experimentSeconds": 8, "outputBytes": 65536}}}}, str(uuid4()))
        review = applications.request_publication("fixture-author", app["id"], app["version"], str(uuid4()))
        applications.decide_publication("fixture-reviewer", review["id"], True, str(uuid4()))

        def post(path, body, subject="subject-123"):
            response = self.client.post("/api/factory" + path, headers=self.bearer(subject),
                                        json={"requestId": str(uuid4()), **body})
            self.assertTrue(response.is_success, response.text)
            return response.json()
        proposal = post("/compositions/proposals", {"goal": "Compute the synthetic fixture checksum",
            "mode": "checksum", "applicationRef": {key: app[key] for key in ("id", "version", "sha256")}})
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal)
        plan = post("/compositions/proposals/" + proposal["id"] + "/accept", {})
        review = post("/plan-reviews", {"planId": plan["id"]})
        post("/plan-reviews/" + review["id"] + "/decision", {"approved": True}, "subject-reviewer")
        request_id = str(uuid4())
        task = post("/instances", {"planId": plan["id"], "requestId": request_id})
        deadline = time.monotonic() + 30
        detail = {}
        while time.monotonic() < deadline:
            response = self.client.get("/api/factory/jobs/" + task["id"], headers=self.bearer())
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail["job"]["status"] in {"completed", "failed", "unknown", "canceled"}:
                break
            time.sleep(.05)
        self.assertEqual(detail["job"]["status"], "completed", detail)
        persisted = self.store.task(task["id"])
        self.assertIsNotNone(persisted["run_id"])
        native = self.store.native_db.get_job(persisted["run_id"])
        self.assertEqual(native["status"], "completed")
        self.assertEqual(persisted["owner_id"], "alice")
        receipt = self.client.get("/api/factory/requests/" + request_id, headers=self.bearer())
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json()["runId"], persisted["run_id"])
        self.assertEqual(len(detail["artifacts"]), 1, detail)
        artifact = detail["artifacts"][0]
        path = f"/api/factory/jobs/{task['id']}/artifacts/{artifact['id']}"
        download = self.client.get(path, headers=self.bearer())
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(hashlib.sha256(download.content).hexdigest(), artifact["sha256"])
        self.assertEqual(download.json()["sha256"], hashlib.sha256(plan["normalizedGoal"].encode()).hexdigest())
        self.assertEqual(artifact["provenance"]["modelAdapterId"], "oidc-native-local-fixture-v1")
        self.assertEqual(self.client.get(path, headers=self.bearer("subject-bob")).status_code, 404)
        usage = self.store.usage_ledger.inspect("alice", task["id"])
        self.assertEqual(len(usage["attempts"]), 2, usage)
        self.assertTrue(all(row["state"] == "SETTLED" for row in usage["attempts"]), usage)
        self.assertEqual(self.store.plan(plan["id"], "alice"), plan)

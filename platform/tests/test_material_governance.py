"""Inert import and exact-version governance against managed native authorization.

Portable cases use owned SQLite metadata and actual native SQL Auth. Opt-in
PostgreSQL cases use generated databases, Factory HTTP, its native executor/queue
and HITL. They make no external research/model calls or production grants.
"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import copy
import hashlib
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Column, Integer, JSON, MetaData, String, Table, create_engine, select

from agent_factory.auth import AuthService
from agent_factory.catalog import SEEDS
from agent_factory.config import Settings
from agent_factory.demo_model import DemoModel
from agent_factory.main import create_app
from agent_factory.material_governance import GovernanceConfig, MaterialGovernance, material_governance_router
from agent_factory.store import digest, now
from pg_fixture import IsolatedPostgres


def definition(kind="prompt", **changes):
    return {"kind": kind, "name": "Original controlled fixture", "content": "Compare synthetic evidence and report uncertainty.",
            "license": "MIT", "provenance": {"kind": "original", "notice": "Original synthetic test fixture."}, **changes}


def ref(material):
    return {key: material[key] for key in ("id", "version", "sha256")}


class PortableMetadata:
    """Owned metadata fixture; SQLite does not prove PostgreSQL concurrency."""
    def __init__(self, db, settings):
        self.engine, self.settings = db.db_engine, settings
        self._connection = ContextVar("governance_fixture_connection", default=None)
        metadata = MetaData()
        self.materials = Table("af_materials", metadata, Column("id", String, primary_key=True),
            Column("version", Integer, primary_key=True), Column("body", JSON), Column("published", Boolean))
        self.audit = Table("af_audit", metadata, Column("id", Integer, primary_key=True, autoincrement=True),
            Column("actor_id", String), Column("action", String), Column("target_id", String), Column("body", JSON), Column("created_at", String))
        metadata.create_all(self.engine)

    def raw(self, material):
        with self.engine.connect() as conn:
            return dict(conn.execute(select(self.materials).where(self.materials.c.id == material["id"],
                self.materials.c.version == material["version"])).mappings().one())

    def seed(self):
        with self.engine.begin() as conn:
            for mid, kind, name, content, permissions in SEEDS:
                body = {"id": mid, "version": 1, "kind": kind, "name": name, "description": content,
                    "content": content, "license": "MIT", "origin": "factory synthetic fixture", "dependencies": [],
                    "compatibility": ["agno:3.1.0", "mode:demo"], "permissions": permissions, "inputSchema": {},
                    "outputSchema": {}, "archived": False, "published": True, "createdAt": now()}
                body["sha256"] = digest({key: value for key, value in body.items() if key not in {"sha256", "published", "createdAt"}})
                conn.execute(self.materials.insert().values(id=mid, version=1, body=body, published=True))
                conn.execute(self.audit.insert().values(actor_id="demo-bootstrap", action="material.seed", target_id=mid,
                    body={"version": 1, "sha256": body["sha256"]}, created_at=now()))


class MaterialGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "owned-governance.sqlite"))
        self.settings = SimpleNamespace(demo=True, jwt_key=secrets.token_urlsafe(48))
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        # Second administrator and editor exist only in this disposable native DB.
        self.auth.authorization.unassign("bob", "factory-user")
        self.auth.authorization.assign("bob", "factory-manager")
        self.auth.authorization.define_role("fixture-editor-role", ["components:read", "components:write"])
        self.auth.directory.upsert("fixture-editor", name="Owned editor fixture")
        self.auth.authorization.assign("fixture-editor", "fixture-editor-role")
        self.store = PortableMetadata(self.db, self.settings)
        self.service = MaterialGovernance(self.store, self.auth)

    def tearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    def draft(self, **changes):
        return self.service.create_draft("manager", definition(**changes), str(uuid4()))

    def publish(self, material=None):
        material = material or self.draft()
        review = self.service.request_publication("manager", material["id"], material["version"], str(uuid4()))
        decision = self.service.decide_publication("bob", review["id"], True, str(uuid4()))
        return material, decision

    def test_default_requires_separate_current_native_admin_and_exact_digest(self):
        material = self.draft()
        original = self.store.raw(material)["body"]
        review = self.service.request_publication("manager", material["id"], 1, "review-first")
        self.assertEqual(review["sha256"], material["sha256"])
        self.assertEqual(review["immutableDigest"], self.service._immutable(original))
        self.assertTrue(review["taskApprovalSeparate"])
        for actor in ("manager", "alice", "fixture-editor"):
            with self.assertRaises(HTTPException) as denied:
                self.service.decide_publication(actor, review["id"], True, "decision-" + actor)
            self.assertEqual(denied.exception.status_code, 403)
        approved = self.service.decide_publication("bob", review["id"], True, "bob-approves")
        self.assertEqual(approved["reviewerId"], "bob")
        self.assertTrue(self.service.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        self.assertEqual(self.store.raw(material)["body"], original)
        self.assertTrue(self.store.raw(material)["published"])

    def test_import_all_six_kinds_is_inert_and_persists_provenance(self):
        values = [definition(kind=kind) for kind in ("skill", "prompt", "knowledge", "model", "environment")]
        values.append(definition(kind="tool", content="checksum", permissions=["checksum:read"]))
        values[2]["content"] = "Inert example: print('synthetic fixture'); never execute imports."
        values[0]["provenance"] = {"kind": "upstream", "source": "https://fixtures.invalid/original",
            "revision": "synthetic-pinned-v1", "notice": "MIT License. Original controlled upstream fixture; preserve this notice."}
        with patch("subprocess.Popen") as no_execution:
            result = self.service.import_definitions("manager", values, "six-kinds")
        self.assertEqual(no_execution.call_count, 0)
        self.assertEqual(len(result["materials"]), 6)
        self.assertFalse(result["executesCode"])
        self.assertFalse(any(item["published"] for item in result["materials"]))
        self.assertEqual(result["materials"][0]["provenance"], values[0]["provenance"])
        self.assertEqual(self.service.filter_active(result["materials"]), [])

    def test_schema_credentials_license_and_provenance_fail_closed_atomically(self):
        bad = [definition(apiKey="synthetic-forbidden-secret"), definition(content="ghp_" + "X" * 30),
               definition(license="unknown-license"), definition(permissions=["agent_os:admin"]),
               definition(inputSchema={"$ref": "https://fixtures.invalid/schema"}), definition(compatibility=["agno:0"]),
               definition(provenance={"kind": "upstream", "source": "https://fixtures.invalid/no-pin"}),
               definition(provenance={"kind": "upstream", "source": "https://user:secret@fixtures.invalid/", "revision": "v1", "notice": "MIT"}),
               definition(provenance={"kind": "upstream", "source": "https://[broken", "revision": "v1", "notice": "MIT"}),
               definition(content="Do not store this credential URL: https://user:synthetic@fixtures.invalid/"),
               definition(inputSchema={"ghp_" + "X" * 30: "forbidden-key"}),
               definition(outputSchema={"value": float("inf")}), definition(content="x" * 16001)]
        absent = definition()
        del absent["license"]
        bad.append(absent)
        for index, invalid in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(HTTPException) as denied:
                self.service.import_definitions("manager", [definition(), invalid], "invalid-" + str(index))
            self.assertEqual(denied.exception.status_code, 422)
        with self.store.engine.connect() as conn:
            self.assertEqual(list(conn.execute(select(self.store.materials))), [])

    def test_registered_tool_binding_and_reserved_identity_cannot_expand(self):
        for value in [definition(kind="tool", content="arbitrary_shell", permissions=["checksum:read"]),
                      definition(kind="tool", content="checksum", permissions=["experiment:synthetic"]),
                      definition(id="checksum-tool", kind="tool", content="run_experiment", permissions=["experiment:synthetic"]),
                      definition(id="checksum-tool", kind="knowledge")]:
            with self.assertRaises(HTTPException):
                self.service.create_draft("manager", value, str(uuid4()))

    def test_json_complexity_batch_and_plan_reference_bounds_are_enforced(self):
        nested = {}
        for _ in range(14):
            nested = {"nested": nested}
        for invalid in [definition(inputSchema=nested), definition(inputSchema={"many": list(range(3001))})]:
            with self.assertRaises(HTTPException):
                self.service.import_definitions("manager", [invalid], str(uuid4()))
        for values in ([], [definition()] * 31):
            with self.assertRaises(HTTPException):
                self.service.import_definitions("manager", values, str(uuid4()))
        material, _ = self.publish()
        for plan in ({}, {"materialRefs": []}, {"materialRefs": [ref(material)] * 31},
                     {"materialRefs": [{**ref(material), "version": True}]},
                     {"materialRefs": [{**ref(material), "credentials": "forbidden"}]}):
            with self.assertRaises(HTTPException):
                self.service.require_materials_current(plan)

    def test_revoked_author_or_admin_cannot_replay_persisted_commands(self):
        material = self.service.create_draft("fixture-editor", definition(id="revocation-fixture"), "editor-original")
        review = self.service.request_publication("fixture-editor", material["id"], 1, "editor-review")
        decision = self.service.decide_publication("bob", review["id"], True, "bob-original")
        self.assertEqual(decision["decision"], "approved")
        self.auth.authorization.unassign("fixture-editor", "fixture-editor-role")
        self.auth.directory.set_disabled("bob", True)
        with self.assertRaises(HTTPException):
            self.service.create_draft("fixture-editor", definition(id="revocation-fixture"), "editor-original")
        with self.assertRaises(HTTPException):
            self.service.decide_publication("bob", review["id"], True, "bob-original")
        with self.assertRaises(HTTPException):
            self.service.withdraw("bob", material["id"], 1, "revoked-withdrawal")
        self.assertTrue(self.service.require_materials_current({"materialRefs": [ref(material)]})["allowed"])

    def test_immutable_pinned_dependency_closure_and_withdrawal(self):
        dependency, _ = self.publish()
        dependent, _ = self.publish(self.draft(dependencies=[ref(dependency)]))
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(dependent)]})
        plan = {"materialRefs": [ref(dependent), ref(dependency)]}
        self.assertTrue(self.service.require_materials_current(plan)["allowed"])
        with self.assertRaises(HTTPException):
            self.draft(dependencies=[{**ref(dependency), "sha256": "0" * 64}])
        before = copy.deepcopy(self.store.raw(dependency))
        self.service.withdraw("bob", dependency["id"], 1, "withdraw-dependency", "Fixture review rescinded")
        self.assertEqual(before, self.store.raw(dependency))
        with self.assertRaises(HTTPException):
            self.service.require_materials_current(plan)
        self.assertEqual(self.service.filter_active([dependency, dependent]), [])
        with self.assertRaises(HTTPException):
            self.draft(dependencies=[ref(dependency)])

    def test_archive_and_withdraw_preserve_versions_hashes_and_history(self):
        material, decision = self.publish()
        before = self.store.raw(material)
        self.service.archive("manager", material["id"], 1, "archive-original", "Superseded fixture")
        self.assertEqual(self.store.raw(material), before)
        inspection = self.service.inspect_version("manager", material["id"], 1)
        self.assertEqual(inspection["governance"]["state"], "archived")
        self.assertEqual(self.service.inspect_review("bob", decision["id"])["sha256"], material["sha256"])
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(material)]})
        with self.assertRaises(HTTPException):
            self.service.request_publication("manager", material["id"], 1, "republish-archive")
        fresh = self.draft(id=material["id"])
        self.assertEqual(fresh["version"], 2)
        self.assertEqual(self.store.raw(material), before)

    def test_scope_author_lineage_and_current_revocation(self):
        material = self.service.create_draft("fixture-editor", definition(), "editor-draft")
        review = self.service.request_publication("fixture-editor", material["id"], 1, "editor-review")
        self.assertEqual(len(self.service.list_reviews("fixture-editor")), 1)
        for action in [lambda: self.service.inspect_review("alice", review["id"]),
                       lambda: self.service.inspect_version("alice", material["id"], 1),
                       lambda: self.service.list_reviews("fixture-editor", all_authors=True),
                       lambda: self.service.create_draft("alice", definition(), "user-draft"),
                       lambda: self.service.withdraw("fixture-editor", material["id"], 1, "editor-withdraw")]:
            with self.assertRaises(HTTPException):
                action()
        self.auth.authorization.define_role("second-editor-role", ["components:read", "components:write"])
        self.auth.directory.upsert("second-editor", name="Owned second editor")
        self.auth.authorization.assign("second-editor", "second-editor-role")
        with self.assertRaises(HTTPException):
            self.service.create_draft("second-editor", definition(id=material["id"]), "overwrite-author")
        self.auth.directory.set_disabled("bob", True)
        with self.assertRaises(HTTPException):
            self.service.decide_publication("bob", review["id"], True, "revoked-admin")
        self.assertFalse(self.store.raw(material)["published"])

    def test_semantic_keys_conflict_deduplicate_and_replay_cannot_reactivate(self):
        material = self.service.create_draft("manager", definition(id="semantic-material"), "draft-key")
        self.assertEqual(material, self.service.create_draft("manager", definition(id="semantic-material"), "draft-key"))
        with self.assertRaises(HTTPException):
            self.service.create_draft("manager", definition(id="semantic-material", name="Changed"), "draft-key")
        with self.assertRaises(HTTPException):
            self.service.archive("manager", material["id"], 1, "draft-key")
        review = self.service.request_publication("manager", material["id"], 1, "review-key")
        self.assertEqual(review, self.service.request_publication("manager", material["id"], 1, "review-key"))
        decision = self.service.decide_publication("bob", review["id"], True, "decision-key")
        self.assertEqual(decision, self.service.decide_publication("bob", review["id"], True, "decision-key"))
        with self.assertRaises(HTTPException):
            self.service.decide_publication("bob", review["id"], False, "decision-key")
        self.service.withdraw("bob", material["id"], 1, "withdraw-key")
        self.assertEqual(decision, self.service.decide_publication("bob", review["id"], True, "decision-key"))
        self.assertEqual(self.service.inspect_version("bob", material["id"], 1)["governance"]["state"], "withdrawn")
        restarted = MaterialGovernance(self.store, self.auth)
        self.assertEqual(restarted.create_draft("manager", definition(id="semantic-material"), "draft-key"), material)
        with self.assertRaises(HTTPException):
            restarted.require_materials_current({"materialRefs": [ref(material)]})

    def test_policy_revision_cannot_rebind_or_approve_stale_review(self):
        material = self.draft()
        review = self.service.request_publication("manager", material["id"], 1, "previous-policy-review")
        with self.assertRaises(ValueError):
            self.service.replace_configuration(GovernanceConfig(review_mode="demo-self-review"), expected_revision="material-governance-v1")
        config = GovernanceConfig(revision="governance-v2")
        self.service.replace_configuration(config, expected_revision="material-governance-v1")
        with self.assertRaises(HTTPException):
            self.service.decide_publication("bob", review["id"], True, "stale-decision")
        self.assertFalse(self.service.inspect_review("manager", review["id"])["currentPolicy"])
        with self.assertRaises(ValueError):
            MaterialGovernance(self.store, self.auth)
        self.assertEqual(MaterialGovernance(self.store, self.auth, config).current()["revision"], "governance-v2")

    def test_explicit_demo_compatibility_never_authorizes_production(self):
        material = self.draft()
        with self.assertRaises(HTTPException):
            self.service.publish_demo_compatibility("manager", material["id"], 1, "demo-publish")
        config = GovernanceConfig(review_mode="demo-self-review", revision="explicit-demo")
        self.service.replace_configuration(config, expected_revision="material-governance-v1")
        result = self.service.publish_demo_compatibility("manager", material["id"], 1, "demo-publish")
        self.assertTrue(result["demoCompatibility"])
        self.assertEqual(result["authorId"], result["reviewerId"])
        self.service.replace_configuration(GovernanceConfig(revision="strict-again"), expected_revision="explicit-demo")
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(material)]})
        self.settings.demo = False
        with self.assertRaises(ValueError):
            self.service.replace_configuration(config, expected_revision="strict-again")
        with self.assertRaises(ValueError):
            self.service.adopt_demo_bootstrap()

    def test_bootstrap_requires_original_seed_receipt_and_does_not_restore_withdrawn(self):
        self.store.seed()
        with self.store.engine.begin() as conn:
            conn.execute(self.store.audit.delete().where(self.store.audit.c.target_id == "checksum-tool"))
        with self.assertRaises(HTTPException):
            self.service.adopt_demo_bootstrap()
        with self.store.engine.connect() as conn:
            self.assertEqual(list(conn.execute(select(self.service.versions))), [])
            checksum = dict(conn.execute(select(self.store.materials).where(self.store.materials.c.id == "checksum-tool")).mappings().one())["body"]
        with self.store.engine.begin() as conn:
            conn.execute(self.store.audit.insert().values(actor_id="demo-bootstrap", action="material.seed", target_id="checksum-tool",
                body={"version": 1, "sha256": checksum["sha256"]}, created_at=now()))
        self.assertEqual(len(self.service.adopt_demo_bootstrap()["adopted"]), 9)
        self.service.withdraw("bob", "checksum-tool", 1, "seed-withdraw")
        self.assertEqual(MaterialGovernance(self.store, self.auth).adopt_demo_bootstrap()["adopted"], [])
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(checksum)]})

    def test_tampered_immutable_body_cannot_use_existing_review(self):
        material, _ = self.publish()
        raw = self.store.raw(material)["body"]
        altered = {**raw, "createdAt": "different immutable timestamp"}
        with self.store.engine.begin() as conn:
            conn.execute(self.store.materials.update().where(self.store.materials.c.id == material["id"]).values(body=altered))
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(material)]})
        self.assertEqual(self.service.filter_active([material]), [])

    def test_native_router_rejects_body_identity_and_untyped_decisions(self):
        native = AgentOS(id="material-router-fixture", agents=[Agent(id="factory-executor", db=self.db, model=DemoModel(), telemetry=False)],
                         db=self.db, **self.auth.agentos_kwargs(), mcp=False, scheduler=False, telemetry=False).get_app()
        native.include_router(material_governance_router(self.auth, self.service))
        with TestClient(native) as client:
            manager = {"Authorization": "Bearer " + self.auth.issue_demo_token("manager")}
            bob = {"Authorization": "Bearer " + self.auth.issue_demo_token("bob")}
            self.assertEqual(client.get("/api/factory/material-governance/policy").status_code, 401)
            body = {"definition": definition(), "requestId": "route-draft"}
            self.assertEqual(client.post("/api/factory/material-governance/drafts", json={**body, "authorId": "bob"}, headers=manager).status_code, 422)
            created = client.post("/api/factory/material-governance/drafts", json=body, headers=manager)
            self.assertEqual(created.status_code, 201, created.text)
            material = created.json()
            response = client.post("/api/factory/material-governance/reviews", json={"materialId": material["id"], "version": 1, "requestId": "route-review"}, headers=manager)
            self.assertEqual(response.status_code, 201, response.text)
            review = response.json()
            self.assertEqual(review["authorId"], "manager")
            path = "/api/factory/material-governance/reviews/" + review["id"] + "/decision"
            self.assertEqual(client.post(path, json={"approved": "yes", "requestId": "untyped"}, headers=bob).status_code, 422)
            self.assertEqual(client.post(path, json={"approved": True, "requestId": "self"}, headers=manager).status_code, 403)
            result = client.post(path, json={"approved": True, "requestId": "native-admin"}, headers=bob)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["reviewerId"], "bob")


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL acceptance")
class MaterialGovernancePostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.directory = TemporaryDirectory()
        self.app = create_app(Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1))
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.auth.authorization.unassign("bob", "factory-user")
        self.auth.authorization.assign("bob", "factory-manager")
        self.service = self.state.get("material_governance") or MaterialGovernance(self.store, self.auth)
        self.service.adopt_demo_bootstrap()
        if not self.state.get("material_governance"):
            self.app.app.include_router(material_governance_router(self.auth, self.service))
            # Explicit owned integration fixture until the root wires production.
            self.store.execution_guards["fixture-material-governance"] = lambda owner, plan, context, tool: self.service.require_materials_current(plan)
        self.client = TestClient(self.app).__enter__()
        self.login()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.engine.dispose()
        self.store.native_db.db_engine.dispose()
        self.directory.cleanup()
        self.database.__exit__(None, None, None)

    def login(self, owner="alice"):
        self.client.cookies.clear()
        response = self.client.post("/api/factory/demo/login", json={"persona": owner})
        self.assertEqual(response.status_code, 200, response.text)

    def plan(self, *, mode="literature", application="research"):
        response = self.client.post("/api/factory/plans", json={"topic": "Controlled material evidence comparison", "mode": mode,
                                    "application": application, "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def submit(self, plan):
        response = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": str(uuid4())})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def wait(self, task_id, expected):
        end = time.monotonic() + 15
        detail = {}
        while time.monotonic() < end:
            response = self.client.get("/api/factory/jobs/" + task_id)
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail["job"]["status"] in expected:
                return detail
            time.sleep(.03)
        self.fail(str(detail))

    def test_actual_checksum_evidence_survives_withdrawal_and_new_admission_denied(self):
        plan = self.plan(application="checksum")
        job = self.submit(plan)
        detail = self.wait(job["id"], {"completed", "failed"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        artifact = detail["artifacts"][0]
        path = f'/api/factory/jobs/{job["id"]}/artifacts/{artifact["id"]}'
        before = self.client.get(path).content
        self.assertEqual(hashlib.sha256(before).hexdigest(), artifact["sha256"])
        stored_plan = self.store.plan(plan["id"], "alice")
        self.service.withdraw("manager", "checksum-tool", 1, "withdraw-completed-tool", "Owned fixture withdrawal")
        rejected = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": str(uuid4())})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], 1)
        self.assertEqual(self.store.plan(plan["id"], "alice"), stored_plan)
        self.assertEqual(self.client.get(path).content, before)
        self.assertEqual(self.client.get("/api/factory/jobs/" + job["id"]).json()["artifacts"], detail["artifacts"])

    def test_native_hitl_resume_rechecks_current_material_before_compute(self):
        plan = self.plan(mode="experiment")
        job = self.submit(plan)
        baseline = self.wait(job["id"], {"waiting_approval", "failed"})
        self.assertEqual(baseline["job"]["status"], "waiting_approval", baseline)
        self.service.withdraw("manager", "experiment-tool", 1, "withdraw-paused-experiment")
        approval = baseline["job"]["approvalDetail"]
        with patch("subprocess.Popen") as no_compute:
            result = self.client.post("/api/factory/jobs/" + job["id"] + "/approve", json={"requirementId": approval["id"], "version": approval["version"], "approved": True})
            # Current withdrawal can be observed before HTTP continuation;
            # either an already-stopped 409 or denied native continuation has
            # zero compute/effect/artifact changes.
            self.assertIn(result.status_code, {200, 409}, result.text)
            stopped = self.wait(job["id"], {"failed", "unknown"})
            self.assertEqual(no_compute.call_count, 0)
        self.assertEqual(stopped["artifacts"], baseline["artifacts"])
        self.assertEqual(stopped["snapshot"]["effects"], baseline["snapshot"]["effects"])
        evidence = {"artifact", "compute_started", "compute_stopped", "compute_cancelled", "experiment_completed"}
        self.assertEqual([event for event in stopped["events"] if event["type"] in evidence],
                         [event for event in baseline["events"] if event["type"] in evidence])

    def test_postgres_concurrent_semantic_commands_and_restart_use_one_connection(self):
        original = self.store.engine
        bounded = create_engine(self.database.url, pool_size=1, max_overflow=0, pool_timeout=2)
        self.store.engine = bounded
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.service.create_draft("manager", definition(id="concurrent-governance"), "same-draft"), range(2)))
            self.assertEqual(results[0], results[1])
            material = results[0]
            with ThreadPoolExecutor(max_workers=2) as pool:
                reviews = list(pool.map(lambda _: self.service.request_publication("manager", material["id"], 1, "same-review"), range(2)))
            self.assertEqual(reviews[0], reviews[1])
            with ThreadPoolExecutor(max_workers=2) as pool:
                decisions = list(pool.map(lambda _: self.service.decide_publication("bob", reviews[0]["id"], True, "same-decision"), range(2)))
            self.assertEqual(decisions[0], decisions[1])
            current = self.service.current()
            restarted = MaterialGovernance(self.store, self.auth, GovernanceConfig(review_mode=current["review_mode"], revision=current["revision"]))
            self.assertEqual(restarted.create_draft("manager", definition(id="concurrent-governance"), "same-draft"), material)
            self.assertTrue(restarted.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        finally:
            self.store.engine = original
            bounded.dispose()
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_materials WHERE id='concurrent-governance'")[0]["n"], 1)
        self.assertEqual(len(self.service.list_reviews("manager")), 1)

    def test_postgres_http_import_publication_archive_preserves_original_body(self):
        self.login("manager")
        response = self.client.post("/api/factory/material-governance/imports", json={"definitions": [definition(id="http-import")], "requestId": "http-import"})
        self.assertEqual(response.status_code, 201, response.text)
        material = response.json()["materials"][0]
        before = self.store.sql("SELECT body FROM af_materials WHERE id='http-import' AND version=1")[0]["body"]
        review = self.client.post("/api/factory/material-governance/reviews", json={"materialId": material["id"], "version": 1, "requestId": "http-review"})
        self.assertEqual(review.status_code, 201, review.text)
        self.login("bob")
        decision = self.client.post("/api/factory/material-governance/reviews/" + review.json()["id"] + "/decision", json={"approved": True, "requestId": "http-decision"})
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertEqual(decision.json()["reviewerId"], "bob")
        self.login("manager")
        archived = self.client.post("/api/factory/material-governance/versions/http-import/1/archive", json={"requestId": "http-archive", "reason": "Superseded fixture"})
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(self.store.sql("SELECT body FROM af_materials WHERE id='http-import' AND version=1")[0]["body"], before)
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(material)]})
        inspection = self.client.get("/api/factory/material-governance/versions/http-import/1")
        self.assertEqual(inspection.status_code, 200, inspection.text)
        self.assertEqual(inspection.json()["governance"]["state"], "archived")


if __name__ == "__main__":
    unittest.main()

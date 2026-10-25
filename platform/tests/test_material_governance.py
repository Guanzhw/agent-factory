"""Inert import and exact-version governance against managed native authorization.

Portable cases use owned SQLite metadata and actual native SQL Auth. Opt-in
PostgreSQL cases use generated databases, Factory HTTP, its native executor/queue
and HITL. They make no external research/model calls or production grants.
"""
from fixture_auth import authorize_client
from fixture_auth import initialize_members
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
from core_native_fixture import SEEDS
from fixture_settings import Settings
from core_native_fixture import FixtureModel as DemoModel
from core_native_fixture import fixture_bindings as default_bindings
from core_native_fixture import create_fixture_app as create_app
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
    def test_outer_rollback_owns_material_publication_and_original_receipts(self):
        with self.assertRaisesRegex(RuntimeError, 'composite publication failed'):
            with self.store.engine.begin() as conn:
                token = self.store._connection.set(conn)
                try:
                    material = self.service.create_draft('alice', definition(id='outer-owned'), 'outer:draft')
                    self.service.publish('alice', material['id'], material['version'], 'outer:publish')
                    raise RuntimeError('composite publication failed')
                finally:
                    self.store._connection.reset(token)
        with self.store.engine.connect() as conn:
            self.assertIsNone(conn.execute(select(self.store.materials.c.id).where(
                self.store.materials.c.id == 'outer-owned')).first())
            self.assertIsNone(conn.execute(select(self.service.commands.c.request_id).where(
                self.service.commands.c.actor_id == 'alice',
                self.service.commands.c.request_id.in_(['outer:draft', 'outer:publish']))).first())
        self.assertIsNone(self.store._connection.get())
        material = self.service.create_draft('alice', definition(id='outer-owned'), 'outer:draft')
        published = self.service.publish('alice', material['id'], material['version'], 'outer:publish')
        self.assertEqual(material['version'], 1)
        self.assertTrue(published['published'])
        self.assertEqual(self.service.create_draft('alice', definition(id='outer-owned'), 'outer:draft'), material)
        self.assertIsNone(self.store._connection.get())

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "owned-governance.sqlite"))
        self.settings = SimpleNamespace(jwt_key=secrets.token_urlsafe(48))
        self.auth = AuthService(self.settings, self.db)
        initialize_members(self.auth)
        # Second administrator and editor exist only in this disposable native DB.
        self.auth.account_roles.unassign("bob", "factory-user")
        self.auth.account_roles.assign("bob", "factory-manager")
        self.auth.directory.upsert("fixture-editor", name="Owned editor fixture")
        self.store = PortableMetadata(self.db, self.settings)
        self.store.execution_bindings = default_bindings(self.settings, self.store)
        self.service = MaterialGovernance(self.store, self.auth, GovernanceConfig(
            review_mode="member-self-service", revision="material-governance-v1"))

    def tearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    def draft(self, **changes):
        return self.service.create_draft("manager", definition(**changes), str(uuid4()))

    def publish(self, material=None):
        material = material or self.draft()
        published = self.service.publish("manager", material["id"], material["version"], str(uuid4()))
        return material, published

    def historical_review(self, material):
        row = {"id": str(uuid4()), "material_id": material["id"], "version": material["version"],
               "author_id": "manager", "material_sha": material["sha256"],
               "immutable_digest": self.service._immutable(material), "policy_revision": "material-governance-v1",
               "policy_hash": self.service.current()["fingerprint"], "requested_by": "manager",
               "created_at": now(), "decision": "pending"}
        with self.store.engine.begin() as conn:
            conn.execute(self.service.reviews.insert().values(**row))
        return row


    def test_member_publication_preserves_exact_digest_and_has_no_review_execution(self):
        material = self.service.create_draft("alice", definition(), "member-draft")
        original = self.store.raw(material)["body"]
        published = self.service.publish("alice", material["id"], 1, "member-publish")
        self.assertEqual(published["sha256"], material["sha256"])
        self.assertTrue(self.service.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        self.assertEqual(self.store.raw(material)["body"], original)
        for actor in ("alice", "manager", "bob"):
            with self.subTest(actor=actor):
                for action in (lambda: self.service.request_publication(actor, material["id"], 1, "review"),
                               lambda: self.service.decide_publication(actor, "historical", True, "decision")):
                    with self.assertRaises(HTTPException) as retired:
                        action()
                    self.assertEqual(retired.exception.status_code, 410)
        self.assertEqual(self.service.list_reviews("alice"), [])


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

    def test_member_registered_tools_publish_without_operator_policy_registration(self):
        registry = self.store.execution_bindings
        registry.register("tool", "personal-tool-command", "1", lambda _: None,
                          tool_name="owned_member_tool", permissions=("member:owned-tool",))
        material = self.service.create_draft("alice", definition(kind="tool", content="owned_member_tool",
            permissions=["member:owned-tool"], runtimeBinding={"adapterId": "personal-tool-command", "revision": "1", "config": {}}), "dynamic-draft")
        self.service.publish("alice", material["id"], 1, "dynamic-publish")
        self.assertTrue(self.service.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        registry.withdraw("tool", "personal-tool-command", "1")
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(material)]})

    def test_historical_configuration_never_blocks_startup_or_overrides_current_contract(self):
        material, _ = self.publish()
        legacy = {"review_mode": "separate-admin", "revision": "legacy-authority", "tool_contract": "legacy-v1"}
        with self.store.engine.begin() as conn:
            conn.execute(self.service.configs.insert().values(revision="legacy-authority", hash="original-legacy-hash", body=legacy))
            conn.execute(self.service.current_config.insert().values(id="current", revision="legacy-authority"))
        restarted = MaterialGovernance(self.store, self.auth, GovernanceConfig())
        self.assertEqual(restarted.current()["review_mode"], "member-self-service")
        self.assertTrue(restarted.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        with self.store.engine.connect() as conn:
            saved = conn.execute(select(restarted.configs)).mappings().one()
            self.assertEqual(saved["body"], legacy)
            self.assertEqual(saved["hash"], "original-legacy-hash")
            self.assertEqual(conn.execute(select(restarted.current_config.c.revision)).scalar_one(), "legacy-authority")

    def test_registered_tool_permissions_and_material_owner_cannot_expand(self):
        for value in [definition(kind="tool", content="arbitrary_shell", permissions=["checksum:read"]),
                      definition(kind="tool", content="checksum", permissions=["fixture:operate"])]:
            with self.assertRaises(HTTPException):
                self.service.create_draft("manager", value, str(uuid4()))
        material, _ = self.publish(self.draft(id="fixture-checksum-tool", kind="knowledge"))
        original = self.service.inspect_version("manager", material["id"], 1)
        revised = definition(id=material["id"], kind="prompt")
        with self.assertRaises(HTTPException) as denied:
            self.service.create_draft("alice", revised, "not-my-material")
        self.assertEqual(denied.exception.status_code, 403)
        next_version = self.service.create_draft("manager", revised, "my-material-revision")
        self.assertEqual(next_version["version"], 2)
        self.assertEqual(self.service.inspect_version("manager", material["id"], 1), original)

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

    def test_revoked_member_cannot_replay_persisted_commands(self):
        material = self.service.create_draft("fixture-editor", definition(id="revocation-fixture"), "editor-original")
        self.service.publish("fixture-editor", material["id"], 1, "publish-original")
        self.auth.directory.set_disabled("fixture-editor", True)
        for action in (lambda: self.service.create_draft("fixture-editor", definition(id="revocation-fixture"), "editor-original"),
                       lambda: self.service.publish("fixture-editor", material["id"], 1, "publish-original"),
                       lambda: self.service.withdraw("fixture-editor", material["id"], 1, "withdraw")):
            with self.assertRaises(HTTPException):
                action()
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
        self.service.withdraw("manager", dependency["id"], 1, "withdraw-dependency", "Fixture review rescinded")
        self.assertEqual(before, self.store.raw(dependency))
        with self.assertRaises(HTTPException):
            self.service.require_materials_current(plan)
        self.assertEqual(self.service.filter_active([dependency, dependent]), [])
        with self.assertRaises(HTTPException):
            self.draft(dependencies=[ref(dependency)])

    def test_archive_and_withdraw_preserve_versions_hashes_and_history(self):
        material, _ = self.publish()
        review = self.historical_review(material)
        before = self.store.raw(material)
        self.service.archive("manager", material["id"], 1, "archive-original", "Superseded fixture")
        self.assertEqual(self.store.raw(material), before)
        inspection = self.service.inspect_version("manager", material["id"], 1)
        self.assertEqual(inspection["governance"]["state"], "archived")
        self.assertEqual(self.service.inspect_review("manager", review["id"])["sha256"], material["sha256"])
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(material)]})
        with self.assertRaises(HTTPException):
            self.service.request_publication("manager", material["id"], 1, "republish-archive")
        fresh = self.draft(id=material["id"])
        self.assertEqual(fresh["version"], 2)
        self.assertEqual(self.store.raw(material), before)

    def test_owner_scope_has_no_administrator_override_for_drafts_or_shared_versions(self):
        material = self.service.create_draft("alice", definition(), "member-draft")
        for actor in ("manager", "bob"):
            with self.assertRaises(HTTPException):
                self.service.inspect_version(actor, material["id"], 1)
        self.service.publish("alice", material["id"], 1, "publish")
        for actor in ("manager", "bob"):
            self.assertEqual(self.service.inspect_version(actor, material["id"], 1)["material"]["sha256"], material["sha256"])
            for action in (lambda: self.service.create_draft(actor, definition(id=material["id"]), "takeover"),
                           lambda: self.service.publish(actor, material["id"], 1, "republish"),
                           lambda: self.service.withdraw(actor, material["id"], 1, "withdraw"),
                           lambda: self.service.archive(actor, material["id"], 1, "archive")):
                with self.assertRaises(HTTPException):
                    action()
        copied = self.service.create_draft("bob", definition(), "copy-public-material")
        self.assertNotEqual(copied["id"], material["id"])
        self.assertEqual(self.service.inspect_version("bob", copied["id"], 1)["governance"]["author_id"], "bob")
        self.service.publish("bob", copied["id"], 1, "publish-copy")
        self.assertEqual(self.service.inspect_version("alice", material["id"], 1)["material"]["sha256"], material["sha256"])
        revised = self.service.create_draft("alice", definition(id=material["id"]), "revision")
        self.assertEqual(revised["version"], 2)
        self.service.withdraw("alice", material["id"], 1, "owner-withdraw")
        self.service.archive("alice", material["id"], 1, "owner-archive")


    def test_semantic_keys_conflict_deduplicate_and_replay_cannot_reactivate(self):
        material = self.service.create_draft("manager", definition(id="semantic-material"), "draft-key")
        self.assertEqual(material, self.service.create_draft("manager", definition(id="semantic-material"), "draft-key"))
        with self.assertRaises(HTTPException):
            self.service.create_draft("manager", definition(id="semantic-material", name="Changed"), "draft-key")
        with self.assertRaises(HTTPException):
            self.service.archive("manager", material["id"], 1, "draft-key")
        published = self.service.publish("manager", material["id"], 1, "publish-key")
        self.assertEqual(published, self.service.publish("manager", material["id"], 1, "publish-key"))
        self.service.withdraw("manager", material["id"], 1, "withdraw-key")
        self.assertEqual(published, self.service.publish("manager", material["id"], 1, "publish-key"))
        self.assertEqual(self.service.inspect_version("manager", material["id"], 1)["governance"]["state"], "withdrawn")
        restarted = MaterialGovernance(self.store, self.auth, GovernanceConfig(review_mode="member-self-service", revision="material-governance-v1"))
        self.assertEqual(restarted.create_draft("manager", definition(id="semantic-material"), "draft-key"), material)
        with self.assertRaises(HTTPException):
            restarted.require_materials_current({"materialRefs": [ref(material)]})


    def test_policy_revision_preserves_read_only_history_and_current_publication(self):
        material = self.draft()
        review = self.historical_review(material)
        self.service.publish("manager", material["id"], 1, "publish")
        with self.assertRaises(ValueError):
            self.service.replace_configuration(GovernanceConfig(review_mode="demo-self-review", revision="material-governance-v1"), expected_revision="material-governance-v1")
        config = GovernanceConfig(review_mode="member-self-service", revision="governance-v2")
        self.service.replace_configuration(config, expected_revision="material-governance-v1")
        self.assertFalse(self.service.inspect_review("manager", review["id"])["currentPolicy"])
        self.assertTrue(self.service.inspect_review("manager", review["id"])["readOnly"])
        self.assertEqual(self.service.list_reviews("bob", all_authors=True), [])
        self.assertTrue(self.service.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        restarted = MaterialGovernance(self.store, self.auth, GovernanceConfig(review_mode="member-self-service", revision="material-governance-v1"))
        self.assertEqual(restarted.current()["revision"], "material-governance-v1")
        self.assertEqual(MaterialGovernance(self.store, self.auth, config).current()["revision"], "governance-v2")


    def test_review_modes_are_removed_and_direct_publication_works_in_production(self):
        material = self.draft()
        for mode in ("separate-admin", "demo-self-review"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                GovernanceConfig(review_mode=mode, revision="retired-mode")
        self.assertFalse(hasattr(self.service, "publish_demo_compatibility"))
        self.service.publish("manager", material["id"], 1, "publish-in-production")
        self.assertTrue(self.service.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        self.assertFalse(hasattr(self.service, "adopt_demo_bootstrap"))

    def test_historical_bootstrap_remains_unadopted_and_cannot_execute(self):
        self.store.seed()
        before = [self.store.raw({'id': seed[0], 'version': 1})['body'] for seed in SEEDS]
        restarted = MaterialGovernance(self.store, self.auth, GovernanceConfig())
        self.assertFalse(hasattr(restarted, 'adopt_demo_bootstrap'))
        with self.assertRaises(HTTPException):
            restarted.require_materials_current({'materialRefs': [ref(before[0])]})
        self.assertEqual([self.store.raw({'id': seed[0], 'version': 1})['body'] for seed in SEEDS], before)
        with self.store.engine.connect() as conn:
            self.assertEqual(list(conn.execute(select(self.service.versions))), [])

    def test_tampered_immutable_body_cannot_use_existing_review(self):
        material, _ = self.publish()
        raw = self.store.raw(material)["body"]
        altered = {**raw, "createdAt": "different immutable timestamp"}
        with self.store.engine.begin() as conn:
            conn.execute(self.store.materials.update().where(self.store.materials.c.id == material["id"]).values(body=altered))
        with self.assertRaises(HTTPException):
            self.service.require_materials_current({"materialRefs": [ref(material)]})
        self.assertEqual(self.service.filter_active([material]), [])

    def test_native_router_rejects_body_identity_and_retired_review_actions(self):
        native = AgentOS(id="material-router-fixture", agents=[Agent(id="factory-executor", db=self.db, model=DemoModel(), telemetry=False)],
                         db=self.db, **self.auth.agentos_kwargs(), mcp=False, scheduler=False, telemetry=False).get_app()
        native.include_router(material_governance_router(self.auth, self.service))
        with TestClient(native, base_url="https://testserver") as client:
            alice = {"Authorization": "Bearer " + self.auth._issue_native_token("alice")}
            manager = {"Authorization": "Bearer " + self.auth._issue_native_token("manager")}
            prefix = "/api/factory/material-governance"
            self.assertEqual(client.get(prefix + "/policy").status_code, 401)
            body = {"definition": definition(), "requestId": "route-draft"}
            self.assertEqual(client.post(prefix + "/drafts", json={**body, "authorId": "manager"}, headers=alice).status_code, 422)
            created = client.post(prefix + "/drafts", json=body, headers=alice)
            self.assertEqual(created.status_code, 201, created.text)
            material = created.json()
            retired = client.post(prefix + "/reviews", json={"materialId": material["id"], "version": 1, "requestId": "old-review"}, headers=alice)
            self.assertEqual(retired.status_code, 410, retired.text)
            path = prefix + "/reviews/historical/decision"
            self.assertEqual(client.post(path, json={"approved": "yes", "requestId": "untyped"}, headers=manager).status_code, 422)
            self.assertEqual(client.post(path, json={"approved": True, "requestId": "old-decision"}, headers=manager).status_code, 410)
            result = client.post(prefix + f'/versions/{material["id"]}/1/publish', json={"requestId": "publish"}, headers=alice)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json()["published"])
            for action in ("publish", "archive", "withdraw"):
                denied = client.post(prefix + f'/versions/{material["id"]}/1/' + action, json={"requestId": "admin-" + action}, headers=manager)
                self.assertEqual(denied.status_code, 404, denied.text)



@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL acceptance")
class MaterialGovernancePostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.directory = TemporaryDirectory()
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1,
            material_review_mode="member-self-service", material_policy_revision="material-governance-v1")
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.auth.account_roles.unassign("bob", "factory-user")
        self.auth.account_roles.assign("bob", "factory-manager")
        self.service = self.state.get("material_governance") or MaterialGovernance(self.store, self.auth, GovernanceConfig(review_mode="member-self-service", revision="material-governance-v1"))
        # This disposable fixture explicitly gives the test member ownership.
        with self.store.engine.begin() as conn:
            conn.execute(self.service.versions.update().values(author_id="manager"))
        if not self.state.get("material_governance"):
            self.app.app.include_router(material_governance_router(self.auth, self.service))
            # Explicit owned integration fixture until the root wires production.
            self.store.execution_guards["fixture-material-governance"] = lambda owner, plan, context, tool: self.service.require_materials_current(plan)
        self.client = TestClient(self.app, base_url="https://testserver").__enter__()
        self.login()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.engine.dispose()
        self.store.native_db.db_engine.dispose()
        self.directory.cleanup()
        self.database.__exit__(None, None, None)

    def login(self, owner="alice"):
        self.client.cookies.clear()
        response = authorize_client(self.client, owner)
        self.assertEqual(response.status_code, 200, response.text)

    def plan(self, *, mode="literature", application="fixture-text"):
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
        plan = self.plan(application="fixture-checksum")
        job = self.submit(plan)
        detail = self.wait(job["id"], {"completed", "failed"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        artifact = detail["artifacts"][0]
        path = f'/api/factory/jobs/{job["id"]}/artifacts/{artifact["id"]}'
        before = self.client.get(path).content
        self.assertEqual(hashlib.sha256(before).hexdigest(), artifact["sha256"])
        stored_plan = self.store.plan(plan["id"], "alice")
        self.service.withdraw("manager", "fixture-checksum-tool", 1, "withdraw-completed-tool", "Owned fixture withdrawal")
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
        self.service.withdraw("manager", "fixture-operation-tool", 1, "withdraw-paused-experiment")
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
        evidence = {"artifact", "operation_started", "operation_stopped", "operation_cancelled", "operation_completed"}
        self.assertEqual([event for event in stopped["events"] if event["type"] in evidence],
                         [event for event in baseline["events"] if event["type"] in evidence])

    def test_old_configuration_and_reviews_survive_actual_restart_and_member_publication(self):
        material = self.service.create_draft("alice", definition(id="historical-member-material"), "old-material-draft")
        self.service.publish("alice", material["id"], 1, "old-material-publish")
        applications = self.state["applications"]
        source = applications.list_active("alice")[0]
        app_definition = {key: value for key, value in source.items()
                          if key not in {"id", "version", "createdAt", "schema", "origin", "sha256"}}
        app = applications.create_draft("alice", {**app_definition, "id": "historical-member-app"}, "old-app-draft")
        applications.publish("alice", app["id"], 1, "old-app-publish")
        legacy_config = {"review_mode": "separate-admin", "revision": "old-separate-review",
                         "tool_contract": "legacy-v1"}
        review = {"id": "old-material-review", "material_id": material["id"], "version": 1,
                  "author_id": "alice", "material_sha": material["sha256"],
                  "immutable_digest": self.service._immutable(material), "policy_revision": legacy_config["revision"],
                  "policy_hash": "old-material-policy-hash", "requested_by": "alice", "created_at": now(),
                  "decision": "approved", "reviewer_id": "manager", "decided_at": now()}
        app_review = {"id": "old-application-review", "application_id": app["id"], "version": 1,
                      "author_id": "alice", "sha": app["sha256"], "policy_hash": "old-application-policy-hash",
                      "decision": "approved", "reviewer_id": "manager", "created_at": now(), "decided_at": now()}
        with self.store.engine.begin() as conn:
            conn.execute(self.service.configs.insert().values(revision=legacy_config["revision"], hash="original-old-hash", body=legacy_config))
            conn.execute(self.service.current_config.insert().values(id="current", revision=legacy_config["revision"]))
            conn.execute(self.service.reviews.insert().values(**review))
            conn.execute(self.service.versions.update().where(self.service.versions.c.material_id == material["id"]).values(review_id=review["id"]))
            conn.execute(applications.reviews.insert().values(**app_review))
            conn.execute(applications.states.update().where(applications.states.c.id == app["id"]).values(review_id=app_review["id"]))
            original_config = dict(conn.execute(select(self.service.configs)).mappings().one())
            original_review = dict(conn.execute(select(self.service.reviews)).mappings().one())
            original_app_review = dict(conn.execute(select(applications.reviews)).mappings().one())
        self.client.__exit__(None, None, None)
        self.store.engine.dispose()
        self.store.native_db.db_engine.dispose()
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.service = self.state["material_governance"]
        applications = self.state["applications"]
        self.client = TestClient(self.app, base_url="https://testserver").__enter__()
        self.login("alice")
        material_path = "/api/factory/material-governance"
        self.assertEqual(self.client.get(material_path + "/reviews/old-material-review").json()["decision"], "approved")
        self.assertTrue(self.client.get("/api/factory/applications/reviews/old-application-review").json()["readOnly"])
        self.assertTrue(self.service.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        self.assertEqual(applications.require_current(ref(app)), app)
        self.assertEqual(self.client.post(material_path + "/reviews", json={"materialId": material["id"], "version": 1, "requestId": "retired-request"}).status_code, 410)
        self.assertEqual(self.client.post(material_path + "/reviews/old-material-review/decision", json={"approved": True, "requestId": "retired-decision"}).status_code, 410)
        self.assertEqual(self.client.post(f'/api/factory/applications/{app["id"]}/versions/1/review', json={"requestId": "retired-app-request"}).status_code, 410)
        self.assertEqual(self.client.post("/api/factory/applications/reviews/old-application-review/decision", json={"approved": True, "requestId": "retired-app-decision"}).status_code, 410)
        fresh = self.client.post(material_path + "/drafts", json={"definition": definition(), "requestId": "new-member-material"})
        self.assertEqual(fresh.status_code, 201, fresh.text)
        published = self.client.post(f'{material_path}/versions/{fresh.json()["id"]}/1/publish', json={"requestId": "new-material-publish"})
        self.assertEqual(published.status_code, 200, published.text)
        revised = self.client.post(f'/api/factory/applications/{app["id"]}/versions/1/revise', json={"definition": {**app_definition, "id": app["id"]}, "requestId": "new-member-app"})
        self.assertEqual(revised.status_code, 201, revised.text)
        published_app = self.client.post(f'/api/factory/applications/{app["id"]}/versions/{revised.json()["version"]}/publish', json={"requestId": "new-app-publish"})
        self.assertEqual(published_app.status_code, 200, published_app.text)
        self.login("manager")
        self.assertEqual(self.client.get(material_path + "/reviews/old-material-review").status_code, 404)
        self.assertEqual(self.client.get("/api/factory/applications/reviews/old-application-review").status_code, 404)
        self.assertEqual(self.client.get(material_path + "/reviews?allAuthors=true").json(), [])
        self.assertEqual(self.client.get("/api/factory/applications/reviews?allAuthors=true").json(), [])
        with self.store.engine.connect() as conn:
            self.assertEqual(dict(conn.execute(select(self.service.configs)).mappings().one()), original_config)
            self.assertEqual(dict(conn.execute(select(self.service.reviews)).mappings().one()), original_review)
            self.assertEqual(dict(conn.execute(select(applications.reviews)).mappings().one()), original_app_review)
            self.assertEqual(conn.execute(select(self.service.current_config.c.revision)).scalar_one(), legacy_config["revision"])
        self.assertEqual(self.service.inspect_version("alice", material["id"], 1)["material"]["sha256"], material["sha256"])
        self.assertEqual(applications.inspect("alice", app["id"], 1)["application"], app)

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
                publications = list(pool.map(lambda _: self.service.publish("manager", material["id"], 1, "same-publish"), range(2)))
            self.assertEqual(publications[0], publications[1])
            current = self.service.current()
            restarted = MaterialGovernance(self.store, self.auth, GovernanceConfig(review_mode=current["review_mode"], revision=current["revision"]))
            self.assertEqual(restarted.create_draft("manager", definition(id="concurrent-governance"), "same-draft"), material)
            self.assertTrue(restarted.require_materials_current({"materialRefs": [ref(material)]})["allowed"])
        finally:
            self.store.engine = original
            bounded.dispose()
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_materials WHERE id='concurrent-governance'")[0]["n"], 1)
        self.assertEqual(len(self.service.list_reviews("manager")), 0)

    def test_postgres_http_import_publication_archive_preserves_original_body(self):
        self.login("manager")
        response = self.client.post("/api/factory/material-governance/imports", json={"definitions": [definition(id="http-import")], "requestId": "http-import"})
        self.assertEqual(response.status_code, 201, response.text)
        material = response.json()["materials"][0]
        before = self.store.sql("SELECT body FROM af_materials WHERE id='http-import' AND version=1")[0]["body"]
        publication = self.client.post("/api/factory/material-governance/versions/http-import/1/publish", json={"requestId": "http-publish"})
        self.assertEqual(publication.status_code, 200, publication.text)
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

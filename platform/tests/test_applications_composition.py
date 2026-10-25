"""Governed configuration/composition tests with actual native managed Auth.

Portable cases use owned SQLite metadata (not queue/concurrency evidence).
Opt-in PostgreSQL cases use the wired Factory HTTP/native executor and generated
databases. All identities, models, materials and execution are synthetic fixtures.
"""
from fixture_auth import authorize_client
from fixture_auth import initialize_members
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Column, Integer, JSON, MetaData, String, Table, select

from agent_factory.applications import ApplicationService, application_router
from agent_factory.auth import AuthService
from agent_factory.catalog import create_plan
from core_native_fixture import publish_fixture_materials, publish_fixture_applications
from core_native_fixture import all_fixture_definitions as all_demo_definitions
from agent_factory.composition import CompositionService, composition_router
from agent_factory.connections import ConnectionService
from agent_factory.personal_tools import ConfigureResourceRequest, PersonalTools
from fixture_settings import Settings
from core_native_fixture import FixtureModel as DemoModel
from agent_factory.execution_bindings import AdapterRegistration
from core_native_fixture import fixture_bindings as default_bindings
from core_native_fixture import create_fixture_app as create_app
from agent_factory.material_governance import GovernanceConfig, MaterialGovernance
from agent_factory.store import digest, now
from pg_fixture import IsolatedPostgres


def pin(value):
    return {key: value[key] for key in ("id", "version", "sha256")}


def app_definition(store, identifier="synthetic-text-audit", **changes):
    seeds = {item["id"]: item for item in store.materials(published_only=True)}
    return {"id": identifier, "name": "Original synthetic text audit", "description": "Owned deterministic fixture.",
            "discoveryKeywords": ["text audit"], "modes": {"literature": {
                "materialRefs": [pin(seeds[mid]) for mid in ("fixture-model", "fixture-environment", "fixture-skill", "fixture-prompt", "fixture-knowledge", "fixture-checksum-tool")],
                "capabilities": ["checksum:read"], "toolOrder": ["checksum"]}}, **changes}


class PortableCompositionStore:
    """Owned metadata with native SQL Auth; never represents a native job queue."""
    def __init__(self, db, settings):
        self.engine, self.settings = db.db_engine, settings
        self._connection = ContextVar("owned_composition_connection", default=None)
        self.material_governance = None
        metadata = MetaData()
        self.material_table = Table("af_materials", metadata, Column("id", String, primary_key=True),
            Column("version", Integer, primary_key=True), Column("body", JSON), Column("published", Boolean))
        self.audit_table = Table("af_audit", metadata, Column("id", Integer, primary_key=True, autoincrement=True),
            Column("actor_id", String), Column("action", String), Column("target_id", String), Column("body", JSON), Column("created_at", String))
        self.plan_table = Table("af_plans", metadata, Column("id", String, primary_key=True),
            Column("owner_id", String), Column("body", JSON), Column("hash", String))
        metadata.create_all(self.engine)

    def transaction(self, *, read_only=False):
        return self.connection(write=not read_only)

    @contextmanager
    def connection(self, *, write=False):
        borrowed = self._connection.get()
        if borrowed is not None:
            yield borrowed
        else:
            with (self.engine.begin() if write else self.engine.connect()) as conn:
                yield conn

    def materials(self, published_only=False):
        with self.connection() as conn:
            query = select(self.material_table)
            if published_only:
                query = query.where(self.material_table.c.published.is_(True))
            rows = conn.execute(query.order_by(self.material_table.c.id, self.material_table.c.version.desc())).mappings()
            values = [{**copy.deepcopy(row["body"]), "published": row["published"]} for row in rows]
        return self.material_governance.filter_active(values) if published_only and self.material_governance else values

    def add_material(self, body, actor, seed=False):
        with self.connection(write=True) as conn:
            body = {**body, "version": 1, "createdAt": now(), "published": seed}
            body["sha256"] = digest({key: val for key, val in body.items() if key not in {"sha256", "published", "createdAt"}})
            conn.execute(self.material_table.insert().values(id=body["id"], version=1, body=body, published=seed))
            conn.execute(self.audit_table.insert().values(actor_id=actor, action="material.seed" if seed else "material.draft",
                target_id=body["id"], body={"version": 1, "sha256": body["sha256"]}, created_at=now()))
        return body

    def save_plan(self, body):
        with self.connection(write=True) as conn:
            conn.execute(self.plan_table.insert().values(id=body["id"], owner_id=body["ownerId"], body=body, hash=digest(body)))
        return copy.deepcopy(body)

    def plan(self, identifier, owner=None):
        with self.connection() as conn:
            row = conn.execute(select(self.plan_table).where(self.plan_table.c.id == identifier)).mappings().first()
        if not row or owner is not None and row["owner_id"] != owner:
            raise HTTPException(404, "Scoped immutable plan not found")
        if digest(row["body"]) != row["hash"]:
            raise HTTPException(409, "Immutable plan integrity differs")
        return copy.deepcopy(row["body"])


class ApplicationCompositionFixture(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "owned-composition.sqlite"))
        self.addCleanup(self.db.db_engine.dispose)
        self.settings = Settings(material_review_mode="member-self-service", material_policy_revision="material-governance-v1", db_url="sqlite://", workspace=Path(self.directory.name))
        self.auth = AuthService(self.settings, self.db)
        initialize_members(self.auth)
        # Explicitly owned test subjects/roles; no production grants are touched.
        self.auth.account_roles.unassign("bob", "factory-user")
        self.auth.account_roles.assign("bob", "factory-manager")
        self.store = PortableCompositionStore(self.db, self.settings)
        self.store.material_governance = MaterialGovernance(self.store, self.auth, GovernanceConfig(
            review_mode="member-self-service", revision="material-governance-v1"))
        self.bindings = default_bindings(self.settings, self.store, None)
        self.store.execution_bindings = self.bindings
        self.applications = ApplicationService(self.store, self.auth)
        self.store.applications = self.applications
        publish_fixture_materials(self.store)
        publish_fixture_applications(self.store, all_demo_definitions)
        self.composition = CompositionService(self.store, self.auth, self.applications, self.bindings, None)
        self.store.composition = self.composition

    def publish(self, definition=None):
        application = self.applications.create_draft("manager", definition or app_definition(self.store), str(uuid4()))
        self.applications.publish("manager", application["id"], application["version"], str(uuid4()))
        return application

    def material(self, **changes):
        material = self.store.material_governance.create_draft("manager", {
            "kind": "prompt", "name": "Original alternate fixture", "content": "Alternate approved deterministic instructions.",
            "license": "MIT", "provenance": {"kind": "original", "notice": "Original synthetic fixture."}, **changes}, str(uuid4()))
        self.store.material_governance.publish("manager", material["id"], 1, str(uuid4()))
        return material


class ApplicationCompositionTests(ApplicationCompositionFixture):
    def test_member_publication_binds_exact_version_and_only_owner_can_manage_it(self):
        definition = app_definition(self.store)
        application = self.applications.create_draft("alice", definition, "member-draft")
        original = copy.deepcopy(application)
        self.applications.publish("alice", application["id"], 1, "member-publish")
        self.assertEqual(self.applications.require_current(pin(application)), original)
        self.assertEqual(self.applications.list_reviews("alice"), [])
        self.assertEqual(self.applications.inspect("manager", application["id"], 1)["application"], original)
        for actor in ("manager", "bob"):
            for action in (lambda: self.applications.publish(actor, application["id"], 1, "publish"),
                           lambda: self.applications.revise(actor, application["id"], 1, definition, "revise"),
                           lambda: self.applications.create_draft(actor, definition, "takeover"),
                           lambda: self.applications.withdraw(actor, application["id"], 1, "withdraw"),
                           lambda: self.applications.archive(actor, application["id"], 1, "archive")):
                with self.assertRaises(HTTPException):
                    action()
            for action in (lambda: self.applications.request_publication(actor, application["id"], 1, "review"),
                           lambda: self.applications.decide_publication(actor, "old-review", True, "decision")):
                with self.assertRaises(HTTPException) as retired:
                    action()
                self.assertEqual(retired.exception.status_code, 410)
        copied = self.applications.create_draft("bob", {key: value for key, value in definition.items() if key != "id"}, "copy-public-app")
        self.assertNotEqual(copied["id"], application["id"])
        self.assertEqual(self.applications.inspect("bob", copied["id"], 1)["governance"]["author_id"], "bob")
        self.applications.publish("bob", copied["id"], 1, "publish-copy")
        self.assertEqual(self.applications.require_current(pin(application)), original)
        self.applications.withdraw("alice", application["id"], 1, "owner-withdraw")
        self.applications.archive("alice", application["id"], 1, "owner-archive")
        revised = self.applications.revise("alice", application["id"], 1, definition, "owner-revise")
        self.assertEqual(revised["version"], 2)


    def test_same_named_private_member_tool_does_not_replace_builtin_material_contract(self):
        connections = ConnectionService(self.store, self.auth)
        personal = PersonalTools(connections, None, ())
        connections.personal_tools = personal
        self.store.personal_tools = personal
        self.bindings.connections = connections
        self.composition.connections = connections
        personal.register(self.bindings)
        original = self.publish()
        before = self.composition.create_plan("bob", "Checksum built-in before another member tool", "literature", application_ref=pin(original))
        resource = personal.configure_resource("alice", ConfigureResourceRequest(transport="cli", toolName="checksum",
            executable=sys.executable, arguments=["-c", "print(123)"], requestId="private-same-name"))
        # The exact built-in declaration and its application remain usable.
        self.applications.require_plan_current(before)
        unchanged = self.composition.create_plan("bob", "Checksum built-in after another member tool", "literature", application_ref=pin(original))
        self.assertEqual(unchanged["capabilities"], ["checksum:read"])
        self.assertEqual(unchanged["executionBindings"]["tools"][0]["adapterId"], "fixture-checksum-v1")
        material = self.store.material_governance.create_draft("alice", {
            "kind": "tool", "name": "Member checksum", "content": "checksum", "permissions": ["tool:invoke"],
            "runtimeBinding": {**resource["runtimeBinding"], "config": {"connectionName": "memberCommand"}}}, "same-name-tool-draft")
        self.store.material_governance.publish("alice", material["id"], 1, "same-name-tool-publish")
        definition = app_definition(self.store, identifier="member-checksum-application")
        mode = definition["modes"]["literature"]
        mode["materialRefs"] = [pin(material) if item["id"] == "fixture-checksum-tool" else item for item in mode["materialRefs"]]
        mode["capabilities"] = ["tool:invoke"]
        mode["connectionRequirements"] = [{"name": "memberCommand", "kind": "tool", "requiredCapabilities": ["tool:invoke"]}]
        application = self.applications.create_draft("alice", definition, "member-same-name-app")
        self.applications.publish("alice", application["id"], 1, "member-same-name-publish")
        connection = connections.bind("alice", resource["registrationRef"], "member-command-bind")
        selected = self.composition.create_plan("alice", "Use my exact member checksum", "literature", application_ref=pin(application),
            connection_refs={"memberCommand": connection["ref"]})
        self.assertEqual(selected["capabilities"], ["tool:invoke"])
        self.assertEqual(selected["executionBindings"]["tools"][0]["adapterId"], resource["adapterId"])
        with self.assertRaises(HTTPException):
            self.store.material_governance.create_draft("alice", {"kind": "tool", "name": "Mismatched declaration",
                "content": "checksum", "permissions": ["checksum:read"], "runtimeBinding": resource["runtimeBinding"]}, "wrong-same-name-permission")

    def test_historical_reviews_remain_owner_scoped_and_do_not_control_publication(self):
        app = self.publish()
        row = {"id": "historical-publication", "application_id": app["id"], "version": app["version"],
               "author_id": "manager", "sha": app["sha256"], "policy_hash": "old-policy",
               "decision": "pending", "created_at": now()}
        with self.store.engine.begin() as conn:
            conn.execute(self.applications.reviews.insert().values(**row))
            conn.execute(self.applications.states.update().where(self.applications.states.c.id == app["id"])
                         .values(review_id=row["id"]))
        self.assertTrue(self.applications.inspect_review("manager", row["id"])["readOnly"])
        self.assertEqual(self.applications.list_reviews("bob", all_authors=True), [])
        with self.assertRaises(HTTPException):
            self.applications.inspect_review("bob", row["id"])
        self.assertEqual(self.applications.require_current(pin(app)), app)

    def test_new_six_kind_configuration_is_discovered_without_application_branches(self):
        app = self.publish()
        with patch("subprocess.Popen") as no_process:
            proposal = self.composition.propose("alice", "Please perform a text audit on synthetic evidence", request_id="discover")
        self.assertEqual(no_process.call_count, 0)
        self.assertEqual(proposal["candidate"]["applicationRef"], pin(app))
        self.assertEqual(proposal["selection"]["matchedKeywords"], ["text audit"])
        self.assertEqual(proposal["candidate"]["tools"], ["checksum"])
        self.assertEqual(proposal["candidate"]["status"], "ready")
        self.assertEqual({material["kind"] for material in proposal["candidate"]["materials"]},
                         {"model", "environment", "skill", "prompt", "knowledge", "tool"})
        bindings = proposal["candidate"]["executionBindings"]
        self.assertEqual(bindings["tools"][0]["toolName"], "checksum")
        self.assertEqual(bindings["knowledge"][0]["materialRef"]["id"], "fixture-knowledge")
        plan = self.composition.accept("alice", proposal["id"], "accept-one")
        self.applications.require_plan_current(plan)
        self.assertEqual(self.store.plan(plan["id"], "alice"), plan)
        self.assertEqual(plan["fingerprint"], digest({k: v for k, v in plan.items() if k not in {"id", "createdAt", "fingerprint"}}))

    def test_semantic_keys_reject_changed_intent_and_accept_recovery_creates_one_plan(self):
        first = self.composition.propose("alice", "Checksum the controlled fixture", application="fixture-checksum", request_id="same")
        self.assertEqual(first, self.composition.propose("alice", "Checksum the controlled fixture", application="fixture-checksum", request_id="same"))
        with self.assertRaises(HTTPException) as conflict:
            self.composition.propose("alice", "Checksum a changed goal", application="fixture-checksum", request_id="same")
        self.assertEqual(conflict.exception.status_code, 409)
        accepted = self.composition.accept("alice", first["id"], "one-accept")
        self.assertEqual(self.composition.accept("alice", first["id"], "one-accept"), accepted)
        with self.store.connection() as conn:
            self.assertEqual(len(list(conn.execute(select(self.store.plan_table)))), 1)
        with self.assertRaises(HTTPException):
            self.composition.accept("alice", first["id"], "another-accept")
        with self.assertRaises(HTTPException) as scoped:
            self.composition.inspect("bob", first["id"])
        self.assertEqual(scoped.exception.status_code, 404)

    def test_reject_revise_receipts_and_restart_preserve_all_immutable_evidence(self):
        proposal = self.composition.propose("alice", "Checksum original", application="fixture-checksum", request_id="initial")
        self.composition.reject("alice", proposal["id"], "reject-first")
        revised = self.composition.revise("alice", proposal["id"], "Checksum revised", application="fixture-checksum", request_id="revise-first")
        self.assertEqual(self.composition.inspect("alice", proposal["id"])["state"], "revised")
        self.assertEqual(self.composition.inspect("alice", proposal["id"])["revisedBy"], revised["id"])
        self.assertEqual(revised["parentId"], proposal["id"])
        self.composition = CompositionService(self.store, self.auth, self.applications, self.bindings, None)
        self.assertEqual(revised, self.composition.revise("alice", proposal["id"], "Checksum revised", application="fixture-checksum", request_id="revise-first"))
        self.assertEqual(self.composition.inspect("alice", proposal["id"])["candidate"], proposal["candidate"])
        with self.assertRaises(HTTPException):
            self.composition.revise("alice", proposal["id"], "Changed revision", application="fixture-checksum", request_id="revise-first")

    def test_approved_variants_pin_actual_instructions_and_inherit_default_choices(self):
        alternate = self.material()
        definition = app_definition(self.store)
        mode = definition["modes"]["literature"]
        original = next(ref for ref in mode["materialRefs"] if ref["id"] == "fixture-prompt")
        mode["materialChoices"] = {"instructions": {"kind": "prompt", "defaultRef": original, "allowedRefs": [original, pin(alternate)]}}
        application = self.publish(definition)
        default = self.composition.create_plan("alice", "Text audit default selection", "literature", application_ref=pin(application))
        self.assertEqual(default["bindingManifest"]["materialChoices"], {"instructions": original})
        selected = self.composition.create_plan("alice", "Text audit alternate selection", "literature", application_ref=pin(application), material_choices={"instructions": pin(alternate)})
        self.assertIn(alternate["content"], selected["instructions"])
        self.assertNotIn(original, selected["materialRefs"])
        class ChildStore:
            def __init__(self, source, parent):
                self.ancestors, self.source, self.saved = [parent], source, None
            def save_plan(self, body):
                self.saved = body
                return self.source.save_plan(body)
        child_store = ChildStore(self.store, selected)
        child = self.composition.create_plan("alice", "Child text audit", "literature", application_ref=pin(application), plan_store=child_store)
        self.assertEqual(child["bindingManifest"]["materialChoices"], selected["bindingManifest"]["materialChoices"])
        self.assertEqual(child_store.saved["id"], child["id"])
        empty = self.composition.create_plan("alice", "Child omits selected variants", "literature", application_ref=pin(application), material_choices={}, plan_store=child_store)
        self.assertEqual(empty["bindingManifest"]["materialChoices"], selected["bindingManifest"]["materialChoices"])
        with self.assertRaises(HTTPException):
            self.composition.create_plan("alice", "Child changes pinned instruction", "literature", application_ref=pin(application), material_choices={"instructions": original}, plan_store=child_store)

    def test_missing_registered_model_and_required_connection_produce_blocked_plans(self):
        model = self.material(kind="model", content="Owned unavailable provider specification.", runtimeBinding={"adapterId": "unavailable-owned-model", "revision": "1", "config": {}})
        definition = app_definition(self.store)
        refs = definition["modes"]["literature"]["materialRefs"]
        refs[0] = pin(model)
        application = self.publish(definition)
        proposal = self.composition.propose("alice", "Text audit unavailable model", application_ref=pin(application), request_id="missing-model")
        self.assertEqual(proposal["candidate"]["status"], "blocked")
        self.assertIsNone(proposal["candidate"]["executionBindings"])
        self.assertEqual(self.composition.accept("alice", proposal["id"], "blocked-accept")["status"], "blocked")
        required = app_definition(self.store, identifier="connection-required")
        required["modes"]["literature"]["connectionRequirements"] = [{"name": "owner-model", "kind": "model", "requiredCapabilities": []}]
        published = self.publish(required)
        blocked = self.composition.propose("alice", "A controlled required connection", application_ref=pin(published), request_id="missing-connection")
        self.assertIn("Missing owner connection: owner-model", blocked["candidate"]["missing"])
        with self.assertRaises(HTTPException):
            self.composition.propose("alice", "No raw URL", connection_refs={"owner-model": "https://fixtures.invalid/credential"}, request_id="no-url")

    def test_variant_dependency_cannot_hide_transitive_capability_expansion(self):
        literature = next(item for item in self.store.materials(published_only=True) if item["id"] == "fixture-question-tool")
        alternate = self.material(dependencies=[pin(literature)])
        definition = app_definition(self.store)
        mode = definition["modes"]["literature"]
        original = next(ref for ref in mode["materialRefs"] if ref["id"] == "fixture-prompt")
        mode["materialChoices"] = {"instructions": {"kind": "prompt", "defaultRef": original, "allowedRefs": [original, pin(alternate)]}}
        with self.assertRaises(HTTPException) as denied:
            self.applications.create_draft("manager", definition, "transitive-variant-denied")
        self.assertEqual(denied.exception.status_code, 422)
        with self.store.connection() as conn:
            self.assertEqual(len(list(conn.execute(select(self.applications.versions).where(self.applications.versions.c.id == definition["id"])))), 0)

    def test_current_withdrawal_blocks_unaccepted_plan_but_never_erases_accepted_plan(self):
        application = self.publish()
        pending = self.composition.propose("alice", "Text audit pending", application_ref=pin(application), request_id="pending")
        plan = self.composition.create_plan("alice", "Text audit accepted", "literature", application_ref=pin(application))
        self.applications.withdraw("manager", application["id"], 1, "withdraw", "Owned withdrawal fixture")
        with self.assertRaises(HTTPException):
            self.composition.accept("alice", pending["id"], "deny-after-withdrawal")
        with self.assertRaises(HTTPException):
            self.applications.require_plan_current(plan)
        self.assertEqual(self.store.plan(plan["id"], "alice"), plan)
        self.assertEqual(self.applications.inspect("manager", application["id"], 1)["application"], application)
        restarted = ApplicationService(self.store, self.auth)
        publish_fixture_applications(self.store, all_demo_definitions)
        with self.assertRaises(HTTPException):
            restarted.require_current(pin(application))

    def test_archive_revise_reject_owner_scope_and_draft_semantic_conflict(self):
        definition = app_definition(self.store)
        draft = self.applications.create_draft("manager", definition, "draft")
        self.assertEqual(draft, self.applications.create_draft("manager", definition, "draft"))
        with self.assertRaises(HTTPException):
            self.applications.create_draft("manager", {**definition, "name": "Changed intent"}, "draft")
        with self.assertRaises(HTTPException) as scoped:
            self.applications.inspect("alice", draft["id"], 1)
        self.assertEqual(scoped.exception.status_code, 404)
        self.applications.archive("manager", draft["id"], 1, "archive")
        next_version = self.applications.revise("manager", draft["id"], 1, definition, "version-two")
        self.assertEqual(next_version["version"], 2)
        self.assertEqual(len([item for item in self.applications.list_definitions("manager") if item["application"]["id"] == draft["id"]]), 2)
        self.assertEqual(self.applications.inspect("manager", draft["id"], 1)["application"], draft)
        with self.assertRaises(HTTPException):
            self.applications.request_publication("manager", draft["id"], 1, "inactive-review")

    def test_forged_tools_caps_budget_anchor_config_and_current_policy_are_denied(self):
        plan = create_plan(self.store, "alice", "Checksum exact governed fixture", "literature", "fixture-checksum")
        for field, value in (("tools", ["checksum", "fixture_operation"]), ("capabilities", ["agent_os:admin"]),
                             ("budget", {**plan["budget"], "toolCalls": 9}), ("config", {**plan["config"], "experimentDurationSeconds": 600}),
                             ("bindingManifest", {**plan["bindingManifest"], "sha256": "0" * 64})):
            with self.subTest(field=field), self.assertRaises(HTTPException):
                self.applications.require_plan_current({**plan, field: value})
        self.settings.max_tool_calls = 3
        narrowed = create_plan(self.store, "alice", "Checksum current ceiling", "literature", "fixture-checksum")
        self.assertEqual(narrowed["budget"]["toolCalls"], 3)
        with self.assertRaises(HTTPException):
            self.applications.require_plan_current(plan)
        proposal = self.composition.propose("alice", "Checksum before config revocation", application="fixture-checksum", request_id="before-unset")
        self.settings.temporary_policy = "unset"
        self.assertEqual(self.composition.accept("alice", proposal["id"], "after-unset")["ownerId"], "alice")
        self.auth.directory.set_disabled("alice", True)
        with self.assertRaises(HTTPException):
            self.composition.accept("alice", proposal["id"], "after-rights-revoked")

    def test_legacy_plan_is_readable_but_never_adopted_for_execution(self):
        plan = create_plan(self.store, 'alice', 'Checksum historical fixture', 'literature', 'fixture-checksum')
        legacy = {k: v for k, v in plan.items() if k not in {'applicationRef', 'executionBindings', 'bindingManifest', 'compositionProposalId'}}
        legacy['syntheticFixture'] = True
        legacy['id'] = str(uuid4())
        self.store.save_plan(legacy)
        with self.assertRaises(HTTPException):
            self.bindings.manifest(legacy)
        with self.assertRaises(HTTPException) as rejected:
            self.applications.require_plan_current(legacy)
        self.assertEqual(rejected.exception.detail, 'APPLICATION_PIN_REQUIRED')
        self.assertEqual(self.store.plan(legacy['id'], 'alice'), legacy)
        self.assertFalse(hasattr(self.applications, 'adopt_legacy_demo_plan'))

    def test_actual_native_authenticated_routers_forbid_body_identity_and_model_grants(self):
        native = AgentOS(id="owned-composition-router", agents=[Agent(id="factory-executor", db=self.db, model=DemoModel(), telemetry=False)],
                         db=self.db, **self.auth.agentos_kwargs(), mcp=False, scheduler=False, telemetry=False).get_app()
        native.include_router(application_router(self.auth, self.applications))
        native.include_router(composition_router(self.auth, self.composition))
        with TestClient(native, base_url="https://testserver") as client:
            alice = {"Authorization": "Bearer " + self.auth._issue_native_token("alice")}
            manager = {"Authorization": "Bearer " + self.auth._issue_native_token("manager")}
            path = "/api/factory/compositions/proposals"
            self.assertEqual(client.get("/api/factory/applications").status_code, 401)
            self.assertEqual(client.post("/api/factory/applications/drafts", headers=alice, json={"definition": app_definition(self.store), "requestId": "user-draft"}).status_code, 201)
            for forbidden in ({"ownerId": "manager"}, {"capabilities": ["agent_os:admin"]}, {"budget": {"toolCalls": 128}}):
                response = client.post(path, headers=alice, json={"goal": "Checksum fixture", "requestId": str(uuid4()), **forbidden})
                self.assertEqual(response.status_code, 422, response.text)
            response = client.post(path, headers=alice, json={"goal": "Checksum fixture", "requestId": "http-one"})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["ownerId"], "alice")
            self.assertEqual(client.get(path + "/" + response.json()["id"], headers=manager).status_code, 404)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL/native queue acceptance")
class ApplicationCompositionPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(material_review_mode="member-self-service", material_policy_revision="material-governance-v1", db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1, max_user_tasks=2)
        self.start()
        self.addCleanup(self.stop)
        self.auth.account_roles.unassign("bob", "factory-user")
        self.auth.account_roles.assign("bob", "factory-manager")

    def start(self):
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.apps, self.composition = self.state["applications"], self.state["composition"]
        self.assertIs(self.store.composition, self.composition)
        self.client = TestClient(self.app, base_url="https://testserver").__enter__()

    def stop(self):
        if getattr(self, "client", None):
            self.client.__exit__(None, None, None)
            self.client = None
            self.store.engine.dispose()
            self.store.native_db.db_engine.dispose()

    def login(self, owner):
        self.client.cookies.clear()
        response = authorize_client(self.client, owner)
        self.assertEqual(response.status_code, 200, response.text)

    def publish_http(self):
        self.login("manager")
        drafted = self.client.post("/api/factory/applications/drafts", json={"definition": app_definition(self.store), "requestId": "native-app-draft"})
        self.assertEqual(drafted.status_code, 201, drafted.text)
        app = drafted.json()
        published = self.client.post(f'/api/factory/applications/{app["id"]}/versions/1/publish', json={"requestId": "native-app-publish"})
        self.assertEqual(published.status_code, 200, published.text)
        return app


    def wait_job(self, identifier):
        end = time.monotonic() + 15
        while time.monotonic() < end:
            response = self.client.get("/api/factory/jobs/" + identifier)
            self.assertEqual(response.status_code, 200, response.text)
            if response.json()["job"]["status"] in {"completed", "failed", "cancelled"}:
                return response.json()
            time.sleep(.03)
        self.fail("Owned native job did not become terminal")

    def test_new_approved_application_natural_language_to_actual_native_artifact_without_core_branch(self):
        app = self.publish_http()
        self.login("alice")
        proposal = self.client.post("/api/factory/compositions/proposals", json={"goal": "Perform a text audit for original synthetic evidence", "requestId": "native-discover"})
        self.assertEqual(proposal.status_code, 201, proposal.text)
        self.assertEqual(proposal.json()["candidate"]["applicationRef"], pin(app))
        accepted = self.client.post("/api/factory/compositions/proposals/" + proposal.json()["id"] + "/accept", json={"requestId": "native-accept"})
        self.assertEqual(accepted.status_code, 201, accepted.text)
        plan = accepted.json()
        admitted = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": "native-instance"})
        self.assertEqual(admitted.status_code, 202, admitted.text)
        detail = self.wait_job(admitted.json()["id"])
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(self.store.plan(plan["id"], "alice")["application"], app["id"])
        self.assertTrue(detail["artifacts"])
        artifact = detail["artifacts"][0]
        raw = self.client.get(f'/api/factory/jobs/{detail["job"]["id"]}/artifacts/{artifact["id"]}').content
        self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact["sha256"])
        self.assertEqual(__import__("json").loads(raw)["algorithm"], "sha256")
        with self.store.engine.connect() as conn:
            events = self.store.events(detail["job"]["id"])
            self.assertTrue(any(event["type"] == "checksum_completed" for event in events))
            self.assertEqual(len(list(conn.execute(select(self.composition.proposals)))), 1)
        # Publication withdrawal applies at admission; completed evidence remains readable.
        self.login("manager")
        withdrawn = self.client.post(f'/api/factory/applications/{app["id"]}/versions/1/withdraw', json={"requestId": "native-withdraw", "reason": "Owned test withdrawal"})
        self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
        self.login("alice")
        self.assertEqual(self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": "deny-second"}).status_code, 409)
        self.assertEqual(self.client.get("/api/factory/jobs/" + detail["job"]["id"]).json()["artifacts"], detail["artifacts"])

    def test_postgres_concurrent_identical_accept_single_native_ticket_and_restart_receipt(self):
        self.store.engine.dispose()
        self.store.engine = __import__("sqlalchemy").create_engine(self.database.url, pool_size=1, max_overflow=0, pool_timeout=3)
        proposal = self.composition.propose("alice", "Checksum concurrent owned fixture", application="fixture-checksum", request_id="concurrent-propose")
        with ThreadPoolExecutor(max_workers=4) as workers:
            plans = list(workers.map(lambda _: self.composition.accept("alice", proposal["id"], "concurrent-accept"), range(4)))
        self.assertTrue(all(plan == plans[0] for plan in plans))
        self.login("alice")
        instance_body = {"planId": plans[0]["id"], "requestId": "same-native-instance"}
        first = self.client.post("/api/factory/instances", json=instance_body)
        second = self.client.post("/api/factory/instances", json=instance_body)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        detail = self.wait_job(first.json()["id"])
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.stop()
        self.start()
        self.assertEqual(self.composition.accept("alice", proposal["id"], "concurrent-accept"), plans[0])
        self.assertEqual(self.composition.inspect("alice", proposal["id"])["state"], "accepted")
        self.login("bob")
        self.assertEqual(self.client.get("/api/factory/compositions/proposals/" + proposal["id"]).status_code, 404)

    def test_seed_application_references_are_stable_across_independent_postgres_databases(self):
        with IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as other_database, TemporaryDirectory() as directory:
            other_settings = Settings(material_review_mode="member-self-service", material_policy_revision="material-governance-v1", db_url=other_database.url, workspace=Path(directory), max_workers=1,
                                      max_tool_calls=3, experiment_timeout_seconds=5)
            other_app = create_app(other_settings)
            other_state = other_app.app.state.factory
            try:
                with TestClient(other_app, base_url="https://testserver"):
                    first = {application["id"]: pin(application) for application in self.apps.list_active("alice")}
                    second = {application["id"]: pin(application) for application in other_state["applications"].list_active("alice")}
                    self.assertEqual(first, second)
                    plan = other_state["composition"].create_plan("alice", "Checksum narrowed deployment ceiling", "literature", "fixture-checksum")
                    self.assertEqual(plan["budget"]["toolCalls"], 3)
                    self.assertEqual(plan["budget"]["experimentSeconds"], 5)
            finally:
                other_state["store"].engine.dispose()
                other_state["store"].native_db.db_engine.dispose()

    def test_historical_legacy_plan_remains_readable_and_new_composition_executes(self):
        original = self.composition.create_plan("alice", "Checksum exact historical synthetic fixture", "literature", "fixture-checksum")
        legacy = {key: value for key, value in original.items() if key not in {"applicationRef", "executionBindings", "bindingManifest", "compositionProposalId"}}
        legacy["syntheticFixture"] = True
        legacy["id"] = str(uuid4())
        legacy["fingerprint"] = digest({key: value for key, value in legacy.items() if key not in {"id", "createdAt", "fingerprint"}})
        self.store.save_plan(legacy)
        self.login("alice")
        rejected = self.client.post("/api/factory/instances", json={"planId": legacy["id"], "requestId": "legacy-native-instance"})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertIn("APPLICATION_PIN_REQUIRED", rejected.text)
        self.assertEqual(self.store.plan(legacy["id"], "alice"), legacy)
        for changed in ({"instructions": ["Changed after adoption"]}, {"unexpected": "silently stripped value"}):
            with self.subTest(changed=changed), self.assertRaises(HTTPException):
                self.apps.require_legacy_demo_plan({**legacy, **changed})
        admitted = self.client.post("/api/factory/instances", json={"planId": original["id"], "requestId": "current-native-instance"})
        self.assertEqual(admitted.status_code, 202, admitted.text)
        detail = self.wait_job(admitted.json()["id"])
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertTrue(detail["artifacts"])
        self.assertEqual(self.store.plan(legacy["id"], "alice"), legacy)

    def test_actual_factory_restart_withdrawn_seed_keeps_history_and_blocks_current_execution(self):
        plan = self.composition.create_plan("alice", "Investigate owned historical evidence", "literature", "fixture-text")
        with self.store.engine.begin() as conn:
            conn.execute(self.store.material_governance.versions.update().where(
                self.store.material_governance.versions.c.material_id == "fixture-knowledge").values(author_id="manager"))
        self.store.material_governance.withdraw("manager", "fixture-knowledge", 1, "withdraw-seed", "Owned inactive fixture")
        self.stop()
        self.start()
        version = self.store.material_governance.inspect_version("manager", "fixture-knowledge", 1)
        self.assertEqual(version["governance"]["state"], "withdrawn")
        self.assertEqual(self.store.plan(plan["id"], "alice"), plan)
        blocked = self.composition.create_plan("alice", "Investigate withdrawn evidence", "literature", "fixture-text")
        self.assertEqual(blocked["status"], "blocked")
        self.login("alice")
        response = self.client.post("/api/factory/instances", json={"planId": plan["id"], "requestId": "no-reactivation"})
        self.assertEqual(response.status_code, 409, response.text)

    def test_actual_production_configuration_missing_exact_model_registration_is_specific_and_never_executes(self):
        with IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as database, TemporaryDirectory() as directory:
            calls = []
            def forbidden_factory(context):
                calls.append(context)
                raise AssertionError("Production preflight must not construct a provider")
            registrations = [AdapterRegistration("environment", "owned-environment-v1", "1", forbidden_factory),
                             AdapterRegistration("tool", "owned-checksum-v1", "1", forbidden_factory, tool_name="checksum", permissions=("checksum:read",)),
                             AdapterRegistration("knowledge", "owned-knowledge-v1", "1", forbidden_factory)]
            settings = Settings(material_review_mode="member-self-service", material_policy_revision="material-governance-v1", db_url=database.url, jwt_key=self.settings.jwt_key,
                                workspace=Path(directory), runtime_adapters=registrations, max_workers=1)
            app = create_app(settings)
            state = app.app.state.factory
            store, auth = state["store"], state["auth"]
            try:
                # Managed subjects/grants are restricted to this generated database.
                for subject, role in (("owned-author", "owned-review-admin"), ("owned-reviewer", "owned-review-admin"), ("owned-user", "owned-plan-user")):
                    auth.directory.upsert(subject, name="Original isolated synthetic authorization fixture")
                materials = []
                for kind, binding, content, caps in (
                    ("skill", None, "Original inert workflow guidance.", []),
                    ("prompt", None, "Original instructions for bounded checksum.", []),
                    ("model", {"adapterId": "unavailable-production-model-v1", "revision": "4", "config": {}}, "Original missing provider specification.", []),
                    ("environment", {"adapterId": "owned-environment-v1", "revision": "1", "config": {}}, "Original controlled environment declaration.", []),
                    ("tool", {"adapterId": "owned-checksum-v1", "revision": "1", "config": {}}, "checksum", ["checksum:read"]),
                    ("knowledge", {"adapterId": "owned-knowledge-v1", "revision": "1", "config": {}}, "Original synthetic evidence text.", [])):
                    definition = {"kind": kind, "name": "Owned production-mode synthetic " + kind, "content": content, "permissions": caps,
                        "license": "MIT", "provenance": {"kind": "original", "notice": "Original isolated synthetic fixture."}}
                    if binding:
                        definition["runtimeBinding"] = binding
                    material = store.material_governance.create_draft("owned-author", definition, "prod-material-" + kind)
                    store.material_governance.publish("owned-author", material["id"], 1, "prod-publish-" + kind)
                    materials.append(material)
                definition = {"id": "owned-production-config", "name": "Isolated production-mode fixture",
                    "modes": {"literature": {"materialRefs": [pin(material) for material in materials], "capabilities": ["checksum:read"], "toolOrder": ["checksum"]}}}
                application = state["applications"].create_draft("owned-author", definition, "prod-app")
                state["applications"].publish("owned-author", application["id"], 1, "prod-app-publish")
                with TestClient(app, base_url="https://testserver") as client:
                    headers = {"Authorization": "Bearer " + auth._issue_native_token("owned-user")}
                    proposal = client.post("/api/factory/compositions/proposals", headers=headers, json={"goal": "Controlled production-mode fixture with no provider calls", "applicationRef": pin(application), "requestId": "prod-proposal"})
                    self.assertEqual(proposal.status_code, 201, proposal.text)
                    candidate = proposal.json()["candidate"]
                    self.assertEqual(candidate["status"], "blocked")
                    self.assertEqual(len(candidate["missing"]), 1)
                    self.assertIn("BINDING_ADAPTER_UNAVAILABLE", candidate["missing"][0])
                    self.assertIn("unavailable-production-model-v1@4", candidate["missing"][0])
                    accepted = client.post("/api/factory/compositions/proposals/" + proposal.json()["id"] + "/accept", headers=headers, json={"requestId": "prod-blocked-plan"})
                    self.assertEqual(accepted.status_code, 201, accepted.text)
                    denied = client.post("/api/factory/instances", headers=headers, json={"planId": accepted.json()["id"], "requestId": "prod-no-native-ticket"})
                    self.assertIn(denied.status_code, {400, 403, 409}, denied.text)
                    self.assertEqual(store.sql("SELECT COUNT(*) AS count FROM af_tasks")[0]["count"], 0)
                    self.assertEqual(calls, [])
            finally:
                store.engine.dispose()
                store.native_db.db_engine.dispose()


if __name__ == "__main__":
    unittest.main()

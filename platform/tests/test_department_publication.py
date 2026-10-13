"""Department members publish exact versions without a separate administrator.

SQLite exercises service contracts; optional isolated PostgreSQL cases exercise
exactly the same mutations through the configured Factory services. No real
model, external connection or production identity is used.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from agent_factory_research.config import ResearchSettings as Settings
from agent_factory_research.bootstrap_catalog import SEEDS
from agent_factory_server.main import create_app
from agent_factory.material_governance import GovernanceConfig, MaterialGovernance
from pg_fixture import IsolatedPostgres
from test_applications_composition import ApplicationCompositionFixture, app_definition, pin


class DepartmentPublicationCases:
    def material(self, actor="alice", **changes):
        return self.governance.create_draft(actor, {
            "kind": "prompt", "name": "Shared departmental fixture", "content": "Summarize synthetic evidence.",
            **changes}, "material-" + actor + "-" + str(changes.get("id", "new")))

    def application(self, actor="alice", identifier="department-fixture"):
        return self.applications.create_draft(actor, app_definition(self.store, identifier), "app-" + identifier)

    def test_members_publish_without_creating_review_records(self):
        material = self.material()
        application = self.application()
        self.assertTrue(self.governance.publish("alice", material["id"], 1, "publish-material")["published"])
        self.assertEqual(self.applications.publish("alice", application["id"], 1, "publish-application"), application)
        self.assertTrue(self.governance.require_materials_current({"materialRefs": [pin(material)]})["allowed"])
        self.assertEqual(self.applications.require_current(pin(application)), application)
        with self.store.engine.connect() as conn:
            self.assertEqual(list(conn.execute(select(self.governance.reviews))), [])
            self.assertEqual(list(conn.execute(select(self.applications.reviews))), [])
        self.assertEqual(self.governance.list_reviews("alice"), [])
        self.assertEqual(self.applications.list_reviews("alice"), [])

    def test_shared_revisions_preserve_exact_existing_application_and_material_bindings(self):
        material = self.material()
        self.governance.publish("alice", material["id"], 1, "material-publish")
        revised_material = self.material("bob", id=material["id"], content="A new shared instruction.")
        self.governance.publish("bob", revised_material["id"], 2, "new-material-publish")
        application = self.application()
        self.applications.publish("alice", application["id"], 1, "application-publish")
        bound_plan = self.store.composition.create_plan("alice", "Checksum the synthetic member fixture",
                                                       "literature", application_ref=pin(application))
        definition = app_definition(self.store, application["id"], name="Member revision")
        revised = self.applications.revise("bob", application["id"], 1, definition, "application-revise")
        self.applications.publish("bob", revised["id"], 2, "new-application-publish")
        self.assertEqual(self.store.plan(bound_plan["id"], "alice"), bound_plan)
        self.assertEqual(bound_plan["applicationRef"], pin(application))
        self.assertEqual(revised["version"], 2)
        self.assertNotEqual(revised["sha256"], application["sha256"])
        self.assertEqual(self.applications.require_current(pin(application)), application)
        self.assertTrue(self.governance.require_materials_current({"materialRefs": [pin(material)]})["allowed"])
        self.assertEqual(self.governance.inspect_version("alice", material["id"], 1)["material"]["sha256"], material["sha256"])

    def test_other_members_cannot_read_publish_or_revise_private_drafts(self):
        material = self.material()
        application = self.application()
        calls = [lambda: self.governance.inspect_version("bob", material["id"], 1),
                 lambda: self.governance.publish("bob", material["id"], 1, "foreign-material"),
                 lambda: self.material("bob", id=material["id"]),
                 lambda: self.applications.inspect("bob", application["id"], 1),
                 lambda: self.applications.publish("bob", application["id"], 1, "foreign-app"),
                 lambda: self.applications.revise("bob", application["id"], 1,
                     app_definition(self.store, application["id"]), "foreign-revise")]
        for call in calls:
            with self.assertRaises(HTTPException) as denied:
                call()
            self.assertIn(denied.exception.status_code, (403, 404))
        self.assertFalse(any(row["application"]["id"] == application["id"]
            for row in self.applications.list_definitions("bob", all_authors=True)))

    def test_public_deactivation_requires_admin_and_keeps_history(self):
        material = self.material()
        application = self.application()
        self.governance.publish("alice", material["id"], 1, "publish-material")
        self.applications.publish("alice", application["id"], 1, "publish-app")
        for service, item in ((self.governance, material), (self.applications, application)):
            for action in ("archive", "withdraw"):
                with self.assertRaises(HTTPException) as denied:
                    getattr(service, action)("alice", item["id"], 1, action + "-member")
                self.assertEqual(denied.exception.status_code, 403)
            result = service.archive("manager", item["id"], 1, "admin-archive", "Retained fixture")
            self.assertTrue(result["immutableBodyPreserved"])
            # Deactivation does not turn a formerly public version private.
            for action in ("archive", "withdraw"):
                with self.assertRaises(HTTPException) as denied:
                    getattr(service, action)("alice", item["id"], 1, action + "-after-admin")
                self.assertEqual(denied.exception.status_code, 403)
            with self.assertRaises(HTTPException) as inactive:
                service.publish("manager", item["id"], 1, "no-silent-restore")
            self.assertEqual(inactive.exception.status_code, 409)
        self.assertEqual(self.applications.inspect("manager", application["id"], 1)["application"], application)
        self.assertEqual(self.governance.inspect_version("manager", material["id"], 1)["material"]["sha256"], material["sha256"])

    def test_owner_can_archive_private_drafts_idempotently_without_losing_bodies(self):
        material, application = self.material(), self.application()
        receipts = []
        for service, item in ((self.governance, material), (self.applications, application)):
            result = service.archive("alice", item["id"], 1, "own-draft", "No longer needed")
            self.assertEqual(result["state"], "archived")
            self.assertTrue(result["immutableBodyPreserved"])
            self.assertEqual(service.archive("alice", item["id"], 1, "own-draft", "No longer needed"), result)
            self.assertEqual(service.archive("alice", item["id"], 1, "own-draft-again", "No longer needed"), result)
            with self.assertRaises(HTTPException) as conflict:
                service.archive("alice", item["id"], 1, "own-draft", "Changed intent")
            self.assertEqual(conflict.exception.status_code, 409)
            receipts.append((service, item))
        self.assertEqual(self.applications.inspect("alice", application["id"], 1)["application"], application)
        self.assertEqual(self.governance.inspect_version("alice", material["id"], 1)["material"], material)
        self.auth.authorization.unassign("alice", "factory-user")
        for service, item in receipts:
            with self.assertRaises(HTTPException) as revoked:
                service.archive("alice", item["id"], 1, "own-draft", "No longer needed")
            self.assertEqual(revoked.exception.status_code, 403)

    def test_other_member_cannot_deactivate_private_draft_before_or_after_archive(self):
        material, application = self.material(), self.application()
        for service, item in ((self.governance, material), (self.applications, application)):
            for archived in (False, True):
                if archived:
                    service.archive("alice", item["id"], 1, "own-draft")
                for action in ("archive", "withdraw"):
                    with self.assertRaises(HTTPException) as denied:
                        getattr(service, action)("bob", item["id"], 1, action + "-other")
                    self.assertEqual(denied.exception.status_code, 403)

    def test_archiving_own_unpublished_revision_preserves_public_version_pins(self):
        material, application = self.material(), self.application()
        self.governance.publish("alice", material["id"], 1, "public-material")
        self.applications.publish("alice", application["id"], 1, "public-application")
        draft_material = self.material("bob", id=material["id"], content="Unpublished replacement")
        draft_app = self.applications.revise("bob", application["id"], 1,
            app_definition(self.store, application["id"], name="Unpublished replacement"), "draft-revision")
        self.governance.archive("bob", draft_material["id"], 2, "discard-private-material")
        self.applications.archive("bob", draft_app["id"], 2, "discard-private-app")
        self.assertEqual(self.applications.require_current(pin(application)), application)
        self.assertTrue(self.governance.require_materials_current({"materialRefs": [pin(material)]})["allowed"])
        self.assertEqual(self.applications.inspect("bob", draft_app["id"], 2)["application"], draft_app)
        self.assertEqual(self.governance.inspect_version("bob", draft_material["id"], 2)["material"], draft_material)

    def test_idempotency_and_current_membership_are_checked_before_recovery(self):
        first = self.application(identifier="first")
        second = self.application(identifier="second")
        published = self.applications.publish("alice", first["id"], 1, "one-publication")
        self.assertEqual(self.applications.publish("alice", first["id"], 1, "one-publication"), published)
        with self.assertRaises(HTTPException) as conflict:
            self.applications.publish("alice", second["id"], 1, "one-publication")
        self.assertEqual(conflict.exception.status_code, 409)
        self.auth.authorization.unassign("alice", "factory-user")
        with self.assertRaises(HTTPException) as revoked:
            self.applications.publish("alice", first["id"], 1, "one-publication")
        self.assertEqual(revoked.exception.status_code, 403)

    def test_basic_member_grant_suffices_without_native_component_write(self):
        self.auth.authorization.define_role("department-member-fixture", ["agents:factory-executor:run"])
        self.auth.directory.upsert("member-only", name="Synthetic minimum member")
        self.auth.authorization.assign("member-only", "department-member-fixture")
        material = self.material("member-only")
        application = self.application("member-only", identifier="minimum-member-app")
        self.governance.publish("member-only", material["id"], 1, "minimal-material-publish")
        self.applications.publish("member-only", application["id"], 1, "minimal-app-publish")
        self.assertEqual(self.applications.inspect("member-only", application["id"], 1)["application"], application)
        self.assertTrue(self.governance.inspect_version("member-only", material["id"], 1)["material"]["published"])
        with self.assertRaises(HTTPException):
            self.auth.require("member-only", "components:write")

    def test_credential_and_runtime_authority_rejections_are_preserved(self):
        for changes in ({"content": "sk-proj-" + "x" * 32}, {"kind": "tool", "content": "arbitrary_shell"},
                        {"permissions": ["agent_os:admin"]}, {"apiKey": "synthetic-forbidden"}):
            with self.assertRaises(HTTPException) as invalid:
                self.material(**changes)
            self.assertEqual(invalid.exception.status_code, 422)
        application = self.application()
        wrong = {**pin(application), "sha256": "0" * 64}
        self.applications.publish("alice", application["id"], 1, "exact-publication")
        with self.assertRaises(HTTPException) as mismatch:
            self.applications.require_current(wrong)
        self.assertEqual(mismatch.exception.status_code, 409)

    def test_old_review_mutations_are_gone_in_member_mode(self):
        material = self.material()
        application = self.application()
        calls = [lambda: self.governance.request_publication("alice", material["id"], 1, "review"),
                 lambda: self.applications.request_publication("alice", application["id"], 1, "review"),
                 lambda: self.governance.decide_publication("manager", "history", True, "decision"),
                 lambda: self.applications.decide_publication("manager", "history", True, "decision")]
        for call in calls:
            with self.assertRaises(HTTPException) as removed:
                call()
            self.assertEqual(removed.exception.status_code, 410)


class DepartmentPublicationTests(DepartmentPublicationCases, ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.auth.authorization.unassign("bob", "factory-manager")
        self.auth.authorization.assign("bob", "factory-user")
        # Safe startup changes only the publication workflow, preserving seeds.
        self.governance = MaterialGovernance(self.store, self.auth, GovernanceConfig(), seed_materials=SEEDS)
        self.store.material_governance = self.governance

    def test_startup_keeps_pending_denied_and_approved_history_unchanged(self):
        legacy = GovernanceConfig(review_mode="separate-admin", revision="legacy-history")
        self.governance.replace_configuration(legacy, expected_revision=self.governance.current()["revision"])
        self.auth.authorization.unassign("bob", "factory-user")
        self.auth.authorization.assign("bob", "factory-manager")
        materials, reviews = [], []
        for state in ("pending", "denied", "approved"):
            material = self.governance.create_draft("manager", {
                "kind": "prompt", "name": state, "content": "Historical synthetic fixture."}, "legacy-" + state)
            review = self.governance.request_publication("manager", material["id"], 1, "review-" + state)
            if state != "pending":
                self.governance.decide_publication("bob", review["id"], state == "approved", "decision-" + state)
            materials.append(material)
            reviews.append(review["id"])
        app = self.applications.create_draft("manager", app_definition(self.store), "legacy-app")
        self.applications.request_publication("manager", app["id"], 1, "legacy-app-review")
        with self.store.engine.connect() as conn:
            before = [dict(row) for row in conn.execute(select(self.governance.reviews)).mappings()]
            app_before = [dict(row) for row in conn.execute(select(self.applications.reviews)).mappings()]
        self.governance = MaterialGovernance(self.store, self.auth, GovernanceConfig(), seed_materials=SEEDS)
        self.store.material_governance = self.governance
        with self.store.engine.connect() as conn:
            self.assertEqual(before, [dict(row) for row in conn.execute(select(self.governance.reviews)).mappings()])
            self.assertEqual(app_before, [dict(row) for row in conn.execute(select(self.applications.reviews)).mappings()])
        for material in materials[:2]:
            with self.assertRaises(HTTPException):
                self.governance.require_materials_current({"materialRefs": [pin(material)]})
        self.assertTrue(self.governance.require_materials_current({"materialRefs": [pin(materials[2])]})["allowed"])
        with self.assertRaises(HTTPException):
            self.applications.require_current(pin(app))
        self.assertTrue(self.governance.inspect_review("manager", reviews[0])["readOnly"])

    def test_startup_cannot_change_execution_contract_as_a_publication_upgrade(self):
        previous = self.governance.current()
        incompatible = GovernanceConfig(review_mode="member-self-service", revision="unexpected-contract", source_synthesis_enabled=True)
        with self.assertRaises(ValueError):
            MaterialGovernance(self.store, self.auth, incompatible, seed_materials=SEEDS)
        self.assertEqual(self.governance.current(), previous)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated loopback PostgreSQL")
class DepartmentPublicationPostgresTests(DepartmentPublicationCases, unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"])
        database.__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        self.settings = Settings(db_url=database.url, workspace=Path(self.directory.name))
        self.settings.material_review_mode = "member-self-service"
        self.settings.material_policy_revision = "material-department-v1"
        application = create_app(self.settings)
        state = application.app.state.factory
        self.store, self.auth = state["store"], state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(application)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.applications = state["applications"]
        self.governance = self.store.material_governance

    def test_http_member_publish_and_admin_only_delete_surface(self):
        headers = {"Authorization": "Bearer " + self.auth.issue_demo_token("alice")}
        material = self.material()
        application = self.application()
        bob_headers = {"Authorization": "Bearer " + self.auth.issue_demo_token("bob")}
        for identity, expected in ((headers, True), (bob_headers, False)):
            response = self.client.get("/api/factory/materials", headers=identity)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(any(row["id"] == material["id"] for row in response.json()), expected)
        for path in (f"/api/factory/material-governance/versions/{material['id']}/1",
                     f"/api/factory/applications/{application['id']}/versions/1"):
            published = self.client.post(path + "/publish", headers=headers, json={"requestId": "http-publish"})
            self.assertEqual(published.status_code, 200, published.text)
            denied = self.client.post(path + "/archive", headers=headers, json={"requestId": "http-delete"})
            self.assertEqual(denied.status_code, 403, denied.text)
        for identity in (headers, bob_headers):
            response = self.client.get("/api/factory/materials", headers=identity)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(any(row["id"] == material["id"] and row["published"] for row in response.json()))
        created = self.client.post("/api/factory/materials", headers=headers, json={
            "requestId": "compatible-create", "kind": "prompt", "name": "Member compatibility fixture",
            "description": "Inert synthetic fixture", "content": "Synthetic public prompt."})
        self.assertEqual(created.status_code, 201, created.text)
        compatible = created.json()
        published = self.client.post(f"/api/factory/materials/{compatible['id']}/1/publish", headers=headers,
                                     json={"requestId": "compatible-publish"})
        self.assertEqual(published.status_code, 202, published.text)
        self.assertTrue(published.json()["published"])

    def test_http_own_private_archive_preserves_owner_visibility(self):
        headers = {"Authorization": "Bearer " + self.auth.issue_demo_token("alice")}
        bob_headers = {"Authorization": "Bearer " + self.auth.issue_demo_token("bob")}
        material, application = self.material(), self.application()
        for path in (f"/api/factory/material-governance/versions/{material['id']}/1",
                     f"/api/factory/applications/{application['id']}/versions/1"):
            denied = self.client.post(path + "/archive", headers=bob_headers, json={"requestId": "foreign-draft"})
            self.assertEqual(denied.status_code, 403, denied.text)
            archived = self.client.post(path + "/archive", headers=headers, json={"requestId": "own-draft"})
            self.assertEqual(archived.status_code, 200, archived.text)
            self.assertTrue(archived.json()["immutableBodyPreserved"])
            self.assertEqual(self.client.get(path, headers=headers).status_code, 200)
            self.assertIn(self.client.get(path, headers=bob_headers).status_code, (403, 404))
        for identity, expected in ((headers, True), (bob_headers, False)):
            response = self.client.get("/api/factory/materials", headers=identity)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(any(row["id"] == material["id"] for row in response.json()), expected)
        self.assertFalse(any(row["application"]["id"] == application["id"]
            for row in self.applications.list_definitions("bob", all_authors=True)))

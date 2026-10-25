"""Catalog delegates to governed composition; native Auth is an owned fixture.

These portable metadata tests are not PostgreSQL queue evidence. New application
and native execution acceptance lives in test_applications_composition.py.
"""
import copy
import unittest

from fastapi import HTTPException

from agent_factory.catalog import create_plan
from fixture_settings import Settings
from test_applications_composition import ApplicationCompositionFixture, app_definition, pin


class CatalogContractTests(ApplicationCompositionFixture):
    def plan(self):
        return create_plan(self.store, "alice", "Compare synthetic candidates", "literature")

    def test_transitive_permission_and_archived_dependency_fail_closed(self):
        with self.assertRaises(HTTPException):
            self.material(kind="knowledge", permissions=["agent_os:admin"])
        owned = self.material(kind="knowledge", id="catalog-archive-owned")
        definition = app_definition(self.store, identifier="catalog-archive-fixture")
        refs = definition["modes"]["literature"]["materialRefs"]
        refs[refs.index(next(ref for ref in refs if ref["id"] == "fixture-knowledge"))] = pin(owned)
        application = self.applications.create_draft("manager", definition, "catalog-archive-app")
        self.applications.publish("manager", application["id"], application["version"], "catalog-archive-publish")
        original = create_plan(self.store, "alice", "Compare synthetic candidates", "literature",
                               application_ref=pin(application))
        self.store.material_governance.archive("manager", owned["id"], owned["version"],
            "archive-fixture", "Controlled inactive dependency")
        self.assertEqual(self.store.plan(original["id"], "alice"), original)
        with self.assertRaises(HTTPException):
            self.applications.require_plan_current(original)

    def test_tool_contract_and_owner_pins_cannot_be_replaced(self):
        with self.assertRaises(HTTPException):
            self.material(kind="tool", content="arbitrary_shell", permissions=["checksum:read"])
        service = self.store.material_governance
        original = service.inspect_version("manager", "fixture-question-tool", 1)
        replacement = {"id": "fixture-question-tool", "kind": "prompt", "name": "Revised instructions",
                       "content": "Ordinary member-owned revision.", "license": "MIT"}
        with self.assertRaises(HTTPException) as denied:
            service.create_draft("alice", replacement, "other-owner-revision")
        self.assertEqual(denied.exception.status_code, 403)
        revised = service.create_draft("manager", replacement, "owner-revision")
        self.assertEqual(revised["version"], 2)
        self.assertEqual(service.inspect_version("manager", "fixture-question-tool", 1), original)
        self.assertEqual(self.plan()["status"], "ready")

    def test_forward_cycles_deep_chains_and_closure_count_are_bounded(self):
        absent = {"id": "self-cycle", "version": 1, "sha256": "0" * 64}
        with self.assertRaises(HTTPException):
            self.material(id="self-cycle", dependencies=[absent])
        previous = None
        for index in range(8):
            previous = self.material(kind="knowledge", id=f"bounded-depth-{index}", dependencies=[pin(previous)] if previous else [])
        ninth = self.material(kind="knowledge", dependencies=[pin(previous)])
        with self.assertRaises(HTTPException):
            self.applications.closure([pin(ninth)])
        with self.assertRaises(HTTPException):
            self.material(kind="knowledge", dependencies=[pin(ninth)])
        refs = [pin(self.material(kind="knowledge", id=f"bounded-count-{index}")) for index in range(31)]
        with self.assertRaises(HTTPException):
            self.applications.closure(refs)
        self.assertEqual(len(self.applications.closure(refs[:30])), 30)

    def test_snapshot_remains_exact_after_material_and_application_revisions(self):
        application = self.publish()
        old = create_plan(self.store, "alice", "Original governed synthetic plan", "literature", application_ref=pin(application))
        alternate = self.material(content="Changed approved instructions in a new immutable version.")
        revised_definition = app_definition(self.store)
        refs = revised_definition["modes"]["literature"]["materialRefs"]
        refs[refs.index(next(ref for ref in refs if ref["id"] == "fixture-prompt"))] = pin(alternate)
        revised = self.applications.revise("manager", application["id"], 1, revised_definition, "revise-config")
        self.applications.publish("manager", revised["id"], 2, "publish-config")
        current = create_plan(self.store, "alice", "Original governed synthetic plan", "literature", application_ref=pin(revised))
        self.assertNotIn(alternate["content"], old["instructions"])
        self.assertIn(alternate["content"], current["instructions"])
        self.assertNotEqual(old["fingerprint"], current["fingerprint"])
        self.assertEqual(self.store.plan(old["id"], "alice"), copy.deepcopy(old))
        self.applications.require_plan_current(old)

    def test_policy_typos_and_implicit_production_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            Settings(db_url="unused", temporary_policy="manual-review")
        with self.assertRaises(ValueError):
            Settings(db_url="unused", temporary_policy="unset")


if __name__ == "__main__":
    unittest.main()

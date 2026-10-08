"""Catalog delegates to governed composition; native Auth is an owned fixture.

These portable metadata tests are not PostgreSQL queue evidence. New application
and native execution acceptance lives in test_applications_composition.py.
"""
import copy
import unittest

from fastapi import HTTPException

from agent_factory.catalog import create_plan
from agent_factory.config import Settings
from test_applications_composition import ApplicationCompositionFixture, app_definition, pin


class CatalogContractTests(ApplicationCompositionFixture):
    def plan(self):
        return create_plan(self.store, "alice", "Compare synthetic candidates", "literature")

    def test_transitive_permission_and_archived_dependency_fail_closed(self):
        with self.assertRaises(HTTPException):
            self.material(kind="knowledge", permissions=["agent_os:admin"])
        original = self.plan()
        self.store.material_governance.archive("manager", "synthetic-knowledge", 1, "archive-fixture", "Controlled inactive dependency")
        blocked = self.plan()
        self.assertEqual(blocked["status"], "blocked")
        self.assertTrue(blocked["missing"])
        self.assertNotIn("agent_os:admin", blocked["capabilities"])
        self.assertEqual(self.store.plan(original["id"], "alice"), original)
        with self.assertRaises(HTTPException):
            self.applications.require_plan_current(original)

    def test_tool_kind_and_registered_binding_cannot_be_replaced(self):
        for changes in ({"kind": "tool", "content": "arbitrary_shell", "permissions": ["checksum:read"]},
                        {"id": "literature-tool", "kind": "prompt"},
                        {"id": "literature-tool", "kind": "tool", "content": "ask_scope", "permissions": ["question:ask"]}):
            with self.subTest(changes=changes), self.assertRaises(HTTPException):
                self.material(**changes)
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
        refs[refs.index(next(ref for ref in refs if ref["id"] == "research-prompt"))] = pin(alternate)
        revised = self.applications.revise("manager", application["id"], 1, revised_definition, "revise-config")
        review = self.applications.request_publication("manager", revised["id"], 2, "review-config")
        self.applications.decide_publication("bob", review["id"], True, "approve-config")
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
            Settings(db_url="unused", demo=False, temporary_policy="unset")


if __name__ == "__main__":
    unittest.main()

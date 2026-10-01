import copy
from types import SimpleNamespace
import unittest
from agent_factory.catalog import create_plan, seed_catalog
from agent_factory.config import Settings
from agent_factory.store import digest


class CatalogFixture:
    def __init__(self):
        self.settings = SimpleNamespace(demo=True, temporary_policy="bounded-synthetic", max_tool_calls=8, experiment_timeout_seconds=8, experiment_output_bytes=65536)
        self.items = []

    def materials(self, published_only=False):
        return copy.deepcopy(self.items)

    def add_material(self, body, actor, seed=False):
        body = {**body, "version": 1}
        body["sha256"] = digest(body)
        self.items.append({**body, "published": True})

    def save_plan(self, body):
        return body

    def edit(self, material_id, **changes):
        item = next(item for item in self.items if item["id"] == material_id)
        item.update(changes)
        item["sha256"] = digest({key: value for key, value in item.items() if key not in {"sha256", "published", "createdAt"}})
        return {key: item[key] for key in ["id", "version", "sha256"]}


class CatalogContractTests(unittest.TestCase):
    def setUp(self):
        self.store = CatalogFixture()
        seed_catalog(self.store)

    def plan(self):
        return create_plan(self.store, "alice", "Compare synthetic candidates", "literature")

    def test_transitive_permission_and_archived_dependency_fail_closed(self):
        self.store.add_material({"id": "foreign", "kind": "knowledge", "name": "Foreign", "content": "Fixture", "dependencies": [], "permissions": ["admin:write"], "compatibility": ["agno:99"], "archived": True}, "manager")
        foreign = self.store.edit("foreign")
        self.store.edit("research-prompt", dependencies=[foreign])
        plan = self.plan()
        self.assertEqual(plan["status"], "blocked")
        self.assertIn("admin:write", plan["capabilities"])
        self.assertTrue(any(ref["id"] == "foreign" for ref in plan["materialRefs"]))

    def test_tool_kind_and_registered_binding_cannot_be_replaced(self):
        self.store.edit("literature-tool", content="ask_scope")
        self.assertEqual(self.plan()["status"], "blocked")
        self.store.edit("literature-tool", content="literature_search", kind="prompt")
        self.assertEqual(self.plan()["status"], "blocked")

    def test_cycles_and_deep_chains_are_bounded(self):
        ref = None
        for index in range(40):
            self.store.add_material({"id": f"dependency-{index}", "kind": "knowledge", "name": "Fixture", "content": "Fixture", "dependencies": [ref] if ref else [], "permissions": [], "compatibility": ["agno:3.1.0"], "archived": False}, "manager")
            ref = self.store.edit(f"dependency-{index}")
        self.store.edit("research-prompt", dependencies=[ref])
        plan = self.plan()
        self.assertEqual(plan["status"], "blocked")
        self.assertLessEqual(len(plan["materialRefs"]), 30)

    def test_snapshot_is_independent_of_later_material_edits(self):
        old = self.plan()
        self.store.edit("research-prompt", content="Changed after planning")
        self.assertNotIn("Changed after planning", old["instructions"])
        self.assertNotEqual(old["fingerprint"], self.plan()["fingerprint"])

    def test_policy_typos_and_implicit_production_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            Settings(db_url="unused", temporary_policy="manual-review")
        with self.assertRaises(ValueError):
            Settings(db_url="unused", demo=False, temporary_policy="unset")


if __name__ == "__main__":
    unittest.main()

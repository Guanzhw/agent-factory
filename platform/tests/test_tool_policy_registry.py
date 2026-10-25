"""Current adapter catalogs replace the retired secondary tool policy registry."""
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from agent_factory.execution_bindings import ExecutionBindings
from agent_factory.plan_policy import PlanPolicyConfig, PlanPolicyService, application_tool_catalog


class ToolPolicyRegistryTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(runtime_tool_contract="legacy-v1")
        self.store = SimpleNamespace(settings=self.settings, personal_tools=None, plan_policy=None)
        self.bindings = ExecutionBindings(self.settings, self.store)
        self.store.execution_bindings = self.bindings

    def test_current_installed_tool_requires_no_policy_registration(self):
        self.bindings.register("tool", "member.inventory", "1", lambda _: None,
            tool_name="inventory_lookup", permissions=("inventory:read",))
        self.assertEqual(application_tool_catalog(self.store)["inventory_lookup"], "inventory:read")
        self.bindings.withdraw("tool", "member.inventory", "1")
        self.assertNotIn("inventory_lookup", application_tool_catalog(self.store))

    def test_new_worker_catalog_reads_persisted_member_tools_without_factory_instantiation(self):
        self.store.personal_tools = SimpleNamespace(catalog_tools=lambda: {"custom_member_tool": "tool:invoke"})
        self.assertEqual(application_tool_catalog(self.store)["custom_member_tool"], "tool:invoke")
        self.assertEqual(self.bindings.describe(), [])

    def test_member_name_collision_does_not_rewrite_builtin_discovery_identity(self):
        self.store.personal_tools = SimpleNamespace(catalog_tools=lambda: {"checksum": "tool:invoke"})
        self.assertEqual(application_tool_catalog(self.store)["checksum"], "checksum:read")

    def test_runtime_scope_has_no_secondary_tool_name_or_capability_whitelist(self):
        plan = {"status": "ready", "missing": [], "tools": ["custom_member_tool"], "capabilities": ["tool:invoke"]}
        PlanPolicyService._scope(plan)
        with self.assertRaises(HTTPException): PlanPolicyService._scope({**plan, "status": "blocked"})
        with self.assertRaises(TypeError): PlanPolicyConfig(tool_policies=())

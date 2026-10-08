"""Operator registry and legacy identities, without factories, SQL or native runs."""
from dataclasses import FrozenInstanceError, asdict, replace
from types import SimpleNamespace
from typing import get_args
import unittest

from fastapi import HTTPException

from agent_factory.execution_bindings import AdapterRegistration, ExecutionBindings
from agent_factory.material_governance import GovernanceConfig, LICENSES
from agent_factory.plan_policy import (PlanPolicyConfig, PlanPolicyService, ToolContract, READ_ONLY_CAPABILITIES,
    application_tool_catalog, tools_for_contract)
from agent_factory.store import digest
from agent_factory.tool_policy_registry import (ToolPolicyRegistration, normalize_tool_policies,
    validate_tool_policies, policy_body, require_installed_policies, require_material_policy)


def registration(**changes):
    return replace(ToolPolicyRegistration('inventory_lookup', 'inventory:read', 'policy-1', True,
        'operator.inventory', '1'), **changes)


def adapter(policy):
    return AdapterRegistration('tool', policy.adapter_id, policy.adapter_revision,
        lambda _: None, tool_name=policy.name, permissions=(policy.capability,))


class ToolPolicyRegistryTests(unittest.TestCase):
    def test_empty_registration_preserves_all_legacy_fingerprints_and_bodies(self):
        for contract in get_args(ToolContract):
            for synthesis in (False, True):
                config = PlanPolicyConfig(revision='legacy-comparison', tool_contract=contract, source_synthesis_enabled=synthesis)
                body = policy_body(config)
                self.assertNotIn('tool_policies', body)
                if not synthesis: body.pop('source_synthesis_enabled')
                if contract == 'legacy-v1': body.pop('tool_contract')
                expected = digest({**body, 'knownTools': config.known_tools,
                    'readOnlyTools': sorted(config.read_only_tools), 'readOnlyCapabilities': sorted(READ_ONLY_CAPABILITIES)})
                self.assertEqual(config.fingerprint, expected)
                governance = GovernanceConfig(revision='legacy-comparison', tool_contract=contract, source_synthesis_enabled=synthesis)
                old = policy_body(governance)
                self.assertNotIn('tool_policies', old)
                if not synthesis: old.pop('source_synthesis_enabled')
                if contract == 'legacy-v1': old.pop('tool_contract')
                self.assertEqual(governance.fingerprint, digest({**old, 'licenses': LICENSES,
                    'toolBindings': governance.known_tools, 'schemaVersion': 'structured-material/v1'}))

    def test_frozen_exact_types_duplicates_and_builtin_collision(self):
        policy = registration()
        with self.assertRaises(FrozenInstanceError): policy.read_only = False  # type: ignore[misc]
        for field, value in (('read_only', 1), ('name', 'a b'), ('revision', True), ('capability', '')):
            with self.assertRaises(ValueError): registration(**{field: value})
        with self.assertRaises(ValueError): normalize_tool_policies((policy, policy))
        for contract in get_args(ToolContract):
            name, capability = next(iter(tools_for_contract(contract).items()))
            for cls in (PlanPolicyConfig, GovernanceConfig):
                with self.assertRaises(ValueError):
                    cls(tool_policies=(registration(name=name, capability=capability),))

    def test_new_tools_and_readonly_semantics_have_versioned_policy_identity(self):
        policy = registration()
        config = PlanPolicyConfig(tool_policies=(policy,))
        self.assertEqual(config.known_tools[policy.name], policy.capability)
        self.assertIn(policy.name, config.read_only_tools)
        self.assertIn(policy.capability, config.read_only_capabilities)
        writer = registration(name='inventory_write', read_only=False)
        both = replace(config, tool_policies=(writer, policy))
        self.assertNotIn(writer.name, both.read_only_tools)
        self.assertNotEqual(config.fingerprint, PlanPolicyConfig().fingerprint)
        self.assertNotEqual(config.fingerprint, replace(config, tool_policies=(replace(policy, revision='policy-2'),)).fingerprint)
        self.assertEqual(PlanPolicyConfig(**asdict(config)), config)
        self.assertEqual(GovernanceConfig(**asdict(GovernanceConfig(tool_policies=(policy,)))).tool_policies, (policy,))

    def test_adapter_identity_capability_and_current_withdrawal(self):
        policy = registration(); entry = adapter(policy)
        self.assertEqual(validate_tool_policies((policy,), (entry,)), (policy,))
        for changed in (replace(entry, tool_name='other'), replace(entry, permissions=('other:read',)),
                        replace(entry, revision='2'), replace(entry, permissions=(policy.capability, 'extra:write'))):
            with self.assertRaises(ValueError): validate_tool_policies((policy,), (changed,))
        settings = SimpleNamespace(tool_policies=(policy,), runtime_adapters=[entry], demo=False)
        store = SimpleNamespace(settings=settings, execution_bindings=None)
        require_installed_policies(store, (policy,))
        bindings = ExecutionBindings(settings, store)
        bindings.register('tool', entry.adapter_id, entry.revision, entry.factory,
                          tool_name=entry.tool_name, permissions=entry.permissions)
        store.execution_bindings = bindings
        self.assertEqual(application_tool_catalog(store)[policy.name], policy.capability)
        bindings.withdraw('tool', entry.adapter_id, entry.revision)
        with self.assertRaises(HTTPException): application_tool_catalog(store)
        settings.tool_policies = ()
        with self.assertRaises(HTTPException): require_installed_policies(store, (policy,))

    def test_material_and_plan_must_pin_exact_registered_adapter(self):
        policy = registration()
        material = {'kind': 'tool', 'content': policy.name, 'permissions': [policy.capability],
            'runtimeBinding': {'adapterId': policy.adapter_id, 'revision': policy.adapter_revision, 'config': {}}}
        require_material_policy(material, (policy,))
        for binding in ({}, {'adapterId': policy.adapter_id, 'revision': '2'}):
            with self.assertRaises(HTTPException): require_material_policy({**material, 'runtimeBinding': binding}, (policy,))
        plan = {'tools': [policy.name], 'capabilities': [policy.capability], 'status': 'ready', 'missing': [],
            'executionBindings': {'tools': [{'toolName': policy.name, 'adapterId': policy.adapter_id, 'revision': '1'}]}}
        PlanPolicyService._scope(plan, PlanPolicyConfig(tool_policies=(policy,)))
        for changed in ({'executionBindings': {'tools': []}}, {'capabilities': []}, {'tools': ['not_registered']}):
            with self.assertRaises(HTTPException): PlanPolicyService._scope({**plan, **changed}, PlanPolicyConfig(tool_policies=(policy,)))
        with self.assertRaises(HTTPException): PlanPolicyService._scope(plan, PlanPolicyConfig())

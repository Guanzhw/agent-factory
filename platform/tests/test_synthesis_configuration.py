"""Compatibility pins calculated from git baseline d4f5e6c, not current code."""
from dataclasses import replace
import unittest
from typing import Any

from agent_factory.config import Settings
from agent_factory.material_governance import GovernanceConfig
from agent_factory.plan_policy import PlanPolicyConfig, application_tool_catalog


class SynthesisConfigurationTests(unittest.TestCase):
    def test_disabled_preserves_exact_legacy_policy_and_governance_hashes(self):
        self.assertEqual(PlanPolicyConfig(source_synthesis_enabled=False).fingerprint,
                         'b03c7ab3571b7a01236685a940580a67197e4e91b236952bfb7a496b711fae72')
        self.assertEqual(GovernanceConfig(source_synthesis_enabled=False).fingerprint,
                         '84a5dd82dea562781e732c0884ed870971ddb4f8fb1257d3b75907f1411d283e')

    def test_disabled_preserves_exact_nonlegacy_policy_and_governance_hashes(self):
        self.assertEqual(PlanPolicyConfig(tool_contract='orx-evidence-v2',
            revision='synthesis-compat-evidence-v2', source_synthesis_enabled=False).fingerprint,
            '223c551c6afa8d42e6f143e214a17f8ed10bb61d91504da15aae28dcc7dc64e9')
        self.assertEqual(GovernanceConfig(tool_contract='orx-evidence-v2',
            revision='synthesis-compat-evidence-v2', source_synthesis_enabled=False).fingerprint,
            '42d679f63c37f3601b773253a6042b0376d207af9e13c5da4fc5673657e20501')

    def test_enabled_changes_each_fingerprint_and_only_adds_scoped_saver(self):
        for original in (PlanPolicyConfig(), GovernanceConfig(),
                         PlanPolicyConfig(tool_contract='orx-evidence-v2', revision='synthesis-compat-evidence-v2'),
                         GovernanceConfig(tool_contract='orx-evidence-v2', revision='synthesis-compat-evidence-v2')):
            with self.subTest(config=type(original).__name__, contract=original.tool_contract):
                enabled = replace(original, source_synthesis_enabled=True)
                self.assertNotEqual(enabled.fingerprint, original.fingerprint)
                self.assertEqual(enabled.known_tools, {**original.known_tools, 'save_literature_synthesis': 'research:read'})
                if isinstance(original, PlanPolicyConfig) and isinstance(enabled, PlanPolicyConfig):
                    self.assertEqual(enabled.read_only_tools, original.read_only_tools | {'save_literature_synthesis'})

    def test_application_catalog_addition_is_opt_in_and_exact(self):
        from types import SimpleNamespace
        for contract in ('legacy-v1', 'orx-evidence-v2'):
            disabled = SimpleNamespace(settings=SimpleNamespace(runtime_tool_contract=contract, source_synthesis_enabled=False))
            enabled = SimpleNamespace(settings=SimpleNamespace(runtime_tool_contract=contract, source_synthesis_enabled=True))
            self.assertEqual(application_tool_catalog(enabled),
                             {**application_tool_catalog(disabled), 'save_literature_synthesis': 'research:read'})

    def test_settings_reject_production_missing_or_nonreview_policy_and_nonboolean(self):
        base: dict[str, Any] = {'db_url': 'sqlite://', 'demo': True, 'temporary_policy': 'admin-review',
                                'source_synthesis_enabled': True}
        settings = Settings(**base)
        self.assertTrue(settings.source_synthesis_enabled)
        for changes in ({'demo': False}, {'temporary_policy': None}, {'temporary_policy': 'bounded-synthetic'},
                        {'temporary_policy': 'read-only-auto'}, {'temporary_policy': 'unset'},
                        {'source_synthesis_enabled': 1}, {'source_synthesis_enabled': 0},
                        {'source_synthesis_enabled': 'true'}, {'source_synthesis_enabled': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Settings(**{**base, **changes})
        self.assertFalse(Settings(db_url='sqlite://').source_synthesis_enabled)

    def test_policy_configs_reject_truthy_nonboolean_flags(self):
        invalid: list[Any] = [1, 0, 'true', None]
        for cls in (PlanPolicyConfig, GovernanceConfig):
            for value in invalid:
                with self.subTest(config=cls.__name__, value=value), self.assertRaises(ValueError):
                    cls(source_synthesis_enabled=value)


if __name__ == '__main__':
    unittest.main()

"""Member configuration fingerprints and application synthesis enablement."""
from dataclasses import replace
import unittest
from typing import Any

from agent_factory_research.config import ResearchSettings as Settings
from agent_factory.material_governance import GovernanceConfig
from agent_factory.plan_policy import PlanPolicyConfig, PlanPolicyService, application_tool_catalog
from agent_factory_research.policy_compatibility import ResearchPlanPolicyService


class SynthesisConfigurationTests(unittest.TestCase):
    def test_disabled_member_legacy_tool_contract_fingerprints(self):
        self.assertEqual(PlanPolicyConfig(name="member-self-service", revision="plan-policy-v1", source_synthesis_enabled=False).fingerprint,
                         '7e823c25a80082cefc9f45207b1ce078cd97bfbe96159ac98624a0ba8010e289')
        self.assertEqual(GovernanceConfig(review_mode="member-self-service", revision="material-governance-v1", source_synthesis_enabled=False).fingerprint,
                         '443c7229370d2ccee312096554b0f202a808bd1b68115c9687529e18ccbb3bbd')

    def test_disabled_member_evidence_tool_contract_fingerprints(self):
        self.assertEqual(PlanPolicyConfig(name='member-self-service', tool_contract='orx-evidence-v2',
            revision='synthesis-compat-evidence-v2', source_synthesis_enabled=False).fingerprint,
            '2e2f9e55353cbe90c031b7b32c3f6f139d09795336f1b1514d8317ae666db151')
        self.assertEqual(GovernanceConfig(review_mode='member-self-service', tool_contract='orx-evidence-v2',
            revision='synthesis-compat-evidence-v2', source_synthesis_enabled=False).fingerprint,
            '71ee9addd9564a22cfc5ea7680f785eb6629b37d073bc542c7252887a070373a')

    def test_enabled_changes_each_fingerprint_and_only_adds_scoped_saver(self):
        for original in (PlanPolicyConfig(), GovernanceConfig(),
                         PlanPolicyConfig(tool_contract='orx-evidence-v2', revision='synthesis-compat-evidence-v2'),
                         GovernanceConfig(tool_contract='orx-evidence-v2', revision='synthesis-compat-evidence-v2')):
            with self.subTest(config=type(original).__name__, contract=original.tool_contract):
                enabled = replace(original, source_synthesis_enabled=True)
                self.assertNotEqual(enabled.fingerprint, original.fingerprint)
                if isinstance(original, GovernanceConfig):
                    self.assertEqual(enabled.known_tools, {**original.known_tools, 'save_literature_synthesis': 'research:read'})
                else:
                    self.assertEqual(enabled.known_tools, original.known_tools)

    def test_application_catalog_addition_is_opt_in_and_exact(self):
        from types import SimpleNamespace
        for contract in ('legacy-v1', 'orx-evidence-v2'):
            disabled = SimpleNamespace(settings=SimpleNamespace(runtime_tool_contract=contract, source_synthesis_enabled=False))
            enabled = SimpleNamespace(settings=SimpleNamespace(runtime_tool_contract=contract, source_synthesis_enabled=True))
            for store in (disabled, enabled):
                store.plan_policy = ResearchPlanPolicyService.__new__(ResearchPlanPolicyService)
                store.plan_policy.store = store
            self.assertEqual(application_tool_catalog(enabled),
                             {**application_tool_catalog(disabled), 'save_literature_synthesis': 'research:read'})

    def test_core_catalog_does_not_read_research_settings(self):
        from types import SimpleNamespace
        class CoreSettings:
            runtime_tool_contract = 'legacy-v1'
            @property
            def source_synthesis_enabled(self):
                raise AssertionError('Core accessed a research application setting')
        store = SimpleNamespace(settings=CoreSettings())
        baseline = application_tool_catalog(store)
        store.plan_policy = PlanPolicyService.__new__(PlanPolicyService)
        self.assertEqual(application_tool_catalog(store), baseline)

    def test_settings_require_demo_member_policy_and_explicit_boolean(self):
        base: dict[str, Any] = {'db_url': 'sqlite://', 'demo': True, 'temporary_policy': 'member-self-service',
                                'source_synthesis_enabled': True}
        settings = Settings(**base)
        self.assertTrue(settings.source_synthesis_enabled)
        for changes in ({'demo': False}, {'temporary_policy': None}, {'temporary_policy': 'admin-review'}, {'temporary_policy': 'bounded-synthetic'},
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

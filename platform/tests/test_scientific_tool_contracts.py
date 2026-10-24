"""Installed scientific adapters advertise their explicit tool contracts."""
from types import SimpleNamespace
from typing import cast
import unittest

from agent_factory.config import Settings
from agent_factory.plan_policy import PlanPolicyConfig, ToolContract, application_tool_catalog


class ScientificToolContractTests(unittest.TestCase):
    def test_installed_scientific_tools_match_their_declared_contract(self):
        new = {'pubmed_sources_report', 'save_literature_synthesis'}
        for contract, expected in (('legacy-v1', set()), ('orx-evidence-v2', set()),
                ('registered-runtime-v1', set()), ('pubmed-host-evidence-v1', {'pubmed_sources_report'}),
                ('scientific-synthesis-fixture-v1', {'save_literature_synthesis'})):
            settings = Settings(db_url="postgresql+psycopg://fixture:fixture@127.0.0.1/fixture", runtime_tool_contract=contract, policy_revision='scientific-contract-test',
                                material_policy_revision='scientific-material-test')
            policy = PlanPolicyConfig(revision=settings.policy_revision, tool_contract=cast(ToolContract, contract))
            self.assertEqual(new & set(application_tool_catalog(SimpleNamespace(settings=settings))), expected)
            self.assertEqual(new & set(policy.known_tools), expected)
        with self.assertRaises(ValueError):
            PlanPolicyConfig(tool_contract=cast(ToolContract, 'unknown-scientific-contract'))

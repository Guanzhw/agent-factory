"""Final native-harness permission checks; no processes or model requests."""
from copy import deepcopy
import unittest

from agent_factory.runtime_packages.openresearch_v1.entry import (
    BUILTINS, LOCAL_TOOLS, PERMISSIONS, opencode_config, verify_effective_agent,
)


class PlatformOpenResearchRuntimeTests(unittest.TestCase):
    def agent(self):
        return {'name': 'build', 'model': {'providerID': 'factory', 'modelID': 'owner-model'},
            'permission': [{'permission': name, 'pattern': '*', 'action': action}
                for name, action in PERMISSIONS.items()],
            'tools': {name: name in LOCAL_TOOLS for name in BUILTINS}}

    def test_native_permissions_without_legacy_tool_merge(self):
        config = opencode_config('synthetic-owner-capability-0123456789')
        self.assertNotIn('tools', config)
        for name in ('factory', 'build', 'plan'):
            self.assertNotIn('tools', config['agent'][name])
        self.assertTrue(verify_effective_agent(self.agent(), 'build')['effectiveToolsVerified'])

    def test_reject_wildcard_order_and_inactive_tools_even_with_correct_config(self):
        agent = self.agent()
        agent['permission'].append({'permission': '*', 'pattern': '*', 'action': 'deny'})
        with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')
        for tool in ('bash', 'read', 'edit'):
            agent = self.agent(); agent['tools'][tool] = False
            with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')

    def test_reject_undeclared_external_tool_and_provider_fallback(self):
        agent = self.agent(); agent['tools']['unknown_external'] = True
        with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')
        for tool in ('webfetch', 'task', 'skill'):
            agent = deepcopy(self.agent())
            agent['permission'].append({'permission': tool, 'pattern': '*', 'action': 'allow'})
            agent['tools'][tool] = True
            with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')
        agent = self.agent(); agent['model']['providerID'] = 'fallback'
        with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')

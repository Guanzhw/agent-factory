"""Real Agno tool descriptors, no synthetic model or runtime dispatch."""
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import Mock

from agent_factory.workflow_profile import registrations, TOOLS
from agent_factory.workflow_contracts import workflow_fingerprint


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.definition = {'schema': 1, 'id': 'example', 'revision': '1', 'maxParallel': 1, 'stages': [
            {'id': 'stage', 'adapterId': 'runtime', 'revision': '1', 'dependencies': [], 'inputs': {}, 'failureRoutes': {}, 'humanGate': False}]}
        self.config = {'workflowId': 'example', 'workflowSha256': workflow_fingerprint(self.definition)}
        self.entries = registrations({'example': self.definition})
    def test_registered_tools_require_exact_definition_and_native_wait(self):
        self.assertEqual(tuple(entry.tool_name for entry in self.entries), TOOLS)
        run = SimpleNamespace(user_id='alice', session_id='task', run_id='native')
        for entry in self.entries:
            assert entry.validator is not None
            entry.validator(self.config)
            with self.assertRaises(ValueError): entry.validator({**self.config, 'workflowSha256': '0'*64})
            spec = {'config': self.config, 'adapterId': entry.adapter_id, 'revision': '1', 'toolName': entry.tool_name}
            ctx = SimpleNamespace(spec=spec, run_context=run, store=Mock(),
                plan={'ownerId': 'alice', 'executionBindings': {'tools': [spec]}})
            function = entry.factory(cast(Any, ctx))
            self.assertEqual(function.name, entry.tool_name)
            self.assertEqual(function.external_execution is True, entry.tool_name == 'workflow_wait')
    def test_no_model_registration_or_human_decision_tool(self):
        self.assertTrue(all(entry.kind == 'tool' for entry in self.entries))
        self.assertNotIn('workflow_decide', TOOLS)

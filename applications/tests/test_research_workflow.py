"""Fixed native component decisions: protocol checks, not live research evidence."""
import unittest

from pydantic import ValidationError
from agent_factory.native_workflows import _configuration
from research.workflow import Decision, Evaluation, ResearchWorkflow, decision


class ResearchWorkflowTests(unittest.TestCase):
    def test_registered_component_has_governed_steps_and_only_native_wait_tool(self):
        workflow = ResearchWorkflow()
        _configuration(workflow.registration)
        self.assertEqual({entry.tool_name for entry in workflow.tool_registrations},
            {*workflow.registration.tool_names, 'factory_wait_operations'})
        self.assertEqual(workflow.registration.component.id, 'research-round')

    def test_scientific_assessment_requires_evidence_but_negative_stop_can_precede_experiment(self):
        stopped = decision('{"action":"stop","outcome":"not_met","reason":"No feasible experiment"}', Decision)
        self.assertEqual(stopped.evidenceIds, [])
        with self.assertRaises(ValidationError):
            Decision(action='stop', outcome='met', reason='Claim without evidence')
        with self.assertRaises(ValidationError):
            Decision(action='experiment', reason='Missing bounded experiment')
        Evaluation(action='stop', outcome='not_met', reason='Actual negative result', evidenceIds=['original-operation'])
        with self.assertRaises(ValidationError):
            Evaluation(action='continue', outcome='met', reason='Inconsistent outcome', evidenceIds=['original-operation'])
        with self.assertRaises(ValidationError):
            Evaluation(action='stop', outcome='met', reason='No actual result', evidenceIds=[])

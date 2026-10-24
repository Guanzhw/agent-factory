"""Historical research disclosure cannot restore removed approval authority."""
import unittest
from unittest.mock import patch

from agent_factory.plan_policy import PlanPolicyConfig
from agent_factory_research.policy_compatibility import ResearchPlanPolicyService
import test_plan_policy as policy_fixture


class ResearchPolicyCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = policy_fixture.PlanPolicyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.service = ResearchPlanPolicyService(self.fixture.store, self.fixture.auth,
            PlanPolicyConfig(), clock=lambda: self.fixture.at)
        self.plan = self.fixture.store.add(application='personal-orx-project-create-v1',
            normalizedGoal='Retain the original project disclosure')

    def test_historical_formatter_survives_member_upgrade_without_reopening_review(self):
        disclosure = {'name': 'Synthetic original project'}
        with patch('agent_factory_research.personal_orx_projects.project_review_summary', return_value=disclosure) as formatter:
            review = policy_fixture.historical_review(self.service, self.plan)
            historical = self.service.inspect('alice', review['id'])
        formatter.assert_called_with(self.plan)
        self.assertEqual(historical['planSummary']['projectCreation'], disclosure)
        self.assertEqual(historical['planDigest'], review['plan_hash'])
        self.assertTrue(historical['planIntegrityMatches'])
        self.assertFalse(historical['currentPolicy'])
        self.assertFalse(historical['approvalEffective'])
        self.assertTrue(self.service.require_execution('alice', self.plan['id'])['allowed'])

    def test_unavailable_original_disclosure_keeps_historical_review_ineffective(self):
        review = policy_fixture.historical_review(self.service, self.plan)
        with patch('agent_factory_research.personal_orx_projects.project_review_summary', side_effect=ValueError('changed original pin')):
            historical = self.service.inspect('alice', review['id'])
        self.assertIsNone(historical['planSummary'])
        self.assertFalse(historical['planIntegrityMatches'])
        self.assertFalse(historical['approvalEffective'])

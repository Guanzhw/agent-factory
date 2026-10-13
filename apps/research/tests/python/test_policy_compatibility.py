"""Historical research disclosure cannot restore removed approval authority."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from agent_factory.plan_policy import PlanPolicyConfig
from agent_factory_research.policy_compatibility import ResearchPlanPolicyService
import test_plan_policy as policy_fixture


class ResearchPolicyCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = policy_fixture.PlanPolicyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.service = ResearchPlanPolicyService(self.fixture.store, self.fixture.auth,
            PlanPolicyConfig(name='admin-review', revision='plan-policy-v1'), clock=lambda: self.fixture.at)
        self.plan = self.fixture.store.add(application='personal-orx-project-create-v1',
            normalizedGoal='Retain the original project disclosure')

    def test_historical_formatter_survives_member_upgrade_without_reopening_review(self):
        disclosure = {'name': 'Synthetic original project'}
        with patch('agent_factory_research.personal_orx_projects.project_review_summary', return_value=disclosure) as formatter:
            review = self.service.request_review('alice', self.plan['id'], 'original')
            self.service.replace_configuration(PlanPolicyConfig(name='member-self-service', revision='members-v2'),
                expected_revision='plan-policy-v1')
            historical = self.service.inspect('alice', review['id'])
        formatter.assert_called_with(self.plan)
        self.assertEqual(historical['planSummary']['projectCreation'], disclosure)
        self.assertEqual(historical['planDigest'], review['planDigest'])
        self.assertTrue(historical['planIntegrityMatches'])
        self.assertFalse(historical['currentPolicy'])
        self.assertFalse(historical['approvalEffective'])
        with self.assertRaises(HTTPException) as denied:
            self.service.decide('manager', review['id'], True, 'do-not-reopen')
        self.assertEqual(denied.exception.status_code, 410)
        with self.assertRaises(HTTPException) as stale:
            self.service.require_execution('alice', self.plan['id'])
        self.assertIn('LEGACY_PLAN_READ_ONLY', stale.exception.detail)

    def test_unavailable_original_disclosure_keeps_historical_review_ineffective(self):
        with patch('agent_factory_research.personal_orx_projects.project_review_summary', side_effect=ValueError('changed original pin')):
            review = self.service.request_review('alice', self.plan['id'], 'original')
            self.assertIsNone(review['planSummary'])
            self.assertFalse(review['planIntegrityMatches'])
            with self.assertRaises(HTTPException) as denied:
                self.service.decide('manager', review['id'], True, 'missing-disclosure')
        self.assertEqual(denied.exception.detail, 'PLAN_REVIEW_SUMMARY_UNAVAILABLE')

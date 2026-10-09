"""No paid provider is constructed when the default-off profile is unavailable."""
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from agent_factory.billing_mode import ledger_for_plan, require_available
from agent_factory.byok_model import ADAPTER_ID
from agent_factory.config import Settings


class BillingModeTests(unittest.TestCase):
    def test_default_off_and_managed_paid_profiles_are_rejected(self):
        settings = Settings(db_url='postgresql://synthetic')
        self.assertFalse(settings.fee_management_enabled)
        self.assertFalse(settings.platform_paid_models_enabled)
        plans = [
            {'executionBindings': {'model': {'adapterId': 'go-development-deepseek-flash-v1', 'revision': '1'}}},
            {'application': 'autoresearch-goal-session-v1'},
            {'executionBindings': {'model': {'adapterId': 'managed-orx-pause-model-v1', 'revision': '1'}}},
        ]
        for plan in plans:
            with self.subTest(plan=plan), self.assertRaises(HTTPException): require_available(settings, plan)
        require_available(settings, {'executionBindings': {'model': {'adapterId': ADAPTER_ID, 'revision': '1'}}})

    def test_nonlocal_tariff_registration_and_byok_outside_legacy_ledger(self):
        settings = Settings(db_url='postgresql://synthetic', usage_pricing=(SimpleNamespace(
            adapter_id='synthetic-platform-model', adapter_revision='1', local_model_type=None),))
        with self.assertRaises(HTTPException):
            require_available(settings, {'executionBindings': {'model': {'adapterId': 'synthetic-platform-model', 'revision': '1'}}})
        store = SimpleNamespace(usage_ledger=object())
        self.assertIsNone(ledger_for_plan(store, {'executionBindings': {'model': {'adapterId': ADAPTER_ID}}}))
        self.assertIs(ledger_for_plan(store, {}), store.usage_ledger)
        with self.assertRaises(ValueError): Settings(db_url='postgresql://synthetic', platform_paid_models_enabled=True)

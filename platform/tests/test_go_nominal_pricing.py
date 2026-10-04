"""Offline nominal-accounting provenance; SQLite tests inspection, not admission."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

from agent_factory.go_development import MODEL_ADAPTER_IDS
from agent_factory.go_usage import pricing_registrations, request_guard
from agent_factory.store import digest
from agent_factory.usage_ledger import PricingRevision, UsageLedger


BASIS = "operator-nominal-not-invoice"


def price(**kwargs):
    return PricingRevision("synthetic-go", "1", "synthetic-provider", "deepseek-flash", "synthetic-v1",
        request_guard=request_guard, input_micros_per_million=1000000,
        output_micros_per_million=1000000, **kwargs)


class NominalPricingTests(unittest.TestCase):
    def test_none_preserves_exact_legacy_body_and_hash(self):
        expected = {"adapterId": "synthetic-go", "adapterRevision": "1", "provider": "synthetic-provider",
            "model": "deepseek-flash", "pricingRevision": "synthetic-v1", "currency": "USD",
            "inputMicrosPerMillion": 1000000, "outputMicrosPerMillion": 1000000,
            "perAttemptInputTokens": 32768, "perAttemptOutputTokens": 4096,
            "usageContract": "operator-provider-usage-v1"}
        for value in (price(), price(accounting_basis=None)):
            self.assertEqual(value.body, expected)
            self.assertEqual(value.sha256, digest(expected))
            self.assertNotIn("accountingBasis", value.body)

    def test_nominal_basis_changes_identity_without_claiming_invoice(self):
        legacy = price()
        nominal = replace(legacy, accounting_basis=BASIS)
        self.assertEqual(nominal.body, {**legacy.body, "accountingBasis": BASIS})
        self.assertNotEqual(legacy.sha256, nominal.sha256)
        self.assertEqual(legacy.charge(10, 5), nominal.charge(10, 5))
        self.assertEqual(nominal.accounting_basis, BASIS)
        with self.assertRaises(ValueError):
            price(accounting_basis="invoice-verified")

    def test_exact_deepseek_registration_is_explicit_nominal_revision(self):
        prices = {value.model: value for value in pricing_registrations(MODEL_ADAPTER_IDS)}
        exact = prices["deepseek-flash"]
        self.assertEqual(exact.adapter_id, MODEL_ADAPTER_IDS["deepseek-flash"])
        self.assertEqual(exact.body["accountingBasis"], BASIS)
        self.assertIn("nominal", exact.revision)
        self.assertGreater(exact.input_micros_per_million, 0)
        self.assertGreater(exact.output_micros_per_million, 0)
        self.assertIs(exact.request_guard, request_guard)
        self.assertNotEqual(exact.model, prices["deepseek-v4-flash"].model)
        self.assertNotEqual(exact.sha256, prices["deepseek-v4-flash"].sha256)

    def inspect_persisted(self, stored_price, current_price):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        commitment = {"schema": 1, "currency": "USD", "amountMicros": 100000, "tokenLimit": 10000,
            "provider": stored_price.provider, "model": stored_price.model,
            "adapterId": stored_price.adapter_id, "adapterRevision": stored_price.adapter_revision,
            "pricingRevision": stored_price.revision, "pricingSha256": stored_price.sha256,
            "inputMicrosPerMillion": stored_price.input_micros_per_million,
            "outputMicrosPerMillion": stored_price.output_micros_per_million,
            "perAttemptInputTokens": stored_price.per_attempt_input_tokens,
            "perAttemptOutputTokens": stored_price.per_attempt_output_tokens,
            "bindingSha256": "0" * 64, "policyRevision": "synthetic-policy"}
        commitment["sha256"] = digest(commitment)
        plan = {"id": "synthetic-plan", "usageBudget": commitment}
        store = SimpleNamespace(engine=engine, transaction=engine.begin,
            task=lambda task_id, owner: {"id": task_id, "plan_id": plan["id"]},
            plan=lambda plan_id, owner: plan)
        # PostgreSQL locking is deliberately out of scope for this read-only
        # provenance test. No reserve/settle/provider operation is performed.
        with patch.object(UsageLedger, "_lock", return_value=None):
            UsageLedger(store, prices=[stored_price])
            reopened = UsageLedger(store, prices=[current_price])
            self.assertEqual(reopened.prices[0], current_price)
            return reopened.inspect("alice", "synthetic-task")

    def test_inspection_uses_persisted_nominal_tariff_when_current_registry_is_legacy(self):
        nominal = price(accounting_basis=BASIS)
        current = replace(price(), revision="synthetic-new-legacy")
        facts = self.inspect_persisted(nominal, current)
        self.assertEqual(facts["pricingBasis"], BASIS)
        self.assertIs(facts["invoiceVerified"], False)
        self.assertEqual(facts["actualCostStatus"], "UNKNOWN")
        self.assertEqual(facts["commitment"]["pricingSha256"], nominal.sha256)
        self.assertEqual(facts["attempts"], [])

    def test_inspection_does_not_relabel_legacy_tariff_using_current_nominal_registry(self):
        legacy = price()
        current = replace(price(accounting_basis=BASIS), revision="synthetic-new-nominal")
        facts = self.inspect_persisted(legacy, current)
        self.assertNotIn("pricingBasis", facts)
        self.assertNotIn("invoiceVerified", facts)
        self.assertNotIn("actualCostStatus", facts)
        self.assertEqual(facts["commitment"]["pricingSha256"], legacy.sha256)

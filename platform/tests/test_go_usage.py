"""Local admission contracts; no sockets or credential reads."""
import unittest

import httpx
from agno.models.message import Message
from fastapi import HTTPException

from agent_factory.go_development import MODEL_ADAPTER_IDS
from agent_factory.go_usage import request_guard, pricing_registrations
from agent_factory.opencode_go import GoDevelopmentModel


class GoUsageTests(unittest.TestCase):
    def setUp(self):
        def forbidden(*args):
            self.fail("Admission must not access credentials or dispatch")
        self.model = GoDevelopmentModel(model_id="deepseek-v4-flash", session_id="synthetic-session",
            credential=forbidden, billing_verified=forbidden, async_transport=httpx.MockTransport(forbidden))
        self.commitment = {"perAttemptInputTokens": 32768, "perAttemptOutputTokens": 512}

    def test_valid_envelope_and_nonzero_exact_prices(self):
        request_guard(self.model, ([Message(role="user", content="Synthetic coding test")],), {}, self.commitment)
        prices = pricing_registrations(MODEL_ADAPTER_IDS)
        self.assertEqual(len(prices), 3)
        for price in prices:
            self.assertGreater(price.input_micros_per_million, 0)
            self.assertGreater(price.output_micros_per_million, 0)
            self.assertIs(price.request_guard, request_guard)
            self.assertEqual(price.accounting_basis, "operator-nominal-not-invoice")

    def test_oversized_input_and_changed_caps_fail_before_dispatch(self):
        with self.assertRaisesRegex(HTTPException, "GO_REQUEST_INPUT_BOUND"):
            request_guard(self.model, ([Message(role="user", content="x" * 32768)],), {}, self.commitment)
        for field, value in (("retries", 1), ("_timeout", 61), ("_cap", 513)):
            original = getattr(self.model, field)
            setattr(self.model, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(HTTPException, "GO_REQUEST_CONTRACT"):
                request_guard(self.model, ([Message(role="user", content="test")],), {}, self.commitment)
            setattr(self.model, field, original)

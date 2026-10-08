"""Offline durable campaign tests. No environment credentials or HTTP calls."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_factory.go_live import GoLiveCampaign, GoLiveGateError, MODELS


USAGE = {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}


def body(model, *, product=False):
    responses = model == MODELS[1]
    result = {"model": model, "stream": True, "input" if responses else "messages": [
        {"role": "user", "content": "Synthetic coding checksum validation."}],
        "max_output_tokens" if responses else "max_tokens": 128,
        **({"store": False} if responses else {"stream_options": {"include_usage": True}})}
    if product:
        function = {"name": "checksum", "description": "Hash synthetic text",
                    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}
        result["tools"] = [{"type": "function", **function}] if responses else [{"type": "function", "function": function}]
        result["parallel_tool_calls"] = False
    return result


@unittest.skipUnless(os.name == "posix", "Live campaign requires private POSIX file permissions")
class GoLiveGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "campaign.sqlite"
        self.campaign = GoLiveCampaign.create(self.path, campaign_id="synthetic-campaign", owner_id="alice",
            confirmation_id="synthetic-account-confirmation", expires_at=time.time() + 3600)

    def smoke(self, model=MODELS[0]):
        session = "smoke-" + model
        self.campaign.authorize(session, model, owner_id="alice")
        ticket = self.campaign.begin(session, model, body(model))
        self.campaign.finish(ticket, usage=USAGE, actual_model=model)

    def settle_model(self, model):
        self.smoke(model)
        session = "product-" + model
        self.campaign.authorize(session, model, purpose="product", owner_id="alice")
        for _ in range(2):
            ticket = self.campaign.begin(session, model, body(model, product=True))
            self.campaign.verify_ticket(ticket, session, model)
            self.campaign.finish(ticket, usage=USAGE, actual_model=model)

    def test_exact_six_requests_and_artifact_gated_model_order(self):
        with self.assertRaises(GoLiveGateError):
            self.campaign.preflight(MODELS[1], "alice")
        for model in MODELS:
            self.settle_model(model)
            with self.assertRaises(GoLiveGateError):
                self.campaign.begin("product-" + model, model, body(model, product=True))
            with self.assertRaises(GoLiveGateError):
                self.campaign.complete_model(model, "not-a-hash")
            self.campaign.complete_model(model, "a" * 64)
        result = GoLiveCampaign(self.path).inspect()
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(result["requestCount"], 6)
        self.assertEqual(result["modelCounts"], {model: 3 for model in MODELS})
        with self.assertRaises(GoLiveGateError):
            self.campaign.preflight(MODELS[0], "alice")

    def test_single_inflight_is_atomic_across_independent_handles(self):
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        def attempt(_):
            try:
                return GoLiveCampaign(self.path).begin("smoke-original", MODELS[0], body(MODELS[0]))
            except GoLiveGateError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            tickets = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(ticket is not None for ticket in tickets), 1)
        self.assertEqual(self.campaign.inspect()["requestCount"], 1)

    def test_restart_cannot_reset_or_replay_unfinished_ticket(self):
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        ticket = self.campaign.begin("smoke-original", MODELS[0], body(MODELS[0]))
        reopened = GoLiveCampaign(self.path)
        for operation in (lambda: reopened.begin("smoke-original", MODELS[0], body(MODELS[0])),
                          lambda: reopened.verify_ticket(ticket, "smoke-original", MODELS[0]),
                          lambda: reopened.authorize("new-session", MODELS[0], owner_id="alice")):
            with self.assertRaises(GoLiveGateError):
                operation()
        self.assertEqual(reopened.inspect()["requestCount"], 1)
        with self.assertRaises(GoLiveGateError):
            GoLiveCampaign.create(self.path, campaign_id="replacement", owner_id="alice",
                confirmation_id="other", expires_at=time.time() + 3600)
        self.assertEqual(reopened.inspect()["campaignId"], "synthetic-campaign")

    def test_read_only_preflight_allows_only_locally_owned_inflight(self):
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        ticket = self.campaign.begin("smoke-original", MODELS[0], body(MODELS[0]))
        before = self.campaign.inspect()
        self.campaign.preflight(MODELS[0], "alice")
        self.assertEqual(self.campaign.inspect(), before)
        for operation in (
            lambda: GoLiveCampaign(self.path).preflight(MODELS[0], "alice"),
            lambda: self.campaign.preflight(MODELS[0], "bob"),
            lambda: self.campaign.begin("smoke-original", MODELS[0], body(MODELS[0])),
            lambda: self.campaign.authorize("new-session", MODELS[0], owner_id="alice"),
            lambda: self.campaign.check("smoke-original", MODELS[0]),
        ):
            with self.assertRaises(GoLiveGateError):
                operation()
        self.campaign.finish(ticket, error_code="QUOTA")
        with self.assertRaises(GoLiveGateError):
            self.campaign.preflight(MODELS[0], "alice")

    def test_quota_auth_unknown_stop_all_models_and_survive_restart(self):
        for code in ("QUOTA", "AUTH", "USAGE_UNKNOWN", "TRANSPORT", "PROTOCOL"):
            with self.subTest(code=code):
                path = Path(self.directory.name) / (code + ".sqlite")
                gate = GoLiveCampaign.create(path, campaign_id=code, owner_id="alice", confirmation_id="fixture",
                                             expires_at=time.time() + 3600)
                gate.authorize("smoke-original", MODELS[0], owner_id="alice")
                ticket = gate.begin("smoke-original", MODELS[0], body(MODELS[0]))
                gate.finish(ticket, error_code=code)
                reopened = GoLiveCampaign(path)
                self.assertEqual(reopened.inspect()["tickets"][0]["state"], "UNKNOWN")
                for model in MODELS:
                    with self.assertRaises(GoLiveGateError):
                        reopened.authorize("another-session", model, owner_id="alice")

    def test_valid_incurred_usage_is_preserved_on_model_mismatch_and_error(self):
        for actual, error in ((MODELS[1], None), (None, "AUTH")):
            with self.subTest(actual=actual, error=error):
                path = Path(self.directory.name) / ("mismatch.sqlite" if error is None else "auth.sqlite")
                gate = GoLiveCampaign.create(path, campaign_id="fixture", owner_id="alice", confirmation_id="fixture",
                                             expires_at=time.time() + 3600)
                gate.authorize("smoke-original", MODELS[0], owner_id="alice")
                ticket = gate.begin("smoke-original", MODELS[0], body(MODELS[0]))
                gate.finish(ticket, usage=USAGE, actual_model=actual, error_code=error)
                state = gate.inspect()
                self.assertEqual(state["status"], "STOPPED")
                self.assertEqual(state["tickets"][0]["state"], "SETTLED")
                self.assertEqual(state["tickets"][0]["total_tokens"], 15)
                self.assertIsNone(state["tickets"][0]["actual_model"])

    def test_usage_over_bound_is_settled_but_campaign_stops(self):
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        ticket = self.campaign.begin("smoke-original", MODELS[0], body(MODELS[0]))
        self.campaign.finish(ticket, usage={"input_tokens": 40000, "output_tokens": 1000, "total_tokens": 41000},
                             actual_model=MODELS[0])
        state = self.campaign.inspect()
        self.assertEqual(state["stopCode"], "USAGE_BOUND")
        self.assertEqual(state["tickets"][0]["state"], "SETTLED")
        self.assertEqual(state["tickets"][0]["total_tokens"], 41000)
        self.assertEqual(state["tickets"][0]["actual_model"], MODELS[0])

    def test_ticket_verification_is_exact_and_stop_preserves_late_usage(self):
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        ticket = self.campaign.begin("smoke-original", MODELS[0], body(MODELS[0]))
        self.campaign.verify_ticket(ticket, "smoke-original", MODELS[0])
        for session, model in (("wrong-session", MODELS[0]), ("smoke-original", MODELS[1])):
            with self.assertRaises(GoLiveGateError):
                self.campaign.verify_ticket(ticket, session, model)
        self.campaign.stop("CANCELLED")
        with self.assertRaises(GoLiveGateError):
            self.campaign.verify_ticket(ticket, "smoke-original", MODELS[0])
        self.campaign.finish(ticket, usage=USAGE, actual_model=MODELS[0])
        self.assertEqual(self.campaign.inspect()["status"], "STOPPED")
        self.assertEqual(self.campaign.inspect()["tickets"][0]["state"], "SETTLED")

    def test_malformed_usage_stops_and_does_not_store_untrusted_model(self):
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        ticket = self.campaign.begin("smoke-original", MODELS[0], body(MODELS[0]))
        self.campaign.finish(ticket, usage={"input_tokens": True, "output_tokens": 3, "total_tokens": 4},
                             actual_model="untrusted-server-model-text")
        state = self.campaign.inspect()
        self.assertEqual(state["status"], "STOPPED")
        self.assertEqual(state["tickets"][0]["state"], "UNKNOWN")
        self.assertIsNone(state["tickets"][0]["actual_model"])
        self.assertNotIn(b"untrusted-server-model-text", self.path.read_bytes())

    def test_expiry_blocks_ticket_verification_and_new_admission_after_restart(self):
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        ticket = self.campaign.begin("smoke-original", MODELS[0], body(MODELS[0]))
        with patch("agent_factory.go_live.time.time", return_value=time.time() + 7200):
            with self.assertRaises(GoLiveGateError):
                self.campaign.verify_ticket(ticket, "smoke-original", MODELS[0])
            reopened = GoLiveCampaign(self.path)
            with self.assertRaises(GoLiveGateError):
                reopened.preflight(MODELS[0], "alice")
            self.assertEqual(reopened.inspect()["requestCount"], 1)

    def test_order_owner_session_and_product_limit_are_persistent(self):
        with self.assertRaises(GoLiveGateError):
            self.campaign.authorize("product-session", MODELS[0], purpose="product", owner_id="alice")
        with self.assertRaises(GoLiveGateError):
            self.campaign.authorize("smoke-original", MODELS[0], owner_id="bob")
        self.smoke()
        self.campaign.authorize("product-original", MODELS[0], purpose="product", owner_id="alice")
        with self.assertRaises(GoLiveGateError):
            GoLiveCampaign(self.path).authorize("product-new-task", MODELS[0], purpose="product", owner_id="alice")
        with self.assertRaises(GoLiveGateError):
            self.campaign.complete_model(MODELS[0], "a" * 64)

    def test_body_bounds_and_tool_surprises_refused_before_reservation(self):
        self.smoke()
        self.campaign.authorize("product-original", MODELS[0], purpose="product", owner_id="alice")
        valid = body(MODELS[0], product=True)
        variants = []
        for key, value in (("model", MODELS[1]), ("stream", False), ("max_tokens", 513),
                           ("parallel_tool_calls", True), ("url", "https://unapproved.invalid"),
                           ("messages", [{"role": "user", "content": "x" * 8192}])):
            invalid = copy.deepcopy(valid)
            invalid[key] = value
            variants.append(invalid)
        invalid = copy.deepcopy(valid)
        invalid["tools"][0]["function"]["name"] = "shell"
        variants.append(invalid)
        for invalid in variants:
            with self.subTest(invalid_keys=list(invalid)):
                with self.assertRaises(GoLiveGateError):
                    self.campaign.begin("product-original", MODELS[0], invalid)
                self.assertEqual(self.campaign.inspect()["requestCount"], 1)

    def test_file_private_and_no_prompt_persistence(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.campaign.authorize("smoke-original", MODELS[0], owner_id="alice")
        request = body(MODELS[0])
        request["messages"][0]["content"] = "PUBLIC_SYNTHETIC_CONTENT_NOT_TO_PERSIST"
        self.campaign.begin("smoke-original", MODELS[0], request)
        self.assertNotIn(b"PUBLIC_SYNTHETIC_CONTENT_NOT_TO_PERSIST", self.path.read_bytes())
        self.assertNotIn("messages", json.dumps(self.campaign.inspect()))

    def test_unknown_error_text_is_not_persisted(self):
        self.campaign.stop("untrusted provider exception body")
        self.assertEqual(self.campaign.inspect()["stopCode"], "UNKNOWN")
        self.assertNotIn(b"untrusted provider exception body", self.path.read_bytes())

    def test_billing_attestation_and_expiry_fail_closed(self):
        for changed in ({"use_balance_disabled": False}, {"auto_reload_disabled": False},
                        {"expires_at": time.time() + 90000}, {"expires_at": float("nan")}):
            with self.subTest(changed=changed):
                values = {"campaign_id": "fixture", "owner_id": "alice", "confirmation_id": "fixture",
                          "expires_at": time.time() + 3600, **changed}
                with self.assertRaises(GoLiveGateError):
                    GoLiveCampaign.create(Path(self.directory.name) / "invalid.sqlite", **values)


if __name__ == "__main__":
    unittest.main()

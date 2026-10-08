"""Offline policy migration and admission tests; synthetic private databases."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import time
import unittest

from agent_factory.go_final_smoke import GoFinalSmokeCampaign
from agent_factory.go_live import GoLiveCampaign, GoLiveGateError
from agent_factory.go_project_campaign import GoProjectCampaign
from agent_factory.go_single_smoke import GoSingleSmokeCampaign


def body(model="deepseek-flash", cap=64):
    if model == "gpt-6-luna":
        return {"model": model, "stream": True, "input": [{"role": "user", "content": "synthetic coding"}], "max_output_tokens": cap, "store": False}
    return {"model": model, "stream": True, "messages": [{"role": "user", "content": "synthetic coding"}], "max_tokens": cap, "stream_options": {"include_usage": True}}


@unittest.skipUnless(os.name == "posix", "Private policy files require POSIX permissions")
class ProjectCampaignTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source = Path(folder.name) / "history.sqlite"
        original = GoLiveCampaign.create(self.source, campaign_id="history", owner_id="alice", confirmation_id="original", expires_at=time.time()+600)
        original.authorize("historical", "deepseek-v4-flash", owner_id="alice")
        original.finish(original.begin("historical", "deepseek-v4-flash", body("deepseek-v4-flash")), error_code="UNKNOWN")
        self.path = Path(str(self.source)+".budget.sqlite")
        second = GoSingleSmokeCampaign.create(self.path, history_path=self.source, campaign_id="continuation", owner_id="alice", confirmation_id="second", expires_at=time.time()+600)
        second.authorize("stable", "deepseek-flash", owner_id="alice")
        second.finish(second.begin("stable", "deepseek-flash", body()), error_code="UNKNOWN")
        third = GoFinalSmokeCampaign.authorize_final(self.path, owner_id="alice", confirmation_id="third")
        third.finish(third.begin("stable", "deepseek-flash", body()), error_code="PROTOCOL")
        with third._transaction(write=False) as db:
            self.history = [dict(r) for r in db.execute("SELECT * FROM tickets ORDER BY ordinal")]
        self.source_bytes = self.source.read_bytes()

    def migrate(self):
        return GoProjectCampaign.migrate(self.path, owner_id="alice", confirmation_id="subscription")

    def settle(self, policy, model="deepseek-flash", session="stable"):
        ticket = policy.begin(session, model, body(model))
        policy.verify_ticket(ticket, session, model)
        policy.preflight(model, "alice")
        policy.finish(ticket, usage={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}, actual_model=model)
        return ticket

    def test_migration_preserves_history_and_repeated_admission_no_lifetime_cap(self):
        policy = self.migrate()
        for _ in range(5):
            self.settle(policy)
        policy.authorize("luna", "gpt-6-luna", owner_id="alice")
        self.settle(policy, "gpt-6-luna", "luna")
        policy.authorize("new-task", "deepseek-flash", owner_id="alice")
        policy.check("new-task", "deepseek-flash")
        facts = policy.inspect()
        self.assertEqual(facts["budgetCounts"], {"deepseek": 8, "gpt-6-luna": 1})
        self.assertEqual(facts["tickets"][:3], self.history)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertIsNone(facts["perModelRequestCap"])
        self.assertEqual(self.migrate().inspect()["requestCount"], 9)
        self.assertEqual(len(self.migrate().inspect()["projectPolicy"]["events"]), 1)
        with self.assertRaises(GoLiveGateError):
            with policy._transaction() as db:
                db.execute("UPDATE tickets SET state='SETTLED' WHERE ordinal=3")

    def test_unknown_stops_and_review_never_replays_or_mutates_ticket(self):
        policy = self.migrate()
        ticket = policy.begin("stable", "deepseek-flash", body())
        policy.finish(ticket, error_code="PROTOCOL")
        unknown = policy.inspect()["tickets"][-1]
        with self.assertRaises(GoLiveGateError):
            policy.begin("stable", "deepseek-flash", body())
        self.assertEqual(self.migrate().inspect()["status"], "STOPPED")
        policy.acknowledge_stop(reason="PROTOCOL_FIX_REVIEWED", owner_id="alice")
        with self.assertRaises(GoLiveGateError):
            policy.finish(ticket, usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, actual_model="deepseek-flash")
        self.settle(policy)
        self.assertEqual(policy.inspect()["tickets"][3], unknown)

    def test_auth_quota_and_bad_reason_fail_closed(self):
        policy = self.migrate()
        policy.stop("AUTH")
        with self.assertRaises(GoLiveGateError):
            policy.acknowledge_stop(reason="DIAGNOSTICS_REVIEWED", owner_id="alice")
        self.assertEqual(self.migrate().inspect()["stopCode"], "AUTH")
        with self.assertRaises(GoLiveGateError):
            policy.acknowledge_stop(reason="secret-payload", owner_id="alice")

    def test_owner_session_model_output_and_purpose_validation(self):
        policy = self.migrate()
        for operation in (
            lambda: GoProjectCampaign.migrate(self.path, owner_id="mallory", confirmation_id="x"),
            lambda: policy.authorize("stable", "gpt-6-luna", owner_id="alice"),
            lambda: policy.authorize("luna", "gpt-6-luna", owner_id="mallory"),
            lambda: policy.authorize("legacy", "deepseek-v4-flash", owner_id="alice"),
            lambda: policy.authorize("product", "deepseek-flash", purpose="product", owner_id="alice"),
            lambda: policy.begin("stable", "deepseek-flash", body(cap=4097)),
            lambda: policy.begin("stable", "deepseek-flash", body(cap=True)),
        ):
            with self.assertRaises(GoLiveGateError):
                operation()
        self.assertEqual(policy.inspect()["requestCount"], 3)
        ticket = policy.begin("stable", "deepseek-flash", body(cap=4096))
        policy.finish(ticket, usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, actual_model="deepseek-flash")
        policy.authorize("product", "deepseek-flash", purpose="product", owner_id="alice")
        for _ in range(3):
            self.settle(policy, session="product")

    def test_concurrent_dispatch_serial_and_reopen_never_owns_inflight(self):
        policy = self.migrate()
        def attempt(_):
            try:
                return GoProjectCampaign(self.path).begin("stable", "deepseek-flash", body())
            except GoLiveGateError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = [r for r in pool.map(attempt, range(4)) if r]
        self.assertEqual(len(winners), 1)
        with self.assertRaises(GoLiveGateError):
            policy.verify_ticket(winners[0], "stable", "deepseek-flash")
        with self.assertRaises(GoLiveGateError):
            self.settle(policy)
        self.assertEqual(policy.inspect()["requestCount"], 4)

    def test_usage_unknown_review_retains_usage_and_redacts_unknown_model(self):
        policy = self.migrate()
        ticket = policy.begin("stable", "deepseek-flash", body())
        policy.finish(ticket, actual_model="deepseek-flash")
        self.assertEqual(policy.inspect()["stopCode"], "USAGE_UNKNOWN")
        policy.acknowledge_stop(reason="DIAGNOSTICS_REVIEWED", owner_id="alice")
        ticket = policy.begin("stable", "deepseek-flash", body())
        policy.finish(ticket, actual_model="secret-payload", error_code="secret-payload")
        self.assertNotIn("secret-payload", str(policy.inspect()))
        self.assertEqual(policy.inspect()["budgetCounts"]["deepseek"], 5)

    def test_quota_stop_cannot_be_cleared_on_reopen(self):
        policy = self.migrate()
        policy.stop("QUOTA")
        reopened = self.migrate()
        with self.assertRaises(GoLiveGateError):
            reopened.acknowledge_stop(reason="PROTOCOL_FIX_REVIEWED", owner_id="alice")
        self.assertEqual(reopened.inspect()["stopCode"], "QUOTA")

    def test_product_tool_results_repeat_across_tasks_and_keep_legacy_sessions(self):
        policy = self.migrate()
        self.settle(policy)
        with policy._transaction(write=False) as db:
            legacy = [tuple(r) for r in db.execute("SELECT * FROM sessions")]
        for session in ("task-one", "task-two"):
            policy.authorize(session, "deepseek-flash", purpose="product", owner_id="alice")
            request = body()
            request["messages"] += [
                {"role": "assistant", "content": None, "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "checksum", "arguments": '{"text":"fixture"}'}}]},
                {"role": "tool", "tool_call_id": "call1", "content": "synthetic-digest"},
            ]
            ticket = policy.begin(session, "deepseek-flash", request)
            policy.finish(ticket, usage={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}, actual_model="deepseek-flash")
        with policy._transaction(write=False) as db:
            self.assertEqual([tuple(r) for r in db.execute("SELECT * FROM sessions")], legacy)
        self.assertEqual(policy.inspect()["requestCount"], 6)

    def test_explicit_billing_stop_is_retained_not_mapped_to_reviewable_unknown(self):
        policy = self.migrate()
        policy.stop("BILLING")
        with self.assertRaises(GoLiveGateError):
            self.migrate().acknowledge_stop(reason="DIAGNOSTICS_REVIEWED", owner_id="alice")
        self.assertEqual(policy.inspect()["stopCode"], "BILLING")

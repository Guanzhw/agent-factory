"""Synthetic SQLite-only final-authority tests; no credentials or HTTP."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_factory.go_final_smoke import GoFinalSmokeCampaign
from agent_factory.go_live import GoLiveCampaign, GoLiveGateError
from agent_factory.go_single_smoke import GoSingleSmokeCampaign


MODEL = "deepseek-flash"


def body(model=MODEL):
    return {"model": model, "stream": True, "max_tokens": 64,
            "messages": [{"role": "user", "content": "Synthetic coding smoke"}],
            "stream_options": {"include_usage": True}}


@unittest.skipUnless(os.name == "posix", "Private campaign files require POSIX permissions")
class FinalSmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        source = Path(self.directory.name) / "source.sqlite"
        history = GoLiveCampaign.create(source, campaign_id="synthetic-history", owner_id="alice",
            confirmation_id="synthetic-confirmation", expires_at=time.time() + 600)
        history.authorize("historical-session", "deepseek-v4-flash", owner_id="alice")
        first = history.begin("historical-session", "deepseek-v4-flash", body("deepseek-v4-flash"))
        history.finish(first, error_code="UNKNOWN")
        self.path = Path(str(source) + ".budget.sqlite")
        self.previous = GoSingleSmokeCampaign.create(self.path, history_path=source,
            campaign_id="synthetic-continuation", owner_id="alice", confirmation_id="synthetic-second",
            expires_at=time.time() + 600)
        self.previous.authorize("stable-existing-session", MODEL, owner_id="alice")
        second = self.previous.begin("stable-existing-session", MODEL, body())
        self.previous.finish(second, error_code="UNKNOWN")
        self.original_inode = self.path.stat().st_ino
        self.old_facts = self.rows(self.previous)

    @staticmethod
    def rows(campaign):
        with campaign._transaction(write=False) as db:
            return [dict(row) for row in db.execute("SELECT * FROM tickets ORDER BY ordinal")]

    def authorize(self):
        return GoFinalSmokeCampaign.authorize_final(self.path, owner_id="alice", confirmation_id="synthetic-final")

    def test_once_same_file_same_session_and_exact_third_ticket(self):
        final = self.authorize()
        self.assertEqual(final.final_session, "stable-existing-session")
        self.assertEqual(self.path.stat().st_ino, self.original_inode)
        facts = final.inspect()
        self.assertEqual(facts["status"], "ACTIVE")
        self.assertEqual(facts["requestCount"], 2)
        self.assertEqual(facts["authorizedStepCap"], 3)
        self.assertEqual(facts["finalAuthorization"]["previousStatus"], "STOPPED")
        self.assertEqual(facts["finalAuthorization"]["previousStopCode"], "UNKNOWN")
        self.assertEqual(self.rows(final), self.old_facts)
        final.authorize(final.final_session, MODEL, owner_id="alice")
        ticket = final.begin(final.final_session, MODEL, body())
        final.verify_ticket(ticket, final.final_session, MODEL)
        final.preflight(MODEL, "alice")
        final.finish(ticket, usage={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}, actual_model=MODEL)
        facts = final.inspect()
        self.assertEqual(facts["status"], "DONE")
        self.assertEqual(facts["budgetCounts"]["deepseek"], 3)
        self.assertEqual([row["imported"] for row in facts["tickets"]], [True, True, False])
        self.assertEqual([row["state"] for row in facts["tickets"]], ["UNKNOWN", "UNKNOWN", "SETTLED"])
        self.assertEqual(self.rows(final)[:2], self.old_facts)
        with self.assertRaises(GoLiveGateError):
            final.begin(final.final_session, MODEL, body())

    def test_reopen_or_reauthorize_cannot_restore_authority_even_before_dispatch(self):
        final = self.authorize()
        reopened = GoFinalSmokeCampaign(self.path)
        for operation in (
            lambda: self.authorize(),
            lambda: reopened.authorize(reopened.final_session, MODEL, owner_id="alice"),
            lambda: reopened.begin(reopened.final_session, MODEL, body()),
            lambda: GoFinalSmokeCampaign.create(Path(self.directory.name) / "new-budget.sqlite"),
        ):
            with self.assertRaises(GoLiveGateError):
                operation()
        self.assertEqual(final.inspect()["requestCount"], 2)

    def test_concurrent_final_authorization_and_dispatch_have_one_winner_each(self):
        def grant(_):
            try:
                return self.authorize()
            except GoLiveGateError:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            grants = [value for value in pool.map(grant, range(6)) if value is not None]
        self.assertEqual(len(grants), 1)
        final = grants[0]
        def dispatch(_):
            try:
                return final.begin(final.final_session, MODEL, body())
            except GoLiveGateError:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            tickets = [value for value in pool.map(dispatch, range(6)) if value is not None]
        self.assertEqual(len(tickets), 1)
        self.assertEqual(final.inspect()["requestCount"], 3)
        self.assertEqual(self.rows(final)[:2], self.old_facts)
        reopened = GoFinalSmokeCampaign(self.path)
        with self.assertRaises(GoLiveGateError):
            reopened.verify_ticket(tickets[0], reopened.final_session, MODEL)

    def test_historical_tickets_and_final_authorization_cannot_be_modified(self):
        final = self.authorize()
        for ordinal in (1, 2):
            for statement in ("UPDATE tickets SET state='SETTLED' WHERE ordinal=:ordinal",
                              "DELETE FROM tickets WHERE ordinal=:ordinal"):
                with self.subTest(ordinal=ordinal, statement=statement), self.assertRaises(GoLiveGateError):
                    with final._transaction() as db:
                        db.execute(statement, {"ordinal": ordinal})
            with self.assertRaises(GoLiveGateError):
                final.finish(self.old_facts[ordinal - 1]["id"], usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, actual_model=MODEL)
        for statement in ("UPDATE final_authorization SET request_cap=3", "DELETE FROM final_authorization"):
            with self.assertRaises(GoLiveGateError):
                with final._transaction() as db:
                    db.execute(statement)
        self.assertEqual(self.rows(final), self.old_facts)

    def test_failed_third_attempt_keeps_all_unknown_and_cannot_be_reauthorized(self):
        final = self.authorize()
        ticket = final.begin(final.final_session, MODEL, body())
        final.finish(ticket, error_code="QUOTA")
        state = final.inspect()
        self.assertEqual((state["status"], state["stopCode"]), ("STOPPED", "QUOTA"))
        self.assertEqual([row["state"] for row in state["tickets"]], ["UNKNOWN"] * 3)
        self.assertEqual(state["finalAuthorization"]["previousStopCode"], "UNKNOWN")
        self.assertEqual(self.rows(final)[:2], self.old_facts)
        with self.assertRaises(GoLiveGateError):
            self.authorize()

    def test_wrong_owner_scope_session_and_bounds_do_not_reserve(self):
        with self.assertRaises(GoLiveGateError):
            GoFinalSmokeCampaign.authorize_final(self.path, owner_id="bob", confirmation_id="synthetic-final")
        final = self.authorize()
        for operation in (
            lambda: final.authorize("replacement-session", MODEL, owner_id="alice"),
            lambda: final.authorize(final.final_session, MODEL, purpose="product", owner_id="alice"),
            lambda: final.begin(final.final_session, "gpt-6-luna", body("gpt-6-luna")),
            lambda: final.begin(final.final_session, MODEL, {**body(), "max_tokens": 65}),
        ):
            with self.assertRaises(GoLiveGateError):
                operation()
        self.assertEqual(final.inspect()["requestCount"], 2)

    def test_diagnostic_failure_after_reservation_cannot_release_third_slot(self):
        final = self.authorize()
        with patch.object(final, "record_event", side_effect=OSError("synthetic persistence failure")):
            with self.assertRaises(OSError):
                final.begin(final.final_session, MODEL, body())
        state = final.inspect()
        self.assertEqual(state["status"], "STOPPED")
        self.assertEqual(state["requestCount"], 3)
        self.assertEqual(state["tickets"][-1]["state"], "UNKNOWN")
        self.assertEqual(self.rows(final)[:2], self.old_facts)


if __name__ == "__main__":
    unittest.main()

import concurrent.futures
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from agent_factory.go_live import GoLiveCampaign, GoLiveGateError
from agent_factory.go_single_smoke import GoSingleSmokeCampaign


def body(model="deepseek-flash"):
    return {"model": model, "stream": True, "messages": [{"role": "user", "content": "Write a Python add function."}], "max_tokens": 32, "stream_options": {"include_usage": True}}


def historical(path):
    c = GoLiveCampaign.create(path, campaign_id="old", owner_id="alice", confirmation_id="confirmed", expires_at=time.time()+600)
    c.authorize("old-session", "deepseek-v4-flash", owner_id="alice")
    ticket = c.begin("old-session", "deepseek-v4-flash", body("deepseek-v4-flash"))
    c.finish(ticket, error_code="UNKNOWN")
    return ticket


@unittest.skipUnless(os.name == "posix", "Private journal requires POSIX")
class GoSingleSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)/"old.sqlite"
        self.old_ticket = historical(self.source)
        self.old_bytes = self.source.read_bytes(), self.source.stat().st_mtime_ns
        self.path = Path(str(self.source)+".budget.sqlite")

    def create(self):
        return GoSingleSmokeCampaign.create(self.path, history_path=self.source, campaign_id="new", owner_id="alice", confirmation_id="confirmed", expires_at=time.time()+600)

    def test_imported_unknown_is_immutable_and_not_replayable(self):
        c = self.create()
        self.assertEqual(c.inspect()["budgetCounts"]["deepseek"], 1)
        with self.assertRaises(GoLiveGateError):
            c.verify_ticket(self.old_ticket, "old-session", "deepseek-flash")
        with self.assertRaises(GoLiveGateError):
            c.finish(self.old_ticket)
        with sqlite3.connect(self.path) as db:
            for sql in ("DELETE FROM tickets", "UPDATE tickets SET state='SETTLED'", "DELETE FROM continuation", "UPDATE continuation SET step_cap=3"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
        self.assertEqual(self.old_bytes, (self.source.read_bytes(), self.source.stat().st_mtime_ns))

    def test_concurrent_reservation_exactly_one_and_cancel_retains_two(self):
        c = self.create()
        c.authorize("new-session", "deepseek-flash", owner_id="alice")
        def reserve(_):
            try:
                return c.begin("new-session", "deepseek-flash", body())
            except GoLiveGateError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            tickets = [v for v in pool.map(reserve, range(8)) if v]
        self.assertEqual(len(tickets), 1)
        self.assertNotEqual(tickets[0], self.old_ticket)
        c.stop("CANCELLED")
        reopened = GoSingleSmokeCampaign(self.path)
        self.assertEqual(reopened.inspect()["budgetCounts"]["deepseek"], 2)
        self.assertEqual([t["state"] for t in reopened.inspect()["tickets"]], ["UNKNOWN", "UNKNOWN"])
        with self.assertRaises(GoLiveGateError):
            reopened.begin("new-session", "deepseek-flash", body())

    def test_new_directory_or_campaign_cannot_reset_budget(self):
        self.create()
        with self.assertRaises(GoLiveGateError):
            self.create()
        with self.assertRaises(GoLiveGateError):
            GoSingleSmokeCampaign.create(Path(self.tmp.name)/"other.sqlite", history_path=self.source, campaign_id="other", owner_id="alice", confirmation_id="confirmed", expires_at=time.time()+600)
        with self.assertRaises(GoLiveGateError):
            GoSingleSmokeCampaign(self.path).authorize("new-session", "deepseek-flash", owner_id="alice")

    def test_wrong_owner_fails_before_budget_creation(self):
        with self.assertRaises(GoLiveGateError):
            GoSingleSmokeCampaign.create(self.path, history_path=self.source, campaign_id="new", owner_id="bob", confirmation_id="confirmed", expires_at=time.time()+600)
        self.assertFalse(self.path.exists())

    def test_success_is_single_only_and_price_remains_unknown(self):
        c = self.create()
        c.authorize("new-session", "deepseek-flash", owner_id="alice")
        ticket = c.begin("new-session", "deepseek-flash", body())
        c.finish(ticket, usage={"input_tokens": 8,"output_tokens": 4,"total_tokens": 12},actual_model="deepseek-flash")
        result = c.inspect()
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(result["pricingStatus"], "UNKNOWN")
        self.assertIsNone(result["monetaryUpperBound"])
        with self.assertRaises(GoLiveGateError):
            c.begin("new-session", "deepseek-flash", body())

    def test_model_mismatch_preserves_safe_observation_and_usage(self):
        c = self.create()
        c.authorize("new-session", "deepseek-flash", owner_id="alice")
        ticket = c.begin("new-session", "deepseek-flash", body())
        c.finish(ticket, usage={"input_tokens": 8,"output_tokens": 4,"total_tokens": 12},actual_model="deepseek-v4-flash")
        result = c.inspect()
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(result["stopCode"], "MODEL_MISMATCH")
        self.assertEqual(result["tickets"][-1]["actual_model"], "deepseek-v4-flash")
        self.assertEqual(result["tickets"][-1]["total_tokens"], 12)
        c.stop("UNKNOWN")
        self.assertEqual(c.inspect()["stopCode"], "MODEL_MISMATCH")

    def test_crash_after_reservation_cannot_replay(self):
        code = '''import os,sys,time
from agent_factory.go_single_smoke import GoSingleSmokeCampaign
c=GoSingleSmokeCampaign.create(sys.argv[2],history_path=sys.argv[1],campaign_id='crash',owner_id='alice',confirmation_id='yes',expires_at=time.time()+600)
c.authorize('new-session','deepseek-flash',owner_id='alice')
c.begin('new-session','deepseek-flash',{'model':'deepseek-flash','stream':True,'messages':[{'role':'user','content':'Write add.'}],'max_tokens':32,'stream_options':{'include_usage':True}})
os._exit(0)
'''
        subprocess.run([sys.executable,"-c",code,str(self.source),str(self.path)],check=True)
        reopened = GoSingleSmokeCampaign(self.path)
        self.assertEqual(reopened.inspect()["requestCount"], 2)
        self.assertEqual(reopened.inspect()["tickets"][-1]["state"], "INFLIGHT")
        self.assertEqual(reopened.inspect()["diagnostics"]["events"][-1]["phase"], "PREPARED")
        with self.assertRaises(GoLiveGateError):
            reopened.verify_ticket(reopened.inspect()["tickets"][-1]["id"], "new-session", "deepseek-flash")

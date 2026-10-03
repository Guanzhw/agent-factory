"""Synthetic-only diagnostics admission/crash compatibility checks."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_factory.go_live import GoLiveCampaign, GoLiveGateError, MODELS


def request_body():
    return {"model": MODELS[0], "stream": True, "messages": [{"role": "user", "content": "Synthetic coding test"}],
            "max_tokens": 32, "stream_options": {"include_usage": True}}


@unittest.skipUnless(os.name == "posix", "Private POSIX campaign storage")
class GoDiagnosticCampaignTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "campaign.sqlite"
        self.campaign = GoLiveCampaign.create(self.path, campaign_id="synthetic-diagnostics", owner_id="alice",
            confirmation_id="synthetic-confirmation", expires_at=time.time() + 3600)
        self.campaign.authorize("synthetic-smoke", MODELS[0], owner_id="alice")

    def test_prepared_is_persisted_without_claiming_dispatch(self):
        ticket = self.campaign.begin("synthetic-smoke", MODELS[0], request_body())
        events = self.campaign.inspect()["diagnostics"]["events"]
        self.assertEqual([event["phase"] for event in events], ["PREPARED"])
        self.assertEqual(events[0]["requestId"], ticket)
        self.assertEqual(self.campaign.inspect()["requestCount"], 1)
        self.assertEqual(self.campaign.inspect()["tickets"][0]["state"], "INFLIGHT")

    def test_prepared_persistence_failure_retains_slot_and_stops(self):
        with patch.object(self.campaign.journal, "record", side_effect=OSError("synthetic-write-failure")):
            with self.assertRaises(GoLiveGateError):
                self.campaign.begin("synthetic-smoke", MODELS[0], request_body())
        proof = GoLiveCampaign(self.path).inspect()
        self.assertEqual(proof["status"], "STOPPED")
        self.assertEqual(proof["requestCount"], 1)
        self.assertEqual(proof["tickets"][0]["state"], "UNKNOWN")

    def test_legacy_inspection_and_denial_do_not_migrate_or_write(self):
        legacy = self.path.with_name("legacy.sqlite")
        shutil.copyfile(self.path, legacy)
        legacy.chmod(0o600)
        before, stamp = legacy.read_bytes(), legacy.stat().st_mtime_ns
        reopened = GoLiveCampaign(legacy)
        proof = reopened.inspect()
        self.assertNotIn("diagnostics", proof)
        self.assertEqual(proof["requestCount"], 0)
        with self.assertRaises(GoLiveGateError) as caught:
            reopened.begin("synthetic-smoke", MODELS[0], request_body())
        self.assertEqual(caught.exception.code, "DIAGNOSTICS_UNAVAILABLE")
        for operation in (lambda: reopened.stop("UNKNOWN"),
                          lambda: reopened.authorize("new-session", MODELS[0], owner_id="alice"),
                          lambda: reopened.finish("missing"),
                          lambda: reopened.complete_model(MODELS[0], "a" * 64)):
            with self.assertRaises(GoLiveGateError) as denied:
                operation()
            self.assertEqual(denied.exception.code, "LEGACY_READ_ONLY")
        self.assertEqual(legacy.read_bytes(), before)
        self.assertEqual(legacy.stat().st_mtime_ns, stamp)
        self.assertFalse(Path(str(legacy) + ".events.sqlite").exists())

    def test_process_crash_keeps_prepared_and_never_replays_budget(self):
        code = '''import os,sys
from agent_factory.go_live import GoLiveCampaign,MODELS
campaign=GoLiveCampaign(sys.argv[1])
body={"model":MODELS[0],"stream":True,"messages":[{"role":"user","content":"Synthetic coding test"}],"max_tokens":32,"stream_options":{"include_usage":True}}
campaign.begin("synthetic-smoke",MODELS[0],body)
os._exit(23)
'''
        result = subprocess.run([sys.executable, "-c", code, str(self.path)],
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1])}, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 23, result.stderr.decode())
        reopened = GoLiveCampaign(self.path)
        before = reopened.inspect()
        self.assertEqual(before["requestCount"], 1)
        self.assertEqual(before["tickets"][0]["state"], "INFLIGHT")
        self.assertEqual([event["phase"] for event in before["diagnostics"]["events"]], ["PREPARED"])
        with self.assertRaises(GoLiveGateError):
            reopened.begin("synthetic-smoke", MODELS[0], request_body())
        with self.assertRaises(GoLiveGateError):
            reopened.verify_ticket(before["tickets"][0]["id"], "synthetic-smoke", MODELS[0])
        self.assertEqual(reopened.inspect(), before)

    def test_crash_after_each_dispatch_boundary_keeps_last_event_and_slot(self):
        phases = ["DISPATCH_STARTED", "RESPONSE_HEADERS", "STREAM_COMPLETED"]
        for target in phases:
            with self.subTest(last_phase=target):
                path = self.path.with_name(target + ".sqlite")
                campaign = GoLiveCampaign.create(path, campaign_id="synthetic-" + target, owner_id="alice",
                    confirmation_id="synthetic-confirmation", expires_at=time.time() + 3600)
                campaign.authorize("synthetic-smoke", MODELS[0], owner_id="alice")
                code = '''import os,sys
from agent_factory.go_live import GoLiveCampaign,MODELS
campaign=GoLiveCampaign(sys.argv[1])
body={"model":MODELS[0],"stream":True,"messages":[{"role":"user","content":"Synthetic coding test"}],"max_tokens":32,"stream_options":{"include_usage":True}}
ticket=campaign.begin("synthetic-smoke",MODELS[0],body)
for phase in ["DISPATCH_STARTED","RESPONSE_HEADERS","STREAM_COMPLETED"]:
 campaign.record_event(ticket,phase)
 if phase==sys.argv[2]:os._exit(23)
'''
                result = subprocess.run([sys.executable, "-c", code, str(path), target],
                    env={"PYTHONPATH": str(Path(__file__).resolve().parents[1])}, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 23, result.stderr.decode())
                reopened = GoLiveCampaign(path)
                proof = reopened.inspect()
                self.assertEqual(proof["diagnostics"]["events"][-1]["phase"], target)
                self.assertEqual(proof["requestCount"], 1)
                self.assertEqual(proof["tickets"][0]["state"], "INFLIGHT")
                with self.assertRaises(GoLiveGateError):
                    reopened.begin("synthetic-smoke", MODELS[0], request_body())
                self.assertEqual(reopened.inspect(), proof)

    def test_diagnostic_event_requires_owned_durable_ticket(self):
        with self.assertRaises(GoLiveGateError):
            self.campaign.record_event("untrusted", "DISPATCH_STARTED")
        self.assertEqual(self.campaign.inspect()["diagnostics"]["events"], [])

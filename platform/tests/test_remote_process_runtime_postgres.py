"""Two task-owned services on one physical host; real HTTP/PG/process custody.

Synthetic identities, deterministic model and fixed cooperative workloads only.
This is not inter-host/TLS/aggregate-capacity or hostile-code sandbox acceptance.
"""
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
from uuid import uuid4

import httpx

from controlled_remote_worker import OTHER_OWNER, RECEIVER_OWNER, REVIEWER, TARGET_REF
from pg_fixture import IsolatedPostgres
from test_governed_remote_process_postgres import OwnedServer, loopback_port, PROJECT


class ProcessRuntimeServer(OwnedServer):
    """Existing real-HTTP helper, with a separate worker and private config."""
    def __init__(self, configuration, directory):
        self.configuration, self.directory = configuration, Path(directory)
        self.path = self.directory / (configuration["role"] + "-server.json")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(configuration, stream)
        self.url = "http://127.0.0.1:" + str(configuration["port"])
        self.process = self.log = None
        self.starts = []

    def start(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Owned fixture is already running")
        if self.log is not None:
            self.log.close()
        self.log = (self.directory / (self.configuration["role"] + "-server.log")).open("ab")
        # Deliberately do not inherit credentials or proxy environment variables.
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "AGNO_TELEMETRY": "false",
            "FACTORY_REMOTE_PROCESS_CONFIG": str(self.path),
            "PYTHONPATH": os.pathsep.join([str(PROJECT / "platform"), str(PROJECT / "platform/tests"), sysconfig.get_path("purelib")])}
        self.process = subprocess.Popen([getattr(sys, "_base_executable", sys.executable),
            "-m", "controlled_remote_process_worker"], cwd=PROJECT, env=environment,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        self.starts.append(self.process.pid)
        deadline = time.monotonic() + 30
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise AssertionError("Owned process runtime fixture startup failed: " + self.log_tail())
                try:
                    if client.get(self.url + "/api/health").status_code == 200:
                        return self
                except httpx.HTTPError:
                    pass
                time.sleep(.04)
        raise AssertionError("Owned process runtime fixture startup did not finish: " + self.log_tail())


class RemoteProcessRuntimePair:
    def __init__(self, database_url, *, workload="normal"):
        self.directory = tempfile.TemporaryDirectory(prefix="remote-process-runtime-")
        self.path = Path(self.directory.name)
        self.database_url, self.workload = database_url, workload
        self.origin_db = self.receiver_db = self.origin = self.receiver = None

    def start(self):
        try:
            self.origin_db = IsolatedPostgres(self.database_url).__enter__()
            self.receiver_db = IsolatedPostgres(self.database_url).__enter__()
            first, second = loopback_port(), loopback_port()
            while first == second:
                second = loopback_port()
            origin_key, receiver_key = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
            common = {"originUrl": f"http://127.0.0.1:{first}", "receiverUrl": f"http://127.0.0.1:{second}",
                "originJwtKey": origin_key, "receiverJwtKey": receiver_key, "controlKey": secrets.token_urlsafe(32),
                "workload": self.workload}
            self.origin = ProcessRuntimeServer({**common, "role": "origin", "dbUrl": self.origin_db.url,
                "jwtKey": origin_key, "port": first, "workspace": str(self.path / "origin-workspace")}, self.path).start()
            source = self.origin.facts()
            self.receiver = ProcessRuntimeServer({**common, "role": "receiver", "dbUrl": self.receiver_db.url,
                "jwtKey": receiver_key, "port": second, "workspace": str(self.path / "receiver-workspace"),
                "sourceApplication": source["applicationSnapshot"], "sourceSpecs": source["sourceSpecs"],
                "sourceMaterials": source["materials"]}, self.path).start()
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            if self.receiver is not None and self.receiver.process is not None:
                if self.receiver.process.poll() is not None:
                    self.receiver.start()
                cleanup = self.receiver.control("cleanup")
                if not cleanup["allOwnedProcessesStopped"]:
                    raise AssertionError("Task-owned process cleanup is unconfirmed")
        finally:
            for server in (self.receiver, self.origin):
                if server is not None:
                    server.stop()
            for database in (self.receiver_db, self.origin_db):
                if database is not None:
                    database.__exit__(None, None, None)
            self.directory.cleanup()


@unittest.skipUnless(sys.platform == "linux" and os.getenv("FACTORY_TEST_DATABASE_URL"),
                     "Requires Linux cooperative processes and isolated loopback PostgreSQL")
class RemoteProcessRuntimePostgresTests(unittest.TestCase):
    def setUp(self):
        number = self._testMethodName.split("_")[1]
        workload = "normal" if number in {"01", "02"} else "unknown" if number == "09" else "deadline" if number == "08" else "sleep"
        self.pair = RemoteProcessRuntimePair(os.environ["FACTORY_TEST_DATABASE_URL"], workload=workload).start()
        self.addCleanup(self.pair.close)
        self.origin, self.receiver = self.pair.origin, self.pair.receiver

    def call(self, server, method, path, *, expected=200, **kwargs):
        response = server.request(method, "/api/factory" + path, **kwargs)
        self.assertEqual(response.status_code, expected, response.text + "\n" + server.log_tail())
        return response.json()

    def approve(self, server, plan_id):
        review = self.call(server, "POST", "/plan-reviews", expected=201,
            json={"planId": plan_id, "requestId": uuid4().hex})
        self.call(server, "POST", "/plan-reviews/" + review["id"] + "/decision", actor=REVIEWER,
            json={"approved": True, "requestId": uuid4().hex})

    def prepare(self):
        proposal = self.call(self.origin, "POST", "/compositions/proposals", expected=201, json={
            "goal": "Execute the fixed receiver cooperative process", "mode": "controlled-fixture",
            "applicationRef": self.origin.facts()["applicationRef"], "requestId": uuid4().hex})
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal)
        plan = self.call(self.origin, "POST", "/compositions/proposals/" + proposal["id"] + "/accept", expected=201,
            json={"requestId": uuid4().hex})
        self.approve(self.origin, plan["id"])
        request = {"planId": plan["id"], "requestId": uuid4().hex, "executionTargetRef": TARGET_REF}
        task = self.call(self.origin, "POST", "/instances", expected=202, json=request)
        self.assertEqual(task["status"], "waiting_approval", task)
        receipt = self.detail(task["id"])["snapshot"]["remoteHandoff"]
        self.assertIsNone(receipt["remoteTaskId"])
        self.approve(self.receiver, receipt["remotePlanId"])
        return plan, task["id"], request

    def detail(self, task):
        return self.call(self.origin, "GET", "/jobs/" + task)

    def until(self, probe, *, timeout=30):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = probe()
            if last:
                return last
            time.sleep(.05)
        self.fail("Remote process fixture did not reach expected state; diagnostics: " + self.receiver.log_tail())

    def execute(self):
        plan, task, request = self.prepare()
        self.call(self.origin, "POST", "/instances", expected=202, json=request)
        receipt = self.until(lambda: (r if r.get("remoteTaskId") else None)
            if (r := self.detail(task)["snapshot"]["remoteHandoff"]) else None)
        return plan, task, request, receipt

    def receiver_lease(self, remote_task):
        leases = self.receiver.facts(remote_task)["leases"]
        selected = [lease for lease in leases if lease["localTaskId"] == remote_task]
        self.assertLessEqual(len(selected), 1)
        return selected[0] if selected else None

    def wait_lease(self, remote_task, states):
        return self.until(lambda: (lease if lease["state"] in states else None)
            if (lease := self.receiver_lease(remote_task)) else None)

    def assert_single(self, origin_task, receipt):
        origin, receiver = self.origin.facts(origin_task), self.receiver.facts(receipt["remoteTaskId"])
        self.assertEqual(origin["nativeTickets"], 0)
        self.assertEqual(origin["leases"], [])
        self.assertEqual(receiver["nativeTickets"], 1)
        self.assertEqual(len(receiver["processMappings"]), 1)
        self.assertEqual(len(receiver["processAllocations"]), 1)
        self.assertEqual(receiver["launchAttemptCount"], 1)
        lease = self.receiver_lease(receipt["remoteTaskId"])
        self.assertEqual(lease["nativeRunId"], receipt["remoteRunId"])
        self.assertEqual(lease["planId"], receipt["remotePlanId"])
        self.assertEqual(lease["ownerId"], RECEIVER_OWNER)
        return lease

    def diagnostics(self, stage, facts):
        # Fixed synthetic metadata only. No configuration, tokens, payloads,
        # arbitrary errors or authorization URL parameters enter the test log.
        task = facts.get("task") or {}
        value = {"stage": stage, "observedAt": datetime.now(timezone.utc).isoformat(),
            "nativeStatus": facts.get("nativeStatus"), "cancelCount": facts["cancelAttemptCount"],
            "taskCancelRequested": task.get("cancel_requested"), "taskTerminal": task.get("terminal"),
            "leases": [{key: lease.get(key) for key in ("id", "state", "deadlineAt", "cancelRequested",
                "executionStatus", "stopEvidence", "capacityHeld", "cancellationReason")} for lease in facts["leases"]],
            "cancelDiagnostics": facts.get("cancelDiagnostics", []),
            "disconnectDiagnostics": facts.get("disconnectDiagnostics", [])}
        print("Remote process synthetic timing: " + json.dumps(value, sort_keys=True), flush=True)
        return value

    def test_01_governed_remote_process_original_identity_receipt_and_owner_isolation(self):
        plan, task, _, receipt = self.execute()
        lease = self.wait_lease(receipt["remoteTaskId"], {"RECLAIMED"})
        self.assertEqual(lease["executionStatus"], "COMPLETED")
        self.assertEqual(self.assert_single(task, receipt)["id"], lease["id"])
        detail = self.until(lambda: (d if d["job"]["status"] == "completed" else None) if (d := self.detail(task)) else None)
        projected = detail["snapshot"]["remoteHandoff"]["processLeases"]
        self.assertEqual(projected["schema"], 1)
        self.assertTrue(projected["complete"])
        self.assertEqual(projected["leases"][0]["id"], lease["id"])
        artifact = next(a for a in detail["artifacts"] if a["name"].startswith("process-"))
        raw = self.origin.request("GET", f"/api/factory/jobs/{task}/artifacts/{artifact['id']}")
        self.assertEqual(raw.status_code, 200)
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact["sha256"])
        self.assertIn("bindingProvenance", artifact["provenance"])
        self.assertEqual(raw.json()["providerJobId"], lease["providerJobId"])
        self.assertEqual(self.origin.facts(task)["plan"], plan)
        denied = self.origin.request("GET", f"/api/factory/jobs/{task}/artifacts/{artifact['id']}", actor=OTHER_OWNER)
        self.assertEqual(denied.status_code, 404)

    def test_02_completed_request_replay_preserves_released_process_identity(self):
        _, task, request, receipt = self.execute()
        first = self.wait_lease(receipt["remoteTaskId"], {"RECLAIMED"})
        repeated = self.call(self.origin, "POST", "/instances", expected=202, json=request)
        self.assertEqual(repeated["id"], task)
        current = self.assert_single(task, receipt)
        for key in ("id", "providerJobId", "nativeRunId", "localTaskId", "planId"):
            self.assertEqual(current[key], first[key])

    def test_03_receiver_exit_after_actual_dispatch_recovers_original_custody(self):
        _, task, request = self.prepare()
        self.receiver.control("fault", fault="exit_after_dispatch")
        self.call(self.origin, "POST", "/instances", expected=202, json=request)
        self.until(lambda: self.receiver.process.poll() is not None)
        self.receiver.start()
        self.call(self.origin, "POST", "/jobs/" + task + "/reconcile")
        receipt = self.until(lambda: (r if r.get("remoteTaskId") else None)
            if (r := self.detail(task)["snapshot"]["remoteHandoff"]) else None)
        self.wait_lease(receipt["remoteTaskId"], {"RECLAIMED", "UNKNOWN"})
        self.assert_single(task, receipt)

    def test_04_origin_cancel_stops_only_original_receiver_process(self):
        _, task, _, receipt = self.execute()
        self.wait_lease(receipt["remoteTaskId"], {"RUNNING"})
        self.call(self.origin, "POST", "/jobs/" + task + "/cancel")
        lease = self.wait_lease(receipt["remoteTaskId"], {"RECLAIMED"})
        self.assertEqual(lease["executionStatus"], "CANCELLED")
        self.assert_single(task, receipt)

    def revoke(self, server):
        _, task, _, receipt = self.execute()
        self.wait_lease(receipt["remoteTaskId"], {"RUNNING"})
        server.control("role-revoke")
        try:
            lease = self.wait_lease(receipt["remoteTaskId"], {"RECLAIMED"})
            self.assertEqual(lease["executionStatus"], "CANCELLED")
            self.assert_single(task, receipt)
        finally:
            server.control("role-restore")

    def test_05_origin_revocation_stops_original_receiver_work(self):
        self.revoke(self.origin)

    def test_06_receiver_revocation_stops_original_work(self):
        self.revoke(self.receiver)

    def test_07_lost_cancel_ack_reconciles_without_duplicate_process(self):
        _, task, _, receipt = self.execute()
        self.wait_lease(receipt["remoteTaskId"], {"RUNNING"})
        self.receiver.control("fault", fault="drop_cancel_ack")
        self.call(self.origin, "POST", "/jobs/" + task + "/cancel")
        lease = self.wait_lease(receipt["remoteTaskId"], {"RECLAIMED"})
        self.assertEqual(lease["executionStatus"], "CANCELLED")
        self.assert_single(task, receipt)
        self.assertEqual(self.receiver.facts(receipt["remoteTaskId"])["cancelAttemptCount"], 1)

    def test_08_remote_deadline_preserves_unsuccessful_execution_outcome(self):
        _, task, _, receipt = self.execute()
        lease = self.wait_lease(receipt["remoteTaskId"], {"RECLAIMED"})
        self.diagnostics("deadline-released", self.receiver.facts(receipt["remoteTaskId"]))
        # The fixed guardian wall limit and absolute lease deadline race.
        # Each permitted winner needs its own positive cause, never success.
        if lease["executionStatus"] == "CANCELLED":
            self.assert_expiry_cancel(self.receiver.facts(receipt["remoteTaskId"]), lease)
        else:
            self.assertEqual(lease["executionStatus"], "LIMIT_STOPPED")
            self.assertEqual(lease["stopEvidence"]["kind"], "original-root-reaped-and-no-live-process-group-members")
        self.assertTrue(lease["stopEvidence"]["allStopped"])
        self.assertFalse(lease["capacityHeld"])
        self.until(lambda: self.detail(task)["job"]["status"] == "failed")
        self.assert_single(task, receipt)

    def test_09_unknown_custody_survives_native_terminal_and_receiver_restart(self):
        _, task, _, receipt = self.execute()
        first = self.wait_lease(receipt["remoteTaskId"], {"UNKNOWN"})
        self.until(lambda: self.receiver.facts(receipt["remoteTaskId"])["nativeStatus"] in {"completed", "failed", "cancelled"})
        self.receiver.stop(); self.receiver.start()
        held = self.assert_single(task, receipt)
        self.assertEqual(held["id"], first["id"])
        self.assertNotEqual(held["state"], "RECLAIMED")
        self.assertTrue(held["capacityHeld"])
        facts = self.receiver.facts(receipt["remoteTaskId"])
        self.assertFalse(facts["task"]["terminal"])
        self.assertEqual(facts["diskHold"], "HELD")
        probe = self.receiver.control("capacity-probe")
        self.assertEqual(probe["status"], 429)
        self.assertEqual(self.receiver.facts(receipt["remoteTaskId"])["launchAttemptCount"], 1)
        origin_detail = self.detail(task)
        self.assertEqual(origin_detail["job"]["status"], "unknown")
        original_receipt = origin_detail["snapshot"]["remoteHandoff"]
        self.assertFalse(original_receipt["allStopped"])
        projected = original_receipt["processLeases"]
        self.assertTrue(projected["complete"])
        self.assertEqual(projected["leases"][0]["id"], first["id"])
        self.assertTrue(projected["leases"][0]["capacityHeld"])
        origin_facts = self.origin.facts(task)
        self.assertFalse(origin_facts["task"]["terminal"])
        self.assertEqual(origin_facts["diskHold"], "HELD")

    def test_10_read_disconnect_retains_custody_without_issuing_cancel(self):
        _, task, request = self.prepare()
        self.call(self.origin, "POST", "/instances", expected=202, json=request)
        # Observe the receiver directly before expensive remote detail projection.
        # Keep the fixed five-second lease; no timer reset or observer suspension.
        before = self.until(lambda: (f if any(x["state"] == "RUNNING" for x in f["leases"]) else None)
            if (f := self.receiver.facts()) else None)
        first = before["leases"][0]
        receipt = {"remoteTaskId": first["localTaskId"], "remoteRunId": first["nativeRunId"], "remotePlanId": first["planId"]}
        self.diagnostics("before-read-disconnect", before)
        self.assertEqual(before["cancelAttemptCount"], 0)
        # This receiver snapshot proves RUNNING/cancel0. A later client clock
        # cannot prove when the snapshot was observed: facts transport itself
        # may cross the unchanged lease deadline. Check actual expiry causality
        # below instead of treating response latency as read-triggered cancel.
        self.receiver.control("fault", fault="disconnect_reads")
        try:
            unavailable = self.detail(task)
            self.assertEqual(unavailable["job"]["status"], "unknown")
            self.assertTrue(unavailable["snapshot"]["remoteUnavailable"])
            self.assertTrue(unavailable["snapshot"]["capacityHeld"])
            during = self.until(lambda: (f if f.get("disconnectDiagnostics") else None)
                if (f := self.receiver.facts()) else None)
            self.diagnostics("during-read-disconnect", during)
            # Capture the real failed read boundary, not the later HTTP
            # diagnostics response whose latency may cross the fixed deadline.
            boundary = during["disconnectDiagnostics"][0]
            self.assertEqual(boundary["leaseId"], first["id"])
            self.assertEqual(boundary["deadlineAt"], first["deadlineAt"])
            before_expiry = datetime.fromisoformat(boundary["observedAt"]) < datetime.fromisoformat(first["deadlineAt"])
            self.assertFalse(boundary["cancelRequested"])
            if before_expiry:
                self.assertEqual(boundary["cancelAttemptCount"], 0)
                if during["cancelAttemptCount"]:
                    self.assert_expiry_cancel(during, during["leases"][0])
            else:
                # A real five-second lease may expire while these real HTTP/PG
                # reads execute. This branch proves original deadline causality,
                # not a pre-expiry real-HTTP outage. The independent fixed-time
                # transport test covers the no-expiry read-only control flow.
                during = self.until(lambda: (f if f["cancelAttemptCount"] or any(
                    x["id"] == first["id"] and x["state"] == "RECLAIMED" for x in f["leases"]) else None)
                    if (f := self.receiver.facts(receipt["remoteTaskId"])) else None)
                ended = during["leases"][0]
                self.assertEqual(ended["id"], first["id"])
                self.assertEqual(ended["deadlineAt"], first["deadlineAt"])
                if during["cancelAttemptCount"]:
                    self.assert_expiry_cancel(during, ended)
                else:
                    # The original guardian's wall limit can win this race.
                    # Only its positive original-process stop/reclaim proof is
                    # admissible here; generic native terminal is insufficient.
                    self.assertEqual(ended["executionStatus"], "LIMIT_STOPPED")
                    self.assertIs(type(ended["exitCode"]), int)
                    self.assertLess(ended["exitCode"], 0)
                    self.assertFalse(ended["cancelRequested"])
                    self.assertEqual(ended["state"], "RECLAIMED")
                    self.assertEqual(ended["stopEvidence"]["kind"], "original-root-reaped-and-no-live-process-group-members")
                    self.assertTrue(ended["stopEvidence"]["allStopped"])
                    self.assertFalse(ended["capacityHeld"])
                    self.assertEqual(during["cancelDiagnostics"], [])
                    self.assertEqual(boundary["cancelAttemptCount"], 0)
                self.assertIn(boundary["cancelAttemptCount"], {0, 1})
            self.assertEqual(during["launchAttemptCount"], 1)
        finally:
            self.receiver.control("fault", fault=None)
        restored = self.detail(task)
        self.assertNotIn("remoteUnavailable", restored["snapshot"])
        current = self.assert_single(task, receipt)
        for key in ("id", "providerJobId", "nativeRunId", "localTaskId", "planId"):
            self.assertEqual(current[key], first[key])
        after = self.receiver.facts(receipt["remoteTaskId"])
        self.diagnostics("after-read-reconnect", after)
        if after["cancelAttemptCount"]:
            self.assert_expiry_cancel(after, after["leases"][0])
        else:
            self.assertFalse(after["leases"][0]["cancelRequested"])

    def assert_expiry_cancel(self, facts, lease):
        self.assertEqual(facts["cancelAttemptCount"], 1)
        self.assertEqual(lease["cancellationReason"], "LEASE_EXPIRED")
        self.assertEqual(len(facts["cancelDiagnostics"]), 1)
        event = facts["cancelDiagnostics"][0]
        self.assertEqual(event["leaseId"], lease["id"])
        self.assertEqual(event["runtimeReason"], "LEASE_EXPIRED")
        self.assertFalse(event["taskCancelRequested"])
        self.assertTrue(event["deadlineElapsed"])
        self.assertEqual(event["deadlineAt"], lease["deadlineAt"])
        self.assertGreaterEqual(datetime.fromisoformat(event["observedAt"]), datetime.fromisoformat(lease["deadlineAt"]))

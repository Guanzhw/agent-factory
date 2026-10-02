"""Two owned OS processes, real loopback HTTP and independent native PostgreSQL.

Production policy/managed auth is real, with separately reviewed generated
materials, application and source/receiver task plans. Provider output remains
explicitly controlled: no API/model charges, TLS/deployed-host or live provider
compatibility is established. Crash injection belongs only to the fixture server.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
from uuid import uuid4

import httpx

from pg_fixture import IsolatedPostgres
from controlled_remote_worker import (MANAGER, MODEL_RECEIVER, MODEL_SOURCE, ORIGIN_OWNER, OTHER_OWNER,
    RECEIVER_OWNER, REVIEWER, TARGET_REF, token)
from agent_factory.store import digest
from agent_factory.orx_tools import ORX_ADAPTER_ID, ORX_ADAPTER_REVISION

PROJECT = Path(__file__).resolve().parents[2]


def loopback_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class OwnedServer:
    def __init__(self, configuration, directory):
        self.configuration, self.directory = configuration, Path(directory)
        self.path = self.directory / (configuration["role"] + "-server.json")
        self.path.write_text(json.dumps(configuration), encoding="utf-8")
        self.url = "http://127.0.0.1:" + str(configuration["port"])
        self.process = self.log = None
        self.starts = []

    def start(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Owned fixture server is already running")
        environment = {**os.environ, "FACTORY_REMOTE_PROCESS_CONFIG": str(self.path),
                       "PYTHONPATH": os.pathsep.join([str(PROJECT / "platform"), str(PROJECT / "platform/tests"), sysconfig.get_path("purelib")]),
                       "AGNO_TELEMETRY": "false"}
        if self.log is not None:
            self.log.close()
        self.log = (self.directory / (self.configuration["role"] + "-server.log")).open("ab")
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
        # On Windows the venv executable is a redirector with a different
        # child PID. Run real CPython with the same pinned environment path
        # so the retained Popen identity owns the actual service directly.
        interpreter = getattr(sys, "_base_executable", sys.executable)
        self.process = subprocess.Popen([interpreter, "-m", "controlled_remote_worker"], cwd=PROJECT, env=environment,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT, creationflags=flags)
        self.starts.append(self.process.pid)
        deadline = time.monotonic() + 25
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise AssertionError("Owned fixture startup failed: " + self.log_tail())
                try:
                    if client.get(self.url + "/api/health").status_code == 200:
                        return self
                except httpx.HTTPError:
                    pass
                time.sleep(.04)
        raise AssertionError("Owned fixture did not start: " + self.log_tail())

    def log_tail(self):
        return (self.directory / (self.configuration["role"] + "-server.log")).read_text(encoding="utf-8", errors="replace")[-5000:]

    def stop(self):
        # Popen identity is created/retained by this fixture; never enumerate or
        # kill arbitrary host processes. This workflow has no subprocess tools.
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        if self.log is not None:
            self.log.close()

    def request(self, method, path, *, actor=None, fixture=False, **kwargs):
        actor = actor or (ORIGIN_OWNER if self.configuration["role"] == "origin" else RECEIVER_OWNER)
        headers = {"Authorization": "Bearer " + token(self.configuration["jwtKey"], actor)}
        if fixture:
            headers["X-Fixture-Control"] = self.configuration["controlKey"]
        # One public instance request may await prepare, dispatch and detail,
        # each with the production handoff client's 20-second read deadline.
        # The outer fixture must allow those phases and current-authority checks
        # to finish; bounded state waits and all admission/effect proofs remain.
        read_seconds = 75 if method.upper() == "POST" and path == "/api/factory/instances" else 30
        timeout = httpx.Timeout(connect=3, read=read_seconds, write=5, pool=3)
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            return client.request(method, self.url + path, headers=headers, **kwargs)

    def facts(self, task=None):
        response = self.request("GET", "/__fixture/state", fixture=True, actor=MANAGER, params={"taskId": task} if task else {})
        if response.status_code != 200:
            raise AssertionError(response.text)
        return response.json()

    def control(self, op, **kwargs):
        response = self.request("POST", "/__fixture/control", fixture=True, actor=MANAGER, json={"op": op, **kwargs})
        if response.status_code != 200:
            raise AssertionError(response.text)
        return response.json()


class OwnedRemotePair:
    """Also usable for explicit browser acceptance; close releases only fixtures."""
    def __init__(self, database_url, directory=None, *, registered_tools=False, usage_profile=None):
        self.directory = tempfile.TemporaryDirectory(prefix="factory-remote-tcp-") if directory is None else None
        self.path = Path(self.directory.name if self.directory else directory).resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self.origin_db = self.receiver_db = self.origin = self.receiver = None
        self.database_url, self.registered_tools, self.usage_profile = database_url, registered_tools, usage_profile

    def start(self):
        try:
            self.origin_db = IsolatedPostgres(self.database_url).__enter__()
            self.receiver_db = IsolatedPostgres(self.database_url).__enter__()
            first, second = loopback_port(), loopback_port()
            while second == first:
                second = loopback_port()
            origin_key, receiver_key, control_key = secrets.token_urlsafe(48), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            common = {"originUrl": f"http://127.0.0.1:{first}", "receiverUrl": f"http://127.0.0.1:{second}",
                      "originJwtKey": origin_key, "receiverJwtKey": receiver_key, "controlKey": control_key, "registeredTools": self.registered_tools, "usageProfile": self.usage_profile}
            self.origin = OwnedServer({**common, "role": "origin", "dbUrl": self.origin_db.url, "jwtKey": origin_key,
                "port": first, "workspace": str(self.path / "origin-workspace")}, self.path)
            self.origin.start()
            source = self.origin.facts()
            spec = {"materialRef": source["materials"]["fixture-selected-model"], "adapterId": MODEL_SOURCE,
                    "revision": "1", "config": {"connectionName": "provider"}, "connection": source["connection"]}
            if self.registered_tools:
                common["sourceORXSpec"] = {"materialRef": source["materials"]["fixture-selected-orx"], "adapterId": ORX_ADAPTER_ID,
                    "revision": ORX_ADAPTER_REVISION, "config": {"connectionName": "discovery"}, "toolName": "orx_discover", "connection": source["orxConnection"]}
            self.receiver = OwnedServer({**common, "role": "receiver", "dbUrl": self.receiver_db.url, "jwtKey": receiver_key,
                "port": second, "workspace": str(self.path / "receiver-workspace"), "sourceSpec": spec, "sourceApplication": source["applicationSnapshot"]}, self.path)
            self.receiver.start()
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        for server in (self.receiver, self.origin):
            if server is not None:
                server.stop()
        for database in (self.receiver_db, self.origin_db):
            if database is not None:
                database.__exit__(None, None, None)
        self.origin_db = self.receiver_db = None
        if self.directory is not None:
            self.directory.cleanup()


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires owned loopback PostgreSQL")
class GovernedRemoteProcessPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pair = OwnedRemotePair(os.environ["FACTORY_TEST_DATABASE_URL"]).start()
        cls.addClassCleanup(cls.pair.close)
        cls.origin, cls.receiver = cls.pair.origin, cls.pair.receiver

    def setUp(self):
        self.tasks = []
        for server in (self.origin, self.receiver):
            if server.process.poll() is not None:
                server.start()
            server.control("role-restore")
            server.control("connection-restore")
        self.receiver.control("mapping-restore")

    def tearDown(self):
        for server in (self.origin, self.receiver):
            if server.process.poll() is not None:
                server.start()
            server.control("role-restore")
            server.control("connection-restore")
        self.receiver.control("mapping-restore")
        for task in self.tasks:
            self.call(self.origin, "POST", f"/jobs/{task}/cancel", expected=200)

    def call(self, server, method, path, expected=200, **kwargs):
        response = server.request(method, "/api/factory" + path, **kwargs)
        if response.status_code != expected:
            self.fail(response.text + "\nReceiver fixture diagnostics: " + self.receiver.log_tail())
        return response

    def plan(self, mode="direct", goal="Original controlled remote checksum evidence"):
        facts = self.origin.facts()
        proposal = self.call(self.origin, "POST", "/compositions/proposals", expected=201, json={
            "goal": goal, "mode": mode, "applicationRef": facts["applicationRef"],
            "connectionRefs": {"provider": facts["connection"]["ref"], **({"discovery": facts["orxConnection"]["ref"]} if mode == "discovery" else {})}, "requestId": uuid4().hex}).json()
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal)
        plan = self.call(self.origin, "POST", f"/compositions/proposals/{proposal['id']}/accept", expected=201,
            json={"requestId": uuid4().hex}).json()
        self.assertFalse(plan["syntheticFixture"])
        self.assertEqual(plan["policy"], "admin-review")
        self.approve(self.origin, plan["id"])
        return plan

    def approve(self, server, plan_id):
        review = self.call(server, "POST", "/plan-reviews", expected=201, json={"planId": plan_id, "requestId": uuid4().hex}).json()
        self.call(server, "POST", f"/plan-reviews/{review['id']}/decision", actor=REVIEWER,
            json={"approved": True, "requestId": uuid4().hex})

    def prepare(self, plan):
        body = {"planId": plan["id"], "requestId": uuid4().hex, "executionTargetRef": TARGET_REF}
        initial = self.call(self.origin, "POST", "/instances", expected=202, json=body).json()
        task = initial["id"]
        self.tasks.append(task)
        self.assertEqual(initial["status"], "waiting_approval", initial)
        detail = self.call(self.origin, "GET", "/jobs/" + task).json()
        receipt = detail["snapshot"]["remoteHandoff"]
        self.assertTrue(detail["snapshot"]["receiverReviewRequired"])
        self.assertIsNone(receipt["remoteTaskId"])
        self.assertIsNone(receipt["remoteRunId"])
        return task, body, receipt

    def execute(self, mode="direct"):
        plan = self.plan(mode)
        task, body, receipt = self.prepare(plan)
        self.approve(self.receiver, receipt["remotePlanId"])
        job = self.call(self.origin, "POST", "/instances", expected=202, json=body).json()
        self.assertEqual(job["id"], task)
        return plan, task, body, receipt

    def wait(self, server, task, states, *, seconds=15):
        deadline, last = time.monotonic() + seconds, None
        while time.monotonic() < deadline:
            last = self.call(server, "GET", "/jobs/" + task).json()
            if last["job"]["status"] in states:
                return last
            time.sleep(.04)
        self.fail(f"Task did not settle to {states}: {last}")

    def stopped(self, server, task, expected):
        deadline, last = time.monotonic() + 12, None
        while time.monotonic() < deadline:
            last = self.call(server, "GET", "/jobs/" + task).json()
            if last["job"]["status"] == expected and last["snapshot"]["delegation"]["allStopped"]:
                return last
            time.sleep(.04)
        self.fail("Native whole-tree cleanup did not positively settle: " + str(last))

    def assert_binding_provenance(self, artifact, plan, receipt):
        original = plan["executionBindings"]
        proof = receipt["receiverBindingProof"]
        entries = {(entry["kind"], digest(entry["sourceSpec"])): entry for entry in proof["entries"]}

        def selected(kind, spec):
            entry = entries[(kind, digest(spec))]
            self.assertEqual(entry["sourceSpec"], spec)
            return entry["effectiveSpec"]

        # Reconstruct from the independently persisted public proof, rather
        # than accepting execution labels as sufficient provenance evidence.
        effective = {"schema": original["schema"],
            "model": selected("model", original["model"]),
            "environment": selected("environment", original["environment"]),
            "tools": [selected("tool", spec) for spec in original["tools"]],
            "knowledge": [selected("knowledge", spec) for spec in original["knowledge"]]}
        provenance = artifact["provenance"]
        binding = provenance["bindingProvenance"]
        self.assertEqual(binding, {"schema": 1,
            "sourceExecutionBindingsSha256": original["sha256"],
            "effectiveExecutionBindingsSha256": digest(effective),
            "receiverBindingProofSha256": proof["sha256"],
            "sourceModel": {"adapterId": MODEL_SOURCE, "revision": "1"},
            "effectiveModel": {"adapterId": MODEL_RECEIVER, "revision": "1"},
            "sourceEnvironment": {key: original["environment"][key] for key in ("adapterId", "revision")},
            "effectiveEnvironment": {key: effective["environment"][key] for key in ("adapterId", "revision")}})
        self.assertEqual(provenance["modelAdapterId"], MODEL_RECEIVER)
        self.assertEqual(provenance["environmentAdapterId"], effective["environment"]["adapterId"])
        self.assertNotEqual(binding["sourceExecutionBindingsSha256"], binding["effectiveExecutionBindingsSha256"])
        encoded = json.dumps(provenance)
        self.assertNotIn("opaque-handle-marker", encoded)
        self.assertNotIn("ControlledProvider", encoded)

        def no_handles(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & {"handle", "opaqueHandle", "opaque_handle", "handleRef", "handle_ref", "jwtKey", "controlKey"})
                for item in value.values():
                    no_handles(item)
            elif isinstance(value, list):
                for item in value:
                    no_handles(item)
        no_handles(provenance)

    def assert_no_ticket(self, origin_task, before_receiver):
        self.assertEqual(self.origin.facts(origin_task)["nativeTickets"], 0)
        self.assertEqual(self.receiver.facts()["nativeTickets"], before_receiver)

    def test_01_real_tcp_governed_mapping_review_single_admission_and_artifact_integrity(self):
        source, receiver = self.origin.facts(), self.receiver.facts()
        self.assertNotEqual(source["pid"], receiver["pid"])
        self.assertNotEqual(source["workspace"], receiver["workspace"])
        self.assertEqual(source["applicationRef"], receiver["applicationRef"])
        self.assertNotEqual(self.pair.origin_db.name, self.pair.receiver_db.name)
        self.assertFalse(source["demo"]); self.assertFalse(receiver["demo"])
        before = receiver["nativeTickets"]
        plan = self.plan()
        task, body, pending = self.prepare(plan)
        self.assert_no_ticket(task, before)
        proof = pending["receiverBindingProof"]
        # Public proof is intentionally redacted; authenticated fixture
        # ledger reads validate its full immutable source/body hash separately.
        stored = next(row for row in self.receiver.facts()["bindingProofs"] if row["receipt_id"] == pending["id"])
        self.assertEqual(stored["body"]["sourceBindings"], plan["executionBindings"])
        self.assertEqual(stored["body"]["sourcePlan"], plan)
        self.assertEqual(stored["sha"], proof["sha256"])
        self.assertEqual(proof["sha256"], digest(stored["body"]))
        mapped = next(entry for entry in proof["entries"] if entry["kind"] == "model")
        self.assertEqual(mapped["sourceSpec"]["connection"], source["connection"])
        self.assertEqual(mapped["effectiveSpec"]["connection"], receiver["connection"])
        self.assertNotEqual(mapped["sourceSpec"]["adapterId"], mapped["effectiveSpec"]["adapterId"])
        self.approve(self.receiver, pending["remotePlanId"])
        for _ in range(2):
            self.assertEqual(self.call(self.origin, "POST", "/instances", expected=202, json=body).json()["id"], task)
        completed = self.wait(self.origin, task, {"completed"})
        receipt = completed["snapshot"]["remoteHandoff"]
        self.assertEqual(receipt["id"], pending["id"])
        self.assertEqual(receipt["receiverBindingProof"], proof)
        self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)
        self.assertEqual(self.receiver.facts(receipt["remoteTaskId"])["nativeTickets"], 1)
        artifact = completed["artifacts"][0]
        self.assert_binding_provenance(artifact, plan, receipt)
        raw = self.call(self.origin, "GET", f"/jobs/{task}/artifacts/{artifact['id']}")
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact["sha256"])
        self.assertEqual(raw.headers["x-content-sha256"], artifact["sha256"])
        self.call(self.origin, "GET", f"/jobs/{task}/artifacts/{artifact['id']}", actor=OTHER_OWNER, expected=404)
        self.call(self.receiver, "POST", "/instances", expected=403, json={"planId": receipt["remotePlanId"], "requestId": uuid4().hex})
        self.assertEqual(self.receiver.facts(receipt["remoteTaskId"])["nativeTickets"], 1)

    def test_02_missing_and_wrong_owner_mapping_never_create_receiver_ticket(self):
        for operation in ("mapping-remove", "mapping-wrong-owner"):
            with self.subTest(operation=operation):
                self.receiver.control("mapping-restore")
                plan, before = self.plan(), self.receiver.facts()["nativeTickets"]
                self.receiver.control(operation)
                body = {"planId": plan["id"], "requestId": uuid4().hex, "executionTargetRef": TARGET_REF}
                denied = self.call(self.origin, "POST", "/instances", expected=409, json=body)
                self.assertEqual(denied.json()["code"], "REMOTE_BINDING_REQUIRED")
                self.assertEqual(denied.json()["message"], "REMOTE_BINDING_REQUIRED: Trusted receiver rejected the operation")
                lookup = self.call(self.origin, "GET", "/requests/" + body["requestId"]).json()
                self.tasks.append(lookup["taskId"])
                self.assert_no_ticket(lookup["taskId"], before)
                self.receiver.control("mapping-restore")

    def test_03_mapping_and_receiver_connection_rotation_block_reviewed_dispatch(self):
        for operation in ("mapping-rotate", "connection-rotate"):
            with self.subTest(operation=operation):
                self.receiver.control("mapping-restore"); self.receiver.control("connection-restore")
                before = self.receiver.facts()["nativeTickets"]
                task, body, receipt = self.prepare(self.plan())
                self.approve(self.receiver, receipt["remotePlanId"])
                self.receiver.control(operation)
                self.call(self.origin, "POST", "/instances", expected=409, json=body)
                self.assert_no_ticket(task, before)
                evidence = self.call(self.receiver, "GET", "/remote-handoffs/" + receipt["id"]).json()
                self.assertEqual(evidence["receiverBindingProof"], receipt["receiverBindingProof"])
                self.receiver.control("mapping-restore"); self.receiver.control("connection-restore")

    def test_04_both_current_role_revocations_stop_paused_native_work_without_checksum(self):
        for revoked in (self.origin, self.receiver):
            with self.subTest(role=revoked.configuration["role"]):
                _, task, body, _ = self.execute("paused")
                paused = self.wait(self.origin, task, {"waiting_input"})
                remote = paused["snapshot"]["remoteHandoff"]["remoteTaskId"]
                revoked.control("role-revoke")
                failed = self.stopped(self.receiver, remote, "failed")
                self.assertTrue(failed["snapshot"]["delegation"]["allStopped"])
                self.assertEqual(failed["artifacts"], [])
                self.assertFalse(any(event["type"] == "checksum_completed" for event in failed["events"]))
                question = paused["job"]["questionDetail"]
                self.call(self.origin, "POST", f"/jobs/{task}/answer", expected=403,
                    json={"questionId": question["id"], "version": question["version"], "answer": "A revoked principal cannot resume this checksum"})
                if revoked is self.origin:
                    self.call(self.origin, "POST", "/instances", expected=403, json=body)
                else:
                    # Original-key replay is an authorized source read of
                    # the failed receipt, never another dispatch/resume.
                    repeated = self.call(self.origin, "POST", "/instances", expected=202, json=body).json()
                    self.assertEqual(repeated["id"], task)
                    self.assertEqual(repeated["status"], "failed")
                revoked.control("role-restore")
                self.assertEqual(self.receiver.facts(remote)["nativeTickets"], 1)
                self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)

    def test_05_real_origin_process_outage_fails_closed_and_restart_reads_original_receipt(self):
        _, task, body, _ = self.execute("paused")
        paused = self.wait(self.origin, task, {"waiting_input"})
        receipt = paused["snapshot"]["remoteHandoff"]
        remote, old_pid = receipt["remoteTaskId"], self.origin.process.pid
        self.origin.stop()
        # A disconnected origin is uncertainty, not revocation or verified
        # cancellation. The real paused native ticket remains held and no new
        # effect may execute while the synchronous current-origin check fails.
        question = paused["job"]["questionDetail"]
        self.call(self.receiver, "POST", "/remote-handoffs/" + receipt["id"] + "/answer", expected=503,
            json={"questionId": question["id"], "version": question["version"], "answer": "Outage cannot authorize this checksum"})
        held = self.wait(self.receiver, remote, {"waiting_input"})
        self.assertFalse(held["snapshot"]["delegation"]["allStopped"])
        self.assertEqual(held["artifacts"], [])
        self.assertEqual(self.receiver.facts(remote)["nativeTickets"], 1)
        self.origin.start()
        self.assertNotEqual(self.origin.process.pid, old_pid)
        self.assertEqual(self.call(self.origin, "GET", "/requests/" + body["requestId"]).json()["taskId"], task)
        reconciled = self.call(self.origin, "POST", "/jobs/" + task + "/reconcile").json()
        self.assertEqual(reconciled["status"], "waiting_input")
        self.assertEqual(self.receiver.facts(remote)["nativeTickets"], 1)
        self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)

    def test_06_descendants_inherit_mapping_narrow_scope_and_cancel_only_owned_tree(self):
        plan, task, _, _ = self.execute("paused")
        root_detail = self.wait(self.origin, task, {"waiting_input"})
        self.assertEqual(root_detail["snapshot"]["delegationScope"]["modes"], ["direct", "paused"])
        self.assertEqual(root_detail["snapshot"]["delegationScope"]["defaultMode"], "paused")
        child_body = {"goal": "Controlled receiver-owned paused child", "mode": "paused", "requestId": uuid4().hex}
        child = self.call(self.origin, "POST", f"/jobs/{task}/children", expected=202, json=child_body).json()
        proxy = child["job"]["id"]
        repeated = self.call(self.origin, "POST", f"/jobs/{task}/children", expected=202, json=child_body).json()
        self.assertEqual(repeated["job"]["id"], proxy)
        paused = self.wait(self.origin, proxy, {"waiting_input"})
        native_child = proxy.split("~", 1)[1]
        self.assertEqual(self.receiver.facts(native_child)["nativeTickets"], 1)
        child_plan = self.receiver.facts(native_child)["plan"]
        self.assertEqual(child_plan["id"], paused["job"]["planId"])
        self.assertEqual(child_plan["executionBindings"]["model"], plan["executionBindings"]["model"])
        grandchild = self.call(self.origin, "POST", f"/jobs/{proxy}/children", expected=202,
            json={"goal": "Narrow checksum only controlled child", "mode": "direct", "requestId": uuid4().hex}).json()
        narrow = self.wait(self.origin, grandchild["job"]["id"], {"completed"})
        narrow_native_id = grandchild["job"]["id"].split("~", 1)[1]
        narrow_plan = self.receiver.facts(narrow_native_id)["plan"]
        self.assertEqual(narrow_plan["id"], narrow["job"]["planId"])
        self.assertEqual(narrow_plan["tools"], ["checksum"])
        self.assertFalse(narrow["snapshot"]["delegationScope"]["allowed"])
        self.assertEqual(narrow["snapshot"]["delegationScope"]["modes"], [])
        self.assertIsNone(narrow["snapshot"]["delegationScope"]["defaultMode"])
        self.assertNotIn("fixture-selected-question", {item["id"] for item in narrow_plan["materialRefs"]})
        self.assertLess({item["id"] for item in narrow_plan["materialRefs"]}, {item["id"] for item in plan["materialRefs"]})
        self.assertLessEqual(set(narrow_plan["capabilities"]), set(plan["capabilities"]))
        for artifact in narrow["artifacts"]:
            self.assert_binding_provenance(artifact, narrow_plan, narrow["snapshot"]["remoteHandoff"])
            raw = self.call(self.origin, "GET", f"/jobs/{grandchild['job']['id']}/artifacts/{artifact['id']}")
            self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact["sha256"])
        self.call(self.origin, "GET", "/jobs/" + proxy, actor=OTHER_OWNER, expected=404)
        self.call(self.origin, "GET", "/jobs/" + str(uuid4()) + "~" + native_child, expected=404)
        self.call(self.origin, "POST", "/jobs/" + proxy + "/cancel")
        self.wait(self.origin, proxy, {"canceled"})
        self.assertEqual(self.call(self.origin, "GET", "/jobs/" + task).json()["job"]["status"], "waiting_input")
        self.call(self.origin, "POST", "/jobs/" + task + "/cancel")
        canceled = self.stopped(self.origin, task, "canceled")
        self.assertTrue(canceled["snapshot"]["delegation"]["allStopped"])
        self.assertTrue(canceled["snapshot"]["remoteHandoff"]["allStopped"])
        self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)

    def test_08_cancel_before_receiver_review_has_positive_no_dispatch_proof_and_releases_only_owned_hold(self):
        before = self.receiver.facts()["nativeTickets"]
        task, _, receipt = self.prepare(self.plan())
        canceled = self.call(self.origin, "POST", "/jobs/" + task + "/cancel").json()
        self.assertEqual(canceled["status"], "canceled")
        for _ in range(3):
            evidence = self.call(self.receiver, "GET", "/remote-handoffs/" + receipt["id"]).json()
            self.assertEqual(evidence["state"], "CANCELLED_NO_DISPATCH")
            self.assertTrue(evidence["allStopped"])
            self.assertIsNone(evidence["remoteTaskId"])
            self.assertIsNone(evidence["remoteRunId"])
            self.assertEqual(evidence["receiverBindingProof"], receipt["receiverBindingProof"])
        self.assert_no_ticket(task, before)
        owned = next(row for row in self.origin.facts()["tasks"] if row["id"] == task)
        self.assertTrue(owned["terminal"])
        self.assertTrue(owned["cancel_requested"])

    def test_09_registered_remote_orx_tool_actual_native_effect_and_controlled_discovery_artifact(self):
        separate = OwnedRemotePair(os.environ["FACTORY_TEST_DATABASE_URL"], registered_tools=True).start()
        previous_origin, previous_receiver, previous_tasks = self.origin, self.receiver, self.tasks
        self.origin, self.receiver, self.tasks = separate.origin, separate.receiver, []
        try:
            plan, task, body, _ = self.execute("discovery")
            self.assertIn("orx_discover", plan["tools"])
            completed = self.wait(self.origin, task, {"completed"})
            receipt = completed["snapshot"]["remoteHandoff"]
            for item in completed["artifacts"]:
                self.assert_binding_provenance(item, plan, receipt)
            mapped = next(entry for entry in receipt["receiverBindingProof"]["entries"] if entry["kind"] == "tool" and entry["sourceSpec"]["toolName"] == "orx_discover")
            self.assertEqual(mapped["sourceSpec"]["connection"], self.origin.facts()["orxConnection"])
            self.assertEqual(mapped["effectiveSpec"]["connection"], self.receiver.facts()["orxConnection"])
            artifact = next(item for item in completed["artifacts"] if item["name"].startswith("orx-discovery-"))
            raw = self.call(self.origin, "GET", f"/jobs/{task}/artifacts/{artifact['id']}")
            self.assertEqual(hashlib.sha256(raw.content).hexdigest(), artifact["sha256"])
            document = raw.json()
            self.assertEqual(document["result"]["evidenceKind"], "controlled_transport_fixture")
            self.assertEqual(document["result"]["results"][0]["id"], "W-controlled-tcp-fixture")
            self.assertTrue(any(event["type"] == "orx_discovery_completed" for event in completed["events"]))
            effects = self.call(self.receiver, "GET", "/remote-handoffs/" + receipt["id"]).json()["effects"]
            self.assertEqual(len(effects), 1)
            self.assertEqual(effects[0]["status"], "DONE")
            self.call(self.origin, "POST", "/instances", expected=202, json=body)
            self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)
            self.assertEqual(self.receiver.facts(receipt["remoteTaskId"])["nativeTickets"], 1)
        finally:
            self.origin, self.receiver, self.tasks = previous_origin, previous_receiver, previous_tasks
            separate.close()

    def test_07_lost_dispatch_ack_receiver_restart_reconciles_one_original_native_ticket(self):
        plan = self.plan("paused")
        task, body, receipt = self.prepare(plan)
        self.approve(self.receiver, receipt["remotePlanId"])
        previous_pid = self.receiver.process.pid
        self.receiver.control("fault", fault="exit_after_dispatch")
        uncertain = self.call(self.origin, "POST", "/instances", expected=202, json=body).json()
        self.assertEqual(uncertain["id"], task)
        self.assertEqual(uncertain["status"], "unknown")
        self.receiver.process.wait(5)
        marker = json.loads((self.pair.path / "receiver-fault.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["pid"], previous_pid)
        self.assertEqual(marker["phase"], "after-native-dispatch-before-http-ack")
        original = next(row for row in self.origin.facts()["placements"] if row["task_id"] == task)
        self.assertTrue(original["body"]["dispatchAttempted"])
        self.receiver.start()
        self.assertNotEqual(self.receiver.process.pid, previous_pid)
        paused = self.wait(self.origin, task, {"waiting_input"}, seconds=20)
        recovered = paused["snapshot"]["remoteHandoff"]
        self.assertEqual(recovered["id"], receipt["id"])
        self.assertEqual(recovered["receiverBindingProof"], receipt["receiverBindingProof"])
        self.assertEqual(self.receiver.facts(recovered["remoteTaskId"])["nativeTickets"], 1)
        self.call(self.origin, "POST", "/instances", expected=202, json=body)
        self.call(self.origin, "POST", "/jobs/" + task + "/reconcile")
        self.assertEqual(self.receiver.facts(recovered["remoteTaskId"])["nativeTickets"], 1)
        self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)


if __name__ == "__main__":
    unittest.main()

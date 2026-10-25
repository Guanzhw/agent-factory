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
import tempfile
import time
import unittest
from uuid import uuid4


from pg_fixture import IsolatedPostgres
from controlled_remote_worker import (MODEL_RECEIVER, MODEL_SOURCE, OTHER_OWNER,
    TARGET_REF)
from agent_factory.store import digest

from controlled_remote_server import OwnedServer, loopback_port


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
        self.origin.control('dispatch-release')

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
            "connectionRefs": {"provider": facts["connection"]["ref"]}, "requestId": uuid4().hex}).json()
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal)
        plan = self.call(self.origin, "POST", f"/compositions/proposals/{proposal['id']}/accept", expected=201,
            json={"requestId": uuid4().hex}).json()
        self.assertFalse(plan["syntheticFixture"])
        self.assertEqual(plan["policy"], "member-self-service")
        return plan

    def prepare(self, plan):
        self.origin.control('dispatch-hold')
        body = {"planId": plan["id"], "requestId": uuid4().hex, "executionTargetRef": TARGET_REF}
        initial = self.call(self.origin, "POST", "/instances", expected=202, json=body).json()
        task = initial["id"]
        self.tasks.append(task)
        placement = next(row for row in self.origin.facts()['placements'] if row['task_id'] == task)
        receipt_id = placement['body']['receipt']['id']
        receipt = self.call(self.receiver, 'GET', '/remote-handoffs/' + receipt_id).json()
        self.assertEqual(receipt['state'], 'PREPARED')
        self.assertIsNotNone(receipt["remoteTaskId"])
        self.assertIsNone(receipt["remoteRunId"])
        return task, body, receipt

    def execute(self, mode="direct"):
        plan = self.plan(mode)
        task, body, receipt = self.prepare(plan)
        self.origin.control('dispatch-release')
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

    def test_01_real_tcp_member_mapping_staging_single_admission_and_artifact_integrity(self):
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
        self.origin.control('dispatch-release')
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

    def test_03_mapping_and_receiver_connection_rotation_block_prepared_dispatch(self):
        for operation in ("mapping-rotate", "connection-rotate"):
            with self.subTest(operation=operation):
                self.receiver.control("mapping-restore"); self.receiver.control("connection-restore")
                before = self.receiver.facts()["nativeTickets"]
                task, body, receipt = self.prepare(self.plan())
                self.origin.control('dispatch-release')
                self.receiver.control(operation)
                self.call(self.origin, "POST", "/instances", expected=409, json=body)
                self.assert_no_ticket(task, before)
                evidence = self.call(self.receiver, "GET", "/remote-handoffs/" + receipt["id"]).json()
                self.assertEqual(evidence["receiverBindingProof"], receipt["receiverBindingProof"])
                self.receiver.control("mapping-restore"); self.receiver.control("connection-restore")

    def test_04_both_current_account_disables_stop_paused_native_work_without_checksum(self):
        for revoked in (self.origin, self.receiver):
            with self.subTest(role=revoked.configuration["role"]):
                try:
                    _, task, body, _ = self.execute("paused")
                    paused = self.wait(self.origin, task, {"waiting_input"})
                    remote = paused["snapshot"]["remoteHandoff"]["remoteTaskId"]
                    revoked.control("role-revoke")
                    if revoked is self.receiver:
                        self.call(self.receiver, 'GET', '/jobs/' + remote, expected=403)
                        deadline = time.monotonic() + 12
                        while time.monotonic() < deadline:
                            facts = self.receiver.facts(remote)
                            if facts['nativeStatus'] in {'failed', 'cancelled', 'error'}:
                                break
                            time.sleep(.04)
                        else:
                            self.fail('Disabled receiver did not terminate its original native ticket')
                        self.assertEqual(facts['artifacts'], [])
                        self.assertFalse(any(event['type'] == 'checksum_completed' for event in facts['events']))
                        # Restore read access only after the native stop proof.
                        revoked.control('role-restore')
                    failed = self.stopped(self.receiver, remote, "failed")
                    self.assertTrue(failed["snapshot"]["delegation"]["allStopped"])
                    self.assertEqual(failed["artifacts"], [])
                    self.assertFalse(any(event["type"] == "checksum_completed" for event in failed["events"]))
                    question = paused["job"]["questionDetail"]
                    # Source revocation denies authentication; receiver revocation
                    # is already positively stopped at the new intent preflight.
                    self.call(self.origin, "POST", f"/jobs/{task}/answer", expected=403 if revoked is self.origin else 409,
                        json={"questionId": question["id"], "version": question["version"], "answer": "A revoked principal cannot resume this checksum"})
                    if revoked is self.origin:
                        self.call(self.origin, "POST", "/instances", expected=403, json=body)
                    else:
                        # Original-key replay is an authorized source read of
                        # the failed receipt, never another dispatch/resume.
                        repeated = self.call(self.origin, "POST", "/instances", expected=202, json=body).json()
                        self.assertEqual(repeated["id"], task)
                        self.assertEqual(repeated["status"], "failed")
                finally:
                    # A failed origin subtest must not revoke the next case's source.
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

    def test_08_cancel_before_receiver_dispatch_has_positive_no_dispatch_proof_and_releases_only_owned_hold(self):
        before = self.receiver.facts()["nativeTickets"]
        task, _, receipt = self.prepare(self.plan())
        canceled = self.call(self.origin, "POST", "/jobs/" + task + "/cancel").json()
        self.assertIn(canceled["status"], {"canceling", "canceled"})
        command = canceled["commandReceipt"]
        self.assertEqual(command["state"], "STOP_CONFIRMED")
        self.assertEqual(command["evidence"]["kind"], "receiver-command")
        recovered = self.call(self.origin, "GET", f'/jobs/{task}/commands/{command["commandId"]}').json()
        self.assertEqual(recovered["fingerprint"], command["fingerprint"])
        self.assertTrue(recovered["stopConfirmed"])
        for _ in range(3):
            evidence = self.call(self.receiver, "GET", "/remote-handoffs/" + receipt["id"]).json()
            self.assertEqual(evidence["state"], "CANCELLED_NO_DISPATCH")
            self.assertTrue(evidence["allStopped"])
            self.assertEqual(evidence["remoteTaskId"], receipt["remoteTaskId"])
            self.assertIsNone(evidence["remoteRunId"])
            self.assertEqual(evidence["receiverBindingProof"], receipt["receiverBindingProof"])
        # Receiver command proof precedes the origin observer's capacity release.
        self.wait(self.origin, task, {"canceled"})
        self.assert_no_ticket(task, before)
        owned = next(row for row in self.origin.facts()["tasks"] if row["id"] == task)
        self.assertTrue(owned["terminal"])
        self.assertTrue(owned["cancel_requested"])


    def test_07_lost_dispatch_ack_receiver_restart_reconciles_one_original_native_ticket(self):
        plan = self.plan("paused")
        task, body, receipt = self.prepare(plan)
        self.origin.control('dispatch-release')
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

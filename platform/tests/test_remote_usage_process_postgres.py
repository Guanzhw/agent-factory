"""Real two-service native metered attempts; prices/usage are synthetic only.

No network provider/model request is made. Operator fixtures exercise the same
durable Factory handoff, native model admission and origin/receiver accounting.
"""
from __future__ import annotations

import json
import os

import httpx
import unittest
from uuid import uuid4

from agent_factory.store import digest
from controlled_remote_worker import ORIGIN_REF, ORIGIN_OWNER, RECEIVER_OWNER, MODEL_RECEIVER, MODEL_SOURCE, TARGET_REF
import test_governed_remote_process_postgres as process_fixture


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires owned loopback PostgreSQL")
class RemoteUsageProcessPostgresTests(unittest.TestCase):
    call = process_fixture.GovernedRemoteProcessPostgresTests.call
    plan = process_fixture.GovernedRemoteProcessPostgresTests.plan
    approve = process_fixture.GovernedRemoteProcessPostgresTests.approve
    prepare = process_fixture.GovernedRemoteProcessPostgresTests.prepare
    execute = process_fixture.GovernedRemoteProcessPostgresTests.execute
    wait = process_fixture.GovernedRemoteProcessPostgresTests.wait
    stopped = process_fixture.GovernedRemoteProcessPostgresTests.stopped

    @classmethod
    def setUpClass(cls):
        cls.pair = process_fixture.OwnedRemotePair(os.environ["FACTORY_TEST_DATABASE_URL"], usage_profile="metered").start()
        cls.addClassCleanup(cls.pair.close)
        cls.origin, cls.receiver = cls.pair.origin, cls.pair.receiver

    def setUp(self):
        self.tasks = []
        for server in (self.origin, self.receiver):
            if server.process.poll() is not None:
                server.start()
            server.control("role-restore")
            server.control("usage-price-restore")
            server.control("usage-known")

    def tearDown(self):
        for server in (self.origin, self.receiver):
            if server.process.poll() is not None:
                server.start()
            server.control("role-restore")
            server.control("usage-price-restore")
            server.control("usage-known")
        for task in self.tasks:
            self.call(self.origin, "POST", f"/jobs/{task}/cancel")

    def usage(self, server, task):
        return server.facts(task)["usageLedger"]

    def task_scope(self, value, task):
        return next(scope for scope in value["scopes"] if scope["scope"] == "task" and scope["id"] == task)

    def grant(self, server, identifier):
        return next(row for row in server.facts()["usageGrants"] if row["id"] == identifier)

    def test_01_actual_native_usage_settles_origin_task_user_and_exact_receiver_quote(self):
        plan, task, body, prepared = self.execute()
        source_hash = digest(plan)
        self.assertEqual(plan["usageBudget"]["adapterId"], MODEL_SOURCE)
        self.assertEqual(prepared["receiverUsageCommitment"]["adapterId"], MODEL_RECEIVER)
        completed = self.wait(self.origin, task, {"completed"})
        receipt = completed["snapshot"]["remoteHandoff"]
        remote = receipt["remoteTaskId"]
        self.assertTrue(receipt["allStopped"])
        self.assertEqual(receipt["receiverUsageCommitment"], prepared["receiverUsageCommitment"])
        self.assertEqual(receipt["receiverPlanSha256"], prepared["receiverPlanSha256"])
        source = self.usage(self.origin, task)
        actual = self.usage(self.receiver, remote)
        self.assertEqual(len(actual["attempts"]), 2)
        self.assertTrue(all(a["state"] == "SETTLED" for a in actual["attempts"]))
        for scope in (self.task_scope(source, task), self.task_scope(actual, remote)):
            self.assertEqual((scope["settledTokens"], scope["settledAmountMicros"], scope["heldTokens"], scope["heldAmountMicros"]), (10, 14, 0, 0))
        self.assertGreaterEqual(next(s for s in source["scopes"] if s["scope"] == "user")["settledTokens"], 10)
        self.assertEqual(completed["usageLedger"], source)
        self.assertEqual(source["attempts"], [])  # Every native attempt belongs to receiver.
        statement = receipt["usageStatement"]
        self.assertEqual(statement["sha256"], digest({k: v for k, v in statement.items() if k != "sha256"}))
        self.assertEqual((statement["settledTokens"], statement["settledAmountMicros"]), (10, 14))
        self.assertEqual(self.grant(self.origin, receipt["id"])["state"], "SETTLED")
        self.assertEqual(self.grant(self.receiver, receipt["id"])["state"], "CLOSED")
        receiver_plan = self.receiver.facts(remote)["plan"]
        self.assertEqual(receiver_plan["usageBudget"], plan["usageBudget"])
        self.assertEqual(digest(self.origin.facts(task)["plan"]), source_hash)
        before = self.task_scope(source, task)
        self.call(self.origin, "POST", "/instances", expected=202, json=body)
        self.call(self.origin, "POST", f"/jobs/{task}/reconcile")
        self.assertEqual(self.task_scope(self.usage(self.origin, task), task), before)
        self.assertEqual(self.receiver.facts(remote)["nativeTickets"], 1)
        self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)

    def test_02_unknown_authoritative_usage_stays_held_after_positive_cancel_and_restart(self):
        self.receiver.control("usage-unknown")
        _, task, _, _ = self.execute("paused")
        paused = self.wait(self.origin, task, {"waiting_input"})
        receipt = paused["snapshot"]["remoteHandoff"]
        remote = receipt["remoteTaskId"]
        actual = self.usage(self.receiver, remote)
        self.assertEqual([a["state"] for a in actual["attempts"]], ["UNKNOWN"])
        self.assertEqual(self.task_scope(actual, remote)["heldTokens"], 12)
        self.call(self.origin, "POST", f"/jobs/{task}/cancel")
        canceled = self.stopped(self.origin, task, "canceled")
        self.assertTrue(canceled["snapshot"]["remoteHandoff"]["allStopped"])
        statement = canceled["snapshot"]["remoteHandoff"]["usageStatement"]
        self.assertEqual((statement["heldTokens"], statement["heldAmountMicros"]), (12, 16))
        held = self.task_scope(self.usage(self.origin, task), task)
        self.assertEqual((held["heldTokens"], held["heldAmountMicros"], held["settledTokens"]), (40, 64, 0))
        self.assertEqual(self.grant(self.origin, receipt["id"])["state"], "ALLOCATED")
        for server in (self.receiver, self.origin):
            old = server.process.pid
            server.stop(); server.start()
            self.assertNotEqual(old, server.process.pid)
        self.call(self.origin, "POST", f"/jobs/{task}/reconcile")
        self.assertEqual(self.task_scope(self.usage(self.origin, task), task), held)
        self.assertEqual([a["state"] for a in self.usage(self.receiver, remote)["attempts"]], ["UNKNOWN"])
        self.assertEqual(self.receiver.facts(remote)["nativeTickets"], 1)

    def test_03_lost_http_ack_restart_recovers_original_grant_and_single_native_ticket(self):
        task, body, receipt = self.prepare(self.plan("paused"))
        self.approve(self.receiver, receipt["remotePlanId"])
        self.receiver.control("fault", fault="exit_after_queued_dispatch")
        uncertain = self.call(self.origin, "POST", "/instances", expected=202, json=body).json()
        self.assertEqual(uncertain["status"], "unknown")
        self.receiver.process.wait(5)
        marker = json.loads((self.pair.path / "receiver-fault.json").read_text(encoding="utf-8"))
        self.assertTrue(marker["workerStopped"])
        self.assertEqual(marker["phase"], "after-native-dispatch-before-http-ack")
        original = self.grant(self.origin, receipt["id"])
        self.assertEqual(original["body"]["receiverCommitmentSha256"], receipt["receiverUsageCommitment"]["sha256"])
        self.receiver.start()
        paused = self.wait(self.origin, task, {"waiting_input"}, seconds=25)
        recovered = paused["snapshot"]["remoteHandoff"]
        self.assertEqual(recovered["usageGrant"], {"id": original["id"], "sha256": original["hash"]})
        self.assertEqual(self.grant(self.receiver, receipt["id"])["hash"], original["hash"])
        remote = recovered["remoteTaskId"]
        old_origin = self.origin.process.pid
        self.origin.stop(); self.origin.start()
        self.assertNotEqual(old_origin, self.origin.process.pid)
        self.call(self.origin, "POST", "/instances", expected=202, json=body)
        self.call(self.origin, "POST", f"/jobs/{task}/reconcile")
        self.assertEqual(self.receiver.facts(remote)["nativeTickets"], 1)
        self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)
        self.assertEqual(self.grant(self.origin, receipt["id"])["hash"], original["hash"])
        self.assertEqual(len(self.usage(self.receiver, remote)["attempts"]), 1)

    def test_04_receiver_child_narrowing_consumes_same_original_origin_grant(self):
        _, task, _, _ = self.execute("paused")
        self.wait(self.origin, task, {"waiting_input"})
        body = {"goal": "Narrow controlled remote child", "mode": "direct", "requestId": uuid4().hex}
        child = self.call(self.origin, "POST", f"/jobs/{task}/children", expected=202, json=body).json()
        proxy = child["job"]["id"]
        completed = self.wait(self.origin, proxy, {"completed"})
        native = proxy.split("~", 1)[1]
        actual = self.usage(self.receiver, native)
        self.assertEqual(len(actual["attempts"]), 2)
        self.assertTrue(all(a["state"] == "SETTLED" for a in actual["attempts"]))
        self.assertEqual(self.receiver.facts(native)["plan"]["tools"], ["checksum"])
        self.assertEqual(actual["migration"]["sourcePlanSha256"], digest(self.receiver.facts(native)["plan"]))
        self.assertEqual(completed["usageLedger"]["taskId"], proxy)
        self.assertEqual(completed["usageLedger"]["rootTaskId"], task)
        self.assertEqual(completed["usageLedger"]["ownerId"], ORIGIN_OWNER)
        # Refresh root statement after the actual child attempts settle.
        root = self.call(self.origin, "GET", f"/jobs/{task}").json()
        statement = root["snapshot"]["remoteHandoff"]["usageStatement"]
        self.assertEqual((statement["settledTokens"], statement["settledAmountMicros"]), (15, 21))
        scope = self.task_scope(self.usage(self.origin, task), task)
        self.assertEqual((scope["settledTokens"], scope["heldTokens"]), (15, 25))
        self.assertEqual(len(self.receiver.facts()["usageGrants"]), len(self.origin.facts()["usageGrants"]))
        self.call(self.origin, "POST", f"/jobs/{task}/cancel")
        self.stopped(self.origin, task, "canceled")
        scope = self.task_scope(self.usage(self.origin, task), task)
        self.assertEqual((scope["settledTokens"], scope["settledAmountMicros"], scope["heldTokens"]), (15, 21, 0))
        self.assertEqual(self.receiver.facts(native)["nativeTickets"], 1)

    def test_05_changed_pricing_or_model_refuses_reviewed_receiver_before_native_admission(self):
        for operation in ("usage-price-change", "usage-model-change"):
            with self.subTest(operation=operation):
                self.receiver.control("usage-price-restore")
                task, body, receipt = self.prepare(self.plan())
                before = self.receiver.facts()["nativeTickets"]
                self.approve(self.receiver, receipt["remotePlanId"])
                self.receiver.control(operation)
                self.call(self.origin, "POST", "/instances", expected=409, json=body)
                self.assertEqual(self.receiver.facts()["nativeTickets"], before)
                self.assertFalse(any(g["task_id"] == task for g in self.origin.facts()["usageGrants"]))
                self.assertEqual(self.origin.facts(task)["nativeTickets"], 0)
                self.receiver.control("usage-price-restore")

    def test_06_forged_receiver_grant_cannot_skip_actual_origin_reservation(self):
        plan = self.plan()
        task, body, pending = self.prepare(plan)
        self.approve(self.receiver, pending["remotePlanId"])
        prepared = self.call(self.receiver, "POST", "/remote-handoffs/prepare", expected=201, json={
            "originRef": ORIGIN_REF, "originOwnerId": ORIGIN_OWNER, "originTaskId": task,
            "requestId": body["requestId"], "manifest": {"plan": plan, "sha256": digest(plan)}}).json()
        self.assertEqual(prepared["state"], "PREPARED")
        quote = prepared["receiverUsageCommitment"]
        grant = {"schema": 1, "id": prepared["id"], "originRef": ORIGIN_REF,
            "targetRef": TARGET_REF,
            "originOwnerId": ORIGIN_OWNER, "originTaskId": task, "sourcePlanSha256": digest(plan),
            "sourceCommitmentSha256": plan["usageBudget"]["sha256"], "receiverOwnerId": RECEIVER_OWNER,
            "receiverTaskId": prepared["remoteTaskId"], "receiverPlanSha256": prepared["receiverPlanSha256"],
            "receiverCommitmentSha256": quote["sha256"], "receiverCommitment": quote,
            "currency": quote["currency"], "tokenLimit": quote["tokenLimit"], "amountMicros": quote["amountMicros"]}
        # Even a correctly hashed native-shape grant is untrusted without the
        # existing current-origin response's exact durable allocation SHA.
        grant["sha256"] = digest(grant)
        before = self.receiver.facts()["nativeTickets"]
        denied = self.call(self.receiver, "POST", f"/remote-handoffs/{prepared['id']}/dispatch", expected=403,
            json={"usageGrant": grant})
        self.assertIn("USAGE_REMOTE_ATTESTATION", denied.text)
        self.assertEqual(self.receiver.facts()["nativeTickets"], before)
        self.assertFalse(any(g["id"] == prepared["id"] for g in self.receiver.facts()["usageGrants"]))
        self.call(self.origin, "POST", "/instances", expected=202, json=body)
        completed = self.wait(self.origin, task, {"completed"})
        self.assertEqual(completed["snapshot"]["remoteHandoff"]["id"], prepared["id"])
        self.assertEqual(self.receiver.facts(prepared["remoteTaskId"])["nativeTickets"], 1)
        self.assertEqual(self.grant(self.origin, prepared["id"])["state"], "SETTLED")

    def test_07_origin_interrupt_after_allocation_never_retries_and_positive_no_dispatch_reclaims(self):
        task, body, receipt = self.prepare(self.plan())
        self.approve(self.receiver, receipt["remotePlanId"])
        before, old_pid = self.receiver.facts()["nativeTickets"], self.origin.process.pid
        self.origin.control("fault", fault="exit_before_remote_dispatch")
        with self.assertRaises(httpx.HTTPError):
            self.origin.request("POST", "/api/factory/instances", json=body)
        self.origin.process.wait(5)
        marker = json.loads((self.pair.path / "origin-fault.json").read_text(encoding="utf-8"))
        self.assertEqual((marker["pid"], marker["phase"]), (old_pid, "after-origin-allocation-before-transport"))
        self.assertEqual(self.receiver.facts()["nativeTickets"], before)
        self.assertFalse(any(g["id"] == receipt["id"] for g in self.receiver.facts()["usageGrants"]))
        self.origin.start()
        self.assertNotEqual(self.origin.process.pid, old_pid)
        original = self.grant(self.origin, receipt["id"])
        self.assertEqual(original["hash"], marker["grantSha256"])
        held = self.task_scope(self.usage(self.origin, task), task)
        self.assertEqual((held["heldTokens"], held["heldAmountMicros"]), (40, 64))
        for _ in range(2):
            self.call(self.origin, "POST", "/instances", expected=202, json=body)
            self.call(self.origin, "POST", f"/jobs/{task}/reconcile")
        self.assertEqual(self.receiver.facts()["nativeTickets"], before)
        self.assertEqual(self.grant(self.origin, receipt["id"])["hash"], original["hash"])
        self.call(self.origin, "POST", f"/jobs/{task}/cancel")
        positive = self.call(self.receiver, "GET", f"/remote-handoffs/{receipt['id']}").json()
        self.assertEqual(positive["state"], "CANCELLED_NO_DISPATCH")
        self.assertTrue(positive["allStopped"])
        self.assertIsNone(positive["native"])
        self.assertIsNone(positive["remoteRunId"])
        closed = self.grant(self.origin, receipt["id"])
        self.assertEqual(closed["state"], "SETTLED")
        self.assertEqual(closed["body"], original["body"])
        final = self.task_scope(self.usage(self.origin, task), task)
        self.assertEqual((final["heldTokens"], final["heldAmountMicros"], final["settledTokens"], final["settledAmountMicros"]), (0, 0, 0, 0))
        self.call(self.origin, "POST", f"/jobs/{task}/cancel")
        self.assertEqual(self.task_scope(self.usage(self.origin, task), task), final)
        self.assertEqual(self.receiver.facts()["nativeTickets"], before)

    def test_08_source_pricing_model_drift_revokes_existing_receiver_attempt_authority(self):
        for operation in ("usage-price-change", "usage-model-change"):
            with self.subTest(operation=operation):
                self.origin.control("usage-price-restore")
                _, task, _, _ = self.execute("paused")
                paused = self.wait(self.origin, task, {"waiting_input"})
                receipt = paused["snapshot"]["remoteHandoff"]
                remote = receipt["remoteTaskId"]
                self.assertEqual(len(self.usage(self.receiver, remote)["attempts"]), 1)
                self.origin.control(operation)
                failed = self.stopped(self.receiver, remote, "failed")
                self.assertEqual(failed["artifacts"], [])
                self.assertFalse(any(e["type"] == "checksum_completed" for e in failed["events"]))
                self.assertEqual(len(self.usage(self.receiver, remote)["attempts"]), 1)
                current = self.call(self.origin, "GET", f"/jobs/{task}").json()
                statement = current["snapshot"]["remoteHandoff"]["usageStatement"]
                self.assertTrue(statement["allStopped"])
                self.assertEqual((statement["settledTokens"], statement["settledAmountMicros"]), (5, 7))
                scope = self.task_scope(self.usage(self.origin, task), task)
                self.assertEqual((scope["settledTokens"], scope["settledAmountMicros"], scope["heldTokens"]), (5, 7, 0))
                self.origin.control("usage-price-restore")


if __name__ == "__main__":
    unittest.main()

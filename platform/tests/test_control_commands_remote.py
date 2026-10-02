"""Dual-database command receipts across the real guarded Factory routes."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_remote_execution_postgres as fixture


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class RemoteControlCommandPostgresTests(unittest.TestCase):
    headers = fixture.RemoteExecutionProductPostgresTests.headers
    request = fixture.RemoteExecutionProductPostgresTests.request
    plan = fixture.RemoteExecutionProductPostgresTests.plan
    submit = fixture.RemoteExecutionProductPostgresTests.submit
    wait = fixture.RemoteExecutionProductPostgresTests.wait
    ticket_count = fixture.RemoteExecutionProductPostgresTests.ticket_count
    install_transport = fixture.RemoteExecutionProductPostgresTests.install_transport
    setUp = fixture.RemoteExecutionProductPostgresTests.setUp
    tearDown = fixture.RemoteExecutionProductPostgresTests.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.RemoteExecutionProductPostgresTests.setUpClass.__func__(cls)

    def waiting(self):
        job, _ = self.submit(self.plan("sort", application="research"))
        return self.wait(job["id"], {"waiting_input"})

    def command(self, detail):
        question = detail["job"]["questionDetail"]
        return {"commandId": str(uuid4()), "action": "answer", "requirementId": question["id"],
                "version": question["version"], "answer": "Controlled remote decision scope"}

    def test_remote_answer_commit_lost_reply_recovers_both_exact_command_receipts(self):
        detail = self.waiting()
        task = detail["job"]["id"]
        remote = detail["snapshot"]["remoteHandoff"]["remoteTaskId"]
        command = self.command(detail)
        loss = fixture.ControlledDispatchLoss(self.receiver_app, suffix="/commands")
        self.install_transport(loss)
        first = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
        self.assertTrue(first["decisionRecorded"], first)
        self.assertEqual(first["evidence"]["kind"], "receiver-command")
        second = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
        self.assertEqual(second["fingerprint"], first["fingerprint"])
        self.assertEqual(loss.attempts, 1)
        rows = self.receiver["store"].sql("SELECT * FROM af_control_commands WHERE command_id=:id", id=command["commandId"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_ref"], remote)
        self.assertEqual(rows[0]["body"]["binding"]["upstream"]["sourceFingerprint"], first["fingerprint"])
        self.assertEqual(self.ticket_count(self.receiver, remote), 1)
        self.assertEqual(self.ticket_count(self.origin, task), 0)
        self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}', owner="bob", expected=404)

    def test_remote_child_command_is_bound_to_exact_tree_member_and_cancel_receipt(self):
        parent = self.waiting()
        root = parent["job"]["id"]
        child = self.request("POST", f"/jobs/{root}/children", expected=202,
            json={"goal": "sort", "mode": "literature", "requestId": str(uuid4())}).json()["job"]["id"]
        detail = self.wait(child, {"waiting_input"})
        command = self.command(detail)
        receipt = self.request("POST", f"/jobs/{child}/commands", expected=202, json=command).json()
        self.assertTrue(receipt["decisionRecorded"], receipt)
        self.assertEqual(receipt["binding"]["remoteChildId"], child.split("~", 1)[1])
        self.request("GET", f'/jobs/{root}/commands/{command["commandId"]}', expected=404)
        self.request("POST", f"/jobs/{root}/commands", expected=409, json=command)
        child_cancel = {"commandId": str(uuid4()), "action": "cancel"}
        child_receipt = self.request("POST", f"/jobs/{child}/commands", expected=202, json=child_cancel).json()
        self.assertTrue(child_receipt["decisionRecorded"], child_receipt)
        self.assertEqual(child_receipt["binding"]["remoteChildId"], child.split("~", 1)[1])
        self.assertFalse(self.origin["store"].task(root)["cancel_requested"])
        # Root cancellation is independently scoped and persisted on both sides.
        cancel = {"commandId": str(uuid4()), "action": "cancel"}
        loss = fixture.ControlledDispatchLoss(self.receiver_app, suffix="/commands")
        self.install_transport(loss)
        value = self.request("POST", f"/jobs/{root}/commands", expected=202, json=cancel).json()
        self.assertTrue(value["decisionRecorded"], value)
        self.request("POST", f"/jobs/{root}/commands", expected=202, json=cancel)
        self.assertEqual(loss.attempts, 1)
        self.assertEqual(len(self.receiver["store"].sql("SELECT 1 FROM af_control_commands WHERE command_id=:id", id=cancel["commandId"])), 1)

    def test_missing_receiver_command_is_unknown_and_never_reposted_by_recovery(self):
        detail = self.waiting()
        task, command = detail["job"]["id"], self.command(detail)
        loss = fixture.ControlledDispatchLoss(self.receiver_app, before_delivery=True, suffix="/commands")
        self.install_transport(loss)
        value = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
        self.assertEqual(value["state"], "UNKNOWN")
        with patch.object(self.handoff, "control_command", side_effect=AssertionError("Read recovery must not dispatch")):
            for _ in range(2):
                value = self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}').json()
                self.assertEqual(value["state"], "UNKNOWN")
                self.request("POST", f"/jobs/{task}/commands", expected=202, json=command)
        self.assertEqual(loss.attempts, 1)
        self.assertEqual(self.receiver["store"].sql("SELECT 1 FROM af_control_commands WHERE command_id=:id", id=command["commandId"]), [])

    def test_changed_receiver_identity_proof_and_revoked_owner_refuse_command(self):
        detail = self.waiting()
        task, command = detail["job"]["id"], self.command(detail)
        original = self.handoff._request
        async def wrong(owner, target, method, path, **kwargs):
            value = await original(owner, target, method, path, **kwargs)
            if "/commands" in path and isinstance(value, dict):
                return {**value, "taskId": str(uuid4())}
            return value
        with patch.object(self.handoff, "_request", side_effect=wrong):
            value = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
            self.assertEqual(value["state"], "UNKNOWN")
        value = self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}').json()
        self.assertTrue(value["decisionRecorded"])
        auth = self.origin["auth"].authorization
        auth.define_role("fixture-product-reader", ["agents:factory-executor:read", "sessions:read", "components:read", "registry:read"])
        auth.unassign("alice", "factory-user")
        auth.assign("alice", "fixture-product-reader")
        self.request("POST", f"/jobs/{task}/commands", expected=403, json=command)
        self.assertTrue(self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}').json()["decisionRecorded"])

    def test_remote_approve_and_reject_lost_reply_preserve_exact_decision(self):
        for approved in (False, True):
            with self.subTest(approved=approved):
                job, _ = self.submit(self.plan("Evaluate controlled remote sorting", mode="experiment", application="research"))
                task = job["id"]
                detail = self.wait(task, {"waiting_approval"})
                requirement = detail["job"]["approvalDetail"]
                command = {"commandId": str(uuid4()), "action": "approve", "requirementId": requirement["id"],
                           "version": requirement["version"], "approved": approved}
                loss = fixture.ControlledDispatchLoss(self.receiver_app, suffix="/commands")
                self.install_transport(loss)
                receipt = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
                self.assertTrue(receipt["decisionRecorded"], receipt)
                self.assertEqual(receipt["approved"], approved)
                self.request("POST", f"/jobs/{task}/commands", expected=202, json=command)
                self.assertEqual(loss.attempts, 1)
                self.request("POST", f"/jobs/{task}/commands", expected=409, json={**command, "approved": not approved})
                self.request("POST", f"/jobs/{task}/cancel")
                self.wait(task, {"canceled", "failed", "completed"})

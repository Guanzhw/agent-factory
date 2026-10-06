"""Durable command fault boundaries against actual PostgreSQL/native execution."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.control_commands import ControlCommand
from agent_factory.factory_api import FactoryAPI
import test_factory_postgres as fixture


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class ControlCommandPostgresTests(unittest.TestCase):
    login = fixture.FactoryPostgresTests.login
    plan = fixture.FactoryPostgresTests.plan
    submit = fixture.FactoryPostgresTests.submit
    wait = fixture.FactoryPostgresTests.wait

    @classmethod
    def setUpClass(cls):
        fixture.FactoryPostgresTests.setUpClass.__func__(cls)
        cls.state = cls.app.app.state.factory
        cls.api = FactoryAPI(cls.settings, cls.state["store"], cls.state["auth"], cls.state["bridge"])

    @classmethod
    def tearDownClass(cls):
        fixture.FactoryPostgresTests.tearDownClass.__func__(cls)

    def setUp(self):
        self.login()
        self.tasks = []

    def tearDown(self):
        self.state["auth"].authorization.unassign("alice", "command-reader")
        self.state["auth"].authorization.assign("alice", "factory-user")
        self.login()
        for task in self.tasks:
            self.client.post(f"/api/factory/jobs/{task}/cancel")

    def waiting(self, action="answer"):
        plan, _ = self.plan("sort" if action == "answer" else "Evaluate the controlled sorting candidate", "literature" if action == "answer" else "experiment")
        job, _ = self.submit(plan)
        self.tasks.append(job["id"])
        detail = self.wait(job["id"], {"waiting_input" if action == "answer" else "waiting_approval"})
        requirement = detail["job"]["questionDetail" if action == "answer" else "approvalDetail"]
        command = {"commandId": str(uuid4()), "action": action, "requirementId": requirement["id"], "version": requirement["version"]}
        command.update({"answer": "Private synthetic scope, never browser-persisted"} if action == "answer" else {"approved": True})
        return job["id"], command

    def post(self, task, command):
        return self.client.post(f"/api/factory/jobs/{task}/commands", json=command)

    def receipt(self, task, command):
        response = self.client.get(f'/api/factory/jobs/{task}/commands/{command["commandId"]}')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_answer_native_commit_lost_ack_original_command_recovers_without_continuation_replay(self):
        task, command = self.waiting()
        original = self.state["bridge"].continue_run
        async def lost(*args, **kwargs):
            await original(*args, **kwargs)
            raise HTTPException(503, "Owned fixture drops acknowledgement after actual native commit")
        with patch.object(self.state["bridge"], "continue_run", side_effect=lost) as dispatch:
            response = self.post(task, command)
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(response.json()["decisionRecorded"], response.text)
            self.assertNotIn(command["answer"], response.text)
            self.assertEqual(self.post(task, command).status_code, 202)
            self.assertEqual(dispatch.await_count, 1)
        receipt = self.receipt(task, command)
        native = self.state["store"].task(task)
        ticket = self.state["store"].native_db.get_job(native["run_id"], strict=True)
        self.assertEqual(ticket["payload"]["continue"]["kwargs"]["metadata"]["factoryControlCommand"],
                         {"commandId": command["commandId"], "fingerprint": receipt["fingerprint"]})
        self.assertEqual(receipt["evidence"]["kind"], "native-continuation")
        self.assertEqual(self.post(task, {**command, "answer": "Conflicting answer"}).status_code, 409)
        self.assertEqual(self.post(task, {**command, "commandId": str(uuid4())}).status_code, 409)
        page = self.client.get("/api/factory/commands", params={"taskId": task})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual([item["commandId"] for item in page.json()["items"]], [command["commandId"]])
        self.assertNotIn(command["answer"], page.text)

    def test_approval_and_rejection_have_exact_native_decision_proof_after_lost_ack(self):
        for approved in (False, True):
            with self.subTest(approved=approved):
                task, command = self.waiting("approve")
                command["approved"] = approved
                original = self.state["bridge"].continue_run
                async def lost(*args, **kwargs):
                    await original(*args, **kwargs)
                    raise HTTPException(503, "Owned committed approval response loss")
                with patch.object(self.state["bridge"], "continue_run", side_effect=lost) as dispatch:
                    response = self.post(task, command)
                    self.assertEqual(response.status_code, 202, response.text)
                    self.assertTrue(response.json()["decisionRecorded"], response.text)
                    self.assertEqual(self.receipt(task, command)["approved"], approved)
                    self.assertEqual(self.post(task, command).status_code, 202)
                    self.assertEqual(dispatch.await_count, 1)
                self.client.post(f"/api/factory/jobs/{task}/cancel")
                self.wait(task, {"canceled", "failed", "completed"})

    def test_cancel_during_environment_preflight_settles_never_dispatched_effect(self):
        task, command = self.waiting("approve")
        store = self.state["store"]
        original = store.execution_bindings.environment_limits
        calls = []

        def cancel_before_launch(plan, context):
            calls.append(context.run_id)
            self.assertEqual(store.effects(task)[0]["status"], "UNKNOWN")
            store.request_cancel(task)
            return original(plan, context)

        with patch.object(store.execution_bindings, "environment_limits", side_effect=cancel_before_launch):
            response = self.post(task, command)
            self.assertEqual(response.status_code, 202, response.text)
            detail = self.wait(task, {"canceled"})
        self.assertEqual(len(calls), 1)
        self.assertTrue(store.task(task)["terminal"])
        effects = store.effects(task)
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["status"], "CANCELLED")
        self.assertEqual(effects[0]["result"]["dispatchState"], "never-dispatched")
        self.assertTrue(effects[0]["result"]["cleanupComplete"])
        self.assertFalse(any(event["type"] in {"compute_started", "compute_stopped"} for event in detail["events"]))

    def test_cancel_lost_ack_needs_positive_stop_evidence_and_does_not_repeat_dispatch(self):
        task, _ = self.waiting()
        command = {"commandId": str(uuid4()), "action": "cancel"}
        original = self.state["store"].delegation.cascade_cancel
        async def lost(*args, **kwargs):
            await original(*args, **kwargs)
            raise HTTPException(503, "Owned cancellation reply loss")
        with patch.object(self.state["store"].delegation, "cascade_cancel", side_effect=lost) as dispatch:
            response = self.post(task, command)
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(response.json()["decisionRecorded"])
            self.assertEqual(self.post(task, command).status_code, 202)
            self.assertEqual(dispatch.await_count, 1)
        deadline = time.monotonic() + 10
        receipt = self.receipt(task, command)
        while not receipt["stopConfirmed"] and time.monotonic() < deadline:
            time.sleep(.05)
            receipt = self.receipt(task, command)
        self.assertTrue(receipt["stopConfirmed"], receipt)
        self.assertEqual(receipt["state"], "STOP_CONFIRMED")

    def test_unknown_dispatch_is_not_retried_or_inferred_from_unchanged_requirement(self):
        task, command = self.waiting()
        with patch.object(self.state["bridge"], "continue_run", side_effect=HTTPException(503, "Unknown native boundary")) as dispatch:
            response = self.post(task, command)
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()["state"], "UNKNOWN")
            for _ in range(2):
                self.assertEqual(self.post(task, command).json()["state"], "UNKNOWN")
                self.assertFalse(self.receipt(task, command)["decisionRecorded"])
            self.assertEqual(dispatch.await_count, 1)
        # Reconstruct the service over the same durable store, not an in-memory
        # command cache. Full OS-process restart is covered separately.
        restored = FactoryAPI(self.settings, self.state["store"], self.state["auth"], self.state["bridge"])
        receipt = self.client.portal.call(restored.commands.recover, "alice", task, command["commandId"])
        self.assertEqual(receipt["state"], "UNKNOWN")
        self.assertEqual(self.post(task, {**command, "commandId": str(uuid4())}).status_code, 409)

    def test_concurrent_same_command_dispatches_once_and_conflicting_decision_refuses(self):
        task, command = self.waiting()
        original = self.state["bridge"].continue_run
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        with patch.object(self.state["bridge"], "continue_run", side_effect=blocked) as dispatch, ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.post, task, command)
            try:
                self.client.portal.call(asyncio.wait_for, entered.wait(), 5)
                repeated = self.post(task, command)
                self.assertEqual(repeated.status_code, 202, repeated.text)
                self.assertEqual(repeated.json()["state"], "UNKNOWN")
                self.assertEqual(self.post(task, {**command, "answer": "opposite"}).status_code, 409)
                self.assertEqual(self.post(task, {**command, "commandId": str(uuid4())}).status_code, 409)
            finally:
                self.client.portal.call(release.set)
            response = pending.result(timeout=10)
            self.assertTrue(response.json()["decisionRecorded"], response.text)
            self.assertEqual(dispatch.await_count, 1)

    def test_owner_read_grant_and_stale_requirement_do_not_authorize_new_dispatch(self):
        task, command = self.waiting()
        self.assertEqual(self.post(task, {**command, "version": command["version"] + 1}).status_code, 409)
        response = self.post(task, command)
        self.assertEqual(response.status_code, 202, response.text)
        self.login("bob")
        self.assertEqual(self.client.get(f'/api/factory/jobs/{task}/commands/{command["commandId"]}').status_code, 404)
        self.assertEqual(self.post(task, command).status_code, 404)
        self.login()
        auth = self.state["auth"].authorization
        auth.define_role("command-reader", ["agents:factory-executor:read", "sessions:read", "components:read", "registry:read"])
        auth.unassign("alice", "factory-user")
        auth.assign("alice", "command-reader")
        self.assertTrue(self.receipt(task, command)["decisionRecorded"])
        self.assertEqual(self.post(task, command).status_code, 403)

    def test_prepared_intent_rechecks_permission_and_changed_requirement(self):
        task, command = self.waiting()
        async def retain(service, owner, task_id, command_id):
            return service.public(service.row(owner, task_id, command_id))
        with patch("agent_factory.control_commands.ControlCommands.dispatch", retain):
            self.assertEqual(self.post(task, command).json()["state"], "INTENT_RECORDED")
        path = f'/api/factory/jobs/{task}/commands/{command["commandId"]}/dispatch'
        auth = self.state["auth"].authorization
        auth.unassign("alice", "factory-user")
        auth.define_role("command-reader", ["agents:factory-executor:read", "sessions:read", "components:read", "registry:read"])
        auth.assign("alice", "command-reader")
        self.assertEqual(self.client.post(path).status_code, 403)
        self.assertEqual(self.receipt(task, command)["state"], "INTENT_RECORDED")
        auth.unassign("alice", "command-reader")
        auth.assign("alice", "factory-user")
        # Revocation may already have stopped the first native task. Restoring
        # a role cannot resurrect it; use a fresh task for requirement drift.
        task, command = self.waiting()
        with patch("agent_factory.control_commands.ControlCommands.dispatch", retain):
            self.assertEqual(self.post(task, command).json()["state"], "INTENT_RECORDED")
        path = f'/api/factory/jobs/{task}/commands/{command["commandId"]}/dispatch'
        row = self.api.commands.row("alice", task, command["commandId"])
        native = self.state["store"].task(task)
        # A separate authorized native interaction changes the paused target.
        self.client.portal.call(self.state["bridge"].continue_run, native["run_id"], task, "alice", row["body"]["requirements"])
        self.assertEqual(self.client.post(path).status_code, 409)
        self.assertEqual(self.receipt(task, command)["state"], "REJECTED")
        self.assertEqual(self.client.post(path.removesuffix("dispatch") + "acknowledge").status_code, 200)

    def test_recorded_proof_does_not_claim_current_execution_during_read_failure(self):
        task, command = self.waiting()
        self.assertTrue(self.post(task, command).json()["decisionRecorded"])
        with patch.object(self.state["store"].native_db, "get_job", side_effect=RuntimeError("Owned read failure")):
            receipt = self.receipt(task, command)
        self.assertTrue(receipt["decisionRecorded"])
        self.assertFalse(receipt["executionContinuing"])
        self.assertEqual(receipt["state"], "DECISION_RECORDED")


class ControlCommandSchemaTests(unittest.TestCase):
    def test_exact_decision_fields_and_strict_types(self):
        good = {"commandId": "owned-command", "action": "approve", "requirementId": "requirement", "version": 1, "approved": False}
        self.assertFalse(ControlCommand.model_validate(good).approved)
        for body in ({**good, "approved": "false"}, {**good, "version": True}, {**good, "answer": "wrong kind"},
                     {**good, "ownerId": "manager"}, {"commandId": "short", "action": "cancel"}):
            with self.assertRaises(ValueError):
                ControlCommand.model_validate(body)
        self.assertNotIn("answer", json.dumps(ControlCommand(commandId="owned-cancel", action="cancel").decision()))

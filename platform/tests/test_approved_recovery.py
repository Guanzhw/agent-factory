"""Offline repair boundaries using the real native queue continuation seam."""
import asyncio
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agno.agent import Agent
from fastapi import HTTPException
from pydantic import ValidationError

from agent_factory.auth import EXECUTOR_ID
from agent_factory.control_commands import ControlCommand, ControlCommands
from agent_factory.factory_api import requirement_version
from agent_factory.native_bridge import NativeBridge
from agent_factory.store import digest


def fixture():
    task = {"id": "task-1", "owner_id": "owner-1", "plan_id": "plan-1", "run_id": "run-1", "cancel_requested": False}
    requirement = {"id": "requirement-1", "tool_execution": {"tool_call_id": "tool-1", "tool_name": "orx_experiment_run",
        "tool_args": {}, "requires_confirmation": True, "confirmed": None, "result": None}}
    approved = copy.deepcopy(requirement)
    approved["confirmation"] = True
    approved["tool_execution"]["confirmed"] = True
    binding = {"kind": "native", "ownerId": task["owner_id"], "taskId": task["id"], "planId": task["plan_id"], "runId": task["run_id"]}
    decision = {"requirementId": requirement["id"], "version": requirement_version(requirement), "approved": True}
    original = {"owner_id": task["owner_id"], "task_ref": task["id"], "command_id": "approval-original", "action": "approve", "state": "DISPATCHING",
        "fingerprint": digest({"taskId": task["id"], "action": "approve", "decision": decision, "binding": binding}),
        "body": {"binding": binding, "decision": decision, "requirements": [approved], "toolsSha256": digest([approved["tool_execution"]])}}
    proof = {"commandId": original["command_id"], "fingerprint": original["fingerprint"]}
    ticket = {"id": task["run_id"], "session_id": task["id"], "user_id": task["owner_id"], "component_id": EXECUTOR_ID,
        "component_type": "agent", "status": "paused", "job_type": "run",
        "payload": {"continue": {"updated_tools": [approved["tool_execution"]], "kwargs": {"metadata": {"factoryControlCommand": proof}}}}}
    snapshot = {"status": "PAUSED", "run_id": task["run_id"], "requirements": [requirement], "queue": ticket}
    return task, original, snapshot


class ApprovedRecoveryProofTests(unittest.TestCase):
    def test_command_schema_requires_exact_original_reference(self):
        body = {"commandId": "repair-123", "action": "resume_approved", "approvalCommandId": "approval-123", "requirementId": "r", "version": 1}
        self.assertEqual(ControlCommand(**body).decision()["approvalCommandId"], "approval-123")
        for changes in ({"approved": True}, {"answer": "x"}, {"approvalCommandId": None}, {"commandId": "approval-123"},
                        {"action": "approve", "approved": True}, {"action": "cancel"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ControlCommand(**{**body, **changes})

    def test_exact_original_approval_accepted_without_mutating_transcript(self):
        task, original, snapshot = fixture()
        before = copy.deepcopy(snapshot)
        value = ControlCommands._approval_payload(task, snapshot, original)
        self.assertEqual(value["requirements"], original["body"]["requirements"])
        self.assertEqual(snapshot, before)
        self.assertEqual(value["pausedRequirementsSha256"], digest(snapshot["requirements"]))

    def test_missing_changed_foreign_or_nonpaused_proofs_rejected(self):
        mutations = [lambda o, s: s["queue"].update(status="running"), lambda o, s: s.update(status="RUNNING"),
            lambda o, s: s["queue"].update(user_id="foreign"), lambda o, s: s["queue"].update(component_type="team"),
            lambda o, s: s["queue"]["payload"].clear(), lambda o, s: o["body"]["decision"].update(approved=False),
            lambda o, s: o.update(state="PREPARED"), lambda o, s: o["body"]["binding"].update(planId="foreign"),
            lambda o, s: s["requirements"][0]["tool_execution"].update(tool_call_id="different"),
            lambda o, s: o["body"]["requirements"][0]["tool_execution"].update(tool_args={"altered": True})]
        for mutate in mutations:
            task, original, snapshot = fixture()
            mutate(original, snapshot)
            with self.assertRaises(HTTPException):
                ControlCommands._approval_payload(task, snapshot, original)

    def test_repair_slot_distinct_from_approval_and_unique_per_original(self):
        self.assertEqual(ControlCommands.repair_slot("t", "a"), ControlCommands.repair_slot("t", "a"))
        self.assertNotEqual(ControlCommands.repair_slot("t", "a"), ControlCommands.repair_slot("t", "b"))
        self.assertNotEqual(ControlCommands.repair_slot("t", "a"), digest({"task": "t", "requirement": "r", "version": 1}))

    def test_existing_repair_blocks_new_id_but_prepared_same_id_can_revalidate(self):
        async def exercise():
            task, original, snapshot = fixture()
            store = SimpleNamespace(sql=Mock(return_value=[{"command_id": "repair-original"}]))
            api = SimpleNamespace(store=store, auth=SimpleNamespace(require=Mock()), bridge=None)
            commands = ControlCommands(api)
            commands.row = Mock(return_value=original)
            commands._completed_launch = Mock(return_value={"orxRunId": "orx-1"})
            with self.assertRaises(HTTPException):
                await commands.approved_recovery(task, snapshot)
            commands._completed_launch.assert_not_called()
            prepared = await commands.approved_recovery(task, snapshot, repair_id="repair-original")
            self.assertEqual(prepared["recoveryDetail"]["approvalCommandId"], original["command_id"])
            commands._completed_launch.assert_called_once()
        asyncio.run(exercise())

    def test_unknown_dispatch_is_read_only_recovery(self):
        async def exercise():
            api = SimpleNamespace(store=None, auth=SimpleNamespace(require=Mock()), bridge=SimpleNamespace(continue_approved_run=AsyncMock()))
            commands = ControlCommands(api)
            commands.row = Mock(return_value={"state": "DISPATCHING"})
            commands.recover = AsyncMock(return_value={"state": "UNKNOWN"})
            result = await commands.dispatch("owner", "task", "repair-command")
            self.assertEqual(result["state"], "UNKNOWN")
            api.bridge.continue_approved_run.assert_not_awaited()
            commands.recover.assert_awaited_once()
        asyncio.run(exercise())


class ApprovedRecoveryQueueTests(unittest.TestCase):
    def setup_bridge(self):
        task, original, snapshot = fixture()
        class QueueStore:
            def __init__(self):
                self.job = copy.deepcopy(snapshot["queue"])
                self.calls = 0
            async def get_job(self, run_id):
                return copy.deepcopy(self.job)
            async def continue_job(self, run_id, payload):
                self.calls += 1
                self.job["payload"]["continue"] = payload
                self.job["status"] = "queued"
                return {"outcome": "queued", "job": copy.deepcopy(self.job)}
        queue_store = QueueStore()
        component = Agent(id=EXECUTOR_ID, telemetry=False)
        worker = SimpleNamespace(store=queue_store, resolve_component=lambda *_: component)
        bridge = NativeBridge(None, None, SimpleNamespace(require=Mock()))
        bridge.attach(SimpleNamespace(state=SimpleNamespace(queue_worker=worker)))
        bridge.detail = AsyncMock(return_value=snapshot)
        bridge._request = AsyncMock(side_effect=AssertionError("Detached HTTP fallback is forbidden"))
        prepared = ControlCommands._approval_payload(task, snapshot, original)
        arguments = (task["run_id"], task["id"], task["owner_id"], prepared["requirements"])
        kwargs = {"command_proof": {"commandId": "repair-original", "fingerprint": "repair-fingerprint"},
                  "original_proof": prepared["originalApprovalProof"], "tools_sha256": prepared["toolsSha256"],
                  "paused_requirements_sha256": prepared["pausedRequirementsSha256"]}
        return bridge, queue_store, arguments, kwargs

    def test_real_public_queue_seam_preserves_run_and_installs_exact_repair_proof(self):
        async def exercise():
            bridge, store, args, kwargs = self.setup_bridge()
            result = await bridge.continue_approved_run(*args, **kwargs)
            self.assertEqual(result["run_id"], "run-1")
            self.assertEqual(store.calls, 1)
            self.assertEqual(store.job["payload"]["continue"]["kwargs"]["metadata"]["factoryControlCommand"], kwargs["command_proof"])
            assert isinstance(bridge._request, AsyncMock)
            bridge._request.assert_not_awaited()
        asyncio.run(exercise())

    def test_none_conflict_settling_and_foreign_attach_never_fallback(self):
        async def exercise():
            for outcome in (None, {"outcome": "conflict"}, {"outcome": "settling"}, {"outcome": "attach", "job": {}}):
                bridge, store, args, kwargs = self.setup_bridge()
                with patch("agno.os.job_queue.acontinue_via_queue", AsyncMock(return_value=outcome)):
                    with self.assertRaises(HTTPException):
                        await bridge.continue_approved_run(*args, **kwargs)
                self.assertEqual(store.calls, 0)
                assert isinstance(bridge._request, AsyncMock)
                bridge._request.assert_not_awaited()
        asyncio.run(exercise())

    def test_raced_foreign_queued_proof_not_attached(self):
        async def exercise():
            bridge, store, args, kwargs = self.setup_bridge()
            store.job["status"] = "queued"
            with self.assertRaises(HTTPException):
                await bridge.continue_approved_run(*args, **kwargs)
            self.assertEqual(store.calls, 0)
        asyncio.run(exercise())

    def test_exact_raced_attach_does_not_dispatch_twice(self):
        async def exercise():
            bridge, store, args, kwargs = self.setup_bridge()
            store.job["status"] = "queued"
            store.job["payload"]["continue"]["kwargs"]["metadata"]["factoryControlCommand"] = kwargs["command_proof"]
            result = await bridge.continue_approved_run(*args, **kwargs)
            self.assertEqual(result["run_id"], "run-1")
            self.assertEqual(store.calls, 0)
        asyncio.run(exercise())

class ApprovedRecoveryEffectTests(unittest.TestCase):
    def completed_fixture(self):
        from contextlib import ExitStack
        from agent_factory.orx_experiment_tools import LAUNCH_EFFECT_KEY
        task, _, _ = fixture()
        result = {"taskId": task["id"], "planId": task["plan_id"], "nativeRunId": task["run_id"],
                  "orxRunId": "orx-1", "effectFingerprint": "original-effect", "status": "done", "stopEvidence": {"allStopped": True}}
        effect = {"effect_key": task["run_id"] + ":" + LAUNCH_EFFECT_KEY, "status": "DONE", "result": copy.deepcopy(result)}
        adapter = SimpleNamespace(observe_existing=Mock(return_value={}))
        binding = SimpleNamespace(contract_revision="2", adapter=adapter)
        store = SimpleNamespace(task=Mock(return_value=task), effects=Mock(return_value=[effect]),
                                execution_bindings=SimpleNamespace(recheck=Mock()))
        commands = ControlCommands(SimpleNamespace(store=store, auth=None, bridge=None, settings=None))
        ctx = SimpleNamespace(user_id=task["owner_id"], session_id=task["id"], run_id=task["run_id"], session_state={})
        stack = ExitStack()
        current = stack.enter_context(patch("agent_factory.inference_wait.current", return_value=({}, ctx)))
        stack.enter_context(patch("agent_factory.inference_wait.read", return_value=None))
        stack.enter_context(patch("agent_factory.inference_wait.execution_owner", return_value={}))
        stack.enter_context(patch("agent_factory.orx_experiment_tools.original_experiment_binding", return_value=(task, {}, ctx, binding)))
        stack.enter_context(patch("agent_factory.orx_experiment_tools._public_result", return_value=result))
        stack.enter_context(patch("agent_factory.orx_experiment_tools._request", return_value={}))
        stack.enter_context(patch("agent_factory.orx_experiment_tools.inspect_orx_experiment", return_value=copy.deepcopy(result)))
        return stack, commands, task, effect, result, adapter, current

    def test_completed_observation_checks_authority_twice_without_launch_handle(self):
        stack, commands, task, effect, result, adapter, current = self.completed_fixture()
        with stack:
            proof = commands._completed_launch(task)
        self.assertEqual(proof["orxRunId"], "orx-1")
        self.assertEqual(current.call_count, 2)
        adapter.observe_existing.assert_called_once()

    def test_unknown_effect_or_nonpositive_stop_cannot_repair(self):
        for mutation in ("unknown", "stop", "identity", "canceled"):
            stack, commands, task, effect, result, adapter, current = self.completed_fixture()
            with stack:
                if mutation == "unknown":
                    effect["status"] = "UNKNOWN"
                elif mutation == "stop":
                    result["stopEvidence"] = {"allStopped": False}
                elif mutation == "identity":
                    result["orxRunId"] = "foreign-run"
                else:
                    result["status"] = "cancelled"
                with self.assertRaises(HTTPException):
                    commands._completed_launch(task)
            if mutation == "unknown":
                adapter.observe_existing.assert_not_called()

    def test_current_denial_and_source_drift_fail_closed(self):
        for source in (False, True):
            stack, commands, task, effect, result, adapter, current = self.completed_fixture()
            with stack:
                if source:
                    adapter.observe_existing.side_effect = PermissionError("source drift")
                else:
                    current.side_effect = PermissionError("revoked or over budget")
                with self.assertRaises(PermissionError):
                    commands._completed_launch(task)
            if not source:
                adapter.observe_existing.assert_not_called()

class ApprovedRecoveryReceiptTests(unittest.TestCase):
    def receipt_fixture(self):
        task, row, snapshot = fixture()
        row.update(action="resume_approved", command_id="repair-original", fingerprint="repair-fingerprint", updated_at="synthetic-time")
        row["body"]["createdAt"] = "synthetic-time"
        row["body"]["decision"] = {"approvalCommandId": "approval-original", "requirementId": "requirement-1", "version": 1}
        ticket = snapshot["queue"]
        bridge = SimpleNamespace(continue_approved_run=AsyncMock())
        store = SimpleNamespace(native_db=SimpleNamespace(get_job=Mock(side_effect=lambda *_args, **_kwargs: copy.deepcopy(ticket))))
        api = SimpleNamespace(store=store, auth=SimpleNamespace(require=Mock()), bridge=bridge, remote=None,
                              scoped_task=Mock(return_value=(task, None)))
        commands = ControlCommands(api)
        commands.row = Mock(return_value=row)
        def update(_row, *, evidence=None, error=None):
            row["body"]["error"] = error
            if evidence is not None:
                row["body"]["evidence"] = evidence
        commands._update = Mock(side_effect=update)
        return commands, row, ticket, bridge

    def test_confirmed_repair_refreshes_status_after_later_payload_replacement(self):
        async def exercise():
            commands, row, ticket, bridge = self.receipt_fixture()
            ticket["status"] = "queued"
            ticket["payload"]["continue"]["kwargs"]["metadata"]["factoryControlCommand"] = {
                "commandId": row["command_id"], "fingerprint": row["fingerprint"]}
            first = await commands.recover("owner-1", "task-1", "repair-original")
            self.assertEqual(first["state"], "EXECUTION_CONTINUING")
            ticket["payload"]["continue"] = {"updated_tools": [], "kwargs": {"metadata": {
                "factoryControlCommand": {"commandId": "later-command", "fingerprint": "later-fingerprint"}}}}
            for status in ("paused", "completed", "cancelled"):
                ticket["status"] = status
                receipt = await commands.recover("owner-1", "task-1", "repair-original")
                self.assertTrue(receipt["decisionRecorded"])
                self.assertFalse(receipt["executionContinuing"])
                self.assertEqual(receipt["evidence"]["nativeStatus"], status)
            bridge.continue_approved_run.assert_not_awaited()
        asyncio.run(exercise())

    def test_unproven_repair_does_not_inherit_another_command_ack(self):
        async def exercise():
            commands, row, ticket, bridge = self.receipt_fixture()
            ticket["status"] = "completed"
            receipt = await commands.recover("owner-1", "task-1", "repair-original")
            self.assertEqual(receipt["state"], "UNKNOWN")
            self.assertFalse(receipt["decisionRecorded"])
            assert isinstance(commands._update, Mock)
            commands._update.assert_not_called()
            bridge.continue_approved_run.assert_not_awaited()
        asyncio.run(exercise())

    def test_foreign_ticket_does_not_keep_stale_execution_continuing(self):
        async def exercise():
            commands, row, ticket, bridge = self.receipt_fixture()
            row["body"]["evidence"] = {"kind": "native-continuation", "runId": "run-1", "decisionRecorded": True,
                "toolsSha256": row["body"]["toolsSha256"], "executionContinuing": True}
            ticket["session_id"] = "another-task"
            receipt = await commands.recover("owner-1", "task-1", "repair-original")
            self.assertTrue(receipt["decisionRecorded"])
            self.assertFalse(receipt["executionContinuing"])
            self.assertIsNotNone(receipt["error"])
            bridge.continue_approved_run.assert_not_awaited()
        asyncio.run(exercise())

"""Durable user decisions, not another execution queue.

Only PREPARED intents may cross the dispatch boundary. Every recovery path reads
native/receiver evidence; an absent acknowledgement never authorizes replay.
"""
from __future__ import annotations

import copy
import asyncio
import sys
import re
from typing import Any, Literal
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from .auth import EXECUTOR_ID
from .store import canonical, digest, now

COMMAND_ID = r"^[a-zA-Z0-9_.:-]{8,100}$"


class ControlCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commandId: str = Field(pattern=COMMAND_ID)
    action: Literal["answer", "approve", "cancel", "resume_approved"]
    approvalCommandId: str | None = Field(default=None, pattern=COMMAND_ID)
    requirementId: str | None = Field(default=None, min_length=1, max_length=200)
    version: StrictInt | None = Field(default=None, ge=0)
    answer: str | None = Field(default=None, min_length=1, max_length=2000)
    approved: StrictBool | None = None

    @model_validator(mode="after")
    def exact_decision(self):
        if self.action == "resume_approved":
            valid = (self.approvalCommandId is not None and self.requirementId is not None and self.version is not None
                     and self.answer is None and self.approved is None and self.commandId != self.approvalCommandId)
        elif self.action == "cancel":
            valid = all(value is None for value in (self.requirementId, self.version, self.answer, self.approved, self.approvalCommandId))
        else:
            valid = self.requirementId is not None and self.version is not None and self.approvalCommandId is None
            valid = valid and (self.answer is not None and self.approved is None if self.action == "answer" else self.answer is None and self.approved is not None)
        if not valid:
            raise ValueError("Command must contain exactly its selected decision")
        return self

    def decision(self):
        return self.model_dump(exclude={"commandId", "action"}, exclude_none=True)


class ControlCommands:
    def __init__(self, api):
        self.api, self.store, self.auth, self.bridge = api, api.store, api.auth, api.bridge

    def row(self, owner, task_id, command_id):
        rows = self.store.sql("SELECT * FROM af_control_commands WHERE owner_id=:owner AND command_id=:id", owner=owner, id=command_id)
        if not rows or rows[0]["task_ref"] != task_id:
            raise HTTPException(404, "COMMAND_NOT_FOUND: command is outside this owner/task")
        return rows[0]

    def _binding(self, task, child=None, upstream=None):
        binding = {"ownerId": task["owner_id"], "taskId": task["id"], "planId": task["plan_id"], "runId": task.get("run_id")}
        if self.api.remote and self.api.remote.placed(task):
            placement = self.api.remote.client._row(task["owner_id"], task["id"])
            binding.update(kind="remote", remoteChildId=child, placementId=placement["task_id"],
                           targetRef=placement["target_ref"], configurationSha256=placement["configuration_hash"],
                           manifestSha256=placement["manifest_hash"])
        else:
            binding["kind"] = "native"
        if upstream is not None:
            binding["upstream"] = copy.deepcopy(upstream)
        return binding

    @staticmethod
    def _same_binding(row, current):
        original = row["body"]["binding"]
        if row["action"] == "cancel" and original["kind"] == "native" and original.get("runId") is None:
            # A pre-admission cancel pins the immutable task. Its first native
            # receipt may arrive later; this never authorizes a different task.
            current = {**current, "runId": None}
        return original == current

    @staticmethod
    def repair_slot(task_id, approval_id):
        return digest({"task": task_id, "approvedRecovery": approval_id})

    @staticmethod
    def _approval_payload(task, snapshot, original):
        """Exact original approval + parked native transcript, never guessed approval."""
        from .factory_api import native_requirements, requirement_version
        binding = original["body"]["binding"]
        decision = original["body"]["decision"]
        ticket = snapshot.get("queue") or {}
        run = snapshot.get("run", snapshot)
        continuation = (ticket.get("payload") or {}).get("continue") or {}
        proof = continuation.get("kwargs", {}).get("metadata", {}).get("factoryControlCommand")
        expected = {"commandId": original["command_id"], "fingerprint": original["fingerprint"]}
        if (original["action"] != "approve" or original["state"] != "DISPATCHING"
                or decision.get("approved") is not True or original["task_ref"] != task["id"]
                or original["owner_id"] != task["owner_id"] or binding.get("kind") != "native"
                or any(binding.get(key) != task.get(column) for key, column in
                       (("taskId", "id"), ("planId", "plan_id"), ("runId", "run_id"), ("ownerId", "owner_id")))
                or ticket.get("status") != "paused" or str(run.get("status")).lower() not in {"paused", "runstatus.paused"}
                or ticket.get("id") != task["run_id"] or ticket.get("session_id") != task["id"]
                or ticket.get("user_id") != task["owner_id"] or ticket.get("component_id") != EXECUTOR_ID
                or ticket.get("component_type") != "agent" or ticket.get("job_type", "run") != "run"
                or proof != expected or digest(continuation.get("updated_tools")) != original["body"].get("toolsSha256")
                or original["fingerprint"] != digest({"taskId": original["task_ref"], "action": "approve",
                    "decision": decision, "binding": binding})):
            raise HTTPException(409, "APPROVED_RECOVERY_PROOF: original parked approval proof is unavailable")
        requirements = copy.deepcopy(native_requirements(snapshot))
        requirement = next((item for item in requirements if item.get("id") == decision.get("requirementId")), None)
        if requirement is None or requirement_version(requirement) != decision.get("version"):
            raise HTTPException(409, "APPROVED_RECOVERY_STALE: original requirement differs")
        tool = requirement.get("tool_execution") or {}
        if (tool.get("tool_name") != "orx_experiment_run" or not tool.get("tool_call_id")
                or tool.get("requires_confirmation") is not True or tool.get("confirmed") is not None
                or tool.get("result") is not None):
            raise HTTPException(409, "APPROVED_RECOVERY_SCOPE: only the original unexecuted launch confirmation qualifies")
        paused_hash = digest(requirements)
        requirement["confirmation"] = True
        tool["confirmed"] = True
        if (requirements != original["body"].get("requirements")
                or digest([item.get("tool_execution", item) for item in requirements]) != original["body"].get("toolsSha256")):
            raise HTTPException(409, "APPROVED_RECOVERY_TOOLS: original approved tool identities differ")
        return {"requirements": requirements, "toolsSha256": original["body"]["toolsSha256"],
                "pausedRequirementsSha256": paused_hash, "originalApprovalProof": expected}

    def _completed_launch(self, task):
        """Current authority + read-only terminal ORX proof; never ensure/wake."""
        from .inference_wait import current, read, execution_owner
        from .orx_experiment_tools import (LAUNCH_EFFECT_KEY, _public_result, _request,
            original_experiment_binding, inspect_orx_experiment)
        if sys.platform != "linux":
            raise HTTPException(409, "APPROVED_RECOVERY_PLATFORM: Linux revision 2 is required")
        task = self.store.task(task["id"], task["owner_id"])
        wait = read(self.store, task["id"])
        if wait and wait["state"] == "STOPPING":
            raise HTTPException(409, "APPROVED_RECOVERY_STOPPING: stop intent cannot be resumed")
        plan, context = current(self.store, task, wait if wait and wait["state"] in {"WAITING", "RESUMING"} else None)
        from agno.run import RunContext
        ctx = RunContext(user_id=context.user_id, session_id=context.session_id, run_id=context.run_id, session_state=context.session_state)
        execution_owner(self.store, task)
        self.store.execution_bindings.recheck(plan, ctx)
        effects = [item for item in self.store.effects(task["id"])
                   if item["effect_key"] == task["run_id"] + ":" + LAUNCH_EFFECT_KEY]
        original = original_experiment_binding(self.api.settings, self.store, task["id"])
        if len(effects) != 1 or effects[0]["status"] != "DONE" or original is None or original[3].contract_revision != "2":
            raise HTTPException(409, "APPROVED_RECOVERY_EFFECT: original Linux v2 effect must be DONE")
        binding = original[3]
        receipt = binding.adapter.observe_existing()
        result = _public_result(plan, ctx, binding, receipt, digest(_request(plan, ctx, binding)))
        saved = effects[0]["result"]
        projection = inspect_orx_experiment(self.store, task["owner_id"], task["id"])
        keys = ("taskId", "planId", "nativeRunId", "orxRunId", "effectFingerprint", "status")
        if (not isinstance(saved, dict) or not isinstance(projection, dict)
                or result.get("status") not in {"done", "failed"} or not result.get("orxRunId")
                or result.get("stopEvidence", {}).get("allStopped") is not True
                or saved.get("stopEvidence", {}).get("allStopped") is not True
                or any(result.get(key) != saved.get(key) or result.get(key) != projection.get(key) for key in keys)):
            raise HTTPException(409, "APPROVED_RECOVERY_STOP: exact terminal experiment and positive stop proof required")
        current(self.store, self.store.task(task["id"], task["owner_id"]),
                wait if wait and wait["state"] in {"WAITING", "RESUMING", "STOPPING"} else None)
        self.store.execution_bindings.recheck(plan, ctx)
        return {key: result[key] for key in keys}

    async def approved_recovery(self, task, snapshot, *, approval_id=None, repair_id=None):
        self.auth.require(task["owner_id"], "run")
        if task["cancel_requested"] or not task.get("run_id"):
            raise HTTPException(409, "APPROVED_RECOVERY_CANCELED: original task is unavailable")
        ticket = snapshot.get("queue") or {}
        proof = ((ticket.get("payload") or {}).get("continue") or {}).get("kwargs", {}).get("metadata", {}).get("factoryControlCommand") or {}
        selected = approval_id or proof.get("commandId")
        if not isinstance(selected, str):
            raise HTTPException(409, "APPROVED_RECOVERY_MISSING: no original approval")
        original = self.row(task["owner_id"], task["id"], selected)
        prepared = self._approval_payload(task, snapshot, original)
        existing = self.store.sql("SELECT command_id FROM af_control_commands WHERE owner_id=:owner AND requirement_slot=:slot",
            owner=task["owner_id"], slot=self.repair_slot(task["id"], selected))
        if existing and (len(existing) != 1 or existing[0]["command_id"] != repair_id):
            raise HTTPException(409, "APPROVED_RECOVERY_ALREADY_RECORDED: reconcile the original repair receipt")
        try:
            prepared["completedLaunch"] = await asyncio.to_thread(self._completed_launch, task)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(409, "APPROVED_RECOVERY_CURRENT: current source, authority or stop evidence is unavailable") from None
        decision = original["body"]["decision"]
        prepared["recoveryDetail"] = {"approvalCommandId": selected, "requirementId": decision["requirementId"],
            "version": decision["version"], "runId": task["run_id"],
            "scope": "恢复已记录审批；仅复用已完成且停止的原实验，不新建运行"}
        return prepared

    async def _prepare(self, task, child, action, decision, *, repair_id=None):
        if action == "resume_approved":
            if self.api.remote and self.api.remote.placed(task):
                detail = await self.api.detail(task, child)
                recovery = detail["job"].get("recoveryDetail") or {}
                if ("resume_approved" not in detail["job"].get("allowedActions", [])
                        or any(recovery.get(key) != decision.get(key) for key in ("approvalCommandId", "requirementId", "version"))):
                    raise HTTPException(409, "APPROVED_RECOVERY_REMOTE: receiver recovery is unavailable")
                original = self.row(task["owner_id"], detail["job"]["id"], decision["approvalCommandId"])
                if (original["action"] != "approve" or original["state"] != "DISPATCHING"
                        or original["body"]["decision"].get("approved") is not True
                        or not self._same_binding(original, self._binding(task, child, original["body"]["binding"].get("upstream")))
                        or not self.public(original)["decisionRecorded"]):
                    raise HTTPException(409, "APPROVED_RECOVERY_REMOTE: original approved origin command is required")
                return {"toolsSha256": digest(recovery), "recoveryDetail": recovery}
            snapshot = await self.bridge.detail(task["run_id"], task["id"], task["owner_id"])
            prepared = await self.approved_recovery(task, snapshot, approval_id=decision["approvalCommandId"], repair_id=repair_id)
            if any(prepared["recoveryDetail"][key] != decision[key] for key in ("requirementId", "version")):
                raise HTTPException(409, "APPROVED_RECOVERY_STALE: original decision differs")
            return prepared
        if action == "cancel":
            if self.api.remote and self.api.remote.placed(task) and child is None:
                placement = self.api.remote.client._row(task["owner_id"], task["id"])
                return {"remotePreparation": not (placement["body"].get("receipt") or {}).get("remoteTaskId")}
            if self.api.delegation and not (self.api.remote and self.api.remote.placed(task)):
                group = await self.api.delegation.inspect_group(task["owner_id"], task["id"])
                return {"alreadyStopped": group["allStopped"]}
            return {}
        from .factory_api import native_requirements, requirement_version
        if not (self.api.remote and self.api.remote.placed(task)):
            context = SimpleNamespace(session_id=task["id"], run_id=task.get("run_id"), user_id=task["owner_id"],
                session_state={"factory_envelope": {"plan_ref": task["plan_id"], "task_id": task["id"],
                    "user_id": task["owner_id"], "request_id": task["request_id"]}})
            self.store.require_plan_execution(task["owner_id"], self.store.plan(task["plan_id"], task["owner_id"]), run_context=context)
        detail = await self.api.detail(task, child)
        expected = "waiting_input" if action == "answer" else "waiting_approval"
        if detail["job"]["status"] != expected or task["cancel_requested"]:
            raise HTTPException(409, "Task is no longer waiting for this action")
        requirements = copy.deepcopy(native_requirements(detail["snapshot"]))
        requirement = next((r for r in requirements if r.get("id") == decision["requirementId"]), None)
        if requirement is None or requirement_version(requirement) != decision["version"]:
            raise HTTPException(409, "STALE_REQUIREMENT: refresh the task before deciding")
        tool = requirement["tool_execution"]
        if action == "answer":
            if not tool.get("requires_user_input") or tool.get("answered"):
                raise HTTPException(409, "This requirement is not an unanswered question")
            fields = requirement.get("user_input_schema") or tool.get("user_input_schema") or []
            unanswered = [field for field in fields if field.get("value") is None]
            if len(unanswered) != 1 or unanswered[0].get("name") != "scope":
                raise HTTPException(409, "Unsupported question schema")
            unanswered[0]["value"] = decision["answer"]
            requirement["user_input_schema"] = fields
            tool.update(user_input_schema=fields, answered=True)
        else:
            from .autoresearch_session_control import TOOL as SESSION_TOOL
            if tool.get("tool_name") == SESSION_TOOL:
                receipt = await self.store.autoresearch_session_control.completion(task, requirement)
                tool["result"] = canonical({**receipt, "accepted": decision["approved"]})
                return {"requirements": requirements, "toolsSha256": digest([r.get("tool_execution", r) for r in requirements])}
            from .research_runtime import TOOL as RESEARCH_TOOL
            if tool.get("tool_name") == RESEARCH_TOOL:
                receipt = await self.store.research_runtime.completion(task, requirement)
                tool["result"] = canonical({**receipt, "accepted": decision["approved"]})
                return {"requirements": requirements, "toolsSha256": digest([r.get("tool_execution", r) for r in requirements])}
            from .inference_wait import CONTROL_NAME, validate_requirement
            if tool.get("tool_name") == CONTROL_NAME:
                await asyncio.to_thread(validate_requirement, self.store, task, tool)
                tool["result"] = canonical({"factoryControl": "resume-same-run" if decision["approved"] else "declined"})
                return {"requirements": requirements, "toolsSha256": digest([r.get("tool_execution", r) for r in requirements]),
                    "inferenceRecovery": True, "inferenceControlId": tool["tool_call_id"], "inferenceDeclined": not decision["approved"]}
            if not tool.get("requires_confirmation") or tool.get("confirmed") is not None:
                raise HTTPException(409, "This requirement is not an undecided approval")
            requirement["confirmation"] = decision["approved"]
            tool["confirmed"] = decision["approved"]
        return {"requirements": requirements, "toolsSha256": digest([r.get("tool_execution", r) for r in requirements])}

    async def submit(self, owner: str, task_id: str, command: ControlCommand, *, upstream=None):
        self.auth.require(owner, "run")
        task, child = self.api.scoped_task(task_id, owner)
        binding = self._binding(task, child, upstream)
        decision = command.decision()
        fingerprint = digest({"taskId": task_id, "action": command.action, "decision": decision, "binding": binding})
        existing = self.store.sql("SELECT * FROM af_control_commands WHERE owner_id=:owner AND command_id=:id", owner=owner, id=command.commandId)
        if existing:
            row = existing[0]
            if (row["task_ref"] != task_id or row["action"] != command.action
                    or row["body"]["decision"] != decision or not self._same_binding(row, binding)):
                raise HTTPException(409, "COMMAND_CONFLICT: original command target or decision differs")
            return await self.dispatch(owner, task_id, command.commandId)
        try:
            prepared = await self._prepare(task, child, command.action, decision)
        except HTTPException:
            # Another copy of this exact command may have committed while this
            # request was observing the requirement. Return its original proof.
            raced = self.store.sql("SELECT * FROM af_control_commands WHERE owner_id=:owner AND command_id=:id", owner=owner, id=command.commandId)
            if raced and raced[0]["task_ref"] == task_id and raced[0]["fingerprint"] == fingerprint:
                return await self.dispatch(owner, task_id, command.commandId)
            raise
        # One semantic requirement may have only one command, even if two tabs
        # minted different IDs or chose opposite decisions concurrently.
        slot = (self.repair_slot(task_id, decision["approvalCommandId"]) if command.action == "resume_approved" else
            digest({"task": task_id, "requirement": decision.get("requirementId"), "version": decision.get("version")}) if command.action != "cancel" else None)
        body = {"binding": binding, "decision": decision, **prepared, "createdAt": now()}
        with self.store.transaction():
            inserted = self.store.sql("""INSERT INTO af_control_commands
                (owner_id,command_id,task_ref,root_task_id,action,fingerprint,requirement_slot,state,body,updated_at)
                VALUES(:owner,:id,:task,:root,:action,:fingerprint,:slot,'PREPARED',CAST(:body AS JSONB),:at)
                ON CONFLICT DO NOTHING RETURNING command_id""", owner=owner, id=command.commandId, task=task_id,
                root=task["id"], action=command.action, fingerprint=fingerprint, slot=slot, body=canonical(body), at=now())
            if inserted:
                self.store.event(task["id"], "control_intent_recorded", "Owner-scoped control intent durably recorded",
                    {"commandId": command.commandId, "action": command.action, "taskRef": task_id, "fingerprint": fingerprint})
        if not inserted:
            rows = self.store.sql("SELECT * FROM af_control_commands WHERE owner_id=:owner AND command_id=:id", owner=owner, id=command.commandId)
            if not rows or rows[0]["task_ref"] != task_id or rows[0]["fingerprint"] != fingerprint:
                raise HTTPException(409, "COMMAND_CONFLICT: this requirement or command already has another decision")
        return await self.dispatch(owner, task_id, command.commandId)

    def _update(self, row, *, evidence=None, error=None):
        patch: dict[str, Any] = {"error": error}
        if evidence is not None:
            patch["evidence"] = evidence
        with self.store.transaction():
            saved = self.store.sql("SELECT body FROM af_control_commands WHERE owner_id=:owner AND command_id=:id FOR UPDATE",
                                   owner=row["owner_id"], id=row["command_id"])[0]["body"]
            self.store.sql("""UPDATE af_control_commands SET body=body || CAST(:patch AS JSONB),updated_at=:at
                WHERE owner_id=:owner AND command_id=:id""", patch=canonical(patch), at=now(),
                owner=row["owner_id"], id=row["command_id"])
            if evidence is not None and not saved.get("evidence") and (evidence.get("decisionRecorded") or evidence.get("receipt", {}).get("decisionRecorded")):
                kind = {"answer": "question_answered", "approve": "approval_decided", "cancel": "control_cancel_recorded", "resume_approved": "approved_recovery_recorded"}[row["action"]]
                self.store.event(row["root_task_id"], kind, "Exact control decision confirmed by authoritative evidence",
                    {"commandId": row["command_id"], "taskRef": row["task_ref"], "fingerprint": row["fingerprint"],
                     "requirementId": saved["decision"].get("requirementId"), "version": saved["decision"].get("version"),
                     "approved": saved["decision"].get("approved"), "evidenceKind": evidence["kind"]})

    async def dispatch(self, owner, task_id, command_id):
        self.auth.require(owner, "run")
        row = self.row(owner, task_id, command_id)
        if row["state"] != "PREPARED":
            return await self.recover(owner, task_id, command_id)
        task, child = self.api.scoped_task(task_id, owner)
        if not self._same_binding(row, self._binding(task, child, row["body"]["binding"].get("upstream"))):
            raise HTTPException(409, "COMMAND_BINDING_CHANGED: original execution target differs")
        # Revalidate before the one durable dispatch CAS. A prepared intent is
        # not a permission grant, even after a service/browser restart.
        try:
            prepared = await self._prepare(task, child, row["action"], row["body"]["decision"], repair_id=command_id)
            if row["action"] == "resume_approved" and row["body"]["binding"]["kind"] == "native":
                if any(prepared.get(key) != row["body"].get(key) for key in
                       ("originalApprovalProof", "pausedRequirementsSha256", "completedLaunch")):
                    raise HTTPException(409, "APPROVED_RECOVERY_CHANGED: original repair identity/effect differs")
            if row["action"] != "cancel" and prepared["toolsSha256"] != row["body"]["toolsSha256"]:
                raise HTTPException(409, "STALE_REQUIREMENT: original decision target differs")
        except HTTPException as error:
            rejected = self.store.sql("""UPDATE af_control_commands SET state='REJECTED',
                body=body || CAST(:patch AS JSONB),updated_at=:at
                WHERE owner_id=:owner AND command_id=:id AND state='PREPARED' RETURNING command_id""",
                patch=canonical({"error": {"code": error.status_code, "reason": "Current requirement or authority rejected dispatch"}}),
                at=now(), owner=owner, id=command_id)
            if not rejected:
                return await self.recover(owner, task_id, command_id)
            raise
        with self.store.transaction():
            claimed = self.store.sql("""UPDATE af_control_commands SET state='DISPATCHING',updated_at=:at
                WHERE owner_id=:owner AND command_id=:id AND state='PREPARED' RETURNING command_id""",
                at=now(), owner=owner, id=command_id)
            if claimed:
                self.store.event(task["id"], "control_dispatch_boundary", "Control dispatch boundary recorded; recovery cannot replay",
                    {"commandId": command_id, "fingerprint": row["fingerprint"], "taskRef": task_id})
                if row["action"] == "cancel" and child is None and not prepared.get("alreadyStopped"):
                    self.store.request_cancel(task["id"])
                if prepared.get("inferenceRecovery"):
                    updated = self.store.sql("""UPDATE af_inference_waits SET state=:state
                        WHERE task_id=:task AND state='WAITING' AND body->>'controlId'=:control
                        AND CAST(body->>'deadline' AS TIMESTAMPTZ)>CURRENT_TIMESTAMP RETURNING task_id""",
                        task=task["id"], control=prepared["inferenceControlId"],
                        state="STOPPING" if prepared["inferenceDeclined"] else "RESUMING")
                    if not updated:
                        raise HTTPException(409, "INFERENCE_WAIT_CHANGED: original wait ended before dispatch")
                    if prepared["inferenceDeclined"]:
                        self.store.request_cancel(task["id"])
        if not claimed:
            return await self.recover(owner, task_id, command_id)
        try:
            if prepared.get("inferenceDeclined"):
                await self.api.delegation.cascade_cancel(owner, task["id"])
                self._update(row, evidence={"kind": "inference-declined", "decisionRecorded": True})
            elif row["body"]["binding"]["kind"] == "remote" and row["body"].get("remotePreparation"):
                # A preparation can be canceled before a receiver task exists.
                # The existing handoff CAS supplies positive no-dispatch proof;
                # this command still owns one durable origin dispatch boundary.
                await self.api.remote.client.cancel(owner, task["id"])
            elif row["body"]["binding"]["kind"] == "remote":
                result = await self.api.remote.client.control_command(owner, task["id"],
                    {"commandId": command_id, "action": row["action"], **row["body"]["decision"], "sourceFingerprint": row["fingerprint"]}, child)
                self._accept_remote(row, result)
            elif row["action"] == "cancel" and prepared.get("alreadyStopped"):
                self._update(row, evidence={"kind": "already-stopped", "decisionRecorded": True, "stopConfirmed": True})
            elif row["action"] == "cancel":
                upstream = row["body"]["binding"].get("upstream")
                if upstream and self.store.handoff_receiver:
                    await self.store.handoff_receiver.cancel(owner, upstream["handoffId"], task["id"])
                elif self.api.delegation:
                    await self.api.delegation.cascade_cancel(owner, task["id"])
                elif task.get("run_id"):
                    await self.bridge.cancel_run(task["run_id"], task["id"], owner)
            elif row["action"] == "resume_approved":
                await self.bridge.continue_approved_run(task["run_id"], task["id"], owner, row["body"]["requirements"],
                    command_proof={"commandId": command_id, "fingerprint": row["fingerprint"]},
                    original_proof=row["body"]["originalApprovalProof"], tools_sha256=row["body"]["toolsSha256"],
                    paused_requirements_sha256=row["body"]["pausedRequirementsSha256"])
            else:
                await self.bridge.continue_run(task["run_id"], task["id"], owner, row["body"]["requirements"],
                    command_proof={"commandId": command_id, "fingerprint": row["fingerprint"]})
        except Exception as error:
            # A returned error, connection loss or process exit cannot prove no
            # native acceptance. Keep the original boundary and read evidence.
            self._update(row, error={"reason": "Dispatch acknowledgement unavailable", "type": type(error).__name__})
        return await self.recover(owner, task_id, command_id)

    def _accept_remote(self, row, result):
        binding = row["body"]["binding"]
        upstream = result.get("binding", {}).get("upstream", {}) if isinstance(result, dict) else {}
        if (not isinstance(result, dict) or result.get("commandId") != row["command_id"]
                or result.get("action") != row["action"] or upstream.get("sourceFingerprint") != row["fingerprint"]
                or upstream.get("originTaskId") != binding["taskId"]
                or upstream.get("manifestSha256") != binding["manifestSha256"]
                or binding.get("remoteChildId") is not None and result.get("taskId") != binding["remoteChildId"]):
            raise HTTPException(409, "COMMAND_REMOTE_PROOF: receiver command belongs to a different intent")
        if result.get("decisionRecorded") or result.get("state") == "REJECTED":
            self._update(row, evidence={"kind": "receiver-command", "receipt": result})

    async def recover(self, owner, task_id, command_id):
        self.auth.require(owner, "read")
        task, child = self.api.scoped_task(task_id, owner)
        row = self.row(owner, task_id, command_id)
        if row["state"] in {"PREPARED", "REJECTED"}:
            return self.public(row)
        try:
            binding = self._binding(task, child, row["body"]["binding"].get("upstream"))
            if not self._same_binding(row, binding):
                raise HTTPException(409, "Original command binding changed")
            if binding["kind"] == "remote" and row["body"].get("remotePreparation"):
                receipt = await self.api.remote.client.receipt(owner, task["id"])
                if task["cancel_requested"]:
                    self._update(row, evidence={"kind": "receiver-handoff-cancel", "handoffId": receipt["id"],
                        "manifestSha256": binding["manifestSha256"], "decisionRecorded": True,
                        "stopConfirmed": receipt.get("allStopped") is True, "receiverState": receipt["state"]})
            elif binding["kind"] == "remote":
                result = await self.api.remote.client.control_receipt(owner, task["id"], command_id, child)
                self._accept_remote(row, result)
            elif row["action"] == "cancel":
                evidence = row["body"].get("evidence", {})
                # This flag was committed with THIS command's dispatch CAS;
                # no missing native response is interpreted as positive stop.
                if task["cancel_requested"] or evidence.get("kind") == "already-stopped":
                    group = await self.api.delegation.inspect_group(owner, task["id"]) if self.api.delegation else None
                    evidence = {"kind": "persisted-cancel-intent" if task["cancel_requested"] else "already-stopped", "decisionRecorded": True,
                        "stopConfirmed": bool(group and group["allStopped"]), "runId": task.get("run_id")}
                    self._update(row, evidence=evidence)
            elif task.get("run_id"):
                ticket = self.store.native_db.get_job(task["run_id"], strict=True)
                continuation = (ticket or {}).get("payload", {}).get("continue", {})
                proof = continuation.get("kwargs", {}).get("metadata", {}).get("factoryControlCommand")
                scoped = bool(ticket and ticket.get("id") == binding["runId"] and ticket.get("session_id") == task["id"]
                              and ticket.get("user_id") == owner and ticket.get("component_id") == EXECUTOR_ID)
                exact = (proof == {"commandId": command_id, "fingerprint": row["fingerprint"]}
                         and digest(continuation.get("updated_tools")) == row["body"]["toolsSha256"])
                previous = row["body"].get("evidence", {})
                # Immutable decision proof survives later requirements replacing
                # the native continuation payload. Execution status is observed
                # afresh and never attributed to the earlier decision itself.
                historical = previous.get("kind") == "native-continuation"
                if row["action"] == "resume_approved":
                    # Initial repair ACK still requires its exact native payload.
                    # Once recorded, later legitimate continuations may replace
                    # that payload; retain the decision, refresh this run's status.
                    historical = (historical and previous.get("decisionRecorded") is True
                        and previous.get("runId") == binding["runId"]
                        and previous.get("toolsSha256") == row["body"]["toolsSha256"])
                    if not scoped or ticket.get("component_type") != "agent":
                        raise HTTPException(409, "APPROVED_RECOVERY_RECEIPT_SCOPE: original native ticket is unavailable")
                if scoped and (exact or historical):
                    assert ticket is not None
                    self._update(row, evidence={"kind": "native-continuation", "runId": task["run_id"],
                        "nativeStatus": ticket["status"], "toolsSha256": row["body"]["toolsSha256"], "decisionRecorded": True,
                        "executionContinuing": ticket["status"] in {"queued", "running"}})
        except Exception as error:
            self._update(row, error={"reason": "Read-only command reconciliation unavailable", "type": type(error).__name__})
        return self.public(self.row(owner, task_id, command_id))

    def public(self, row):
        body = row["body"]
        proof = body.get("evidence", {})
        remote = proof.get("receipt", {}) if proof.get("kind") == "receiver-command" else proof
        recorded = remote.get("decisionRecorded") is True
        continuing = remote.get("executionContinuing") is True and not body.get("error")
        stopped = remote.get("stopConfirmed") is True
        state = "INTENT_RECORDED" if row["state"] == "PREPARED" else "REJECTED" if row["state"] == "REJECTED" or remote.get("state") == "REJECTED" else "UNKNOWN"
        if recorded:
            state = "STOP_CONFIRMED" if stopped else "EXECUTION_CONTINUING" if continuing else "DECISION_RECORDED"
        return {"commandId": row["command_id"], "ownerId": row["owner_id"], "taskId": row["task_ref"],
            "action": row["action"], "fingerprint": row["fingerprint"], "binding": body["binding"],
            "decisionSha256": digest({"action": row["action"], **body["decision"]}),
            "requirementId": body["decision"].get("requirementId"), "version": body["decision"].get("version"),
            "approved": body["decision"].get("approved"), "approvalCommandId": body["decision"].get("approvalCommandId"), "state": state, "intentRecorded": True,
            "decisionRecorded": recorded, "executionContinuing": continuing, "stopConfirmed": stopped,
            "canDispatch": row["state"] == "PREPARED", "acknowledged": body.get("acknowledged") is True, "createdAt": body["createdAt"], "updatedAt": row["updated_at"],
            "evidence": {key: value for key, value in proof.items() if key != "receipt"}, "error": body.get("error")}

    async def acknowledge(self, owner, task_id, command_id):
        receipt = await self.recover(owner, task_id, command_id)
        if receipt["state"] != "REJECTED" and (not receipt["decisionRecorded"]
                or receipt["action"] == "cancel" and not receipt["stopConfirmed"]):
            raise HTTPException(409, "COMMAND_UNRESOLVED: retain the original command for recovery")
        self.store.sql("UPDATE af_control_commands SET body=body || CAST(:patch AS JSONB) WHERE owner_id=:owner AND command_id=:id",
                       patch=canonical({"acknowledged": True}), owner=owner, id=command_id)
        return self.public(self.row(owner, task_id, command_id))

    async def list(self, owner, task_id=None, *, limit=50, after=None, outstanding=True):
        self.auth.require(owner, "read")
        if task_id is not None:
            self.api.scoped_task(task_id, owner)
        rows = self.store.sql("""SELECT * FROM af_control_commands WHERE owner_id=:owner
            AND (CAST(:task AS TEXT) IS NULL OR task_ref=:task) AND (CAST(:after AS TEXT) IS NULL OR command_id>:after)
            AND (NOT :outstanding OR body->>'acknowledged' IS DISTINCT FROM 'true')
            ORDER BY command_id LIMIT :limit""", owner=owner, task=task_id, after=after, limit=limit + 1, outstanding=outstanding)
        items = [await self.recover(owner, row["task_ref"], row["command_id"]) for row in rows[:limit]]
        return {"items": items, "nextCursor": rows[limit - 1]["command_id"] if len(rows) > limit else None}


def legacy_command(task_id, action, decision, command_id=None):
    # Compatibility clients still enter the same durable protocol. Identical
    # old requests derive one semantic ID; new clients persist an explicit ID.
    command_id = command_id or "legacy-" + digest({"taskId": task_id, "action": action, "decision": decision})
    if not re.fullmatch(COMMAND_ID, command_id):
        raise HTTPException(422, "Invalid command ID")
    return ControlCommand(commandId=command_id, action=action, **decision)

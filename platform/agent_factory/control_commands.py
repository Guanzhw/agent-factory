"""Durable user decisions, not another execution queue.

Only PREPARED intents may cross the dispatch boundary. Every recovery path reads
native/receiver evidence; an absent acknowledgement never authorizes replay.
"""
from __future__ import annotations

import copy
from typing import Any, Literal
from types import SimpleNamespace

from agno.exceptions import RunCancelledException
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from .auth import EXECUTOR_ID
from .store import canonical, digest, now

COMMAND_ID = r"^[a-zA-Z0-9_.:-]{8,100}$"


class ControlCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commandId: str = Field(pattern=COMMAND_ID)
    action: Literal["approve", "cancel"]
    requirementId: str | None = None
    version: StrictInt | None = Field(default=None, ge=0)
    approved: StrictBool | None = None

    @model_validator(mode="after")
    def exact_decision(self):
        if self.action == "cancel":
            valid = self.requirementId is None and self.version is None and self.approved is None
        else:
            valid = bool(self.requirementId) and self.version is not None and self.approved is True
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

    def _binding(self, task):
        return {"ownerId": task["owner_id"], "taskId": task["id"], "planId": task["plan_id"],
                "runId": task.get("run_id"), "kind": "native"}

    @staticmethod
    def _same_binding(row, current):
        original = row["body"]["binding"]
        if row["action"] == "cancel" and original["kind"] == "native" and original.get("runId") is None:
            # A pre-admission cancel pins the immutable task. Its first native
            # receipt may arrive later; this never authorizes a different task.
            current = {**current, "runId": None}
        return original == current

    async def _prepare(self, task, action, decision):
        if action == "cancel":
            group = await self.api.delegation.inspect_group(task["owner_id"], task["id"])
            return {"alreadyStopped": group["allStopped"]}
        from .factory_api import native_requirements, requirement_version
        context = SimpleNamespace(session_id=task["id"], run_id=task.get("run_id"), user_id=task["owner_id"],
            session_state={"factory_envelope": {"plan_ref": task["plan_id"], "task_id": task["id"],
                "user_id": task["owner_id"], "request_id": task["request_id"]}})
        try:
            self.store.require_plan_execution(task["owner_id"], self.store.plan(task["plan_id"], task["owner_id"]), run_context=context)
        except RunCancelledException as error:
            raise HTTPException(409, "Task is no longer waiting for this action") from error
        snapshot = await self.bridge.detail(task["run_id"], task["id"], task["owner_id"])
        if task["cancel_requested"]:
            raise HTTPException(409, "Task is no longer waiting for this action")
        requirements = copy.deepcopy(native_requirements(snapshot))
        requirement = next((r for r in requirements if r.get("id") == decision["requirementId"]), None)
        if requirement is None or requirement_version(requirement) != decision["version"]:
            raise HTTPException(409, "STALE_REQUIREMENT: original requirement differs")
        result = await self.store.research_sessions.external_result(self, task, requirement, requirements, decision)
        if result is None:
            raise HTTPException(409, "Unsupported continuation requirement")
        return result

    async def submit(self, owner: str, task_id: str, command: ControlCommand):
        self.auth.require_member(owner)
        task, _ = self.api.scoped_task(task_id, owner)
        binding = self._binding(task)
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
            prepared = await self._prepare(task, command.action, decision)
        except HTTPException:
            # Another copy of this exact command may have committed while this
            # request was observing the requirement. Return its original proof.
            raced = self.store.sql("SELECT * FROM af_control_commands WHERE owner_id=:owner AND command_id=:id", owner=owner, id=command.commandId)
            if raced and raced[0]["task_ref"] == task_id and raced[0]["fingerprint"] == fingerprint:
                return await self.dispatch(owner, task_id, command.commandId)
            raise
        # One semantic requirement may have only one command, even if two tabs
        # minted different IDs or chose opposite decisions concurrently.
        slot = (digest({"task": task_id, "requirement": decision.get("requirementId"),
                        "version": decision.get("version")}) if command.action != "cancel" else None)
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
                kind = {"approve": "approval_decided", "cancel": "control_cancel_recorded"}[row["action"]]
                self.store.event(row["root_task_id"], kind, "Exact control decision confirmed by authoritative evidence",
                    {"commandId": row["command_id"], "taskRef": row["task_ref"], "fingerprint": row["fingerprint"],
                     "requirementId": saved["decision"].get("requirementId"), "version": saved["decision"].get("version"),
                     "approved": saved["decision"].get("approved"), "evidenceKind": evidence["kind"]})

    async def dispatch(self, owner, task_id, command_id):
        self.auth.require_member(owner)
        row = self.row(owner, task_id, command_id)
        if row["state"] != "PREPARED":
            return await self.recover(owner, task_id, command_id)
        task, _ = self.api.scoped_task(task_id, owner)
        if not self._same_binding(row, self._binding(task)):
            raise HTTPException(409, "COMMAND_BINDING_CHANGED: original execution target differs")
        # Revalidate before the one durable dispatch CAS. A prepared intent is
        # not a permission grant, even after a service/browser restart.
        try:
            prepared = await self._prepare(task, row["action"], row["body"]["decision"])
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
                if row["action"] == "cancel" and not prepared.get("alreadyStopped"):
                    self.store.request_cancel(task["id"])
        if not claimed:
            return await self.recover(owner, task_id, command_id)
        try:
            if row["action"] == "cancel" and prepared.get("alreadyStopped"):
                self._update(row, evidence={"kind": "already-stopped", "decisionRecorded": True, "stopConfirmed": True})
            elif row["action"] == "cancel":
                await self.api.delegation.cascade_cancel(owner, task["id"])
            else:
                await self.bridge.continue_run(task["run_id"], task["id"], owner, row["body"]["requirements"],
                    command_proof={"commandId": command_id, "fingerprint": row["fingerprint"]})
        except Exception as error:
            # A returned error, connection loss or process exit cannot prove no
            # native acceptance. Keep the original boundary and read evidence.
            self._update(row, error={"reason": "Dispatch acknowledgement unavailable", "type": type(error).__name__})
        return await self.recover(owner, task_id, command_id)

    async def recover(self, owner, task_id, command_id):
        self.auth.require_member(owner)
        task, _ = self.api.scoped_task(task_id, owner)
        row = self.row(owner, task_id, command_id)
        if row["state"] in {"PREPARED", "REJECTED"}:
            return self.public(row)
        try:
            binding = self._binding(task)
            if not self._same_binding(row, binding):
                raise HTTPException(409, "Original command binding changed")
            if row["action"] == "cancel":
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
        recorded = proof.get("decisionRecorded") is True
        continuing = proof.get("executionContinuing") is True and not body.get("error")
        stopped = proof.get("stopConfirmed") is True
        state = "INTENT_RECORDED" if row["state"] == "PREPARED" else "REJECTED" if row["state"] == "REJECTED" or proof.get("state") == "REJECTED" else "UNKNOWN"
        if recorded:
            state = "STOP_CONFIRMED" if stopped else "EXECUTION_CONTINUING" if continuing else "DECISION_RECORDED"
        return {"commandId": row["command_id"], "ownerId": row["owner_id"], "taskId": row["task_ref"],
            "action": row["action"], "fingerprint": row["fingerprint"], "binding": body["binding"],
            "decisionSha256": digest({"action": row["action"], **body["decision"]}),
            "requirementId": body["decision"].get("requirementId"), "version": body["decision"].get("version"),
            "approved": body["decision"].get("approved"), "state": state, "intentRecorded": True,
            "decisionRecorded": recorded, "executionContinuing": continuing, "stopConfirmed": stopped,
            "canDispatch": row["state"] == "PREPARED", "createdAt": body["createdAt"], "updatedAt": row["updated_at"],
            "evidence": {key: value for key, value in proof.items() if key != "receipt"}, "error": body.get("error")}

"""Research-only compatibility for existing recorded native decisions."""
import sys
import asyncio
from .services import services_for
from fastapi import HTTPException
from agent_factory.auth import EXECUTOR_ID
from agent_factory.control_commands import ControlCommands
from agent_factory.store import canonical, digest
import copy


class ResearchControlCommands(ControlCommands):
    @staticmethod
    def _approval_payload(task, snapshot, original):
        """Exact original approval + parked native transcript, never guessed approval."""
        from agent_factory.factory_api import native_requirements, requirement_version
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

    async def _external_result(self, task, requirement, requirements, decision):
        tool = requirement.get("tool_execution") or {}
        from .autoresearch_session_control import TOOL as SESSION_TOOL
        if tool.get("tool_name") == SESSION_TOOL:
            receipt = await services_for(self.store).autoresearch_session_control.completion(task, requirement)
            tool["result"] = canonical({**receipt, "accepted": decision["approved"]})
            return {"requirements": requirements, "toolsSha256": digest([r.get("tool_execution", r) for r in requirements])}
        from .research_runtime import TOOL as RESEARCH_TOOL
        if tool.get("tool_name") == RESEARCH_TOOL:
            receipt = await services_for(self.store).research_runtime.completion(task, requirement)
            tool["result"] = canonical({**receipt, "accepted": decision["approved"]})
            return {"requirements": requirements, "toolsSha256": digest([r.get("tool_execution", r) for r in requirements])}
        from .inference_wait import CONTROL_NAME, validate_requirement
        if tool.get("tool_name") == CONTROL_NAME:
            await asyncio.to_thread(validate_requirement, self.store, task, tool)
            tool["result"] = canonical({"factoryControl": "resume-same-run" if decision["approved"] else "declined"})
            return {"requirements": requirements, "toolsSha256": digest([r.get("tool_execution", r) for r in requirements]),
                "inferenceRecovery": True, "inferenceControlId": tool["tool_call_id"], "inferenceDeclined": not decision["approved"]}
        return await super()._external_result(task, requirement, requirements, decision)

    def _claim_external_result(self, task, prepared):
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

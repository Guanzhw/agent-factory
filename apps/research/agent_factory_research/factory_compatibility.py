"""Legacy research response projection over the unchanged Factory task API."""
from agent_factory.factory_api import FactoryAPI, native_requirements, requirement_version
from .control_compatibility import ResearchControlCommands
from .research_runtime_hooks import ResearchRuntimeHooks


class ResearchFactoryAPI(FactoryAPI):
    command_type = ResearchControlCommands

    def _waiting_control(self, task, snapshot):
        from .inference_wait import CONTROL_NAME, read as read_wait
        inference_wait = read_wait(self.store, task["id"])
        inference_requirement = next((r for r in native_requirements(snapshot)
            if (r.get("tool_execution") or {}).get("tool_name") == CONTROL_NAME
            and (r.get("tool_execution") or {}).get("external_execution_required") is True), None)
        waiting_inference = bool(inference_wait and inference_wait["state"] == "WAITING" and inference_requirement
                and not task["cancel_requested"] and not self.store.has_failures(task["id"])
                and (snapshot.get("queue") or {}).get("status") == "paused")
        return inference_wait, waiting_inference

    async def _project_detail(self, task, plan, snapshot, events, job, control_wait):
        from .inference_wait import CONTROL_NAME
        job["definition"]["runtimePolicy"].update(ResearchRuntimeHooks.policy_projection(plan))
        inference_wait = control_wait
        status, actions = job["status"], job["allowedActions"]
        for requirement in native_requirements(snapshot):
            tool = requirement.get("tool_execution") or {}
            version = requirement_version(requirement)
            if (tool.get("tool_name") == CONTROL_NAME and tool.get("external_execution_required")
                    and inference_wait and tool.get("tool_call_id") == inference_wait["controlId"]):
                scope = ("推理服务暂时不可用。已有实验仍按原批准边界运行；本次仅恢复同一推理 run，"
                    "不会重新启动实验、增加预算或延长截止时间。截止：" + inference_wait["deadline"])
                job.update(approvalDetail={"id": requirement["id"], "version": version, "scope": scope,
                    "toolName": CONTROL_NAME, "arguments": {}}, approval={"scope": scope})
                if status == "waiting_approval":
                    actions.append("approve")
            else:
                await ResearchRuntimeHooks.requirement(self.store, task, requirement, version, status, job, actions)
        await ResearchRuntimeHooks.recovery(self.commands, task, snapshot, native_requirements(snapshot), job, actions)
        actions[:] = dict.fromkeys(actions)
        evidence, evaluation = ResearchRuntimeHooks.project(self.settings, self.store, task, plan, events, job)
        return {**evidence, "inferenceWait": inference_wait}, evaluation

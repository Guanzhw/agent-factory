"""Legacy research response projection over the unchanged Factory task API."""
from functools import partial
from agent_factory.factory_api import FactoryAPI, native_requirements, requirement_version
from .control_compatibility import ResearchControlCommands
from .research_runtime_hooks import ResearchRuntimeHooks


class ResearchTaskProjection:
    """Research-owned projection, called only after original binding dispatch."""

    @staticmethod
    def waiting_control(api, task, snapshot):
        from .inference_wait import CONTROL_NAME, read as read_wait
        inference_wait = read_wait(api.store, task["id"])
        inference_requirement = next((r for r in native_requirements(snapshot)
            if (r.get("tool_execution") or {}).get("tool_name") == CONTROL_NAME
            and (r.get("tool_execution") or {}).get("external_execution_required") is True), None)
        waiting_inference = bool(inference_wait and inference_wait["state"] == "WAITING" and inference_requirement
                and not task["cancel_requested"] and not api.store.has_failures(task["id"])
                and (snapshot.get("queue") or {}).get("status") == "paused")
        return inference_wait, waiting_inference

    @staticmethod
    async def project_detail(api, task, plan, snapshot, events, job, control_wait, *, research):
        research.require_store(api.store, ready=True)
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
                await ResearchRuntimeHooks.requirement(api.store, task, requirement, version, status, job, actions, research=research)
        await ResearchRuntimeHooks.recovery(api.commands, task, snapshot, native_requirements(snapshot), job, actions)
        actions[:] = dict.fromkeys(actions)
        evidence, evaluation = ResearchRuntimeHooks.project(api.settings, api.store, task, plan, events, job, research=research)
        return {**evidence, "inferenceWait": inference_wait}, evaluation


class ResearchFactoryAPI(FactoryAPI):
    """Legacy standalone entry; production uses registered application hooks."""
    def __init__(self, settings, store, auth, bridge, *, research):
        research.require_store(store)
        self.research = research
        self.command_type = partial(ResearchControlCommands, research=research)
        super().__init__(settings, store, auth, bridge)

    def _waiting_control(self, task, snapshot):
        return ResearchTaskProjection.waiting_control(self, task, snapshot)

    async def _project_detail(self, task, plan, snapshot, events, job, control_wait):
        return await ResearchTaskProjection.project_detail(self, task, plan, snapshot, events, job, control_wait, research=self.research)

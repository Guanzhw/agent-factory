import asyncio
import hashlib
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from .control_commands import ControlCommand, ControlCommands, legacy_command, COMMAND_ID
from .catalog import create_plan
from .delegation import application_group_status
from .remote_handoff import FactoryPublicRoute
from .store import effect_unresolved, canonical


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Body):
    persona: Literal["manager", "alice", "bob"]


class PlanRequest(Body):
    topic: str = Field(min_length=2, max_length=2000)
    mode: str = Field(default="literature", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    application: str = Field(default="research", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    applicationRef: dict | None = None
    materialChoices: dict = Field(default_factory=dict, max_length=30)
    connectionRefs: dict = Field(default_factory=dict, max_length=30)
    inputValues: dict | None = None
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")


class InstanceRequest(Body):
    planId: str = Field(max_length=100)
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")
    executionTargetRef: str | None = Field(default=None, min_length=1, max_length=100)


class ChildRequest(Body):
    goal: str = Field(min_length=2, max_length=2000)
    mode: str = Field(default="literature", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")


class MaterialRequest(Body):
    requestId: str | None = Field(default=None, min_length=1, max_length=200)
    id: str | None = Field(default=None, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")
    kind: Literal["skill", "tool", "prompt", "knowledge", "model", "environment"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=2000)
    content: str = Field(max_length=16000)
    dependencies: list[dict] = Field(default_factory=list, max_length=30)
    permissions: list[str] = Field(default_factory=list, max_length=30)


class PublicationRequest(Body):
    requestId: str = Field(min_length=1, max_length=200)


class Cancel(Body):
    commandId: str | None = Field(default=None, pattern=COMMAND_ID)


class Answer(Cancel):
    questionId: str
    version: int
    answer: str = Field(min_length=1, max_length=2000)


class Approval(Cancel):
    requirementId: str
    version: int
    approved: bool


def requirement_version(requirement):
    # A native requirement ID plus canonical contents form a stable stale-action token.
    return int(hashlib.sha256(canonical(requirement).encode()).hexdigest()[:12], 16)


def native_requirements(snapshot):
    run = snapshot.get("run", snapshot)
    return run.get("requirements") or []


def status_of(task, snapshot, effects, events):
    if task["admission"] == "rejected":
        return "failed"
    if task["admission"] in {"unknown", "reserved"} and not task.get("run_id"):
        return "unknown"
    queue = snapshot.get("queue") or snapshot.get("job") or {}
    run = snapshot.get("run", snapshot)
    raw = str(queue.get("status") or run.get("status") or "queued").lower()
    if any(effect_unresolved(effect) for effect in effects) and raw not in {"running", "runstatus.running"}:
        return "unknown"
    if task["cancel_requested"] and raw not in {"cancelled", "canceled", "failed", "completed", "error"}:
        return "canceling"
    if raw in {"paused", "runstatus.paused"}:
        requirements = native_requirements(snapshot)
        if any((r.get("tool_execution") or {}).get("requires_user_input") for r in requirements):
            return "waiting_input"
        return "waiting_approval"
    if raw in {"cancelled", "canceled", "runstatus.cancelled"}:
        return "canceled"
    if raw in {"failed", "error", "runstatus.error"}:
        return "failed"
    if raw in {"completed", "runstatus.completed"}:
        # A model's completed response is not evidence that a protected tool succeeded.
        if task.get("protected_failed") or any(event["type"] in {"tool_failed", "protected_denied", "experiment_failed"} for event in events):
            return "failed"
        return "completed"
    return "running" if raw in {"running", "runstatus.running"} else "queued"


class FactoryAPI:
    def __init__(self, settings, store, auth, bridge):
        self.settings, self.store, self.auth, self.bridge = settings, store, auth, bridge
        self.delegation = getattr(store, "delegation", None)
        self.remote = getattr(store, "remote_execution", None)
        self.commands = ControlCommands(self)
        self.router = APIRouter(prefix="/api/factory", route_class=FactoryPublicRoute)
        self.routes()

    def user(self, request, action="run"):
        user = self.auth.user(request)
        self.auth.require(user["id"], "components:write" if action == "write" else action)
        return user

    def scoped_task(self, identifier, owner):
        return self.remote.resolve(identifier, owner) if self.remote else (self.store.task(identifier, owner), None)

    async def detail(self, task, remote_child=None):
        if self.remote and self.remote.placed(task):
            return await self.remote.detail(task, remote_child)
        snapshot = {}
        if task.get("run_id"):
            snapshot = await self.bridge.detail(task["run_id"], task["id"], task["owner_id"])
        task = self.store.task(task["id"], task["owner_id"])
        effects = self.store.effects(task["id"])
        events = self.store.events(task["id"])
        status = status_of({**task, "protected_failed": self.store.has_failures(task["id"])}, snapshot, effects, events)
        from .inference_wait import CONTROL_NAME, read as read_wait
        inference_wait = read_wait(self.store, task["id"])
        inference_requirement = next((r for r in native_requirements(snapshot)
            if (r.get("tool_execution") or {}).get("tool_name") == CONTROL_NAME
            and (r.get("tool_execution") or {}).get("external_execution_required") is True), None)
        waiting_inference = bool(inference_wait and inference_wait["state"] == "WAITING" and inference_requirement
                and not task["cancel_requested"] and not self.store.has_failures(task["id"])
                and (snapshot.get("queue") or {}).get("status") == "paused")
        if waiting_inference:
            status = "waiting_approval"
        group = None
        if self.delegation:
            group = await self.delegation.inspect_group(task["owner_id"], task["id"])
            if status in {"failed", "canceled"} and not group["allStopped"]:
                try:
                    self.auth.require(task["owner_id"], "run")
                except HTTPException as error:
                    if error.status_code != 403:
                        raise
                else:
                    group = (await self.delegation.cascade_cancel(task["owner_id"], task["id"]))["group"]
                    task = self.store.task(task["id"], task["owner_id"])
            # Native/group reads can await a concurrent trusted cleanup. Its
            # cancellation flag and failure provenance commit together; never
            # overwrite that cause using the caller's pre-await task snapshot.
            task = self.store.task(task["id"], task["owner_id"])
            status = application_group_status(status, group)
            if task["cancel_requested"] and not group["allStopped"]:
                status = "unknown" if group["unknown"] else "canceling"
            elif task["cancel_requested"] and group["allStopped"]:
                status = "failed" if self.store.failure_cleanup_requested(task["id"]) else "canceled"
            elif waiting_inference and not self.store.has_failures(task["id"]):
                status = "waiting_approval"
        self.store.observed(task, status, status in {"completed", "failed", "canceled"} and (group is None or group["allStopped"]))
        plan = self.store.plan(task["plan_id"], task["owner_id"])
        application_ref = plan.get("applicationRef", {"id": plan["application"], "version": 1})
        model_binding = (plan.get("executionBindings") or {}).get("model", {})
        selected_model = next((event["data"] for event in reversed(events) if event["type"] == "model_binding_selected"), {})
        definition = {"id": application_ref["id"], "version": application_ref["version"], "name": plan["application"],
            "description": "Governed immutable application over native Agno", "instructions": "\n".join(plan["instructions"]),
            "skills": [], "tools": plan["tools"], "knowledge": [], "materialRefs": plan["materialRefs"],
            "modelPolicy": {"providerId": selected_model.get("provider", "factory-registered"), "modelId": selected_model.get("modelId", "pending-selection"),
                "adapterId": model_binding.get("adapterId"), "revision": model_binding.get("revision"), "maxSteps": plan["budget"]["toolCalls"]},
            "runtimePolicy": {"timeoutSeconds": 60, "allowExperiment": bool({"run_experiment", "orx_experiment_run"} & set(plan["tools"]))}, "published": False, "createdAt": plan["createdAt"]}
        delegation_scope = await asyncio.to_thread(self.delegation.delegation_scope, task["owner_id"], task["id"]) if self.delegation else None
        actions = ["inspect"]
        if delegation_scope and delegation_scope["allowed"]:
            actions.append("delegate")
        if status in {"queued", "running", "waiting_input", "waiting_approval", "unknown", "canceling", "waiting_children"}:
            actions.append("cancel")
        if status == "unknown":
            actions.append("reconcile")
        job = {"id": task["id"], "ownerId": task["owner_id"], "planId": plan["id"], "definitionId": definition["id"], "definitionVersion": definition["version"],
            "definition": definition, "binding": plan.get("bindingManifest", {}), "input": {"topic": plan["normalizedGoal"], "mode": plan["mode"], "scenario": "normal"},
            "status": status, "createdAt": task["body"]["createdAt"], "updatedAt": task["body"]["updatedAt"],
            "runtime": "demo" if self.settings.demo else "live", "attempt": (snapshot.get("queue") or {}).get("attempt", 0),
            "allowedActions": actions, "validationStatus": "执行链路已验证；研究数据为合成示例" if self.settings.demo else "注册适配器执行记录；研究结论需按产物证据验证",
            "evidenceKind": "合成示例" if self.settings.demo else "按产物来源分别验证"}
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
            elif tool.get('tool_name') == 'workflow_wait' and tool.get('external_execution_required'):
                scope = '等待原工作流阶段或人工决定；请使用工作流面板核对与继续。'
                job.update(approvalDetail={'id': requirement['id'], 'version': version, 'scope': scope,
                    'toolName': 'workflow_wait', 'arguments': tool.get('tool_args', {})}, approval={'scope': scope})
            elif tool.get("tool_name") == "autoresearch_session_run" and tool.get("external_execution_required"):
                control = getattr(self.store, "autoresearch_session_control", None)
                if control is not None and status == "waiting_approval":
                    try:
                        await control.completion(task, requirement)
                    except (ValueError, HTTPException):
                        pass
                    else:
                        scope = "原 ORX 会话和受管子任务已结束；继续同一原生运行，接收原始结果。"
                        job.update(approvalDetail={"id": requirement["id"], "version": version,
                            "scope": scope, "toolName": "autoresearch_session_run", "arguments": {}}, approval={"scope": scope})
                        actions.append("approve")
            elif tool.get("tool_name") == "research_process_run" and tool.get("external_execution_required"):
                runtime = getattr(self.store, "research_runtime", None)
                original = runtime._original(task["id"]) if runtime is not None else None
                if original is not None and runtime is not None:
                    lease = runtime.resources.inspect(task["owner_id"], original["lease_id"])
                    job["researchExecution"] = {"leaseId": lease["id"], "state": lease["state"],
                        "capacityHeld": lease["capacityHeld"], "gpuExecutionVerified": False,
                        "scientificConclusionVerified": False}
                    if (status == "waiting_approval" and lease["state"] == "RECLAIMED"
                            and lease.get("executionStatus") == "COMPLETED" and lease.get("exitCode") == 0
                            and lease.get("gpuEvidence", {}).get("state") == "RELEASED"):
                        scope = "原研究进程已停止并释放租约；继续同一运行，仅接收执行凭据，不代表科研评分已验证。"
                        job.update(approvalDetail={"id": requirement["id"], "version": version,
                            "scope": scope, "toolName": "research_process_run", "arguments": {}}, approval={"scope": scope})
                        actions.append("approve")
            elif tool.get("requires_user_input") and not tool.get("answered"):
                question = {"id": requirement["id"], "version": version, "text": "请补充这次研究的具体问题或范围。", "fields": requirement.get("user_input_schema") or tool.get("user_input_schema") or []}
                job.update(questionDetail=question, question=question["text"])
                if status == "waiting_input":
                    actions.append("answer")
            elif tool.get("requires_confirmation") and tool.get("confirmed") is None:
                approval = {"id": requirement["id"], "version": version, "scope": f"运行本任务的固定本地合成实验：最长 {self.settings.experiment_timeout_seconds} 秒，输出最多 {self.settings.experiment_output_bytes // 1024} KB；不调用付费模型。", "toolName": tool.get("tool_name"), "arguments": tool.get("tool_args", {})}
                job.update(approvalDetail=approval, approval={"scope": approval["scope"], "requestedAt": requirement.get("created_at", plan["createdAt"])})
                if status == "waiting_approval":
                    actions.append("approve")
        if (str((snapshot.get("run", snapshot)).get("status")).lower() in {"paused", "runstatus.paused"}
                and (snapshot.get("queue") or {}).get("status") == "paused"
                and any((r.get("tool_execution") or {}).get("tool_name") == "orx_experiment_run"
                        for r in native_requirements(snapshot))):
            try:
                recovery = await self.commands.approved_recovery(task, snapshot)
            except Exception:
                # Eligibility is advisory; absent/unverifiable original proof
                # cannot grant a repair or erase the existing paused receipt.
                pass
            else:
                job["recoveryDetail"] = recovery["recoveryDetail"]
                actions[:] = [action for action in actions if action != "approve"]
                actions.append("resume_approved")
        if delegation_scope and delegation_scope.get("executionUnavailable"):
            job["allowedActions"] = [action for action in actions if action in {"inspect", "cancel", "reconcile"}]
        try:
            self.auth.require(task["owner_id"], "run")
        except HTTPException as error:
            if error.status_code != 403:
                raise
            job["allowedActions"] = ["inspect"]
        evaluation = next((event["data"] for event in reversed(events) if event["type"] == "experiment_completed"), None)
        from .orx_experiment_tools import inspect_orx_experiment
        experiment = inspect_orx_experiment(self.store, task["owner_id"], task["id"])
        from .literature_evidence import APPLICATION_TOOLS, inspect_literature_evidence
        literature = (inspect_literature_evidence(self.store, task["owner_id"], task["id"])
                      if plan.get("application") in APPLICATION_TOOLS else None)
        from .synthesis_runtime import inspect_synthesis_evidence
        synthesis = inspect_synthesis_evidence(self.store, task["owner_id"], task["id"])
        comparison = self.store.comparisons.inspect(task["owner_id"], task["id"]) if self.store.comparisons is not None else None
        ledger = getattr(self.store, "usage_ledger", None)
        usage = ledger.inspect(task["owner_id"], task["id"]) if ledger is not None else None
        if synthesis is not None:
            job.update(validationStatus="受控综合；引用结构检查不等于科研结论验证", evidenceKind="controlled_model_synthesis")
        if comparison is not None:
            job.update(validationStatus="合成开发数据的受控比较；未验证科学结论", evidenceKind="controlled_comparison")
        if literature is not None:
            labels = {"ready": "书目与摘录已保存；不代表科研结论", "no-sources": "执行已结束，但未取得文献来源",
                      "pending": "等待文献证据产物", "invalid": "文献证据未通过完整性核对"}
            job.update(validationStatus=labels[literature["status"]], evidenceKind=literature["evidenceKind"])
        if experiment is not None:
            job.update(validationStatus="真实 ORX 本地 toy 实验；未调用模型服务", evidenceKind="toy_local_evaluation")
            if job.get("approvalDetail", {}).get("toolName") == "orx_experiment_run":
                provenance = experiment.get("provenance", {})
                limits = provenance.get("environment", {})
                scope = ("运行已封存的任务自有 ORX toy 实验："
                         f"最长 {limits.get('timeoutSeconds', '?')} 秒，"
                         f"输出上限 {limits.get('outputBytes', '?')} 字节；"
                         "源码和命令哈希见下方实验凭证。金额批准为零，无模型服务调用。")
                job["approvalDetail"]["scope"] = scope
                job["approval"]["scope"] = scope
        return {**({"comparisonEvidence": comparison} if comparison is not None else {}), **({"synthesisEvidence": synthesis} if synthesis is not None else {}), **({"literatureEvidence": literature} if literature is not None else {}), "inferenceWait": inference_wait, "orxExperiment": experiment, "usageLedger": usage, "job": job, "events": self.store.events(task["id"]), "artifacts": self.store.artifacts(task["id"]),
                "snapshot": {**snapshot, "delegation": group, "delegationScope": delegation_scope, "evaluation": evaluation, "nativeMetrics": snapshot.get("metrics") or (snapshot.get("run") or {}).get("metrics"), "planFingerprint": plan["fingerprint"], "effects": effects, "syntheticFixture": self.settings.demo}}

    def routes(self):
        router = self.router

        @router.get("/status")
        def status():
            rows = self.store.sql("SELECT body->>'lastStatus' AS state,COUNT(*) AS n FROM af_tasks WHERE NOT terminal GROUP BY state")
            counts = {row["state"]: row["n"] for row in rows}
            return {"mode": "demo" if self.settings.demo else "live", "integration": "Agno AgentOS 3.1.0 + PostgreSQL",
                    "maxWorkers": self.settings.max_workers, "activeWorkers": counts.get("running", 0), "queuedJobs": counts.get("queued", 0),
                    "liveEnabled": not self.settings.demo, "liveIntegrationVerified": False,
                    "admissionMode": "per-plan-preflight", "observedMetrics": True}

        @router.post("/demo/login")
        def login(body: Login, response: Response):
            if not self.settings.demo:
                raise HTTPException(404, "Demo login is disabled")
            token = self.auth.issue_demo_token(body.persona)
            response.set_cookie("factory_demo_session", token, httponly=True, samesite="strict", secure=False, max_age=3600)
            return self.auth.identity(body.persona)

        @router.post("/logout", status_code=204)
        def logout(request: Request, response: Response):
            self.auth.user(request)
            response.delete_cookie("factory_demo_session", httponly=True, samesite="strict")

        @router.get("/session")
        def session(request: Request):
            return self.auth.user(request)

        @router.get("/materials")
        def materials(request: Request):
            user = self.user(request, "read")
            service = self.store.material_governance
            values = self.store.materials(published_only=user["role"] != "manager")
            if service is None:
                raise HTTPException(503, "Material governance is unavailable")
            projected = []
            for material in values:
                try:
                    version = service.inspect_version(user["id"], material["id"], material["version"])
                except HTTPException as error:
                    if error.status_code not in {403, 404, 409}:
                        raise
                    continue
                state = version["governance"]
                projected.append({**version["material"], "archived": state["state"] == "archived",
                    "published": state["state"] == "published" and version["material"]["published"],
                    "governance": {"state": state["state"], "authorId": state["author_id"],
                                   "reason": state["reason"], "reviewId": state["review_id"]}})
            return projected

        @router.post("/materials", status_code=201)
        def material_create(body: MaterialRequest, request: Request):
            user = self.user(request, "write")
            if not body.requestId:
                raise HTTPException(400, "Material drafts require a stable requestId")
            definition = {**body.model_dump(exclude_none=True, exclude={"requestId"}), "license": "MIT",
                          "compatibility": ["agno:3.1.0"], "provenance": {"kind": "original", "notice": "Original manager-authored material."}}
            return self.store.material_governance.create_draft(user["id"], definition, body.requestId)

        @router.post("/materials/{material_id}/{version}/publish", status_code=202)
        def material_publish(material_id: str, version: int, body: PublicationRequest, request: Request):
            user = self.user(request, "write")
            # Compatibility route requests review; it cannot bypass distinct admin.
            return self.store.material_governance.request_publication(user["id"], material_id, version, body.requestId)

        @router.get("/connections")
        def connections(request: Request):
            user = self.user(request, "read")
            service = getattr(self.store, "connections", None)
            if service is None:
                raise HTTPException(503, "Trusted connection service is unavailable")
            return service.list(user["id"])

        @router.get("/runtime-adapters")
        def runtime_adapters(request: Request):
            self.user(request, "components:read")
            service = getattr(self.store, "execution_bindings", None)
            if service is None:
                raise HTTPException(503, "Trusted runtime adapter registry is unavailable")
            return service.describe()

        @router.get("/execution-targets")
        def execution_targets(request: Request):
            user = self.user(request, "read")
            return [{"id": ref, "name": ref, "kind": "remote-factory", "connectivityVerified": False}
                    for ref, target in self.remote.client.targets.items() if user["id"] in target.identity_map] if self.remote else []

        @router.post("/plans", status_code=201)
        def plan_create(body: PlanRequest, request: Request):
            user = self.user(request)
            fields = body.model_dump(exclude={"requestId", *({'inputValues'} if body.inputValues is None else set())})
            plan = self.store.admit_plan(user["id"], body.requestId, fields, lambda: create_plan(self.store, user["id"], body.topic, body.mode, body.application, application_ref=body.applicationRef, material_choices=body.materialChoices, connection_refs=body.connectionRefs, **({'input_values': body.inputValues} if body.inputValues is not None else {})))
            return {**plan, "authorization": self.store.plan_policy.status(user["id"], plan)}

        @router.post("/instances", status_code=202)
        async def instantiate(body: InstanceRequest, request: Request):
            user = self.user(request)
            self.store.require_current_policy()
            plan = self.store.plan(body.planId, user["id"])
            if plan.get("delegation") or plan.get("remoteHandoff"):
                raise HTTPException(403, "Delegated plans require their persisted ancestor mandate; use the child admission API")
            if plan["status"] != "ready":
                raise HTTPException(409, "Plan preflight is blocked: " + "; ".join(plan["missing"]))
            self.store.require_plan_execution(user["id"], plan)
            if body.executionTargetRef:
                if self.remote is None:
                    raise HTTPException(503, "Trusted remote execution is unavailable")
                return await self.remote.instantiate(user["id"], plan["id"], body.executionTargetRef, body.requestId)
            task, fresh = self.store.reserve_task(plan, body.requestId)
            if self.remote and self.remote.placed(task):
                raise HTTPException(409, "IDEMPOTENCY_CONFLICT: request already selected a remote execution server")
            if fresh:
                try:
                    receipt = await self.bridge.submit({**plan, "task_id": task["id"]}, user["id"], body.requestId)
                    self.store.accept(task["id"], receipt["run_id"])
                    self.store.event(task["id"], "native_accepted", "Native durable queue accepted the task", {"runId": receipt["run_id"]})
                except HTTPException as error:
                    if error.status_code >= 500:
                        self.store.admission_unknown(task["id"])
                    else:
                        self.store.admission_failed(task["id"], "Native admission rejected")
                        raise error
                except Exception:
                    self.store.admission_unknown(task["id"])
            return (await self.detail(self.store.task(task["id"], user["id"]))) ["job"]

        @router.get("/requests/{request_id}")
        def request_receipt(request_id: str, request: Request):
            user = self.user(request, "read")
            task = self.store.task_for_request(request_id, user["id"])
            # Do not invoke detail/reconciliation: this lookup cannot submit,
            # continue, cancel, emit events or release a reservation.
            placement = self.store.sql("SELECT target_ref FROM af_remote_placements WHERE task_id=:id AND owner_id=:owner",
                                       id=task["id"], owner=user["id"])
            return {"requestId": request_id, "taskId": task["id"], "planId": task["plan_id"],
                    "executionTargetRef": placement[0]["target_ref"] if placement else None,
                    "runId": task["run_id"], "admission": task["admission"],
                    "outcomeSource": "persisted_factory_intent"}

        @router.get("/jobs")
        async def jobs(request: Request):
            user = self.user(request, "read")
            details = await asyncio.gather(*(self.detail(task) for task in self.store.tasks(user["id"])))
            return [detail["job"] for detail in details]

        @router.get("/jobs/{task_id}")
        async def task_detail(task_id: str, request: Request):
            user = self.user(request, "read")
            task, child = self.scoped_task(task_id, user["id"])
            return await self.detail(task, child)

        @router.get("/jobs/{task_id}/events")
        async def event_page(task_id: str, request: Request, cursor: str | None = Query(default=None, max_length=4096),
                             limit: int = Query(default=100, ge=1, le=1000)):
            user = self.user(request, "read")
            task, child = self.scoped_task(task_id, user["id"])
            if self.remote and self.remote.placed(task):
                return await self.remote.events(task, child, cursor=cursor, limit=limit)
            return self.store.event_replay.page(user["id"], task["id"], cursor=cursor, limit=limit)

        @router.post("/jobs/{task_id}/children", status_code=202)
        async def delegate(task_id: str, body: ChildRequest, request: Request):
            user = self.user(request)
            task, child = self.scoped_task(task_id, user["id"])
            if self.remote and self.remote.placed(task):
                return await self.remote.delegate(task, body.goal, body.mode, body.requestId, child)
            if self.delegation is None:
                raise HTTPException(503, "Delegation service is unavailable")
            result = await self.delegation.create(user["id"], task_id, body.goal, body.mode, body.requestId)
            return {**result, "job": (await self.detail(result["childTask"]))["job"]}

        @router.get("/jobs/{task_id}/children")
        async def children(task_id: str, request: Request):
            user = self.user(request, "read")
            if self.delegation is None:
                raise HTTPException(503, "Delegation service is unavailable")
            task, child = self.scoped_task(task_id, user["id"])
            if self.remote and self.remote.placed(task):
                return await self.remote.children(task, child)
            return await self.delegation.children(user["id"], task_id)

        @router.get("/jobs/{task_id}/group")
        async def group(task_id: str, request: Request):
            user = self.user(request, "read")
            if self.delegation is None:
                raise HTTPException(503, "Delegation service is unavailable")
            task, child = self.scoped_task(task_id, user["id"])
            if self.remote and self.remote.placed(task):
                return (await self.remote.detail(task, child))["snapshot"].get("delegation")
            return await self.delegation.inspect_group(user["id"], task_id)

        @router.get("/commands")
        async def outstanding_commands(request: Request, taskId: str | None = None,
                                       limit: int = Query(default=50, ge=1, le=100),
                                       after: str | None = Query(default=None, max_length=100), outstanding: bool = True):
            user = self.user(request, "read")
            return await self.commands.list(user["id"], taskId, limit=limit, after=after, outstanding=outstanding)

        @router.get("/jobs/{task_id}/commands/{command_id}")
        async def command_receipt(task_id: str, command_id: str, request: Request):
            user = self.user(request, "read")
            return await self.commands.recover(user["id"], task_id, command_id)

        @router.post("/jobs/{task_id}/commands", status_code=202)
        async def submit_command(task_id: str, body: ControlCommand, request: Request):
            user = self.user(request)
            return await self.commands.submit(user["id"], task_id, body)

        @router.post("/jobs/{task_id}/commands/{command_id}/acknowledge")
        async def acknowledge_command(task_id: str, command_id: str, request: Request):
            user = self.user(request, "read")
            return await self.commands.acknowledge(user["id"], task_id, command_id)

        @router.post("/jobs/{task_id}/commands/{command_id}/dispatch", status_code=202)
        async def dispatch_prepared(task_id: str, command_id: str, request: Request):
            user = self.user(request)
            return await self.commands.dispatch(user["id"], task_id, command_id)

        async def compatibility_command(task_id, request, action, decision, command_id):
            user = self.user(request)
            receipt = await self.commands.submit(user["id"], task_id, legacy_command(task_id, action, decision, command_id))
            task, child = self.scoped_task(task_id, user["id"])
            return {**(await self.detail(task, child))["job"], "commandReceipt": receipt}

        @router.post("/jobs/{task_id}/cancel")
        async def cancel(task_id: str, request: Request, body: Cancel | None = None):
            return await compatibility_command(task_id, request, "cancel", {}, body.commandId if body else None)

        @router.post("/jobs/{task_id}/answer")
        async def answer(task_id: str, body: Answer, request: Request):
            return await compatibility_command(task_id, request, "answer",
                {"requirementId": body.questionId, "version": body.version, "answer": body.answer}, body.commandId)

        @router.post("/jobs/{task_id}/approve")
        async def approve(task_id: str, body: Approval, request: Request):
            return await compatibility_command(task_id, request, "approve",
                {"requirementId": body.requirementId, "version": body.version, "approved": body.approved}, body.commandId)

        @router.post("/jobs/{task_id}/reconcile")
        async def reconcile(task_id: str, request: Request):
            user = self.user(request)
            task, child = self.scoped_task(task_id, user["id"])
            if self.remote and self.remote.placed(task):
                return (await self.remote.detail(task, child))["job"]
            # Snapshot/receipt lookup only; no replay and no timeout-based capacity release.
            if not task.get("run_id"):
                finder = getattr(self.bridge, "find_run", None)
                receipt = await finder(task["id"], user["id"]) if finder else None
                if receipt:
                    self.store.accept(task_id, receipt["run_id"])
            self.store.event(task_id, "reconciliation", "Queried native state; unresolved effects remain UNKNOWN", {})
            return (await self.detail(self.store.task(task_id, user["id"]))) ["job"]

        @router.get("/jobs/{task_id}/artifacts/{artifact_id}")
        async def download(task_id: str, artifact_id: str, request: Request):
            user = self.user(request, "read")
            task, child = self.scoped_task(task_id, user["id"])
            if self.remote and self.remote.placed(task):
                meta, raw = await self.remote.client.artifact(user["id"], task["id"], artifact_id, child)
            else:
                meta, raw = self.store.artifact(task_id, artifact_id)
            return Response(raw, media_type=meta["mediaType"], headers={"Content-Disposition": "attachment; filename*=UTF-8''" + __import__("urllib.parse", fromlist=["quote"]).quote(meta["name"]), "X-Content-SHA256": meta["sha256"], "Cache-Control": "private, no-store"})

import asyncio
import hashlib

from fastapi import APIRouter, HTTPException, Request, Response
from .control_commands import ControlCommands
from .application_runs import StartNotSubmitted
from .native_bridge import NativeAdmissionRejected
from .delegation import application_group_status
from fastapi.routing import APIRoute as FactoryPublicRoute
from .store import FAILURE_CLEANUP_REASONS, effect_unresolved, canonical
from .runtime_hooks import execution_classification
from .task_status import finalized_status, native_status


def requirement_version(requirement):
    # A native requirement ID plus canonical contents form a stable stale-action token.
    return int(hashlib.sha256(canonical(requirement).encode()).hexdigest()[:12], 16)


def native_requirements(snapshot):
    run = snapshot.get("run", snapshot)
    return run.get("requirements") or []


def status_of(task, snapshot, effects, events, store, *, failure_cleanup):
    if task["admission"] == "rejected":
        return "failed"
    if task["admission"] in {"unknown", "reserved"} and not task.get("run_id"):
        return "unknown"
    queue = snapshot.get("queue") or snapshot.get("job") or {}
    run = snapshot.get("run", snapshot)
    raw = native_status(queue.get("status"), run.get("status"))
    if any(effect_unresolved(effect, store) for effect in effects) and raw not in {"running", "runstatus.running"}:
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
        if failure_cleanup or any(event["type"] in {"tool_failed", "protected_denied", "experiment_failed"} for event in events):
            return "failed"
        return "completed"
    return "running" if raw in {"running", "runstatus.running"} else "queued"


class FactoryAPI:
    command_type = ControlCommands

    def __init__(self, settings, store, auth, bridge):
        self.settings, self.store, self.auth, self.bridge = settings, store, auth, bridge
        self.delegation = getattr(store, "delegation", None)
        self.commands = self.command_type(self)
        self.router = APIRouter(prefix="/api/factory", route_class=FactoryPublicRoute)
        self.routes()

    def _instantiate_preflight(self, owner, execution):
        self.auth.require_member(owner)
        if execution.get("delegation") or execution.get("remoteHandoff"):
            raise HTTPException(403, "Delegated tasks require their persisted ancestor context; use the child admission API")
        self.store.require_plan_execution(owner, execution)

    async def admit(self, owner, execution, request_id, *, delivery_id=None, private_event_id=None):
        """Shared governed admission, including durable unknown-ack handling."""
        if self.store._connection.get() is not None:
            raise RuntimeError('Native admission requires a committed metadata boundary')
        # Trusted owner resources can require a synchronous remote health
        # check. Preserve fresh checks without blocking other ASGI requests.
        options = {}
        if delivery_id is not None:
            options['delivery_id'] = delivery_id
        if private_event_id is not None:
            options['private_event_id'] = private_event_id
        try:
            await asyncio.to_thread(self._instantiate_preflight, owner, execution)
            task, fresh = await asyncio.to_thread(self.store.reserve_task, execution, request_id, **options)
        except Exception as error:
            raise StartNotSubmitted(error) from error
        execution = self.store.execution(task)
        if fresh:
            try:
                receipt = await self.bridge.submit({**execution, "task_id": task["id"]}, owner, request_id)
                self.store.accept(task["id"], receipt["run_id"])
                self.store.event(task["id"], "native_accepted", "Native durable queue accepted the task", {"runId": receipt["run_id"]})
                return task["id"]
            except NativeAdmissionRejected:
                self.store.admission_failed(task["id"], "Native queue is full; submission was not accepted", never_submitted=True)
                raise
            except Exception:
                self.store.admission_unknown(task["id"])
        if not task.get("run_id") and task["admission"] != "rejected":
            await self.store.lifecycle_observer.recover_admission(self.store.task(task["id"], owner))
        return task["id"]

    def owner(self, request):
        owner = self.auth.request_owner(request)
        self.auth.require_member(owner)
        return owner

    def scoped_task(self, identifier, owner):
        return self.store.task(identifier, owner), None

    async def observe_task(self, task):
        task = await self.store.lifecycle_observer.recover_admission(task)
        snapshot = {}
        if task.get("run_id"):
            try:
                snapshot = await self.bridge.detail(task["run_id"], task["id"], task["owner_id"],
                    native_session=self.store.native_session_id(task))
            except HTTPException as error:
                ticket = self.store.lifecycle_observer._binding(task)
                if error.status_code != 404 or not ticket or ticket['status'] != 'cancelled':
                    raise
                # Native acceptance preparation can cancel its ticket before saving a run.
                snapshot = {'queue': ticket}
        group = None
        if self.delegation:
            group = await self.delegation.inspect_group(task["owner_id"], task["id"])
        # Cleanup can commit during the native/group reads; use its latest cancellation and failure state.
        task = self.store.task(task["id"], task["owner_id"])
        events = self.store.events(task["id"])
        failure_cleanup = any(event["type"] == "lifecycle_cleanup_requested" and
            isinstance(event["data"], dict) and event["data"].get("reason") in FAILURE_CLEANUP_REASONS for event in events)
        effects = group["parent"]["effects"] if group is not None else self.store.effects(task["id"])
        status = status_of(task, snapshot, effects, events, self.store, failure_cleanup=failure_cleanup)
        if group is not None:
            status = application_group_status(status, group)
            if task["cancel_requested"] and not group["allStopped"]:
                status = "unknown" if group["unknown"] else "canceling"
            elif task["cancel_requested"] and group["allStopped"]:
                status = "failed" if failure_cleanup else "canceled"
        stopped_status = task["body"].get("stoppedStatus")
        status = (stopped_status if task["terminal"] else "finalizing") if stopped_status else finalized_status(status, task["terminal"])
        return {"task": task, "status": status, "events": events, "snapshot": {**snapshot, "delegation": group, "effects": effects}}

    async def detail(self, task, remote_child=None):
        observation = await self.observe_task(task)
        task, status, snapshot = observation["task"], observation["status"], observation["snapshot"]
        execution = self.store.execution(task)
        stopped_status = task["body"].get("stoppedStatus")
        delegation_scope = await asyncio.to_thread(self.delegation.delegation_scope, task["owner_id"], task["id"]) if self.delegation else None
        actions = ["inspect"]
        if delegation_scope and delegation_scope["allowed"]:
            actions.append("delegate")
        if status in {"queued", "running", "waiting_input", "waiting_approval", "unknown", "canceling", "waiting_children"}:
            actions.append("cancel")
        if status in {"unknown", "finalizing"}:
            actions.append("reconcile")
        job = {"id": task["id"], "ownerId": task["owner_id"], "executionId": execution["id"], "planId": execution["id"],
            "input": {"topic": execution["normalizedGoal"], "mode": execution["mode"], "scenario": "normal"},
            "status": status, "createdAt": task["body"]["createdAt"], "updatedAt": task["body"]["updatedAt"],
            "runtime": "live", "attempt": (snapshot.get("queue") or {}).get("attempt", 0),
            "allowedActions": actions, "validationStatus": "执行与结论需按产物证据分别验证",
            "executionKind": execution_classification(execution)["executionKind"],
            "verificationStatus": "unverified", "evidenceKind": "unverified"}
        if stopped_status:
            job.update(executionStatus=stopped_status, finalizationPending=not task["terminal"])
        for requirement in native_requirements(snapshot):
            tool = requirement.get("tool_execution") or {}
            version = requirement_version(requirement)
            if tool.get('tool_name') == 'workflow_wait' and tool.get('external_execution_required'):
                scope = '等待原工作流阶段或人工决定；请使用工作流面板核对与继续。'
                job.update(approvalDetail={'id': requirement['id'], 'version': version, 'scope': scope,
                    'toolName': 'workflow_wait', 'arguments': tool.get('tool_args', {})}, approval={'scope': scope})
            elif tool.get("external_execution_required") and tool.get("tool_name") in getattr(self.store, "external_execution_handlers", {}) and tool.get("result") is None:
                scope = "Continue this exact approved external execution within its existing budget and original custody."
                job.update(approvalDetail={"id": requirement["id"], "version": version, "scope": scope,
                    "toolName": tool["tool_name"], "arguments": tool.get("tool_args", {})}, approval={"scope": scope})
                if status == "waiting_approval":
                    actions.append("approve")
            elif tool.get("requires_user_input") and not tool.get("answered"):
                question = {"id": requirement["id"], "version": version, "text": "请补充本任务所需的信息。", "fields": requirement.get("user_input_schema") or tool.get("user_input_schema") or []}
                job.update(questionDetail=question, question=question["text"])
                if status == "waiting_input":
                    actions.append("answer")
            elif tool.get("requires_confirmation") and tool.get("confirmed") is None:
                approval = {"id": requirement["id"], "version": version, "scope": f"批准本任务已绑定的工具 {tool.get('tool_name')}，参数与权限以当前任务上下文为准。", "toolName": tool.get("tool_name"), "arguments": tool.get("tool_args", {})}
                job.update(approvalDetail=approval, approval={"scope": approval["scope"], "requestedAt": requirement.get("created_at", execution["createdAt"])})
                if status == "waiting_approval":
                    actions.append("approve")
        if delegation_scope and delegation_scope.get("executionUnavailable"):
            job["allowedActions"] = [action for action in actions if action in {"inspect", "cancel", "reconcile"}]
        try:
            self.auth.require_member(task["owner_id"])
        except HTTPException as error:
            if error.status_code != 403:
                raise
            job["allowedActions"] = ["inspect"]
        return {"job": job,
                "events": observation["events"], "artifacts": self.store.artifacts(task["id"]),
                "snapshot": {**snapshot, "delegationScope": delegation_scope,
                    "nativeMetrics": snapshot.get("metrics") or (snapshot.get("run") or {}).get("metrics"),
                    "executionFingerprint": task["fingerprint"], "planFingerprint": task["fingerprint"],
                    "syntheticFixture": execution_classification(execution)["syntheticFixture"]}}

    def routes(self):
        router = self.router

        @router.get('/session')
        def session(request: Request):
            return self.auth.user(request)

        @router.get('/jobs/{task_id}')
        async def detail(task_id: str, request: Request):
            return await self.detail(self.store.task(task_id, self.owner(request)))

        @router.get('/jobs/{task_id}/artifacts/{artifact_id}')
        async def download(task_id: str, artifact_id: str, request: Request):
            self.store.task(task_id, self.owner(request))
            meta, raw = self.store.artifact(task_id, artifact_id)
            from urllib.parse import quote
            return Response(raw, media_type=meta['mediaType'], headers={
                'Content-Disposition': "attachment; filename*=UTF-8''" + quote(meta['name']),
                'X-Content-SHA256': meta['sha256'], 'Cache-Control': 'private, no-store'})

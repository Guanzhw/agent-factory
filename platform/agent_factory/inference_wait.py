"""Bounded native pause after a transient inference failure, never a new worker.

Only acknowledged revision-2 Linux toy launches in the original tree qualify. The pause is
Factory control metadata, not a fabricated provider answer or a new tool grant.
Native Agno owns the pause, continuation ticket and original run transcript.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

from agno.exceptions import ModelProviderError, RunCancelledException
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.requirement import RunRequirement
from fastapi import HTTPException

from .orx_experiment_tools import (ADAPTER_ID, LAUNCH_EFFECT_KEY, TOOL_NAMES, _observe,
    _persist_result, _public_result, _request, inspect_orx_experiment, original_experiment_binding)
from .store import canonical, digest

CONTROL_NAME = "factory_resume_inference"
MAX_FAILURES = 2


def transient(error):
    # 429 can mean quota exhaustion. Authentication, quota, context and unknown
    # errors are deliberately excluded; providers cannot self-declare a pause.
    return type(error) is ModelProviderError and error.status_code in {408, 500, 502, 503, 504}


def read(store, task_id):
    rows = store.sql("SELECT * FROM af_inference_waits WHERE task_id=:task", task=task_id)
    if not rows:
        return None
    row = rows[0]
    task = store.task(task_id)
    body = row["body"]
    if (digest(body) != row["hash"] or body.get("taskId") != task_id
            or body.get("ownerId") != task["owner_id"] or body.get("nativeRunId") != task["run_id"]
            or body.get("planId") != task["plan_id"]):
        raise PermissionError("Inference wait identity/integrity differs")
    return {**body, "state": row["state"]}


def context(task):
    return SimpleNamespace(user_id=task["owner_id"], session_id=task["id"], run_id=task["run_id"],
        session_state={"factory_envelope": {"user_id": task["owner_id"], "task_id": task["id"],
            "plan_ref": task["plan_id"], "request_id": task["request_id"]}})


def execution_owner(store, task):
    """Bind the existing delegation/receiver owner; never transfer execution."""
    service = getattr(store, "delegation", None)
    root, ancestors = service._ancestry(task) if service else (task["id"], [])
    root_task = ancestors[-1] if ancestors else task
    plan = store.plan(root_task["plan_id"], task["owner_id"])
    if plan.get("remoteHandoff") and not callable(getattr(store, "execution_guards", {}).get("remote_receiver")):
        raise PermissionError("Current receiver authority guard is unavailable")
    if plan.get("delegation") and service is None:
        raise PermissionError("Current delegation owner is unavailable")
    return {"rootTaskId": root, "rootNativeRunId": root_task["run_id"],
            "ancestorTaskIds": [a["id"] for a in ancestors], "receiver": plan.get("remoteHandoff")}


def within_budget(store, task):
    ledger = store.usage_ledger.inspect(task["owner_id"], task["id"])
    for scope in ledger["scopes"]:
        if (scope["settledTokens"] + scope["heldTokens"] > scope["tokenLimit"]
                or scope["settledAmountMicros"] + scope["heldAmountMicros"] > scope["amountMicrosLimit"]):
            raise HTTPException(429, "USAGE_BUDGET_EXCEEDED: external work must stop")


def current(store, task, wait=None):
    ctx = context(task)
    plan = store.plan(task["plan_id"], task["owner_id"])
    if task["cancel_requested"]:
        raise RunCancelledException("Existing cancellation denies inference recovery")
    if store.has_failures(task["id"]):
        raise PermissionError("Existing protected failure denies inference recovery")
    owner = execution_owner(store, task) if wait and "executionOwner" in wait else None
    if owner is not None and wait is not None and wait["executionOwner"] != owner:
        raise PermissionError("Inference wait execution ownership differs")
    checked_guards = store.require_plan_execution(task["owner_id"], plan, run_context=ctx) or {}
    # Observation spends no tool call. require_plan_execution already checks the
    # exact policy/review once. Receiver authorize(None) validates the *whole*
    # immutable tool/capability intersection, current origin and original grant;
    # repeating that same HTTP proof per name adds no narrower authority.
    # Explicitly tool-independent guards were also fully checked above. Match
    # callable identity so a replacement never inherits the old declaration.
    # Unknown/tool-specific guards still receive each name; actual tool entry
    # and fresh checks at both ends of observation remain unchanged.
    independent = getattr(store, "tool_independent_execution_guards", {})
    for name in (TOOL_NAMES[1], TOOL_NAMES[2]):
        if name not in plan.get("tools", []):
            raise PermissionError("Original run/wait capability is unavailable")
        for key, guard in getattr(store, "execution_guards", {}).items():
            if key != "remote_receiver" and not (checked_guards.get(key) is guard and independent.get(key) is guard):
                guard(ctx.user_id, plan, ctx, name)
    if store.task(task["id"])["cancel_requested"]:
        raise RunCancelledException("Cancellation supersedes inference observation")
    if wait and datetime.now(timezone.utc) >= datetime.fromisoformat(wait["deadline"]):
        raise HTTPException(409, "INFERENCE_WAIT_EXPIRED: original deadline cannot renew")
    within_budget(store, task)
    # Unknown billed attempts retain their full holds. They cannot be retried
    # without admission; begin_attempt remains the only authority to spend.
    return plan, ctx


def observe(store, task, wait, *, admitting=False):
    """Current authority plus original source/run/kernel observation, no launch."""
    if not admitting:
        latest = read(store, task["id"])
        if not latest or latest["state"] not in {"WAITING", "RESUMING"} or latest["controlId"] != wait["controlId"]:
            return None
    current(store, store.task(task["id"]), wait)
    work = wait.get("externalWork") or [{"taskId": task["id"], "nativeRunId": task["run_id"],
        "planId": task["plan_id"], "orxRunId": wait["orxRunId"], "effectFingerprint": wait["effectFingerprint"]}]
    results = []
    for identity in work:
        completed_child = False
        owned = store.task(identity["taskId"], task["owner_id"])
        if owned["run_id"] != identity["nativeRunId"] or owned["plan_id"] != identity["planId"]:
            raise PermissionError("Inference wait cannot adopt a different child/run/plan")
        if owned["id"] != task["id"]:
            _, ancestors = store.delegation._ancestry(owned)
            if task["id"] not in {a["id"] for a in ancestors}:
                raise PermissionError("Inference wait external work left its original subtree")
            # Completed work is read-only evidence, not a renewed child mandate.
            # Active children retain the full inherited native policy checks.
            ticket = store.native_db.get_job(owned["run_id"], strict=True) or {}
            if not ticket:
                raise PermissionError("Original child native ticket is missing")
            if ticket.get("status") == "completed":
                completed_child = True
                if owned["cancel_requested"] or store.has_failures(owned["id"]):
                    raise PermissionError("Completed child has unresolved failure/cancellation")
                if (ticket.get("id"), ticket.get("session_id"), ticket.get("user_id"), ticket.get("component_id")) != (
                        owned["run_id"], owned["id"], owned["owner_id"], "factory-executor"):
                    raise PermissionError("Completed child native identity differs")
                within_budget(store, owned)
            else:
                current(store, owned)
        results.append(observe_work(store, owned, identity, require_stopped=completed_child))
    current(store, store.task(task["id"]), wait)
    return results[0] if len(results) == 1 else results


def observe_work(store, task, wait, *, require_stopped=False):
    original = original_experiment_binding(store.settings, store, task["id"])
    if original is None:
        raise PermissionError("Original experiment binding is missing")
    _, plan, ctx, binding = original
    receipt = binding.adapter.observe_existing()
    if receipt.get("run_id") != wait["orxRunId"]:
        raise PermissionError("Inference wait cannot adopt a different ORX run")
    result = _public_result(plan, ctx, binding, receipt, digest(_request(plan, ctx, binding)))
    if result["effectFingerprint"] != wait["effectFingerprint"]:
        raise PermissionError("Inference wait cannot replace its external effect")
    if require_stopped and (result["status"] not in {"done", "failed", "cancelled"}
            or result.get("stopEvidence", {}).get("allStopped") is not True):
        raise PermissionError("Completed child does not authorize continuing external work")
    if result["status"] in {"done", "failed", "cancelled"} and result.get("stopEvidence", {}).get("allStopped") is True:
        old = next(e for e in store.effects(task["id"]) if e["effect_key"] == task["run_id"] + ":" + LAUNCH_EFFECT_KEY)
        if old["status"] == "UNKNOWN":
            if result["status"] == "cancelled":
                result["cancelled"] = True
            result = _persist_result(store, ctx, result, binding)
            store.effect_complete(ctx.run_id, LAUNCH_EFFECT_KEY, result)
        else:
            result = old["result"]
    _observe(store, ctx, result)
    return result


def reconcile_recovered_children(store, task, wait):
    """Read original child effects after parent inference resumes; never retry.

    A recovered parent may complete before an independently approved child.
    Reconciliation must not depend on another parent inference failure. Each
    still-active child supplies its own current mandate and original bounds.
    """
    latest = read(store, task["id"])
    if not latest or latest["state"] != "RECOVERED" or latest["controlId"] != wait["controlId"]:
        return
    if task["cancel_requested"] or store.has_failures(task["id"]):
        return  # The ordinary observer cascades existing stop authority.
    if wait.get("executionOwner") != execution_owner(store, task):
        raise PermissionError("Recovered parent ownership differs")
    for identity in wait.get("externalWork", []):
        if identity["taskId"] == task["id"]:
            continue
        child = store.task(identity["taskId"], task["owner_id"])
        if child["run_id"] != identity["nativeRunId"] or child["plan_id"] != identity["planId"]:
            raise PermissionError("Recovered parent cannot adopt another child")
        _, ancestors = store.delegation._ancestry(child)
        if task["id"] not in {a["id"] for a in ancestors}:
            raise PermissionError("Recovered child left its original subtree")
        effects = [e for e in store.effects(child["id"])
            if e["effect_key"] == child["run_id"] + ":" + LAUNCH_EFFECT_KEY]
        if not effects or effects[0]["status"] != "UNKNOWN":
            continue
        ticket = store.native_db.get_job(child["run_id"], strict=True)
        if not ticket or ticket.get("status") not in {"queued", "running", "paused"}:
            continue  # Native terminal failure/unknown remains fail-closed.
        current(store, child)
        observe_work(store, child, identity)


def acknowledged_work(store, task):
    candidates = [task]
    service = getattr(store, "delegation", None)
    if service:
        candidates += [store.task(link["child_id"], task["owner_id"])
            for link in service._descendants(task["id"]) if link["child_id"]]
    work = []
    for candidate in candidates:
        plan = store.plan(candidate["plan_id"], candidate["owner_id"])
        launch = [s for s in plan.get("executionBindings", {}).get("tools", [])
                  if s.get("adapterId") == ADAPTER_ID + "-run" and s.get("revision") == "2"]
        if len(launch) != 1:
            continue
        experiment = inspect_orx_experiment(store, candidate["owner_id"], candidate["id"])
        if not experiment or not experiment.get("orxRunId") or experiment.get("status") not in {"running", "starting", "done"}:
            continue
        work.append({"taskId": candidate["id"], "planId": candidate["plan_id"], "nativeRunId": candidate["run_id"],
            "orxRunId": experiment["orxRunId"], "effectFingerprint": experiment["effectFingerprint"],
            "timeoutSeconds": experiment["provenance"]["environment"]["timeoutSeconds"]})
    return work


def prepare_pause(store, response, error):
    if not transient(error) or os.name != "posix" or getattr(store, "usage_ledger", None) is None:
        return None
    task = store.task(response.session_id, response.user_id)
    work = acknowledged_work(store, task)
    if not work:
        return None
    previous = read(store, task["id"])
    if previous and (previous["failures"] >= MAX_FAILURES or previous["state"] == "STOPPING"):
        return None
    current(store, task, previous)
    at = datetime.now(timezone.utc)
    seconds = min(30., *(float(w["timeoutSeconds"]) for w in work))
    body = {"schema": 1, "ownerId": task["owner_id"], "taskId": task["id"], "planId": task["plan_id"],
        "nativeRunId": task["run_id"], "orxRunId": work[0]["orxRunId"],
        "effectFingerprint": work[0]["effectFingerprint"], "errorStatus": error.status_code,
        "executionOwner": execution_owner(store, task), "externalWork": work,
        "failures": previous["failures"] + 1 if previous else 1,
        "deadline": previous["deadline"] if previous else (at + timedelta(seconds=seconds)).isoformat(),
        "createdAt": previous["createdAt"] if previous else at.isoformat(), "controlId": str(uuid4())}
    observe(store, task, body, admitting=True)
    return body


def publish_pause(store, response, messages, body, *, streaming=False):
    # Native output and requirement mutation must stay on the calling event loop.
    # A cancelled blocking preparation can never publish a late native pause.
    task = store.task(response.session_id, response.user_id)
    if task["cancel_requested"]:
        raise RunCancelledException("Existing cancellation denies inference recovery")
    if store.has_failures(task["id"]):
        raise PermissionError("Existing protected failure denies inference recovery")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(body["deadline"]):
        raise HTTPException(409, "INFERENCE_WAIT_EXPIRED: original deadline cannot renew")
    # Persist before exposing the native pause. A crash here grants no replay;
    # the observer still bounds and checks the original external workload.
    store.sql("""INSERT INTO af_inference_waits VALUES(:task,CAST(:body AS JSONB),:hash,'WAITING')
        ON CONFLICT(task_id) DO UPDATE SET body=EXCLUDED.body,hash=EXCLUDED.hash,state='WAITING'""",
        task=task["id"], body=canonical(body), hash=digest(body))
    store.event(task["id"], "inference_wait_recorded", "Transient inference failure; existing approved experiment remains bounded", body)
    call = {"id": body["controlId"], "type": "function", "function": {"name": CONTROL_NAME, "arguments": "{}"}}
    messages.append(Message(role="assistant", content="Factory control: inference unavailable; awaiting a bounded retry decision.", tool_calls=[call]))
    execution = ToolExecution(tool_call_id=body["controlId"], tool_name=CONTROL_NAME, tool_args={}, external_execution_required=True)
    if not streaming:
        if response.requirements is None:
            response.requirements = []
        response.requirements.append(RunRequirement(tool_execution=execution))
    return ModelResponse(event=ModelResponseEvent.tool_call_paused.value, tool_executions=[execution])


def pause(store, response, messages, error, *, streaming=False):
    body = prepare_pause(store, response, error)
    return None if body is None else publish_pause(store, response, messages, body, streaming=streaming)


def validate_requirement(store, task, tool):
    wait = read(store, task["id"])
    if (not wait or wait["state"] != "WAITING" or tool.get("tool_name") != CONTROL_NAME
            or tool.get("tool_call_id") != wait["controlId"] or tool.get("tool_args") != {}
            or tool.get("external_execution_required") is not True or tool.get("result") is not None):
        raise HTTPException(409, "INFERENCE_WAIT_CHANGED: exact native recovery requirement required")
    # Approval cannot outrun the observer and discard a drifted external binding.
    try:
        observe(store, task, wait)
    except (PermissionError, RunCancelledException) as error:
        raise HTTPException(409, "INFERENCE_WAIT_UNAVAILABLE: original work no longer permits recovery") from error
    return wait

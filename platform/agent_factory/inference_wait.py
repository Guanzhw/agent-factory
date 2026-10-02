"""Bounded native pause after a transient inference failure, never a new worker.

Only acknowledged standalone revision-2 Linux toy launches qualify. The pause is
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


def current(store, task, wait=None):
    ctx = context(task)
    plan = store.plan(task["plan_id"], task["owner_id"])
    if task["cancel_requested"]:
        raise RunCancelledException("Existing cancellation denies inference recovery")
    if store.has_failures(task["id"]):
        raise PermissionError("Existing protected failure denies inference recovery")
    store.require_plan_execution(task["owner_id"], plan, run_context=ctx)
    # This is observation, not a new tool call. Apply the same current per-tool
    # policy/guards without recording user cancellation as a protected failure.
    for name in (TOOL_NAMES[1], TOOL_NAMES[2]):
        if name not in plan.get("tools", []):
            raise PermissionError("Original run/wait capability is unavailable")
        policy = getattr(store, "plan_policy", None)
        if policy is not None:
            policy.require_context_tool(ctx, name)
        for guard in getattr(store, "execution_guards", {}).values():
            guard(ctx.user_id, plan, ctx, name)
    if store.task(task["id"])["cancel_requested"]:
        raise RunCancelledException("Cancellation supersedes inference observation")
    if wait and datetime.now(timezone.utc) >= datetime.fromisoformat(wait["deadline"]):
        raise HTTPException(409, "INFERENCE_WAIT_EXPIRED: original deadline cannot renew")
    ledger = store.usage_ledger.inspect(task["owner_id"], task["id"])
    for scope in ledger["scopes"]:
        if (scope["settledTokens"] + scope["heldTokens"] > scope["tokenLimit"]
                or scope["settledAmountMicros"] + scope["heldAmountMicros"] > scope["amountMicrosLimit"]):
            raise HTTPException(429, "USAGE_BUDGET_EXCEEDED: external work must stop")
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
    current(store, store.task(task["id"]), wait)
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


def pause(store, response, messages, error, *, streaming=False):
    if not transient(error) or os.name != "posix" or getattr(store, "usage_ledger", None) is None:
        return None
    task = store.task(response.session_id, response.user_id)
    plan = store.plan(task["plan_id"], task["owner_id"])
    launch = [s for s in plan.get("executionBindings", {}).get("tools", [])
              if s.get("adapterId") == ADAPTER_ID + "-run" and s.get("revision") == "2"]
    if len(launch) != 1 or plan.get("delegation") or plan.get("remoteHandoff"):
        return None
    experiment = inspect_orx_experiment(store, task["owner_id"], task["id"])
    if not experiment or not experiment.get("orxRunId") or experiment.get("status") not in {"running", "starting", "done"}:
        return None
    previous = read(store, task["id"])
    if previous and (previous["failures"] >= MAX_FAILURES or previous["state"] == "STOPPING"):
        return None
    current(store, task, previous)
    at = datetime.now(timezone.utc)
    seconds = min(30., float(experiment["provenance"]["environment"]["timeoutSeconds"]))
    body = {"schema": 1, "ownerId": task["owner_id"], "taskId": task["id"], "planId": task["plan_id"],
        "nativeRunId": task["run_id"], "orxRunId": experiment["orxRunId"],
        "effectFingerprint": experiment["effectFingerprint"], "errorStatus": error.status_code,
        "failures": previous["failures"] + 1 if previous else 1,
        "deadline": previous["deadline"] if previous else (at + timedelta(seconds=seconds)).isoformat(),
        "createdAt": previous["createdAt"] if previous else at.isoformat(), "controlId": str(uuid4())}
    observe(store, task, body, admitting=True)
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


def validate_requirement(store, task, tool):
    wait = read(store, task["id"])
    if (not wait or wait["state"] != "WAITING" or tool.get("tool_name") != CONTROL_NAME
            or tool.get("tool_call_id") != wait["controlId"] or tool.get("tool_args") != {}
            or tool.get("external_execution_required") is not True or tool.get("result") is not None):
        raise HTTPException(409, "INFERENCE_WAIT_CHANGED: exact native recovery requirement required")
    current(store, task, wait)
    return wait

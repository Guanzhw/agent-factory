"""Native, plan-bound tools for one reviewed task-owned ORX toy experiment.

The deterministic model exercises Agno's real tool/HITL loop. ORX alone creates
experiment/run rows. UNKNOWN launch acknowledgements never grant retry authority.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Callable

from agno.exceptions import RunCancelledException
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from .demo_model import CONTEXT_MARKER
from .openresearch import BinaryPin, OpenResearchAdapter, OpenResearchError, REVISION, VERSION
from .store import canonical, digest

ADAPTER_ID = "openresearch-experiment-v1"
ADAPTER_REVISION = "1"
LEAST_CAPABILITY_REVISION = "2"
MODEL_ADAPTER_ID = "local-orx-workflow-model-v1"
MODEL_ADAPTER_REVISION = "1"
WINDOWS_BINARY_SHA256 = "d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7"
from .orx_linux import BINARY_SHA256 as LINUX_BINARY_SHA256
BINARY_SHA256 = WINDOWS_BINARY_SHA256 if os.name == "nt" else LINUX_BINARY_SHA256
TOOL_NAMES = tuple("orx_experiment_" + name for name in ("inspect", "run", "wait", "cancel", "logs"))
SCENARIOS = frozenset({"success", "evaluator_failure", "long_running"})
READ_CAPABILITY = "research:read"
RUN_CAPABILITY = "compute:local"
LAUNCH_EFFECT_KEY = "orx-experiment-launch-v1"
_TERMINAL = frozenset({"done", "failed", "cancelled"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def initialize_orx_experiments(store: Any) -> None:
    """Install Factory metadata only; ORX experiment/run tables stay upstream-owned."""
    store.sql("""CREATE TABLE IF NOT EXISTS af_orx_task_experiments (
        task_id TEXT PRIMARY KEY REFERENCES af_tasks(id), owner_id TEXT NOT NULL,
        plan_id TEXT NOT NULL REFERENCES af_plans(id), run_id TEXT NOT NULL,
        binding JSONB NOT NULL, binding_hash TEXT NOT NULL,
        observation JSONB NOT NULL, observation_hash TEXT NOT NULL)""")


def _record_binding(store: Any, plan: dict[str, Any], ctx: RunContext,
                    binding: ResolvedExperimentBinding) -> None:
    request = _request(plan, ctx, binding)
    native = binding.adapter._bound()
    immutable = {**request, "projectId": native.project_id, "experimentId": native.experiment_id}
    initial = _public_result(plan, ctx, binding, {"state": "NOT_STARTED", "run_id": None}, digest(request))
    store.sql("""INSERT INTO af_orx_task_experiments VALUES(
        :task,:owner,:plan,:run,CAST(:binding AS JSONB),:hash,CAST(:observation AS JSONB),:ohash)
        ON CONFLICT DO NOTHING""", task=ctx.session_id, owner=ctx.user_id, plan=plan["id"], run=ctx.run_id,
        binding=canonical(immutable), hash=digest(immutable), observation=canonical(initial), ohash=digest(initial))
    rows = store.sql("SELECT * FROM af_orx_task_experiments WHERE task_id=:task", task=ctx.session_id)
    if len(rows) != 1 or rows[0]["binding_hash"] != digest(immutable) or digest(rows[0]["binding"]) != rows[0]["binding_hash"]:
        raise OpenResearchError("BINDING_CHANGED", "Immutable task experiment source, command or connection changed")


def _observe(store: Any, ctx: RunContext, result: dict[str, Any]) -> None:
    rows = store.sql("SELECT * FROM af_orx_task_experiments WHERE task_id=:task", task=ctx.session_id)
    if len(rows) != 1:
        raise OpenResearchError("BINDING_MISSING", "The task experiment binding was not persisted")
    row = rows[0]
    if (row["owner_id"] != ctx.user_id or row["run_id"] != ctx.run_id
            or digest(row["binding"]) != row["binding_hash"]
            or digest(row["observation"]) != row["observation_hash"]):
        raise OpenResearchError("BINDING_CHANGED", "The task experiment metadata failed its integrity check")
    original = row["observation"]
    if original.get("orxRunId") is not None and original["orxRunId"] != result.get("orxRunId"):
        raise OpenResearchError("RUN_CHANGED", "The original ORX run cannot be replaced by an observed later launch")
    if original.get("status") in _TERMINAL and original.get("status") != result.get("status"):
        raise OpenResearchError("RESULT_CHANGED", "The observed original native terminal outcome is immutable")
    store.sql("""UPDATE af_orx_task_experiments SET observation=CAST(:body AS JSONB),observation_hash=:hash
        WHERE task_id=:task AND owner_id=:owner AND run_id=:run""", task=ctx.session_id, owner=ctx.user_id,
        run=ctx.run_id, body=canonical(result), hash=digest(result))


@dataclass(frozen=True)
class ResolvedExperimentBinding:
    adapter: Any = field(repr=False, compare=False)
    owner_id: str
    task_id: str
    ref: str
    version: int
    fingerprint: str
    revision: str
    capabilities: tuple[str, ...]
    contract_revision: str = "1"
    experiment_connection: dict[str, Any] | None = None


def validate_experiment_config(value: dict[str, Any]) -> None:
    if set(value) - {"scenario"} or value.get("scenario", "success") not in SCENARIOS:
        raise ValueError("Only an exact reviewed toy scenario is configurable")


def _scenario(plan: dict[str, Any]) -> str:
    runs = [spec for spec in plan.get("executionBindings", {}).get("tools", [])
            if spec.get("adapterId") == ADAPTER_ID + "-run" and spec.get("revision") in {ADAPTER_REVISION, LEAST_CAPABILITY_REVISION}]
    if len(runs) != 1:
        raise OpenResearchError("RECIPE_INVALID", "Exactly one reviewed experiment launch recipe is required")
    value = runs[0].get("config", {}).get("scenario", "success")
    if value not in SCENARIOS:
        raise OpenResearchError("RECIPE_INVALID", "The immutable plan selects an unsupported toy recipe")
    return value


def _limits(settings: Any, plan: dict[str, Any], environment: Any) -> tuple[int, float, dict[str, Any]]:
    if environment is None:
        raise OpenResearchError("ENVIRONMENT_UNAVAILABLE", "An enforceable selected environment is required")
    budget, policy = plan.get("budget", {}), plan.get("runtimePolicy", {})
    seconds = min(float(environment.timeout_seconds), float(settings.experiment_timeout_seconds),
                  float(budget.get("experimentSeconds", settings.experiment_timeout_seconds)),
                  float(policy.get("timeoutSeconds", 30)))
    output = min(environment.output_bytes, settings.experiment_output_bytes, budget.get("outputBytes", 65536))
    if not math.isfinite(seconds) or not .1 <= seconds <= 30 or type(output) is not int or output < 8192:
        raise OpenResearchError("RESOURCE_LIMIT_INVALID", "The reviewed task has invalid experiment resource bounds")
    bounds = {"timeoutSeconds": seconds, "outputBytes": output - 4096,
              "memoryBytes": environment.memory_bytes, "cpuPercent": environment.cpu_percent,
              "cpuSeconds": max(1, math.ceil(seconds * environment.cpu_percent / 100)),
              "maxProcesses": environment.process_limit}
    return output - 4096, seconds, bounds


def _validate(binding: Any, ctx: RunContext, tool_name: str = TOOL_NAMES[0]) -> ResolvedExperimentBinding:
    if not isinstance(binding, ResolvedExperimentBinding):
        raise OpenResearchError("CONNECTION_NOT_CONFIGURED", "No task-owned experiment provider is configured")
    adapter = binding.adapter
    if (binding.owner_id != ctx.user_id or binding.task_id != ctx.session_id
            or not isinstance(adapter, OpenResearchAdapter)
            or adapter.owner_id != ctx.user_id or adapter.task_id != ctx.session_id):
        raise OpenResearchError("BINDING_MISMATCH", "The actual ORX adapter belongs to another task")
    if (not binding.ref or type(binding.version) is not int or binding.version < 1
            or not _HASH.fullmatch(binding.fingerprint) or not binding.revision
            or not set(_required_caps(tool_name, binding.contract_revision)) <= set(binding.capabilities)):
        raise OpenResearchError("BINDING_INVALID", "The immutable experiment connection pin is incomplete")
    if adapter.pin != BinaryPin(REVISION, VERSION, BINARY_SHA256) or not adapter.enabled:
        raise OpenResearchError("UNVERIFIED_BINARY", "The reviewed ORX binary is required")
    for method in ("ensure_experiment", "provenance", "evaluation_result", "reclaim_experiment"):
        if not callable(getattr(adapter, method, None)):
            raise OpenResearchError("ADAPTER_INVALID", "The native experiment provider is incomplete")
    return binding


def _required_caps(tool_name: str, revision: str) -> tuple[str, ...]:
    if revision == "1":
        return READ_CAPABILITY, RUN_CAPABILITY
    if revision != "2" or tool_name not in TOOL_NAMES:
        raise OpenResearchError("CONTRACT_INVALID", "Unknown immutable experiment contract")
    return (RUN_CAPABILITY,) if tool_name in {TOOL_NAMES[1], TOOL_NAMES[3]} else (READ_CAPABILITY,)


def _plan_check(store: Any, ctx: RunContext, plan: dict[str, Any], tool_name: str, revision: str = "1") -> None:
    required = {READ_CAPABILITY} if revision == "1" else set(_required_caps(tool_name, revision))
    if tool_name not in plan.get("tools", []) or not required <= set(plan.get("capabilities", [])):
        raise PermissionError("The experiment tool is outside the immutable plan")
    if tool_name in {TOOL_NAMES[1], TOOL_NAMES[3]} and RUN_CAPABILITY not in plan.get("capabilities", []):
        raise PermissionError("Local experiment execution is outside the immutable plan")
    store.authorize_tool(ctx, tool_name)
    if store.cancellation_requested(ctx.run_id):
        raise RunCancelledException("Factory cancellation requested")


async def _resolve(resolver: Callable, ctx: RunContext, plan: dict[str, Any], tool_name: str = TOOL_NAMES[0]) -> ResolvedExperimentBinding:
    result = resolver(ctx, plan)
    return _validate(await result if inspect.isawaitable(result) else result, ctx, tool_name)


def _identity(binding: ResolvedExperimentBinding) -> tuple[Any, ...]:
    return binding.ref, binding.version, binding.fingerprint, binding.revision, binding.capabilities


def _experiment_anchor(store: Any, plan: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Provenance only: unify per-tool connections on the admitted launch pin.

    Historical receiver proof lookup grants no execution or new handle. Every
    tool still resolves its own current least-capability connection separately.
    """
    manifest = plan.get("executionBindings", {})
    if store.remote_bindings is not None:
        manifest = store.remote_bindings.historical_manifest(plan, context=ctx)
    elif plan.get("remoteHandoff"):
        raise OpenResearchError("BINDING_INVALID", "Receiver proof is unavailable")
    runs = [spec for spec in manifest.get("tools", [])
            if spec.get("adapterId") == ADAPTER_ID + "-run" and spec.get("revision") == "2"]
    if len(runs) != 1:
        raise OpenResearchError("BINDING_INVALID", "Exactly one admitted revision-2 launch pin is required")
    pin = runs[0].get("connection", {})
    if set(pin.get("capabilities", [])) != {RUN_CAPABILITY}:
        raise OpenResearchError("BINDING_INVALID", "Revision-2 launch requires a compute-only connection")
    return {key: sorted(pin[key]) if key == "capabilities" else pin[key]
            for key in ("ref", "version", "fingerprint", "revision", "capabilities")}


def _request(plan: dict[str, Any], ctx: RunContext, binding: ResolvedExperimentBinding) -> dict[str, Any]:
    source = binding.adapter.provenance()
    if not isinstance(source, dict):
        raise OpenResearchError("PROVENANCE_INVALID", "Reviewed experiment provenance is unavailable")
    return {"ownerId": ctx.user_id, "taskId": ctx.session_id, "nativeRunId": ctx.run_id,
            "planId": plan["id"], "planFingerprint": plan.get("fingerprint"),
            "materialRefs": plan.get("materialRefs", []),
            "connection": (binding.experiment_connection if binding.contract_revision == "2" else
                           {"ref": binding.ref, "version": binding.version,
                            "fingerprint": binding.fingerprint, "revision": binding.revision,
                            "capabilities": sorted(binding.capabilities)}),
            "provenance": source}


def _public_result(plan: dict[str, Any], ctx: RunContext, binding: ResolvedExperimentBinding,
                   receipt: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    native = binding.adapter._bound()
    evaluation = binding.adapter.evaluation_result() if receipt.get("state") in {"done", "failed"} else None
    if inspect.isawaitable(evaluation):
        raise OpenResearchError("ADAPTER_INVALID", "Result inspection must be local and synchronous")
    provenance = binding.adapter.provenance()
    if isinstance(evaluation, dict) and isinstance(evaluation.get("resultSha256"), str):
        provenance = {**provenance, "resultSha256": evaluation["resultSha256"]}
    return {"schema": 1, "evidenceKind": "toy_local_evaluation", "taskId": ctx.session_id,
            "planId": plan["id"], "nativeRunId": ctx.run_id, "effectFingerprint": fingerprint,
            "projectId": native.project_id, "experimentId": native.experiment_id,
            "orxRunId": receipt.get("run_id"), "status": receipt.get("state", "UNKNOWN"),
            "launchIntent": {"state": receipt.get("state", "UNKNOWN"),
                             "acknowledgement": "observed_native_run" if receipt.get("run_id") else "unknown",
                             "previousRunId": receipt.get("previous_run_id")},
            "provenance": provenance, "evaluation": evaluation,
            "stopEvidence": receipt.get("stop_evidence", receipt.get("stopEvidence")),
            "sourceVerified": True, "scopeVerified": True,
            "notice": "Deterministic local toy evaluation; no live model research is established."}


def _persist_source(store: Any, ctx: RunContext, binding: ResolvedExperimentBinding,
                    result: dict[str, Any]) -> dict[str, Any]:
    fingerprint = result["effectFingerprint"]
    expected = result["provenance"]["sourceArchiveSha256"]
    name = "orx-toy-source-" + fingerprint[:24] + ".tar"
    for row in store.artifacts(ctx.session_id):
        if row.get("name") == name and row.get("provenance", {}).get("effectFingerprint") == fingerprint:
            _, raw = store.artifact(ctx.session_id, row["id"])
            if hashlib.sha256(raw).hexdigest() != expected or row["sha256"] != expected:
                raise OpenResearchError("SOURCE_CHANGED", "The sealed original evaluator archive failed its SHA-256 check")
            return row
    raw = binding.adapter.source_archive_bytes()
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != expected:
        raise OpenResearchError("SOURCE_CHANGED", "The sealed original evaluator archive differs from the reviewed source")
    return store.artifact_write(ctx.run_id, name, raw, "application/x-tar",
        {**result["provenance"], "effectFingerprint": fingerprint,
         "evidenceKind": "original_reviewed_toy_source", "taskId": ctx.session_id,
         "nativeRunId": ctx.run_id, "orxRunId": result["orxRunId"]})


def _persist_result(store: Any, ctx: RunContext, result: dict[str, Any],
                    binding: ResolvedExperimentBinding) -> dict[str, Any]:
    with store.transaction():
        store.sql("SELECT pg_advisory_xact_lock(hashtext(:key))", key="orx-evidence:" + ctx.session_id)
        return _persist_result_locked(store, ctx, result, binding)


def _persist_result_locked(store: Any, ctx: RunContext, result: dict[str, Any],
                           binding: ResolvedExperimentBinding) -> dict[str, Any]:
    source = _persist_source(store, ctx, binding, result)
    result = {**result, "sourceArtifactId": source["id"], "sourceArtifactSha256": source["sha256"]}
    fingerprint = result["effectFingerprint"]
    name = "orx-toy-evaluation-" + fingerprint[:24] + ".json"
    for row in store.artifacts(ctx.session_id):
        if row.get("name") == name and row.get("provenance", {}).get("effectFingerprint") == fingerprint:
            _, raw = store.artifact(ctx.session_id, row["id"])
            previous = json.loads(raw)
            if previous.get("result") != result:
                raise OpenResearchError("RESULT_CHANGED", "A terminal experiment result changed after persistence")
            return {**result, "artifactId": row["id"], "artifactSha256": row["sha256"]}
    content = json.dumps({"schema": 1, "result": result}, ensure_ascii=False, sort_keys=True)
    artifact = store.artifact_write(ctx.run_id, name, content, "application/json",
        {**result["provenance"], "effectFingerprint": fingerprint, "evidenceKind": "toy_local_evaluation",
         "taskId": ctx.session_id, "nativeRunId": ctx.run_id, "orxRunId": result["orxRunId"]})
    return {**result, "artifactId": artifact["id"], "artifactSha256": artifact["sha256"]}


def _record_held_reclaim(store: Any, ctx: RunContext, plan: dict[str, Any],
                          binding: ResolvedExperimentBinding, receipt: dict[str, Any]) -> dict[str, Any]:
    result = _public_result(plan, ctx, binding, receipt, digest(_request(plan, ctx, binding)))
    proof = result.get("stopEvidence")
    if result["status"] not in _TERMINAL or not isinstance(proof, dict) or proof.get("allStopped") is not True:
        # Persist positive kernel observations even if native metadata remains
        # unresolved, while holding UNKNOWN and never fabricating a run state.
        result["sourceVerified"] = not bool(receipt.get("cleanupNativeStatusPending"))
        _observe(store, ctx, result)
        store.event(ctx.run_id, "orx_cleanup_unconfirmed", "Original process-stop observations retained while native effect reconciliation is unresolved", result)
        raise OpenResearchError("CLEANUP_UNCONFIRMED", "Original ORX native outcome or process stop remains unresolved")
    if result["status"] == "cancelled":
        result["cancelled"] = True
    rows = [row for row in store.effects(ctx.session_id) if row.get("effect_key") == ctx.run_id + ":" + LAUNCH_EFFECT_KEY]
    if len(rows) != 1:
        raise OpenResearchError("INVALID_EFFECT", "The original owned launch effect is missing or ambiguous")
    old = rows[0].get("result")
    if rows[0]["status"] in {"DONE", "CANCELLED"} and isinstance(old, dict):
        result = {**old, "stopEvidence": result["stopEvidence"]}
    else:
        result = _persist_result(store, ctx, result, binding)
    store.effect_complete(ctx.run_id, LAUNCH_EFFECT_KEY, result)
    _observe(store, ctx, result)
    store.event(ctx.run_id, "orx_experiment_reclaimed", "Trusted cleanup confirmed only the original task-owned native process tree", result)
    return result


async def _operation(store: Any, ctx: RunContext, plan: dict[str, Any], binding: ResolvedExperimentBinding,
                     resolver: Callable, tool_name: str, coroutine: Any, *, deadline: float) -> Any:
    operation = asyncio.create_task(coroutine)
    started = asyncio.get_running_loop().time()
    try:
        while True:
            done, _ = await asyncio.wait({operation}, timeout=.2)
            if done:
                value = await operation
                await asyncio.to_thread(_plan_check, store, ctx, plan, tool_name, binding.contract_revision)
                current = await _resolve(resolver, ctx, plan, tool_name)
                if _identity(current) != _identity(binding):
                    raise PermissionError("The task experiment connection changed during execution")
                return value
            await asyncio.to_thread(_plan_check, store, ctx, plan, tool_name, binding.contract_revision)
            current = await _resolve(resolver, ctx, plan, tool_name)
            if _identity(current) != _identity(binding):
                raise PermissionError("The task experiment connection changed during execution")
            if asyncio.get_running_loop().time() - started > deadline:
                raise OpenResearchError("TIMEOUT", "The selected task environment deadline expired")
    except BaseException:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        # Independent cleanup authority owns this exact immutable task scope;
        # ordinary revoked connection/tool authority is never enlarged.
        receipt = await binding.adapter.reclaim_experiment()
        _record_held_reclaim(store, ctx, plan, binding, receipt)
        raise


def make_orx_experiment_tools(settings: Any, store: Any, resolver: Callable, contract_revision: str = "1") -> dict[str, Any]:
    async def prepare(ctx: RunContext, tool_name: str, *, allow_completed=False) -> tuple[dict[str, Any], ResolvedExperimentBinding]:
        plan = store.resolve_run(ctx)
        await asyncio.to_thread(_plan_check, store, ctx, plan, tool_name, contract_revision)
        binding = await _resolve(resolver, ctx, plan, tool_name)
        if (allow_completed and os.name == "posix" and binding.contract_revision == "2"
                and any(e["effect_key"] == ctx.run_id + ":" + LAUNCH_EFFECT_KEY and e["status"] == "DONE"
                        for e in store.effects(ctx.session_id))):
            return plan, binding
        await binding.adapter.ensure_experiment()
        _record_binding(store, plan, ctx, binding)
        return plan, binding

    async def settle(ctx: RunContext, plan: dict[str, Any], binding: ResolvedExperimentBinding,
                     receipt: dict[str, Any]) -> dict[str, Any]:
        request = _request(plan, ctx, binding)
        result = _public_result(plan, ctx, binding, receipt, digest(request))
        if result["status"] in _TERMINAL:
            if not isinstance(result.get("stopEvidence"), dict) or result["stopEvidence"].get("allStopped") is not True:
                _observe(store, ctx, result)
                raise OpenResearchError("CLEANUP_UNCONFIRMED", "Native terminal outcome lacks positive process-stop evidence")
            if result["status"] == "cancelled":
                result["cancelled"] = True
            result = _persist_result(store, ctx, result, binding)
            _observe(store, ctx, result)
            store.effect_complete(ctx.run_id, LAUNCH_EFFECT_KEY, result)
            store.event(ctx.run_id, "experiment_failed" if result["status"] == "failed" else "orx_experiment_" + result["status"],
                "Reviewed task-owned ORX toy experiment reached its observed native terminal state", result)
        else:
            _observe(store, ctx, result)
        store.event(ctx.run_id, "orx_experiment_observed", "Observed the original task-owned ORX launch without retry", result)
        return result

    async def orx_experiment_inspect(run_context: RunContext) -> str:
        plan, binding = await prepare(run_context, TOOL_NAMES[0])
        try:
            receipt = await binding.adapter.reconcile_experiment()
        except OpenResearchError as error:
            if error.code != "NO_LAUNCH_INTENT":
                raise
            status = await binding.adapter.experiment_status()
            receipt = {"state": status["status"], "run_id": status["run_id"]}
        result = _public_result(plan, run_context, binding, receipt, digest(_request(plan, run_context, binding)))
        _observe(store, run_context, result)
        store.event(run_context.run_id, "orx_experiment_inspected", "Verified the reviewed task-owned native ORX experiment before launch confirmation", result)
        return json.dumps(result, sort_keys=True)

    async def orx_experiment_run(run_context: RunContext) -> str:
        plan, binding = await prepare(run_context, TOOL_NAMES[1], allow_completed=True)
        completed = await completed_evidence(run_context, plan, binding, TOOL_NAMES[1])
        if completed is not None:
            return json.dumps(completed[0], sort_keys=True)
        request = _request(plan, run_context, binding)
        with store.transaction():
            reservation = store.effect_reserve(run_context.run_id, LAUNCH_EFFECT_KEY, request)
            if reservation["status"] == "new":
                _observe(store, run_context, _public_result(plan, run_context, binding,
                    {"state": "UNKNOWN", "run_id": None}, digest(request)))
        if reservation["status"] == "done":
            return json.dumps(reservation["result"], sort_keys=True)
        store.event(run_context.run_id, "orx_experiment_launch_intent", "Durable native experiment launch intent; unresolved intent is never replayed",
                    {"effectFingerprint": digest(request), "newIntent": reservation["status"] == "new"})
        if reservation["status"] == "unknown":
            try:
                receipt = await binding.adapter.reconcile_experiment()
            except OpenResearchError as error:
                raise OpenResearchError("UNKNOWN_EFFECT", "Persisted experiment launch requires reconciliation; automatic replay refused") from error
        else:
            # Revision 2 contains multiple bounded CLI commands plus current
            # origin/receiver checks. Use the admitted environment's total
            # window, not one command's timeout; revision 1 is unchanged.
            deadline = float(binding.adapter.command_timeout) + 5
            if binding.contract_revision == "2":
                deadline = float(request["provenance"]["environment"]["timeoutSeconds"])
            receipt = await _operation(store, run_context, plan, binding, resolver, TOOL_NAMES[1],
                binding.adapter.launch_experiment(), deadline=deadline)
        return json.dumps(await settle(run_context, plan, binding, receipt), sort_keys=True)

    async def completed_evidence(run_context, plan, binding, tool_name):
        # A recovered native transcript may still ask to wait after the
        # observer sealed the original outcome. Verify it read-only instead
        # of starting a CLI in an already stopped, deadline-bound namespace.
        if os.name == "posix" and binding.contract_revision == "2":
            completed = next((e for e in store.effects(run_context.session_id)
                if e["effect_key"] == run_context.run_id + ":" + LAUNCH_EFFECT_KEY
                and e["status"] == "DONE"), None)
            if completed is not None:
                original = original_experiment_binding(settings, store, run_context.session_id)
                if original is None:
                    raise PermissionError("Original completed experiment binding is missing")
                original_binding = original[3]
                receipt = original_binding.adapter.observe_existing()
                result = _public_result(plan, run_context, original_binding, receipt,
                    digest(_request(plan, run_context, original_binding)))
                saved = completed["result"]
                if (result["status"] not in _TERMINAL or result.get("stopEvidence", {}).get("allStopped") is not True
                        or any(result.get(key) != saved.get(key) for key in
                            ("taskId", "planId", "nativeRunId", "orxRunId", "effectFingerprint", "status"))
                        or result["effectFingerprint"] != digest(_request(plan, run_context, binding))):
                    raise PermissionError("Original completed experiment evidence differs")
                await asyncio.to_thread(_plan_check, store, run_context, plan, tool_name, binding.contract_revision)
                current_binding = await _resolve(resolver, run_context, plan, tool_name)
                if _identity(current_binding) != _identity(binding):
                    raise PermissionError("The task experiment connection changed during observation")
                return saved, original_binding.adapter
        return None

    async def orx_experiment_wait(run_context: RunContext, timeout_seconds: int = 10) -> str:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise ValueError("Wait timeout must be an integer between 1 and 30 seconds")
        plan, binding = await prepare(run_context, TOOL_NAMES[2], allow_completed=True)
        completed = await completed_evidence(run_context, plan, binding, TOOL_NAMES[2])
        if completed is not None:
            return json.dumps(completed[0], sort_keys=True)
        receipt = await _operation(store, run_context, plan, binding, resolver, TOOL_NAMES[2],
            binding.adapter.wait_experiment(timeout_seconds=timeout_seconds), deadline=timeout_seconds + 5)
        return json.dumps(await settle(run_context, plan, binding, receipt), sort_keys=True)

    async def orx_experiment_cancel(run_context: RunContext) -> str:
        plan, binding = await prepare(run_context, TOOL_NAMES[3])
        receipt = await binding.adapter.cancel_experiment(timeout_seconds=10)
        return json.dumps(await settle(run_context, plan, binding, receipt), sort_keys=True)

    async def orx_experiment_logs(run_context: RunContext) -> str:
        plan, binding = await prepare(run_context, TOOL_NAMES[4], allow_completed=True)
        completed = await completed_evidence(run_context, plan, binding, TOOL_NAMES[4])
        logs = (completed[1].read_completed_logs() if completed is not None
                else await binding.adapter.run_logs())
        current = await _resolve(resolver, run_context, plan)
        if _identity(current) != _identity(binding):
            raise PermissionError("The task experiment connection changed during log inspection")
        return json.dumps({"stdout": logs.stdout, "stdoutSha256": logs.stdout_sha256,
                           "evidenceKind": "toy_local_evaluation", "taskId": run_context.session_id}, sort_keys=True)

    return {function.__name__: function for function in (orx_experiment_inspect, orx_experiment_run,
            orx_experiment_wait, orx_experiment_cancel, orx_experiment_logs)}


def register_orx_experiment_adapters(bindings: Any) -> list[Any]:
    registrations = []
    for contract_revision, tool_name in ((revision, name) for revision in ("1", "2") for name in TOOL_NAMES):
        required = _required_caps(tool_name, contract_revision)

        def factory(context: Any, selected=tool_name, revision=contract_revision, required=required):
            pin = context.spec.get("connection")
            handle = context.connection
            if not isinstance(pin, dict) or not callable(getattr(handle, "create_experiment_adapter", None)):
                raise OpenResearchError("CONNECTION_NOT_CONFIGURED", "A trusted task-owned experiment provider is required")
            owner, task_id = context.run_context.user_id, context.run_context.session_id
            scope = (Path(context.settings.workspace).resolve() / "orx-tasks" /
                     hashlib.sha256(owner.encode()).hexdigest()[:24] / task_id)
            initial = {key: pin[key] for key in ("ref", "version", "fingerprint", "revision", "capabilities")}
            if revision == "2" and set(initial["capabilities"]) != set(required):
                raise OpenResearchError("BINDING_INVALID", "Revision-2 tools require an exact least-capability connection")
            adapter = None

            def resolve_sync(ctx: RunContext, plan: dict[str, Any]) -> ResolvedExperimentBinding:
                nonlocal adapter
                if (ctx.user_id != owner or ctx.session_id != task_id or ctx.run_id != context.run_context.run_id
                        or plan["id"] != context.plan["id"] or plan.get("fingerprint") != context.plan.get("fingerprint")):
                    raise OpenResearchError("BINDING_MISMATCH", "The retained experiment callable belongs to another task")
                current = context.store.connections.resolve(owner, initial["ref"], "orx",
                    expected_revision=initial["revision"], expected_fingerprint=initial["fingerprint"],
                    expected_version=initial["version"], expected_adapter_ref=ADAPTER_ID,
                    required_capabilities=required, task_id=task_id)
                if current is not handle:
                    raise OpenResearchError("CONNECTION_CHANGED", "The exact task experiment provider changed")
                environment = bindings.environment_limits(plan, ctx)
                output, timeout, bounds = _limits(context.settings, plan, environment)

                def authorize_sync(_operation: str):
                    _plan_check(context.store, ctx, plan, selected, revision)
                    latest = context.store.connections.resolve(owner, initial["ref"], "orx",
                        expected_revision=initial["revision"], expected_fingerprint=initial["fingerprint"],
                        expected_version=initial["version"], expected_adapter_ref=ADAPTER_ID,
                        required_capabilities=required, task_id=task_id)
                    if latest is not handle:
                        raise OpenResearchError("CONNECTION_CHANGED", "The exact task experiment provider changed")

                async def authorize(operation: str):
                    await asyncio.to_thread(authorize_sync, operation)
                    if context.store.cancellation_requested(ctx.run_id):
                        raise RunCancelledException("Factory cancellation requested")

                if adapter is None:
                    scenario = _scenario(plan)
                    if context.spec.get("config", {}).get("scenario", scenario) != scenario:
                        raise OpenResearchError("RECIPE_INVALID", "Selected experiment tools disagree about the reviewed task recipe")
                    adapter = handle.create_experiment_adapter(owner_id=owner, task_id=task_id, scope=scope,
                        authorize=authorize, pin=BinaryPin(REVISION, VERSION, BINARY_SHA256),
                        max_output_bytes=output, command_timeout=min(timeout, 15), environment=bounds,
                        scenario=scenario)
                if adapter.max_output_bytes > output or adapter.command_timeout > timeout:
                    raise OpenResearchError("RESOURCE_LIMIT_EXCEEDED", "The task experiment adapter exceeds its current selected environment")
                anchor = _experiment_anchor(context.store, plan, ctx) if revision == "2" else None
                return ResolvedExperimentBinding(adapter, owner, task_id, initial["ref"], initial["version"],
                    initial["fingerprint"], initial["revision"], tuple(initial["capabilities"]), revision, anchor)

            async def resolve(ctx: RunContext, plan: dict[str, Any]) -> ResolvedExperimentBinding:
                return await asyncio.to_thread(resolve_sync, ctx, plan)

            function = make_orx_experiment_tools(context.settings, context.store, resolve, revision)[selected]
            return tool(requires_confirmation=True)(function) if selected == TOOL_NAMES[1] else function

        registrations.append(bindings.register("tool", ADAPTER_ID + "-" + tool_name.rsplit("_", 1)[1],
            contract_revision, factory, tool_name=tool_name, connection_kind="orx",
            connection_adapter_ref=ADAPTER_ID,
            required_capabilities=required,
            permissions=(RUN_CAPABILITY,) if tool_name in {TOOL_NAMES[1], TOOL_NAMES[3]} else (READ_CAPABILITY,),
            validator=validate_experiment_config))
    return registrations


def inspect_owned_orx_experiment(store: Any, task_id: str) -> dict[str, Any] | None:
    """Read a durable projection; HTTP caller must enforce ordinary read access.

    This never launches, provisions, resolves a credential or assumes that a
    missing supervisor is stopped. Active projections are explicitly stale.
    """
    task = store.task(task_id)
    exact = (task.get("run_id") or "") + ":" + LAUNCH_EFFECT_KEY
    rows = [row for row in store.effects(task_id) if row.get("effect_key") == exact]
    if not rows:
        return None
    if len(rows) != 1:
        raise OpenResearchError("INVALID_EFFECT", "The original task launch effect is ambiguous")
    result = rows[0].get("result")
    if not isinstance(result, dict):
        events = [event for event in store.events(task_id) if event.get("type") == "orx_experiment_observed"]
        result = events[-1].get("data") if events else None
    if not isinstance(result, dict):
        return {"schema": 1, "evidenceKind": "toy_local_evaluation", "taskId": task_id,
                "nativeRunId": task.get("run_id"), "status": "UNKNOWN", "orxRunId": None,
                "launchIntent": {"state": "UNKNOWN", "acknowledgement": "unknown"},
                "observationSource": "durable_factory_intent", "liveObservation": False}
    if (result.get("taskId") != task_id or result.get("nativeRunId") != task.get("run_id")
            or result.get("planId") != task.get("plan_id") or result.get("evidenceKind") != "toy_local_evaluation"):
        raise OpenResearchError("INVALID_EFFECT", "The observed ORX effect belongs to another native task")
    return {**result, "observationSource": "durable_factory_effect" if rows[0]["status"] != "UNKNOWN"
            else "durable_factory_observation", "liveObservation": False}


def inspect_orx_experiment(store: Any, owner: str, task_id: str) -> dict[str, Any] | None:
    """Read only an exact owner-scoped, integrity-checked persisted observation."""
    task = store.task(task_id, owner)
    rows = store.sql("SELECT * FROM af_orx_task_experiments WHERE task_id=:task AND owner_id=:owner",
                     task=task_id, owner=owner)
    if not rows:
        return None
    row = rows[0]
    binding, observation = row["binding"], row["observation"]
    if (len(rows) != 1 or digest(binding) != row["binding_hash"] or digest(observation) != row["observation_hash"]
            or row["plan_id"] != task["plan_id"] or row["run_id"] != task.get("run_id")
            or binding.get("ownerId") != owner or binding.get("taskId") != task_id
            or observation.get("taskId") != task_id or observation.get("nativeRunId") != row["run_id"]
            or observation.get("planId") != row["plan_id"] or observation.get("effectFingerprint") != digest({
                key: value for key, value in binding.items() if key not in {"projectId", "experimentId"}})
            or observation.get("projectId") != binding.get("projectId")
            or observation.get("experimentId") != binding.get("experimentId")):
        raise OpenResearchError("BINDING_CHANGED", "The persisted task experiment observation failed its exact identity check")
    return {**observation, "observationSource": "durable_factory_observation", "liveObservation": False}


def original_experiment_binding(settings: Any, store: Any, task_id: str) -> tuple[Any, ...] | None:
    """Trusted lifecycle cleanup of an existing scope after revocation/restart.

    No ordinary connection resolution or current run permission is required.
    Exact historic owner/connection metadata and operator handle identity are
    still mandatory. This path calls only adapter.reclaim_experiment: never
    ensure/create/run/wake, and it never restores a launch budget.
    """
    task = store.task(task_id)
    if not task.get("run_id"):
        return None
    exact = task["run_id"] + ":" + LAUNCH_EFFECT_KEY
    effects = [row for row in store.effects(task_id) if row.get("effect_key") == exact]
    if not effects:
        return None
    plan = store.plan(task["plan_id"], task["owner_id"])
    specs = [spec for spec in plan.get("executionBindings", {}).get("tools", [])
             if spec.get("adapterId") == ADAPTER_ID + "-run" and spec.get("revision") in {ADAPTER_REVISION, LEAST_CAPABILITY_REVISION}]
    if len(specs) != 1:
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "No exact immutable native experiment launch binding exists")
    spec = specs[0]
    ctx = RunContext(user_id=task["owner_id"], session_id=task_id, run_id=task["run_id"])
    if store.remote_bindings is not None:
        spec = store.remote_bindings.historical_spec(plan, "tool", spec, ctx)
    elif plan.get("remoteHandoff"):
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "The original receiver proof registry is unavailable")
    if spec.get("adapterId") != ADAPTER_ID + "-run" or spec.get("revision") not in {ADAPTER_REVISION, LEAST_CAPABILITY_REVISION}:
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "The admitted receiver adapter cannot reclaim this experiment")
    pin = spec.get("connection", {})
    service = store.connections
    if service is None:
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "The original trusted connection registry is unavailable")
    handle = service.cleanup_handle(task["owner_id"], pin, adapter_ref=ADAPTER_ID, task_id=task_id)
    if not callable(getattr(handle, "create_experiment_adapter", None)):
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "The original task-scoped cleanup handle is unavailable")
    owner = task["owner_id"]
    scope = (Path(settings.workspace).resolve() / "orx-tasks" / hashlib.sha256(owner.encode()).hexdigest()[:24] / task_id)
    if not scope.is_dir():
        raise OpenResearchError("CLEANUP_UNCONFIRMED", "The original task experiment scope is missing")

    def deny_new_execution(_operation: str):
        raise PermissionError("Trusted cleanup never grants new experiment execution")

    rows = store.sql("SELECT * FROM af_orx_task_experiments WHERE task_id=:task AND owner_id=:owner", task=task_id, owner=owner)
    if len(rows) != 1 or digest(rows[0]["binding"]) != rows[0]["binding_hash"]:
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "The original admitted task experiment binding is unavailable")
    original = rows[0]["binding"]
    environment = original.get("provenance", {}).get("environment")
    if not isinstance(environment, dict) or original.get("nativeRunId") != task["run_id"]:
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "The original admitted environment bounds are unavailable")
    adapter = handle.create_experiment_adapter(owner_id=owner, task_id=task_id, scope=scope,
        authorize=deny_new_execution, pin=BinaryPin(REVISION, VERSION, BINARY_SHA256),
        max_output_bytes=environment["outputBytes"], command_timeout=min(environment["timeoutSeconds"], 15),
        environment=environment, scenario=spec.get("config", {}).get("scenario", "success"), cleanup_only=True)
    binding = _validate(ResolvedExperimentBinding(adapter, owner, task_id, pin["ref"], pin["version"],
        pin["fingerprint"], pin["revision"], tuple(pin["capabilities"]), spec["revision"],
        _experiment_anchor(store, plan, ctx) if spec["revision"] == "2" else None),
        RunContext(user_id=owner, session_id=task_id, run_id=task["run_id"]), TOOL_NAMES[1])
    return task, plan, ctx, binding


async def reclaim_orx_experiment(settings: Any, store: Any, task_id: str) -> dict[str, Any] | None:
    original = original_experiment_binding(settings, store, task_id)
    if original is None:
        return None
    task, plan, ctx, binding = original
    adapter = binding.adapter
    owner = task["owner_id"]
    receipt = await adapter.reclaim_experiment()
    if receipt.get("state") == "NO_LAUNCH_INTENT":
        # Factory's persisted intent can precede native receipt admission.
        # Absence grants no terminal proof and must never authorize retry.
        raise OpenResearchError("CLEANUP_UNCONFIRMED", "No native stop proof exists for the original launch intent")
    previous = inspect_orx_experiment(store, owner, task_id)
    fingerprint = previous.get("effectFingerprint") if previous else None
    if not isinstance(fingerprint, str) or not _HASH.fullmatch(fingerprint):
        request = _request(plan, RunContext(user_id=owner, session_id=task_id, run_id=task["run_id"]), binding)
        fingerprint = digest(request)
    ctx = RunContext(user_id=owner, session_id=task_id, run_id=task["run_id"])
    if fingerprint != digest(_request(plan, ctx, binding)):
        raise OpenResearchError("RECLAIM_BINDING_INVALID", "The original effect fingerprint differs from its admitted binding")
    try:
        return _record_held_reclaim(store, ctx, plan, binding, receipt)
    except OpenResearchError as error:
        # Corrupted source cannot become a successful result or release an
        # UNKNOWN effect. Still retain positive kernel stop proof for operators.
        proof = receipt.get("stop_evidence")
        if isinstance(proof, dict) and proof.get("allStopped") is True:
            store.event(task_id, "orx_cleanup_source_unverified", "Original process tree stopped; source/result reconciliation remains held",
                {"nativeRunId": task["run_id"], "orxRunId": receipt.get("run_id"),
                 "effectFingerprint": fingerprint, "stopEvidence": proof, "errorCode": error.code,
                 "sourceVerified": False, "capacityReleased": False})
        raise


@dataclass
class LocalORXWorkflowModel(Model):
    """Deterministic no-provider orchestration over the exact approved native tools."""
    id: str = "factory-local-orx-workflow-v1"
    name: str = "Deterministic ORX toy workflow"
    provider: str = "local-deterministic"

    def _response(self, messages: Any) -> ModelResponse:
        system = next((str(message.content) for message in messages if message.role == "system"), "")
        encoded = next((line.split(CONTEXT_MARKER, 1)[1] for line in reversed(system.splitlines())
                        if CONTEXT_MARKER in line), "{}")
        plan = json.loads(encoded)
        latest: dict[str, Any] = {}
        failures = []
        for message in messages:
            if message.role != "tool":
                continue
            if message.tool_call_error:
                failures.append(str(message.content))
            try:
                latest[message.tool_name] = json.loads(message.content)
            except (TypeError, ValueError):
                failures.append("The approved experiment tool returned invalid JSON")
        if failures:
            return ModelResponse(role="assistant", content=json.dumps({"status": "failed", "errors": failures,
                "evidenceKind": "toy_local_evaluation", "notice": "No provider was called."}))

        def call(name: str, arguments: dict[str, Any]) -> ModelResponse:
            if name not in plan.get("tools", []):
                return ModelResponse(role="assistant", content=json.dumps({"status": "failed", "errors": ["Required reviewed workflow tool is unavailable"]}))
            count = sum(1 for message in messages if message.role == "tool")
            return ModelResponse(role="assistant", tool_calls=[{"id": "orx-local-" + str(count) + "-" + name,
                "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}])

        if TOOL_NAMES[0] not in latest:
            return call(TOOL_NAMES[0], {})
        if TOOL_NAMES[1] not in latest:
            return call(TOOL_NAMES[1], {})
        outcome = latest.get(TOOL_NAMES[2], latest[TOOL_NAMES[1]])
        if outcome.get("status") == "UNKNOWN" or not outcome.get("orxRunId"):
            return ModelResponse(role="assistant", content=json.dumps({"status": "blocked-unknown",
                "evidenceKind": "toy_local_evaluation", "result": outcome,
                "notice": "The original launch acknowledgement requires reconciliation; no launch was retried."}))
        if outcome.get("status") not in _TERMINAL:
            return call(TOOL_NAMES[2], {"timeout_seconds": 10})
        if TOOL_NAMES[4] not in latest:
            return call(TOOL_NAMES[4], {})
        return ModelResponse(role="assistant", content=json.dumps({"status": outcome["status"],
            "evidenceKind": "toy_local_evaluation", "modelId": self.id, "result": outcome,
            "notice": "Deterministic local toy evaluation; no paid model or live research was used."}, sort_keys=True))

    def invoke(self, messages, **kwargs):
        return self._response(messages)

    async def ainvoke(self, messages, **kwargs):
        return self._response(messages)

    def invoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response

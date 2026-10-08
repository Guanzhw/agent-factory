"""Plan-bound, read-only OpenResearch discovery tools.

The runtime must supply a trusted resolver built from ExecutionBindings and
ConnectionService. Catalog text never constructs an adapter or grants access.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from agno.exceptions import RunCancelledException
from agno.run import RunContext

from .openresearch import BinaryPin, OpenResearchAdapter, OpenResearchError, REVISION, VERSION
from .store import digest

TOOL_NAME = "orx_discover"
CAPABILITY = "research:read"
_CORPORA = frozenset({"keyword", "openalex", "biorxiv", "pubmed"})
_AUTHORITY_POLL_SECONDS = 0.25
_WRAPPER_RESERVE_BYTES = 4096
_MAX_COMMAND_SECONDS = 15
_APPROVED_BINARY_SHA256 = "d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7"
ORX_ADAPTER_ID = "openresearch-discover-v1"
ORX_ADAPTER_REVISION = "1"


class TaskORXAdapterProvider(Protocol):
    """Operator-installed factory held only as a trusted connection handle.

    Implementations create adapters for one canonical Factory task, using the
    supplied private scope and hard ceilings. They must not accept user URLs,
    commands, credentials, or paths from material configuration.
    """

    def create_adapter(self, *, owner_id: str, task_id: str, scope: Path,
                       authorize: Callable[[str], Any], pin: BinaryPin,
                       max_output_bytes: int, command_timeout: float) -> OpenResearchAdapter: ...


@dataclass(frozen=True)
class ResolvedORXBinding:
    """Opaque adapter plus redacted, current connection identity.

    Construct this only inside the trusted runtime binding factory after
    ConnectionService has revalidated the exact plan pin. The adapter contains
    the task-local private handle; this record intentionally carries metadata
    only.
    """

    adapter: Any = field(repr=False, compare=False)
    owner_id: str
    task_id: str
    ref: str
    # Owner connection-reference version (an integer), distinct from the
    # reviewed OpenResearch source/binary version carried by BinaryPin.
    version: int
    fingerprint: str
    revision: str
    capabilities: tuple[str, ...]


def _check_plan(store: Any, ctx: RunContext, plan: dict[str, Any]) -> None:
    """Fail closed on plan/tool/capability drift before resolving a handle."""
    if not isinstance(plan, dict) or not isinstance(plan.get("tools"), list):
        raise OpenResearchError("PLAN_SCOPE_INVALID", "The current immutable plan is unavailable")
    if TOOL_NAME not in plan["tools"]:
        raise PermissionError("ORX discovery is outside the immutable task plan")
    if CAPABILITY not in plan.get("capabilities", []):
        raise PermissionError("The immutable plan does not grant research:read")
    store.authorize_tool(ctx, TOOL_NAME)


def _validate_binding(binding: Any, ctx: Any) -> ResolvedORXBinding:
    if not isinstance(binding, ResolvedORXBinding):
        raise OpenResearchError("CONNECTION_NOT_CONFIGURED", "No trusted OpenResearch connection is configured for this task")
    adapter = binding.adapter
    if (binding.owner_id != ctx.user_id or binding.task_id != ctx.session_id
            or getattr(adapter, "owner_id", None) != ctx.user_id
            or getattr(adapter, "task_id", None) != ctx.session_id):
        raise OpenResearchError("BINDING_MISMATCH", "OpenResearch connection is not bound to the current user and task")
    if (not binding.ref or type(binding.version) is not int or binding.version < 1 or not binding.revision
            or not re.fullmatch(r"[0-9a-f]{64}", binding.fingerprint)
            or CAPABILITY not in binding.capabilities):
        raise OpenResearchError("BINDING_INVALID", "OpenResearch connection pin is incomplete")
    pin = _verified_pin(adapter)
    if (pin.revision != REVISION or pin.version != VERSION
            or pin.sha256 != _APPROVED_BINARY_SHA256
            or getattr(adapter, "enabled", False) is not True):
        raise OpenResearchError("UNVERIFIED_BINARY", "The task connection does not carry the reviewed OpenResearch build")
    return binding


def _verified_pin(adapter: Any) -> BinaryPin:
    pin = adapter.pin
    if not isinstance(pin, BinaryPin):
        raise OpenResearchError("UNVERIFIED_BINARY", "The task connection has no approved OpenResearch binary pin")
    return pin


def _effective_limits(settings: Any, plan: dict[str, Any], environment: Any = None) -> tuple[int, float]:
    raw_budget = plan.get("budget")
    raw_policy = plan.get("runtimePolicy")
    budget: dict[str, Any] = raw_budget if isinstance(raw_budget, dict) else {}
    policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    setting_bytes = int(getattr(settings, "experiment_output_bytes", 65536))
    plan_bytes = budget.get("outputBytes", setting_bytes)
    policy_seconds = policy.get("timeoutSeconds", _MAX_COMMAND_SECONDS)
    task_seconds = budget.get("experimentSeconds", getattr(settings, "experiment_timeout_seconds", _MAX_COMMAND_SECONDS))
    if type(policy_seconds) not in (int, float) or type(task_seconds) not in (int, float):
        raise OpenResearchError("RESOURCE_LIMIT_INVALID", "The plan has invalid OpenResearch runtime bounds")
    plan_seconds = float(min(policy_seconds, task_seconds))
    setting_seconds = getattr(settings, "orx_command_timeout_seconds",
                              getattr(settings, "experiment_timeout_seconds", _MAX_COMMAND_SECONDS))
    if type(plan_bytes) is not int or type(setting_seconds) not in (int, float):
        raise OpenResearchError("RESOURCE_LIMIT_INVALID", "The plan has invalid OpenResearch resource bounds")
    if not 1024 <= setting_bytes <= 8_388_608 or not 1 <= plan_bytes <= 8_388_608:
        raise OpenResearchError("RESOURCE_LIMIT_INVALID", "The plan has invalid output bounds")
    if not 0 < plan_seconds <= 300 or not 0 < float(setting_seconds) <= 300:
        raise OpenResearchError("RESOURCE_LIMIT_INVALID", "The plan has invalid runtime bounds")
    environment_output = getattr(environment, "output_bytes", setting_bytes)
    environment_seconds = getattr(environment, "timeout_seconds", _MAX_COMMAND_SECONDS)
    if (type(environment_output) is not int or type(environment_seconds) not in (int, float)
            or not 1024 <= environment_output <= 1_048_576
            or not 0.1 <= float(environment_seconds) <= 30):
        raise OpenResearchError("RESOURCE_LIMIT_INVALID", "The selected environment has invalid resource bounds")
    max_output = min(setting_bytes, plan_bytes, environment_output)
    # Leave space for the platform's provenance envelope in the stored artifact.
    adapter_output_cap = max_output - _WRAPPER_RESERVE_BYTES
    if adapter_output_cap < 1024:
        raise OpenResearchError("RESOURCE_LIMIT_INVALID", "The plan output budget is too small for discovery provenance")
    max_seconds = min(plan_seconds, float(setting_seconds), float(environment_seconds), float(_MAX_COMMAND_SECONDS))
    return adapter_output_cap, max_seconds


def _request_key(ctx: RunContext, plan: dict[str, Any], binding: ResolvedORXBinding,
                 query: str, corpus: str, limit: int) -> tuple[str, dict[str, Any], str]:
    refs = plan.get("materialRefs", [])
    if not isinstance(refs, list):
        raise OpenResearchError("PLAN_SCOPE_INVALID", "Material revision pins are invalid")
    request = {
        "ownerId": ctx.user_id,
        "taskId": ctx.session_id,
        "planId": plan.get("id"),
        "planFingerprint": plan.get("fingerprint"),
        "materialRefs": refs,
        "connection": {"ref": binding.ref, "version": binding.version,
                       "fingerprint": binding.fingerprint, "revision": binding.revision,
                       "capabilities": list(binding.capabilities)},
        "query": query.strip(), "corpus": corpus, "limit": limit,
    }
    fingerprint = digest(request)
    return "orx-discover:" + fingerprint[:40], request, fingerprint


def _result_from_artifact(store: Any, ctx: RunContext, name: str,
                          fingerprint: str) -> dict[str, Any] | None:
    """Recover a result only from an already persisted, integrity-checked artifact."""
    for artifact in store.artifacts(ctx.session_id):
        if artifact.get("name") != name:
            continue
        provenance = artifact.get("provenance", {})
        if provenance.get("effectFingerprint") != fingerprint:
            continue
        _, raw = store.artifact(ctx.session_id, artifact["id"])
        try:
            document = json.loads(raw)
        except (TypeError, ValueError):
            continue
        result = document.get("result") if isinstance(document, dict) else None
        if (isinstance(result, dict) and result.get("effectFingerprint") == fingerprint
                and isinstance(result.get("results"), list)):
            return {**result, "artifactId": artifact["id"], "artifactSha256": artifact.get("sha256")}
    return None


def _binding_provenance(binding: ResolvedORXBinding, plan: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    pin = _verified_pin(binding.adapter)
    transport_kind = getattr(binding.adapter, "transport_kind", None)
    is_pinned_cli = isinstance(binding.adapter, OpenResearchAdapter)
    if not is_pinned_cli:
        transport_kind = transport_kind or "trusted_non_cli_transport"
    return {
        "evidenceKind": "public_literature_metadata" if is_pinned_cli else "controlled_transport_fixture",
        "transportKind": transport_kind or "pinned_openresearch_cli",
        "adapterId": "openresearch-discover-v1",
        "sourceRevision": REVISION,
        "sourceVersion": VERSION,
        **({"binarySha256": pin.sha256} if is_pinned_cli else {"configuredBinarySha256": pin.sha256}),
        "connection": {"ref": binding.ref, "version": binding.version,
                       "fingerprint": binding.fingerprint, "revision": binding.revision,
                       "capabilities": list(binding.capabilities)},
        "ownerId": ctx.user_id,
        "taskId": ctx.session_id,
        "planId": plan["id"],
        "planFingerprint": plan.get("fingerprint"),
        "materialRefs": plan.get("materialRefs", []),
    }


def make_orx_discover_tool(settings: Any, store: Any,
                           adapter_provider: Callable[[RunContext, dict[str, Any]], Any] | None):
    """Build a native callable whose only ORX operation is bounded discovery.

    `adapter_provider` is supplied by trusted ExecutionBindings/ConnectionService
    glue. It must resolve the immutable plan pin and current owner/task each time
    it is called, then return a ResolvedORXBinding with a task-scoped adapter.
    """
    async def orx_discover(query: str, run_context: RunContext,
                           corpus: str = "openalex", limit: int = 5) -> str:
        if not isinstance(query, str) or not query.strip() or len(query) > 4000 or "\x00" in query or query.startswith("-"):
            raise ValueError("Query must be 1 through 4000 characters and cannot begin with an option marker")
        if corpus not in _CORPORA:
            raise ValueError("Unsupported OpenResearch discovery corpus")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Discovery limit must be 1 through 20")
        resolver = adapter_provider
        if resolver is None:
            raise OpenResearchError("CONNECTION_NOT_CONFIGURED", "No OpenResearch connection is configured for this task")

        plan = store.resolve_run(run_context)
        _check_plan(store, run_context, plan)
        bindings = getattr(store, "execution_bindings", None)
        environment = bindings.environment_limits(plan, run_context) if bindings is not None else None
        raw_binding = resolver(run_context, plan)
        if inspect.isawaitable(raw_binding):
            raw_binding = await raw_binding
        binding = _validate_binding(raw_binding, run_context)
        output_limit, timeout = _effective_limits(settings, plan, environment)
        adapter = binding.adapter
        if (adapter.max_output_bytes > output_limit
                or adapter.command_timeout > timeout
                or adapter.command_timeout <= 0):
            raise OpenResearchError("RESOURCE_LIMIT_EXCEEDED", "Resolved OpenResearch adapter exceeds current task limits")

        effect_key, request, fingerprint = _request_key(run_context, plan, binding, query, corpus, limit)
        reservation = store.effect_reserve(run_context.run_id, effect_key, request)
        artifact_name = "orx-discovery-" + fingerprint[:24] + ".json"
        if reservation["status"] == "done":
            result = reservation.get("result")
            if isinstance(result, dict) and result.get("cancelled"):
                raise RunCancelledException("This discovery effect was cancelled after authority ended")
            if not isinstance(result, dict) or not isinstance(result.get("results"), list):
                raise OpenResearchError("INVALID_EFFECT", "Persisted discovery result is malformed")
            return json.dumps(result, ensure_ascii=False, sort_keys=True)
        if reservation["status"] == "unknown":
            recovered = _result_from_artifact(store, run_context, artifact_name, fingerprint)
            if recovered is not None:
                store.effect_complete(run_context.run_id, effect_key, recovered)
                store.event(run_context.run_id, "orx_discovery_reconciled",
                            "Recovered discovery result from its integrity-checked task artifact",
                            {"effectFingerprint": fingerprint, "artifactId": recovered.get("artifactId")})
                return json.dumps(recovered, ensure_ascii=False, sort_keys=True)
            store.event(run_context.run_id, "effect_unknown",
                        "OpenResearch discovery acknowledgement is unresolved; automatic retry refused",
                        {"tool": TOOL_NAME, "effectFingerprint": fingerprint})
            raise OpenResearchError("UNKNOWN_EFFECT", "Discovery outcome is unresolved; issue a new reviewed request after reconciliation")

        store.event(run_context.run_id, "orx_discovery_started", "Bounded public metadata discovery started",
                    {"corpus": corpus, "limit": limit, "querySha256": hashlib.sha256(query.strip().encode()).hexdigest(),
                     "effectFingerprint": fingerprint, "connectionRef": binding.ref,
                     "connectionRevision": binding.revision})
        operation = asyncio.create_task(adapter.discover(query.strip(), corpus=corpus, limit=limit))
        start = time.monotonic()

        async def stop_and_settle() -> None:
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            # OpenResearchAdapter owns process-tree termination in discover's
            # cancellation/finally path. A lingering owned process is a cleanup
            # failure, so retain UNKNOWN rather than claiming cancellation.
            processes = tuple(getattr(adapter, "_processes", ()))
            for process in processes:
                await adapter._terminate(process)
            if getattr(adapter, "_processes", ()):
                raise OpenResearchError("CLEANUP_UNCONFIRMED", "Owned OpenResearch subprocess cleanup is unconfirmed")

        async def current_authority() -> ResolvedORXBinding:
            store.authorize_tool(run_context, TOOL_NAME)
            if store.cancellation_requested(run_context.run_id):
                raise RunCancelledException("Factory cancellation requested during OpenResearch discovery")
            current_raw = resolver(run_context, plan)
            if inspect.isawaitable(current_raw):
                current_raw = await current_raw
            current = _validate_binding(current_raw, run_context)
            if (current.ref, current.version, current.fingerprint, current.revision,
                    tuple(current.capabilities)) != (binding.ref, binding.version, binding.fingerprint,
                                                       binding.revision, tuple(binding.capabilities)):
                raise PermissionError("Current OpenResearch connection pin changed during discovery")
            return current

        try:
            while True:
                done, _ = await asyncio.wait({operation}, timeout=_AUTHORITY_POLL_SECONDS)
                if done:
                    hits = await operation
                    break
                if time.monotonic() - start > timeout:
                    raise OpenResearchError("TIMEOUT", "OpenResearch discovery exceeded current task time limit")
                try:
                    await current_authority()
                except (RunCancelledException, asyncio.CancelledError):
                    await stop_and_settle()
                    cancelled = {"cancelled": True, "cleanupComplete": True,
                                 "effectFingerprint": fingerprint, "connectionRef": binding.ref}
                    store.effect_complete(run_context.run_id, effect_key, cancelled)
                    store.event(run_context.run_id, "orx_discovery_cancelled",
                                "Owned OpenResearch discovery stopped after Factory cancellation",
                                {"effectFingerprint": fingerprint, "cleanupComplete": True})
                    raise
                except Exception as error:
                    await stop_and_settle()
                    cancelled = {"cancelled": True, "cleanupComplete": True,
                                 "effectFingerprint": fingerprint, "connectionRef": binding.ref}
                    store.effect_complete(run_context.run_id, effect_key, cancelled)
                    store.event(run_context.run_id, "protected_denied",
                                "Current OpenResearch authority ended; owned discovery was stopped",
                                {"tool": TOOL_NAME, "effectFingerprint": fingerprint})
                    raise RunCancelledException("Current authority ended during OpenResearch discovery") from error

            # Confirm current plan/connection authority before persisting any
            # result artifact or returning data to the model.
            try:
                await current_authority()
            except Exception as error:
                cancelled = {"cancelled": True, "cleanupComplete": not bool(getattr(adapter, "_processes", ())),
                             "effectFingerprint": fingerprint, "connectionRef": binding.ref}
                if cancelled["cleanupComplete"]:
                    store.effect_complete(run_context.run_id, effect_key, cancelled)
                store.event(run_context.run_id, "protected_denied",
                            "Current OpenResearch authority ended before results could be released",
                            {"tool": TOOL_NAME, "effectFingerprint": fingerprint})
                raise RunCancelledException("Current authority ended before OpenResearch results were released") from error

            if not isinstance(hits, list) or len(hits) > limit or any(not isinstance(item, dict) for item in hits):
                raise OpenResearchError("INVALID_OUTPUT", "OpenResearch returned an invalid discovery result")
            provenance = _binding_provenance(binding, plan, run_context)
            evidence_kind = "public_literature_metadata" if isinstance(adapter, OpenResearchAdapter) else "controlled_transport_fixture"
            result = {"evidenceKind": evidence_kind, "query": query.strip(),
                      "corpus": corpus, "results": hits, "provenance": provenance,
                      "effectFingerprint": fingerprint}
            content = json.dumps({"result": result}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            artifact_budget = plan.get("budget")
            plan_output_bytes = artifact_budget.get("outputBytes", 65536) if isinstance(artifact_budget, dict) else 65536
            if len(content.encode("utf-8")) > min(int(getattr(settings, "experiment_output_bytes", 65536)),
                                                   int(plan_output_bytes)):
                raise OpenResearchError("OUTPUT_LIMIT", "Discovery result and provenance exceed the task output budget")
            artifact = store.artifact_write(run_context.run_id, artifact_name, content, "application/json",
                {**provenance, "effectFingerprint": fingerprint})
            result["artifactId"] = artifact["id"]
            result["artifactSha256"] = artifact["sha256"]
            store.effect_complete(run_context.run_id, effect_key, result)
            store.event(run_context.run_id, "orx_discovery_completed",
                        "Public metadata discovery completed with pinned provenance",
                        {"effectFingerprint": fingerprint, "resultCount": len(hits),
                         "artifactId": artifact["id"], "artifactSha256": artifact["sha256"]})
            # The native protected hook performs the final permission check too;
            # this one closes the small gap between artifact persistence and return.
            await current_authority()
            return json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (RunCancelledException, asyncio.CancelledError):
            if not operation.done():
                await stop_and_settle()
                cancelled = {"cancelled": True, "cleanupComplete": True,
                             "effectFingerprint": fingerprint, "connectionRef": binding.ref}
                store.effect_complete(run_context.run_id, effect_key, cancelled)
            raise
        except BaseException as error:
            if not operation.done():
                try:
                    await stop_and_settle()
                except BaseException as cleanup_error:
                    store.event(run_context.run_id, "orx_discovery_cleanup_unconfirmed",
                                "Discovery stopped returning before owned process cleanup was confirmed",
                                {"effectFingerprint": fingerprint,
                                 "cleanupError": type(cleanup_error).__name__})
            store.event(run_context.run_id, "effect_unknown",
                        "OpenResearch discovery result requires reconciliation; automatic retry refused",
                        {"tool": TOOL_NAME, "effectFingerprint": fingerprint,
                         "errorCode": getattr(error, "code", type(error).__name__)})
            if isinstance(error, OpenResearchError):
                raise
            raise OpenResearchError("UNKNOWN_EFFECT", "OpenResearch discovery outcome is unresolved; automatic retry refused") from error

    return orx_discover


def register_orx_adapter(bindings: Any) -> Any:
    """Register the operator-owned, plan-bound ORX discovery adapter.

    The public material contains only a symbolic connection name. Its owner
    connection resolves to an operator-installed ``TaskORXAdapterProvider``;
    current SQL and process-local handle identity are rechecked on every poll.
    """
    def factory(context: Any):
        spec = context.spec
        connection = spec.get("connection")
        initial_handle = context.connection
        if (not isinstance(connection, dict) or not callable(getattr(initial_handle, "create_adapter", None))
                or context.store.connections is None):
            raise OpenResearchError("CONNECTION_NOT_CONFIGURED", "A trusted task-scoped OpenResearch provider is unavailable")
        settings, store = context.settings, context.store
        owner_id = context.run_context.user_id
        task_id = context.run_context.session_id
        if not isinstance(owner_id, str) or not task_id:
            raise OpenResearchError("BINDING_MISMATCH", "Native owner/task identity is unavailable")
        base = Path(settings.workspace).resolve()
        owner_key = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]
        scope = (base / "orx-tasks" / owner_key / task_id).resolve()
        if not scope.is_relative_to(base):
            raise OpenResearchError("SCOPE_INVALID", "OpenResearch task scope escapes its workspace")
        scope.mkdir(parents=True, exist_ok=True)
        adapter: Any = None
        fixed: dict[str, Any] = {key: connection.get(key) for key in
                 ("ref", "version", "fingerprint", "revision", "capabilities")}
        if (not isinstance(fixed["ref"], str) or type(fixed["version"]) is not int
                or not isinstance(fixed["fingerprint"], str) or not isinstance(fixed["revision"], str)
                or not isinstance(fixed["capabilities"], list)):
            raise OpenResearchError("BINDING_INVALID", "OpenResearch connection pin is incomplete")

        def resolve(run_context: RunContext, plan: dict[str, Any]) -> ResolvedORXBinding:
            nonlocal adapter
            if (run_context.user_id != owner_id or run_context.session_id != task_id
                    or plan.get("id") != context.plan.get("id")
                    or plan.get("fingerprint") != context.plan.get("fingerprint")):
                raise OpenResearchError("BINDING_MISMATCH", "OpenResearch binding belongs to another native run")
            spec_pin = fixed
            current_handle = store.connections.resolve(
                owner_id, spec_pin["ref"], "orx",
                expected_revision=spec_pin["revision"],
                expected_fingerprint=spec_pin["fingerprint"],
                expected_version=spec_pin["version"],
                expected_adapter_ref=ORX_ADAPTER_ID,
                required_capabilities=(CAPABILITY,), task_id=task_id)
            if current_handle is not initial_handle:
                raise OpenResearchError("CONNECTION_CHANGED", "Trusted OpenResearch provider changed during this run")
            bindings = getattr(store, "execution_bindings", None)
            environment = bindings.environment_limits(plan, run_context) if bindings is not None else None
            output_limit, timeout = _effective_limits(settings, plan, environment)

            def authorize(_operation: str) -> None:
                store.authorize_tool(run_context, TOOL_NAME)
                if store.cancellation_requested(run_context.run_id):
                    raise RunCancelledException("Factory cancellation requested before OpenResearch subprocess")
                latest_handle = store.connections.resolve(
                    owner_id, spec_pin["ref"], "orx",
                    expected_revision=spec_pin["revision"],
                    expected_fingerprint=spec_pin["fingerprint"],
                    expected_version=spec_pin["version"],
                    expected_adapter_ref=ORX_ADAPTER_ID,
                    required_capabilities=(CAPABILITY,), task_id=task_id)
                if latest_handle is not initial_handle:
                    raise OpenResearchError("CONNECTION_CHANGED", "Trusted OpenResearch provider changed before subprocess")

            if adapter is None:
                adapter = initial_handle.create_adapter(owner_id=owner_id, task_id=task_id,
                    scope=scope, authorize=authorize, pin=BinaryPin(REVISION, VERSION, _APPROVED_BINARY_SHA256),
                    max_output_bytes=output_limit, command_timeout=timeout)
            if getattr(adapter, "owner_id", None) != owner_id or getattr(adapter, "task_id", None) != task_id:
                raise OpenResearchError("BINDING_MISMATCH", "Provider returned an adapter for a different task")
            return ResolvedORXBinding(adapter=adapter, owner_id=owner_id, task_id=task_id,
                ref=spec_pin["ref"], version=spec_pin["version"], fingerprint=spec_pin["fingerprint"],
                revision=spec_pin["revision"], capabilities=tuple(spec_pin["capabilities"]))

        return make_orx_discover_tool(settings, store, resolve)

    return bindings.register("tool", ORX_ADAPTER_ID, ORX_ADAPTER_REVISION, factory,
        tool_name=TOOL_NAME, connection_kind="orx", required_capabilities=(CAPABILITY,),
        permissions=(CAPABILITY,))


def build_orx_tools(settings: Any, store: Any,
                    adapter_provider: Callable[[RunContext, dict[str, Any]], Any] | None) -> dict[str, Any]:
    """Return optional ORX tools for the plan-aware native function registry."""
    return {TOOL_NAME: make_orx_discover_tool(settings, store, adapter_provider)}

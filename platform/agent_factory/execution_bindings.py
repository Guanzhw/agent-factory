"""Trusted runtime factories selected by exact immutable material snapshots.

Material specifications are inert data. Only operator-registered Python factories
can create adapters; no import paths, code, credentials or endpoint discovery are
loaded from a material. Every executable material requires an explicit binding.
"""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from functools import wraps
import inspect
import json
import math
import re
import threading
from typing import Any, Callable, Mapping
import weakref

from agno.exceptions import InputCheckError, RunCancelledException
from agno.models.base import Model
from agno.tools.function import Function
from fastapi import HTTPException

from .store import digest

KINDS = frozenset({"model", "tool", "knowledge", "environment"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_SECRET = re.compile(r"^(?:api[_-]?key|password|secret|access[_-]?token|refresh[_-]?token|authorization|cookie|credentials|private[_-]?key)$", re.I)



@dataclass(frozen=True)
class EnvironmentLimits:
    runtime_id: str = "local-python-bounded-v1"
    timeout_seconds: float = 8
    output_bytes: int = 65536
    memory_bytes: int = 256 * 1024 * 1024
    process_limit: int = 4
    cpu_percent: int = 10

    def __post_init__(self):
        if not _IDENTIFIER.fullmatch(self.runtime_id):
            raise ValueError("Invalid trusted environment runtime ID")
        if type(self.timeout_seconds) not in {int, float} or not math.isfinite(self.timeout_seconds) or not .1 <= self.timeout_seconds <= 600:
            raise ValueError("Environment timeout must be between 0.1 and 600 seconds")
        for value, lower, upper in ((self.output_bytes, 1024, 1024 * 1024),
                (self.memory_bytes, 64 * 1024 * 1024, 1024 * 1024 * 1024), (self.process_limit, 1, 64), (self.cpu_percent, 1, 100)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("Environment limit is outside the bounded native profile")


@dataclass(frozen=True)
class KnowledgeContext:
    content: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class BindingContext:
    settings: Any
    store: Any
    plan: Mapping[str, Any]
    run_context: Any
    spec: Mapping[str, Any]
    connection: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class AdapterRegistration:
    kind: str
    adapter_id: str
    revision: str
    factory: Callable[[BindingContext], Any] = field(repr=False)
    tool_name: str | None = None
    connection_kind: str | None = None
    required_capabilities: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    validator: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False)
    # Optional operator-selected shared handle identity for a narrow tool family.
    # It never changes a material's exact adapter/tool identity or capabilities.
    connection_adapter_ref: str | None = None


class ExecutionBindings:
    def __init__(self, settings: Any, store: Any, connections: Any = None):
        self.settings, self.store, self.connections = settings, store, connections
        self._adapters: dict[tuple[str, str, str], AdapterRegistration] = {}
        self._models: weakref.WeakValueDictionary[int, Model] = weakref.WeakValueDictionary()
        self._lock = threading.RLock()

    def register(self, kind: str, adapter_id: str, revision: str, factory: Callable[[BindingContext], Any], *,
                 tool_name: str | None = None, connection_kind: str | None = None, required_capabilities=(),
                 permissions=(), validator=None, connection_adapter_ref: str | None = None) -> AdapterRegistration:
        if kind not in KINDS or not _IDENTIFIER.fullmatch(adapter_id) or not _IDENTIFIER.fullmatch(revision) or not callable(factory):
            raise ValueError("Invalid trusted adapter registration")
        if kind == "tool" and (not isinstance(tool_name, str) or not _IDENTIFIER.fullmatch(tool_name)):
            raise ValueError("A tool adapter requires its exact native name")
        if kind != "tool" and tool_name is not None:
            raise ValueError("Only tool registrations declare native tool names")
        if connection_adapter_ref is not None and (connection_kind is None or not _IDENTIFIER.fullmatch(connection_adapter_ref)):
            raise ValueError("A shared connection identity must be an exact operator registration")
        entry = AdapterRegistration(kind, adapter_id, revision, factory, tool_name, connection_kind,
                                    tuple(required_capabilities), tuple(permissions), validator, connection_adapter_ref)
        with self._lock:
            key = (kind, adapter_id, revision)
            if key in self._adapters:
                raise ValueError("Trusted adapter revision already registered")
            self._adapters[key] = entry
        return entry

    def describe(self) -> list[dict[str, Any]]:
        """Installed descriptors only; availability does not prove live use.

        No factory, validator, connection handle or material config is exposed.
        The HTTP boundary owns authenticated current manager/read authority.
        """
        with self._lock:
            entries = sorted(self._adapters.values(), key=lambda entry: (entry.kind, entry.adapter_id, entry.revision))
        return [{"kind": entry.kind, "adapterId": entry.adapter_id, "revision": entry.revision,
                 "toolName": entry.tool_name, "connectionKind": entry.connection_kind,
                 "requiredCapabilities": list(entry.required_capabilities), "permissions": list(entry.permissions)}
                for entry in entries]

    def withdraw(self, kind: str, adapter_id: str, revision: str) -> None:
        with self._lock:
            self._adapters.pop((kind, adapter_id, revision), None)

    @staticmethod
    def _configuration(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise HTTPException(409, "BINDING_CONFIG_INVALID: configuration must be an inert JSON object")
        def visit(item, depth=0):
            if depth > 8:
                raise ValueError("Configuration nesting exceeds its bound")
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str) or _SECRET.fullmatch(key):
                        raise ValueError("Credential keys cannot be material configuration")
                    visit(child, depth + 1)
            elif isinstance(item, list):
                for child in item:
                    visit(child, depth + 1)
            elif type(item) not in {str, int, float, bool, type(None)} or isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Configuration is not bounded JSON data")
        try:
            visit(value)
            if len(json.dumps(value, allow_nan=False).encode()) > 16000:
                raise ValueError("Configuration exceeds 16000 bytes")
        except (ValueError, TypeError) as error:
            raise HTTPException(409, "BINDING_CONFIG_INVALID: " + str(error)) from error
        return copy.deepcopy(value)

    def _entry(self, kind: str, spec: Mapping[str, Any]) -> AdapterRegistration:
        adapter_id, revision = spec["adapterId"], spec["revision"]
        with self._lock:
            entry = self._adapters.get((kind, adapter_id, revision))
        if entry is None and kind == "tool" and getattr(self.store, "personal_tools", None) is not None:
            self.store.personal_tools.ensure_registered(adapter_id)
            with self._lock:
                entry = self._adapters.get((kind, adapter_id, revision))
        if entry is None:
            raise HTTPException(409, "BINDING_ADAPTER_UNAVAILABLE: exact trusted adapter revision is unavailable")
        return entry

    def _spec(self, material: Mapping[str, Any], connections: Mapping[str, Any]) -> dict[str, Any]:
        kind = material["kind"]
        binding = material.get("runtimeBinding")
        if binding is None:
            raise HTTPException(409, "BINDING_SPEC_REQUIRED: material has no explicit trusted runtime binding")
        if not isinstance(binding, dict) or set(binding) - {"adapterId", "revision", "config"}:
            raise HTTPException(409, "BINDING_SPEC_INVALID: unrecognized runtime binding fields")
        from .material_governance import normalize_runtime_binding
        # Admission and direct trusted registry use share the governed inert
        # schema; adapter registration cannot make material text executable.
        try:
            binding = normalize_runtime_binding(binding)
        except HTTPException as error:
            raise HTTPException(409, "BINDING_CONFIG_INVALID: invalid inert runtime binding") from error
        spec = {"materialRef": {key: material[key] for key in ("id", "version", "sha256")},
                "adapterId": binding.get("adapterId"), "revision": binding.get("revision"),
                "config": binding["config"]}
        entry = self._entry(kind, spec)
        if entry.validator is not None:
            try:
                entry.validator({key: val for key, val in spec["config"].items() if key != "connectionName"})
            except (ValueError, TypeError) as error:
                raise HTTPException(409, "BINDING_CONFIG_INVALID: " + str(error)) from error
        if kind == "tool":
            spec["toolName"] = entry.tool_name
        name = spec["config"].get("connectionName")
        if entry.connection_kind:
            if not isinstance(name, str) or name not in connections:
                raise HTTPException(409, "BINDING_CONNECTION_REQUIRED: selected resource connection is unavailable")
            value = connections[name]
            if not isinstance(value, dict):
                raise HTTPException(409, "BINDING_CONNECTION_INVALID: connection pin must be redacted metadata")
            spec["connection"] = {key: value[key] for key in ("ref", "version", "fingerprint", "kind", "revision", "capabilities", "taskId") if key in value}
        elif name is not None:
            raise HTTPException(409, "BINDING_CONNECTION_INVALID: adapter does not accept a connection")
        return spec

    def preflight(self, materials: list[dict[str, Any]], owner: str,
                  connections: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Report only actual unavailable bindings; never instantiate factories."""
        missing = []
        if not isinstance(materials, list) or len(materials) > 30:
            raise HTTPException(409, "BINDING_MATERIAL_LIMIT: invalid selected material closure")
        for material in materials:
            kind = material.get("kind")
            if kind not in KINDS:
                continue
            try:
                actual = digest({key: value for key, value in material.items() if key not in {"sha256", "published", "createdAt"}})
                if actual != material.get("sha256"):
                    raise HTTPException(409, "BINDING_MATERIAL_INTEGRITY: selected material changed")
                spec = self._spec(material, connections or {})
                self._connection(owner, self._entry(kind, spec), spec, None, resolve=False)
            except HTTPException as error:
                match = re.match(r"^(BINDING_[A-Z_]+|CONNECTION_[A-Z_]+):", str(error.detail))
                raw_binding = material.get("runtimeBinding")
                binding = raw_binding if isinstance(raw_binding, dict) else {}
                # Only immutable public material descriptors are included, never
                # exception text, trusted registrations, handles or endpoints.
                item = {"code": match.group(1) if match else "BINDING_PREFLIGHT_DENIED", "kind": kind,
                        "materialRef": {key: material[key] for key in ("id", "version", "sha256")}}
                for key in ("adapterId", "revision"):
                    if key in binding:
                        item[key] = binding[key]
                name = binding.get("config", {}).get("connectionName")
                if name is not None:
                    item["connectionName"] = name
                missing.append(item)
        return missing

    def build(self, materials: list[dict[str, Any]], owner: str, connections: Mapping[str, Any] | None = None) -> dict[str, Any]:
        values: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
        if not isinstance(materials, list) or len(materials) > 30:
            raise HTTPException(409, "BINDING_MATERIAL_LIMIT: invalid selected material closure")
        for material in materials:
            actual = digest({key: value for key, value in material.items() if key not in {"sha256", "published", "createdAt"}})
            if actual != material.get("sha256"):
                raise HTTPException(409, "BINDING_MATERIAL_INTEGRITY: selected material differs from its exact hash")
            if material.get("kind") in KINDS:
                values[material["kind"]].append(self._spec(material, connections or {}))
        if len(values["model"]) != 1 or len(values["environment"]) != 1:
            raise HTTPException(409, "BINDING_SINGLETON_REQUIRED: select exactly one model and environment")
        names = [value["toolName"] for value in values["tool"]]
        if len(names) != len(set(names)):
            raise HTTPException(409, "BINDING_TOOL_DUPLICATE: selected materials bind the same native tool")
        body = {"schema": 1, "model": values["model"][0], "environment": values["environment"][0],
                "tools": values["tool"], "knowledge": values["knowledge"]}
        for kind, spec in self._items(body):
            self._connection(owner, self._entry(kind, spec), spec, None, resolve=False)
        return {**body, "sha256": digest(body)}

    @staticmethod
    def _items(manifest: Mapping[str, Any]):
        return [("model", manifest["model"]), ("environment", manifest["environment"]),
                *[("tool", item) for item in manifest["tools"]], *[("knowledge", item) for item in manifest["knowledge"]]]

    def manifest(self, plan: Mapping[str, Any], *, context: Any = None) -> dict[str, Any]:
        receiver = getattr(self.store, "remote_bindings", None)
        if receiver is not None and (plan.get("remoteHandoff") or plan.get("delegation")):
            # Preserve the original immutable source manifest. Only an exact
            # receipt-bound receiver proof may select its effective local
            # adapters/connections; origin pins are never resolved as local pins.
            effective = receiver.effective(plan, plan.get("executionBindings"), context)
            if effective is not None:
                return effective
        manifest = plan.get("executionBindings")
        if manifest is None:
            raise HTTPException(409, "BINDING_MANIFEST_REQUIRED: regenerate the plan with explicit runtime bindings")
        return manifest

    def _connection(self, owner: str, entry: AdapterRegistration, spec: Mapping[str, Any], context: Any, *, resolve: bool):
        pin = spec.get("connection")
        if not entry.connection_kind:
            if pin is not None:
                raise HTTPException(409, "BINDING_CONNECTION_INVALID: unexpected connection pin")
            return None
        if self.connections is None or not isinstance(pin, dict):
            raise HTTPException(409, "BINDING_CONNECTION_UNAVAILABLE: trusted owner connection is unavailable")
        required = {"ref", "version", "fingerprint", "kind", "revision", "capabilities", "taskId"}
        if (set(pin) != required or not isinstance(pin["ref"], str) or type(pin["version"]) is not int or pin["version"] < 1
                or not isinstance(pin["fingerprint"], str) or re.fullmatch(r"[a-f0-9]{64}", pin["fingerprint"]) is None
                or pin["kind"] != entry.connection_kind or not isinstance(pin["revision"], str)
                or not isinstance(pin["capabilities"], list) or not set(entry.required_capabilities) <= set(pin["capabilities"])):
            raise HTTPException(409, "BINDING_CONNECTION_INVALID: an exact revision/fingerprint/capability pin is required")
        action = self.connections.resolve if resolve else self.connections.preflight
        return action(owner, pin.get("ref"), expected_kind=entry.connection_kind,
            expected_revision=pin.get("revision"), expected_fingerprint=pin.get("fingerprint"), expected_version=pin.get("version"),
            required_capabilities=entry.required_capabilities, task_id=getattr(context, "session_id", None), expected_adapter_ref=entry.connection_adapter_ref or spec["adapterId"])

    def require_execution(self, owner, plan, context, tool):
        return self.recheck(plan, context)

    def recheck(self, plan: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
        owner = plan["ownerId"]
        if context is not None:
            task = self.store.task(context.session_id, owner)
            envelope = (getattr(context, "session_state", None) or {}).get("factory_envelope")
            expected = {"plan_ref": plan["id"], "user_id": owner, "task_id": task["id"], "request_id": task["request_id"]}
            # Native bind_run owns strict external envelope ingress. Trusted
            # internal Factory actions may omit session state only after their
            # owner/task/plan/original native run matches this persisted row.
            if (context.user_id != owner or task["owner_id"] != owner or task["id"] != context.session_id
                    or task["plan_id"] != plan["id"] or task["run_id"] != context.run_id
                    or envelope is not None and envelope != expected):
                raise HTTPException(403, "BINDING_NATIVE_IDENTITY: native run differs from its trusted execution binding")
            if task["cancel_requested"]:
                raise RunCancelledException("Factory cancellation requested before adapter execution")
        manifest = self.manifest(plan, context=context)
        for kind, spec in self._items(manifest):
            self._connection(owner, self._entry(kind, spec), spec, context, resolve=False)
        from .billing_mode import require_available
        require_available(self.settings, plan, manifest=manifest)
        return manifest

    def inspect(self, plan: Mapping[str, Any], context: Any = None) -> dict[str, Any]:
        return self.recheck(plan, context)

    def resolve(self, plan: Mapping[str, Any], context: Any) -> dict[str, BindingContext | list[BindingContext]]:
        manifest = self.recheck(plan, context)
        values: dict[str, Any] = {"tools": [], "knowledge": []}
        for kind, spec in self._items(manifest):
            entry = self._entry(kind, spec)
            binding = BindingContext(self.settings, self.store, plan, context, spec,
                self._connection(plan["ownerId"], entry, spec, context, resolve=True))
            if kind in {"tool", "knowledge"}:
                values[kind + ("s" if kind == "tool" else "")].append(binding)
            else:
                values[kind] = binding
        return values

    def _create(self, kind: str, context: BindingContext):
        result = self._entry(kind, context.spec).factory(context)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise InputCheckError("Trusted adapter factory must synchronously construct its adapter")
        return result

    def model_for(self, plan: Mapping[str, Any], context: Any) -> Model:
        binding = self.resolve(plan, context)["model"]
        assert isinstance(binding, BindingContext)
        return self.model_from_binding(binding)

    def model_from_binding(self, binding: BindingContext) -> Model:
        """Construct on the caller's loop after blocking binding checks finish."""
        model = self._create("model", binding)
        if not isinstance(model, Model):
            raise InputCheckError("Trusted model factory did not return a native Model")
        with self._lock:
            if self._models.get(id(model)) is model:
                raise InputCheckError("Model factories must create separate instances for native response contexts")
            self._models[id(model)] = model
        return model

    def tools_for(self, plan: Mapping[str, Any], context: Any) -> list[Any]:
        values = []
        bindings = self.resolve(plan, context)["tools"]
        assert isinstance(bindings, list)
        for binding in bindings:
            value = self._create("tool", binding)
            name = value.name if isinstance(value, Function) else getattr(value, "__name__", None)
            if name != binding.spec["toolName"] or not isinstance(value, Function) and not callable(value):
                raise InputCheckError("Trusted tool factory returned a different native tool")
            if isinstance(value, Function):
                # Native Function metadata (including HITL) survives, while
                # mutable entrypoint/hook state is local to this selected run.
                value = value.model_copy(deep=True)
                if value.entrypoint is None:
                    raise InputCheckError("Trusted tool factory has no native entrypoint")
                value.entrypoint = self._guard_tool(value.entrypoint, binding)
            else:
                value = self._guard_tool(value, binding)
            values.append(value)
        return values

    def _guard_tool(self, entrypoint, binding: BindingContext):
        signature = inspect.signature(entrypoint)
        expected = binding.run_context
        def current(args, kwargs):
            supplied = signature.bind_partial(*args, **kwargs).arguments.get("run_context")
            context = supplied if supplied is not None else expected
            if (context.user_id != expected.user_id or context.session_id != expected.session_id
                    or context.run_id != expected.run_id):
                raise HTTPException(403, "BINDING_NATIVE_IDENTITY: retained tool belongs to a different native run")
            try:
                self.store.authorize_tool(context, binding.spec["toolName"])
            except RunCancelledException:
                raise
            except Exception:
                self.store.event(context.run_id, "protected_denied", "Current member, selected tool or resource denied execution", {"tool": binding.spec["toolName"]})
                raise
        def local_current():
            if self.store.cancellation_requested(expected.run_id):
                raise RunCancelledException("Factory cancellation requested before tool execution")
        if inspect.isasyncgenfunction(entrypoint):
            @wraps(entrypoint)
            async def async_stream(*args, **kwargs):
                await asyncio.to_thread(current, args, kwargs)
                local_current()
                async for result in entrypoint(*args, **kwargs):
                    await asyncio.to_thread(current, args, kwargs)
                    local_current()
                    yield result
            return async_stream
        if inspect.iscoroutinefunction(entrypoint):
            @wraps(entrypoint)
            async def asynchronous(*args, **kwargs):
                await asyncio.to_thread(current, args, kwargs)
                local_current()
                return await entrypoint(*args, **kwargs)
            return asynchronous
        if inspect.isgeneratorfunction(entrypoint):
            @wraps(entrypoint)
            def stream(*args, **kwargs):
                current(args, kwargs)
                for result in entrypoint(*args, **kwargs):
                    current(args, kwargs)
                    yield result
            return stream
        @wraps(entrypoint)
        def synchronous(*args, **kwargs):
            current(args, kwargs)
            return entrypoint(*args, **kwargs)
        return synchronous

    def knowledge_for(self, plan: Mapping[str, Any], context: Any) -> list[KnowledgeContext]:
        values = []
        bindings = self.resolve(plan, context)["knowledge"]
        assert isinstance(bindings, list)
        for binding in bindings:
            value = self._create("knowledge", binding)
            if not isinstance(value, KnowledgeContext) or not isinstance(value.content, str) or len(value.content.encode()) > 16000:
                raise InputCheckError("Knowledge adapter returned invalid or oversized scoped context")
            provenance = self._configuration(dict(value.provenance))
            values.append(KnowledgeContext(value.content, {**provenance, "materialRef": binding.spec["materialRef"],
                "adapterId": binding.spec["adapterId"], "revision": binding.spec["revision"], "contentSha256": digest(value.content)}))
        return values

    def environment_limits(self, plan: Mapping[str, Any], context: Any) -> EnvironmentLimits:
        binding = self.resolve(plan, context)["environment"]
        assert isinstance(binding, BindingContext)
        value = self._create("environment", binding)
        if not isinstance(value, EnvironmentLimits):
            raise InputCheckError("Trusted environment factory did not return enforceable resource limits")
        return value


def default_bindings(settings: Any, store: Any, connections: Any = None) -> ExecutionBindings:
    """Installed adapters plus lazily registered member resource adapters."""
    return ExecutionBindings(settings, store, connections)

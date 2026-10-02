"""Operator-trusted Factory-to-Factory prepare/dispatch over native ownership.

This optional adapter never accepts a user URL, bearer credential, native
session_state, or native run payload. Preparation reserves metadata only. A
durable UNKNOWN boundary precedes native submission; recovery is a ticket read.
Main registration and UI routing remain optional; no target is installed by default.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
from dataclasses import dataclass, field
import re
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

from agno.exceptions import RunCancelledException
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .store import canonical, digest, now
from .native_bridge import INTERNAL_NATIVE
from .plan_policy import ToolContract, tools_for_contract

KNOWN_TOOLS = {"ask_scope": "question:ask", "literature_search": "research:read",
               "run_experiment": "experiment:synthetic", "checksum": "checksum:read"}
BUDGET_KEYS = {"toolCalls", "maxDepth", "maxChildren", "experimentSeconds", "outputBytes"}
PLAN_KEYS = {"id", "ownerId", "normalizedGoal", "mode", "application", "instructions", "tools", "config",
             "materialRefs", "materials", "capabilities", "missing", "status", "createdAt", "policy", "budget",
             "syntheticFixture", "fingerprint"}
ASSEMBLY_KEYS = {"applicationRef", "executionBindings", "bindingManifest", "compositionProposalId"}
USAGE_KEYS = {"schema", "currency", "amountMicros", "tokenLimit", "provider", "model", "adapterId", "adapterRevision",
              "pricingRevision", "pricingSha256", "inputMicrosPerMillion", "outputMicrosPerMillion",
              "perAttemptInputTokens", "perAttemptOutputTokens", "bindingSha256", "policyRevision", "sha256"}


def _usage_commitment(value: Any, *, bindings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    # Structural validation is independent of installed receiver prices. The
    # receiver separately approves its effective local quote without rewriting
    # any source manifest field or historical fingerprint.
    if not isinstance(value, dict) or set(value) != USAGE_KEYS or type(value.get("schema")) is not int or value["schema"] != 1:
        raise HTTPException(422, "USAGE_COMMITMENT_SCHEMA: exact immutable usage fields required")
    hashes = ("pricingSha256", "bindingSha256", "sha256")
    names = ("provider", "model", "adapterId", "adapterRevision", "pricingRevision", "policyRevision")
    counters = ("amountMicros", "tokenLimit", "inputMicrosPerMillion", "outputMicrosPerMillion", "perAttemptInputTokens", "perAttemptOutputTokens")
    if (value["currency"] not in {"USD", "EUR", "CNY"}
            or any(not isinstance(value[k], str) or not re.fullmatch(r"[a-f0-9]{64}", value[k]) for k in hashes)
            or any(not isinstance(value[k], str) or not 1 <= len(value[k]) <= 120 or any(c.isspace() for c in value[k]) for k in names)
            or any(type(value[k]) is not int or not 0 <= value[k] <= 10**15 for k in counters)
            or any(value[k] < 1 for k in ("tokenLimit", "perAttemptInputTokens", "perAttemptOutputTokens"))
            or value["sha256"] != digest({k: v for k, v in value.items() if k != "sha256"})):
        raise HTTPException(409, "USAGE_COMMITMENT_INTEGRITY: exact approved currency, limits and pricing digest required")
    if bindings is not None and (value["bindingSha256"] != bindings.get("sha256")
            or value["adapterId"] != bindings.get("model", {}).get("adapterId")
            or value["adapterRevision"] != bindings.get("model", {}).get("revision")):
        raise HTTPException(409, "USAGE_BINDING_INTEGRITY: usage differs from its original model binding")
    return copy.deepcopy(value)
REQUEST = re.compile(r"^[a-zA-Z0-9_.:-]{8,100}$")


class HandoffCancellationRequested(RunCancelledException):
    """Trusted cleanup signal; never a grant, receipt, or request-body field."""
    def __init__(self, owner: str, task_id: str, manifest_hash: str):
        super().__init__("Origin cancellation requested for this immutable handoff")
        self.owner, self.task_id, self.manifest_hash = owner, task_id, manifest_hash


class FactoryPublicRoute(APIRoute):
    """Translate late validated cleanup signals only at Factory HTTP ingress.

    Native AgentOS routes and background guards retain RunCancelledException.
    A signal for a different binding is rejected by _authority before reaching
    this boundary. No request body can construct or install a trusted signal.
    """
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def scoped(request: Request):
            try:
                return await handler(request)
            except HandoffCancellationRequested as error:
                raise HTTPException(409, "Origin cancellation ended this immutable handoff") from error

        return scoped


@dataclass(frozen=True)
class HandoffAuthority:
    """Current origin callback result, additionally bounded by receiver ceilings."""
    capabilities: frozenset[str]
    tools: frozenset[str]
    budget: Mapping[str, int]
    origin_ref: str | None = None
    target_ref: str | None = None
    receiver_identity: str | None = None
    target_revision: str | None = None
    target_fingerprint: str | None = None
    usage_grant_sha256: str | None = None


@dataclass(frozen=True)
class TrustedOrigin:
    """Installed by the receiver's operator, never by a remote request."""
    reference: str
    identity_map: Mapping[str, str]
    authorize: Callable[[str, str, str, str | None], HandoffAuthority] = field(repr=False)
    capabilities: frozenset[str] = frozenset(KNOWN_TOOLS.values())
    tools: frozenset[str] = frozenset(KNOWN_TOOLS)
    budget: Mapping[str, int] = field(default_factory=lambda: {
        "toolCalls": 8, "maxDepth": 2, "maxChildren": 4, "experimentSeconds": 8, "outputBytes": 65536})
    configuration_revision: str = "1"
    tool_contract: ToolContract = "legacy-v1"

    def __post_init__(self):
        if not self.reference or not self.identity_map or not callable(self.authorize):
            raise ValueError("A trusted origin requires explicit identities and a current-authority callback")
        _check_budget(self.budget)
        registered = tools_for_contract(self.tool_contract)
        if self.tool_contract != "legacy-v1" and self.configuration_revision == "1":
            raise ValueError("Extended remote tool contracts require a distinct operator revision")
        if not self.tools <= registered.keys() or not self.capabilities <= set(registered.values()):
            raise ValueError("Trusted origin ceiling exceeds the registered adapter contract")

    @property
    def fingerprint(self) -> str:
        body = {"reference": self.reference, "identityMap": dict(self.identity_map),
                "capabilities": sorted(self.capabilities), "tools": sorted(self.tools),
                "budget": dict(self.budget), "revision": self.configuration_revision}
        if self.tool_contract != "legacy-v1":
            body["toolContract"] = self.tool_contract
        transport_hash = getattr(self.authorize, "fingerprint", None)
        if transport_hash is not None:
            if not isinstance(transport_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", transport_hash):
                raise ValueError("Origin authority transport requires an exact configuration digest")
            body["authorityTransportSha256"] = transport_hash
        return digest(body)


def _check_budget(budget: Mapping[str, Any]) -> None:
    if set(budget) != BUDGET_KEYS or any(type(value) is not int or value < 1 for value in budget.values()):
        raise HTTPException(422, "Remote budget must contain the exact positive integer ceilings")


def plan_manifest(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Exact immutable source snapshot, not a newly generated remote goal/plan."""
    body = copy.deepcopy(dict(plan))
    return {"plan": body, "sha256": digest(body)}


def _manifest(manifest: Mapping[str, Any], store: Any, owner: str, *, receiver: bool = False) -> dict[str, Any]:
    if set(manifest) != {"plan", "sha256"} or not isinstance(manifest.get("plan"), dict):
        raise HTTPException(422, "An exact immutable plan manifest is required")
    plan = copy.deepcopy(manifest["plan"])
    if len(canonical(manifest).encode()) > 524288 or digest(plan) != manifest.get("sha256"):
        raise HTTPException(409, "Immutable manifest integrity mismatch")
    if set(plan) - {"usageBudget"} not in (PLAN_KEYS, PLAN_KEYS | ASSEMBLY_KEYS) or plan.get("ownerId") != owner or plan.get("status") != "ready" or plan.get("missing"):
        raise HTTPException(409, "Remote handoff requires a complete ready root plan owned by the origin user")
    if plan.get("fingerprint") != digest({key: value for key, value in plan.items()
                                         if key not in {"id", "createdAt", "fingerprint"}}):
        raise HTTPException(409, "Immutable origin plan fingerprint mismatch")
    try:
        UUID(plan["id"])
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, "Origin plan identity is invalid") from error
    if any(not isinstance(plan.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", plan[key]) for key in ("application", "mode")):
        raise HTTPException(422, "Remote application or mode is unsupported")
    policy_service = getattr(store, "plan_policy", None)
    contract = policy_service.current()["tool_contract"] if policy_service else store.settings.runtime_tool_contract
    known_tools = tools_for_contract(contract)
    tools, caps, budget = plan.get("tools"), plan.get("capabilities"), plan.get("budget")
    if not isinstance(tools, list) or not tools or any(type(name) is not str or name not in known_tools for name in tools):
        raise HTTPException(422, "Manifest contains an unregistered remote tool")
    if not isinstance(caps, list) or any(type(cap) is not str for cap in caps) or set(caps) != {known_tools[name] for name in tools}:
        raise HTTPException(422, "Manifest capability scope does not exactly match registered tools")
    if not isinstance(budget, dict) or set(budget) != BUDGET_KEYS | {"depth"} or type(budget.get("depth")) is not int or budget.get("depth") != 0:
        raise HTTPException(422, "Only a root delegation tree may select an execution server")
    _check_budget({key: budget[key] for key in BUDGET_KEYS})
    if not isinstance(plan.get("instructions"), list) or any(type(item) is not str or len(item) > 16000 for item in plan["instructions"]):
        raise HTTPException(422, "Bounded immutable instructions are required")
    config = plan.get("config")
    if not isinstance(config, dict) or set(config) not in ({"askScope", "sample", "experimentDurationSeconds"}, {"askScope", "sample", "experimentDurationSeconds", "toolOrder"}):
        raise HTTPException(422, "Unsupported remote executor configuration")
    if type(config["askScope"]) is not bool or type(config["sample"]) is not str or not 2 <= len(config["sample"]) <= 2000:
        raise HTTPException(422, "Remote executor input is invalid")
    if type(config["experimentDurationSeconds"]) is not int or not 0 < config["experimentDurationSeconds"] <= budget["experimentSeconds"]:
        raise HTTPException(422, "Remote experiment duration exceeds the immutable budget")
    if "toolOrder" in config and (not isinstance(config["toolOrder"], list) or config["toolOrder"] != tools):
        raise HTTPException(422, "Remote tool order differs from the immutable tool scope")
    if "usageBudget" in plan:
        _usage_commitment(plan["usageBudget"], bindings=plan.get("executionBindings"))
    if set(plan) - {"usageBudget"} == PLAN_KEYS | ASSEMBLY_KEYS:
        applications = getattr(store, "applications", None)
        bindings = getattr(store, "execution_bindings", None)
        if applications is None or bindings is None:
            raise HTTPException(409, "Receiver governed assembly bindings are unavailable")
        applications.require_plan_current(plan)
        if receiver:
            service = getattr(store, "remote_bindings", None)
            if service is None:
                raise HTTPException(409, "Receiver binding proof service is unavailable")
            service.validate_source(plan)
        else:
            bindings.inspect(plan)
    materials, refs = plan.get("materials"), plan.get("materialRefs")
    if not isinstance(materials, list) or not 1 <= len(materials) <= 30 or not isinstance(refs, list) or len(refs) != len(materials):
        raise HTTPException(422, "Bounded complete material manifest is required")
    known = {(item["id"], item["version"], item["sha256"]): item
             for item in store.materials(published_only=True) if not item.get("archived")}
    chosen = {}
    for item in materials:
        if not isinstance(item, dict):
            raise HTTPException(422, "Material manifest entries must be objects")
        if type(item.get("id")) is not str or type(item.get("version")) is not int or type(item.get("sha256")) is not str:
            raise HTTPException(422, "Immutable material references are invalid")
        key = (item["id"], item["version"], item["sha256"])
        local = known.get(key)
        if local is None or key in chosen:
            raise HTTPException(409, "Receiver has not approved the exact immutable material version")
        def meaningful(value):
            return {k: v for k, v in value.items() if k not in {"published", "createdAt"}}
        actual_hash = digest({k: v for k, v in item.items() if k not in {"sha256", "published", "createdAt"}})
        if actual_hash != item["sha256"] or meaningful(item) != meaningful(local) or "agno:3.1.0" not in item.get("compatibility", []):
            raise HTTPException(409, "Receiver material semantics or runtime compatibility differ")
        if item.get("kind") == "tool" and item.get("content") not in tools:
            raise HTTPException(422, "Material tool binding exceeds manifest scope")
        chosen[key] = item
    expected_refs = [{"id": item["id"], "version": item["version"], "sha256": item["sha256"]} for item in materials]
    dependencies = [dep for item in materials for dep in item.get("dependencies", [])]
    if refs != expected_refs or any(not isinstance(dep, dict) or type(dep.get("id")) is not str or type(dep.get("version")) is not int or type(dep.get("sha256")) is not str
                                   or (dep["id"], dep["version"], dep["sha256"]) not in chosen for dep in dependencies):
        raise HTTPException(409, "Material reference closure is incomplete or changed")
    if set(caps) != {cap for item in materials for cap in item.get("permissions", [])}:
        raise HTTPException(422, "Material permissions do not match the immutable manifest")
    if type(plan.get("syntheticFixture")) is not bool or plan.get("policy") not in {"bounded-synthetic", "admin-review", "read-only-auto"}:
        raise HTTPException(409, "Remote plan requires an explicit supported policy and provenance flag")
    if plan.get("policy") == "bounded-synthetic" and (not store.settings.demo or plan["syntheticFixture"] is not True):
        raise HTTPException(409, "Synthetic policy cannot authorize a production remote plan")
    return plan


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    originRef: str = Field(min_length=1, max_length=100)
    originOwnerId: str = Field(min_length=1, max_length=100)
    originTaskId: UUID
    requestId: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,100}$")
    manifest: dict[str, Any]


class DispatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usageGrant: dict[str, Any]


class PreparedHandoffService:
    """Receiver metadata and the one existing NativeBridge submission owner."""
    def __init__(self, store: Any, auth: Any, bridge: Any, origins: Mapping[str, TrustedOrigin],
                 *, admission_guard: Callable[[str, Any], Any] | None = None):
        self.store, self.auth, self.bridge, self.origins = store, auth, bridge, dict(origins)
        self.admission_guard = admission_guard or store.require_plan_execution
        self.router = APIRouter(prefix="/api/factory/remote-handoffs", route_class=FactoryPublicRoute)
        self._installed = False
        self.initialize()
        self._routes()

    def initialize(self) -> None:
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_remote_handoffs (
            id TEXT PRIMARY KEY, origin_ref TEXT NOT NULL, origin_owner TEXT NOT NULL,
            origin_task TEXT NOT NULL, remote_owner TEXT NOT NULL, request_id TEXT NOT NULL,
            manifest_hash TEXT NOT NULL, configuration_hash TEXT NOT NULL, state TEXT NOT NULL,
            body JSONB NOT NULL, UNIQUE(origin_ref,origin_owner,request_id), UNIQUE(origin_ref,origin_task))""")

    def _origin(self, remote_owner: str, origin_ref: str, origin_owner: str, *, execution: bool = True) -> TrustedOrigin:
        self.auth.require(remote_owner, "run" if execution else "read")
        if execution:
            self.store.require_current_policy()
        origin = self.origins.get(origin_ref)
        if origin is None or origin.identity_map.get(origin_owner) != remote_owner:
            raise HTTPException(404, "Trusted origin identity mapping not found")
        return origin

    def _authority(self, origin: TrustedOrigin, owner: str, task_id: str, manifest_hash: str,
                   plan: Mapping[str, Any], tool: str | None = None, *, native: bool = False) -> HandoffAuthority:
        try:
            current = origin.authorize(owner, task_id, manifest_hash, tool)
            if not isinstance(current, HandoffAuthority):
                raise PermissionError("Origin did not return its current trusted authority")
            _check_budget(current.budget)
            if not set(plan["tools"]) <= origin.tools & current.tools or not set(plan["capabilities"]) <= origin.capabilities & current.capabilities:
                raise PermissionError("Current origin/receiver capability intersection denies the manifest")
            for name in BUDGET_KEYS:
                receiver = {"toolCalls": self.store.settings.max_tool_calls, "maxDepth": 2, "maxChildren": 4,
                            "experimentSeconds": self.store.settings.experiment_timeout_seconds,
                            "outputBytes": self.store.settings.experiment_output_bytes}
                if plan["budget"][name] > min(origin.budget[name], current.budget[name], receiver[name]):
                    raise PermissionError("Current origin/receiver budget intersection denies the manifest")
            if tool is not None and tool not in current.tools & origin.tools:
                raise PermissionError("Current origin denies this protected tool")
            return current
        except HandoffCancellationRequested as error:
            if (error.owner, error.task_id, error.manifest_hash) != (owner, task_id, manifest_hash):
                raise HTTPException(403, "Origin cancellation signal differs from this handoff binding") from error
            if native:
                raise  # This exact trusted intent ends execution; it grants no work.
            raise HTTPException(409, "Origin cancellation ended this immutable handoff") from error
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(403, "Current trusted origin authority denied remote execution") from error

    def _locked(self, key: str, secondary: str | None = None):
        # Existing Store methods own independent quota transactions. A session
        # advisory lock protects multi-phase preparation without nesting them.
        from contextlib import contextmanager

        @contextmanager
        def lock():
            with self.store.engine.connect() as connection:
                keys = sorted({"remote-handoff:" + item for item in (key, secondary) if item is not None})
                for item in keys:
                    connection.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": item})
                connection.commit()
                try:
                    yield
                finally:
                    connection.rollback()
                    for item in reversed(keys):
                        connection.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": item})
                    connection.commit()
        return lock()

    def _row(self, identifier: str, owner: str) -> dict[str, Any]:
        rows = self.store.sql("SELECT * FROM af_remote_handoffs WHERE id=:id AND remote_owner=:owner", id=identifier, owner=owner)
        if not rows:
            raise HTTPException(404, "Remote handoff receipt not found")
        return rows[0]

    def _check_row(self, row: Mapping[str, Any], owner: str, *, tool: str | None = None,
                   execution: bool = True, native: bool = False) -> dict[str, Any]:
        origin = self._origin(owner, row["origin_ref"], row["origin_owner"], execution=execution)
        if row["configuration_hash"] != origin.fingerprint:
            raise HTTPException(409, "Trusted origin configuration changed; handoff cannot be replayed")
        source = row["body"]["manifest"]["plan"]
        if execution:
            current = self._authority(origin, row["origin_owner"], row["origin_task"], row["manifest_hash"], source, tool, native=native)
            proof = self.store.remote_bindings.inspect(row["id"], owner)
            if proof["receiverConfiguration"] != {"revision": origin.configuration_revision, "sha256": origin.fingerprint}:
                raise HTTPException(409, "Receiver binding proof configuration differs from current trust")
            if current.target_revision is not None or current.target_fingerprint is not None:
                if (current.origin_ref != origin.reference or current.receiver_identity != owner or
                        proof["sourceConfiguration"] != {"revision": current.target_revision, "sha256": current.target_fingerprint}):
                    raise HTTPException(409, "Current origin configuration differs from the immutable receiver binding proof")
            grant = row["body"].get("usageGrant")
            if grant is not None and current.usage_grant_sha256 != grant.get("sha256"):
                raise HTTPException(403, "USAGE_REMOTE_ATTESTATION: current origin has no exact durable reservation")
            ledger = getattr(self.store, "usage_ledger", None)
            quote = row["body"].get("receiverUsageCommitment")
            if ledger is not None and quote is not None:
                imported = row["body"]["remotePlan"]
                effective = self.store.execution_bindings.manifest(imported)
                ledger.validate_commitment(imported, quote, effective_bindings=effective)
        return source

    def prepare(self, remote_owner: str, body: PrepareBody) -> dict[str, Any]:
        origin = self._origin(remote_owner, body.originRef, body.originOwnerId)
        source = _manifest(body.manifest, self.store, body.originOwnerId, receiver=True)
        origin_task = str(body.originTaskId)
        key = digest({"origin": body.originRef, "owner": body.originOwnerId, "request": body.requestId})
        task_key = digest({"origin": body.originRef, "task": origin_task})
        with self._locked(key, task_key):
            rows = self.store.sql("SELECT * FROM af_remote_handoffs WHERE origin_ref=:ref AND (origin_owner=:owner AND request_id=:request OR origin_task=:task)",
                                  ref=body.originRef, owner=body.originOwnerId, request=body.requestId, task=origin_task)
            if rows:
                row = rows[0]
                if len(rows) != 1 or row["remote_owner"] != remote_owner or row["origin_task"] != origin_task or row["origin_owner"] != body.originOwnerId or row["request_id"] != body.requestId or row["manifest_hash"] != body.manifest["sha256"]:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: original handoff identity or manifest changed")
                self._check_row(row, remote_owner)
            else:
                authority = self._authority(origin, body.originOwnerId, origin_task, body.manifest["sha256"], source)
                identifier, plan_id = str(uuid4()), str(uuid4())
                service = getattr(self.store, "remote_bindings", None)
                if service is None:
                    raise HTTPException(409, "Receiver binding proof service is unavailable")
                if authority.target_revision is None or authority.target_fingerprint is None:
                    if source.get("bindingManifest", {}).get("connections"):
                        raise HTTPException(409, "Connection mappings require identity-bound current origin configuration")
                    source_configuration = {"revision": origin.configuration_revision, "sha256": origin.fingerprint}
                else:
                    if authority.origin_ref != origin.reference or authority.receiver_identity != remote_owner:
                        raise HTTPException(403, "Current source configuration identity differs from the receiver")
                    source_configuration = {"revision": authority.target_revision, "sha256": authority.target_fingerprint}
                proof = service.prepare(origin, remote_owner, origin_task, identifier, body.manifest,
                    receiver_plan_id=plan_id, source_configuration=source_configuration)
                imported = {**source, "id": plan_id, "ownerId": remote_owner, "createdAt": now(),
                            "remoteHandoff": {"receiptId": identifier, "originRef": body.originRef,
                                              "originTaskId": origin_task, "manifestHash": body.manifest["sha256"],
                                              "bindingProofSha256": proof["sha256"]}}
                imported["fingerprint"] = digest({k: v for k, v in imported.items() if k not in {"id", "createdAt", "fingerprint"}})
                saved = {"manifest": body.manifest, "remotePlan": imported, "remoteTaskId": None, "createdAt": now()}
                ledger = getattr(self.store, "usage_ledger", None)
                if ledger is not None:
                    effective = self.store.execution_bindings.manifest(imported)
                    saved["receiverUsageCommitment"] = ledger.prepare_remote_commitment(imported, effective)
                elif "usageBudget" in source:
                    raise HTTPException(409, "USAGE_REMOTE_LEDGER_REQUIRED: receiver must install durable accounting")
                self.store.sql("INSERT INTO af_remote_handoffs VALUES(:id,:ref,:origin_owner,:origin_task,:remote_owner,:request,:manifest,:configuration,'PREPARING',CAST(:body AS JSONB))",
                               id=identifier, ref=body.originRef, origin_owner=body.originOwnerId, origin_task=origin_task,
                               remote_owner=remote_owner, request=body.requestId, manifest=body.manifest["sha256"],
                               configuration=origin.fingerprint, body=canonical(saved))
                row = self._row(identifier, remote_owner)
            if row["state"] == "PREPARING":
                imported = row["body"]["remotePlan"]
                existing = self.store.sql("SELECT id FROM af_plans WHERE id=:id", id=imported["id"])
                if existing:
                    if self.store.plan(imported["id"], remote_owner) != imported:
                        raise HTTPException(409, "Persisted receiver plan differs from prepared manifest")
                else:
                    self.store.save_plan(imported)
                if self.admission_guard:
                    try:
                        self.admission_guard(remote_owner, imported)
                    except HTTPException as error:
                        if error.status_code == 409 and str(error.detail).startswith("PLAN_REVIEW_REQUIRED:"):
                            # Metadata preparation exposes the exact receiver
                            # plan for independent approval, without a ticket.
                            return {**self._public(row), "receiverReviewRequired": True}
                        raise
                task, _ = self.store.reserve_task(imported, "remote-" + row["id"])
                if task.get("run_id"):
                    raise HTTPException(409, "Preparation encountered an unexpected execution ticket")
                saved = {**row["body"], "remoteTaskId": task["id"]}
                self.store.sql("UPDATE af_remote_handoffs SET state='PREPARED',body=CAST(:body AS JSONB) WHERE id=:id AND state='PREPARING'",
                               id=row["id"], body=canonical(saved))
                self.store.event(task["id"], "remote_prepared", "Remote immutable plan reserved without native execution", {"receiptId": row["id"], "originRef": body.originRef})
            return self._public(self._row(row["id"], remote_owner))

    def _public(self, row: Mapping[str, Any], native: Mapping[str, Any] | None = None) -> dict[str, Any]:
        task_id = row["body"].get("remoteTaskId")
        task = self.store.task(task_id, row["remote_owner"]) if task_id else None
        return {"id": row["id"], "originRef": row["origin_ref"], "originOwnerId": row["origin_owner"],
                "originTaskId": row["origin_task"], "remoteOwnerId": row["remote_owner"], "requestId": row["request_id"],
                "manifestHash": row["manifest_hash"], "remotePlanId": row["body"]["remotePlan"]["id"],
                "remoteTaskId": task_id, "remoteRunId": task.get("run_id") if task else None,
                "state": row["state"], "native": native,
                "receiverBindingProof": self.store.remote_bindings.inspect(row["id"], row["remote_owner"]),
                "syntheticFixture": row["body"]["remotePlan"]["syntheticFixture"],
                **({"receiverPlanSha256": digest(row["body"]["remotePlan"]),
                    "receiverUsageCommitment": copy.deepcopy(row["body"]["receiverUsageCommitment"])}
                   if "receiverUsageCommitment" in row["body"] else {}),
                **({"usageGrant": {"id": row["body"]["usageGrant"]["id"], "sha256": row["body"]["usageGrant"]["sha256"]}}
                   if "usageGrant" in row["body"] else {})}

    async def receipt(self, remote_owner: str, identifier: str) -> dict[str, Any]:
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner, execution=False)
        if not row["body"].get("remoteTaskId"):
            return {**self._public(row), "allStopped": row["state"] == "CANCELLED_NO_DISPATCH",
                    "applicationStatus": "canceled" if row["state"] == "CANCELLED_NO_DISPATCH" else "unknown"}
        task = self.store.task(row["body"]["remoteTaskId"], remote_owner)
        native = None
        if row["state"] in {"UNKNOWN", "ACCEPTED"}:
            native = await self.bridge.find_run(task["id"], remote_owner)
            if native:
                if not task.get("run_id"):
                    self.store.accept(task["id"], native["run_id"])
                elif task["run_id"] != native["run_id"]:
                    raise HTTPException(409, "Receiver native ticket differs from the original task binding")
                # Read recovery of an already-bound ticket must preserve its
                # observed terminal state and any rejected-admission cause.
                self.store.sql("UPDATE af_remote_handoffs SET state='ACCEPTED' WHERE id=:id AND state IN ('UNKNOWN','ACCEPTED')", id=identifier)
                try:
                    native = await self.bridge.detail(native["run_id"], task["id"], remote_owner)
                except HTTPException as error:
                    if error.status_code not in {404, 503}:
                        raise
                    # Queue commit can precede the session row. A failed detail
                    # read never erases a positively identified admission ticket.
                    native = {**native, "detailUnavailable": True}
            # No matching ticket is not proof that admission/effects did not run.
        # A first recovered acknowledgement can change the persisted binding;
        # project its current admission/cancellation facts in this same read.
        task = self.store.task(task["id"], remote_owner)
        result = self._public(self._row(identifier, remote_owner), native)
        effects = self.store.effects(task["id"])
        group = await self.store.delegation.inspect_group(remote_owner, task["id"]) if getattr(self.store, "delegation", None) and native else None
        raw = str(((native or {}).get("queue") or {}).get("status") or (native or {}).get("status", "")).lower()
        from .factory_api import status_of
        from .delegation import application_group_status
        application_status = "canceled" if row["state"] == "CANCELLED_NO_DISPATCH" else status_of(task, native or {}, effects, self.store.events(task["id"]))
        if group:
            application_status = application_group_status(application_status, group)
            if task["cancel_requested"]:
                # Native cancellation establishes stop, not success or cause.
                # Preserve the group's full-history protected/native failure
                # facts when trusted cleanup follows an earlier failure.
                failed = group["parent"]["failed"] or any(child["failed"] for child in group["children"])
                application_status = ("failed" if failed else "canceled") if group["allStopped"] else "unknown" if group["unknown"] else "canceling"
        result.update(effects=effects, artifacts=self.store.artifacts(task["id"]), group=group,
                      applicationStatus=application_status,
                      allStopped=bool(row["state"] == "CANCELLED_NO_DISPATCH" or native and raw in {"completed", "failed", "cancelled", "error"}
                                      and not any(effect["status"] == "UNKNOWN" for effect in effects)
                                      and (group is None or group["allStopped"])))
        if row["body"].get("usageGrant") is not None:
            result["usageStatement"] = self.store.usage_ledger.remote_statement(remote_owner, task["id"], identifier,
                all_stopped=result["allStopped"])
        return result

    async def by_request(self, remote_owner: str, origin_ref: str, origin_owner: str, request_id: str) -> dict[str, Any]:
        self._origin(remote_owner, origin_ref, origin_owner, execution=False)
        rows = self.store.sql("SELECT id FROM af_remote_handoffs WHERE origin_ref=:ref AND origin_owner=:origin AND remote_owner=:owner AND request_id=:request",
                              ref=origin_ref, origin=origin_owner, owner=remote_owner, request=request_id)
        if not rows:
            raise HTTPException(404, "Original handoff receipt is not observable")
        return await self.receipt(remote_owner, rows[0]["id"])

    def _task(self, row: Mapping[str, Any], remote_task_id: str | None = None) -> dict[str, Any]:
        root_id = row["body"].get("remoteTaskId")
        if not root_id:
            raise HTTPException(409, "Receiver preparation has not reserved an execution task")
        identifier = remote_task_id or root_id
        if identifier != root_id:
            delegation = getattr(self.store, "delegation", None)
            if not delegation or identifier not in {link.get("child_id") for link in delegation._descendants(root_id)}:
                raise HTTPException(404, "Task is outside this receiver-owned handoff tree")
        return self.store.task(identifier, row["remote_owner"])

    async def detail(self, remote_owner: str, identifier: str, remote_task_id: str | None = None) -> dict[str, Any]:
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner, execution=False)
        task = self._task(row, remote_task_id)
        from .factory_api import FactoryAPI
        detail = await FactoryAPI(self.store.settings, self.store, self.auth, self.bridge).detail(task)
        detail["handoff"] = await self.receipt(remote_owner, identifier)
        return detail

    def events(self, remote_owner: str, identifier: str, remote_task_id: str | None = None, *, cursor=None, limit=100):
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner, execution=False)
        task = self._task(row, remote_task_id)
        return self.store.event_replay.page(remote_owner, task["id"], cursor=cursor, limit=limit)

    async def cancel(self, remote_owner: str, identifier: str, remote_task_id: str | None = None) -> dict[str, Any]:
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner, execution=False)
        self.auth.require(remote_owner, "run")
        # A positive CAS proves no dispatch boundary was crossed, unlike a
        # missing ticket after UNKNOWN. Only that proof may settle preparation.
        if remote_task_id is None or remote_task_id == row["body"].get("remoteTaskId"):
            key = digest({"origin": row["origin_ref"], "owner": row["origin_owner"], "request": row["request_id"]})
            task_key = digest({"origin": row["origin_ref"], "task": row["origin_task"]})
            with self._locked(key, task_key):
                row = self._row(identifier, remote_owner)
                no_dispatch = self.store.sql("UPDATE af_remote_handoffs SET state='CANCELLED_NO_DISPATCH' WHERE id=:id AND state IN ('PREPARING','PREPARED') RETURNING id", id=identifier)
                if no_dispatch and row["body"].get("remoteTaskId"):
                    task = self._task(row)
                    self.store.request_cancel(task["id"])
                    self.store.admission_failed(task["id"], "Receiver canceled before its durable dispatch boundary; no native execution")
            if no_dispatch:
                return {"receipt": await self.receipt(remote_owner, identifier), "group": None}
        task = self._task(row, remote_task_id)
        delegation = getattr(self.store, "delegation", None)
        if delegation is None:
            raise HTTPException(503, "Receiver descendant/experiment cancellation service is unavailable")
        group = await delegation.cascade_cancel(remote_owner, task["id"])
        return {**group, "receipt": await self.receipt(remote_owner, identifier)}

    async def _factory_action(self, remote_owner: str, identifier: str, action: str, body: dict[str, Any],
                              remote_task_id: str | None = None) -> dict[str, Any]:
        if action not in {"answer", "approve", "children"}:
            raise HTTPException(422, "Unsupported guarded factory continuation")
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner)
        task = self._task(row, remote_task_id)
        # Root approval does not skip current receiver policy; children use its
        # actual persisted ancestor/native mandate, never a caller's parent ID.
        context = SimpleNamespace(session_id=task["id"], run_id=task["run_id"], user_id=remote_owner,
            session_state={"factory_envelope": {"plan_ref": task["plan_id"], "user_id": remote_owner,
                "task_id": task["id"], "request_id": task["request_id"]}})
        self.store.require_plan_execution(remote_owner, self.store.plan(task["plan_id"], remote_owner), run_context=context)
        native_context = INTERNAL_NATIVE.set(False)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.bridge._app), base_url="http://receiver.factory.invalid",
                                         headers={"Authorization": "Bearer " + self.auth._issue_native_token(remote_owner)}, timeout=30) as client:
                response = await client.post("/api/factory/jobs/" + quote(task["id"], safe="") + "/" + action, json=body)
        finally:
            INTERNAL_NATIVE.reset(native_context)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, "Scoped receiver Factory action was rejected")
        value = response.json()
        if not isinstance(value, dict):
            raise HTTPException(502, "Scoped receiver action returned an invalid receipt")
        return value

    async def children(self, remote_owner: str, identifier: str, remote_task_id: str | None = None) -> list[dict[str, Any]]:
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner, execution=False)
        task = self._task(row, remote_task_id)
        return await self.store.delegation.children(remote_owner, task["id"])

    def artifact(self, remote_owner: str, identifier: str, artifact_id: str, remote_task_id: str | None = None) -> tuple[dict[str, Any], bytes]:
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner, execution=False)
        task = self._task(row, remote_task_id)
        return self.store.artifact(task["id"], artifact_id)

    async def dispatch(self, remote_owner: str, identifier: str, usage_grant: dict[str, Any] | None = None) -> dict[str, Any]:
        row = self._row(identifier, remote_owner)
        self._check_row(row, remote_owner)
        if row["state"] in {"UNKNOWN", "ACCEPTED"}:
            return await self.receipt(remote_owner, identifier)
        plan = self.store.plan(row["body"]["remotePlan"]["id"], remote_owner)
        if plan != row["body"]["remotePlan"]:
            raise HTTPException(409, "Receiver immutable prepared plan changed")
        if self.admission_guard:
            self.admission_guard(remote_owner, plan)
        task = self.store.task(row["body"]["remoteTaskId"], remote_owner) if row["body"].get("remoteTaskId") else None
        if task is None or task["cancel_requested"] or task["terminal"]:
            raise HTTPException(409, "Prepared task is unavailable or canceled")
        ledger = getattr(self.store, "usage_ledger", None)
        if ledger is not None:
            source = row["body"]["manifest"]["plan"]
            quote = row["body"].get("receiverUsageCommitment")
            if quote is None or not isinstance(usage_grant, dict) or len(canonical(usage_grant).encode()) > 16384:
                raise HTTPException(409, "USAGE_REMOTE_GRANT_REQUIRED: exact attested source allocation required")
            origin = self._origin(remote_owner, row["origin_ref"], row["origin_owner"])
            authority = self._authority(origin, row["origin_owner"], row["origin_task"], row["manifest_hash"], source)
            if (authority.usage_grant_sha256 != usage_grant.get("sha256")
                    or usage_grant.get("id") != identifier or authority.target_ref is None):
                raise HTTPException(403, "USAGE_REMOTE_ATTESTATION: current origin has no exact durable reservation")
            source_budget = source.get("usageBudget")
            ledger.import_remote_grant(remote_owner, task["id"], usage_grant,
                expected_origin_ref=row["origin_ref"], expected_target_ref=authority.target_ref,
                expected_origin_task_id=row["origin_task"], expected_origin_owner=row["origin_owner"],
                expected_source_plan_sha256=row["manifest_hash"],
                expected_source_commitment_sha256=source_budget.get("sha256") if source_budget else None)
            old_grant = row["body"].get("usageGrant")
            if old_grant is not None and old_grant != usage_grant:
                raise HTTPException(409, "USAGE_REMOTE_GRANT_CONFLICT: immutable dispatch allocation changed")
            saved = {**row["body"], "usageGrant": copy.deepcopy(usage_grant)}
            self.store.sql("UPDATE af_remote_handoffs SET body=CAST(:body AS JSONB) WHERE id=:id AND state='PREPARED'",
                id=identifier, body=canonical(saved))
            row = self._row(identifier, remote_owner)
        elif usage_grant is not None:
            raise HTTPException(409, "USAGE_REMOTE_LEDGER_REQUIRED: receiver accounting unavailable")
        # CAS commits BEFORE any native HTTP call. Concurrent/restarted callers
        # read the receipt and cannot reacquire a submission attempt.
        changed = self.store.sql("UPDATE af_remote_handoffs SET state='UNKNOWN' WHERE id=:id AND state='PREPARED' RETURNING id", id=identifier)
        if not changed:
            if self._row(identifier, remote_owner)["state"] not in {"UNKNOWN", "ACCEPTED"}:
                raise HTTPException(409, "Remote handoff is not dispatchable")
            return await self.receipt(remote_owner, identifier)
        self.store.admission_unknown(task["id"])
        self.store.event(task["id"], "remote_dispatch_boundary", "One native submission attempt begun; uncertain results retain capacity", {"receiptId": identifier})
        try:
            accepted = await self.bridge.submit({**plan, "task_id": task["id"]}, remote_owner, task["request_id"])
            run_id = accepted.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise HTTPException(502, "Native admission receipt has no run identity")
            self.store.accept(task["id"], run_id)
            self.store.sql("UPDATE af_remote_handoffs SET state='ACCEPTED' WHERE id=:id", id=identifier)
        except Exception as error:
            # Even a lost worker/HTTP reply after commit cannot authorize replay.
            raise HTTPException(503, "REMOTE_DISPATCH_UNKNOWN: recover by owner-bound receipt read; do not replay") from error
        return await self.receipt(remote_owner, identifier)

    def authorize(self, context: Any, tool: str | None = None) -> None:
        """Synchronous guard called by native bind AND every direct tool entrypoint."""
        task = self.store.task(context.session_id, context.user_id)
        root = task
        seen = {root["id"]}
        while getattr(self.store, "delegation", None):
            link = self.store.delegation._link(root["id"])
            if link is None:
                break
            root = self.store.task(link["parent_id"], context.user_id)
            if root["id"] in seen or len(seen) > 2:
                raise PermissionError("Invalid receiver-local delegation ancestry")
            seen.add(root["id"])
        plan = self.store.plan(root["plan_id"], context.user_id)
        binding = plan.get("remoteHandoff")
        if not binding:
            # An imported child cannot execute as a standalone unlinked root.
            own = self.store.plan(task["plan_id"], context.user_id)
            if own.get("remoteHandoff"):
                raise PermissionError("Receiver handoff ancestry is unavailable")
            return
        row = self._row(binding["receiptId"], context.user_id)
        if row["body"].get("remoteTaskId") != root["id"] or row["body"]["remotePlan"] != plan or row["state"] not in {"UNKNOWN", "ACCEPTED"}:
            raise PermissionError("Remote handoff task/plan/dispatch binding is unavailable")
        self._check_row(row, context.user_id, tool=tool, native=True)

    def install_guard(self) -> None:
        if self._installed:
            return
        def guard(owner, plan, context, name):
            if context is not None:
                self.authorize(context, name)
            elif plan.get("remoteHandoff"):
                row = self._row(plan["remoteHandoff"]["receiptId"], owner)
                if self.store.plan(plan["id"], owner) != row["body"]["remotePlan"]:
                    raise PermissionError("Imported admission plan differs from its trusted receiver manifest")
                self._check_row(row, owner, native=True)

        self.store.execution_guards["remote_receiver"] = guard
        self._installed = True

    def _routes(self) -> None:
        def owner(request, execution=False):
            user = self.auth.user(request)
            self.auth.require(user["id"], "run" if execution else "read")
            return user["id"]

        @self.router.post("/prepare", status_code=201)
        def prepare(body: PrepareBody, request: Request):
            return self.prepare(owner(request, True), body)

        @self.router.get("/receipts/by-request")
        async def by_request(request: Request, originRef: str, originOwnerId: str, requestId: str):
            return await self.by_request(owner(request), originRef, originOwnerId, requestId)

        @self.router.get("/{identifier}")
        async def receipt(identifier: str, request: Request):
            return await self.receipt(owner(request), identifier)

        @self.router.post("/{identifier}/dispatch", status_code=202)
        async def dispatch(identifier: str, request: Request, body: DispatchBody | None = None):
            return await self.dispatch(owner(request, True), identifier, body.usageGrant if body else None)

        @self.router.get("/{identifier}/detail")
        async def detail(identifier: str, request: Request, remoteTaskId: str | None = None):
            return await self.detail(owner(request), identifier, remoteTaskId)

        @self.router.get("/{identifier}/events")
        def events(identifier: str, request: Request, remoteTaskId: str | None = None,
                   cursor: str | None = Query(default=None, max_length=4096),
                   limit: int = Query(default=100, ge=1, le=1000)):
            return self.events(owner(request), identifier, remoteTaskId, cursor=cursor, limit=limit)

        @self.router.post("/{identifier}/cancel")
        async def cancel(identifier: str, request: Request, remoteTaskId: str | None = None):
            return await self.cancel(owner(request, True), identifier, remoteTaskId)

        @self.router.post("/{identifier}/answer")
        async def answer(identifier: str, body: dict[str, Any], request: Request, remoteTaskId: str | None = None):
            return await self._factory_action(owner(request, True), identifier, "answer", body, remoteTaskId)

        @self.router.post("/{identifier}/approve")
        async def approve(identifier: str, body: dict[str, Any], request: Request, remoteTaskId: str | None = None):
            return await self._factory_action(owner(request, True), identifier, "approve", body, remoteTaskId)

        @self.router.post("/{identifier}/children")
        async def delegate(identifier: str, body: dict[str, Any], request: Request, remoteTaskId: str | None = None):
            return await self._factory_action(owner(request, True), identifier, "children", body, remoteTaskId)

        @self.router.get("/{identifier}/children")
        async def children(identifier: str, request: Request, remoteTaskId: str | None = None):
            return await self.children(owner(request), identifier, remoteTaskId)

        @self.router.get("/{identifier}/artifacts/{artifact_id}")
        def artifact(identifier: str, artifact_id: str, request: Request, remoteTaskId: str | None = None):
            metadata, raw = self.artifact(owner(request), identifier, artifact_id, remoteTaskId)
            return Response(raw, media_type=metadata["mediaType"], headers={"X-Content-SHA256": metadata["sha256"],
                            "Cache-Control": "private, no-store", "Content-Disposition": "attachment; filename*=UTF-8''" + quote(metadata["name"])})


@dataclass(frozen=True)
class HandoffTarget:
    """Operator-held HTTP connection reference and mapped native credentials."""
    reference: str
    origin_ref: str
    base_url: str
    identity_map: Mapping[str, str]
    headers: Callable[[str], Mapping[str, str]] = field(repr=False)
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    configuration_revision: str = "1"

    def __post_init__(self):
        value = urlsplit(self.base_url)
        if value.scheme not in {"http", "https"} or not value.hostname or value.username or value.password or value.query or value.fragment or not self.identity_map or not callable(self.headers):
            raise ValueError("Target requires an operator HTTP origin, identity mapping and trusted credential callback")
        try:
            loopback = ipaddress.ip_address(value.hostname).is_loopback
        except ValueError:
            loopback = value.hostname.lower() == "localhost"
        if value.scheme == "http" and not loopback and self.transport is None:
            raise ValueError("Non-loopback remote targets require HTTPS")

    @property
    def fingerprint(self):
        return digest({"reference": self.reference, "origin": self.origin_ref, "url": self.base_url,
                       "mapping": dict(self.identity_map), "revision": self.configuration_revision})


class TrustedHandoffClient:
    """Origin reservation chooses one server; origin never owns its native ticket."""
    def __init__(self, store: Any, auth: Any, targets: Mapping[str, HandoffTarget],
                 *, admission_guard: Callable[[str, Any], Any] | None = None):
        self.store, self.auth, self.targets = store, auth, dict(targets)
        self.admission_guard = admission_guard or store.require_plan_execution
        self._installed = False
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_remote_placements (
            task_id TEXT PRIMARY KEY REFERENCES af_tasks(id), owner_id TEXT NOT NULL, target_ref TEXT NOT NULL,
            request_id TEXT NOT NULL, manifest_hash TEXT NOT NULL, configuration_hash TEXT NOT NULL,
            state TEXT NOT NULL, body JSONB NOT NULL, UNIQUE(owner_id,request_id))""")

    def reserve(self, owner: str, plan_id: str, target_ref: str, request_id: str) -> dict[str, Any]:
        self.auth.require(owner, "run")
        self.store.require_current_policy()
        target = self.targets.get(target_ref)
        if target is None or owner not in target.identity_map:
            raise HTTPException(404, "Trusted execution target not found")
        if not REQUEST.fullmatch(request_id):
            raise HTTPException(422, "A bounded stable remote request key is required")
        plan = self.store.plan(plan_id, owner)
        _manifest(plan_manifest(plan), self.store, owner)
        if self.admission_guard:
            self.admission_guard(owner, plan)
        # Child placement is deliberately unsupported: its root-selected server
        # owns the whole shared-budget/authority tree until cross-server fencing.
        if plan.get("delegation") or plan.get("remoteHandoff"):
            raise HTTPException(409, "Delegation must stay on its initially selected receiver")
        task, _ = self.store.reserve_task(plan, request_id)
        if task.get("run_id"):
            raise HTTPException(409, "A locally executing task cannot switch execution servers")
        manifest = plan_manifest(plan)
        saved = {"manifest": manifest, "receipt": None, "dispatchAttempted": False, "createdAt": now()}
        rows = self.store.sql("INSERT INTO af_remote_placements VALUES(:task,:owner,:target,:request,:manifest,:configuration,'RESERVED',CAST(:body AS JSONB)) ON CONFLICT DO NOTHING RETURNING task_id",
                              task=task["id"], owner=owner, target=target_ref, request=request_id,
                              manifest=manifest["sha256"], configuration=target.fingerprint, body=canonical(saved))
        row = self._row(owner, task["id"])
        if row["target_ref"] != target_ref or row["manifest_hash"] != manifest["sha256"] or row["configuration_hash"] != target.fingerprint:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT: initially selected server or manifest changed")
        if rows:
            self.store.event(task["id"], "remote_selected", "One receiver selected; origin has a metadata reservation and no native run", {"targetRef": target_ref})
        return row

    def _row(self, owner: str, task_id: str) -> dict[str, Any]:
        rows = self.store.sql("SELECT * FROM af_remote_placements WHERE task_id=:id AND owner_id=:owner", id=task_id, owner=owner)
        if not rows:
            raise HTTPException(404, "Owner-bound remote placement not found")
        return rows[0]

    def _target(self, owner: str, row: Mapping[str, Any], *, execution: bool = True,
                native_cancellation: bool = False) -> HandoffTarget:
        self.auth.require(owner, "run" if execution else "read")
        if execution:
            self.store.require_current_policy()
        target = self.targets.get(row["target_ref"])
        if target is None or owner not in target.identity_map or target.fingerprint != row["configuration_hash"]:
            raise HTTPException(409, "Trusted target identity/configuration is no longer valid")
        task = self.store.task(row["task_id"], owner)
        plan = self.store.plan(task["plan_id"], owner)
        if task["run_id"] or digest(plan) != row["manifest_hash"]:
            raise HTTPException(409, "Origin task/manifest authority is unavailable")
        if execution and task["cancel_requested"]:
            # The trusted authority callback may observe cancellation only on
            # this second read. Preserve its exact verified cleanup signal;
            # other target callers continue to receive an HTTP conflict.
            if native_cancellation and not self.store.failure_cleanup_requested(task["id"]) and not self.store.has_failures(task["id"]):
                raise HandoffCancellationRequested(owner, task["id"], row["manifest_hash"])
            raise HTTPException(409, "Origin task/manifest authority is unavailable")
        if execution and self.admission_guard:
            self.admission_guard(owner, plan)
        return target

    async def _request(self, owner: str, target: HandoffTarget, method: str, path: str, *, binary: bool = False, **kwargs) -> Any:
        # In-process test transports must model a real HTTP trust boundary too.
        # Caller native context cannot make a receiver's public ingress internal.
        native_context = INTERNAL_NATIVE.set(False)
        try:
            async with httpx.AsyncClient(base_url=target.base_url.rstrip("/") + "/", transport=target.transport,
                                         headers={**dict(target.headers(owner)), "Accept-Encoding": "identity"},
                                         timeout=20, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, path.lstrip("/"), **kwargs) as streamed:
                    limit = (16384 if streamed.is_redirect or streamed.status_code >= 400 else
                             self.store.settings.experiment_output_bytes if binary else 2 * 1024 * 1024)
                    if streamed.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise HTTPException(502, "Remote compressed responses are unsupported")
                    advertised = streamed.headers.get("Content-Length")
                    if advertised is not None:
                        try:
                            declared = int(advertised)
                        except ValueError as error:
                            raise HTTPException(502, "Remote response length is invalid") from error
                        if declared < 0 or declared > limit:
                            raise HTTPException(502, "Remote response exceeds the operator ceiling")
                    raw = bytearray()
                    async for chunk in streamed.aiter_raw():
                        if len(raw) + len(chunk) > limit:
                            raise HTTPException(502, "Remote response exceeds the operator ceiling")
                        raw.extend(chunk)
                    result = httpx.Response(streamed.status_code, headers=streamed.headers, content=bytes(raw))
        except httpx.HTTPError as error:
            raise HTTPException(503, "REMOTE_ACK_UNKNOWN: read the original owner-bound receipt") from error
        finally:
            INTERNAL_NATIVE.reset(native_context)
        if result.is_redirect or result.status_code >= 400:
            code = None
            # Only fixed public protocol codes cross this error boundary.
            # Receiver exception/provider text can contain private handles.
            allowed = {"REMOTE_BINDING_" + name for name in ("SOURCE", "CONFIGURATION", "IDENTITY", "REQUIRED",
                "AMBIGUOUS", "CHANGED", "INTEGRITY", "SCOPE", "ANCESTRY", "UNBOUND", "CONFLICT")} | {
                "ORIGIN_AUTHORITY_" + name for name in ("BINDING_DENIED", "CONFIG_CHANGED", "DENIED", "UNAVAILABLE",
                    "AUTH_UNAVAILABLE", "SCHEMA_INVALID", "RESPONSE_INVALID")} | {
                "PLAN_REVIEW_REQUIRED", "PLAN_REVIEW_DENIED", "PLAN_REVIEW_EXPIRED", "POLICY_UNSET"} | {
                "USAGE_" + name for name in ("COMMITMENT_SCHEMA", "COMMITMENT_INTEGRITY", "BINDING_INTEGRITY",
                    "PRICE_UNAVAILABLE", "CURRENCY_MISMATCH", "APPROVAL_CEILING", "PRICING_DRIFT", "BUDGET_EXHAUSTED",
                    "REMOTE_LEDGER_REQUIRED", "REMOTE_QUOTE_REQUIRED", "REMOTE_QUOTE_INTEGRITY", "REMOTE_PRICE_MISMATCH",
                    "REMOTE_MODEL_MISMATCH", "REMOTE_SCOPE", "REMOTE_GRANT_REQUIRED", "REMOTE_ATTESTATION",
                    "REMOTE_COMMITMENT_CONFLICT", "REMOTE_GRANT_INTEGRITY", "REMOTE_GRANT_IDENTITY", "REMOTE_GRANT_SOURCE")}
            if result.status_code >= 400 and len(result.content) <= 16384:
                try:
                    value = result.json()
                    candidate = value.get("code") if isinstance(value, dict) else None
                    if isinstance(candidate, str) and candidate in allowed:
                        code = candidate
                except ValueError:
                    pass
            message = (code + ": " if code else "") + "Trusted receiver rejected the operation"
            raise HTTPException(result.status_code if result.status_code >= 400 else 502, message)
        if binary:
            if len(result.content) > self.store.settings.experiment_output_bytes:
                raise HTTPException(502, "Remote artifact exceeds the operator output ceiling")
            return {"content": result.content, "sha256": result.headers.get("X-Content-SHA256")}
        try:
            body = result.json()
        except ValueError as error:
            raise HTTPException(502, "Remote receipt is invalid JSON") from error
        if not isinstance(body, (dict, list)):
            raise HTTPException(502, "Remote response must be a bounded object or list")
        return body

    def _save_receipt(self, row: Mapping[str, Any], target: HandoffTarget, receipt: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(receipt, dict):
            raise HTTPException(502, "Remote receipt must be an object")
        for key, expected in {"originRef": target.origin_ref, "originOwnerId": row["owner_id"], "originTaskId": row["task_id"],
                              "remoteOwnerId": target.identity_map[row["owner_id"]], "requestId": row["request_id"], "manifestHash": row["manifest_hash"]}.items():
            if receipt.get(key) != expected:
                raise HTTPException(409, "Remote receipt identity differs from the original admission")
        proof = receipt.get("receiverBindingProof")
        expected_keys = {"schema", "originRef", "receiptId", "originTaskId", "originOwner", "receiverOwner", "receiverPlanId",
                         "manifestHash", "sourceConfiguration", "receiverConfiguration", "entries", "sha256"}
        if not isinstance(proof, dict) or set(proof) != expected_keys:
            raise HTTPException(502, "Receiver receipt has no exact immutable local binding proof")
        original = row["body"]["manifest"]["plan"]
        full_proof = {key: value for key, value in proof.items() if key != "sha256"} | {
            "sourcePlan": original, "sourceBindings": original["executionBindings"]}
        if digest(full_proof) != proof["sha256"] or any(proof.get(key) != value for key, value in {
                "schema": 1, "originRef": target.origin_ref, "receiptId": receipt.get("id"),
                "originTaskId": row["task_id"], "originOwner": row["owner_id"],
                "receiverOwner": target.identity_map[row["owner_id"]], "receiverPlanId": receipt.get("remotePlanId"),
                "manifestHash": row["manifest_hash"],
                "sourceConfiguration": {"revision": target.configuration_revision, "sha256": target.fingerprint}}.items()):
            raise HTTPException(409, "Receiver binding proof integrity or source identity/configuration differs")
        try:
            UUID(str(receipt["id"]))
            UUID(str(receipt["remotePlanId"]))
            if receipt.get("remoteTaskId"):
                UUID(str(receipt["remoteTaskId"]))
        except (ValueError, KeyError) as error:
            raise HTTPException(502, "Remote receipt identities are invalid") from error
        quote = receipt.get("receiverUsageCommitment")
        if quote is not None:
            _usage_commitment(quote)
            if not isinstance(receipt.get("receiverPlanSha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", receipt["receiverPlanSha256"]):
                raise HTTPException(409, "USAGE_REMOTE_PLAN_INTEGRITY: receiver quote requires exact prepared plan hash")
            effective = {"schema": 1, "tools": [], "knowledge": []}
            for entry in proof["entries"]:
                kind = entry["kind"]
                if kind in {"tool", "knowledge"}:
                    effective[kind + ("s" if kind == "tool" else "")].append(entry["effectiveSpec"])
                else:
                    effective[kind] = entry["effectiveSpec"]
            effective["sha256"] = digest(effective)
            _usage_commitment(quote, bindings=effective)
        with self.store.engine.begin() as connection:
            current = connection.execute(text("SELECT * FROM af_remote_placements WHERE task_id=:id AND owner_id=:owner FOR UPDATE"),
                                         {"id": row["task_id"], "owner": row["owner_id"]}).mappings().first()
            if current is None:
                raise HTTPException(404, "Owner-bound remote placement disappeared")
            previous = current["body"].get("receipt")
            if previous and (previous.get("receiverBindingProof", {}).get("sha256") != proof["sha256"]
                             or any(previous.get(key) != receipt.get(key) for key in ("id", "remotePlanId"))
                             or previous.get("remoteTaskId") is not None and previous["remoteTaskId"] != receipt.get("remoteTaskId")
                             or previous.get("remoteRunId") is not None and previous["remoteRunId"] != receipt.get("remoteRunId")):
                raise HTTPException(409, "Receiver replaced the original prepared task or native ticket")
            if previous and any(previous.get(key) != receipt.get(key) for key in ("receiverUsageCommitment", "receiverPlanSha256")):
                raise HTTPException(409, "USAGE_REMOTE_QUOTE_CHANGED: receiver replaced its original immutable quote")
            grant = current["body"].get("usageGrant")
            reported_grant = receipt.get("usageGrant")
            if reported_grant is not None and (not grant or reported_grant != {"id": grant["id"], "sha256": grant["sha256"]}):
                raise HTTPException(409, "USAGE_REMOTE_GRANT_IDENTITY: receipt differs from original source allocation")
            statement = receipt.get("usageStatement")
            if statement is not None:
                if not isinstance(statement, dict) or grant is None or reported_grant is None or statement.get("grantId") != receipt["id"]:
                    raise HTTPException(409, "USAGE_REMOTE_STATEMENT_IDENTITY: accounting has no attested original grant")
                old_statement = previous.get("usageStatement") if previous else None
                if old_statement and statement.get("sequence", 0) < old_statement["sequence"]:
                    raise HTTPException(409, "USAGE_REMOTE_STATEMENT_STALE: cached cumulative accounting cannot regress")
                if statement.get("allStopped") is True and receipt.get("allStopped") is not True:
                    raise HTTPException(409, "USAGE_REMOTE_STATEMENT_STOP: accounting requires positive native/effect/tree stop")
            body = {**current["body"], "receipt": dict(receipt)}
            local_state = receipt.get("state", "UNKNOWN")
            if body.get("dispatchAttempted") and local_state in {"PREPARING", "PREPARED"}:
                local_state = "DISPATCH_UNKNOWN"
            connection.execute(text("UPDATE af_remote_placements SET state=:state,body=CAST(:body AS JSONB) WHERE task_id=:id"),
                               {"id": row["task_id"], "state": local_state, "body": canonical(body)})
        if receipt.get("usageStatement") is not None:
            ledger = getattr(self.store, "usage_ledger", None)
            if ledger is None:
                raise HTTPException(409, "USAGE_REMOTE_LEDGER_REQUIRED: origin settlement unavailable")
            ledger.apply_remote_statement(row["owner_id"], row["task_id"], receipt["usageStatement"])
        elif receipt.get("state") == "CANCELLED_NO_DISPATCH" and grant is not None:
            ledger = getattr(self.store, "usage_ledger", None)
            if ledger is None:
                raise HTTPException(409, "USAGE_REMOTE_LEDGER_REQUIRED: origin reclaim unavailable")
            # This exact receiver CAS is positive no-admission evidence; missing
            # tickets, generic cancellation or UNKNOWN never release money.
            ledger.reclaim_remote_no_dispatch(row["owner_id"], row["task_id"], receipt["id"], dict(receipt))
        raw = str(((receipt.get("native") or {}).get("queue") or {}).get("status") or (receipt.get("native") or {}).get("status", "unknown")).lower()
        # Origin capacity is released only by positive receiver stop evidence,
        # including descendants/effects; no origin native ticket is fabricated.
        self.store.observed(self.store.task(row["task_id"], row["owner_id"]), receipt.get("applicationStatus", raw), receipt.get("allStopped") is True)
        return {**receipt, "originDispatchState": local_state}

    async def prepare(self, owner: str, task_id: str) -> dict[str, Any]:
        row = self._row(owner, task_id)
        target = self._target(owner, row)
        if row["body"].get("dispatchAttempted") or row["state"] not in {"RESERVED", "PREPARE_UNKNOWN", "PREPARING"}:
            return await self.receipt(owner, task_id)
        self.store.sql("UPDATE af_remote_placements SET state='PREPARE_UNKNOWN' WHERE task_id=:id", id=task_id)
        receipt = await self._request(owner, target, "POST", "/api/factory/remote-handoffs/prepare", json={
            "originRef": target.origin_ref, "originOwnerId": owner, "originTaskId": task_id,
            "requestId": row["request_id"], "manifest": row["body"]["manifest"]})
        return self._save_receipt(row, target, receipt)

    async def receipt(self, owner: str, task_id: str) -> dict[str, Any]:
        row = self._row(owner, task_id)
        target = self._target(owner, row, execution=False)
        previous = row["body"].get("receipt")
        if previous:
            path = "/api/factory/remote-handoffs/" + quote(previous["id"], safe="")
            receipt = await self._request(owner, target, "GET", path)
        else:
            receipt = await self._request(owner, target, "GET", "/api/factory/remote-handoffs/receipts/by-request",
                                          params={"originRef": target.origin_ref, "originOwnerId": owner, "requestId": row["request_id"]})
        return self._save_receipt(row, target, receipt)

    async def dispatch(self, owner: str, task_id: str) -> dict[str, Any]:
        row = self._row(owner, task_id)
        target = self._target(owner, row)
        previous = row["body"].get("receipt")
        if row["body"].get("dispatchAttempted") or not previous or row["state"] in {"UNKNOWN", "DISPATCH_UNKNOWN", "ACCEPTED"}:
            return await self.receipt(owner, task_id)
        ledger = getattr(self.store, "usage_ledger", None)
        grant = None
        if ledger is not None:
            receiver_quote = previous.get("receiverUsageCommitment")
            if previous.get("state") != "PREPARED" or not previous.get("remoteTaskId") or receiver_quote is None:
                raise HTTPException(409, "USAGE_REMOTE_QUOTE_REQUIRED: exact prepared receiver identity and quote required")
            grant = ledger.allocate_remote(owner, task_id, previous["id"], origin_ref=target.origin_ref,
                target_ref=target.reference, receiver_owner=target.identity_map[owner],
                receiver_task_id=previous["remoteTaskId"], receiver_plan_sha256=previous["receiverPlanSha256"],
                receiver_commitment=receiver_quote)
            row = self._row(owner, task_id)
        body = {**row["body"], "dispatchAttempted": True, **({"usageGrant": grant} if grant else {})}
        changed = self.store.sql("UPDATE af_remote_placements SET state='DISPATCH_UNKNOWN',body=CAST(:body AS JSONB) WHERE task_id=:id AND state='PREPARED' RETURNING task_id", id=task_id, body=canonical(body))
        if not changed:
            raise HTTPException(409, "Origin placement is not prepared for dispatch")
        dispatch_options: dict[str, Any] = {"json": {"usageGrant": grant}} if grant else {}
        receipt = await self._request(owner, target, "POST", "/api/factory/remote-handoffs/" + quote(previous["id"], safe="") + "/dispatch",
            **dispatch_options)
        return self._save_receipt(self._row(owner, task_id), target, receipt)

    async def detail(self, owner: str, task_id: str, remote_task_id: str | None = None) -> dict[str, Any]:
        row, target, identifier = await self._binding(owner, task_id, execution=False)
        value = await self._request(owner, target, "GET", "/api/factory/remote-handoffs/" + identifier + "/detail",
                                    params={"remoteTaskId": remote_task_id} if remote_task_id else {})
        if not isinstance(value, dict) or not isinstance(value.get("handoff"), dict):
            raise HTTPException(502, "Remote detail has no owner-bound handoff receipt")
        self._save_receipt(row, target, value["handoff"])
        return value

    async def _binding(self, owner: str, task_id: str, *, execution: bool) -> tuple[dict[str, Any], HandoffTarget, str]:
        row = self._row(owner, task_id)
        target = self._target(owner, row, execution=execution)
        receipt = row["body"].get("receipt")
        if not receipt:
            receipt = await self.receipt(owner, task_id)
            row = self._row(owner, task_id)
        return row, target, quote(receipt["id"], safe="")

    async def cancel(self, owner: str, task_id: str, remote_task_id: str | None = None) -> dict[str, Any]:
        self.auth.require(owner, "run")
        row = self._row(owner, task_id)
        self._target(owner, row, execution=False)
        if remote_task_id is None:
            # Persist intent even when a lost prepare reply first requires a
            # receipt lookup. An unreachable receiver cannot undo cancellation.
            self.store.request_cancel(task_id)
        row, target, identifier = await self._binding(owner, task_id, execution=False)
        result = await self._request(owner, target, "POST", "/api/factory/remote-handoffs/" + identifier + "/cancel",
                                     params={"remoteTaskId": remote_task_id} if remote_task_id else {})
        if not isinstance(result, dict) or not isinstance(result.get("receipt"), dict):
            raise HTTPException(502, "Remote cancellation has no scoped receipt")
        self._save_receipt(self._row(owner, task_id), target, result["receipt"])
        return result

    async def action(self, owner: str, task_id: str, action: str, body: dict[str, Any],
                     remote_task_id: str | None = None) -> dict[str, Any]:
        if action not in {"answer", "approve", "children"}:
            raise HTTPException(422, "Unsupported scoped remote action")
        _, target, identifier = await self._binding(owner, task_id, execution=True)
        result = await self._request(owner, target, "POST", "/api/factory/remote-handoffs/" + identifier + "/" + action,
                                     json=body, params={"remoteTaskId": remote_task_id} if remote_task_id else {})
        if not isinstance(result, dict):
            raise HTTPException(502, "Remote action returned an invalid object")
        return result

    async def answer(self, owner: str, task_id: str, body: dict[str, Any], remote_task_id: str | None = None) -> dict[str, Any]:
        return await self.action(owner, task_id, "answer", body, remote_task_id)

    async def approve(self, owner: str, task_id: str, body: dict[str, Any], remote_task_id: str | None = None) -> dict[str, Any]:
        return await self.action(owner, task_id, "approve", body, remote_task_id)

    async def delegate(self, owner: str, task_id: str, goal: str, mode: str, request_id: str,
                       remote_task_id: str | None = None) -> dict[str, Any]:
        return await self.action(owner, task_id, "children", {"goal": goal, "mode": mode, "requestId": request_id}, remote_task_id)

    async def children(self, owner: str, task_id: str, remote_task_id: str | None = None) -> list[dict[str, Any]]:
        _, target, identifier = await self._binding(owner, task_id, execution=False)
        result = await self._request(owner, target, "GET", "/api/factory/remote-handoffs/" + identifier + "/children",
                                     params={"remoteTaskId": remote_task_id} if remote_task_id else {})
        if not isinstance(result, list) or len(result) > 4:
            raise HTTPException(502, "Remote descendant response exceeds the delegation ceiling")
        return result

    async def events(self, owner: str, task_id: str, remote_task_id: str | None = None, *, cursor=None, limit=100):
        row, target, identifier = await self._binding(owner, task_id, execution=False)
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        if remote_task_id:
            params["remoteTaskId"] = remote_task_id
        value = await self._request(owner, target, "GET", "/api/factory/remote-handoffs/" + identifier + "/events", params=params)
        expected = remote_task_id or row["body"]["receipt"].get("remoteTaskId")
        if (not isinstance(value, dict) or value.get("schema") != 1 or value.get("nativeCursor") is not False
                or value.get("source") != "factory-af_events" or not isinstance(value.get("events"), list)
                or len(value["events"]) > limit or not isinstance(value.get("nextCursor"), str)
                or len(value["nextCursor"]) > 4096 or not isinstance(value.get("streamId"), str)
                or type(value.get("hasMore")) is not bool):
            raise HTTPException(502, "Remote event page has an invalid bounded Factory replay receipt")
        for event in value["events"]:
            if (not isinstance(event, dict) or event.get("jobId") != expected
                    or event.get("payloadSha256") != digest({key: item for key, item in event.items() if key not in {"payloadSha256", "sequence"}})):
                raise HTTPException(409, "Remote event payload is outside its scoped task or differs from its digest")
        if value.get("payloadSha256") != digest(value["events"]):
            raise HTTPException(409, "Remote event page differs from its payload digest")
        return value

    async def artifact(self, owner: str, task_id: str, artifact_id: str, remote_task_id: str | None = None) -> tuple[dict[str, Any], bytes]:
        _, target, identifier = await self._binding(owner, task_id, execution=False)
        detail = await self.detail(owner, task_id, remote_task_id)
        metadata = next((artifact for artifact in detail.get("artifacts", []) if artifact.get("id") == artifact_id), None)
        if not metadata:
            raise HTTPException(404, "Artifact is outside the selected remote task")
        result = await self._request(owner, target, "GET", "/api/factory/remote-handoffs/" + identifier + "/artifacts/" + quote(artifact_id, safe=""),
                                     binary=True, params={"remoteTaskId": remote_task_id} if remote_task_id else {})
        content = result["content"]
        if hashlib.sha256(content).hexdigest() != metadata["sha256"] or result["sha256"] != metadata["sha256"] or len(content) != metadata["size"]:
            raise HTTPException(409, "Remote artifact receipt/content SHA-256 or length mismatch")
        return metadata, content

    def authority_callback(self, owner: str, task_id: str, manifest_hash: str, tool: str | None) -> HandoffAuthority:
        row = self._row(owner, task_id)
        if row["manifest_hash"] != manifest_hash:
            raise PermissionError("Origin immutable manifest changed")
        # Validate owner, initial target/configuration, absence of a local run,
        # and the persisted immutable manifest before interpreting cleanup.
        # A public cancel commits at the origin before its receiver POST. That
        # gap must stop receiver work as cancellation, not manufacture failure.
        self._target(owner, row, execution=False)
        task = self.store.task(task_id, owner)
        if task["cancel_requested"] and not self.store.failure_cleanup_requested(task_id) and not self.store.has_failures(task_id):
            raise HandoffCancellationRequested(owner, task_id, manifest_hash)
        self._target(owner, row, native_cancellation=True)
        plan = self.store.plan(task["plan_id"], owner)
        ledger = getattr(self.store, "usage_ledger", None)
        if ledger is not None:
            # Origin has no native model attempt. Its current pricing/budget
            # mandate must still fence every receiver provider/tool entry.
            ledger.require_current_commitment(plan)
        if tool is not None and tool not in plan["tools"]:
            raise PermissionError("Origin plan denies this protected tool")
        target = self.targets[row["target_ref"]]
        return HandoffAuthority(frozenset(plan["capabilities"]), frozenset(plan["tools"]),
                                {key: plan["budget"][key] for key in BUDGET_KEYS},
                                origin_ref=target.origin_ref, target_ref=target.reference,
                                receiver_identity=target.identity_map[owner],
                                target_revision=target.configuration_revision, target_fingerprint=target.fingerprint,
                                usage_grant_sha256=row["body"].get("usageGrant", {}).get("sha256"))

    def install_guard(self) -> None:
        if self._installed:
            return
        def deny_local(owner, plan, context, name):
            if context is None:
                return
            rows = self.store.sql("SELECT 1 FROM af_remote_placements WHERE task_id=:id", id=context.session_id)
            if rows:
                raise PermissionError("This task's initially selected receiver owns execution; local execution denied")
        self.store.execution_guards["remote_origin"] = deny_local
        self._installed = True

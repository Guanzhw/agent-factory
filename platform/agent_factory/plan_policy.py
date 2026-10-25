"""Member execution and inspection of historical plan reviews."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Literal, cast

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, UniqueConstraint, select


from .store import digest

PolicyName = Literal["member-self-service"]
# Generic legacy vocabulary is a compatibility contract, not installed seeds.
LEGACY_TOOLS = {"ask_scope": "question:ask", "checksum": "checksum:read"}
KNOWN_TOOLS = {**LEGACY_TOOLS, "bounded_process_run": "compute:local"}
ToolContract = Literal["legacy-v1", "bounded-process-v1", "controlled-development-v1"]


def tools_for_contract(contract: ToolContract) -> dict[str, str]:
    if contract == "legacy-v1":
        return dict(LEGACY_TOOLS)
    if contract in {"bounded-process-v1", "controlled-development-v1"}:
        return dict(KNOWN_TOOLS)
    raise ValueError("Unsupported registered tool contract")


def application_tool_catalog(store):
    """Native tool identities supplied by installed and member-created adapters."""
    contract = getattr(store.settings, "runtime_tool_contract", "legacy-v1")
    catalog = {**KNOWN_TOOLS, **tools_for_contract(cast(ToolContract, contract))}
    bindings = getattr(store, "execution_bindings", None)
    if bindings is not None:
        for entry in bindings.describe():
            if entry["kind"] == "tool":
                catalog.setdefault(entry["toolName"], next(iter(entry["permissions"]), "tool:invoke"))
    personal = getattr(store, "personal_tools", None)
    if personal is not None:
        for name, capability in personal.catalog_tools().items():
            catalog.setdefault(name, capability)
    policy = getattr(store, "plan_policy", None)
    return policy.extend_application_tool_catalog(catalog) if policy is not None else catalog


@dataclass(frozen=True)
class PlanPolicyConfig:
    name: Literal["member-self-service"] = "member-self-service"
    revision: str = "department-member-v1"
    tool_contract: ToolContract = "legacy-v1"

    def __post_init__(self):
        if self.name != "member-self-service":
            raise ValueError("Members execute plans directly; plan review modes are retired")
        tools_for_contract(self.tool_contract)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", self.revision):
            raise ValueError("Policy revision must be a bounded identifier")

    @property
    def fingerprint(self):
        # Preserve the historic false bit in immutable policy fingerprints;
        # no application-specific tool or enabling switch remains.
        return digest({**asdict(self), "source_synthesis_enabled": False})

    @property
    def known_tools(self):
        return tools_for_contract(self.tool_contract)



class NativeMandateCompleted(HTTPException):
    """Execution denied because this exact child ticket completed normally."""

    def __init__(self, task_id: str, run_id: str):
        super().__init__(409, "Current native delegation mandate is completed")
        self.task_id, self.run_id = task_id, run_id


def persisted_ancestor_guard(store: Any):
    """Trusted integration callback; checks existing native/persisted mandates.

    This reads native tickets, links and plans without recursively invoking tool
    authorization or consuming shared budget. No body may provide this callback.
"""
    def guard(owner: str, plan: dict, context: Any) -> list[dict]:
        service = getattr(store, "delegation", None)
        if service is None or context is None:
            raise HTTPException(409, "DELEGATION_POLICY_UNBOUND: persisted mandate unavailable")
        task = store.task(context.session_id, owner)
        if task["id"] != context.session_id or task["plan_id"] != plan["id"] or context.user_id != owner:
            raise HTTPException(403, "Delegation policy context does not match the task")
        if task.get("run_id") not in {None, context.run_id}:
            raise HTTPException(403, "Delegation native run differs from task binding")
        root_id, ancestors = service._ancestry(task)
        if not ancestors or plan["delegation"].get("rootTaskId") != root_id:
            raise HTTPException(403, "Delegation policy root differs from the persisted mandate")
        link = service._link(task["id"])
        expected = {"parentTaskId": ancestors[0]["id"], "rootTaskId": root_id, "depth": len(ancestors)}
        if not link or link["owner_id"] != owner or link["plan_id"] != plan["id"] or plan["delegation"] != expected:
            raise HTTPException(403, "Child policy differs from persisted delegation scope")
        roots = store.sql("SELECT * FROM af_delegation_roots WHERE root_id=:id", id=root_id)
        if not roots or roots[0]["owner_id"] != owner or roots[0]["reclaimed"]:
            raise HTTPException(409, "Delegation approval root is unavailable or reclaimed")
        own_completed = False
        for current in [task, *ancestors]:
            if current["owner_id"] != owner or current["cancel_requested"] or current["admission"] == "rejected":
                raise HTTPException(403, "Current delegation mandate is revoked")
            if current["id"] != task["id"] and current["admission"] != "accepted":
                raise HTTPException(409, "Ancestor native acknowledgement is unavailable")
            if store.has_failures(current["id"]):
                raise HTTPException(409, "Current delegation application mandate failed")
            run_id = context.run_id if current["id"] == task["id"] else current["run_id"]
            native = store.native_db.get_job(run_id) or {}
            from .native_component import component_identity
            kind, component_id = component_identity(store.plan(current["plan_id"], owner))
            if (native.get("session_id") != current["id"] or native.get("user_id") != owner
                    or native.get("component_id") != component_id or native.get("component_type", "agent") != kind):
                raise HTTPException(403, "Native delegation ticket differs from owner/task/executor")
            if current["id"] == task["id"] and str(native.get("status", "")).lower() == "completed":
                # Finish validating ancestors before exposing the narrow normal
                # completion reason; genuine revocation/failure takes precedence.
                own_completed = True
                continue
            allowed = {"queued", "running", "paused"} | ({"completed"} if current["id"] != task["id"] else set())
            if str(native.get("status", "")).lower() not in allowed:
                raise HTTPException(409, "Current native delegation mandate is unavailable")
        plans = [store.plan(parent["plan_id"], owner) for parent in ancestors]
        for child, parent in zip([plan, *plans], plans):
            if not set(child["tools"]) <= set(parent["tools"]) or not set(child["capabilities"]) <= set(parent["capabilities"]):
                raise HTTPException(403, "Child exceeds a persisted ancestor mandate")
        if own_completed:
            raise NativeMandateCompleted(task["id"], context.run_id)
        return plans
    return guard


class PlanPolicyService:
    """Member execution plus read-only historical approval records.

    Immutable plan storage owns snapshot integrity. Runtime services own current
    identity, resource access, cancellation, budgets and operation receipts.
    """
    def extend_application_tool_catalog(self, catalog):
        return catalog

    def __init__(self, store: Any, auth: Any, config: PlanPolicyConfig | None = None, *,
                 clock: Callable[[], datetime] | None = None,
                 ancestor_guard: Callable[[str, dict, Any], list[dict]] | None = None):
        self.store, self.auth = store, auth
        self.config = config or PlanPolicyConfig()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ancestor_guard = ancestor_guard
        self.metadata = MetaData()
        self.reviews = Table("af_plan_reviews", self.metadata,
            Column("id", String, primary_key=True), Column("owner_id", String, nullable=False),
            Column("plan_id", String, nullable=False), Column("plan_hash", String, nullable=False),
            Column("plan_fingerprint", String, nullable=False), Column("policy_revision", String, nullable=False),
            Column("policy_hash", String, nullable=False), Column("request_id", String, nullable=False),
            Column("intent_hash", String, nullable=False), Column("expires_at", String, nullable=False),
            Column("created_at", String, nullable=False),
            UniqueConstraint("owner_id", "request_id"))
        self.decisions = Table("af_plan_review_decisions", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("review_id", String, ForeignKey("af_plan_reviews.id"), nullable=False),
            Column("actor_id", String, nullable=False), Column("request_id", String, nullable=False),
            Column("intent_hash", String, nullable=False), Column("decision", String, nullable=False),
            Column("decided_at", String, nullable=False),
            UniqueConstraint("actor_id", "request_id"), UniqueConstraint("review_id"))
        self.metadata.create_all(store.engine)

    def current(self):
        return {**asdict(self.config), "fingerprint": self.config.fingerprint,
                "nativeToolConfirmationSeparate": True}

    def _plan(self, owner, plan, *, connection=None):
        if not isinstance(plan, str):
            if plan["ownerId"] != owner:
                raise HTTPException(403, "Plan belongs to another member")
            return plan
        shared = getattr(self.store, "_connection", None)
        if connection is None or shared is None:
            return self.store.plan(plan, owner)
        token = shared.set(connection)
        try:
            return self.store.plan(plan, owner)
        finally:
            shared.reset(token)

    @staticmethod
    def _scope(plan):
        if plan.get("status") != "ready" or plan.get("missing"):
            raise HTTPException(409, "PLAN_PREFLIGHT_BLOCKED: resolve missing prerequisites before execution")

    def _plan_summary(self, plan):
        return {key: plan.get(key) for key in ("normalizedGoal", "application", "mode", "tools", "capabilities", "budget", "materialRefs", "config", "usageBudget")}

    def _require_authorization(self, owner, plan, *, run_context=None, ancestor_resolver=None):
        self.auth.require_member(owner)
        current = self._plan(owner, plan)
        self._scope(current)
        ancestors = []
        if ancestor_resolver is not None:
            ancestors = ancestor_resolver(current)
        elif current.get("delegation"):
            if self.ancestor_guard is None or run_context is None:
                raise HTTPException(409, "DELEGATION_CONTEXT_REQUIRED: original child task is required")
            ancestors = self.ancestor_guard(owner, current, run_context)
        for ancestor in ancestors:
            if not set(current["tools"]) <= set(ancestor["tools"]) or not set(current["capabilities"]) <= set(ancestor["capabilities"]):
                raise HTTPException(403, "Child exceeds its original parent task scope")
            from .application_schema import time_budget_key
            if current.get("contractVersion", 1) != ancestor.get("contractVersion", 1):
                raise HTTPException(403, "Child differs from its parent budget contract")
            for key in ("toolCalls", time_budget_key(current), "outputBytes", "maxDepth", "maxChildren"):
                if not 0 < current["budget"][key] <= ancestor["budget"][key]:
                    raise HTTPException(403, "Child exceeds its parent task budget")
        return {"allowed": True, "ownerId": owner, "planId": current["id"],
                "planDigest": digest(current), "planFingerprint": current["fingerprint"],
                "source": "member-self-service", "reviewId": None}

    def require_execution(self, owner, plan, *, run_context=None):
        return self._require_authorization(owner, plan, run_context=run_context)

    def status(self, owner, plan, *, run_context=None):
        self.auth.require_member(owner)
        stored = self._plan(owner, plan)
        result = {"ownerId": owner, "planId": stored["id"], "planDigest": digest(stored),
                  "planFingerprint": stored["fingerprint"], "policy": self.current(),
                  "reviewRequired": False, "reviewRequestSupported": False,
                  "nativeToolConfirmationRequired": "run_experiment" in stored.get("tools", []), "executionAllowed": False,
                  "reason": None, "approval": None, "ownerSubmissionSupported": False}
        try:
            result["approval"] = self.require_execution(owner, stored, run_context=run_context)
            result["executionAllowed"] = True
            result["ownerSubmissionSupported"] = True
        except HTTPException as error:
            if error.status_code not in {403, 409}:
                raise
            result["reason"] = str(error.detail)
        return result

    def _project(self, conn, row):
        decision = conn.execute(select(self.decisions).where(self.decisions.c.review_id == row["id"])).mappings().first()
        summary = None
        integrity = False
        try:
            plan = self._plan(row["owner_id"], row["plan_id"], connection=conn)
            integrity = digest(plan) == row["plan_hash"] and plan["fingerprint"] == row["plan_fingerprint"]
            if integrity:
                summary = self._plan_summary(plan)
        except (HTTPException, ValueError):
            integrity = False
            summary = None
        return {"id": row["id"], "ownerId": row["owner_id"], "planId": row["plan_id"],
                "planDigest": row["plan_hash"], "planFingerprint": row["plan_fingerprint"],
                "policyRevision": row["policy_revision"], "policyDigest": row["policy_hash"],
                "requestId": row["request_id"], "createdAt": row["created_at"], "expiresAt": row["expires_at"],
                "expired": self.clock() >= datetime.fromisoformat(row["expires_at"]), "currentPolicy": False,
                "decision": decision["decision"] if decision else "pending",
                "reviewerId": decision["actor_id"] if decision else None,
                "decidedAt": decision["decided_at"] if decision else None,
                "planSummary": summary, "planIntegrityMatches": integrity, "approvalEffective": False}

    def inspect(self, actor, review_id):
        self.auth.require_member(actor)
        with self.store.engine.connect() as conn:
            row = conn.execute(select(self.reviews).where(self.reviews.c.id == review_id, self.reviews.c.owner_id == actor)).mappings().first()
            if row is None:
                raise HTTPException(404, "Scoped plan review not found")
            return self._project(conn, row)

    def list_reviews(self, actor, *, plan_id=None):
        self.auth.require_member(actor)
        with self.store.engine.connect() as conn:
            query = select(self.reviews).where(self.reviews.c.owner_id == actor).order_by(self.reviews.c.created_at.desc(), self.reviews.c.id).limit(100)
            if plan_id is not None:
                query = query.where(self.reviews.c.plan_id == plan_id)
            return [self._project(conn, row) for row in conn.execute(query).mappings()]


def plan_policy_router(auth: Any, service: PlanPolicyService) -> APIRouter:
    router = APIRouter(prefix="/api/factory")

    @router.get("/plan-policy")
    def current(request: Request):
        auth.require_member(auth.user(request)["id"])
        return service.current()

    @router.get("/plans/{plan_id}/authorization")
    def authorization(plan_id: str, request: Request):
        return service.status(auth.user(request)["id"], plan_id)

    @router.get("/plan-reviews")
    def list_reviews(request: Request, planId: str | None = None):
        return service.list_reviews(auth.user(request)["id"], plan_id=planId)

    @router.post("/plan-reviews")
    @router.post("/plan-reviews/{review_id}/decision")
    def retired(request: Request):
        auth.require_member(auth.user(request)["id"])
        raise HTTPException(410, "PLAN_REVIEWS_RETIRED: members submit plans directly")

    @router.get("/plan-reviews/{review_id}")
    def inspect(review_id: str, request: Request):
        return service.inspect(auth.user(request)["id"], review_id)

    return router

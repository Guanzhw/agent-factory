"""Persisted plan approval, separate from native HITL and execution ownership.

Operator configuration defaults to admin review. This module grants no native
roles, selects no paid model and cannot approve a native tool confirmation.
Register its router and call require_execution/require_tool at admission and
protected boundaries; merely constructing the service does not enforce policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import Column, ForeignKey, Integer, JSON, MetaData, String, Table, UniqueConstraint, select, text

from .store import digest

PolicyName = Literal["unset", "admin-review", "read-only-auto", "bounded-synthetic"]
LEGACY_TOOLS = {"literature_search": "research:read", "ask_scope": "question:ask",
               "checksum": "checksum:read", "run_experiment": "experiment:synthetic"}
REGISTERED_TOOLS = {**LEGACY_TOOLS, "orx_discover": "research:read"}
ORX_EXPERIMENT_TOOLS = {
    "orx_experiment_inspect": "research:read",
    "orx_experiment_run": "compute:local",
    "orx_experiment_wait": "research:read",
    "orx_experiment_cancel": "compute:local",
    "orx_experiment_logs": "research:read",
}
LOCAL_ORX_TOOLS = {**REGISTERED_TOOLS, **ORX_EXPERIMENT_TOOLS}
KNOWN_TOOLS = {**LOCAL_ORX_TOOLS, "orx_paper": "research:read", "orx_text": "research:read", "orx_sources_report": "research:read"}
LEGACY_READ_ONLY_TOOLS = frozenset({"literature_search", "ask_scope", "checksum"})
READ_ONLY_TOOLS = LEGACY_READ_ONLY_TOOLS | {"orx_discover"}
READ_ONLY_CAPABILITIES = frozenset({"research:read", "question:ask", "checksum:read"})
LOCAL_ORX_READ_ONLY_TOOLS = READ_ONLY_TOOLS | {"orx_experiment_inspect", "orx_experiment_wait", "orx_experiment_logs"}
LITERATURE_TOOLS = {**KNOWN_TOOLS, "orx_paper": "research:read", "orx_text": "research:read", "orx_sources_report": "research:read"}
ToolContract = Literal["legacy-v1", "registered-runtime-v1", "local-orx-v1", "orx-evidence-v2"]


def tools_for_contract(contract: ToolContract) -> dict[str, str]:
    if contract == "legacy-v1":
        return dict(LEGACY_TOOLS)
    if contract == "registered-runtime-v1":
        return dict(REGISTERED_TOOLS)
    if contract == "local-orx-v1":
        return dict(LOCAL_ORX_TOOLS)
    if contract == "orx-evidence-v2":
        return dict(LITERATURE_TOOLS)
    raise ValueError("Unsupported registered tool contract")


@dataclass(frozen=True)
class PlanPolicyConfig:
    name: PolicyName = "admin-review"
    revision: str = "plan-policy-v1"
    review_ttl_seconds: int = 3600
    tool_contract: ToolContract = "legacy-v1"

    def __post_init__(self):
        tools_for_contract(self.tool_contract)
        if self.tool_contract != "legacy-v1" and self.revision == "plan-policy-v1":
            raise ValueError("Registered runtime tools require a distinct plan policy revision")
        if self.name not in {"unset", "admin-review", "read-only-auto", "bounded-synthetic"}:
            raise ValueError("Unsupported plan approval policy")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", self.revision):
            raise ValueError("Policy revision must be a bounded identifier")
        if type(self.review_ttl_seconds) is not int or not 60 <= self.review_ttl_seconds <= 86400:
            raise ValueError("Review TTL must be 60 through 86400 seconds")

    @property
    def fingerprint(self) -> str:
        body = asdict(self)
        if self.tool_contract == "legacy-v1":
            del body["tool_contract"]
        return digest({**body, "knownTools": self.known_tools,
                       "readOnlyTools": sorted(self.read_only_tools),
                       "readOnlyCapabilities": sorted(READ_ONLY_CAPABILITIES)})

    @property
    def known_tools(self) -> dict[str, str]:
        return tools_for_contract(self.tool_contract)

    @property
    def read_only_tools(self) -> frozenset[str]:
        if self.tool_contract == "legacy-v1":
            return LEGACY_READ_ONLY_TOOLS
        if self.tool_contract == "orx-evidence-v2":
            return LOCAL_ORX_READ_ONLY_TOOLS | {"orx_paper", "orx_text", "orx_sources_report"}
        return LOCAL_ORX_READ_ONLY_TOOLS if self.tool_contract == "local-orx-v1" else READ_ONLY_TOOLS


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
        for current in [task, *ancestors]:
            if current["owner_id"] != owner or current["cancel_requested"] or current["admission"] == "rejected":
                raise HTTPException(403, "Current delegation mandate is revoked")
            if current["id"] != task["id"] and current["admission"] != "accepted":
                raise HTTPException(409, "Ancestor native acknowledgement is unavailable")
            if store.has_failures(current["id"]):
                raise HTTPException(409, "Current delegation application mandate failed")
            run_id = context.run_id if current["id"] == task["id"] else current["run_id"]
            native = store.native_db.get_job(run_id) or {}
            if native.get("session_id") != current["id"] or native.get("user_id") != owner or native.get("component_id") != "factory-executor":
                raise HTTPException(403, "Native delegation ticket differs from owner/task/executor")
            allowed = {"queued", "running", "paused"} | ({"completed"} if current["id"] != task["id"] else set())
            if str(native.get("status", "")).lower() not in allowed:
                raise HTTPException(409, "Current native delegation mandate is unavailable")
        plans = [store.plan(parent["plan_id"], owner) for parent in ancestors]
        for child, parent in zip([plan, *plans], plans):
            if not set(child["tools"]) <= set(parent["tools"]) or not set(child["capabilities"]) <= set(parent["capabilities"]):
                raise HTTPException(403, "Child exceeds a persisted ancestor mandate")
        return plans
    return guard


class PlanPolicyService:
    def __init__(self, store: Any, auth: Any, config: PlanPolicyConfig | None = None, *,
                 clock: Callable[[], datetime] | None = None,
                 ancestor_guard: Callable[[str, dict, Any], list[dict]] | None = None):
        self.store, self.auth = store, auth
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ancestor_guard = ancestor_guard
        self.metadata = MetaData()
        self.configs = Table("af_plan_policy_configs", self.metadata,
            Column("revision", String, primary_key=True), Column("policy_hash", String, nullable=False),
            Column("body", JSON, nullable=False))
        self.state = Table("af_plan_policy_state", self.metadata,
            Column("id", String, primary_key=True), Column("revision", String, nullable=False))
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
        self.metadata.create_all(self.store.engine)
        initial = config or PlanPolicyConfig()
        self._validate_mode(initial)
        with self.store.engine.begin() as conn:
            self._lock(conn)
            self._register(conn, initial)
            current = conn.execute(select(self.state.c.revision).where(self.state.c.id == "current")).scalar()
            if current is None:
                conn.execute(self.state.insert().values(id="current", revision=initial.revision))
            elif current != initial.revision:
                raise ValueError("Configured policy differs from persisted current revision; reconcile operator configuration")

    def _lock(self, conn):
        if self.store.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_plan_policy'))"))

    def _at(self) -> datetime:
        at = self.clock()
        if at.tzinfo is None:
            raise ValueError("Policy clock must be timezone-aware")
        return at.astimezone(timezone.utc)

    def _validate_mode(self, config):
        if config.name == "bounded-synthetic" and not self.store.settings.demo:
            raise ValueError("bounded-synthetic plan approval is demo-only")

    def _register(self, conn, config):
        row = conn.execute(select(self.configs).where(self.configs.c.revision == config.revision)).mappings().first()
        if row and row["policy_hash"] != config.fingerprint:
            raise ValueError("A policy revision cannot be rebound to different approval rules")
        if not row:
            conn.execute(self.configs.insert().values(revision=config.revision,
                         policy_hash=config.fingerprint, body=asdict(config)))

    def _current(self, conn) -> PlanPolicyConfig:
        row = conn.execute(select(self.configs.c.body, self.configs.c.policy_hash).join(
            self.state, self.state.c.revision == self.configs.c.revision).where(self.state.c.id == "current")).mappings().first()
        if not row:
            raise HTTPException(503, "Current plan approval policy is unavailable")
        config = PlanPolicyConfig(**row["body"])
        if row["policy_hash"] != config.fingerprint:
            raise HTTPException(409, "Immutable policy configuration integrity mismatch")
        try:
            self._validate_mode(config)
        except ValueError as error:
            raise HTTPException(409, "POLICY_MODE_INVALID: synthetic approval cannot run in production") from error
        return config

    def current(self) -> dict:
        # Composition/admission may already own this Store transaction. Reuse
        # its connection instead of opening a second pool slot under its lock.
        shared = getattr(self.store, "_connection", None)
        existing = shared.get() if shared is not None else None
        if existing is not None:
            config = self._current(existing)
        else:
            with self.store.engine.connect() as conn:
                config = self._current(conn)
        return {**asdict(config), "fingerprint": config.fingerprint,
                "nativeToolConfirmationSeparate": True}

    def status(self, owner: str, plan: str | Mapping, *, run_context: Any = None) -> dict:
        self.auth.require(owner, "run")
        stored = self._plan(owner, plan)
        policy = self.current()
        read_only = (set(stored.get("tools", [])) <= (LEGACY_READ_ONLY_TOOLS if policy["tool_contract"] == "legacy-v1" else READ_ONLY_TOOLS) and
                     set(stored.get("capabilities", [])) <= READ_ONLY_CAPABILITIES and
                     stored.get("mode") != "experiment")
        review_required = policy["name"] == "admin-review" or policy["name"] == "read-only-auto" and not read_only
        result = {"ownerId": owner, "planId": stored["id"], "planDigest": digest(stored),
                  "planFingerprint": stored["fingerprint"], "policy": policy,
                  "reviewRequired": review_required, "reviewRequestSupported": policy["name"] in {"admin-review", "read-only-auto"} and not stored.get("delegation"),
                  "nativeToolConfirmationRequired": "run_experiment" in stored.get("tools", []),
                  "executionAllowed": False, "reason": None, "approval": None}
        try:
            result["approval"] = self.require_execution(owner, stored["id"], run_context=run_context)
            result["executionAllowed"] = True
        except HTTPException as error:
            if error.status_code not in {403, 409}:
                raise
            result["reason"] = str(error.detail)
        return result

    def replace_configuration(self, config: PlanPolicyConfig, *, expected_revision: str) -> dict:
        """Trusted operator operation, deliberately absent from the HTTP router."""
        self._validate_mode(config)
        with self.store.engine.begin() as conn:
            self._lock(conn)
            old = self._current(conn)
            if old.revision != expected_revision:
                raise HTTPException(409, "POLICY_REVISION_CONFLICT: current configuration changed")
            self._register(conn, config)
            conn.execute(self.state.update().where(self.state.c.id == "current").values(revision=config.revision))
        return self.current()

    @staticmethod
    def _key(key: str):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", key):
            raise HTTPException(400, "A bounded review request ID is required")

    def _plan(self, owner: str, plan: str | Mapping, *, connection: Any = None) -> dict:
        plan_id = plan if isinstance(plan, str) else plan.get("id")
        if not isinstance(plan_id, str):
            raise HTTPException(400, "A persisted immutable plan ID is required")
        shared = getattr(self.store, "_connection", None)
        token = shared.set(connection) if connection is not None and shared is not None else None
        try:
            stored = self.store.plan(plan_id, owner)
        finally:
            if token is not None and shared is not None:
                shared.reset(token)
        if not isinstance(plan, str) and digest(dict(plan)) != digest(stored):
            raise HTTPException(409, "Plan approval cannot bind a changed snapshot")
        if stored.get("ownerId") != owner or not isinstance(stored.get("fingerprint"), str):
            raise HTTPException(403, "Plan approval owner or immutable fingerprint is invalid")
        return stored

    @staticmethod
    def _scope(plan, config: PlanPolicyConfig | None = None):
        known = (config or PlanPolicyConfig()).known_tools
        tools, caps = plan.get("tools"), plan.get("capabilities")
        if not isinstance(tools, list) or not tools or any(not isinstance(t, str) or t not in known for t in tools):
            raise HTTPException(409, "PLAN_SCOPE_INVALID: plan contains an unregistered tool")
        if not isinstance(caps, list) or any(not isinstance(c, str) or c not in known.values() for c in caps):
            raise HTTPException(409, "PLAN_SCOPE_INVALID: plan contains an unregistered capability")
        if not {known[t] for t in tools} <= set(caps):
            raise HTTPException(409, "PLAN_SCOPE_INVALID: tool authority is missing")
        if plan.get("status") != "ready" or plan.get("missing"):
            raise HTTPException(409, "PLAN_PREFLIGHT_BLOCKED: review cannot approve missing prerequisites")

    def _is_admin(self, actor):
        try:
            self.auth.require(actor, "agent_os:admin")
            return True
        except HTTPException as error:
            if error.status_code == 403:
                return False
            raise

    def _project(self, conn, row):
        config = self._current(conn)
        decision = conn.execute(select(self.decisions).where(self.decisions.c.review_id == row["id"])).mappings().first()
        latest = conn.execute(select(self.decisions.c.id).join(
            self.reviews, self.reviews.c.id == self.decisions.c.review_id).where(
            self.reviews.c.owner_id == row["owner_id"], self.reviews.c.plan_id == row["plan_id"],
            self.reviews.c.plan_hash == row["plan_hash"], self.reviews.c.policy_revision == row["policy_revision"],
            self.reviews.c.policy_hash == row["policy_hash"]
        ).order_by(self.decisions.c.id.desc()).limit(1)).scalar()
        expired = self._at() >= datetime.fromisoformat(row["expires_at"])
        valid_revision = row["policy_revision"] == config.revision and row["policy_hash"] == config.fingerprint
        summary = None
        integrity = False
        try:
            plan = self._plan(row["owner_id"], row["plan_id"], connection=conn)
            integrity = digest(plan) == row["plan_hash"] and plan["fingerprint"] == row["plan_fingerprint"]
            if integrity:
                summary = {key: plan.get(key) for key in ("normalizedGoal", "application", "mode", "tools", "capabilities", "budget", "materialRefs", "config", "usageBudget")}
        except Exception:
            # A persisted review remains inspectable for diagnosis; a corrupt or
            # unavailable plan cannot become an effective execution approval.
            integrity = False
        return {"id": row["id"], "ownerId": row["owner_id"], "planId": row["plan_id"],
                "planDigest": row["plan_hash"], "planFingerprint": row["plan_fingerprint"],
                "policyRevision": row["policy_revision"], "policyDigest": row["policy_hash"],
                "requestId": row["request_id"], "createdAt": row["created_at"], "expiresAt": row["expires_at"],
                "expired": expired, "currentPolicy": valid_revision,
                "decision": decision["decision"] if decision else "pending",
                "reviewerId": decision["actor_id"] if decision else None,
                "decidedAt": decision["decided_at"] if decision else None,
                "planSummary": summary, "planIntegrityMatches": integrity,
                "approvalEffective": bool(integrity and decision and decision["id"] == latest and decision["decision"] == "approved" and not expired and valid_revision)}

    def request_review(self, owner: str, plan_id: str, request_id: str) -> dict:
        self.auth.require(owner, "run")
        self._key(request_id)
        plan = self._plan(owner, plan_id)
        if plan.get("delegation"):
            raise HTTPException(409, "DELEGATION_POLICY_UNBOUND: child approval requires its root mandate")
        with self.store.engine.begin() as conn:
            self._lock(conn)
            config = self._current(conn)
            self._scope(plan, config)
            if config.name in {"unset", "bounded-synthetic"}:
                raise HTTPException(409, "This policy does not accept administrator plan reviews")
            intent = digest({"ownerId": owner, "planId": plan["id"], "planDigest": digest(plan),
                             "planFingerprint": plan["fingerprint"], "policyRevision": config.revision,
                             "policyDigest": config.fingerprint})
            row = conn.execute(select(self.reviews).where(self.reviews.c.owner_id == owner,
                               self.reviews.c.request_id == request_id)).mappings().first()
            if row:
                if row["intent_hash"] != intent:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: review request intent changed")
                return self._project(conn, row)
            at = self._at()
            value = {"id": str(uuid4()), "owner_id": owner, "plan_id": plan["id"], "plan_hash": digest(plan),
                     "plan_fingerprint": plan["fingerprint"], "policy_revision": config.revision,
                     "policy_hash": config.fingerprint, "request_id": request_id, "intent_hash": intent,
                     "created_at": at.isoformat(),
                     "expires_at": (at + timedelta(seconds=config.review_ttl_seconds)).isoformat()}
            conn.execute(self.reviews.insert().values(**value))
            return self._project(conn, value)

    def inspect(self, actor: str, review_id: str) -> dict:
        admin = self._is_admin(actor)
        if not admin:
            self.auth.require(actor, "run")
        with self.store.engine.connect() as conn:
            row = conn.execute(select(self.reviews).where(self.reviews.c.id == review_id)).mappings().first()
            if row is None or not admin and row["owner_id"] != actor:
                raise HTTPException(404, "Scoped plan review not found")
            return self._project(conn, row)

    def list_reviews(self, actor: str, *, all_owners: bool = False) -> list[dict]:
        self.auth.require(actor, "agent_os:admin" if all_owners else "run")
        with self.store.engine.connect() as conn:
            query = select(self.reviews).order_by(self.reviews.c.created_at.desc(), self.reviews.c.id).limit(100)
            if not all_owners:
                query = query.where(self.reviews.c.owner_id == actor)
            return [self._project(conn, row) for row in conn.execute(query).mappings()]

    def decide(self, actor: str, review_id: str, approved: bool, request_id: str) -> dict:
        self.auth.require(actor, "agent_os:admin")
        self._key(request_id)
        if type(approved) is not bool:
            raise HTTPException(400, "A typed approval decision is required")
        with self.store.engine.begin() as conn:
            self._lock(conn)
            row = conn.execute(select(self.reviews).where(self.reviews.c.id == review_id)).mappings().first()
            if row is None:
                raise HTTPException(404, "Plan review not found")
            intent = digest({"actorId": actor, "reviewId": review_id, "reviewIntent": row["intent_hash"], "approved": approved})
            old = conn.execute(select(self.decisions).where(self.decisions.c.actor_id == actor,
                               self.decisions.c.request_id == request_id)).mappings().first()
            if old:
                if old["intent_hash"] != intent:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: review decision intent changed")
                return self._project(conn, row)
            projection = self._project(conn, row)
            if not projection["currentPolicy"] or projection["expired"] or projection["decision"] != "pending":
                raise HTTPException(409, "Review is expired, decided or bound to a previous policy")
            if approved:
                self.auth.require(row["owner_id"], "run")
                plan = self._plan(row["owner_id"], row["plan_id"], connection=conn)
                self._scope(plan, self._current(conn))
                if digest(plan) != row["plan_hash"] or plan["fingerprint"] != row["plan_fingerprint"]:
                    raise HTTPException(409, "Immutable plan differs from the requested review")
            self.auth.require(actor, "agent_os:admin")
            conn.execute(self.decisions.insert().values(review_id=review_id, actor_id=actor,
                         request_id=request_id, intent_hash=intent,
                         decision="approved" if approved else "denied", decided_at=self._at().isoformat()))
            return self._project(conn, row)

    def require_execution(self, owner: str, plan: str | Mapping, *, run_context: Any = None) -> dict:
        self.auth.require(owner, "run")
        configuration_guard = getattr(self.store, "require_current_policy", None)
        if configuration_guard is not None:
            # This Store boundary is configuration-only; it must not call back
            # into require_execution. It preserves operator emergency denial.
            configuration_guard()
        current_plan = self._plan(owner, plan)
        with self.store.engine.connect() as scope_connection:
            scope_config = self._current(scope_connection)
        self._scope(current_plan, scope_config)
        review_plan = current_plan
        inherited = False
        if current_plan.get("delegation"):
            if self.ancestor_guard is None or run_context is None:
                raise HTTPException(409, "DELEGATION_POLICY_UNBOUND: current persisted ancestor proof required")
            ancestors = self.ancestor_guard(owner, current_plan, run_context)
            if not ancestors or ancestors[-1].get("delegation"):
                raise HTTPException(403, "Delegation approval root is unavailable")
            for ancestor in ancestors:
                ancestor = self._plan(owner, ancestor)
                self._scope(ancestor, scope_config)
                if not set(current_plan["tools"]) <= set(ancestor["tools"]) or not set(current_plan["capabilities"]) <= set(ancestor["capabilities"]):
                    raise HTTPException(403, "Child exceeds ancestor approval scope")
                for key in ("toolCalls", "experimentSeconds", "outputBytes", "maxDepth", "maxChildren"):
                    value, ceiling = current_plan.get("budget", {}).get(key), ancestor.get("budget", {}).get(key)
                    if type(value) is not int or type(ceiling) is not int or not 0 < value <= ceiling:
                        raise HTTPException(403, "Child exceeds ancestor approval budget")
            review_plan, inherited = ancestors[-1], True
        with self.store.engine.connect() as conn:
            config = self._current(conn)
            # A concurrent operator change cannot widen admission between checks.
            self._scope(current_plan, config)
            self._scope(review_plan, config)
            if config.name == "unset":
                raise HTTPException(409, "POLICY_UNSET: plan execution has no selected approval policy")
            if config.name == "bounded-synthetic":
                if not current_plan.get("syntheticFixture") or current_plan.get("policy") != "bounded-synthetic":
                    raise HTTPException(409, "Synthetic policy cannot authorize a live plan")
                approval = {"source": "bounded-synthetic", "reviewId": None}
            elif config.name == "read-only-auto" and set(review_plan["tools"]) <= config.read_only_tools and set(review_plan["capabilities"]) <= READ_ONLY_CAPABILITIES and review_plan.get("mode") != "experiment":
                approval = {"source": "read-only-auto", "reviewId": None}
            else:
                row = conn.execute(select(self.reviews, self.decisions.c.decision).join(
                    self.decisions, self.decisions.c.review_id == self.reviews.c.id).where(
                    self.reviews.c.owner_id == owner, self.reviews.c.plan_id == review_plan["id"],
                    self.reviews.c.plan_hash == digest(review_plan), self.reviews.c.plan_fingerprint == review_plan["fingerprint"],
                    self.reviews.c.policy_revision == config.revision, self.reviews.c.policy_hash == config.fingerprint
                ).order_by(self.decisions.c.id.desc()).limit(1)).mappings().first()
                if row is None:
                    raise HTTPException(409, "PLAN_REVIEW_REQUIRED: exact current plan needs administrator approval")
                if row["decision"] != "approved":
                    raise HTTPException(409, "PLAN_REVIEW_DENIED: administrator denied the latest exact-plan review")
                if self._at() >= datetime.fromisoformat(row["expires_at"]):
                    raise HTTPException(409, "PLAN_REVIEW_EXPIRED: request a new exact-plan review")
                approval = {"source": "administrator-review", "reviewId": row["id"]}
        return {"allowed": True, "ownerId": owner, "planId": current_plan["id"], "planDigest": digest(current_plan),
                "planFingerprint": current_plan["fingerprint"], "policyRevision": config.revision,
                "policyDigest": config.fingerprint, "inheritedFromRoot": inherited, **approval}

    def require_tool(self, owner: str, plan: str | Mapping, tool_name: str, *, run_context: Any = None) -> dict:
        stored = self._plan(owner, plan)
        if tool_name not in stored.get("tools", []):
            raise HTTPException(403, "Tool is outside the immutable task scope")
        return self.require_execution(owner, stored["id"], run_context=run_context)

    def require_context_tool(self, run_context: Any, tool_name: str) -> dict:
        plan = self.store.resolve_run(run_context)
        return self.require_tool(run_context.user_id, plan["id"], tool_name, run_context=run_context)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planId: str = Field(min_length=1, max_length=100)
    requestId: str = Field(min_length=1, max_length=200)


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: StrictBool
    requestId: str = Field(min_length=1, max_length=200)


def plan_policy_router(auth: Any, service: PlanPolicyService) -> APIRouter:
    router = APIRouter(prefix="/api/factory")

    def actor(request):
        return auth.user(request)["id"]

    @router.get("/plan-policy")
    def current(request: Request):
        auth.require(actor(request), "run")
        return service.current()

    @router.post("/plan-reviews", status_code=201)
    def create(body: ReviewRequest, request: Request):
        return service.request_review(actor(request), body.planId, body.requestId)

    @router.get("/plans/{plan_id}/authorization")
    def authorization(plan_id: str, request: Request):
        return service.status(actor(request), plan_id)

    @router.get("/plan-reviews")
    def list_reviews(request: Request, allOwners: bool = False):
        return service.list_reviews(actor(request), all_owners=allOwners)

    @router.get("/plan-reviews/{review_id}")
    def inspect(review_id: str, request: Request):
        return service.inspect(actor(request), review_id)

    @router.post("/plan-reviews/{review_id}/decision")
    def decide(review_id: str, body: ReviewDecision, request: Request):
        return service.decide(actor(request), review_id, body.approved, body.requestId)

    return router

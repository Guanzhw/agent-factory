"""Durable provider-attempt admission; money is integer currency micro-units.

This owns accounting, never scheduling or provider credentials. A registered
operator reader supplies authoritative usage, including an explicit zero-usage
local contract. Missing/partial/error usage remains held through cancellation,
revocation and restart. No client-facing settlement route is provided.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping
from uuid import uuid4

from agno.models.base import Model
from agno.models.response import ModelResponse
from fastapi import HTTPException
from sqlalchemy import BigInteger, Column, JSON, MetaData, String, Table, select, text

from .store import digest, now

MAX_INTEGER = 10**15
COMMITMENT_KEYS = frozenset({"schema", "currency", "amountMicros", "tokenLimit", "provider", "model", "adapterId",
    "adapterRevision", "pricingRevision", "pricingSha256", "inputMicrosPerMillion", "outputMicrosPerMillion",
    "perAttemptInputTokens", "perAttemptOutputTokens", "bindingSha256", "policyRevision", "sha256"})
GRANT_KEYS = frozenset({"schema", "id", "originRef", "targetRef", "originOwnerId", "originTaskId", "sourcePlanSha256",
    "sourceCommitmentSha256", "receiverOwnerId", "receiverTaskId", "receiverPlanSha256", "receiverCommitmentSha256",
    "receiverCommitment", "currency", "tokenLimit", "amountMicros", "sha256"})
STATEMENT_KEYS = frozenset({"schema", "grantId", "grantSha256", "receiverOwnerId", "receiverTaskId", "receiverPlanSha256",
    "receiverCommitmentSha256", "settledTokens", "settledAmountMicros", "heldTokens", "heldAmountMicros", "allStopped",
    "sequence", "sha256"})


def validate_usage_commitment(value):
    """Structural source validation without resolving a source adapter/credential."""
    if (not isinstance(value, dict) or set(value) != COMMITMENT_KEYS or type(value.get("schema")) is not int
            or value["schema"] != 1 or value.get("currency") not in {"USD", "EUR", "CNY"}
            or value.get("sha256") != digest({k: v for k, v in value.items() if k != "sha256"})):
        raise HTTPException(422, "USAGE_COMMITMENT_SCHEMA: exact hashed version-one commitment required")
    for key in ("amountMicros", "tokenLimit", "inputMicrosPerMillion", "outputMicrosPerMillion",
                "perAttemptInputTokens", "perAttemptOutputTokens"):
        try:
            integer(value[key], key, minimum=1 if key in {"tokenLimit", "perAttemptInputTokens", "perAttemptOutputTokens"} else 0)
        except ValueError as error:
            raise HTTPException(422, "USAGE_COMMITMENT_SCHEMA: invalid numeric ceiling") from error
    for key in ("provider", "model", "adapterId", "adapterRevision", "pricingRevision", "policyRevision"):
        if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 120 or any(c.isspace() for c in value[key]):
            raise HTTPException(422, "USAGE_COMMITMENT_SCHEMA: invalid immutable identity")
    for key in ("pricingSha256", "bindingSha256"):
        if not isinstance(value[key], str) or len(value[key]) != 64 or any(c not in "abcdef0123456789" for c in value[key]):
            raise HTTPException(422, "USAGE_COMMITMENT_SCHEMA: invalid provenance digest")
    return copy.deepcopy(value)


def integer(value, name, *, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise ValueError(f"{name} must be a bounded integer")
    return value


@dataclass(frozen=True)
class UsageEvidence:
    input_tokens: int
    output_tokens: int
    source: str
    provider_request_id: str | None = None

    def __post_init__(self):
        integer(self.input_tokens, "input tokens")
        integer(self.output_tokens, "output tokens")
        if not isinstance(self.source, str) or not 1 <= len(self.source) <= 100:
            raise ValueError("A bounded authoritative usage source is required")
        if self.provider_request_id is not None and (not isinstance(self.provider_request_id, str)
                or not 1 <= len(self.provider_request_id) <= 200):
            raise ValueError("Invalid provider request ID")


def zero_local_usage(value) -> UsageEvidence | None:
    # Called only for an explicitly installed local model/pricing registration.
    return UsageEvidence(0, 0, "registered-local-no-provider") if isinstance(value, ModelResponse) else None


def native_response_usage(value) -> UsageEvidence | None:
    """Controlled native fixtures; not an adapter for an arbitrary raw SDK object."""
    if not isinstance(value, ModelResponse) or value.response_usage is None:
        return None
    usage = value.response_usage
    incoming, outgoing, total = usage.input_tokens, usage.output_tokens, usage.total_tokens
    if (type(incoming) is not int or type(outgoing) is not int or type(total) is not int
            or incoming < 0 or outgoing < 0 or total != incoming + outgoing):
        return None
    return UsageEvidence(incoming, outgoing, "registered-native-provider-usage")


@dataclass(frozen=True)
class PricingRevision:
    adapter_id: str
    adapter_revision: str
    provider: str
    model: str
    revision: str
    currency: str = "USD"
    input_micros_per_million: int = 0
    output_micros_per_million: int = 0
    per_attempt_input_tokens: int = 32768
    per_attempt_output_tokens: int = 4096
    usage_reader: Callable[[Any], UsageEvidence | None] = field(default=zero_local_usage, repr=False, compare=False)
    # A trusted adapter must bound the actual request/output and disable hidden
    # SDK retries. Native Agno retries each cross the guarded invoke boundary.
    request_guard: Callable[[Model, tuple, dict, Mapping], None] | None = field(default=None, repr=False, compare=False)
    local_model_type: type | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        for name in ("adapter_id", "adapter_revision", "provider", "model", "revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not 1 <= len(value) <= 120 or any(c.isspace() for c in value):
                raise ValueError("Pricing identity must be a bounded identifier")
        if self.currency not in {"USD", "EUR", "CNY"}:
            raise ValueError("Unsupported approved currency")
        for name in ("input_micros_per_million", "output_micros_per_million"):
            integer(getattr(self, name), name)
        for name in ("per_attempt_input_tokens", "per_attempt_output_tokens"):
            integer(getattr(self, name), name, minimum=1)
        if not callable(self.usage_reader):
            raise ValueError("An explicit authoritative usage reader is required")
        if self.local_model_type is None and not callable(self.request_guard):
            raise ValueError("Non-local adapters require an actual request cap/no-hidden-retry guard")
        if self.local_model_type is not None and (self.input_micros_per_million or self.output_micros_per_million):
            raise ValueError("A zero-local contract cannot register a paid tariff")

    @property
    def body(self):
        return {"adapterId": self.adapter_id, "adapterRevision": self.adapter_revision,
            "provider": self.provider, "model": self.model, "pricingRevision": self.revision,
            "currency": self.currency, "inputMicrosPerMillion": self.input_micros_per_million,
            "outputMicrosPerMillion": self.output_micros_per_million,
            "perAttemptInputTokens": self.per_attempt_input_tokens,
            "perAttemptOutputTokens": self.per_attempt_output_tokens,
            "usageContract": "local-no-provider-v1" if self.local_model_type else "operator-provider-usage-v1"}

    @property
    def sha256(self):
        return digest(self.body)

    def charge(self, incoming, outgoing):
        # One ceiling after summing both components, never binary floating point.
        return (incoming * self.input_micros_per_million + outgoing * self.output_micros_per_million + 999999) // 1000000


@dataclass(frozen=True)
class UsagePolicy:
    revision: str = "usage-policy-zero-local-v1"
    currency: str = "USD"
    task_token_limit: int = 1_000_000
    task_amount_micros: int = 0
    user_token_limit: int = 20_000_000
    user_amount_micros: int = 0

    def __post_init__(self):
        if not isinstance(self.revision, str) or not 1 <= len(self.revision) <= 100:
            raise ValueError("Invalid usage policy revision")
        if self.currency not in {"USD", "EUR", "CNY"}:
            raise ValueError("Unsupported approved currency")
        integer(self.task_token_limit, "task token limit", minimum=1)
        integer(self.user_token_limit, "user token limit", minimum=1)
        integer(self.task_amount_micros, "task amount")
        integer(self.user_amount_micros, "user amount")


def default_zero_prices():
    from .demo_model import DemoModel
    values = [PricingRevision("local-synthetic-model-v1", "1", "local-synthetic", "factory-synthetic-v1",
        "zero-local-v1", local_model_type=DemoModel)]
    try:
        from .orx_experiment_tools import LocalORXWorkflowModel
    except ImportError:
        return tuple(values)
    values.append(PricingRevision("local-orx-workflow-model-v1", "1", "local-deterministic",
        "factory-local-orx-workflow-v1", "zero-local-v1", local_model_type=LocalORXWorkflowModel))
    return tuple(values)


class UsageLedger:
    def __init__(self, store: Any, prices=None, policy: UsagePolicy | None = None):
        self.store, self.policy = store, policy or UsagePolicy()
        self.prices = tuple(prices if prices is not None else default_zero_prices())
        self.by_adapter = {(p.adapter_id, p.adapter_revision): p for p in self.prices}
        if len(self.by_adapter) != len(self.prices):
            raise ValueError("One active immutable pricing revision per adapter is required")
        metadata = MetaData()
        self.configs = Table("af_usage_policies", metadata, Column("revision", String, primary_key=True),
            Column("body", JSON, nullable=False), Column("hash", String, nullable=False))
        self.tariffs = Table("af_usage_prices", metadata, Column("id", String, primary_key=True),
            Column("body", JSON, nullable=False), Column("hash", String, nullable=False))
        self.migrations = Table("af_usage_plan_migrations", metadata, Column("plan_id", String, primary_key=True),
            Column("source_hash", String, nullable=False), Column("body", JSON, nullable=False), Column("hash", String, nullable=False))
        self.accounts = Table("af_usage_accounts", metadata, Column("id", String, primary_key=True),
            Column("owner_id", String, nullable=False), Column("body", JSON, nullable=False), Column("hash", String, nullable=False),
            Column("settled_tokens", BigInteger, nullable=False), Column("settled_amount", BigInteger, nullable=False),
            Column("held_tokens", BigInteger, nullable=False), Column("held_amount", BigInteger, nullable=False))
        self.attempts = Table("af_usage_attempts", metadata, Column("id", String, primary_key=True),
            Column("owner_id", String, nullable=False), Column("task_id", String, nullable=False),
            Column("state", String, nullable=False), Column("body", JSON, nullable=False), Column("hash", String, nullable=False),
            Column("usage", JSON), Column("created_at", String, nullable=False), Column("updated_at", String, nullable=False))
        self.grants = Table("af_usage_remote_grants", metadata, Column("id", String, primary_key=True),
            Column("owner_id", String, nullable=False), Column("task_id", String, nullable=False),
            Column("body", JSON, nullable=False), Column("hash", String, nullable=False),
            Column("state", String, nullable=False), Column("statement", JSON), Column("allocation", JSON))
        metadata.create_all(store.engine)
        with self._transaction() as conn:
            self._lock(conn)
            self._immutable(conn, self.configs, "revision", self.policy.revision, asdict(self.policy))
            for price in self.prices:
                self._immutable(conn, self.tariffs, "id", self._price_id(price), price.body)

    def _transaction(self):
        return self.store.transaction()

    def _lock(self, conn):
        # Bounded single-server MVP: one short lock makes root/child/user/grant
        # intersections atomic even across independent API worker processes.
        if self.store.engine.dialect.name != "postgresql":
            raise RuntimeError("Durable usage admission requires PostgreSQL transactions")
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_usage_ledger_v1'))"))

    @staticmethod
    def _immutable(conn, table, key, identity, body):
        old = conn.execute(select(table).where(table.c[key] == identity)).mappings().first()
        hashed = digest(body)
        if old:
            if old["body"] != body or old["hash"] != hashed:
                raise ValueError("An immutable usage configuration cannot be rebound")
        else:
            conn.execute(table.insert().values(**{key: identity, "body": body, "hash": hashed}))

    @staticmethod
    def _price_id(price):
        return digest({"adapterId": price.adapter_id, "adapterRevision": price.adapter_revision, "pricingRevision": price.revision})

    def _spec(self, plan, effective_bindings=None):
        manifest = effective_bindings if effective_bindings is not None else plan.get("executionBindings")
        if not isinstance(manifest, dict) or not isinstance(manifest.get("model"), dict):
            raise HTTPException(409, "USAGE_BINDING_REQUIRED: an exact model manifest is required")
        if manifest.get("sha256") != digest({k: v for k, v in manifest.items() if k != "sha256"}):
            raise HTTPException(409, "USAGE_BINDING_INTEGRITY: exact manifest hash required")
        return manifest, manifest["model"]

    def commitment_for(self, plan: Mapping, *, token_limit=None, amount_micros=None, effective_bindings=None):
        manifest, spec = self._spec(plan, effective_bindings)
        price = self.by_adapter.get((spec.get("adapterId"), spec.get("revision")))
        if price is None:
            raise HTTPException(409, "USAGE_PRICE_UNAVAILABLE: exact installed pricing is required")
        if price.currency != self.policy.currency:
            raise HTTPException(409, "USAGE_CURRENCY_MISMATCH: current approved policy differs")
        tokens = self.policy.task_token_limit if token_limit is None else integer(token_limit, "token ceiling", minimum=1)
        amount = self.policy.task_amount_micros if amount_micros is None else integer(amount_micros, "amount ceiling")
        if tokens > self.policy.task_token_limit or amount > self.policy.task_amount_micros:
            raise HTTPException(403, "USAGE_APPROVAL_CEILING: requested usage exceeds approved operator policy")
        body = {"schema": 1, "currency": price.currency, "amountMicros": amount, "tokenLimit": tokens,
            "provider": price.provider, "model": price.model, "adapterId": price.adapter_id,
            "adapterRevision": price.adapter_revision, "pricingRevision": price.revision, "pricingSha256": price.sha256,
            "inputMicrosPerMillion": price.input_micros_per_million, "outputMicrosPerMillion": price.output_micros_per_million,
            "perAttemptInputTokens": price.per_attempt_input_tokens, "perAttemptOutputTokens": price.per_attempt_output_tokens,
            "bindingSha256": manifest["sha256"], "policyRevision": self.policy.revision}
        return {**body, "sha256": digest(body)}

    def validate_commitment(self, plan, commitment, *, effective_bindings=None):
        validate_usage_commitment(commitment)
        if not isinstance(commitment, dict) or commitment.get("sha256") != digest({k: v for k, v in commitment.items() if k != "sha256"}):
            raise HTTPException(409, "USAGE_COMMITMENT_INTEGRITY: immutable budget differs")
        expected = self.commitment_for(plan, token_limit=commitment.get("tokenLimit"), amount_micros=commitment.get("amountMicros"), effective_bindings=effective_bindings)
        if expected != commitment:
            raise HTTPException(409, "USAGE_PRICING_DRIFT: model, rate, policy or binding differs from approval")
        return commitment

    def require_current_commitment(self, plan, *, effective_bindings=None):
        with self._transaction() as conn:
            commitment = self._commitment(conn, plan)
        return self.validate_commitment(plan, commitment, effective_bindings=effective_bindings)

    def _commitment(self, conn, plan):
        plan = {k: v for k, v in plan.items() if k not in {"taskId", "runId"}}
        migration = conn.execute(select(self.migrations).where(self.migrations.c.plan_id == plan["id"])).mappings().first()
        if migration:
            if migration["source_hash"] != digest(plan) or migration["hash"] != digest(migration["body"]):
                raise HTTPException(409, "USAGE_MIGRATION_INTEGRITY: historical plan hash differs")
            return migration["body"]
        commitment = plan.get("usageBudget")
        if commitment is not None:
            if commitment.get("sha256") != digest({k: v for k, v in commitment.items() if k != "sha256"}):
                raise HTTPException(409, "USAGE_COMMITMENT_INTEGRITY: historical commitment differs")
            return commitment
        # Preserve historical plan bytes; only explicitly registered local
        # implementations can migrate without a new approved plan.
        manifest, spec = self._spec(plan)
        price = self.by_adapter.get((spec.get("adapterId"), spec.get("revision")))
        if price is None or price.local_model_type is None:
            raise HTTPException(409, "USAGE_APPROVAL_REQUIRED: historical plans cannot gain provider spending")
        value = self.commitment_for(plan)
        conn.execute(self.migrations.insert().values(plan_id=plan["id"], source_hash=digest(plan), body=value, hash=digest(value)))
        return value

    def prepare_remote_commitment(self, plan, effective_bindings):
        """Trusted receiver preparation; preserve source plan bytes and hashes."""
        source = plan.get("usageBudget")
        if not isinstance(source, dict):
            source = self.commitment_for(plan)
        value = self.commitment_for(plan,
            token_limit=min(source["tokenLimit"], self.policy.task_token_limit),
            amount_micros=min(source["amountMicros"], self.policy.task_amount_micros),
            effective_bindings=effective_bindings)
        self._compatible(source, value)
        with self._transaction() as conn:
            self._lock(conn)
            old = conn.execute(select(self.migrations).where(self.migrations.c.plan_id == plan["id"])).mappings().first()
            if old:
                if old["source_hash"] != digest(plan) or old["hash"] != digest(old["body"]) or old["body"] != value:
                    raise HTTPException(409, "USAGE_REMOTE_COMMITMENT_CONFLICT: receiver quote cannot change")
            else:
                conn.execute(self.migrations.insert().values(plan_id=plan["id"], source_hash=digest(plan), body=value, hash=digest(value)))
        return copy.deepcopy(value)

    @staticmethod
    def _compatible(source, receiver):
        for value in (source, receiver):
            validate_usage_commitment(value)
            if not isinstance(value, dict) or value.get("sha256") != digest({k: v for k, v in value.items() if k != "sha256"}):
                raise HTTPException(409, "USAGE_REMOTE_QUOTE_INTEGRITY: exact immutable pricing quote required")
        keys = ("currency", "inputMicrosPerMillion", "outputMicrosPerMillion")
        if any(source.get(k) != receiver.get(k) for k in keys):
            raise HTTPException(409, "USAGE_REMOTE_PRICE_MISMATCH: source and receiver tariff/currency differ")
        if (source["inputMicrosPerMillion"] or source["outputMicrosPerMillion"]) and any(
                source.get(k) != receiver.get(k) for k in ("provider", "model", "pricingRevision")):
            raise HTTPException(409, "USAGE_REMOTE_MODEL_MISMATCH: a costed model cannot change remotely")
        if receiver["tokenLimit"] > source["tokenLimit"] or receiver["amountMicros"] > source["amountMicros"]:
            raise HTTPException(403, "USAGE_REMOTE_SCOPE: receiver cannot enlarge source cap")

    def commitment_for_candidate(self, candidate, plan_store=None):
        ancestors = getattr(plan_store, "ancestors", None)
        if not ancestors:
            return self.commitment_for(candidate)
        root = ancestors[-1]
        if root.get("remoteHandoff"):
            source = validate_usage_commitment(root["usageBudget"])
            if candidate["executionBindings"]["model"] != root["executionBindings"]["model"]:
                raise HTTPException(403, "USAGE_CHILD_MODEL_SCOPE: child cannot replace root source model")
            source["bindingSha256"] = candidate["executionBindings"]["sha256"]
            for parent in ancestors:
                parent_source = validate_usage_commitment(parent["usageBudget"])
                source["tokenLimit"] = min(source["tokenLimit"], parent_source["tokenLimit"])
                source["amountMicros"] = min(source["amountMicros"], parent_source["amountMicros"])
            source["sha256"] = digest({k: v for k, v in source.items() if k != "sha256"})
            return source
        with self._transaction() as conn:
            values = [self._commitment(conn, parent) for parent in ancestors]
        return self.commitment_for(candidate, token_limit=min(v["tokenLimit"] for v in values),
            amount_micros=min(v["amountMicros"] for v in values))

    def prepare_remote_child_commitment(self, plan, effective_bindings, root_plan):
        with self._transaction() as conn:
            root = self._commitment(conn, root_plan)
        source = validate_usage_commitment(plan["usageBudget"])
        value = self.commitment_for(plan, effective_bindings=effective_bindings,
            token_limit=min(source["tokenLimit"], root["tokenLimit"]),
            amount_micros=min(source["amountMicros"], root["amountMicros"]))
        if any(value[k] != root[k] for k in ("provider", "model", "adapterId", "adapterRevision", "pricingRevision", "pricingSha256")):
            raise HTTPException(403, "USAGE_CHILD_PRICE_SCOPE: child cannot replace approved receiver model/rate")
        self._compatible(source, value)
        with self._transaction() as conn:
            self._lock(conn)
            old = conn.execute(select(self.migrations).where(self.migrations.c.plan_id == plan["id"])).mappings().first()
            if old and (old["source_hash"] != digest(plan) or old["body"] != value or old["hash"] != digest(value)):
                raise HTTPException(409, "USAGE_CHILD_COMMITMENT_CONFLICT: immutable inherited receiver budget differs")
            if not old:
                conn.execute(self.migrations.insert().values(plan_id=plan["id"], source_hash=digest(plan), body=value, hash=digest(value)))
        return value

    def _account(self, conn, identity, owner, body):
        old = conn.execute(select(self.accounts).where(self.accounts.c.id == identity)).mappings().first()
        if old:
            if old["owner_id"] != owner or old["body"] != body or old["hash"] != digest(body):
                raise HTTPException(409, "USAGE_ACCOUNT_INTEGRITY: original ceiling cannot be reset")
            return dict(old)
        conn.execute(self.accounts.insert().values(id=identity, owner_id=owner, body=body, hash=digest(body),
            settled_tokens=0, settled_amount=0, held_tokens=0, held_amount=0))
        return dict(conn.execute(select(self.accounts).where(self.accounts.c.id == identity)).mappings().one())

    def _scope_accounts(self, conn, owner, task):
        service = getattr(self.store, "delegation", None)
        root, ancestors = service._ancestry(task) if service is not None else (task["id"], [])
        if task.get("plan_id") is None or task["owner_id"] != owner:
            raise HTTPException(403, "USAGE_NATIVE_IDENTITY: invalid task owner")
        if service is None and self.store.plan(task["plan_id"], owner).get("delegation"):
            raise HTTPException(409, "USAGE_ANCESTRY_REQUIRED: delegation accounting unavailable")
        values = []
        for current in [task, *ancestors]:
            if current["owner_id"] != owner:
                raise HTTPException(403, "USAGE_ANCESTRY_IDENTITY: ancestor differs from owner")
            plan = self.store.plan(current["plan_id"], owner)
            commitment = self._commitment(conn, plan)
            body = {"schema": 1, "scope": "task", "taskId": current["id"], "ownerId": owner,
                "planSha256": digest(plan), "commitmentSha256": commitment["sha256"], "currency": commitment["currency"],
                "tokenLimit": commitment["tokenLimit"], "amountMicros": commitment["amountMicros"]}
            values.append(self._account(conn, "task:" + current["id"], owner, body))
        user_body = {"schema": 1, "scope": "user", "ownerId": owner, "currency": self.policy.currency,
            "tokenLimit": self.policy.user_token_limit, "amountMicros": self.policy.user_amount_micros,
            "policyRevision": self.policy.revision}
        # User lifetime cap remains on the original account; a policy revision
        # cannot create a fresh bucket and silently reset previous consumption.
        values.append(self._account(conn, "user:" + owner, owner, user_body))
        return root, values

    def _hold(self, conn, accounts, tokens, amount):
        for account in accounts:
            if (account["settled_tokens"] + account["held_tokens"] + tokens > account["body"]["tokenLimit"]
                    or account["settled_amount"] + account["held_amount"] + amount > account["body"]["amountMicros"]):
                raise HTTPException(429, "USAGE_BUDGET_EXHAUSTED: shared token or amount ceiling is held/exhausted")
        for account in accounts:
            conn.execute(self.accounts.update().where(self.accounts.c.id == account["id"]).values(
                held_tokens=self.accounts.c.held_tokens + tokens, held_amount=self.accounts.c.held_amount + amount))

    def begin_attempt(self, context, plan, model: Model, *, streaming=False, arguments=(), keyword_arguments=None):
        owner = context.user_id
        plan = {k: v for k, v in plan.items() if k not in {"taskId", "runId"}}
        if self.store._connection.get() is not None:
            raise RuntimeError("Provider admission must commit before invocation, outside a borrowed transaction")
        with self._transaction() as conn:
            self._lock(conn)
            task = self.store.task(context.session_id, owner)
            if task["run_id"] != context.run_id or task["plan_id"] != plan["id"] or digest(self.store.plan(plan["id"], owner)) != digest(plan):
                raise HTTPException(403, "USAGE_NATIVE_IDENTITY: provider attempt differs from original run/plan")
            effective = self.store.execution_bindings.manifest(plan, context=context) if getattr(self.store, "execution_bindings", None) else None
            service = getattr(self.store, "delegation", None)
            if service is not None and plan.get("delegation"):
                root_id, _ = service._ancestry(task)
                root_plan = self.store.plan(self.store.task(root_id, owner)["plan_id"], owner)
                if root_plan.get("remoteHandoff"):
                    self.prepare_remote_child_commitment(plan, effective, root_plan)
            commitment = self._commitment(conn, plan)
            self.validate_commitment(plan, commitment, effective_bindings=effective)
            price = self.by_adapter[(commitment["adapterId"], commitment["adapterRevision"])]
            if model.id != price.model or model.provider != price.provider:
                raise HTTPException(409, "USAGE_MODEL_DRIFT: returned native provider/model differs from approval")
            if price.local_model_type is not None and not isinstance(model, price.local_model_type):
                raise HTTPException(409, "USAGE_LOCAL_CONTRACT: native model is not the registered no-provider implementation")
            if price.request_guard is not None:
                price.request_guard(model, tuple(arguments), keyword_arguments or {}, commitment)
            root, accounts = self._scope_accounts(conn, owner, task)
            grant_rows = conn.execute(select(self.grants).where(self.grants.c.task_id == root,
                self.grants.c.owner_id == owner, self.grants.c.state == "IMPORTED")).mappings().all()
            for grant in grant_rows:
                if grant["hash"] != digest(grant["body"]) or grant["body"]["receiverCommitmentSha256"] != self._commitment(conn, self.store.plan(self.store.task(root, owner)["plan_id"], owner))["sha256"]:
                    raise HTTPException(409, "USAGE_REMOTE_GRANT_INTEGRITY: receiver commitment differs")
                accounts.append(self._account(conn, "grant:" + grant["id"], owner, {
                    "schema": 1, "scope": "remote-grant", "grantSha256": grant["hash"], "currency": commitment["currency"],
                    "tokenLimit": grant["body"]["tokenLimit"], "amountMicros": grant["body"]["amountMicros"]}))
            if self.store.plan(self.store.task(root, owner)["plan_id"], owner).get("remoteHandoff") and not grant_rows:
                raise HTTPException(409, "USAGE_REMOTE_GRANT_REQUIRED: origin must reserve before remote provider execution")
            tokens = commitment["perAttemptInputTokens"] + commitment["perAttemptOutputTokens"]
            amount = price.charge(commitment["perAttemptInputTokens"], commitment["perAttemptOutputTokens"])
            self._hold(conn, accounts, tokens, amount)
            identity, at = str(uuid4()), now()
            body = {"schema": 1, "taskId": task["id"], "rootTaskId": root, "runId": context.run_id,
                "commitmentSha256": commitment["sha256"], "provider": price.provider, "model": price.model,
                "pricingRevision": price.revision, "pricingSha256": price.sha256, "currency": price.currency,
                "inputMicrosPerMillion": price.input_micros_per_million, "outputMicrosPerMillion": price.output_micros_per_million,
                "streaming": bool(streaming), "reservedTokens": tokens, "reservedAmountMicros": amount,
                "accountIds": [a["id"] for a in accounts]}
            conn.execute(self.attempts.insert().values(id=identity, owner_id=owner, task_id=task["id"],
                state="RESERVED", body=body, hash=digest(body), created_at=at, updated_at=at))
        self.store.event(task["id"], "provider_attempt_reserved", "Provider attempt admitted against durable shared ceilings",
            {"attemptId": identity, "provider": price.provider, "model": price.model, "streaming": bool(streaming),
             "reservedTokens": tokens, "reservedAmountMicros": amount, "currency": price.currency})
        return identity

    def evidence_for(self, plan, value):
        with self._transaction() as conn:
            commitment = self._commitment(conn, plan)
        price = self.by_adapter.get((commitment["adapterId"], commitment["adapterRevision"]))
        if price is None or price.sha256 != commitment["pricingSha256"]:
            return None
        try:
            evidence = price.usage_reader(value)
            return evidence if isinstance(evidence, UsageEvidence) else None
        except Exception:
            # Unparseable provider data does not become a free attempt.
            return None

    def finish_attempt(self, attempt_id, evidence: UsageEvidence | None):
        with self._transaction() as conn:
            self._lock(conn)
            row = conn.execute(select(self.attempts).where(self.attempts.c.id == attempt_id)).mappings().first()
            if row is None:
                raise HTTPException(404, "USAGE_ATTEMPT_NOT_FOUND: original reservation is required")
            body = row["body"]
            if row["hash"] != digest(body):
                raise HTTPException(409, "USAGE_ATTEMPT_INTEGRITY: immutable reservation differs")
            if evidence is None:
                if row["state"] != "SETTLED":
                    conn.execute(self.attempts.update().where(self.attempts.c.id == attempt_id).values(state="UNKNOWN", updated_at=now()))
                return {"id": attempt_id, "state": row["state"] if row["state"] == "SETTLED" else "UNKNOWN"}
            usage = asdict(evidence)
            if row["state"] == "SETTLED":
                if row["usage"] != usage:
                    raise HTTPException(409, "USAGE_SETTLEMENT_CONFLICT: authoritative usage cannot be rewritten")
                return {"id": attempt_id, "state": "SETTLED", "idempotent": True}
            charged = (evidence.input_tokens * body["inputMicrosPerMillion"]
                + evidence.output_tokens * body["outputMicrosPerMillion"] + 999999) // 1000000
            tokens = evidence.input_tokens + evidence.output_tokens
            for identity in body["accountIds"]:
                account = conn.execute(select(self.accounts).where(self.accounts.c.id == identity)).mappings().one()
                if account["hash"] != digest(account["body"]):
                    raise HTTPException(409, "USAGE_ACCOUNT_INTEGRITY: immutable account differs")
                if account["held_tokens"] < body["reservedTokens"] or account["held_amount"] < body["reservedAmountMicros"]:
                    raise HTTPException(409, "USAGE_RESERVATION_INTEGRITY: held balance cannot be released twice")
                conn.execute(self.accounts.update().where(self.accounts.c.id == identity).values(
                    held_tokens=self.accounts.c.held_tokens - body["reservedTokens"],
                    held_amount=self.accounts.c.held_amount - body["reservedAmountMicros"],
                    settled_tokens=self.accounts.c.settled_tokens + tokens,
                    settled_amount=self.accounts.c.settled_amount + charged))
            conn.execute(self.attempts.update().where(self.attempts.c.id == attempt_id).values(
                state="SETTLED", usage=usage, updated_at=now()))
        # Settlement is intentionally independent of current execution grants:
        # revoke/cancel after a response cannot erase an incurred bill.
        self.store.event(row["task_id"], "provider_attempt_settled", "Authoritative provider usage durably settled",
            {"attemptId": attempt_id, "inputTokens": evidence.input_tokens, "outputTokens": evidence.output_tokens,
             "chargedAmountMicros": charged, "currency": body["currency"], "usageEvidenceSha256": digest(usage),
             "reservationExceeded": tokens > body["reservedTokens"] or charged > body["reservedAmountMicros"]})
        return {"id": attempt_id, "state": "SETTLED", "chargedAmountMicros": charged}

    def inspect(self, owner, task_id):
        with self._transaction() as conn:
            self._lock(conn)
            task = self.store.task(task_id, owner)
            plan = self.store.plan(task["plan_id"], owner)
            commitment = self._commitment(conn, plan)
            service = getattr(self.store, "delegation", None)
            root, ancestors = service._ancestry(task) if service is not None else (task["id"], [])
            accounts = []
            for current in [task, *ancestors]:
                account = conn.execute(select(self.accounts).where(self.accounts.c.id == "task:" + current["id"])).mappings().first()
                if account is None:
                    current_commitment = self._commitment(conn, self.store.plan(current["plan_id"], owner))
                    account = {"id": "task:" + current["id"], "body": {"scope": "task", "taskId": current["id"],
                        "tokenLimit": current_commitment["tokenLimit"], "amountMicros": current_commitment["amountMicros"]},
                        "settled_tokens": 0, "settled_amount": 0, "held_tokens": 0, "held_amount": 0}
                elif account["hash"] != digest(account["body"]):
                    raise HTTPException(409, "USAGE_ACCOUNT_INTEGRITY: historical account differs")
                accounts.append(account)
            user = conn.execute(select(self.accounts).where(self.accounts.c.id == "user:" + owner)).mappings().first()
            if user is None:
                user = {"id": "user:" + owner, "body": {"scope": "user", "tokenLimit": self.policy.user_token_limit,
                    "amountMicros": self.policy.user_amount_micros}, "settled_tokens": 0, "settled_amount": 0, "held_tokens": 0, "held_amount": 0}
            elif user["hash"] != digest(user["body"]):
                raise HTTPException(409, "USAGE_ACCOUNT_INTEGRITY: historical user account differs")
            accounts.append(user)
            migration = conn.execute(select(self.migrations).where(self.migrations.c.plan_id == plan["id"])).mappings().first()
            scopes = []
            for account in accounts:
                kind = "user" if account["body"]["scope"] == "user" else "task" if account["id"] == "task:" + task["id"] else "root" if account["id"] == "task:" + root else "ancestor"
                scopes.append({"scope": kind, "id": owner if kind == "user" else account["body"]["taskId"],
                    "tokenLimit": account["body"]["tokenLimit"], "amountMicrosLimit": account["body"]["amountMicros"],
                    "settledTokens": account["settled_tokens"], "settledAmountMicros": account["settled_amount"],
                    "heldTokens": account["held_tokens"], "heldAmountMicros": account["held_amount"]})
            attempts = []
            for row in conn.execute(select(self.attempts).where(self.attempts.c.task_id == task["id"],
                    self.attempts.c.owner_id == owner).order_by(self.attempts.c.created_at)).mappings():
                if row["hash"] != digest(row["body"]):
                    raise HTTPException(409, "USAGE_ATTEMPT_INTEGRITY: historical attempt differs")
                item = {"id": row["id"], "state": row["state"], **{k: v for k, v in row["body"].items() if k != "accountIds"},
                    "createdAt": row["created_at"], "updatedAt": row["updated_at"]}
                if row["usage"] is not None:
                    usage = row["usage"]
                    item.update(inputTokens=usage["input_tokens"], outputTokens=usage["output_tokens"],
                        chargedAmountMicros=(usage["input_tokens"] * row["body"]["inputMicrosPerMillion"]
                            + usage["output_tokens"] * row["body"]["outputMicrosPerMillion"] + 999999) // 1000000,
                        usageEvidenceSha256=digest(usage))
                attempts.append(item)
            return {"schema": 1, "ownerId": owner, "taskId": task["id"], "rootTaskId": root,
                "currency": commitment["currency"], "commitment": copy.deepcopy(commitment), "scopes": scopes,
                "attempts": attempts, "hasUnknown": any(a["state"] in {"UNKNOWN", "RESERVED"} for a in attempts),
                "zeroTariff": commitment["inputMicrosPerMillion"] == commitment["outputMicrosPerMillion"] == 0,
                "migration": {"schema": 1, "sourcePlanSha256": migration["source_hash"], "commitmentSha256": commitment["sha256"]} if migration else None}


    def allocate_remote(self, owner, task_id, grant_id, *, origin_ref, target_ref,
                        receiver_owner, receiver_task_id, receiver_plan_sha256, receiver_commitment):
        """Commit origin holds before dispatch; grant ID is the original receipt ID."""
        if not all(isinstance(v, str) and 1 <= len(v) <= 200 for v in
                (grant_id, origin_ref, target_ref, receiver_owner, receiver_task_id, receiver_plan_sha256)):
            raise HTTPException(422, "USAGE_REMOTE_IDENTITY: bounded exact grant identities required")
        with self._transaction() as conn:
            self._lock(conn)
            task = self.store.task(task_id, owner)
            plan = self.store.plan(task["plan_id"], owner)
            source = self._commitment(conn, plan)
            self.validate_commitment(plan, source)
            self._compatible(source, receiver_commitment)
            body = {"schema": 1, "id": grant_id, "originRef": origin_ref, "targetRef": target_ref,
                "originOwnerId": owner, "originTaskId": task["id"], "sourcePlanSha256": digest(plan),
                "sourceCommitmentSha256": source["sha256"], "receiverOwnerId": receiver_owner,
                "receiverTaskId": receiver_task_id, "receiverPlanSha256": receiver_plan_sha256,
                "receiverCommitmentSha256": receiver_commitment["sha256"], "receiverCommitment": receiver_commitment,
                "currency": source["currency"], "tokenLimit": receiver_commitment["tokenLimit"],
                "amountMicros": receiver_commitment["amountMicros"]}
            old = conn.execute(select(self.grants).where(self.grants.c.id == grant_id)).mappings().first()
            if old:
                if old["owner_id"] != owner or old["task_id"] != task["id"] or old["body"] != body or old["hash"] != digest(body):
                    raise HTTPException(409, "USAGE_REMOTE_ALLOCATION_CONFLICT: original grant differs")
                return {**copy.deepcopy(body), "sha256": old["hash"]}
            _, accounts = self._scope_accounts(conn, owner, task)
            self._hold(conn, accounts, body["tokenLimit"], body["amountMicros"])
            conn.execute(self.grants.insert().values(id=grant_id, owner_id=owner, task_id=task["id"],
                body=body, hash=digest(body), state="ALLOCATED", allocation=[a["id"] for a in accounts]))
            return {**copy.deepcopy(body), "sha256": digest(body)}

    def import_remote_grant(self, owner, task_id, grant, *, expected_origin_ref, expected_target_ref, expected_origin_task_id,
                            expected_origin_owner=None, expected_source_plan_sha256=None, expected_source_commitment_sha256=None):
        """Trusted authenticated handoff only; there is no user grant-write API."""
        if not isinstance(grant, dict) or set(grant) != GRANT_KEYS or grant.get("sha256") != digest({k: v for k, v in grant.items() if k != "sha256"}):
            raise HTTPException(409, "USAGE_REMOTE_GRANT_INTEGRITY: allocation digest differs")
        body = {k: v for k, v in grant.items() if k != "sha256"}
        validate_usage_commitment(body["receiverCommitment"])
        for key, expected in (("originOwnerId", expected_origin_owner), ("sourcePlanSha256", expected_source_plan_sha256),
                ("sourceCommitmentSha256", expected_source_commitment_sha256)):
            if expected is not None and body.get(key) != expected:
                raise HTTPException(409, "USAGE_REMOTE_GRANT_SOURCE: original source identity/hash differs")
        with self._transaction() as conn:
            self._lock(conn)
            task = self.store.task(task_id, owner)
            plan = self.store.plan(task["plan_id"], owner)
            commitment = self._commitment(conn, plan)
            if any(body.get(k) != v for k, v in {"schema": 1, "originRef": expected_origin_ref,
                    "targetRef": expected_target_ref, "originTaskId": expected_origin_task_id,
                    "receiverOwnerId": owner, "receiverTaskId": task["id"], "receiverPlanSha256": digest(plan),
                    "receiverCommitmentSha256": commitment["sha256"], "receiverCommitment": commitment,
                    "currency": commitment["currency"], "tokenLimit": commitment["tokenLimit"],
                    "amountMicros": commitment["amountMicros"]}.items()):
                raise HTTPException(409, "USAGE_REMOTE_GRANT_IDENTITY: source/receiver/price binding differs")
            old = conn.execute(select(self.grants).where(self.grants.c.id == body["id"])).mappings().first()
            if old:
                if old["owner_id"] != owner or old["task_id"] != task["id"] or old["body"] != body or old["hash"] != grant["sha256"]:
                    raise HTTPException(409, "USAGE_REMOTE_IMPORT_CONFLICT: original imported grant differs")
            else:
                conn.execute(self.grants.insert().values(id=body["id"], owner_id=owner, task_id=task["id"],
                    body=body, hash=grant["sha256"], state="IMPORTED"))
            self._account(conn, "grant:" + body["id"], owner, {"schema": 1, "scope": "remote-grant",
                "grantSha256": grant["sha256"], "currency": commitment["currency"],
                "tokenLimit": body["tokenLimit"], "amountMicros": body["amountMicros"]})
        return {"id": body["id"], "sha256": grant["sha256"], "imported": True}

    def remote_statement(self, owner, task_id, grant_id, *, all_stopped=False):
        """Caller supplies positive native/effect/tree stop evidence, never absence."""
        if type(all_stopped) is not bool:
            raise HTTPException(422, "USAGE_REMOTE_STOP_EVIDENCE: explicit boolean required")
        with self._transaction() as conn:
            self._lock(conn)
            self.store.task(task_id, owner)
            row = conn.execute(select(self.grants).where(self.grants.c.id == grant_id,
                self.grants.c.owner_id == owner, self.grants.c.task_id == task_id)).mappings().first()
            if not row or row["state"] not in {"IMPORTED", "CLOSED"} or row["hash"] != digest(row["body"]):
                raise HTTPException(404, "USAGE_REMOTE_GRANT_NOT_FOUND: original receiver grant required")
            account = conn.execute(select(self.accounts).where(self.accounts.c.id == "grant:" + grant_id)).mappings().one()
            body = {"schema": 1, "grantId": grant_id, "grantSha256": row["hash"],
                "receiverOwnerId": owner, "receiverTaskId": task_id,
                "receiverPlanSha256": row["body"]["receiverPlanSha256"],
                "receiverCommitmentSha256": row["body"]["receiverCommitmentSha256"],
                "settledTokens": account["settled_tokens"], "settledAmountMicros": account["settled_amount"],
                "heldTokens": account["held_tokens"], "heldAmountMicros": account["held_amount"],
                "allStopped": all_stopped or row["state"] == "CLOSED"}
            previous = row["statement"]
            if previous and all(previous.get(k) == v for k, v in body.items()):
                return copy.deepcopy(previous)
            body["sequence"] = previous["sequence"] + 1 if previous else 1
            body["sha256"] = digest(body)
            conn.execute(self.grants.update().where(self.grants.c.id == grant_id).values(statement=body,
                state="CLOSED" if body["allStopped"] else "IMPORTED"))
            return body

    def apply_remote_statement(self, owner, task_id, statement):
        """Authenticated target receipt accounting; cumulative, monotonic, idempotent."""
        if not isinstance(statement, dict) or set(statement) != STATEMENT_KEYS or statement.get("sha256") != digest({k: v for k, v in statement.items() if k != "sha256"}):
            raise HTTPException(409, "USAGE_REMOTE_STATEMENT_INTEGRITY: exact statement digest required")
        for k in ("settledTokens", "settledAmountMicros", "heldTokens", "heldAmountMicros", "sequence"):
            integer(statement.get(k), k, minimum=1 if k == "sequence" else 0)
        if type(statement.get("allStopped")) is not bool:
            raise HTTPException(422, "USAGE_REMOTE_STATEMENT_STOP: explicit stop evidence required")
        with self._transaction() as conn:
            self._lock(conn)
            self.store.task(task_id, owner)
            row = conn.execute(select(self.grants).where(self.grants.c.id == statement.get("grantId"),
                self.grants.c.owner_id == owner, self.grants.c.task_id == task_id)).mappings().first()
            if not row or row["state"] not in {"ALLOCATED", "SETTLED"} or row["hash"] != digest(row["body"]):
                raise HTTPException(404, "USAGE_REMOTE_ALLOCATION_NOT_FOUND: original source hold required")
            grant = row["body"]
            if any(statement.get(k) != v for k, v in {"schema": 1, "grantSha256": row["hash"],
                    "receiverOwnerId": grant["receiverOwnerId"], "receiverTaskId": grant["receiverTaskId"],
                    "receiverPlanSha256": grant["receiverPlanSha256"],
                    "receiverCommitmentSha256": grant["receiverCommitmentSha256"]}.items()):
                raise HTTPException(409, "USAGE_REMOTE_STATEMENT_IDENTITY: receiver/grant differs")
            previous = row["statement"]
            if previous and statement["sequence"] <= previous["sequence"]:
                if statement == previous:
                    return {"id": row["id"], "state": row["state"], "idempotent": True}
                raise HTTPException(409, "USAGE_REMOTE_STATEMENT_STALE: previous accounting cannot reset")
            old_tokens, old_amount = (previous["settledTokens"], previous["settledAmountMicros"]) if previous else (0, 0)
            if (statement["settledTokens"] < old_tokens or statement["settledAmountMicros"] < old_amount
                    or previous and previous["allStopped"] and not statement["allStopped"]):
                raise HTTPException(409, "USAGE_REMOTE_STATEMENT_REGRESSION: cumulative accounting cannot decrease")
            release = statement["allStopped"] and statement["heldTokens"] == statement["heldAmountMicros"] == 0
            if row["state"] == "SETTLED":
                raise HTTPException(409, "USAGE_REMOTE_GRANT_CLOSED: settled original cap cannot reopen")
            old_hold_tokens, old_hold_amount = max(0, grant["tokenLimit"] - old_tokens), max(0, grant["amountMicros"] - old_amount)
            hold_tokens = 0 if release else max(0, grant["tokenLimit"] - statement["settledTokens"])
            hold_amount = 0 if release else max(0, grant["amountMicros"] - statement["settledAmountMicros"])
            for identity in row["allocation"]:
                account = conn.execute(select(self.accounts).where(self.accounts.c.id == identity)).mappings().one()
                if account["held_tokens"] < old_hold_tokens or account["held_amount"] < old_hold_amount:
                    raise HTTPException(409, "USAGE_REMOTE_HOLD_INTEGRITY: original allocation cannot release twice")
                conn.execute(self.accounts.update().where(self.accounts.c.id == identity).values(
                    held_tokens=self.accounts.c.held_tokens - old_hold_tokens + hold_tokens,
                    held_amount=self.accounts.c.held_amount - old_hold_amount + hold_amount,
                    settled_tokens=self.accounts.c.settled_tokens + statement["settledTokens"] - old_tokens,
                    settled_amount=self.accounts.c.settled_amount + statement["settledAmountMicros"] - old_amount))
            state = "SETTLED" if release else "ALLOCATED"
            conn.execute(self.grants.update().where(self.grants.c.id == row["id"]).values(state=state, statement=statement))
            return {"id": row["id"], "state": state, "releasedUnused": release}


    def reclaim_remote_no_dispatch(self, owner, task_id, grant_id, positive_receipt):
        """Trusted proof-checked receiver CAS cancellation, never a missing ACK.

        Caller must first verify receiver binding proof, sticky identities and
        current trusted target transport. This has no public write endpoint.
        """
        with self._transaction() as conn:
            self._lock(conn)
            self.store.task(task_id, owner)
            row = conn.execute(select(self.grants).where(self.grants.c.id == grant_id,
                self.grants.c.owner_id == owner, self.grants.c.task_id == task_id)).mappings().first()
            if not row or row["hash"] != digest(row["body"]):
                raise HTTPException(404, "USAGE_REMOTE_ALLOCATION_NOT_FOUND: original hold required")
            grant = row["body"]
            expected = {"id": grant_id, "originOwnerId": owner, "originTaskId": task_id,
                "remoteOwnerId": grant["receiverOwnerId"], "remoteTaskId": grant["receiverTaskId"],
                "receiverPlanSha256": grant["receiverPlanSha256"], "receiverUsageCommitment": grant["receiverCommitment"],
                "state": "CANCELLED_NO_DISPATCH", "remoteRunId": None, "native": None, "allStopped": True}
            if not isinstance(positive_receipt, dict) or any(k not in positive_receipt or positive_receipt[k] != v for k, v in expected.items()):
                raise HTTPException(409, "USAGE_REMOTE_NO_DISPATCH_PROOF: exact positive fenced cancellation required")
            previous = row["statement"]
            if previous and any(previous[k] != 0 for k in ("settledTokens", "settledAmountMicros", "heldTokens", "heldAmountMicros")):
                raise HTTPException(409, "USAGE_REMOTE_NO_DISPATCH_CONFLICT: accounted/unknown invocation cannot be erased")
            if row["state"] == "SETTLED":
                return {"id": grant_id, "state": "SETTLED", "idempotent": True}
            statement = {"schema": 1, "grantId": grant_id, "grantSha256": row["hash"],
                "receiverOwnerId": grant["receiverOwnerId"], "receiverTaskId": grant["receiverTaskId"],
                "receiverPlanSha256": grant["receiverPlanSha256"], "receiverCommitmentSha256": grant["receiverCommitmentSha256"],
                "settledTokens": 0, "settledAmountMicros": 0, "heldTokens": 0, "heldAmountMicros": 0,
                "allStopped": True, "sequence": previous["sequence"] + 1 if previous else 1}
            statement["sha256"] = digest(statement)
            return self.apply_remote_statement(owner, task_id, statement)

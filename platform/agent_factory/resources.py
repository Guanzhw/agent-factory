"""Trusted remote references and persistent leases; never a second scheduler.

Native runtime attachment, provider allocation and optional A2A are separate axes.
UNKNOWN acknowledgements are reconciled with reads, never replayed or freed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Awaitable, Callable, Mapping, Protocol, cast
from urllib.parse import quote, urlsplit
from uuid import uuid4

from fastapi import HTTPException
import httpx
from sqlalchemy import text

from .store import canonical, digest, now

TERMINAL = {"COMPLETED", "FAILED", "CANCEL_CONFIRMED"}
NATIVE_STATES = {"PENDING": "ACCEPTED", "RUNNING": "RUNNING", "PAUSED": "PAUSED",
                 "COMPLETED": "COMPLETED", "ERROR": "FAILED", "CANCELLED": "CANCEL_CONFIRMED"}


class ResourceProvider(Protocol):
    """Operator adapter contract. No native Agno environment allocator is assumed."""
    async def allocate(self, lease_id: str, owner: str, fingerprint: str, limits: dict) -> dict: ...
    async def inspect(self, lease_id: str, owner: str) -> dict: ...
    async def cancel(self, lease_id: str, owner: str) -> dict: ...
    async def reclaim(self, lease_id: str, owner: str) -> dict: ...


@dataclass(frozen=True)
class ComputePool:
    """Operator admission budgets; not a claim of kernel quota enforcement."""
    pool_id: str
    cpu: int
    memory_mb: int
    disk_mb: int
    max_leases: int = 20
    max_owner_leases: int = 2

    def __post_init__(self):
        if type(self.pool_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.pool_id):
            raise ValueError("A bounded operator pool identity is required")
        for value, ceiling in ((self.cpu, 65536), (self.memory_mb, 2**40), (self.disk_mb, 2**40),
                               (self.max_leases, 10000), (self.max_owner_leases, 10000)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("Pool budgets require bounded positive integers")
        if self.max_owner_leases > self.max_leases:
            raise ValueError("Owner slots cannot exceed pool slots")

    def limits(self):
        return {"cpu": self.cpu, "memoryMb": self.memory_mb, "diskMb": self.disk_mb,
                "maxLeases": self.max_leases, "maxOwnerLeases": self.max_owner_leases}

    @property
    def fingerprint(self):
        return digest({"poolId": self.pool_id, **self.limits()})


@dataclass(frozen=True)
class RemoteTarget:
    """Constructed by operator code, never deserialized from a user's request."""
    name: str
    axis: str
    owners: frozenset[str]
    base_url: str | None = None
    executor_id: str = "factory-executor"
    headers: Callable[[str], Mapping[str, str]] | None = field(default=None, repr=False)
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    provider: ResourceProvider | None = field(default=None, repr=False)
    max_leases: int = 2
    max_cpu: int = 2
    max_memory_mb: int = 2048
    max_disk_mb: int = 1024
    max_seconds: int = 300
    synthetic_fixture: bool = False
    expected_version: str = "3.1.0"
    configuration_revision: str = "1"
    capacity_pool: ComputePool | None = None

    def __post_init__(self):
        if self.axis not in {"runtime", "compute", "a2a"} or not self.owners:
            raise ValueError("A target needs a distinct axis and explicit owner grants")
        if self.base_url:
            url = urlsplit(self.base_url)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("Operator URL must be an HTTP origin/base path without credentials, query or fragment")
        if self.axis == "runtime" and not self.base_url:
            raise ValueError("Native runtime target requires an operator-configured URL")
        if self.axis == "runtime" and not self.synthetic_fixture and self.headers is None:
            raise ValueError("Production runtime requires a trusted per-user credential callback")
        if any(type(value) is not int or not 1 <= value <= 2**40
               for value in (self.max_leases, self.max_cpu, self.max_memory_mb, self.max_disk_mb, self.max_seconds)):
            raise ValueError("Positive operator resource ceilings are required")
        if self.capacity_pool is not None and (self.axis != "compute" or type(self.capacity_pool) is not ComputePool):
            raise ValueError("Compute pools apply only to explicit compute targets")


class NativeAgnoHTTP:
    """Selected 3.1.x public routes. Snapshot reads; no durable cursor promise."""
    def __init__(self, target: RemoteTarget):
        self.target = target

    async def request(self, owner: str, method: str, path: str, **kwargs):
        base_url = self.target.base_url
        if base_url is None:
            raise HTTPException(409, "Native runtime target URL is not configured")
        headers = dict(self.target.headers(owner)) if self.target.headers else {}
        headers.update(kwargs.pop("headers", {}))
        async with httpx.AsyncClient(base_url=base_url.rstrip("/") + "/",
                                     transport=self.target.transport, timeout=20,
                                     follow_redirects=False) as client:
            response = await client.request(method, path.lstrip("/"), headers=headers, **kwargs)
        if response.is_redirect:
            raise HTTPException(502, "Remote redirect denied; configure the actual target origin")
        if response.status_code >= 400:
            # Do not echo an upstream body that might contain paths or credentials.
            raise HTTPException(response.status_code, "Configured remote target rejected the operation")
        try:
            return response.json()
        except ValueError as error:
            raise HTTPException(502, "Remote acknowledgement is not valid JSON") from error

    async def handshake(self, owner: str) -> dict:
        info = await self.request(owner, "GET", "/info")
        config = await self.request(owner, "GET", "/config")
        if not isinstance(info, dict) or not isinstance(config, dict):
            raise HTTPException(502, "Remote metadata is not an object")
        version = info.get("agno_version")
        if version != self.target.expected_version:
            raise HTTPException(409, "Remote runtime version differs from the operator-pinned Agno version")
        agents = config.get("agents", [])
        ids = [item.get("id") for item in agents if isinstance(item, dict)]
        if self.target.executor_id not in ids:
            raise HTTPException(409, "Configured plan-aware executor was not discovered")
        if not self.target.synthetic_fixture and (info.get("auth_mode") != "jwt" or not info.get("user_isolation")):
            raise HTTPException(409, "Production remote attachment requires verified JWT identity and user isolation")
        # /info has no native boot epoch. Fixtures may explicitly provide it;
        # ordinary native targets remain unknown and cannot claim restart fencing.
        epoch = info.get("boot_epoch") if self.target.synthetic_fixture else None
        return {"serverVersion": version, "serverId": info.get("os_id"), "bootEpoch": epoch,
                "bootEpochVerified": epoch is not None and self.target.synthetic_fixture,
                "capabilities": {"registeredExecutor": self.target.executor_id,
                                 "reportedAgentCount": info.get("agent_count"),
                                 "authMode": info.get("auth_mode"), "userIsolation": info.get("user_isolation"),
                                 "allocation": False, "eventReplay": "not_verified", "reconciliation": "snapshot"},
                "syntheticFixture": self.target.synthetic_fixture}

    def run_path(self, run_id: str) -> str:
        return f"/agents/{quote(self.target.executor_id, safe='')}/runs/{quote(run_id, safe='')}"

    async def submit(self, owner: str, lease: dict) -> dict:
        return await self.request(owner, "POST", self.run_path("").rstrip("/"),
            headers={"Idempotency-Key": lease["id"]},
            data={"message": "Execute the persisted factory plan.", "session_id": lease["localTaskId"],
                  "background": "true", "stream": "false", "session_state": canonical({"factory_envelope": {
                      "task_id": lease["localTaskId"], "user_id": owner, "plan_ref": lease["planId"],
                      "request_id": lease["requestId"], "resource_fingerprint": lease["fingerprint"]}})})

    async def snapshot(self, owner: str, lease: dict) -> dict | None:
        params = {"session_id": lease["remoteSessionId"]}
        if lease.get("remoteRunId"):
            result = await self.request(owner, "GET", self.run_path(lease["remoteRunId"]), params=params)
            if not isinstance(result, dict):
                raise HTTPException(502, "Remote run snapshot is not an object")
            return result
        # Lost submit acknowledgement: inspect the unique task session. Its
        # persisted envelope must bind the exact fingerprint before adopting a run.
        path = f"/sessions/{quote(lease['remoteSessionId'], safe='')}"
        session = await self.request(owner, "GET", path, params={"type": "agent"})
        envelope = session.get("session_state", {}).get("factory_envelope", {}) if isinstance(session, dict) else {}
        if envelope.get("resource_fingerprint") != lease["fingerprint"] or envelope.get("user_id") != owner:
            return None
        runs = await self.request(owner, "GET", path + "/runs", params={"type": "agent"})
        candidates = [run for run in runs if isinstance(run, dict) and run.get("agent_id") == self.target.executor_id
                      and run.get("user_id") == owner and isinstance(run.get("run_id"), str)] if isinstance(runs, list) else []
        return candidates[0] if len(candidates) == 1 else None

    async def cancel(self, owner: str, lease: dict) -> dict:
        return await self.request(owner, "POST", self.run_path(lease["remoteRunId"]) + "/cancel",
                                  params={"session_id": lease["remoteSessionId"]})


class PersistentResourceService:
    """Factory metadata in existing af_resources/af_leases, not remote scheduling."""
    def __init__(self, store: Any, auth: Any, targets: Mapping[str, RemoteTarget]):
        self.store, self.auth = store, auth
        self.targets = dict(targets)
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", ref) for ref in self.targets):
            raise ValueError("Configured connection references must be bounded identifiers")
        pools = {}
        namespaces = {}
        for target in self.targets.values():
            pool = target.capacity_pool
            if pool is not None:
                if pool.pool_id in pools and pools[pool.pool_id] != pool:
                    raise ValueError("Conflicting definitions of the same compute pool")
                pools[pool.pool_id] = pool
            namespace = self._provider_namespace(target)
            if namespace is not None:
                identity = pool.fingerprint if pool is not None else None
                if namespace in namespaces and namespaces[namespace] != identity:
                    raise ValueError("Aliases of one provider namespace must share one capacity pool")
                namespaces[namespace] = identity

    def _authorize(self, owner: str, ref: str) -> RemoteTarget:
        self.auth.require(owner, "run")
        target = self.targets.get(ref)
        if target is None or owner not in target.owners:
            raise HTTPException(404, "Authorized resource reference not found")
        return target

    @staticmethod
    def _provider_namespace(target: RemoteTarget):
        namespace = getattr(target.provider, "capacity_namespace", None)
        if namespace is not None and (type(namespace) is not str or not re.fullmatch(r"[0-9a-f]{64}", namespace)):
            raise ValueError("Provider capacity namespace must be a SHA-256 identity")
        return namespace

    @staticmethod
    def _target_fingerprint(target: RemoteTarget) -> str:
        # URLs remain operator-only; persist a one-way binding fingerprint so
        # rebinding a reference cannot redirect existing cancellation/effects.
        provider_pin = getattr(target.provider, "configuration_fingerprint", None)
        if provider_pin is not None and (type(provider_pin) is not str or not re.fullmatch(r"[0-9a-f]{64}", provider_pin)):
            raise ValueError("Provider configuration fingerprint must be a SHA-256 identity")
        return digest({"axis": target.axis, "url": target.base_url, "executor": target.executor_id,
                       "version": target.expected_version, "revision": target.configuration_revision,
                       **({"providerFingerprint": provider_pin} if provider_pin is not None else {})})

    @staticmethod
    def _provider(target: RemoteTarget) -> ResourceProvider:
        if target.axis != "compute" or target.provider is None:
            raise HTTPException(409, "Configured compute provider is unavailable")
        return target.provider

    @property
    def _json_param(self):
        return "CAST(:body AS JSONB)" if self.store.engine.dialect.name == "postgresql" else ":body"

    def _body(self, value):
        return json.loads(value) if isinstance(value, str) else value

    def _lock(self, conn):
        if self.store.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_remote_resources'))"))

    def _resource(self, owner: str, ref: str, metadata: dict | None = None) -> dict:
        target = self._authorize(owner, ref)
        resource_id = digest({"owner": owner, "connectionRef": ref})
        rows = self.store.sql("SELECT body FROM af_resources WHERE id=:id AND owner_id=:owner", id=resource_id, owner=owner)
        old = self._body(rows[0]["body"]) if rows else {}
        capability_reader = getattr(target.provider, "isolation_capabilities", None)
        isolation = {"isolationCapabilities": capability_reader()} if callable(capability_reader) else {}
        body = {**old, "id": resource_id, "connectionRef": ref, "ownerId": owner, "name": target.name,
                "axis": target.axis, "updatedAt": now(), "allocationSupported": target.axis == "compute" and target.provider is not None,
                "syntheticFixture": target.synthetic_fixture, "targetFingerprint": self._target_fingerprint(target), **isolation, **(metadata or {})}
        if not callable(capability_reader):
            body.pop("isolationCapabilities", None)
        self.store.sql(f"INSERT INTO af_resources VALUES(:id,:owner,{self._json_param}) ON CONFLICT(id) DO UPDATE SET body={self._json_param}",
                       id=resource_id, owner=owner, body=canonical(body))
        return body

    def discover(self, owner: str) -> list[dict]:
        self.auth.require(owner, "run")
        return [self._resource(owner, ref) for ref, target in self.targets.items() if owner in target.owners]

    async def attach(self, owner: str, connection_ref: str, task_id: str | None = None, request_id: str | None = None) -> dict:
        target = self._authorize(owner, connection_ref)
        if target.axis == "a2a":
            return self._resource(owner, connection_ref, {"interface": "a2a", "dispatchSupported": False,
                                                        "status": "configured_not_verified"})
        if target.axis != "runtime":
            raise HTTPException(409, "Compute allocation is a separate provider operation")
        adapter = NativeAgnoHTTP(target)
        metadata = await adapter.handshake(owner)
        resource = self._resource(owner, connection_ref, metadata)
        if task_id is None:
            return resource
        lease, fresh = self._reserve(owner, connection_ref, task_id, request_id, {}, resource)
        if not fresh:
            return lease  # UNKNOWN/old requests are never replayed.
        self._admit_effect(owner, lease)
        try:
            result = await adapter.submit(owner, lease)
            return self._observe(owner, lease["id"], result)
        except (httpx.HTTPError, HTTPException, ValueError, TypeError):
            # Even an error response may follow a committed remote effect.
            return self._update(owner, lease["id"], "UNKNOWN", {"acknowledgement": "unknown", "connected": False})

    def _admit_effect(self, owner, lease):
        """Current task/owner authority immediately before new external work."""
        target = self._authorize(owner, lease["connectionRef"])
        pool = target.capacity_pool
        if (lease.get("targetFingerprint") != self._target_fingerprint(target)
                or lease.get("poolFingerprint") != (pool.fingerprint if pool is not None else None)
                or lease.get("providerNamespace") != self._provider_namespace(target)):
            raise HTTPException(409, "Allocation configuration changed before dispatch")
        task = self.store.task(lease["localTaskId"], owner)
        if lease.get("nativeRunId") is not None:
            self.store.process_runtime.guard_lease(lease)
        if (task.get("terminal") or task.get("cancel_requested")
                or datetime.now(timezone.utc) >= datetime.fromisoformat(lease["deadlineAt"])):
            raise HTTPException(409, "Canceled, terminal or expired work cannot allocate new effects")

    def _reserve(self, owner, ref, task_id, request_id, limits, resource=None, execution=None):
        target = self._authorize(owner, ref)
        if not isinstance(request_id, str) or not request_id or len(request_id) > 200:
            raise HTTPException(400, "A bounded request ID is required")
        task = self.store.task(task_id, owner)
        if task.get("terminal") or task.get("cancel_requested"):
            raise HTTPException(409, "A terminal or canceled local task cannot attach new execution")
        plan = self.store.plan(task["plan_id"], owner)
        if execution is not None:
            self.store.process_runtime.validate_execution(owner, task, plan, ref, execution)
        resource = resource or self._resource(owner, ref)
        pool = target.capacity_pool
        provider_namespace = self._provider_namespace(target)
        pool_binding = {"poolId": pool.pool_id, "poolFingerprint": pool.fingerprint,
                        "poolLimits": pool.limits()} if pool is not None else {}
        fingerprint = digest({"connectionRef": ref, "axis": target.axis, "taskId": task_id,
                              "targetFingerprint": self._target_fingerprint(target), "planHash": digest(plan),
                              "limits": limits, **({"poolFingerprint": pool.fingerprint} if pool is not None else {}),
                              **({"execution": execution} if execution is not None else {})})
        with self.store.engine.begin() as conn:
            self._lock(conn)
            if execution is not None:
                fresh_task = conn.execute(text("SELECT * FROM af_tasks WHERE id=:task FOR UPDATE"),
                    {"task": task_id}).mappings().first()
                if (fresh_task is None or fresh_task["terminal"] or fresh_task["cancel_requested"]
                        or fresh_task["owner_id"] != owner or fresh_task["plan_id"] != plan["id"]
                        or fresh_task["run_id"] != execution["nativeRunId"]):
                    raise HTTPException(409, "Original native task no longer admits process execution")
                prior = conn.execute(text("SELECT * FROM af_process_runs WHERE task_id=:task AND effect_key=:effect"),
                    {"task": task_id, "effect": execution["effectKey"]}).mappings().first()
                if prior:
                    binding = self._body(prior["body"])
                    if (prior["owner_id"] != owner or prior["native_run_id"] != execution["nativeRunId"]
                            or binding.get("leaseFingerprint") != fingerprint):
                        raise HTTPException(409, "Original process execution binding cannot be replaced")
                    original = conn.execute(text("SELECT body FROM af_leases WHERE id=:id AND owner_id=:owner"),
                        {"id": prior["lease_id"], "owner": owner}).first()
                    if original is None:
                        raise HTTPException(409, "Original process lease is unavailable; no replay")
                    return self._body(original[0]), False
            old = conn.execute(text("SELECT * FROM af_leases WHERE owner_id=:owner AND request_id=:request"), {"owner": owner, "request": request_id}).mappings().first()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: request is bound to different immutable resource work")
                return self._body(old["body"]), False
            # Count references across all owner-specific registry rows; users
            # cannot evade the configured target ceiling by changing their identity.
            rows = conn.execute(text("SELECT l.body FROM af_leases l JOIN af_resources r ON l.target_id=r.id WHERE l.state <> 'RECLAIMED'" )).mappings().all()
            held = [self._body(row["body"]) for row in rows]
            # A restart/config change cannot hide an old pool reservation behind
            # another pool, an unpooled alias, or a replacement provider.
            for previous in held:
                if (provider_namespace is not None and previous.get("providerNamespace") == provider_namespace
                        and (previous.get("poolId") != pool_binding.get("poolId")
                             or previous.get("poolFingerprint") != pool_binding.get("poolFingerprint"))):
                    raise HTTPException(409, "Provider namespace still holds its original pool reservations")
                if previous.get("connectionRef") == ref and (pool is not None or previous.get("poolId") is not None):
                    if (previous.get("poolId") != pool_binding.get("poolId")
                            or previous.get("poolFingerprint") != pool_binding.get("poolFingerprint")
                            or previous.get("targetFingerprint") != self._target_fingerprint(target)):
                        raise HTTPException(409, "Active allocation configuration changed; reconcile original leases before admission")
            if pool is not None:
                pooled = [item for item in held if item.get("poolId") == pool.pool_id]
                if any(item.get("poolFingerprint") != pool.fingerprint for item in pooled):
                    raise HTTPException(409, "Active pool configuration changed; original reservations remain held")
                if any(item.get("localTaskId") == task_id for item in pooled):
                    raise HTTPException(409, "Task already holds a compute allocation in this pool; reconcile its original lease")
                if len(pooled) >= pool.max_leases or sum(item.get("ownerId") == owner for item in pooled) >= pool.max_owner_leases:
                    raise HTTPException(429, "Compute pool or owner admission slots are reserved")
                for key in ("cpu", "memoryMb", "diskMb"):
                    values = [item.get("limits", {}).get(key) for item in pooled]
                    if any(type(value) is not int or value <= 0 for value in values):
                        raise HTTPException(409, "Held allocation has invalid resource accounting; operator reconciliation required")
                    if sum(values) + limits[key] > pool.limits()[key]:
                        raise HTTPException(429, "Compute pool capacity is reserved; UNKNOWN retains all resource dimensions")
            count = sum(self._body(row["body"]).get("connectionRef") == ref for row in rows)
            if count >= target.max_leases:
                raise HTTPException(429, "Resource capacity is reserved; UNKNOWN acknowledgements retain capacity")
            if target.axis == "runtime" and any(self._body(row["body"]).get("localTaskId") == task_id
                                                and self._body(row["body"]).get("axis") == "runtime" for row in rows):
                raise HTTPException(409, "Task already has a remote runtime attachment; reconcile its original lease")
            lease_id = str(uuid4())
            at = datetime.now(timezone.utc)
            duration = limits.get("seconds", target.max_seconds)
            body = {"id": lease_id, "ownerId": owner, "connectionRef": ref, "axis": target.axis,
                    "localTaskId": task_id, "planId": plan["id"], "requestId": request_id,
                    "fingerprint": fingerprint, "remoteSessionId": task_id if target.axis == "runtime" else None,
                    "remoteRunId": None, "state": "RESERVED", "capacityHeld": True, "connected": False,
                    "limits": limits, "bootEpoch": resource.get("bootEpoch"), "createdAt": at.isoformat(),
                    "serverVersion": resource.get("serverVersion"), "serverId": resource.get("serverId"),
                    "targetFingerprint": self._target_fingerprint(target),
                    "updatedAt": at.isoformat(), "heartbeatAt": at.isoformat(),
                    **({"nativeRunId": execution["nativeRunId"], "planHash": digest(plan)} if execution is not None else {}),
                    "deadlineAt": (at + timedelta(seconds=duration)).isoformat(), "cancelRequested": False,
                    "artifacts": [], "syntheticFixture": target.synthetic_fixture, "reconciliation": "snapshot", **pool_binding,
                    **({"providerNamespace": provider_namespace} if provider_namespace is not None else {})}
            conn.execute(text(f"INSERT INTO af_leases VALUES(:id,:owner,:target,:request,:fp,'RESERVED',{self._json_param})"),
                         {"id": lease_id, "owner": owner, "target": resource["id"], "request": request_id, "fp": fingerprint, "body": canonical(body)})
            if execution is not None:
                binding = {"taskId": task_id, "nativeRunId": execution["nativeRunId"], "planId": plan["id"],
                    "ownerId": owner, "leaseId": lease_id, "targetRef": ref, "planHash": digest(plan),
                    "requestId": request_id, "leaseFingerprint": fingerprint}
                conn.execute(text(f"INSERT INTO af_process_runs VALUES(:task,:effect,:owner,:run,:lease,{self._json_param})"),
                    {"task": task_id, "effect": execution["effectKey"], "owner": owner,
                     "run": execution["nativeRunId"], "lease": lease_id, "body": canonical(binding)})
        self.store.audit(owner, "resource.reserve", lease_id, {"connectionRef": ref, "fingerprint": fingerprint})
        return body, True

    def inspect(self, owner: str, lease_id: str) -> dict:
        self.auth.require(owner, "run")
        rows = self.store.sql("SELECT * FROM af_leases WHERE id=:id AND owner_id=:owner", id=lease_id, owner=owner)
        if not rows:
            raise HTTPException(404, "Scoped resource lease not found")
        body = self._body(rows[0]["body"])
        target = self._authorize(owner, body["connectionRef"])
        if body.get("targetFingerprint") != self._target_fingerprint(target):
            raise HTTPException(409, "Connection reference was rebound; existing lease requires operator reconciliation")
        body["expired"] = datetime.now(timezone.utc) >= datetime.fromisoformat(body["deadlineAt"])
        return body

    def _update(self, owner, lease_id, state, changes=None):
        with self.store.engine.begin() as conn:
            self._lock(conn)
            row = conn.execute(text("SELECT * FROM af_leases WHERE id=:id AND owner_id=:owner"), {"id": lease_id, "owner": owner}).mappings().first()
            if row is None:
                raise HTTPException(404, "Scoped lease not found")
            body = self._body(row["body"])
            if body["state"] == "RECLAIMED":
                return body
            if body["state"] in TERMINAL and state not in TERMINAL | {"RECLAIMING", "RECLAIMED"}:
                state = body["state"]
            if body.get("cancelRequested") and state in {"RUNNING", "ACCEPTED", "PAUSED"}:
                state = "CANCEL_REQUESTED"
            if body.get("releaseAck") == "unknown" and state in TERMINAL:
                state = "RECLAIMING"
            body = {**body, **(changes or {}), "state": state, "updatedAt": now(), "capacityHeld": state != "RECLAIMED"}
            conn.execute(text(f"UPDATE af_leases SET state=:state,body={self._json_param} WHERE id=:id AND owner_id=:owner"),
                         {"id": lease_id, "owner": owner, "state": state, "body": canonical(body)})
        return body

    def _observe(self, owner, lease_id, snapshot):
        lease = self.inspect(owner, lease_id)
        if not isinstance(snapshot, dict):
            raise ValueError("Remote snapshot is not an object")
        target = self._authorize(owner, lease["connectionRef"])
        if target.axis == "runtime":
            remote_run = snapshot.get("run_id")
            if not isinstance(remote_run, str) or not remote_run or len(remote_run) > 200:
                raise ValueError("Remote run identity missing")
            if lease.get("remoteRunId") not in {None, remote_run}:
                raise ValueError("Remote run binding changed")
            if snapshot.get("session_id", lease["remoteSessionId"]) != lease["remoteSessionId"]:
                raise ValueError("Remote session binding changed")
            if snapshot.get("user_id", owner) != owner or snapshot.get("agent_id", target.executor_id) != target.executor_id:
                raise ValueError("Remote run owner/executor mismatch")
            state = NATIVE_STATES.get(str(snapshot.get("status", "")).upper(), "UNKNOWN")
            changes = {"remoteRunId": remote_run}
        else:
            if snapshot.get("leaseId") != lease_id or snapshot.get("ownerId") != owner or snapshot.get("fingerprint") != lease["fingerprint"]:
                raise ValueError("Provider lease identity/fingerprint mismatch")
            state = snapshot.get("state", "UNKNOWN")
            if state not in TERMINAL | {"ACCEPTED", "RUNNING", "UNKNOWN", "RECLAIMED"}:
                state = "UNKNOWN"
            # A provider must separately prove released allocation. Completion
            # or cancellation alone is not proof of compute capacity release.
            if state == "RECLAIMED" and snapshot.get("released") is not True:
                state = "UNKNOWN"
            changes = {"providerJobId": snapshot.get("providerJobId")}
            if lease.get("nativeRunId") is not None:
                changes = self.process_snapshot(lease, snapshot)
        return self._update(owner, lease_id, state, {**changes, "connected": True,
                            "acknowledgement": "confirmed", "observedStatus": snapshot.get("status", snapshot.get("state")),
                            "snapshotAt": now()})

    @staticmethod
    def process_snapshot(lease, snapshot):
        if (type(snapshot) is not dict or snapshot.get("leaseId") != lease["id"]
                or snapshot.get("ownerId") != lease["ownerId"] or snapshot.get("fingerprint") != lease["fingerprint"]):
            raise ValueError("Process lease receipt mismatch")
        binding, job = snapshot.get("processBinding"), snapshot.get("providerJobId")
        if snapshot.get("state") == "UNKNOWN" and binding is None and job is None:
            return {}
        if (type(binding) is not dict or set(binding) != {"taskId", "nativeRunId", "planId", "bindingFingerprint"}
                or any(binding.get(key) != expected for key, expected in
                    (("taskId", lease["localTaskId"]), ("nativeRunId", lease["nativeRunId"]), ("planId", lease["planId"])))
                or not isinstance(binding.get("bindingFingerprint"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", binding["bindingFingerprint"])
                or type(job) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", job)
                or lease.get("providerJobId") not in {None, job}
                or lease.get("processBinding") not in (None, binding)):
            raise ValueError("Original process identity changed")
        enforcement = snapshot.get("enforcement")
        expected = {"cpu": "per-process-RLIMIT_CPU", "memory": "per-process-RLIMIT_AS",
            "fileSize": "per-file-RLIMIT_FSIZE", "wall": "cooperative-process-group-guardian",
            "aggregateQuota": False, "hostileCodeSandbox": False, "networkIsolation": False}
        aggregate = None
        if type(enforcement) is dict and enforcement.get("schema") == 2:
            from .aggregate_process import validate_aggregate_evidence
            aggregate = validate_aggregate_evidence(snapshot.get("aggregateEvidence"), binding["bindingFingerprint"],
                enforcement, lease.get("aggregateEvidence"))
            expected = enforcement
        elif (type(enforcement) is not dict or enforcement != expected
                or any(type(enforcement[key]) is not type(value) for key, value in expected.items())
                or snapshot.get("aggregateEvidence") is not None):
            raise ValueError("Process enforcement contract changed")
        if lease.get("enforcement") not in (None, expected):
            raise ValueError("Original enforcement declaration changed")
        outcome, exit_code = snapshot.get("executionStatus"), snapshot.get("exitCode")
        if (outcome not in {"PREPARED", "DISPATCHING", "RUNNING", "UNKNOWN", "COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}
                or exit_code is not None and (type(exit_code) is not int or not -255 <= exit_code <= 255)):
            raise ValueError("Process outcome is invalid")
        stop = snapshot.get("stopEvidence")
        positive = (type(stop) is dict and set(stop) == {"allStopped", "kind"} and stop["allStopped"] is True
                    and stop["kind"] in ({"original-delegated-cgroup-empty-and-removed", "never-dispatched"} if aggregate is not None
                                           else {"original-root-reaped-and-no-live-process-group-members", "never-dispatched"}))
        if positive and aggregate is not None and isinstance(stop, dict):
            from .aggregate_process import aggregate_stopped
            if not (aggregate["state"] == "NEW" if stop["kind"] == "never-dispatched" else aggregate_stopped(aggregate)):
                raise ValueError("Original aggregate stop proof is unconfirmed")
        if snapshot.get("state") in TERMINAL | {"RECLAIMED"} and (not positive or outcome not in {"COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}):
            raise ValueError("Terminal process lacks original stop proof")
        if snapshot.get("state") == "RECLAIMED" and snapshot.get("released") is not True:
            raise ValueError("Process allocation release is unconfirmed")
        return {"providerJobId": job, "processBinding": binding, "enforcement": expected,
                "stopEvidence": stop if positive else None, "executionStatus": outcome, "exitCode": exit_code,
                **({"aggregateEvidence": aggregate} if aggregate is not None else {})}

    def list_leases(self, owner, *, after=None):
        self.auth.require(owner, "run")
        if after is not None and (type(after) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", after)):
            raise HTTPException(400, "Invalid lease cursor")
        rows = self.store.sql("SELECT id,body FROM af_leases WHERE owner_id=:owner AND id>:after ORDER BY id LIMIT 100",
                              owner=owner, after=after or "")
        leases = []
        for row in rows:
            body = self._body(row["body"])
            if body.get("nativeRunId") is None:
                continue
            # Metadata visibility does not grant launch/stop/release authority.
            fields = ("id", "ownerId", "localTaskId", "planId", "nativeRunId", "state", "capacityHeld",
                      "providerJobId", "processBinding", "enforcement", "aggregateEvidence", "stopEvidence", "syntheticFixture", "executionStatus", "exitCode")
            leases.append({key: body.get(key) for key in fields})
        return {"leases": leases, "nextCursor": rows[-1]["id"] if len(rows) == 100 else None}

    def _claim_effect(self, owner, lease_id, field, state, *, reason=None):
        """Compare-and-set before transmission across processes, not a Python lock."""
        if reason is not None and (field != "cancelAck" or reason not in {
                "TASK_CANCEL_REQUESTED", "NATIVE_TERMINAL", "LEASE_EXPIRED", "AUTHORITY_ENDED"}):
            raise ValueError("Invalid original-custody cancellation reason")
        with self.store.engine.begin() as conn:
            self._lock(conn)
            row = conn.execute(text("SELECT body FROM af_leases WHERE id=:id AND owner_id=:owner"),
                               {"id": lease_id, "owner": owner}).mappings().first()
            if row is None:
                raise HTTPException(404, "Scoped lease not found")
            body = self._body(row["body"])
            if body.get(field) not in {None, "not_sent"} or body["state"] == "RECLAIMED":
                return body, False
            if field == "cancelAck" and body["state"] in TERMINAL:
                return body, False
            if field == "releaseAck" and body["state"] not in TERMINAL:
                return body, False
            body = {**body, field: "unknown", "state": state, "updatedAt": now(), "capacityHeld": True}
            if field == "cancelAck":
                body["cancelRequested"] = True
                if reason is not None:
                    body["cancellationReason"] = reason
            conn.execute(text(f"UPDATE af_leases SET state=:state,body={self._json_param} WHERE id=:id AND owner_id=:owner"),
                         {"id": lease_id, "owner": owner, "state": state, "body": canonical(body)})
            return body, True

    async def allocate(self, owner: str, connection_ref: str, task_id: str, request_id: str, limits: dict, *, execution=None) -> dict:
        target = self._authorize(owner, connection_ref)
        if target.axis != "compute" or target.provider is None:
            raise HTTPException(409, "ALLOCATION_UNSUPPORTED: native runtime attachment does not provision environments")
        if callable(getattr(target.provider, "allocate_bound", None)) and execution is None:
            raise HTTPException(409, "Governed native execution binding is required for process allocation")
        if execution is not None and (not callable(getattr(target.provider, "allocate_bound", None)) or target.capacity_pool is None):
            raise HTTPException(409, "Bound process execution requires its configured shared pool")
        ceilings = {"cpu": target.max_cpu, "memoryMb": target.max_memory_mb, "diskMb": target.max_disk_mb, "seconds": target.max_seconds}
        if not isinstance(limits, dict) or set(limits) != set(ceilings) or any(type(limits[key]) is not int or not 0 < limits[key] <= ceiling for key, ceiling in ceilings.items()):
            raise HTTPException(400, "Allocation must stay within all configured resource ceilings")
        lease, fresh = self._reserve(owner, connection_ref, task_id, request_id, limits, execution=execution)
        if not fresh:
            return lease
        self._admit_effect(owner, lease)
        try:
            provider = self._provider(target)
            guarded: Any = getattr(provider, "allocate_guarded", None)
            bound: Any = getattr(provider, "allocate_bound", None)
            if execution is not None and callable(bound):
                result = await cast(Awaitable[dict], bound(lease, before_effect=lambda: self._admit_effect(owner, lease)))
            elif callable(guarded):
                result = await cast(Awaitable[dict], guarded(lease["id"], owner, lease["fingerprint"], limits,
                                       before_effect=lambda: self._admit_effect(owner, lease)))
            else:
                result = await provider.allocate(lease["id"], owner, lease["fingerprint"], limits)
            return self._observe(owner, lease["id"], result)
        except Exception:
            return self._update(owner, lease["id"], "UNKNOWN", {"acknowledgement": "unknown", "connected": False})

    async def reconcile(self, owner: str, lease_id: str) -> dict:
        lease = self.inspect(owner, lease_id)
        if lease["state"] == "RECLAIMED":
            return lease
        target = self._authorize(owner, lease["connectionRef"])
        try:
            if target.axis == "runtime":
                adapter = NativeAgnoHTTP(target)
                info = await adapter.handshake(owner)
                if lease.get("serverId") is not None and lease["serverId"] != info.get("serverId"):
                    return self._update(owner, lease_id, "UNKNOWN", {"serverIdentityMismatch": True, "connected": True})
                if lease.get("bootEpoch") is not None and lease["bootEpoch"] != info.get("bootEpoch"):
                    return self._update(owner, lease_id, "UNKNOWN", {"epochMismatch": True, "connected": True})
                snapshot = await adapter.snapshot(owner, lease)
            else:
                snapshot = await self._provider(target).inspect(lease_id, owner)
            if snapshot is None:
                return self._update(owner, lease_id, "UNKNOWN", {"connected": True})
            result = self._observe(owner, lease_id, snapshot)
            if result["state"] in TERMINAL and not result.get("artifactCaptured"):
                # Native file/workspace transfer is not invented. Persist only
                # the observed result snapshot as a provenance-marked artifact.
                payload = canonical({"observedStatus": snapshot.get("status", snapshot.get("state")), "content": snapshot.get("content"), "metrics": snapshot.get("metrics")})
                metadata = {"origin": "configured_remote_snapshot", "connectionRef": lease["connectionRef"],
                            "remoteRunId": result.get("remoteRunId"), "remoteSessionId": lease.get("remoteSessionId"),
                            "bootEpoch": lease.get("bootEpoch"), "syntheticFixture": target.synthetic_fixture,
                            "researchValidated": False}
                artifact = self.store.artifact_write(lease["localTaskId"], f"remote-{lease_id}.json", payload, "application/json", metadata)
                result = self._update(owner, lease_id, result["state"], {"artifactCaptured": True, "artifacts": [artifact]})
            return result
        except Exception:
            return self._update(owner, lease_id, "UNKNOWN", {"connected": False, "lastRead": "unconfirmed"})

    async def cancel(self, owner: str, lease_id: str) -> dict:
        lease = self.inspect(owner, lease_id)
        if lease["state"] in TERMINAL | {"RECLAIMED"}:
            return lease
        target = self._authorize(owner, lease["connectionRef"])
        if lease.get("cancelAck") in {"accepted", "unknown"}:
            return lease  # repeated cancel is a read/reconcile, not another effect.
        if target.axis == "runtime" and not lease.get("remoteRunId"):
            return self._update(owner, lease_id, "UNKNOWN", {"cancelRequested": True, "cancelAck": "not_sent"})
        # Persist uncertainty BEFORE transmission. A lost cancellation reply is
        # never retried automatically; reconcile the original run/provider lease.
        lease, fresh = self._claim_effect(owner, lease_id, "cancelAck", "CANCEL_REQUESTED")
        if not fresh:
            return lease
        self._authorize(owner, lease["connectionRef"])
        try:
            if target.axis == "runtime":
                await NativeAgnoHTTP(target).cancel(owner, lease)
            else:
                await self._provider(target).cancel(lease_id, owner)
            return self._update(owner, lease_id, "CANCEL_REQUESTED", {"cancelAck": "accepted"})
        except Exception:
            return self._update(owner, lease_id, "UNKNOWN", {"cancelAck": "unknown", "connected": False})

    def disconnect(self, owner: str, lease_id: str) -> dict:
        lease = self.inspect(owner, lease_id)
        return self._update(owner, lease_id, lease["state"], {"connected": False})

    def heartbeat(self, owner: str, lease_id: str) -> dict:
        lease = self.inspect(owner, lease_id)
        if lease["state"] in TERMINAL | {"RECLAIMED"} or lease["expired"]:
            raise HTTPException(409, "Lease cannot renew after its fixed deadline or terminal observation")
        return self._update(owner, lease_id, lease["state"], {"heartbeatAt": now()})

    async def reclaim(self, owner: str, lease_id: str) -> dict:
        lease = self.inspect(owner, lease_id)
        if lease["state"] == "RECLAIMED":
            return lease
        if lease["state"] not in TERMINAL:
            raise HTTPException(409, "Only confirmed terminal execution can be reclaimed; UNKNOWN retains capacity")
        if lease.get("releaseAck") == "unknown":
            raise HTTPException(409, "Release acknowledgement unknown; inspect the existing provider lease without replay")
        target = self._authorize(owner, lease["connectionRef"])
        if target.axis == "runtime":
            # Releases only our runtime attachment slot. No VM/container/files
            # destruction and no remote compute lease release is implied.
            return self._update(owner, lease_id, "RECLAIMED", {"reclaimedAt": now(), "releaseScope": "runtime_attachment_only"})
        lease, fresh = self._claim_effect(owner, lease_id, "releaseAck", "RECLAIMING")
        if not fresh:
            return lease
        try:
            await self._provider(target).reclaim(lease_id, owner)
        except Exception:
            return self._update(owner, lease_id, "UNKNOWN", {"releaseAck": "unknown"})
        # Provider acknowledgement is not release confirmation; inspect again.
        return await self.reconcile(owner, lease_id)

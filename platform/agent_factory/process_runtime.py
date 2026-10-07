"""Governed native execution using original shared-pool process custody.

The existing lifecycle observer invokes bounded stop-only reconciliation. It
cannot allocate, replace native runs, restore grants or replay uncertain effects.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import hashlib
import math
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import text

from .local_compute import LocalComputeBusy
from .resource_maintenance import ResourceMaintenance
from .resources import TERMINAL
from .store import canonical, digest, now

TOOL = "bounded_process_run"
EFFECT = "bounded-process-run-v1"


def _require(value):
    if not value:
        raise HTTPException(409, "PROCESS_EXECUTION_BINDING_INVALID")


def process_reservation(provider):
    """Reserve the complete declared job budget before any external dispatch."""
    limits = getattr(provider, "limits", None)
    _require(limits is not None)
    assert limits is not None
    _require(type(limits.address_space_mb) is int and limits.address_space_mb > 0
             and type(limits.file_size_bytes) is int and limits.file_size_bytes > 0
             and type(limits.wall_seconds) in {int, float}
             and math.isfinite(limits.wall_seconds) and limits.wall_seconds > 0)
    preflight = getattr(provider, "preflight_seconds", 0)
    _require(type(preflight) is int and 0 <= preflight <= 30)
    mib = 1024 * 1024
    reservation = {"cpu": 1, "memoryMb": limits.address_space_mb,
                   "diskMb": max(1, (limits.file_size_bytes + mib - 1) // mib),
                   "seconds": math.ceil(limits.wall_seconds) + preflight}
    disk_bytes = getattr(limits, "disk_bytes", None)
    if disk_bytes is not None:
        _require(type(disk_bytes) is int and disk_bytes >= limits.file_size_bytes)
        reservation["diskMb"] = max(reservation["diskMb"], (disk_bytes + mib - 1) // mib)
    aggregate = getattr(provider, "aggregate_config", None)
    if aggregate is not None:
        quota, period = aggregate.cpu_quota_us, aggregate.cpu_period_us
        memory, swap = aggregate.memory_bytes, aggregate.swap_bytes
        _require(all(type(value) is int and value > 0 for value in (quota, period, memory))
                 and type(swap) is int and swap >= 0)
        reservation["cpu"] = max(reservation["cpu"], (quota + period - 1) // period)
        reservation["memoryMb"] = max(reservation["memoryMb"], (memory + swap + mib - 1) // mib)
    return reservation


class ProcessRuntimeService:
    tool_name = TOOL
    effect_key = EFFECT
    def __init__(self, store, auth, resources):
        self.store, self.auth, self.resources = store, auth, resources
        self._cursor = ""
        self._tick_lock = asyncio.Lock()

    def task_held(self, task_id):
        return bool(self.store.sql("""SELECT EXISTS(SELECT 1 FROM af_process_runs p
            LEFT JOIN af_leases l ON p.lease_id=l.id WHERE p.task_id=:task
            AND (l.id IS NULL OR l.state<>'RECLAIMED')) AS held""", task=task_id)[0]["held"])

    def _context(self, task):
        return SimpleNamespace(user_id=task["owner_id"], session_id=task["id"], run_id=task["run_id"],
            session_state={"factory_envelope": {"plan_ref": task["plan_id"], "user_id": task["owner_id"],
                "task_id": task["id"], "request_id": task["request_id"]}})

    def validate_execution(self, owner, task, plan, target_ref, execution):
        _require(type(execution) is dict and set(execution) == {"nativeRunId", "effectKey"}
            and execution["effectKey"] == self.effect_key and type(task.get("run_id")) is str
            and execution["nativeRunId"] == task["run_id"] and owner == task["owner_id"])
        # Receiver mappings preserve the immutable source manifest. Resolve the
        # already-verified effective target under this exact native context.
        bindings = self.store.execution_bindings
        _require(bindings is not None)
        specs = bindings.manifest(plan, context=self._context(task)).get("tools", [])
        selected = [item for item in specs if item.get("toolName") == self.tool_name]
        _require(len(selected) == 1 and selected[0].get("config") == {"targetRef": target_ref})
        self.store.authorize_tool(self._context(task), self.tool_name)

    def guard_lease(self, lease):
        self.resources._authorize(lease["ownerId"], lease["connectionRef"])
        task = self.store.task(lease["localTaskId"], lease["ownerId"])
        plan = self.store.plan(lease["planId"], lease["ownerId"])
        _require(task["plan_id"] == lease["planId"] and digest(plan) == lease["planHash"])
        self.validate_execution(lease["ownerId"], task, plan, lease["connectionRef"],
                                {"nativeRunId": lease["nativeRunId"], "effectKey": self.effect_key})

    def _original(self, task_id):
        rows = self.store.sql("SELECT * FROM af_process_runs WHERE task_id=:task AND effect_key=:effect",
                              task=task_id, effect=self.effect_key)
        _require(len(rows) <= 1)
        return rows[0] if rows else None

    def _custody(self, lease_id):
        # Reuse strict persisted resource-directory checks, without a synthetic
        # admin principal or the ability to grant new execution authority.
        lease = ResourceMaintenance(self.resources)._custody(lease_id)
        _require(lease.get("executionEffect", EFFECT) == self.effect_key)
        row = self._original(lease["localTaskId"])
        _require(row is not None)
        assert row is not None
        body = row["body"] if isinstance(row["body"], dict) else json.loads(row["body"])
        expected = {"taskId": lease["localTaskId"], "nativeRunId": lease.get("nativeRunId"),
            "planId": lease["planId"], "ownerId": lease["ownerId"], "leaseId": lease_id,
            "targetRef": lease["connectionRef"], "planHash": lease.get("planHash"),
            "requestId": lease["requestId"], "leaseFingerprint": lease["fingerprint"]}
        _require(row["lease_id"] == lease_id and row["native_run_id"] == lease.get("nativeRunId")
            and row["owner_id"] == lease["ownerId"] and body == expected)
        target = self.resources.targets.get(lease["connectionRef"])
        _require(target is not None and target.axis == "compute" and target.capacity_pool is not None
            and target.provider is not None and callable(getattr(target.provider, "allocate_bound", None)))
        _require(lease["targetFingerprint"] == self.resources._target_fingerprint(target)
            and lease.get("poolFingerprint") == target.capacity_pool.fingerprint
            and lease.get("providerNamespace") == self.resources._provider_namespace(target))
        task = self.store.task(lease["localTaskId"], lease["ownerId"])
        plan = self.store.plan(lease["planId"], lease["ownerId"])
        _require(task["run_id"] == lease["nativeRunId"] and task["plan_id"] == lease["planId"]
                 and digest(plan) == lease["planHash"])
        observer = self.store.lifecycle_observer
        _require(observer is not None)
        ticket = observer._binding(task)
        _require(ticket is not None and ticket["id"] == lease["nativeRunId"])
        assert ticket is not None
        return lease, target, task, ticket

    def _reason(self, lease, task, ticket):
        if task["cancel_requested"]:
            return "TASK_CANCEL_REQUESTED"
        if task["terminal"] or ticket["status"] in {"completed", "cancelled", "failed"}:
            return "NATIVE_TERMINAL"
        if datetime.now(timezone.utc) >= datetime.fromisoformat(lease["deadlineAt"]):
            return "LEASE_EXPIRED"
        try:
            self.guard_lease(lease)
        except HTTPException as error:
            if error.status_code in {403, 404, 409}:
                return "AUTHORITY_ENDED"
            raise
        except PermissionError:
            return "AUTHORITY_ENDED"
        return None

    async def _read(self, lease_id):
        lease, target, _, _ = self._custody(lease_id)
        if lease["state"] == "RECLAIMED":
            return lease
        snapshot = await self.resources._provider(target).inspect(lease_id, lease["ownerId"])
        fresh, current, _, _ = self._custody(lease_id)
        _require(current is target)
        changes = self.resources.process_snapshot(fresh, snapshot)
        state = snapshot.get("state")
        _require(state in TERMINAL | {"ACCEPTED", "RUNNING", "UNKNOWN", "RECLAIMED"})
        return self.resources._update(fresh["ownerId"], lease_id, state,
            {**changes, "snapshotAt": now(), "connected": True, "observedStatus": state})

    async def observe_lease(self, lease_id):
        """Internal original-custody read/stop/reclaim only; never dispatch."""
        lease, target, task, ticket = self._custody(lease_id)
        if lease["state"] == "RECLAIMED":
            return lease
        reason = self._reason(lease, task, ticket)
        try:
            lease = await self._read(lease_id)
        except LocalComputeBusy:
            # Allocation may still hold the original custody lock. Preserve the
            # last durable observation and capacity; a busy read proves no stop
            # and must not trigger another effect or replace the original lease.
            latest, current, _, _ = self._custody(lease_id)
            _require(current is target)
            return latest
        if reason is not None and lease["state"] not in TERMINAL | {"RECLAIMED", "RECLAIMING"}:
            lease, fresh = self.resources._claim_effect(lease["ownerId"], lease_id, "cancelAck", "CANCEL_REQUESTED", reason=reason)
            if fresh:
                latest, current, current_task, current_ticket = self._custody(lease_id)
                _require(current is target and self._reason(latest, current_task, current_ticket) is not None)
                try:
                    await self.resources._provider(target).cancel(lease_id, lease["ownerId"])
                except Exception:
                    pass  # Original request remains UNKNOWN; only inspect, never replay.
                self._custody(lease_id)
            lease = await self._read(lease_id)
        if lease["state"] in TERMINAL:
            lease, fresh = self.resources._claim_effect(lease["ownerId"], lease_id, "releaseAck", "RECLAIMING")
            if fresh:
                latest, current, _, _ = self._custody(lease_id)
                _require(current is target and latest["state"] == "RECLAIMING")
                try:
                    await self.resources._provider(target).reclaim(lease_id, lease["ownerId"])
                except Exception:
                    pass
                self._custody(lease_id)
            lease = await self._read(lease_id)
        return lease

    async def tick(self):
        async with self._tick_lock:
            query = """SELECT p.lease_id,p.effect_key FROM af_process_runs p LEFT JOIN af_leases l ON l.id=p.lease_id
                WHERE (l.id IS NULL OR l.state<>'RECLAIMED') AND p.lease_id>:after ORDER BY p.lease_id LIMIT 20"""
            rows = self.store.sql(query, after=self._cursor)
            if not rows and self._cursor:
                rows = self.store.sql(query, after="")
            self._cursor = rows[-1]["lease_id"] if len(rows) == 20 else ""
            results = []
            for row in rows:
                try:
                    runtime = self.resources.execution_runtime(row["effect_key"])
                    lease = await runtime.observe_lease(row["lease_id"])
                    results.append({"leaseId": row["lease_id"], "state": lease["state"], "capacityHeld": lease["capacityHeld"]})
                except Exception:
                    results.append({"leaseId": row["lease_id"], "state": "UNKNOWN", "capacityHeld": True})
            return results

    def _receipt(self, context, lease):
        # Serialize receipts without occupying metadata connections needed by
        # fresh authorization and provenance. This also works with a size-one pool.
        key = "process-receipt:" + lease["id"]
        with self.store.root_lock_engine().connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": key})
            conn.commit()
            try:
                return self._write_receipt(context, lease)
            finally:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key})
                conn.commit()

    def _write_receipt(self, context, lease):
        self.store.authorize_tool(context, self.tool_name)
        _require(lease["state"] == "RECLAIMED" and lease.get("stopEvidence", {}).get("allStopped") is True)
        result = {key: lease.get(key) for key in ("id", "localTaskId", "planId", "nativeRunId", "providerJobId",
            "state", "capacityHeld", "processBinding", "enforcement", "stopEvidence", "executionStatus", "exitCode")}
        if lease.get("aggregateEvidence") is not None:
            result["aggregateEvidence"] = lease["aggregateEvidence"]
        evidence_kind = "bounded_aggregate_process_receipt" if lease.get("aggregateEvidence") is not None else "bounded_cooperative_process_receipt"
        result.update(leaseId=lease["id"], evidenceKind=evidence_kind, researchValidated=False)
        raw = canonical(result)
        name = "process-" + lease["id"] + ".json"
        existing = [a for a in self.store.artifacts(context.session_id) if a["name"] == name]
        if existing:
            _require(len(existing) == 1 and existing[0]["sha256"] == hashlib.sha256(raw.encode()).hexdigest())
            artifact = existing[0]
        else:
            self.store.authorize_tool(context, self.tool_name)
            artifact = self.store.artifact_write(context.run_id, name, raw, "application/json",
                {"evidenceKind": evidence_kind, "leaseId": lease["id"],
                 "nativeRunId": context.run_id, "providerJobId": lease["providerJobId"], "researchValidated": False})
        return {**result, "artifactId": artifact["id"], "artifactSha256": artifact["sha256"]}

    async def run(self, context, config):
        _require(type(config) is dict and set(config) == {"targetRef"})
        self.store.authorize_tool(context, self.tool_name)
        task = self.store.task(context.session_id, context.user_id)
        plan = self.store.plan(task["plan_id"], context.user_id)
        execution = {"nativeRunId": context.run_id, "effectKey": self.effect_key}
        self.validate_execution(context.user_id, task, plan, config["targetRef"], execution)
        prior = self._original(task["id"])
        if prior:
            _require(prior["native_run_id"] == context.run_id and prior["owner_id"] == context.user_id)
            lease = self.resources.inspect(context.user_id, prior["lease_id"])
            _require(lease["connectionRef"] == config["targetRef"])
        else:
            target = self.resources._authorize(context.user_id, config["targetRef"])
            provider = self.resources._provider(target)
            reservation = process_reservation(provider)
            lease = await self.resources.allocate(context.user_id, config["targetRef"], task["id"],
                "process-" + digest({"task": task["id"], "run": context.run_id, "effect": self.effect_key}), reservation, execution=execution)
        # Bounded observation only; a later native retry can read the same binding
        # but can never issue a second allocate, even after positive release.
        deadline = asyncio.get_running_loop().time() + 7
        while True:
            self.store.authorize_tool(context, self.tool_name)
            lease = await self.observe_lease(lease["id"])
            if lease["state"] == "RECLAIMED":
                result = await asyncio.to_thread(self._receipt, context, lease)
                if lease.get("executionStatus") != "COMPLETED":
                    raise HTTPException(409, "PROCESS_EXECUTION_FAILED_WITH_STOP_PROOF")
                return result
            if asyncio.get_running_loop().time() >= deadline:
                raise HTTPException(409, "PROCESS_OUTCOME_UNKNOWN_CAPACITY_HELD")
            await asyncio.sleep(.05)

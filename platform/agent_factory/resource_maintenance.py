"""Explicit operator stop-only cleanup of existing compute custody.

No allocation, scheduling, owner-authority bypass for ordinary operations, or
replay of uncertain effects. Positive identity-bound reads alone release holds.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from fastapi import HTTPException

from .resources import TERMINAL
from .store import digest, now


class _Held(Exception):
    def __init__(self, reason):
        self.reason = reason


class ResourceMaintenance:
    def __init__(self, resources):
        self.resources = resources

    def _admin(self, operator):
        self.resources.auth.require(operator, "agent_os:admin")

    def _custody(self, lease_id):
        resources = self.resources
        rows = resources.store.sql("SELECT * FROM af_leases WHERE id=:id", id=lease_id)
        if len(rows) != 1:
            raise _Held("CUSTODY_INVALID")
        row = rows[0]
        body = resources._body(row["body"])
        if (type(body) is not dict or body.get("id") != row["id"]
                or body.get("ownerId") != row["owner_id"]
                or body.get("fingerprint") != row["fingerprint"]
                or body.get("requestId") != row["request_id"]
                or body.get("state") != row["state"] or body.get("axis") != "compute"
                or any(type(body.get(key)) is not str or not body[key] or len(body[key]) > 200
                       for key in ("id", "ownerId", "connectionRef", "localTaskId", "planId"))):
            raise _Held("CUSTODY_INVALID")
        if any(type(body.get(key)) is not str or not re.fullmatch(r"[a-f0-9]{64}", body[key])
               for key in ("fingerprint", "targetFingerprint")):
            raise _Held("CUSTODY_INVALID")
        if row["target_id"] != digest({"owner": body["ownerId"], "connectionRef": body["connectionRef"]}):
            raise _Held("CUSTODY_INVALID")
        directory = resources.store.sql("SELECT * FROM af_resources WHERE id=:id", id=row["target_id"])
        if len(directory) != 1 or directory[0]["owner_id"] != body["ownerId"]:
            raise _Held("DIRECTORY_UNAVAILABLE")
        resource = resources._body(directory[0]["body"])
        if (type(resource) is not dict or resource.get("id") != row["target_id"]
                or any(resource.get(key) != body.get(key) for key in ("ownerId", "connectionRef", "axis", "targetFingerprint"))):
            raise _Held("CUSTODY_INVALID")
        return body

    def _current(self, operator, original, target):
        self._admin(operator)
        lease = self._custody(original["id"])
        keys = ("id", "ownerId", "connectionRef", "fingerprint", "targetFingerprint", "localTaskId", "planId", "requestId")
        if any(lease.get(key) != original.get(key) for key in keys):
            raise _Held("CUSTODY_CHANGED")
        current = self.resources.targets.get(lease["connectionRef"])
        if current is not target or current is None or current.axis != "compute":
            raise _Held("TARGET_UNAVAILABLE")
        if lease.get("targetFingerprint") != self.resources._target_fingerprint(current):
            raise _Held("TARGET_REBOUND")
        if current.provider is None:
            raise _Held("TARGET_UNAVAILABLE")
        return lease, self.resources._provider(current)

    def _reason(self, lease):
        try:
            self.resources.auth.require(lease["ownerId"], "run")
        except HTTPException as error:
            if error.status_code == 403:
                return "OWNER_REVOKED"
            raise _Held("OWNER_AUTH_UNAVAILABLE") from None
        except Exception:
            raise _Held("OWNER_AUTH_UNAVAILABLE") from None
        try:
            deadline = datetime.fromisoformat(lease["deadlineAt"])
            if deadline.tzinfo is None:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise _Held("DEADLINE_INVALID") from None
        if datetime.now(timezone.utc) >= deadline:
            return "DEADLINE_EXPIRED"
        try:
            task = self.resources.store.task(lease["localTaskId"], lease["ownerId"])
        except Exception:
            raise _Held("TASK_UNAVAILABLE") from None
        if task.get("plan_id") != lease["planId"]:
            raise _Held("CUSTODY_INVALID")
        if task.get("terminal") is True:
            return "TASK_TERMINAL"
        return "TASK_CANCEL_REQUESTED" if task.get("cancel_requested") is True else None

    async def _read(self, operator, original, target):
        lease, provider = self._current(operator, original, target)
        if lease["state"] == "RECLAIMED":
            return lease
        try:
            snapshot = await provider.inspect(lease["id"], lease["ownerId"])
        except Exception:
            raise _Held("READ_UNCONFIRMED") from None
        # A provider await is an authority/configuration change boundary.
        lease, _ = self._current(operator, original, target)
        if (type(snapshot) is not dict or any(type(snapshot.get(key)) is not str or snapshot[key] != expected
                for key, expected in (("leaseId", lease["id"]), ("ownerId", lease["ownerId"]), ("fingerprint", lease["fingerprint"])))):
            raise _Held("SNAPSHOT_INVALID")
        changes = {}
        if lease.get("nativeRunId") is not None:
            try:
                changes = self.resources.process_snapshot(lease, snapshot)
            except (ValueError, TypeError):
                raise _Held("PROCESS_RECEIPT_UNCONFIRMED") from None
        state = snapshot.get("state")
        if type(state) is not str or state not in TERMINAL | {"ACCEPTED", "RUNNING", "UNKNOWN", "RECLAIMED"}:
            raise _Held("SNAPSHOT_INVALID")
        if state == "RECLAIMED":
            if snapshot.get("released") is not True:
                raise _Held("RELEASE_UNCONFIRMED")
            return self.resources._update(lease["ownerId"], lease["id"], "RECLAIMED",
                {**changes, "reclaimedAt": now(), "releaseScope": "compute_provider", "snapshotAt": now()})
        # Terminal execution is still held until reclaim and positive release.
        return self.resources._update(lease["ownerId"], lease["id"], state,
            {**changes, "snapshotAt": now(), "connected": True})

    async def _effect(self, operator, original, target, field):
        lease, _ = self._current(operator, original, target)
        if field == "releaseAck" and lease["state"] not in TERMINAL:
            return
        state = "CANCEL_REQUESTED" if field == "cancelAck" else "RECLAIMING"
        lease, fresh = self.resources._claim_effect(lease["ownerId"], lease["id"], field, state)
        if not fresh:
            return
        lease, provider = self._current(operator, original, target)
        if lease["state"] == "RECLAIMED":
            return
        try:
            if field == "cancelAck":
                await provider.cancel(lease["id"], lease["ownerId"])
            else:
                await provider.reclaim(lease["id"], lease["ownerId"])
        except Exception:
            # CAS already persisted unknown. Do not retry or free capacity.
            return
        lease, _ = self._current(operator, original, target)
        if field == "cancelAck":
            self.resources._update(lease["ownerId"], lease["id"], "CANCEL_REQUESTED", {"cancelAck": "accepted"})

    async def sweep(self, operator_id, *, limit=20, after=None) -> dict[str, Any]:
        self._admin(operator_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise HTTPException(400, "Maintenance limit must be an integer between 1 and 100")
        if after is not None and (type(after) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", after)):
            raise HTTPException(400, "Maintenance cursor must be a bounded lease identifier")
        rows = self.resources.store.sql(
            "SELECT id FROM af_leases WHERE state <> 'RECLAIMED' AND body->>'axis'='compute' AND id > :after ORDER BY id LIMIT :limit", limit=limit, after=after or "")
        outcomes = []
        for row in rows:
            identifier = row["id"]
            outcome = {"leaseId": identifier if type(identifier) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier) else None,
                       "status": "held", "reason": "UNCONFIRMED", "capacityHeld": True}
            try:
                self._admin(operator_id)
                original = self._custody(identifier)
                target = self.resources.targets.get(original["connectionRef"])
                lease, _ = self._current(operator_id, original, target)
                reason = self._reason(lease)
                if reason is None:
                    outcome.update(status="skipped", reason="NOT_ELIGIBLE")
                else:
                    lease = await self._read(operator_id, original, target)
                    if lease["state"] not in TERMINAL | {"RECLAIMED", "RECLAIMING"}:
                        await self._effect(operator_id, original, target, "cancelAck")
                        lease = await self._read(operator_id, original, target)
                    if lease["state"] in TERMINAL:
                        await self._effect(operator_id, original, target, "releaseAck")
                        lease = await self._read(operator_id, original, target)
                    outcome.update(status="reclaimed" if lease["state"] == "RECLAIMED" else "held",
                                   reason=reason, capacityHeld=lease["state"] != "RECLAIMED")
            except _Held as error:
                outcome["reason"] = error.reason
            except HTTPException:
                outcome["reason"] = "AUTHORITY_OR_CUSTODY_UNAVAILABLE"
            except Exception:
                outcome["reason"] = "UNCONFIRMED"
            outcomes.append(outcome)
        return {"schema": 1, "scanned": len(rows), "outcomes": outcomes,
                "nextCursor": rows[-1]["id"] if len(rows) == limit else None}

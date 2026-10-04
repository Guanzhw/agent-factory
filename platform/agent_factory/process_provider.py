"""Task-bound process custody backed by durable resource admission.

Trusted operator programs only. Per-process rlimits and a cooperative process
group guardian are not aggregate quotas, a hostile-code sandbox, or network
isolation. Reclaim releases capacity while retaining original custody evidence.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
from inspect import isawaitable, iscoroutine
import json
import hashlib
import math
import os
from pathlib import Path
import re
import threading
import sys
from typing import cast

from sqlalchemy import text

from .local_compute import LocalWorkspaceProvider
from .process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec
from .store import canonical, digest

_BINDINGS = ("id", "ownerId", "fingerprint", "localTaskId", "planId", "nativeRunId", "requestId",
             "connectionRef", "planHash", "targetFingerprint", "poolId", "poolFingerprint", "providerNamespace", "limits")
_PINS = ("id", "specSha256", "identitySha256", "rootPin")
_TERMINAL = {"COMPLETED": "COMPLETED", "CANCELLED": "CANCEL_CONFIRMED", "LIMIT_STOPPED": "FAILED", "FAILED": "FAILED"}


def _require(value):
    if not value:
        raise ValueError("PROCESS_ALLOCATION_UNCONFIRMED")


class ProcessResourceProvider:
    def __init__(self, store, root: Path, spec: ProcessSpec, limits: ProcessLimits):
        _require(sys.platform == "linux")
        _require(type(spec) is ProcessSpec and type(limits) is ProcessLimits)
        self.store, self.spec, self.limits = store, spec, limits
        # Reuse descriptor-pinned root traversal and bounded directory flock.
        # No workspace allocation or its journal API is invoked.
        self._root_guard = LocalWorkspaceProvider(store, root)
        self.root = self._root_guard.root

    @property
    def capacity_namespace(self):
        return digest({"namespace": "process-custody-v1", "root": self._root_guard.capacity_namespace})

    @property
    def configuration_fingerprint(self):
        return digest({"namespace": self.capacity_namespace, "spec": asdict(self.spec),
                       "limits": asdict(self.limits), "revision": "process-provider-v1"})

    def _binding(self, lease: dict):
        _require(type(lease) is dict and all(key in lease for key in _BINDINGS))
        for key in ("id", "ownerId", "localTaskId", "planId", "nativeRunId", "requestId", "connectionRef", "poolId"):
            _require(type(lease[key]) is str and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", lease[key]))
        _require(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", lease["id"]))
        for key in ("fingerprint", "planHash", "targetFingerprint", "poolFingerprint", "providerNamespace"):
            _require(type(lease[key]) is str and re.fullmatch(r"[a-f0-9]{64}", lease[key]))
        _require(lease["providerNamespace"] == self.capacity_namespace)
        budgets = lease["limits"]
        _require(type(budgets) is dict and set(budgets) == {"cpu", "memoryMb", "diskMb", "seconds"}
                 and all(type(value) is int and 0 < value <= 2147483647 for value in budgets.values()))
        budgets = cast(dict[str, int], budgets)
        _require(budgets["cpu"] >= 1 and budgets["memoryMb"] >= self.limits.address_space_mb
                 and budgets["diskMb"] >= math.ceil(self.limits.file_size_bytes / (1024 * 1024))
                 and budgets["seconds"] >= self.limits.wall_seconds)
        # JSON roundtrip detaches caller-owned mutable inputs before thread work.
        return json.loads(canonical({key: lease[key] for key in _BINDINGS}))

    @contextmanager
    def _transaction(self):
        with self.store.engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "af_process_allocations"})
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _decode(value):
        return json.loads(value) if isinstance(value, str) else value

    def _save(self, conn, record, *, insert=False):
        value = "CAST(:body AS JSONB)" if conn.dialect.name == "postgresql" else ":body"
        query = (f"INSERT INTO af_process_allocations(id,owner_id,body) VALUES(:id,:owner,{value})" if insert else
                 f"UPDATE af_process_allocations SET body={value} WHERE id=:id AND owner_id=:owner")
        conn.execute(text(query), {"id": record["binding"]["id"], "owner": record["binding"]["ownerId"], "body": canonical(record)})

    def _load(self, conn, lease_id, owner):
        row = conn.execute(text("SELECT body FROM af_process_allocations WHERE id=:id AND owner_id=:owner"),
                           {"id": lease_id, "owner": owner}).mappings().first()
        _require(row is not None)
        record = self._decode(row["body"])
        _require(record["binding"]["id"] == lease_id and record["binding"]["ownerId"] == owner)
        _require(record["configurationFingerprint"] == self.configuration_fingerprint)
        _require(record["bindingHash"] == digest(self._binding(record["binding"])))
        self._verify_mapping(conn, record["binding"])
        return record

    def _verify_mapping(self, conn, binding):
        lease = conn.execute(text("SELECT body FROM af_leases WHERE id=:id AND owner_id=:owner"),
            {"id": binding["id"], "owner": binding["ownerId"]}).mappings().first()
        _require(lease is not None and self._binding(self._decode(lease["body"])) == binding)
        row = conn.execute(text("SELECT task_id,owner_id,native_run_id,lease_id,body FROM af_process_runs "
            "WHERE task_id=:task AND effect_key=:effect"),
            {"task": binding["localTaskId"], "effect": "bounded-process-run-v1"}).mappings().first()
        _require(row is not None and row["owner_id"] == binding["ownerId"]
                 and row["native_run_id"] == binding["nativeRunId"] and row["lease_id"] == binding["id"])
        expected = {"taskId": binding["localTaskId"], "nativeRunId": binding["nativeRunId"],
            "planId": binding["planId"], "ownerId": binding["ownerId"], "leaseId": binding["id"],
            "targetRef": binding["connectionRef"], "planHash": binding["planHash"],
            "requestId": binding["requestId"], "leaseFingerprint": binding["fingerprint"]}
        _require(self._decode(row["body"]) == expected)

    def _dispatch_authority(self, binding, cancelled, callback):
        self._authority(cancelled, callback)
        with self._transaction() as conn:
            self._verify_mapping(conn, binding)
        # Database lock waits can outlast cancellation or authority changes.
        self._authority(cancelled, callback)

    @staticmethod
    def _authority(cancelled, callback):
        if cancelled.is_set():
            raise asyncio.CancelledError()
        result = callback()
        if isawaitable(result):
            if iscoroutine(result):
                result.close()
            raise ValueError("PROCESS_ALLOCATION_UNCONFIRMED")
        if cancelled.is_set():
            raise asyncio.CancelledError()

    async def allocate(self, lease_id, owner, fingerprint, limits):
        raise ValueError("PROCESS_LEASE_CONTEXT_REQUIRED")

    async def allocate_bound(self, lease: dict, *, before_effect):
        _require(callable(before_effect))
        binding = self._binding(lease)
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(self._allocate, binding, cancelled, before_effect)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def _allocate(self, binding, cancelled, callback):
        with self._root_guard._operation_lock():
            self._authority(cancelled, callback)
            with self._transaction() as conn:
                self._verify_mapping(conn, binding)
                rows = conn.execute(text("SELECT id,body FROM af_process_allocations WHERE id=:id OR "
                    "(owner_id=:owner AND body->'binding'->>'fingerprint'=:fp)"),
                    {"id": binding["id"], "owner": binding["ownerId"], "fp": binding["fingerprint"]}).mappings().all()
                for row in rows:
                    previous = self._decode(row["body"])
                    if row["id"] == binding["id"]:
                        _require(previous["binding"] == binding)
                        return self._snapshot(self._load(conn, binding["id"], binding["ownerId"]))
                    _require(previous.get("released") is True)
                record = {"binding": binding, "bindingHash": digest(binding),
                    "configurationFingerprint": self.configuration_fingerprint, "state": "UNKNOWN", "released": False,
                    "allStopped": False, "stopKind": None, "executionStatus": "UNKNOWN", "exitCode": None, "directoryIdentity": None, "journalIdentity": None, "processPin": None}
                self._save(conn, record, insert=True)
            try:
                with self._root_guard._root() as root_fd:
                    os.mkdir(binding["id"], mode=0o700, dir_fd=root_fd)
                    fd = os.open(binding["id"], os.O_RDONLY | self._root_guard._directory_flag |
                                 self._root_guard._nofollow_flag, dir_fd=root_fd)
                    try:
                        info = os.fstat(fd)
                        record["directoryIdentity"] = [info.st_dev, info.st_ino]
                        os.fsync(fd); os.fsync(root_fd)
                    finally:
                        os.close(fd)
                path = self.root / binding["id"] / "custody.sqlite"
                adapter = BoundedProcessAdapter.create(path, owner_id=binding["ownerId"], task_id=binding["localTaskId"],
                    request_id=binding["requestId"], spec=self.spec, limits=self.limits)
                original = adapter.inspect(owner_id=binding["ownerId"])
                self._validate_process(record, original, pin=False)
                info = path.lstat()
                record["journalIdentity"] = [info.st_dev, info.st_ino]
                record["processPin"] = {key: original[key] for key in _PINS}
                with self._transaction() as conn:
                    self._save(conn, record)
                adapter.launch(owner_id=binding["ownerId"], before_effect=lambda: self._dispatch_authority(binding, cancelled, callback))
                return self._inspect_locked(binding["id"], binding["ownerId"])
            except (Exception, asyncio.CancelledError):
                # Never retry create/launch after durable intent, including uncertain
                # dispatch. Original journal remains available for inspect/cancel.
                with self._transaction() as conn:
                    return self._snapshot(self._load(conn, binding["id"], binding["ownerId"]))

    def _validate_process(self, record, snapshot, *, pin=True):
        binding = record["binding"]
        _require(type(snapshot) is dict and snapshot.get("ownerId") == binding["ownerId"]
                 and snapshot.get("taskId") == binding["localTaskId"] and snapshot.get("requestId") == binding["requestId"]
                 and snapshot.get("limits") == asdict(self.limits))
        _require(snapshot.get("state") in {*_TERMINAL, "PREPARED", "DISPATCHING", "RUNNING", "UNKNOWN"})
        exit_code = snapshot.get("exitCode")
        _require(exit_code is None or type(exit_code) is int and -255 <= exit_code <= 255)
        _require(all(key in snapshot for key in _PINS))
        _require(snapshot["specSha256"] == hashlib.sha256(json.dumps(
            {"spec": asdict(self.spec), "limits": asdict(self.limits)},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        if pin:
            _require(record["processPin"] == {key: snapshot[key] for key in _PINS})

    @contextmanager
    def _adapter(self, record):
        binding = record["binding"]
        with self._root_guard._root() as root_fd:
            fd = os.open(binding["id"], os.O_RDONLY | self._root_guard._directory_flag |
                         self._root_guard._nofollow_flag, dir_fd=root_fd)
            try:
                info = os.fstat(fd)
                _require(record["directoryIdentity"] == [info.st_dev, info.st_ino])
                info = os.stat("custody.sqlite", dir_fd=fd, follow_symlinks=False)
                _require(record["journalIdentity"] == [info.st_dev, info.st_ino])
                adapter = BoundedProcessAdapter(self.root / binding["id"] / "custody.sqlite")
                snapshot = adapter.inspect(owner_id=binding["ownerId"])
                self._validate_process(record, snapshot)
                yield adapter, snapshot
            finally:
                os.close(fd)

    @staticmethod
    def _snapshot(record):
        binding = record["binding"]
        return {"leaseId": binding["id"], "ownerId": binding["ownerId"], "fingerprint": binding["fingerprint"],
            "bindingSha256": record["bindingHash"],
            "processBinding": {"taskId": binding["localTaskId"], "nativeRunId": binding["nativeRunId"],
                "planId": binding["planId"], "bindingFingerprint": record["bindingHash"]},
            "stopEvidence": {"allStopped": True, "kind": record["stopKind"]}
                if record["allStopped"] else None, "state": record["state"], "released": record["released"],
            "executionStatus": record["executionStatus"], "exitCode": record["exitCode"],
            "allStopped": record["allStopped"], "capacityHeld": record["released"] is not True,
            "providerJobId": (record.get("processPin") or {}).get("id"), "retainedEvidence": True,
            "allocationKind": "bounded-cooperative-process", "enforcement": {
                "cpu": "per-process-RLIMIT_CPU", "memory": "per-process-RLIMIT_AS", "fileSize": "per-file-RLIMIT_FSIZE",
                "wall": "cooperative-process-group-guardian", "aggregateQuota": False,
                "hostileCodeSandbox": False, "networkIsolation": False}}

    def _inspect_locked(self, lease_id, owner, action="inspect"):
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
        try:
            with self._adapter(record) as (adapter, snapshot):
                if action == "cancel" and not record["released"]:
                    snapshot = adapter.cancel(owner_id=owner)
                    self._validate_process(record, snapshot)
                proof_kind = (snapshot.get("stopReceipt") or {}).get("kind")
                stopped = (snapshot.get("stoppedProof") is True and snapshot.get("state") in _TERMINAL
                           and proof_kind in {"original-group-stopped", "never-dispatched"})
                record.update(executionStatus=snapshot["state"], exitCode=snapshot.get("exitCode"))
                if snapshot["state"] in _TERMINAL and not stopped:
                    record.update(executionStatus="UNKNOWN", exitCode=None)
                record["stopKind"] = ("never-dispatched" if proof_kind == "never-dispatched" else
                    "original-root-reaped-and-no-live-process-group-members") if stopped else None
                if record["released"]:
                    _require(stopped)
                    record.update(state="RECLAIMED", allStopped=True)
                elif stopped:
                    record.update(state=_TERMINAL[snapshot["state"]], allStopped=True)
                    if action == "reclaim":
                        record.update(state="RECLAIMED", released=True)
                else:
                    record.update(state="RUNNING" if snapshot.get("state") == "RUNNING" else "UNKNOWN", allStopped=False)
        except Exception:
            record.update(state="UNKNOWN", released=False, allStopped=False, stopKind=None, executionStatus="UNKNOWN", exitCode=None)
        with self._transaction() as conn:
            self._save(conn, record)
        return self._snapshot(record)

    def _operate(self, lease_id, owner, action):
        with self._root_guard._operation_lock():
            return self._inspect_locked(lease_id, owner, action)

    async def inspect(self, lease_id, owner):
        return await asyncio.to_thread(self._operate, lease_id, owner, "inspect")

    async def cancel(self, lease_id, owner):
        return await asyncio.to_thread(self._operate, lease_id, owner, "cancel")

    async def reclaim(self, lease_id, owner):
        return await asyncio.to_thread(self._operate, lease_id, owner, "reclaim")

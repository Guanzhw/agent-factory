"""Durable task-owned local workspace allocation, not kernel resource quotas."""
from __future__ import annotations

from contextlib import contextmanager
from inspect import isawaitable, iscoroutine
import json
import time
import asyncio
import threading
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from sqlalchemy import text

from .store import canonical, digest

if os.name == "posix":
    import fcntl
else:
    fcntl = None

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_MARKER = ".allocation.json"


def _require(value):
    if not value:
        raise ValueError("LOCAL_COMPUTE_UNCONFIRMED")


class WorkspaceBackend:
    """Workspace availability only; does not start or own a process."""
    revision = "workspace-only-v1"

    def allocate(self, record):
        return {"state": "ACCEPTED", "allStopped": True, "released": False}

    def inspect(self, record):
        return {"state": "CANCEL_CONFIRMED" if record["cancel"] != "NOT_SENT" else "ACCEPTED",
                "allStopped": True, "released": record["reclaim"] == "DONE"}

    def cancel(self, record):
        return {"state": "CANCEL_CONFIRMED", "allStopped": True, "released": False}

    def reclaim(self, record):
        return {"state": "CANCEL_CONFIRMED", "allStopped": True, "released": True}


class LocalWorkspaceProvider:
    def __init__(self, store, root: Path, backend=None):
        _require(os.name == "posix")
        self.store = store
        self.root = Path(root).absolute()
        _require(self.root != Path(self.root.anchor) and ".." not in self.root.parts)
        _require(backend is None)
        self.backend = WorkspaceBackend()
        self.max_files, self.max_bytes = 0, 0
        self._identity = None
        with self._root() as fd:
            info = os.fstat(fd)
            self._identity = [info.st_dev, info.st_ino]

    @property
    def capacity_namespace(self):
        return digest({"namespace": "local-workspace-v1", "root": str(self.root), "rootIdentity": self._identity})

    @property
    def configuration_fingerprint(self):
        return digest({"namespace": "local-workspace-v1", "root": str(self.root),
                       "rootIdentity": self._identity, "backendRevision": self.backend.revision})

    @contextmanager
    def _operation_lock(self):
        # Lock the pinned directory inode itself: no replaceable lock file can
        # split serialization. All effects occur in an off-event-loop thread.
        assert fcntl is not None
        with self._root() as root_fd:
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    _require(time.monotonic() < deadline)
                    time.sleep(.005)
            yield

    def _serialized(self, operation, *args):
        with self._operation_lock():
            return operation(*args)

    def _guarded_allocation(self, cancelled, before_effect, lease_id, owner, fingerprint, limits):
        with self._operation_lock():
            if cancelled.is_set():
                raise asyncio.CancelledError()
            if before_effect is not None:
                result = before_effect()
                if isawaitable(result):
                    if iscoroutine(result):
                        result.close()
                    raise ValueError("LOCAL_COMPUTE_UNCONFIRMED")
            if cancelled.is_set():
                raise asyncio.CancelledError()
            return self._allocate(lease_id, owner, fingerprint, limits)

    async def allocate(self, lease_id, owner, fingerprint, limits):
        return await self.allocate_guarded(lease_id, owner, fingerprint, limits, before_effect=None)

    async def allocate_guarded(self, lease_id, owner, fingerprint, limits, *, before_effect):
        _require(before_effect is None or callable(before_effect))
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(self._guarded_allocation, cancelled, before_effect,
                                           lease_id, owner, fingerprint, limits)
        except asyncio.CancelledError:
            # A waiting worker must not create an allocation after its caller
            # leaves. Already-started effects retain their durable journal.
            cancelled.set()
            raise

    async def inspect(self, lease_id, owner):
        return await asyncio.to_thread(self._serialized, self._inspect, lease_id, owner)

    async def cancel(self, lease_id, owner):
        return await asyncio.to_thread(self._serialized, self._cancel, lease_id, owner)

    async def reclaim(self, lease_id, owner):
        return await asyncio.to_thread(self._serialized, self._reclaim, lease_id, owner)

    @contextmanager
    def _root(self):
        fd = os.open(self.root.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.root.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = child
            info = os.fstat(fd)
            _require(self._identity is None or [info.st_dev, info.st_ino] == self._identity)
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _transaction(self):
        with self.store.engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": "af_local_compute"})
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _decode(value):
        return json.loads(value) if isinstance(value, str) else value

    def _load(self, conn, lease, owner):
        row = conn.execute(text("SELECT body FROM af_compute_allocations WHERE id=:id AND owner_id=:owner"),
                           {"id": lease, "owner": owner}).mappings().first()
        _require(row is not None)
        record = self._decode(row["body"])
        _require(record["rootIdentity"] == self._identity and record["backendRevision"] == self.backend.revision)
        return record

    def _save(self, conn, record, *, insert=False):
        value = "CAST(:body AS JSONB)" if conn.dialect.name == "postgresql" else ":body"
        sql = (f"INSERT INTO af_compute_allocations(id,owner_id,body) VALUES(:id,:owner,{value})" if insert else
               f"UPDATE af_compute_allocations SET body={value} WHERE id=:id AND owner_id=:owner")
        conn.execute(text(sql), {"id": record["leaseId"], "owner": record["ownerId"], "body": canonical(record)})

    @staticmethod
    def _marker(record):
        return {key: record[key] for key in ("leaseId", "ownerId", "fingerprint", "nonce", "rootIdentity", "backendRevision")}

    @contextmanager
    def _workspace(self, root_fd, record):
        fd = os.open(record["leaseId"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            info = os.fstat(fd)
            _require(record.get("workspaceIdentity") in (None, [info.st_dev, info.st_ino]))
            marker_fd = os.open(_MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                marker = os.fstat(marker_fd)
                _require(stat.S_ISREG(marker.st_mode) and marker.st_nlink == 1 and marker.st_size <= 4096)
                _require(json.loads(os.read(marker_fd, 4097)) == self._marker(record))
            finally:
                os.close(marker_fd)
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _snapshot(record):
        return {key: record[key] for key in ("leaseId", "ownerId", "fingerprint", "state", "released", "allStopped")} | {
            "providerJobId": record["leaseId"], "allocationKind": "local-workspace",
            "enforcement": {"cpu": "admission-only", "memory": "admission-only", "disk": "admission-only",
                            "seconds": "admission-only", "kernelQuotas": False},
            "capacityHeld": record["released"] is not True}

    def _allocate(self, lease_id, owner, fingerprint, limits):
        _require(all(type(value) is str and _IDENTIFIER.fullmatch(value) for value in (lease_id, owner)))
        _require(type(fingerprint) is str and re.fullmatch(r"[a-f0-9]{64}", fingerprint))
        _require(type(limits) is dict and set(limits) == {"cpu", "memoryMb", "diskMb", "seconds"}
                 and all(type(value) is int and 0 < value <= 2147483647 for value in limits.values()))
        with self._transaction() as conn:
            rows = conn.execute(text(
                "SELECT id,owner_id,body FROM af_compute_allocations "
                "WHERE id=:lease OR (owner_id=:owner AND body->>'fingerprint'=:fp)"
            ), {"lease": lease_id, "owner": owner, "fp": fingerprint}).mappings().all()
            for row in rows:
                prior = self._decode(row["body"])
                if row["id"] == lease_id:
                    _require(row["owner_id"] == owner and prior["fingerprint"] == fingerprint and prior["limits"] == limits)
                    return self._snapshot(self._load(conn, lease_id, owner))
                _require(not (row["owner_id"] == owner and prior["fingerprint"] == fingerprint and not prior["released"]))
            record = {"leaseId": lease_id, "ownerId": owner, "fingerprint": fingerprint, "limits": dict(limits),
                "nonce": str(uuid4()), "rootIdentity": self._identity, "backendRevision": self.backend.revision,
                "state": "UNKNOWN", "released": False, "allStopped": False,
                "allocation": "UNKNOWN", "cancel": "NOT_SENT", "reclaim": "NOT_SENT"}
            self._save(conn, record, insert=True)
        # Durable unknown is committed before either filesystem or backend effect.
        try:
            with self._root() as root_fd:
                os.mkdir(lease_id, mode=0o700, dir_fd=root_fd)
                fd = os.open(lease_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                try:
                    info = os.fstat(fd); record["workspaceIdentity"] = [info.st_dev, info.st_ino]
                    marker_fd = os.open(_MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    try:
                        raw = canonical(self._marker(record)).encode()
                        _require(os.write(marker_fd, raw) == len(raw)); os.fsync(marker_fd)
                    finally:
                        os.close(marker_fd)
                    os.fsync(fd); os.fsync(root_fd)
                finally:
                    os.close(fd)
            result = self.backend.allocate(dict(record))
            _require(type(result) is dict and result.get("state") in {"ACCEPTED", "RUNNING"})
            with self._transaction() as conn:
                current = self._load(conn, lease_id, owner)
                _require(current["cancel"] == "NOT_SENT" and current["reclaim"] == "NOT_SENT")
                record.update(state=result["state"], allStopped=result.get("allStopped") is True, allocation="DONE")
                self._save(conn, record)
        except Exception:
            pass  # Unknown effects are inspected, never replayed or implicitly released.
        with self._transaction() as conn:
            return self._snapshot(self._load(conn, lease_id, owner))

    def _inspect(self, lease_id, owner):
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
            if record["released"]:
                return self._snapshot(record)
            try:
                with self._root() as root_fd:
                    try:
                        with self._workspace(root_fd, record) as fd:
                            info = os.fstat(fd); record["workspaceIdentity"] = [info.st_dev, info.st_ino]
                    except FileNotFoundError:
                        # A missing marker inside an extant directory is not
                        # positive workspace release evidence.
                        try:
                            os.stat(lease_id, dir_fd=root_fd, follow_symlinks=False)
                        except FileNotFoundError:
                            pass
                        else:
                            raise ValueError("LOCAL_COMPUTE_UNCONFIRMED")
                        _require(record["reclaim"] == "DONE")
                        record.update(state="RECLAIMED", released=True, allStopped=True)
                        self._save(conn, record)
                        return self._snapshot(record)
                result = self.backend.inspect(dict(record))
                _require(type(result) is dict and result.get("state") in {"ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "CANCEL_CONFIRMED"})
                stopped = result.get("allStopped") is True
                state = result["state"]
                if state in {"COMPLETED", "FAILED", "CANCEL_CONFIRMED"}:
                    _require(stopped)
                record.update(state=state, allStopped=stopped)
            except Exception:
                record.update(state="UNKNOWN", allStopped=False)
            self._save(conn, record)
            return self._snapshot(record)

    def _cancel(self, lease_id, owner):
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
            if record["released"] or record["cancel"] != "NOT_SENT":
                return self._snapshot(record)
            record.update(cancel="UNKNOWN", state="UNKNOWN")
            self._save(conn, record)
        try:
            with self._root() as root_fd, self._workspace(root_fd, record):
                result = self.backend.cancel(dict(record))
                _require(type(result) is dict and result.get("allStopped") is True and result.get("state") == "CANCEL_CONFIRMED")
            with self._transaction() as conn:
                record = self._load(conn, lease_id, owner)
                record.update(cancel="DONE", state="CANCEL_CONFIRMED", allStopped=True)
                self._save(conn, record)
        except Exception:
            pass
        with self._transaction() as conn:
            return self._snapshot(self._load(conn, lease_id, owner))

    def _reclaim(self, lease_id, owner):
        observed = self._inspect(lease_id, owner)
        _require(observed["allStopped"] and observed["state"] in {"COMPLETED", "FAILED", "CANCEL_CONFIRMED", "RECLAIMED"})
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
            if record["released"] or record["reclaim"] != "NOT_SENT":
                return self._snapshot(record)
            record.update(reclaim="UNKNOWN", state="UNKNOWN")
            self._save(conn, record)
        try:
            with self._root() as root_fd, self._workspace(root_fd, record) as fd:
                names = os.listdir(fd)
                _require(len(names) <= self.max_files + 1 and _MARKER in names)
                entries = []
                for name in names:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
                    entries.append((name, info))
                _require(sum(info.st_size for name, info in entries if name != _MARKER) <= self.max_bytes)
                result = self.backend.reclaim(dict(record))
                _require(type(result) is dict and result.get("released") is True and result.get("allStopped") is True)
                # Persist backend release proof before deletion; later inspection
                # may confirm absence after an interrupted filesystem release.
                with self._transaction() as conn:
                    record = self._load(conn, lease_id, owner)
                    record["reclaim"] = "DONE"; self._save(conn, record)
                for name, original in entries:
                    current = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    _require((current.st_dev, current.st_ino, current.st_nlink, current.st_mode) ==
                             (original.st_dev, original.st_ino, original.st_nlink, original.st_mode))
                    os.unlink(name, dir_fd=fd)
                os.fsync(fd)
                current = os.stat(lease_id, dir_fd=root_fd, follow_symlinks=False)
                identity = os.fstat(fd)
                _require((current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino))
                os.rmdir(lease_id, dir_fd=root_fd); os.fsync(root_fd)
        except Exception:
            return self._snapshot({**record, "state": "UNKNOWN"})
        return self._inspect(lease_id, owner)

"""Single-host disk admission and explicitly owned, recoverable retention.

The filesystem is not a quota-enforcing sandbox. Reservations are conservative
admission holds; free-space observation also sees unmanaged/Docker growth on the
same filesystem. No host-wide walk, Docker prune or legacy-directory adoption.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import asyncio
import hashlib
import os
from pathlib import Path
import stat
from uuid import uuid4

from fastapi import HTTPException

from .store import canonical, digest, now


class StorageGovernance:
    def __init__(self, store, auth):
        self.store, self.auth, self.settings = store, auth, store.settings
        self.root = Path(self.settings.workspace).resolve() / "managed-storage"
        if self.root.is_symlink():
            raise ValueError("Managed storage cannot be a symlink")
        self.root.mkdir(exist_ok=True)
        self.objects = self.root / "objects"
        self.quarantine = self.root / "quarantine"
        for path in (self.objects, self.quarantine):
            if path.is_symlink():
                raise ValueError("Managed storage namespace cannot be a symlink")
            path.mkdir(exist_ok=True)
        marker = self.root / "root-id"
        if marker.is_symlink():
            raise ValueError("Storage marker cannot be a symlink")
        try:
            with marker.open("x") as output:
                output.write(str(uuid4()))
        except FileExistsError:
            pass
        self.root_id = marker.read_text().strip()
        if len(self.root_id) != 36:
            raise ValueError("Invalid managed storage identity")
        self.identities = {str(path): (path.stat().st_dev, path.stat().st_ino) for path in (self.root, self.objects, self.quarantine)}
        # Upgrades must account for already active/UNKNOWN work. This adopts
        # only admission holds, never legacy directories or cleanup authority.
        with self.store.transaction():
            self.store.sql("SELECT pg_advisory_xact_lock(hashtext('af_admission'))")
            self.store.sql("""INSERT INTO af_disk_holds(task_id,owner_id,bytes,state,created_at)
                SELECT id,owner_id,:bytes,'HELD',:at FROM af_tasks WHERE NOT terminal
                ON CONFLICT(task_id) DO NOTHING""", bytes=self.settings.storage_task_reserve_bytes, at=now())

    def _namespace(self):
        for name, identity in self.identities.items():
            info = Path(name).lstat()
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                raise HTTPException(409, "STORAGE_BINDING: managed namespace was replaced")

    def _leases(self, task_id):
        descendants = self.store.delegation._descendants(task_id) if self.store.delegation else []
        identifiers = [task_id, *[link["child_id"] for link in descendants if link.get("child_id")]]
        return self.store.sql("SELECT id FROM af_leases WHERE body->>'localTaskId'=ANY(CAST(:ids AS TEXT[])) AND state<>'RECLAIMED' LIMIT 1", ids=identifiers)

    def filesystems(self):
        values = {}
        for path in (self.root, *self.settings.storage_monitor_paths):
            path = Path(path)
            info = path.stat()
            # disk_usage is portable; filesystem identity prevents counting
            # one underlying mount twice when workspace and Docker share it.
            import shutil
            usage = shutil.disk_usage(path)
            values[str(info.st_dev)] = {"filesystem": str(info.st_dev), "totalBytes": usage.total,
                "freeBytes": usage.free, "usedBytes": usage.used}
        return list(values.values())

    def reserve(self, task_id, owner):
        """Called inside Store's existing global admission transaction."""
        amount = self.settings.storage_task_reserve_bytes
        held = self.store.sql("SELECT COALESCE(SUM(bytes),0) AS n FROM af_disk_holds WHERE state='HELD'")[0]["n"]
        try:
            mounts = self.filesystems()
        except OSError as error:
            raise HTTPException(503, "STORAGE_UNOBSERVABLE: disk admission is unavailable") from error
        if any(mount["freeBytes"] - held - amount < self.settings.storage_low_water_bytes for mount in mounts):
            raise HTTPException(507, "STORAGE_LOW_WATER: preserve free space and existing UNKNOWN holds")
        self.store.sql("INSERT INTO af_disk_holds(task_id,owner_id,bytes,state,created_at) VALUES(:task,:owner,:bytes,'HELD',:at)",
                       task=task_id, owner=owner, bytes=amount, at=now())

    def release(self, task_id):
        """Caller supplies an already positively stopped native group boundary."""
        if self._leases(task_id):
            return
        changed = self.store.sql("UPDATE af_disk_holds SET state='RELEASED' WHERE task_id=:task AND state='HELD' RETURNING bytes", task=task_id)
        if changed:
            self.store.event(task_id, "disk_reservation_released", "Positive stop releases unused admission reservation; files still consume physical space", {"bytes": changed[0]["bytes"]})

    @contextmanager
    def _lock(self, identifier):
        """Nonblocking cross-process fence, shared by producers and retention."""
        from sqlalchemy import text
        from sqlalchemy.exc import TimeoutError as PoolTimeout
        try:
            connection = self.store.retention_lock_engine().connect()
        except PoolTimeout:
            raise HTTPException(409, "RETENTION_BUSY: another original fence is active") from None
        with connection:
            key = "af_retention:" + identifier
            if not connection.execute(text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key}).scalar():
                raise HTTPException(409, "RETENTION_BUSY: reconcile the original plan")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key})
                connection.commit()

    def directory(self, task_id, key, *, evidence=False):
        """Internal producer API; callers cannot supply a filesystem path."""
        identifier = digest({"task": task_id, "key": key})
        with self._lock(identifier):
            return self._directory(task_id, identifier, evidence=evidence)

    def _directory(self, task_id, identifier, *, evidence):
        self._namespace()
        task = self.store.task(task_id)
        rows = self.store.sql("SELECT * FROM af_storage_objects WHERE id=:id", id=identifier)
        if rows:
            row = rows[0]
            if row["root_id"] != self.root_id or row["state"] != "AVAILABLE" or row["evidence"] != evidence:
                raise HTTPException(409, "STORAGE_BINDING: original storage object is unavailable")
        else:
            if task["terminal"] or task["cancel_requested"]:
                raise HTTPException(409, "Stopped tasks cannot create storage")
            self.store.sql("""INSERT INTO af_storage_objects(id,owner_id,task_id,root_id,evidence,state,created_at)
                VALUES(:id,:owner,:task,:root,:evidence,'AVAILABLE',:at) ON CONFLICT DO NOTHING""",
                id=identifier, owner=task["owner_id"], task=task["id"], root=self.root_id, evidence=evidence, at=now())
        path = self.objects / identifier
        if path.is_symlink():
            raise HTTPException(409, "STORAGE_BINDING: links cannot be adopted")
        if path.exists() and (not rows or not rows[0]["identity"]):
            raise HTTPException(409, "STORAGE_UNCONFIRMED: existing directory cannot be adopted")
        path.mkdir(exist_ok=True)
        info = path.lstat()
        identity = {"device": info.st_dev, "directoryInode": info.st_ino}
        if rows and rows[0]["identity"] and rows[0]["identity"] != identity:
            raise HTTPException(409, "STORAGE_BINDING: directory identity changed")
        self.store.sql("UPDATE af_storage_objects SET identity=CAST(:identity AS JSONB) WHERE id=:id", id=identifier, identity=canonical(identity))
        return path

    def _object(self, owner, identifier):
        rows = self.store.sql("SELECT * FROM af_storage_objects WHERE id=:id AND owner_id=:owner", id=identifier, owner=owner)
        if not rows:
            raise HTTPException(404, "Storage object not found")
        return rows[0]

    def scan(self, path, *, hashes=False, identity=None):
        """Bounded Linux descriptor walk: never follow a swapped path/link."""
        self._namespace()
        if os.name != "posix":
            raise HTTPException(501, "RETENTION_UNVERIFIED: descriptor-safe inventory is Linux-only")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
        entries, logical, allocated = [], 0, 0
        anchor = Path(self.settings.workspace).resolve()
        parts = path.relative_to(anchor).parts
        if any(part in {".", ".."} for part in parts):
            raise HTTPException(409, "STORAGE_UNSAFE: invalid scoped directory")
        root_fd = os.open(anchor, directory_flags)
        try:
            for part in parts:
                child = os.open(part, directory_flags, dir_fd=root_fd)
                os.close(root_fd)
                root_fd = child
        except BaseException:
            os.close(root_fd)
            raise
        try:
            root_stat = os.fstat(root_fd)
            if identity is not None and {"device": root_stat.st_dev, "directoryInode": root_stat.st_ino} != identity:
                raise HTTPException(409, "STORAGE_BINDING: original directory identity differs")
            def walk(fd, prefix):
                nonlocal logical, allocated
                if prefix.count("/") > 64:
                    raise HTTPException(409, "STORAGE_SCAN_LIMIT: directory depth exceeded")
                names = []
                with os.scandir(fd) as listing:
                    for item in listing:
                        if len(names) + len(entries) >= self.settings.storage_scan_entries:
                            raise HTTPException(409, "STORAGE_SCAN_LIMIT: inventory is incomplete")
                        names.append(item.name)
                names.sort()
                for name in names:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if info.st_dev != root_stat.st_dev or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                        raise HTTPException(409, "STORAGE_UNSAFE: links, devices and mount crossings are protected")
                    if len(entries) >= self.settings.storage_scan_entries:
                        raise HTTPException(409, "STORAGE_SCAN_LIMIT: inventory is incomplete")
                    relative = prefix + name
                    is_directory = stat.S_ISDIR(info.st_mode)
                    entry = {"path": relative, "kind": "directory" if is_directory else "file", "inode": info.st_ino}
                    entries.append(entry)
                    opened = os.open(name, directory_flags if is_directory else flags | getattr(os, "O_NONBLOCK", 0), dir_fd=fd)
                    try:
                        actual = os.fstat(opened)
                        if (actual.st_dev, actual.st_ino, actual.st_mode) != (info.st_dev, info.st_ino, info.st_mode):
                            raise HTTPException(409, "STORAGE_CHANGED: inventory changed during observation")
                        if is_directory:
                            walk(opened, relative + "/")
                        else:
                            if info.st_nlink != 1:
                                raise HTTPException(409, "STORAGE_UNSAFE: shared hardlinks are protected")
                            logical += info.st_size
                            allocated += getattr(info, "st_blocks", (info.st_size + 511) // 512) * 512
                            entry.update(bytes=info.st_size, inode=info.st_ino, links=info.st_nlink)
                            if hashes:
                                if logical > self.settings.storage_hash_bytes:
                                    raise HTTPException(409, "STORAGE_SCAN_LIMIT: hash budget exceeded")
                                checksum = hashlib.sha256()
                                with os.fdopen(os.dup(opened), "rb") as content:
                                    remaining = info.st_size
                                    while remaining:
                                        chunk = content.read(min(65536, remaining))
                                        if not chunk:
                                            raise HTTPException(409, "STORAGE_CHANGED: file shrank while hashing")
                                        checksum.update(chunk)
                                        remaining -= len(chunk)
                                    if content.read(1):
                                        raise HTTPException(409, "STORAGE_CHANGED: file grew while hashing")
                                entry["sha256"] = checksum.hexdigest()
                                after = os.fstat(opened)
                                if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                                    raise HTTPException(409, "STORAGE_CHANGED: file changed while hashing")
                    finally:
                        os.close(opened)
            walk(root_fd, "")
            return {"entries": sorted(entries, key=lambda entry: entry["path"]), "logicalBytes": logical,
                    "allocatedBytes": allocated, "directoryInode": root_stat.st_ino, "device": root_stat.st_dev}
        finally:
            os.close(root_fd)

    async def summary(self, owner):
        self.auth.require(owner, "read")
        pending = self.store.sql("SELECT task_id FROM af_disk_holds WHERE owner_id=:owner AND state='HELD' ORDER BY created_at LIMIT 20", owner=owner)
        reconciliation_errors = []
        for hold in pending:
            try:
                await self._reconcile_hold(owner, hold["task_id"])
            except (OSError, HTTPException):
                reconciliation_errors.append(hold["task_id"])
        return await asyncio.to_thread(self._summary, owner, reconciliation_errors)

    async def _reconcile_hold(self, owner, task_id):
        task = self.store.task(task_id, owner)
        if self.store.remote_execution and self.store.remote_execution.placed(task):
            await self.store.remote_execution.detail(task)  # Validated receiver receipt updates holds.
        elif self.store.delegation:
            group = await self.store.delegation.inspect_group(owner, task["id"])
            if group["allStopped"]:
                self.release(task["id"])

    def _summary(self, owner, reconciliation_errors):
        rows = self.store.sql("SELECT * FROM af_storage_objects WHERE owner_id=:owner ORDER BY created_at DESC LIMIT 100", owner=owner)
        objects = []
        for row in rows:
            value = {key: row[key] for key in ("id", "task_id", "evidence", "state", "created_at")}
            value["availableOnThisHost"] = row["root_id"] == self.root_id
            if value["availableOnThisHost"] and row["state"] in {"AVAILABLE", "QUARANTINED"}:
                try:
                    result = self.scan((self.objects if row["state"] == "AVAILABLE" else self.quarantine) / row["id"], identity=row["identity"])
                    value.update(logicalBytes=result["logicalBytes"], allocatedBytes=result["allocatedBytes"], complete=True)
                except (OSError, HTTPException):
                    value["complete"] = False
            objects.append(value)
        artifact = self.store.sql("""SELECT COALESCE(SUM(octet_length(a.content)),0) AS bytes,COUNT(*) AS count
            FROM af_artifacts a JOIN af_tasks t ON t.id=a.task_id WHERE t.owner_id=:owner""", owner=owner)[0]
        holds = self.store.sql("SELECT task_id,bytes,state FROM af_disk_holds WHERE owner_id=:owner ORDER BY created_at DESC LIMIT 100", owner=owner)
        total = self.store.sql("SELECT COALESCE(SUM(bytes),0) AS n FROM af_disk_holds WHERE state='HELD'")[0]["n"]
        plans = self.store.sql("SELECT * FROM af_retention_plans WHERE owner_id=:owner ORDER BY body->>'createdAt' DESC LIMIT 100", owner=owner)
        protected = []
        containers = []
        # Existing ORX evidence is measured, never adopted for cleanup. The
        # path is derived from authenticated owner and actual persisted task.
        experiments = self.store.sql("SELECT task_id FROM af_orx_task_experiments WHERE owner_id=:owner ORDER BY task_id LIMIT 10", owner=owner)
        for experiment in experiments:
            task_id = experiment["task_id"]
            path = Path(self.settings.workspace).resolve() / "orx-tasks" / hashlib.sha256(owner.encode()).hexdigest()[:24] / task_id
            item = {"taskId": task_id, "kind": "orx-evidence", "retentionProtected": True, "complete": False}
            try:
                observed = self.scan(path)
                item.update(logicalBytes=observed["logicalBytes"], allocatedBytes=observed["allocatedBytes"], complete=True)
            except (OSError, HTTPException):
                pass
            protected.append(item)
            if self.settings.runtime_tool_contract in {"local-orx-v1", "orx-evidence-v2"}:
                from .storage_runtime import observe_container
                containers.append(observe_container(Path(self.settings.workspace), owner, task_id))
        return {"ownerId": owner, "unconfirmedHoldTaskIds": reconciliation_errors, "plans": [self.public(plan) for plan in plans], "protectedDirectories": protected, "protectedContainers": containers,
            "observationLimits": {"objects": 100, "plans": 100, "orxDirectories": 10, "holdReconciliations": 20},
            "retentionSupported": os.name == "posix", "filesystems": self.filesystems(), "reservedBytes": total, "lowWaterBytes": self.settings.storage_low_water_bytes,
            "taskReserveBytes": self.settings.storage_task_reserve_bytes, "ownerHolds": holds, "objects": objects,
            "databaseArtifacts": dict(artifact), "purgeEnabled": self.settings.storage_allow_purge,
            "quarantineGraceSeconds": self.settings.storage_retention_grace_seconds,
            "scope": "Managed task scratch and database artifact bytes; filesystem usage also includes unattributed host/Docker data. No host-wide cleanup."}

    async def _eligible(self, owner, row):
        task = self.store.task(row["task_id"], owner)
        if row["root_id"] != self.root_id or row["evidence"] or not task["terminal"] or task["admission"] == "unknown":
            raise HTTPException(409, "RETENTION_PROTECTED: evidence, active, unknown or another workspace")
        group = await self.store.delegation.inspect_group(owner, task["id"])
        if not group["allStopped"] or self._leases(task["id"]):
            raise HTTPException(409, "RETENTION_PROTECTED: positive group stop is required")
        if self.store.sql("SELECT 1 FROM af_control_commands WHERE root_task_id=:task AND state IN ('PREPARED','DISPATCHING') AND body->'evidence' IS NULL LIMIT 1", task=task["id"]):
            raise HTTPException(409, "RETENTION_PROTECTED: unresolved control evidence")
        return task

    async def plan(self, owner, identifier, request_id):
        self.auth.require(owner, "run")
        self._object(owner, identifier)
        old = self.store.sql("SELECT * FROM af_retention_plans WHERE owner_id=:owner AND request_id=:request", owner=owner, request=request_id)
        if old:
            if old[0]["object_id"] != identifier:
                raise HTTPException(409, "RETENTION_CONFLICT: original object differs")
            return self.public(old[0])
        with self._lock(identifier):
            return await self._create_plan(owner, identifier, request_id)

    async def _create_plan(self, owner, identifier, request_id):
        self.auth.require(owner, "run")
        row = self._object(owner, identifier)
        if row["state"] != "AVAILABLE":
            raise HTTPException(409, "Retention requires an available object")
        await self._eligible(owner, row)
        manifest = self.scan(self.objects / identifier, hashes=True, identity=row["identity"])
        fingerprint = digest({"object": identifier, "root": self.root_id, "manifest": manifest})
        old = self.store.sql("SELECT * FROM af_retention_plans WHERE owner_id=:owner AND request_id=:request", owner=owner, request=request_id)
        if old:
            if old[0]["fingerprint"] != fingerprint:
                raise HTTPException(409, "RETENTION_CONFLICT: original plan differs")
            return self.public(old[0])
        plan_id = str(uuid4())
        body = {"manifest": manifest, "createdAt": now(), "rootId": self.root_id}
        with self.store.transaction():
            inserted = self.store.sql("""INSERT INTO af_retention_plans(id,owner_id,object_id,request_id,fingerprint,state,body)
                VALUES(:id,:owner,:object,:request,:fp,'PLANNED',CAST(:body AS JSONB)) ON CONFLICT(owner_id,request_id) DO NOTHING RETURNING id""", id=plan_id, owner=owner,
                object=identifier, request=request_id, fp=fingerprint, body=canonical(body))
            if not inserted:
                winner = self.store.sql("SELECT * FROM af_retention_plans WHERE owner_id=:owner AND request_id=:request", owner=owner, request=request_id)[0]
                if winner["object_id"] != identifier:
                    raise HTTPException(409, "RETENTION_CONFLICT: original object differs")
                return self.public(winner)
            self.store.event(row["task_id"], "retention_planned", "Owner-scoped dry-run retained; no files moved or deleted", {"planId": plan_id, "fingerprint": fingerprint, "bytes": manifest["logicalBytes"]})
            return self.public(self._plan(owner, plan_id))

    def _plan(self, owner, identifier):
        rows = self.store.sql("SELECT * FROM af_retention_plans WHERE id=:id AND owner_id=:owner", id=identifier, owner=owner)
        if not rows:
            raise HTTPException(404, "Retention plan not found")
        return rows[0]

    @staticmethod
    def public(row):
        return {"id": row["id"], "ownerId": row["owner_id"], "objectId": row["object_id"], "state": row["state"], "fingerprint": row["fingerprint"],
                "createdAt": row["body"]["createdAt"], "logicalBytes": row["body"]["manifest"]["logicalBytes"],
                "allocatedBytes": row["body"]["manifest"]["allocatedBytes"], "quarantinedAt": row["body"].get("quarantinedAt"),
                "reclaimedLogicalBytes": row["body"].get("reclaimedLogicalBytes", 0)}

    def _state(self, plan, state, object_state, patch=None):
        with self.store.transaction():
            self.store.sql("UPDATE af_retention_plans SET state=:state,body=body || CAST(:patch AS JSONB) WHERE id=:id",
                           id=plan["id"], state=state, patch=canonical(patch or {}))
            self.store.sql("UPDATE af_storage_objects SET state=:state WHERE id=:id", id=plan["object_id"], state=object_state)
            row = self._object(plan["owner_id"], plan["object_id"])
            self.store.event(row["task_id"], "retention_" + state.lower(), "Scoped retention transition; audit and evidence remain persisted", {"planId": plan["id"], "fingerprint": plan["fingerprint"]})

    def _matches(self, path, manifest, *, remaining=False):
        actual = self.scan(path, hashes=True, identity={key: manifest[key] for key in ("device", "directoryInode")})
        if (actual["device"], actual["directoryInode"]) != (manifest["device"], manifest["directoryInode"]):
            raise HTTPException(409, "RETENTION_CHANGED: directory identity differs")
        if remaining:
            original = {entry["path"]: entry for entry in manifest["entries"]}
            valid = all(original.get(entry["path"]) == entry for entry in actual["entries"])
        else:
            valid = actual == manifest
        if not valid:
            raise HTTPException(409, "RETENTION_CHANGED: original content differs")
        return actual

    async def inspect(self, owner, identifier):
        self.auth.require(owner, "read")
        plan = self._plan(owner, identifier)
        with self._lock(plan["object_id"]):
            return self._inspect(owner, identifier)

    def _inspect(self, owner, identifier):
        plan = self._plan(owner, identifier)
        if plan["body"]["rootId"] != self.root_id:
            return {**self.public(plan), "recovery": "original_workspace_required"}
        source, target = self.objects / plan["object_id"], self.quarantine / plan["object_id"]
        # Reads can reconcile an interrupted rename, never move/delete files.
        if plan["state"] in {"MOVING", "RESTORING"}:
            locations = (target, source) if plan["state"] == "MOVING" else (source, target)
            try:
                if locations[0].exists() and not locations[1].exists():
                    self._matches(locations[0], plan["body"]["manifest"])
                    state = "QUARANTINED" if plan["state"] == "MOVING" else "RESTORED"
                    self._state(plan, state, "QUARANTINED" if state == "QUARANTINED" else "AVAILABLE",
                                {"quarantinedAt": now()} if state == "QUARANTINED" else {})
            except (OSError, HTTPException):
                return {**self.public(plan), "recovery": "identity_or_content_unconfirmed"}
        return self.public(self._plan(owner, identifier))

    async def transition(self, owner, identifier, action):
        self.auth.require(owner, "run")
        plan = self._plan(owner, identifier)
        row = self._object(owner, plan["object_id"])
        await self._eligible(owner, row)
        with self._lock(row["id"]):
            self.auth.require(owner, "run")
            row = self._object(owner, plan["object_id"])
            await self._eligible(owner, row)
            self._inspect(owner, identifier)
            plan = self._plan(owner, identifier)
            source, target = self.objects / row["id"], self.quarantine / row["id"]
            if action == "quarantine":
                if plan["state"] == "QUARANTINED":
                    return self.public(plan)
                if plan["state"] not in {"PLANNED", "MOVING"} or target.exists() or target.is_symlink():
                    raise HTTPException(409, "RETENTION_STATE: quarantine boundary is not available")
                self._matches(source, plan["body"]["manifest"])
                self._state(plan, "MOVING", "MOVING")
                self._rename_object(self.objects, self.quarantine, row["id"])
                self._state(plan, "QUARANTINED", "QUARANTINED", {"quarantinedAt": now()})
            elif action == "restore":
                if plan["state"] == "RESTORED":
                    return self.public(plan)
                if plan["state"] not in {"QUARANTINED", "RESTORING"} or source.exists() or source.is_symlink():
                    raise HTTPException(409, "RETENTION_STATE: restore requires an empty original location")
                self._matches(target, plan["body"]["manifest"])
                self._state(plan, "RESTORING", "RESTORING")
                self._rename_object(self.quarantine, self.objects, row["id"])
                self._state(plan, "RESTORED", "AVAILABLE")
            elif action == "purge":
                if plan["state"] == "PURGED":
                    return self.public(plan)
                if not self.settings.storage_allow_purge:
                    raise HTTPException(403, "RETENTION_POLICY: permanent reclamation requires operator policy")
                at = plan["body"].get("quarantinedAt")
                if plan["state"] not in {"QUARANTINED", "PURGING"} or not at:
                    raise HTTPException(409, "RETENTION_STATE: only quarantined rebuildable objects may be reclaimed")
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds()
                if age < self.settings.storage_retention_grace_seconds:
                    raise HTTPException(409, "RETENTION_GRACE: recovery window has not elapsed")
                if target.exists():
                    actual = self._matches(target, plan["body"]["manifest"], remaining=plan["state"] == "PURGING")
                    self._state(plan, "PURGING", "PURGING")
                    # Only an immutable, fully observed manifest is removed.
                    # Never recurse through arbitrary paths or follow links.
                    self._purge_manifest(target, actual)
                elif plan["state"] != "PURGING":
                    raise HTTPException(409, "RETENTION_MISSING: absence alone is not a purge receipt")
                self._state(plan, "PURGED", "PURGED", {"reclaimedLogicalBytes": plan["body"]["manifest"]["logicalBytes"]})
            else:
                raise HTTPException(422, "Unknown retention transition")
            return self.public(self._plan(owner, identifier))

    def _purge_manifest(self, target, manifest):
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        root = os.open(target, flags)
        original = {entry["path"]: entry for entry in manifest["entries"]}
        try:
            if os.fstat(root).st_ino != manifest["directoryInode"]:
                raise HTTPException(409, "RETENTION_CHANGED: quarantine directory changed")
            for entry in sorted(manifest["entries"], key=lambda item: item["path"].count("/"), reverse=True):
                parts = entry["path"].split("/")
                parent = os.dup(root)
                try:
                    for index, part in enumerate(parts[:-1]):
                        child = os.open(part, flags, dir_fd=parent)
                        os.close(parent)
                        parent = child
                        if os.fstat(parent).st_ino != original["/".join(parts[:index + 1])]["inode"]:
                            raise HTTPException(409, "RETENTION_CHANGED: nested directory changed")
                    info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    expected_kind = stat.S_ISREG(info.st_mode) if entry["kind"] == "file" else stat.S_ISDIR(info.st_mode)
                    if not expected_kind or info.st_ino != entry["inode"] or entry["kind"] == "file" and info.st_nlink != 1:
                        raise HTTPException(409, "RETENTION_CHANGED: manifest entry changed")
                    if entry["kind"] == "file":
                        os.unlink(parts[-1], dir_fd=parent)
                    else:
                        os.rmdir(parts[-1], dir_fd=parent)
                finally:
                    os.close(parent)
        finally:
            os.close(root)
        # rmdir cannot follow a replacement link or remove a nonempty tree.
        target.rmdir()

    def _rename_object(self, source, target, identifier):
        self._namespace()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        source_fd = os.open(source, flags)
        try:
            target_fd = os.open(target, flags)
            try:
                for fd, path in ((source_fd, source), (target_fd, target)):
                    info = os.fstat(fd)
                    if (info.st_dev, info.st_ino) != self.identities[str(path)]:
                        raise HTTPException(409, "STORAGE_BINDING: rename namespace changed")
                try:
                    os.stat(identifier, dir_fd=target_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise HTTPException(409, "RETENTION_CONFLICT: destination already exists")
                os.rename(identifier, identifier, src_dir_fd=source_fd, dst_dir_fd=target_fd)
                os.fsync(source_fd)
                os.fsync(target_fd)
            finally:
                os.close(target_fd)
        finally:
            os.close(source_fd)

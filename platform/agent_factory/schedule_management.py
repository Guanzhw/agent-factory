"""Recoverable editor commands over the existing native schedule adapter.

The command journal fences control-plane writes, never retries native execution.
Only an exact native row from a precommitted intent can repair a lost receipt.
"""
from datetime import datetime, timezone
import json
import re
from uuid import NAMESPACE_URL, uuid5

from agno.db.schemas.scheduler import Schedule
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import text

from .auth import EXECUTOR_ID
from .schedule_contract import preview_schedule
from .scheduling import ENDPOINT, MANAGED_BY
from .store import canonical, digest, now


def _require(value, status=409, code="SCHEDULE_EDITOR_CONFLICT"):
    if not value:
        raise HTTPException(status, code)


class ScheduleManagement:
    def __init__(self, service):
        self.service, self.store, self.auth = service, service.store, service.auth
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_schedule_editor_commands (
            owner_id TEXT NOT NULL, request_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, intent TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY(owner_id,request_id))""")

    def metadata(self, owner):
        self.auth.require(owner, "run")
        try:
            self.service._require_write(owner)
            manage = True
        except HTTPException:
            manage = False
        return {"schema": 1, "ownerId": owner, "canManage": manage,
            "policy": {"singlePoller": True, "overlap": "allow-with-current-budget-admission",
                "missed": "coalesce", "pauseCancelsRunning": False, "timeSemantics": "cron-iana-timezone",
                "maxUserTasks": self.service.settings.max_user_tasks,
                "maxTotalTasks": self.service.settings.max_total_tasks}}

    def _editor(self, identifier):
        rows = self.store.sql("SELECT * FROM af_schedule_editor_state WHERE schedule_id=:id", id=identifier)
        return rows[0] if rows else {"revision": 0, "request_id": None, "last_command_id": None}

    def _version(self, schedule):
        return digest({"definition": self.service._definition(schedule), "enabled": schedule.enabled,
                       "revision": self._editor(schedule.id)["revision"]})

    def _project(self, owner, identifier):
        schedule, binding = self.service._bound(identifier, owner)
        plan = self.store.plan(binding["plan_id"], owner)
        _require(digest(plan) == binding["plan_hash"])
        editor = self._editor(identifier)
        return {"id": identifier, "ownerId": owner, "requestId": editor["request_id"],
            "lastCommandId": editor["last_command_id"], "name": schedule.name,
            "cron": schedule.cron_expr, "timezone": schedule.timezone, "enabled": schedule.enabled,
            "planId": plan["id"], "planFingerprint": plan["fingerprint"], "planDigest": binding["plan_hash"],
            "definitionFingerprint": self._version(schedule),
            "nextRunAt": datetime.fromtimestamp(schedule.next_run_at, timezone.utc).isoformat() if schedule.next_run_at else None,
            "allowedActions": (["edit", "disable" if schedule.enabled else "enable"]
                               if self.metadata(owner)["canManage"] else [])}

    def _pending(self, owner, identifier):
        return self.store.sql("""SELECT * FROM af_schedule_editor_commands
            WHERE owner_id=:owner AND schedule_id=:id AND status='pending'""", owner=owner, id=identifier)

    def _recover(self, owner, command):
        """Reconcile metadata only. Never create/modify/enable a native schedule."""
        # A caller may have read pending before waiting for this schedule lock.
        # Re-read under the lock so an old receipt cannot roll a later revision back.
        rows = self.store.sql("SELECT * FROM af_schedule_editor_commands WHERE owner_id=:owner AND request_id=:request",
                              owner=owner, request=command["request_id"])
        _require(bool(rows), 404)
        command = rows[0]
        if command["status"] == "complete":
            return
        intent = json.loads(command["intent"])
        row = self.service.db.get_schedule(command["schedule_id"], user_id=owner)
        _require(row is not None, 409, "SCHEDULE_EDITOR_UNKNOWN")
        native = Schedule.from_dict(row)
        target = Schedule.from_dict(intent["target"])
        _require(native.user_id == owner and native.enabled == target.enabled
                 and self.service._definition(native) == self.service._definition(target),
                 409, "SCHEDULE_EDITOR_UNKNOWN")
        # Exact command custody, original plan and owner were pinned before the native write.
        with self.store.engine.begin() as conn:
            conn.execute(text("""INSERT INTO af_schedule_bindings
                VALUES(:id,:owner,:plan,:hash,:definition,:at)
                ON CONFLICT(schedule_id) DO UPDATE SET definition_hash=:definition"""),
                {"id": native.id, "owner": owner, "plan": intent["planId"], "hash": intent["planHash"],
                 "definition": self.service._definition(native), "at": intent["createdAt"]})
            conn.execute(text("""INSERT INTO af_schedule_editor_state VALUES(:id,:revision,:request,:last)
                ON CONFLICT(schedule_id) DO UPDATE SET revision=:revision,last_command_id=:last"""),
                {"id": native.id, "revision": intent["revision"],
                 "request": command["request_id"] if intent["kind"] == "create" else None,
                 "last": command["request_id"]})
            conn.execute(text("""UPDATE af_schedule_editor_commands SET status='complete'
                WHERE owner_id=:owner AND request_id=:request AND status='pending'"""),
                {"owner": owner, "request": command["request_id"]})

    def _read_recover(self, owner, identifier):
        # Metadata repair is permitted on read; there is never native mutation/replay.
        for command in self._pending(owner, identifier):
            with self.service._lock(identifier):
                self._recover(owner, command)

    def recover(self, owner, request_id):
        self.auth.require(owner, "run")
        rows = self.store.sql("SELECT * FROM af_schedule_editor_commands WHERE owner_id=:owner AND request_id=:request",
                              owner=owner, request=request_id)
        _require(bool(rows), 404, "SCHEDULE_COMMAND_NOT_FOUND")
        command = rows[0]
        with self.service._lock(command["schedule_id"]):
            self._recover(owner, command)
        return self._project(owner, command["schedule_id"])

    def inspect(self, owner, identifier):
        self.auth.require(owner, "run")
        self._read_recover(owner, identifier)
        return self._project(owner, identifier)

    def list(self, owner, after=None):
        self.auth.require(owner, "run")
        if after is not None:
            _require(type(after) is str and re.fullmatch(r"[a-f0-9-]{36}", after), 400)
            self.service._bound(after, owner)
        # Include precommitted creations whose native write may have committed before ACK loss.
        pending = self.store.sql("""SELECT DISTINCT schedule_id FROM af_schedule_editor_commands
            WHERE owner_id=:owner AND status='pending' LIMIT 100""", owner=owner)
        for row in pending:
            try:
                self._read_recover(owner, row["schedule_id"])
            except HTTPException as error:
                if error.status_code != 409:
                    raise
        rows = self.store.sql("""SELECT schedule_id FROM af_schedule_bindings
            WHERE owner_id=:owner AND schedule_id>:after ORDER BY schedule_id LIMIT 21""",
            owner=owner, after=after or "")
        items = [self._project(owner, row["schedule_id"]) for row in rows[:20]]
        return {"schema": 1, "ownerId": owner, "items": items,
                "nextCursor": items[-1]["id"] if len(rows) > 20 else None, "snapshot": False}

    def mutate(self, owner, kind, body, identifier=None):
        self.service._require_write(owner)
        request = body["requestId"]
        fingerprint = digest({"kind": kind, "scheduleId": identifier, "body": body})
        identifier = identifier or str(uuid5(NAMESPACE_URL, canonical({"owner": owner, "request": request, "scope": "schedule-editor-v1"})))
        with self.service._lock(identifier):
            old = self.store.sql("SELECT * FROM af_schedule_editor_commands WHERE owner_id=:owner AND request_id=:request",
                                 owner=owner, request=request)
            if old:
                _require(old[0]["fingerprint"] == fingerprint, 409, "IDEMPOTENCY_CONFLICT")
                self._recover(owner, old[0])
                return self._project(owner, identifier)
            _require(not self._pending(owner, identifier), 409, "SCHEDULE_EDITOR_UNKNOWN")
            if kind == "create":
                preview = preview_schedule(body["cron"], body["timezone"])
                plan = self.service._plan(body["planId"], owner)
                _require(not self.service.db.get_schedule_by_name(body["name"].strip(), user_id=owner), 409,
                         "SCHEDULE_NAME_EXISTS")
                target = Schedule(id=identifier, name=body["name"].strip(), cron_expr=preview["cron"],
                    timezone=body["timezone"], endpoint=ENDPOINT, enabled=False, user_id=owner,
                    payload={"planId": plan["id"], "planHash": digest(plan)}, max_retries=0, timeout_seconds=30,
                    next_run_at=preview["nextRuns"][0]["epoch"], managed_by=MANAGED_BY,
                    target_type="agent", target_id=EXECUTOR_ID)
                revision = 1
            else:
                current, binding = self.service._bound(identifier, owner)
                _require(self._version(current) == body["expectedDefinitionFingerprint"], 409, "SCHEDULE_EDITOR_STALE")
                plan = self.store.plan(binding["plan_id"], owner)
                target = Schedule.from_dict(current.to_dict())
                if kind == "update":
                    self.service._plan(plan["id"], owner)
                    preview = preview_schedule(body["cron"], body["timezone"])
                    target.cron_expr, target.timezone = preview["cron"], body["timezone"]
                    target.next_run_at = preview["nextRuns"][0]["epoch"]
                else:
                    _require(type(body["enabled"]) is bool, 422)
                    if body["enabled"]:
                        self.service._plan(plan["id"], owner)
                    target.enabled = body["enabled"]
                revision = self._editor(identifier)["revision"] + 1
            intent = {"kind": kind, "target": target.to_dict(), "planId": plan["id"],
                      "planHash": digest(plan), "revision": revision, "createdAt": now()}
            self.store.sql("""INSERT INTO af_schedule_editor_commands VALUES
                (:owner,:request,:id,:fp,:intent,'pending')""", owner=owner, request=request,
                id=identifier, fp=fingerprint, intent=canonical(intent))
            # No automatic retry after this durable intent. A lost native ACK is reconciled by exact ID.
            self.service._require_write(owner)
            if kind != "enabled" or target.enabled:
                self.service._plan(plan["id"], owner)
            try:
                if kind == "create":
                    self.service.db.create_schedule(target.to_dict())
                elif kind == "update":
                    self.service.manager.update(identifier, user_id=owner, cron_expr=target.cron_expr,
                        timezone=target.timezone, next_run_at=target.next_run_at)
                else:
                    (self.service.manager.enable if target.enabled else self.service.manager.disable)(identifier, user_id=owner)
            except Exception:
                # A committed native write may have lost its response. Never repeat it here.
                raise HTTPException(409, "SCHEDULE_EDITOR_UNKNOWN") from None
            command = self.store.sql("SELECT * FROM af_schedule_editor_commands WHERE owner_id=:owner AND request_id=:request",
                                     owner=owner, request=request)[0]
            self._recover(owner, command)
            self.store.audit(owner, "schedule.editor." + kind, identifier, {"requestId": request})
            return self._project(owner, identifier)

    def occurrences(self, owner, identifier, after=None):
        self.auth.require(owner, "run")
        self.service._history_binding(identifier, owner)
        if after is not None:
            rows = self.store.sql("""SELECT id FROM af_schedule_occurrences
                WHERE id=:after AND owner_id=:owner AND schedule_id=:id""", after=after, owner=owner, id=identifier)
            _require(bool(rows), 400)
        rows = self.store.sql("""SELECT * FROM af_schedule_occurrences WHERE owner_id=:owner
            AND schedule_id=:id AND id>:after ORDER BY id LIMIT 21""", owner=owner, id=identifier, after=after or "")
        items = []
        for row in rows[:20]:
            task = self.store.task(row["task_id"], owner) if row["task_id"] else None
            queue = self.service.db.get_job(task["run_id"]) if task and task["run_id"] else None
            items.append({"id": row["id"], "ownerId": owner, "scheduleId": identifier,
                "status": row["status"], "taskId": row["task_id"], "nativeRunId": task["run_id"] if task else None,
                "createdAt": row["created_at"], "taskStatus": queue.get("status") if queue else None,
                "reasonCode": "ADMISSION_REJECTED" if row["status"] == "rejected" else
                              "ADMISSION_UNKNOWN" if row["status"] in {"unknown", "reserving"} else None})
        return {"schema": 1, "ownerId": owner, "scheduleId": identifier, "items": items,
                "nextCursor": items[-1]["id"] if len(rows) > 20 else None, "snapshot": False}


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Clock(Body):
    cron: str = Field(min_length=5, max_length=100)
    timezone: str = Field(min_length=1, max_length=100)


class Create(Clock):
    planId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")


class Update(Clock):
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")
    expectedDefinitionFingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class Enabled(Body):
    enabled: StrictBool
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")
    expectedDefinitionFingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def schedule_management_router(auth, service):
    router = APIRouter(prefix="/api/factory/schedule-management")
    def owner(request):
        user = auth.user(request)
        auth.require(user["id"], "run")
        return user["id"]

    @router.get("/metadata")
    def metadata(request: Request):
        return service.metadata(owner(request))

    @router.post("/preview")
    def preview(body: Clock, request: Request):
        owner(request)
        return preview_schedule(body.cron, body.timezone)

    @router.get("")
    def listing(request: Request, after: str | None = None):
        return service.list(owner(request), after)

    @router.post("", status_code=201)
    def create(body: Create, request: Request):
        return service.mutate(owner(request), "create", body.model_dump())

    @router.get("/commands/{request_id}")
    def recover(request_id: str, request: Request):
        return service.recover(owner(request), request_id)

    @router.get("/{identifier}")
    def inspect(identifier: str, request: Request):
        return service.inspect(owner(request), identifier)

    @router.patch("/{identifier}")
    def update(identifier: str, body: Update, request: Request):
        return service.mutate(owner(request), "update", body.model_dump(), identifier)

    @router.post("/{identifier}/enabled")
    def enabled(identifier: str, body: Enabled, request: Request):
        return service.mutate(owner(request), "enabled", body.model_dump(), identifier)

    @router.get("/{identifier}/occurrences")
    def occurrences(identifier: str, request: Request, after: str | None = None):
        return service.occurrences(owner(request), identifier, after)

    return router

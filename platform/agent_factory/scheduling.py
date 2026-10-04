"""Guarded Factory admission over Agno's public persistent schedule poller.

This adapter schedules admissions, not agent loops. Native queue jobs own
execution, pause/resume and restart recovery. An uncertain admission is never
submitted again automatically.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.scheduler import ScheduleManager, SchedulePoller
from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as PoolTimeout

from .auth import EXECUTOR_ID
from .schedule_diagnostics import ScheduleDiagnostics
from .store import canonical, digest, now

MANAGED_BY = "agent-factory"
ENDPOINT = f"/agents/{EXECUTOR_ID}/runs"


class SchedulingService:
    """Native poller executor; CRUD callers must supply native-verified identity."""

    def __init__(self, settings: Any, store: Any, native_db: Any, auth: Any, bridge: Any):
        self.settings, self.store, self.db = settings, store, native_db
        self.auth, self.bridge = auth, bridge
        self.manager = ScheduleManager(native_db)
        self.diagnostics = ScheduleDiagnostics(self)
        # Separate, strictly bounded lock pool: metadata stays available across HTTP.
        self.lock_engine = create_engine(store.engine.url, pool_size=1, max_overflow=0, pool_timeout=.01)
        self.poller = SchedulePoller(native_db, self,
            poll_interval=getattr(settings, "schedule_poll_seconds", 15),
            max_concurrent=min(settings.max_workers, 4), stop_timeout=2)

    def initialize(self) -> None:
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_schedule_bindings (
            schedule_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            plan_id TEXT NOT NULL REFERENCES af_plans(id), plan_hash TEXT NOT NULL,
            definition_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_schedule_occurrences (
            id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL REFERENCES af_schedule_bindings(schedule_id),
            owner_id TEXT NOT NULL, occurrence_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
            request_id TEXT NOT NULL, task_id TEXT REFERENCES af_tasks(id),
            status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL,
            UNIQUE(owner_id,schedule_id,occurrence_key))""")

        self.store.sql("""CREATE TABLE IF NOT EXISTS af_schedule_editor_commands (
            owner_id TEXT NOT NULL, request_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, intent TEXT NOT NULL, status TEXT NOT NULL,
            PRIMARY KEY(owner_id,request_id))""")
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_schedule_editor_state (
            schedule_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
            request_id TEXT, last_command_id TEXT)""")

        self.diagnostics.initialize()

    def _touch_editor(self, schedule_id):
        self.store.sql("""INSERT INTO af_schedule_editor_state VALUES(:id,1,NULL,NULL)
            ON CONFLICT(schedule_id) DO UPDATE SET revision=af_schedule_editor_state.revision+1,
            last_command_id=NULL""", id=schedule_id)

    @staticmethod
    def _definition(schedule: Schedule) -> str:
        return digest({key: getattr(schedule, key) for key in (
            "id", "user_id", "name", "cron_expr", "timezone", "endpoint", "method",
            "payload", "max_retries", "managed_by", "target_type", "target_id")})

    @contextmanager
    def _lock(self, key: str):
        # A nonblocking session lock spans committed metadata and native HTTP.
        # A crash releases it; duplicate claimants never block the event loop.
        try:
            connection = self.lock_engine.connect()
        except PoolTimeout:
            raise HTTPException(409, "SCHEDULE_ADMISSION_BUSY: inspect the persisted occurrence") from None
        with connection:
            locked = connection.execute(text("SELECT pg_try_advisory_lock(hashtext(:key))"),
                                        {"key": "af_schedule:" + key}).scalar()
            connection.commit()
            if not locked:
                raise HTTPException(409, "SCHEDULE_ADMISSION_BUSY: inspect the persisted occurrence")
            try:
                yield
            finally:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"),
                                   {"key": "af_schedule:" + key})
                connection.commit()

    def _require_write(self, owner: str) -> None:
        self.auth.require(owner, "components:write")
        self.auth.require(owner, "run")

    def _plan(self, plan_id: str, owner: str) -> dict[str, Any]:
        self.store.require_current_policy()
        self.auth.require(owner, "run")
        plan = self.store.plan(plan_id, owner)
        if plan["status"] != "ready" or plan.get("delegation") or plan.get("remoteHandoff"):
            raise HTTPException(409, "Schedule requires a ready, top-level immutable plan")
        self.store.require_plan_execution(owner, plan)
        return plan

    def _bound(self, schedule_id: str, owner: str) -> tuple[Schedule, dict[str, Any]]:
        schedule = self.manager.get(schedule_id, user_id=owner)
        rows = self.store.sql("SELECT * FROM af_schedule_bindings WHERE schedule_id=:id AND owner_id=:owner",
                              id=schedule_id, owner=owner)
        if schedule is None or not rows:
            raise HTTPException(404, "Factory schedule not found")
        binding = rows[0]
        pending = self.store.sql("""SELECT request_id FROM af_schedule_editor_commands
            WHERE owner_id=:owner AND schedule_id=:id AND status='pending' LIMIT 1""", owner=owner, id=schedule_id)
        if pending:
            raise HTTPException(409, "SCHEDULE_EDITOR_UNKNOWN: reconcile the original editor receipt")
        if schedule.managed_by != MANAGED_BY or self._definition(schedule) != binding["definition_hash"]:
            raise HTTPException(409, "SCHEDULE_INTEGRITY: native definition differs from its trusted binding")
        return schedule, binding

    def create(self, owner: str, plan_id: str, name: str, cron: str, timezone: str = "UTC") -> dict[str, Any]:
        self._require_write(owner)
        plan = self._plan(plan_id, owner)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise HTTPException(422, "Schedule name must contain 1–120 characters")
        if not validate_cron_expr(cron) or not validate_timezone(timezone):
            raise HTTPException(422, "Invalid cron expression or IANA timezone")
        with self._lock("create:" + owner + ":" + name.strip()):
            if self.manager.db.get_schedule_by_name(name.strip(), user_id=owner):
                raise HTTPException(409, "Schedule name already exists for this owner")
            schedule = self.manager.create(name.strip(), cron, ENDPOINT, timezone=timezone,
                payload={"planId": plan_id, "planHash": digest(plan)}, max_retries=0,
                timeout_seconds=30, user_id=owner,
                provenance={"managed_by": MANAGED_BY, "target_type": "agent", "target_id": EXECUTOR_ID})
            self.store.sql("""INSERT INTO af_schedule_bindings VALUES(:id,:owner,:plan,:hash,:definition,:at)""",
                id=schedule.id, owner=owner, plan=plan_id, hash=digest(plan),
                definition=self._definition(schedule), at=now())
        self.store.audit(owner, "schedule.create", schedule.id, {"planId": plan_id, "cron": cron, "timezone": timezone})
        return schedule.to_dict()

    def get(self, owner: str, schedule_id: str) -> dict[str, Any]:
        self.auth.require(owner, "run")
        return self._bound(schedule_id, owner)[0].to_dict()

    def list(self, owner: str) -> list[dict[str, Any]]:
        self.auth.require(owner, "run")
        rows = self.store.sql("SELECT schedule_id FROM af_schedule_bindings WHERE owner_id=:owner ORDER BY created_at DESC LIMIT 100", owner=owner)
        return [self.get(owner, row["schedule_id"]) for row in rows]

    def update(self, owner: str, schedule_id: str, cron: str, timezone: str = "UTC") -> dict[str, Any]:
        self._require_write(owner)
        if not validate_cron_expr(cron) or not validate_timezone(timezone):
            raise HTTPException(422, "Invalid cron expression or IANA timezone")
        with self._lock(schedule_id):
            _, binding = self._bound(schedule_id, owner)
            self._plan(binding["plan_id"], owner)
            updated = self.manager.update(schedule_id, user_id=owner, cron_expr=cron,
                timezone=timezone, next_run_at=compute_next_run(cron, timezone))
            if updated is None:
                raise HTTPException(503, "Native schedule update failed")
            self.store.sql("UPDATE af_schedule_bindings SET definition_hash=:hash WHERE schedule_id=:id",
                           id=schedule_id, hash=self._definition(updated))
            self._touch_editor(schedule_id)
        self.store.audit(owner, "schedule.update", schedule_id, {"cron": cron, "timezone": timezone})
        return updated.to_dict()

    def set_enabled(self, owner: str, schedule_id: str, enabled: bool) -> dict[str, Any]:
        self._require_write(owner)
        with self._lock(schedule_id):
            _, binding = self._bound(schedule_id, owner)
            if enabled:
                self._plan(binding["plan_id"], owner)
            updated = self.manager.enable(schedule_id, user_id=owner) if enabled else self.manager.disable(schedule_id, user_id=owner)
            if updated is None:
                raise HTTPException(503, "Native schedule state update failed")
            self._touch_editor(schedule_id)
        self.store.audit(owner, "schedule.enable" if enabled else "schedule.disable", schedule_id, {})
        return updated.to_dict()

    def _history_binding(self, schedule_id, owner):
        # Cleanup and history bind to the original immutable plan, not a pending
        # clock edit. A native ACK cannot revoke custody of an already owned task.
        rows = self.store.sql("SELECT * FROM af_schedule_bindings WHERE schedule_id=:id AND owner_id=:owner",
                              id=schedule_id, owner=owner)
        if not rows:
            raise HTTPException(404, "Factory schedule not found")
        plan = self.store.plan(rows[0]["plan_id"], owner)
        if digest(plan) != rows[0]["plan_hash"]:
            raise HTTPException(409, "SCHEDULE_INTEGRITY: historical plan binding changed")
        return rows[0]

    def occurrences(self, owner: str, schedule_id: str) -> list[dict[str, Any]]:
        self.auth.require(owner, "run")
        self._history_binding(schedule_id, owner)
        rows = self.store.sql("SELECT * FROM af_schedule_occurrences WHERE schedule_id=:id AND owner_id=:owner ORDER BY created_at DESC LIMIT 100", id=schedule_id, owner=owner)
        for row in rows:
            if row["task_id"]:
                task = self.store.task(row["task_id"], owner)
                row["task"] = task
                row["queue"] = self.db.get_job(task["run_id"]) if task["run_id"] else None
        return rows

    async def trigger(self, owner: str, schedule_id: str, request_id: str) -> dict[str, Any]:
        self._require_write(owner)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 160:
            raise HTTPException(422, "Manual trigger requires a bounded request ID")
        schedule, _ = self._bound(schedule_id, owner)
        return await self._fire(schedule, "manual:" + request_id, release=False)

    async def cancel_occurrence(self, owner: str, schedule_id: str, occurrence_id: str) -> dict[str, Any]:
        self.auth.require(owner, "run")
        self._history_binding(schedule_id, owner)
        rows = self.store.sql("SELECT * FROM af_schedule_occurrences WHERE id=:id AND schedule_id=:schedule AND owner_id=:owner",
                              id=occurrence_id, schedule=schedule_id, owner=owner)
        if not rows:
            raise HTTPException(404, "Scheduled occurrence not found")
        occurrence = rows[0]
        if not occurrence["task_id"]:
            raise HTTPException(409, "UNKNOWN occurrence has no authoritative task binding")
        task = self.store.task(occurrence["task_id"], owner)
        binding = self._history_binding(schedule_id, owner)
        if task["plan_id"] != binding["plan_id"] or task["request_id"] != occurrence["request_id"]:
            raise HTTPException(409, "SCHEDULE_INTEGRITY: original occurrence task changed")
        self.store.request_cancel(task["id"])
        if self.store.delegation:
            return await self.store.delegation.cascade_cancel(owner, task["id"])
        if not task["run_id"]:
            found = await self.bridge.find_run(task["id"], owner)
            if found:
                self.store.accept(task["id"], found["run_id"])
                task = self.store.task(task["id"], owner)
        if not task["run_id"]:
            raise HTTPException(409, "UNKNOWN native admission; cancellation retained pending reconciliation")
        return await self.bridge.cancel_run(task["run_id"], task["id"], owner)

    def _require_lease(self, claimed: Schedule) -> None:
        current = self.db.get_schedule(claimed.id)
        if not current or not claimed.locked_by or claimed.locked_at is None or any(
            current.get(field) != getattr(claimed, field)
            for field in ("locked_by", "locked_at", "next_run_at")
        ):
            raise HTTPException(409, "SCHEDULE_LEASE_CHANGED: current native claim no longer belongs to this worker")

    async def _reconcile(self, receipt: dict[str, Any]) -> dict[str, Any]:
        if receipt["status"] == "rejected":
            return receipt
        if not receipt["task_id"]:
            try:
                task = self.store.task_for_request(receipt["request_id"], receipt["owner_id"])
            except HTTPException as error:
                if error.status_code != 404:
                    raise
            else:
                # Read the original committed reservation after a crash between
                # reservation and occurrence binding; never reserve or submit again.
                _, binding = self._bound(receipt["schedule_id"], receipt["owner_id"])
                plan = self.store.plan(binding["plan_id"], receipt["owner_id"])
                expected = digest({"definition": binding["definition_hash"], "plan": binding["plan_hash"]})
                if (receipt["fingerprint"] != expected or digest(plan) != binding["plan_hash"]
                        or task["plan_id"] != binding["plan_id"]
                        or task["fingerprint"] != digest({"planId": plan["id"], "planHash": digest(plan)})):
                    raise HTTPException(409, "SCHEDULE_INTEGRITY: original reservation differs from its occurrence")
                self.store.sql("UPDATE af_schedule_occurrences SET task_id=:task WHERE id=:id AND task_id IS NULL",
                               id=receipt["id"], task=task["id"])
                receipt = self._receipt(receipt["id"])
        if receipt["task_id"]:
            task = self.store.task(receipt["task_id"], receipt["owner_id"])
            if not task["run_id"] and task["admission"] != "rejected":
                found = await self.bridge.find_run(task["id"], receipt["owner_id"])
                if found:
                    self.store.accept(task["id"], found["run_id"])
                else:
                    self.store.admission_unknown(task["id"])
                task = self.store.task(task["id"], receipt["owner_id"])
            status = "accepted" if task["run_id"] else "rejected" if task["admission"] == "rejected" else "unknown"
            self._record(receipt["id"], status, task)
        else:
            self._record(receipt["id"], "unknown", error="Interrupted before authoritative task binding; no automatic replay")
        return self._receipt(receipt["id"])

    def _receipt(self, identifier: str) -> dict[str, Any]:
        return self.store.sql("SELECT * FROM af_schedule_occurrences WHERE id=:id", id=identifier)[0]

    def _record(self, identifier: str, status: str, task: dict[str, Any] | None = None, error: str | None = None) -> None:
        self.store.sql("UPDATE af_schedule_occurrences SET status=:status,error=:error WHERE id=:id",
                       id=identifier, status=status, error=error)
        native = self.db.update_schedule_run(identifier, status=status,
            run_id=task["run_id"] if task else None, session_id=task["id"] if task else None,
            error=error, completed_at=int(time.time()))
        if native is None:
            raise HTTPException(503, "Native schedule admission history could not be persisted")
        receipt = self._receipt(identifier)
        self.store.audit(receipt["owner_id"], "schedule.admission", receipt["schedule_id"],
                         {"occurrenceId": identifier, "taskId": receipt["task_id"], "status": status})

    async def _fire(self, claimed: Schedule, key: str, release: bool) -> dict[str, Any]:
        observation = {"reason": "CLOCK_BUSY", "beforeOccurrence": True}
        try:
            return await self._fire_locked(claimed, key, release, observation)
        except Exception as error:
            if observation["beforeOccurrence"]:
                reason = observation["reason"] if isinstance(error, HTTPException) and error.status_code < 500 else "CHECK_UNAVAILABLE"
                await self.diagnostics.observe(claimed, key, reason, source="native" if release else "manual")
            raise

    async def _fire_locked(self, claimed: Schedule, key: str, release: bool, observation: dict[str, Any]) -> dict[str, Any]:
        with self._lock(claimed.id):
            try:
                observation["reason"] = "AUTHORIZATION_DENIED"
                owner = claimed.user_id
                if not owner:
                    raise HTTPException(403, "Unowned schedules cannot admit Factory tasks")
                self.auth.require(owner, "run")
                observation["reason"] = "CLAIM_CHANGED"
                if release:
                    self._require_lease(claimed)
                observation["reason"] = "BINDING_UNAVAILABLE"
                current, binding = self._bound(claimed.id, owner)
                observation["reason"] = "PAUSED"
                if not current.enabled:
                    raise HTTPException(409, "Schedule disabled after claim")
                observation["reason"] = "DEFINITION_CHANGED"
                if self._definition(claimed) != self._definition(current):
                    raise HTTPException(409, "Schedule changed after claim")
                observation["reason"] = "CLAIM_CHANGED"
                if release and current.next_run_at != claimed.next_run_at:
                    raise HTTPException(409, "Schedule occurrence already advanced")
                observation["reason"] = "PLAN_UNAVAILABLE"
                plan = self._plan(binding["plan_id"], owner)
                if digest(plan) != binding["plan_hash"]:
                    raise HTTPException(409, "Immutable scheduled plan differs from its binding")
                identifier = str(uuid5(NAMESPACE_URL, canonical({"owner": owner, "schedule": claimed.id, "key": key})))
                fp = digest({"definition": binding["definition_hash"], "plan": binding["plan_hash"]})
                request_id = "schedule:" + identifier
                observation["beforeOccurrence"] = False
                rows = self.store.sql("""INSERT INTO af_schedule_occurrences
                    VALUES(:id,:schedule,:owner,:key,:fp,:request,NULL,'reserving',NULL,:at)
                    ON CONFLICT DO NOTHING RETURNING id""", id=identifier, schedule=claimed.id,
                    owner=owner, key=key, fp=fp, request=request_id, at=now())
                receipt = self._receipt(identifier)
                if receipt["fingerprint"] != fp:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: scheduled occurrence definition changed")
                if self.db.get_schedule_run(identifier, user_id=owner) is None:
                    self.db.create_schedule_run(ScheduleRun(id=identifier, schedule_id=claimed.id,
                        user_id=owner, status="admitting").to_dict())
                if not rows:
                    return await self._reconcile(receipt)
                try:
                    task, fresh = self.store.reserve_task(plan, request_id)
                except HTTPException as error:
                    self._record(identifier, "rejected", error=str(error.detail))
                    return self._receipt(identifier)
                self.store.sql("UPDATE af_schedule_occurrences SET task_id=:task WHERE id=:id",
                               id=identifier, task=task["id"])
                if not fresh:
                    return await self._reconcile(self._receipt(identifier))
                try:
                    # Fresh current lease, rights and policy before native admission.
                    if release:
                        self._require_lease(claimed)
                    self._plan(binding["plan_id"], owner)
                    native = await asyncio.wait_for(self.bridge.submit({**plan, "task_id": task["id"]}, owner, request_id), timeout=30)
                    run_id = native.get("run_id")
                    if not isinstance(run_id, str) or not run_id:
                        raise RuntimeError("Native acknowledgement has no run ID")
                    self.store.accept(task["id"], run_id)
                    self._record(identifier, "accepted", self.store.task(task["id"], owner))
                    self.store.event(task["id"], "scheduled_admission", "Native queue accepted scheduled immutable plan", {"scheduleId": claimed.id, "occurrenceId": identifier})
                except HTTPException as error:
                    if error.status_code < 500:
                        self.store.admission_failed(task["id"], str(error.detail))
                        self._record(identifier, "rejected", self.store.task(task["id"], owner), str(error.detail))
                    else:
                        self.store.admission_unknown(task["id"])
                        current_task = self.store.task(task["id"], owner)
                        self._record(identifier, "accepted" if current_task["run_id"] else "unknown", current_task,
                                     "Native acknowledgement/history uncertain; inspect before retry")
                except (Exception, asyncio.CancelledError):
                    self.store.admission_unknown(task["id"])
                    current_task = self.store.task(task["id"], owner)
                    self._record(identifier, "accepted" if current_task["run_id"] else "unknown", current_task,
                                 "Native acknowledgement/history uncertain; inspect before retry")
                    current_async_task = asyncio.current_task()
                    if current_async_task is not None and current_async_task.cancelling():
                        raise
                return self._receipt(identifier)
            except HTTPException as error:
                self.store.audit(claimed.user_id or "__unowned_schedule__", "schedule.denied", claimed.id,
                                 {"statusCode": error.status_code, "occurrenceKey": key})
                raise
            finally:
                if release:
                    # Do not release a successor worker's lease or another due time.
                    current = self.db.get_schedule(claimed.id)
                    if current and current.get("managed_by") == MANAGED_BY and current.get("next_run_at") == claimed.next_run_at and current.get("locked_by") == claimed.locked_by and current.get("locked_at") == claimed.locked_at:
                        self.db.release_schedule(claimed.id, next_run_at=compute_next_run(current["cron_expr"], current["timezone"]))

    async def execute(self, schedule: Schedule | dict[str, Any], db: Any, release_schedule: bool = True) -> dict[str, Any]:
        if db is not self.db:
            raise RuntimeError("Schedule poller database does not match Factory database")
        claimed = Schedule.from_dict(schedule) if isinstance(schedule, dict) else schedule
        if not release_schedule:
            raise HTTPException(409, "Use the Factory trigger API with a request ID")
        if claimed.next_run_at is None:
            await self.diagnostics.observe(claimed, "missing-due-time", "CLAIM_CHANGED")
            raise HTTPException(409, "Schedule has no persisted occurrence time")
        return await self._fire(claimed, "due:" + str(claimed.next_run_at), release=True)

    async def start(self) -> None:
        self.initialize()
        # Read-only ticket reconciliation on startup, never queue resubmission.
        rows = self.store.sql("SELECT * FROM af_schedule_occurrences WHERE status IN ('reserving','unknown') ORDER BY created_at LIMIT 100")
        for receipt in rows:
            try:
                self.auth.require(receipt["owner_id"], "run")
                with self._lock(receipt["schedule_id"]):
                    await self._reconcile(receipt)
            except HTTPException:
                continue
        await self.poller.start()

    async def stop(self) -> None:
        await self.poller.stop()
        self.manager.close()
        self.lock_engine.dispose()
        self.diagnostics.engine.dispose()

    @asynccontextmanager
    async def lifespan(self, app: Any):
        await self.start()
        try:
            yield
        finally:
            await self.stop()

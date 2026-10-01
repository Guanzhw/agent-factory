"""Bounded metadata around independently queued native factory children.

There is no agent loop, polling scheduler, or queue implementation here. A
receiptless reservation is conservatively UNKNOWN and is never submitted twice.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from .catalog import create_plan
from .store import digest, now

ACTIVE = {"queued", "pending", "running", "paused"}
TERMINAL = {"completed", "failed", "cancelled", "canceled", "error"}


def application_group_status(parent_status: str, group: dict[str, Any]) -> str:
    """A completed native parent cannot close an application with pending children."""
    if group["unknown"]:
        return "unknown"
    if parent_status == "completed" and group["pending"]:
        return "waiting_children"
    if parent_status == "completed" and any(child["failed"] for child in group["children"]):
        return "failed"
    if parent_status == "completed" and any(child["nativeStatus"] in {"cancelled", "canceled"} for child in group["children"]):
        return "canceled"
    if parent_status == "canceled" and group["pending"]:
        return "canceling"
    return parent_status


class _ChildPlannerStore:
    """Reuse the catalog while binding delegation scope before immutable storage."""
    def __init__(self, store: Any, ancestors: list[dict[str, Any]], binding: dict[str, Any]):
        self.store, self.ancestors, self.binding = store, ancestors, binding

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)

    def save_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        for parent in self.ancestors:
            if not set(plan["capabilities"]) <= set(parent["capabilities"]) or not set(plan["tools"]) <= set(parent["tools"]):
                raise HTTPException(403, "Child authority exceeds an ancestor's immutable mandate")
        plan = {**plan, "delegation": self.binding,
                "budget": {**plan["budget"], "depth": self.binding["depth"]}}
        plan["fingerprint"] = digest({key: value for key, value in plan.items() if key not in {"id", "createdAt", "fingerprint"}})
        return self.store.save_plan(plan)


class DelegationService:
    def __init__(self, settings: Any, store: Any, auth: Any, bridge: Any):
        self.settings, self.store, self.auth, self.bridge = settings, store, auth, bridge

    def initialize(self) -> None:
        self.store.sql("CREATE TABLE IF NOT EXISTS af_delegation_roots (root_id TEXT PRIMARY KEY REFERENCES af_tasks(id), owner_id TEXT NOT NULL, reclaimed BOOLEAN NOT NULL DEFAULT FALSE)")
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_delegation_links (
            owner_id TEXT NOT NULL, parent_id TEXT NOT NULL REFERENCES af_tasks(id), request_id TEXT NOT NULL,
            root_id TEXT NOT NULL REFERENCES af_tasks(id), depth INTEGER NOT NULL CHECK(depth BETWEEN 1 AND 2),
            fingerprint TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES af_plans(id),
            child_id TEXT UNIQUE REFERENCES af_tasks(id), created_at TEXT NOT NULL,
            PRIMARY KEY(owner_id,parent_id,request_id))""")
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_delegation_tool_calls (
            task_id TEXT NOT NULL REFERENCES af_tasks(id), call_id TEXT NOT NULL,
            root_id TEXT NOT NULL REFERENCES af_tasks(id), tool_name TEXT NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(task_id,call_id))""")

    @contextmanager
    def _root_lock(self, root_id: str):
        # Session lock spans the two committed metadata phases. Store's global
        # quota lock is acquired only after this root lock; no async work occurs
        # while it is held, and no native HTTP request depends on releasing it.
        with self.store.engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": "delegation:" + root_id})
            conn.commit()
            try:
                yield conn
            finally:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": "delegation:" + root_id})
                conn.commit()

    def _link(self, child_id: str) -> dict[str, Any] | None:
        rows = self.store.sql("SELECT * FROM af_delegation_links WHERE child_id=:id", id=child_id)
        return rows[0] if rows else None

    def _ancestry(self, task: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        ancestors, seen = [], {task["id"]}
        cursor = task
        while (link := self._link(cursor["id"])) is not None:
            cursor = self.store.task(link["parent_id"], task["owner_id"])
            if cursor["id"] in seen or len(ancestors) >= 2:
                raise HTTPException(409, "Invalid persisted delegation ancestry")
            seen.add(cursor["id"])
            ancestors.append(cursor)
        return cursor["id"], ancestors

    def _native(self, task: dict[str, Any]) -> dict[str, Any]:
        db = getattr(self.store, "native_db", None)
        if db is None:
            raise HTTPException(503, "Native durable queue facts are unavailable")
        if not task.get("run_id"):
            return {}
        ticket = db.get_job(task["run_id"])
        if not ticket:
            raise HTTPException(503, "Persisted native ticket is unavailable")
        if ticket.get("session_id") != task["id"] or ticket.get("user_id") != task["owner_id"] or ticket.get("component_id") != "factory-executor":
            raise HTTPException(403, "Native ticket identity differs from delegation binding")
        return ticket

    def _mandate(self, owner: str, task: dict[str, Any], *, creating: bool = False) -> tuple[str, list[dict[str, Any]]]:
        self.auth.require(owner, "run")
        self.store.require_current_policy()
        root_id, ancestors = self._ancestry(task)
        roots = self.store.sql("SELECT * FROM af_delegation_roots WHERE root_id=:id", id=root_id)
        if roots and (roots[0]["owner_id"] != owner or roots[0]["reclaimed"]):
            raise HTTPException(409, "Delegation group mandate has been reclaimed")
        plans = []
        for current in [task, *ancestors]:
            if current["owner_id"] != owner or current["cancel_requested"] or current["admission"] != "accepted":
                raise HTTPException(403, "Ancestor mandate is canceled, unavailable or belongs to another user")
            if self.store.has_failures(current["id"]):
                raise HTTPException(409, "Ancestor application mandate has failed")
            native = self._native(current)
            raw = str(native.get("status", "")).lower()
            if raw in {"failed", "cancelled", "canceled", "error"} or raw not in ACTIVE | {"completed"}:
                raise HTTPException(409, "Ancestor native mandate is unavailable")
            if current["id"] == task["id"] and raw not in ACTIVE:
                raise HTTPException(409, "Parent must have an active or paused native ticket" if creating else "Child native ticket is no longer active")
            plan = self.store.plan(current["plan_id"], owner)
            if self.store.material_governance is not None:
                self.store.material_governance.require_materials_current(plan)
            if plan["status"] != "ready":
                raise HTTPException(409, "Ancestor plan is blocked")
            if creating:
                ids = [current["id"], *(link["child_id"] for link in self._descendants(current["id"]) if link["child_id"])]
                used = self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE task_id=ANY(:ids)", ids=ids)[0]["n"]
                if used >= int(plan["budget"]["toolCalls"]):
                    raise HTTPException(429, "Ancestor tool execution budget is exhausted")
            plans.append(plan)
        for child, parent in zip(plans, plans[1:]):
            if not set(child["capabilities"]) <= set(parent["capabilities"]) or not set(child["tools"]) <= set(parent["tools"]):
                raise HTTPException(403, "Child scope exceeds immutable ancestor authority")
        return root_id, plans

    def authorize_child(self, run_context: Any) -> None:
        task = self.store.task(run_context.run_id, run_context.user_id)
        if task["id"] != run_context.session_id:
            raise PermissionError("Child session binding mismatch")
        link = self._link(task["id"])
        plan = self.store.plan(task["plan_id"], run_context.user_id)
        binding = plan.get("delegation")
        if link is None:
            # A persisted intent cannot become an unguarded standalone task after
            # an uncertain crash between task reservation and link binding.
            if binding is not None or task["request_id"].startswith("delegation:"):
                raise PermissionError("Delegation metadata binding is incomplete")
            return
        expected = {"parentTaskId": link["parent_id"], "rootTaskId": link["root_id"], "depth": link["depth"]}
        if binding != expected or link["plan_id"] != task["plan_id"] or link["owner_id"] != run_context.user_id:
            raise PermissionError("Immutable child plan differs from its persisted delegation binding")
        try:
            self._mandate(run_context.user_id, task)
        except HTTPException as error:
            self.store.event(task["id"], "protected_denied", "Current ancestor mandate denied a child operation", {"code": error.status_code})
            raise PermissionError(str(error.detail)) from error

    def consume_tool_budget(self, run_context: Any, call_id: str, name: str) -> dict[str, Any]:
        """Charge a native execution ID once against its root and ancestor budgets.

        Standalone root executions are recorded too, so later delegation cannot
        reset already consumed budget. The native runtime still owns execution.
        """
        if not isinstance(call_id, str) or not call_id or len(call_id) > 200:
            raise PermissionError("A bounded native tool execution ID is required")
        task = self.store.task(run_context.run_id, run_context.user_id)
        if task["id"] != run_context.session_id:
            raise PermissionError("Tool budget session binding mismatch")
        self.auth.require(run_context.user_id, "run")
        self.store.require_current_policy()
        root_id, ancestors = self._ancestry(task)
        with self._root_lock(root_id) as conn:
            self._mandate(run_context.user_id, self.store.task(task["id"], run_context.user_id))
            plan = self.store.plan(task["plan_id"], run_context.user_id)
            if name not in plan["tools"]:
                raise PermissionError("Tool budget cannot authorize an unlisted tool")
            old = self.store.sql("SELECT * FROM af_delegation_tool_calls WHERE task_id=:id AND call_id=:call", id=task["id"], call=call_id)
            if old:
                if old[0]["tool_name"] != name or old[0]["root_id"] != root_id:
                    raise PermissionError("Native execution ID conflicts with its persisted budget charge")
                return {"charged": False, "rootTaskId": root_id}
            for ancestor in [task, *ancestors]:
                ids = [ancestor["id"], *(link["child_id"] for link in self._descendants(ancestor["id"]) if link["child_id"])]
                used = self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE task_id=ANY(:ids)", ids=ids)[0]["n"]
                limit = int(self.store.plan(ancestor["plan_id"], run_context.user_id)["budget"]["toolCalls"])
                if used >= limit:
                    self.store.event(task["id"], "protected_denied", "Shared ancestor tool execution budget exhausted", {"ancestorTaskId": ancestor["id"], "used": used, "limit": limit})
                    raise PermissionError("Shared ancestor tool execution budget exhausted")
            with conn.begin():
                conn.execute(text("INSERT INTO af_delegation_roots(root_id,owner_id) VALUES(:root,:owner) ON CONFLICT DO NOTHING"), {"root": root_id, "owner": task["owner_id"]})
                conn.execute(text("INSERT INTO af_delegation_tool_calls VALUES(:task,:call,:root,:name,:at)"), {"task": task["id"], "call": call_id, "root": root_id, "name": name, "at": now()})
            return {"charged": True, "rootTaskId": root_id}

    def has_pending_children(self, task_id: str) -> bool:
        """Conservative synchronous native facts for Store capacity accounting."""
        for link in self._descendants(task_id):
            if not link["child_id"]:
                return True
            task = self.store.task(link["child_id"], link["owner_id"])
            if any(effect["status"] == "UNKNOWN" for effect in self.store.effects(task["id"])):
                return True
            if task["admission"] == "rejected" and not task.get("run_id"):
                continue
            try:
                native = self._native(task)
            except Exception:
                return True
            if str(native.get("status", "")).lower() not in TERMINAL:
                return True
        return False

    def delegation_scope(self, owner: str, parentTaskId: str) -> dict[str, Any]:
        """Current owner-scoped UI facts; this response never grants authority."""
        parent = self.store.task(parentTaskId, owner)  # Cross-owner access stays 404.
        root_id, ancestors = self._ancestry(parent)
        plan = self.store.plan(parent["plan_id"], owner)
        root = self.store.task(root_id, owner)
        root_plan = self.store.plan(root["plan_id"], owner)
        used = self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE root_id=:root", root=root_id)[0]["n"]
        children = self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_links WHERE root_id=:root", root=root_id)[0]["n"]
        shared = {"toolCallsUsed": used, "toolCallsLimit": root_plan["budget"]["toolCalls"], "childrenUsed": children,
                  "childrenLimit": min(4, int(root_plan["budget"].get("maxChildren", 4))), "maxDepth": min(2, int(root_plan["budget"].get("maxDepth", 2)))}
        depth = len(ancestors) + 1
        scope = {"allowed": True, "parentTaskId": parent["id"], "rootTaskId": root_id, "depth": depth,
                 "capabilities": plan["capabilities"], "tools": plan["tools"], "budget": plan["budget"], "sharedBudget": shared}
        try:
            self._mandate(owner, parent, creating=True)
            if depth > shared["maxDepth"] or children >= shared["childrenLimit"] or used >= shared["toolCallsLimit"]:
                raise HTTPException(429, "Shared delegation budget exhausted")
            counts = self.store.sql("SELECT COUNT(*) AS total,COUNT(*) FILTER(WHERE owner_id=:owner) AS owned FROM af_tasks WHERE NOT terminal", owner=owner)[0]
            if counts["total"] >= self.settings.max_total_tasks or counts["owned"] >= self.settings.max_user_tasks:
                raise HTTPException(429, "Active task budget exhausted")
        except HTTPException as error:
            if error.status_code not in {403, 409, 429}:
                raise
            scope.update(allowed=False, reason=str(error.detail))
        return scope

    async def create(self, owner: str, parentTaskId: str, goal: str, mode: str, requestId: str) -> dict[str, Any]:
        if not isinstance(requestId, str) or not 8 <= len(requestId) <= 100 or any(not (c.isascii() and (c.isalnum() or c in "_.:-")) for c in requestId):
            raise HTTPException(422, "A bounded delegation request ID is required")
        if not isinstance(goal, str) or not 2 <= len(goal.strip()) <= 2000 or mode not in {"literature", "experiment"}:
            raise HTTPException(422, "Unsupported bounded child goal or mode")
        self.auth.require(owner, "run")
        self.store.require_current_policy()
        parent = self.store.task(parentTaskId, owner)
        root_id, _ = self._ancestry(parent)
        request = {"owner": owner, "parent": parent["id"], "goal": goal.strip(), "mode": mode}
        fp = digest(request)
        native_request = "delegation:" + digest({"parent": parent["id"], "request": requestId})
        fresh, duplicate = False, False
        with self._root_lock(root_id) as conn:
            previous = self.store.sql("SELECT * FROM af_delegation_links WHERE owner_id=:owner AND parent_id=:parent AND request_id=:request", owner=owner, parent=parent["id"], request=requestId)
            if previous and previous[0]["fingerprint"] != fp:
                raise HTTPException(409, "IDEMPOTENCY_CONFLICT: delegation request changed")
            if previous:
                link, duplicate = previous[0], True
                if not link["child_id"]:
                    self._mandate(owner, self.store.task(parent["id"], owner), creating=True)
                    # No submit was possible without a persisted child binding.
                    # Recover the native Store reservation exactly once, rather
                    # than guessing whether a native acknowledgement was lost.
                    plan = self.store.plan(link["plan_id"], owner)
                    task, _ = self.store.reserve_task(plan, native_request)
                    with conn.begin():
                        conn.execute(text("UPDATE af_delegation_links SET child_id=:child WHERE owner_id=:owner AND parent_id=:parent AND request_id=:request"), {"child": task["id"], "owner": owner, "parent": parent["id"], "request": requestId})
                    link = {**link, "child_id": task["id"]}
                task = self.store.task(link["child_id"], owner)
            else:
                parent = self.store.task(parent["id"], owner)
                _, plans = self._mandate(owner, parent, creating=True)
                depth = len(plans)
                max_depth = min(2, int(plans[-1]["budget"].get("maxDepth", 2)))
                max_children = min(4, int(plans[-1]["budget"].get("maxChildren", 4)))
                count = self.store.sql("SELECT COUNT(*) AS n FROM af_delegation_links WHERE root_id=:root", root=root_id)[0]["n"]
                if depth > max_depth or count >= max_children:
                    raise HTTPException(429, "Shared delegation depth or lifetime child budget exhausted")
                binding = {"parentTaskId": parent["id"], "rootTaskId": root_id, "depth": depth}
                planner_store = _ChildPlannerStore(self.store, plans, binding)
                plan = self.store.admit_plan(owner, native_request, request, lambda: create_plan(planner_store, owner, goal.strip(), mode, plans[0]["application"]))
                if plan["status"] != "ready":
                    raise HTTPException(409, "Child preflight is blocked: " + "; ".join(plan["missing"]))
                link = {"owner_id": owner, "parent_id": parent["id"], "request_id": requestId, "root_id": root_id,
                        "depth": depth, "fingerprint": fp, "plan_id": plan["id"], "child_id": None, "created_at": now()}
                # An intent counts against the root before task reservation. A
                # crash anywhere after this commit cannot exceed the root cap.
                with conn.begin():
                    conn.execute(text("INSERT INTO af_delegation_roots(root_id,owner_id) VALUES(:root,:owner) ON CONFLICT DO NOTHING"), {"root": root_id, "owner": owner})
                    conn.execute(text("INSERT INTO af_delegation_links VALUES(:owner_id,:parent_id,:request_id,:root_id,:depth,:fingerprint,:plan_id,:child_id,:created_at)"), link)
                try:
                    task, fresh = self.store.reserve_task(plan, native_request)
                except HTTPException:
                    # A known quota rejection creates no native task/effect.
                    with conn.begin():
                        conn.execute(text("DELETE FROM af_delegation_links WHERE owner_id=:owner AND parent_id=:parent AND request_id=:request AND child_id IS NULL"), {"owner": owner, "parent": parent["id"], "request": requestId})
                    raise
                with conn.begin():
                    conn.execute(text("UPDATE af_delegation_links SET child_id=:child WHERE owner_id=:owner AND parent_id=:parent AND request_id=:request"), {"child": task["id"], "owner": owner, "parent": parent["id"], "request": requestId})
                link["child_id"] = task["id"]
                self.store.event(task["id"], "delegation_bound", "Immutable child bound before native submission", binding)
        receipt = None
        if fresh:
            try:
                # Cancellation may have landed after metadata commit. If no
                # native submission started, rejecting is a known safe outcome.
                self._mandate(owner, self.store.task(parent["id"], owner), creating=True)
            except HTTPException:
                self.store.request_cancel(task["id"])
                self.store.admission_failed(task["id"], "Ancestor authority ended before native submission")
                raise
            try:
                receipt = await self.bridge.submit({**plan, "task_id": task["id"]}, owner, native_request)
                self.store.accept(task["id"], receipt["run_id"])
                self.store.event(task["id"], "native_accepted", "Independent native child ticket accepted", {"runId": receipt["run_id"]})
            except HTTPException as error:
                if error.status_code < 500:
                    self.store.admission_failed(task["id"], "Native child admission rejected")
                    raise
                self.store.admission_unknown(task["id"])
            except Exception:
                self.store.admission_unknown(task["id"])
        elif not task.get("run_id") and task["admission"] != "rejected":
            receipt = await self.bridge.find_run(task["id"], owner)
            if receipt:
                self.store.accept(task["id"], receipt["run_id"])
            else:
                self.store.admission_unknown(task["id"])
        task = self.store.task(task["id"], owner)
        if task.get("run_id") and receipt is None:
            receipt = {"run_id": task["run_id"], "session_id": task["id"]}
        # A concurrent cascade may have marked this reservation while HTTP was
        # in flight. Honor it against the newly acknowledged ticket as well.
        if task["cancel_requested"] and task.get("run_id"):
            if str(self._native(task).get("status", "")).lower() not in TERMINAL:
                await self.bridge.cancel_run(task["run_id"], task["id"], owner)
        return {"childTask": task, "receipt": receipt, "link": link, "duplicate": duplicate}

    def _descendants(self, parent_id: str) -> list[dict[str, Any]]:
        return self.store.sql("""WITH RECURSIVE descendants AS (
            SELECT * FROM af_delegation_links WHERE parent_id=:parent
            UNION ALL SELECT link.* FROM af_delegation_links link JOIN descendants d ON link.parent_id=d.child_id
            ) SELECT * FROM descendants ORDER BY depth,created_at""", parent=parent_id)

    async def _facts(self, task: dict[str, Any]) -> dict[str, Any]:
        snapshot, unavailable = {}, False
        if task.get("run_id"):
            try:
                snapshot = await self.bridge.detail(task["run_id"], task["id"], task["owner_id"])
            except HTTPException as error:
                if error.status_code < 500:
                    raise
                unavailable = True
        native = snapshot.get("queue") or snapshot.get("job") or {}
        raw = str(native.get("status") or (snapshot.get("run") or snapshot).get("status") or "").lower().removeprefix("runstatus.")
        effects = self.store.effects(task["id"])
        unresolved_effect = any(effect["status"] == "UNKNOWN" for effect in effects)
        # A reserved effect during known native computation is in flight. It
        # retains capacity, but becomes externally UNKNOWN after native work
        # stops without a confirmed result/cleanup.
        unknown = unavailable or (unresolved_effect and raw != "running") or (not task.get("run_id") and task["admission"] != "rejected")
        failed = task["admission"] == "rejected" or raw in {"failed", "error"} or self.store.has_failures(task["id"])
        known_rejected_without_ticket = task["admission"] == "rejected" and not task.get("run_id")
        stopped = not unknown and not unresolved_effect and (raw in TERMINAL or known_rejected_without_ticket)
        return {"taskId": task["id"], "ownerId": task["owner_id"], "planId": task["plan_id"], "runId": task.get("run_id"),
                "admission": task["admission"], "nativeStatus": raw or None, "snapshot": snapshot, "effects": effects,
                "cancelRequested": task["cancel_requested"], "unknown": unknown, "failed": failed, "pending": not stopped, "stopped": stopped}

    async def children(self, owner: str, parentid: str) -> list[dict[str, Any]]:
        self.auth.require(owner, "read")
        parent = self.store.task(parentid, owner)
        links = self.store.sql("SELECT * FROM af_delegation_links WHERE parent_id=:parent ORDER BY created_at", parent=parent["id"])
        return [await self._linked_facts(owner, link) for link in links]

    async def _linked_facts(self, owner: str, link: dict[str, Any]) -> dict[str, Any]:
        if link["owner_id"] != owner:
            raise HTTPException(403, "Delegation link owner mismatch")
        if link["child_id"] is None:
            return {"taskId": None, "link": link, "unknown": True, "failed": False, "pending": True, "stopped": False, "nativeStatus": None, "effects": []}
        return {**await self._facts(self.store.task(link["child_id"], owner)), "link": link}

    async def inspect_group(self, owner: str, parentid: str) -> dict[str, Any]:
        self.auth.require(owner, "read")
        parent = self.store.task(parentid, owner)
        children = [await self._linked_facts(owner, link) for link in self._descendants(parent["id"])]
        parent_facts = await self._facts(parent)
        all_stopped = parent_facts["stopped"] and all(child["stopped"] for child in children)
        root_id, _ = self._ancestry(parent)
        if parent["id"] == root_id and all_stopped:
            self.store.sql("UPDATE af_delegation_roots SET reclaimed=TRUE WHERE root_id=:root", root=root_id)
        return {"parent": parent_facts, "children": children, "pending": any(child["pending"] for child in children),
                "unknown": parent_facts["unknown"] or any(child["unknown"] for child in children), "allStopped": all_stopped}

    async def cascade_cancel(self, owner: str, parentid: str) -> dict[str, Any]:
        self.auth.require(owner, "run")
        parent = self.store.task(parentid, owner)
        root_id, _ = self._ancestry(parent)
        with self._root_lock(root_id):
            links = self._descendants(parent["id"])
            tasks = [parent, *(self.store.task(link["child_id"], owner) for link in links if link["child_id"])]
            for task in tasks:
                self.store.request_cancel(task["id"])
        requested, errors = [], []
        for task in tasks:
            task = self.store.task(task["id"], owner)
            if not task.get("run_id"):
                continue  # Unacknowledged admission retains capacity/UNKNOWN.
            try:
                native = self._native(task)
                if str(native.get("status", "")).lower() not in TERMINAL:
                    await self.bridge.cancel_run(task["run_id"], task["id"], owner)
                    requested.append(task["id"])
            except HTTPException as error:
                errors.append({"taskId": task["id"], "status": error.status_code})
                self.store.event(task["id"], "cascade_cancel_pending", "Native cancellation remains unconfirmed", {"code": error.status_code})
        return {"requested": requested, "errors": errors, "group": await self.inspect_group(owner, parent["id"])}

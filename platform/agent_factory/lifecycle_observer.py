"""Bounded cleanup observation over the existing native Factory execution owner.

This service never submits, resumes, retries or claims work. It has no HTTP
ingress and issues no credentials. Only an exact persisted Factory/native
binding permits the public native cancellation APIs. Signal delivery is not
stop proof: running/missing tickets and unresolved effects retain capacity.
With Agno's default in-memory cancellation manager, running signals reach this
process only; cross-replica stop remains unproven without existing coordination.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Callable

from agno.agent import Agent
from agno.db.base import SessionType
from fastapi import HTTPException
from sqlalchemy import text

from .store import effect_unresolved, runtime_custody_held


TERMINAL = {"completed", "cancelled", "failed"}


class _FinalizationPending(Exception):
    pass


class FactoryLifecycleObserver:
    def __init__(self, store: Any, auth: Any, native_db: Any, worker_getter: Callable[[], Any],
                 *, interval: float = .5, batch_limit: int = 24):
        if not .05 <= interval <= 60 or not 1 <= batch_limit <= 100:
            raise ValueError("Lifecycle observation requires a bounded interval and batch")
        self.store, self.auth, self.native_db = store, auth, native_db
        self.worker_getter, self.interval, self.batch_limit = worker_getter, interval, batch_limit
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._tick_lock = asyncio.Lock()
        self.last_result: dict[str, Any] = {}
        self.last_error_type: str | None = None
        self._cursor = ""

    async def recover_admission(self, task: dict) -> dict:
        if task.get('run_id'):
            return task
        if task['admission'] != 'rejected':
            receipt = await self.store.delegation.bridge.find_original_run(task['id'], task['owner_id'])
            if receipt:
                candidate = {**task, 'run_id': receipt['run_id']}
                try:
                    await asyncio.to_thread(self._binding, candidate)
                except ValueError as error:
                    raise HTTPException(409, "Original native admission does not match the task") from error
                self.store.accept(task['id'], receipt['run_id'])
        return self.store.task(task['id'], task['owner_id'])

    def _binding(self, task: dict, *, include_content: bool = False) -> dict | None:
        """Strict native read; caller must keep missing/mismatched work held."""
        plan = self.store.plan(task["plan_id"], task["owner_id"])
        if not task.get("run_id"):
            return None
        from .native_component import component_identity
        kind, component_id = component_identity(plan)
        ticket = self.native_db.get_job(task["run_id"], strict=True)
        expected = {"id": task["run_id"], "session_id": task["id"], "user_id": task["owner_id"],
                    "component_type": kind, "component_id": component_id}
        if not ticket or any(ticket.get(key) != value for key, value in expected.items()) or ticket.get("job_type", "run") != "run":
            raise ValueError("Native ticket differs from the persisted Factory execution binding")
        key = hashlib.sha256(json.dumps({"owner": task["owner_id"], "task": task["id"], "request": task["request_id"]},
                                       sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if ticket.get("idempotency_key") != key:
            raise ValueError("Native admission key differs from the original Factory intent")
        envelope = {"plan_ref": plan["id"], "user_id": task["owner_id"], "task_id": task["id"], "request_id": task["request_id"]}
        state = (ticket.get("payload") or {}).get("kwargs", {}).get("session_state")
        if isinstance(state, str):
            state = json.loads(state)
        session = self.native_db.get_session(task["id"], session_type=SessionType.WORKFLOW if kind == "workflow" else SessionType.AGENT, user_id=task["owner_id"])
        native_status = None
        requirements = []
        content = None
        if session is not None:
            if session.user_id != task["owner_id"] or getattr(session, kind + "_id", None) != component_id:
                raise ValueError("Native session differs from its Factory owner/executor")
            runs = [run for run in session.runs or [] if run.run_id == task["run_id"] and getattr(run, kind + "_id", None) == component_id]
            if len(runs) != 1 and not (not runs and ticket["status"] == "cancelled"):
                raise ValueError("Exact persisted native Factory run is not observable")
            if runs:
                native_status = str(getattr(runs[0].status, "value", runs[0].status)).lower()
                requirements = runs[0].to_dict().get("requirements") or []
                if include_content:
                    content = runs[0].to_dict().get("content")
            if state is None:
                state = (session.session_data or {}).get("session_state")
        if not isinstance(state, dict) or state.get("factory_envelope") != envelope:
            raise ValueError("Native payload/session lacks the exact immutable Factory envelope")
        return {**ticket, "persistedRunStatus": native_status, "requirements": requirements,
                **({"content": content} if include_content else {})}

    def _group(self, root: dict) -> tuple[list[dict], list[dict]]:
        links = self.store.sql("SELECT * FROM af_delegation_links WHERE root_id=:root ORDER BY depth,created_at", root=root["id"])
        tasks, depths = [root], {root["id"]: 0}
        for link in links:
            if link["owner_id"] != root["owner_id"] or link["parent_id"] not in depths or link["depth"] != depths[link["parent_id"]] + 1:
                raise ValueError("Persisted descendant owner or ancestry differs from its root")
            if link["child_id"] is None:
                continue
            if link["child_id"] in depths:
                raise ValueError("Persisted delegation group repeats an ancestor")
            child = self.store.task(link["child_id"], root["owner_id"])
            plan = self.store.plan(child["plan_id"], root["owner_id"])
            if child["plan_id"] != link["plan_id"] or plan.get("delegation") != {
                    "rootTaskId": root["id"], "parentTaskId": link["parent_id"], "depth": link["depth"]}:
                raise ValueError("Persisted child plan differs from its immutable ancestor binding")
            tasks.append(child)
            depths[child["id"]] = link["depth"]
        return tasks, links

    def _reason(self, task: dict, ticket: dict | None) -> str | None:
        if task['body'].get('stoppedStatus') is not None:
            return None
        if task["cancel_requested"]:
            return "cancel-requested"
        if task["admission"] == "rejected":
            # A later metadata rejection does not erase an acknowledged native
            # ticket. Its exact binding was checked before this observation;
            # only native cleanup and positive stop proof can free capacity.
            return "admission-rejected"
        if self.store.has_failures(task["id"]):
            return "protected-failure"
        if ticket and ticket["status"] == "failed":
            return "native-failure"
        if ticket and ticket["status"] == "cancelled":
            return "native-ended"
        if ticket and ticket["status"] == "completed":
            # Native completion does not renew an execution grant. Its pending
            # descendants are observed independently below; their current
            # guards still validate ancestor grants before any further effect.
            # Group capacity remains held until every descendant stops.
            return None
        plan = self.store.plan(task["plan_id"], task["owner_id"])
        try:
            self.auth.require_member(task["owner_id"])
            envelope = {"plan_ref": plan["id"], "user_id": task["owner_id"],
                        "task_id": task["id"], "request_id": task["request_id"]}
            context = SimpleNamespace(session_id=task["id"], run_id=task.get("run_id"), user_id=task["owner_id"],
                                      session_state={"factory_envelope": envelope})
            if plan.get("delegation") and ticket is None:
                # The validated tree can contain a reservation before native
                # admission finishes. Absence of a ticket is uncertainty, not
                # revoked inherited review. The root is checked separately in
                # this same traversal, and any ancestor failure cascades here.
                # Current owner/config/material/receiver denials still apply;
                # native execution itself retains its full admission guards.
                # This reservation snapshot may become accepted while these
                # metadata checks run. Do not invent a native context carrying
                # its old None run ID: a current strict binding guard would
                # mistake admission progress for authority revocation. Exact
                # contexts remain mandatory for observed acknowledged tickets.
                for guard in self.store.execution_guards.values():
                    guard(task["owner_id"], plan, None, None)
            else:
                self.store.require_plan_execution(task["owner_id"], plan, run_context=context if ticket else None)
        except HTTPException as error:
            if error.status_code in {403, 409}:
                return "current-authority-ended"
            raise
        except PermissionError:
            return "current-authority-ended"
        return None

    def _mark_cancel(self, task: dict, reason: str) -> None:
        # Readers classify cleanup from both the flag and its failure provenance.
        # Publish them together so authority loss cannot look like user cancel.
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            changed = self.store.sql("UPDATE af_tasks SET cancel_requested=TRUE WHERE id=:id AND owner_id=:owner AND NOT cancel_requested RETURNING id",
                                     id=task["id"], owner=task["owner_id"])
            if changed:
                sessions = getattr(self.store, 'research_sessions', None)
                if sessions is not None:
                    sessions.mark_cancel(self.store, task['id'], reason=reason)
                if reason == "current-authority-ended":
                    self.store.event(task["id"], "protected_denied", "Current authority ended; existing owned work requires cleanup",
                                     {"boundary": "lifecycle", "createsExecution": False})
                self.store.event(task["id"], "lifecycle_cleanup_requested", "Trusted lifecycle observation requested existing task cleanup",
                                 {"reason": reason, "nativeRunId": task.get("run_id"), "createsExecution": False})

    async def _cancel_bound(self, task: dict) -> None:
        ticket = self._binding(self.store.task(task["id"], task["owner_id"]))
        # Detached experiment supervision belongs to the same persisted task.
        # Cleanup validates its original handle/source/limits even after grants
        # end. Native completion alone cannot prove that tree stopped.
        if not ticket or ticket["status"] in TERMINAL:
            return
        worker = self.worker_getter()
        if worker is not None:
            # Verify the attached native worker reads the same exact ticket,
            # before its public run-row-first, waiting-ticket cancellation.
            worker_ticket = await worker.store.get_job(task["run_id"])
            for key in ("id", "session_id", "user_id", "component_type", "component_id", "idempotency_key"):
                if not worker_ticket or worker_ticket.get(key) != ticket.get(key):
                    raise ValueError("Attached native worker has a different execution binding")
            await worker.acancel_queued(task["run_id"])
        # Same public static native signal used by AgentOS's cancel route.
        # Its result acknowledges intent, never proves stop or releases quota.
        await Agent.acancel_run(task["run_id"])

    def _facts(self, task: dict, *, include_content: bool = False) -> dict:
        try:
            ticket = self._binding(task, include_content=True) if include_content else self._binding(task)
        except Exception as error:
            return {"taskId": task["id"], "stopped": False, "unknown": True, "errorType": type(error).__name__}
        effects_unknown = any(effect_unresolved(effect, self.store) for effect in self.store.effects(task["id"]))
        effects_unknown = effects_unknown or runtime_custody_held(self.store, task['id'])
        stopped = not effects_unknown and bool(ticket and ticket["status"] in TERMINAL or not ticket and task["admission"] == "rejected")
        return {"taskId": task["id"], "stopped": stopped,
                "unknown": (effects_unknown and (not ticket or ticket["status"] != "running"))
                    or ticket is None and task["admission"] != "rejected",
                "nativeStatus": ticket["status"] if ticket else None,
                "persistedRunStatus": ticket.get("persistedRunStatus") if ticket else None,
                "failed": (task["body"]["stoppedStatus"] == "failed" if task["body"].get("stoppedStatus") is not None
                           else self.store.has_failures(task["id"]) or bool(ticket and ticket["status"] == "failed")),
                "displayStatus": task["body"].get("stoppedStatus") or self._display_status(task, ticket, effects_unknown),
                **({"content": ticket.get("content")} if include_content and ticket and stopped else {})}

    def _subtree(self, owner: str, child_id: str):
        child = self.store.task(child_id, owner)
        root_id, _ = self.store.delegation._ancestry(child)
        tasks, links = self._group(self.store.task(root_id, owner))
        selected = {child_id}
        missing = False
        for link in links:
            if link['parent_id'] in selected:
                if link['child_id'] is None:
                    missing = True
                else:
                    selected.add(link['child_id'])
        return root_id, [task for task in tasks if task['id'] in selected], missing

    def _inspect_subtree(self, owner: str, child_id: str):
        root_id, _ = self.store.delegation._ancestry(self.store.task(child_id, owner))
        with self.store.delegation._root_lock(root_id):
            _, tasks, missing = self._subtree(owner, child_id)
            facts = {task['id']: self._facts(task, include_content=task['id'] == child_id) for task in tasks}
            return {'parent': facts[child_id], 'children': [fact for key, fact in facts.items() if key != child_id],
                    'unknown': missing or any(fact['unknown'] for fact in facts.values()),
                    'allStopped': not missing and all(fact['stopped'] for fact in facts.values())}

    async def inspect_subtree(self, owner: str, child_id: str):
        """Trusted original custody read, without including the waiting parent."""
        return await asyncio.to_thread(self._inspect_subtree, owner, child_id)

    async def cancel_subtree(self, owner: str, child_id: str):
        def mark():
            root_id, _ = self.store.delegation._ancestry(self.store.task(child_id, owner))
            with self.store.delegation._root_lock(root_id):
                _, tasks, _ = self._subtree(owner, child_id)
                for task in tasks:
                    self.store.request_cancel(task['id'])
                return tasks
        tasks = await asyncio.to_thread(mark)
        requested, errors = [], []
        for task in tasks:
            try:
                await self._cancel_bound(task)
                requested.append(task['id'])
            except Exception as error:
                errors.append({'taskId': task['id'], 'errorType': type(error).__name__})
        return {**await self.inspect_subtree(owner, child_id), 'requested': requested, 'errors': errors}

    def _display_status(self, task, ticket, effects_unknown):
        if task["admission"] == "rejected":
            return "failed"
        if ticket is None:
            return "unknown"
        # Match the detail projector: an ordinary in-flight effect is UNKNOWN
        # until its receipt arrives, but a verified running ticket stays running.
        # Once native execution pauses or ends, unresolved effects take priority.
        raw = ticket["status"] or ticket.get("persistedRunStatus") or "queued"
        if effects_unknown and raw != "running":
            return "unknown"
        if task["cancel_requested"] and raw not in {"cancelled", "canceled", "failed", "completed", "error"}:
            return "canceling"
        if raw == "paused":
            return "waiting_input" if any((item.get("tool_execution") or {}).get("requires_user_input")
                                           for item in ticket.get("requirements", [])) else "waiting_approval"
        return {"pending": "queued", "cancelled": "canceled", "error": "failed"}.get(raw, raw)

    def _summary_status(self, task, status):
        """Applications may project their persisted wait state for the summary."""
        return status

    def _observe_summaries(self, root, facts):
        tasks, links = self._group(self.store.task(root["id"], root["owner_id"]))
        for task in tasks:
            fact = facts.get(task["id"])
            if fact is None:
                continue  # A child admitted after this observation awaits the next tick.
            if fact["groupStopped"]:
                continue  # Terminal observation already published under stop proof.
            status = fact.get("displayStatus", "unknown")
            descendants = [link for link in links if link["parent_id"] == task["id"]]
            children_unknown = any(not link["child_id"] or facts.get(link["child_id"], {}).get("unknown", True)
                                   for link in descendants)
            if status not in {"running", "canceling"} and (fact["unknown"] or children_unknown):
                status = "unknown"
            elif status == "completed" and descendants:
                status = "waiting_children"
            self.store.observe_summary(task, self._summary_status(task, status))

    async def _observe_application_waits(self, root):
        """Application observers may inspect existing work before core cleanup."""
        sessions = getattr(self.store, 'research_sessions', None)
        if sessions is not None:
            for task in self._group(root)[0]:
                await sessions.observe_waits(self, task)

    async def observe_root(self, identifier: str) -> dict:
        root = self.store.task(identifier)
        service = self.store.delegation
        if service is None:
            raise ValueError("Trusted lifecycle cleanup requires persisted delegation bindings")
        errors = []
        for task in self._group(root)[0]:
            try:
                await self.recover_admission(task)
            except Exception as error:
                errors.append({'taskId': task['id'], 'errorType': type(error).__name__})
        root = self.store.task(identifier)
        await self._observe_application_waits(root)
        requested, phase_errors = await asyncio.to_thread(self._request_cleanup, root)
        errors.extend(phase_errors)
        for task in requested.values():
            try:
                await self._cancel_bound(task)
            except Exception as error:
                errors.append({"taskId": task["id"], "errorType": type(error).__name__})
        facts = await asyncio.to_thread(self._observe_stopped, root)
        await asyncio.to_thread(self._observe_summaries, root, facts)
        return {"rootTaskId": root["id"], "allStopped": facts[root["id"]]["groupStopped"],
                "requested": list(requested), "facts": list(facts.values()), "errors": errors}

    def _request_cleanup(self, root: dict) -> tuple[dict, list]:
        """Keep fresh synchronous authority and its complete root lock off the loop.

        Cancellation can leave this read/cleanup-marking phase finishing in its
        thread. It cannot submit work or reclaim capacity; native cancellation
        and positive stop observation remain separate awaited phases.
        """
        service = self.store.delegation
        requested: dict[str, dict] = {}
        errors = []
        with service._root_lock(root["id"]):
            root = self.store.task(root["id"], root["owner_id"])
            tasks, links = self._group(root)
            for task in tasks:
                try:
                    reason = self._reason(task, self._binding(task))
                except Exception as error:
                    errors.append({"taskId": task["id"], "errorType": type(error).__name__})
                    continue
                if reason:
                    affected = {task["id"]}
                    for link in links:
                        if link["parent_id"] in affected and link["child_id"]:
                            affected.add(link["child_id"])
                    for current in tasks:
                        if current["id"] in affected:
                            self._mark_cancel(current, reason)
                            requested[current["id"]] = current
        return requested, errors

    def _observe_stopped(self, root: dict) -> dict:
        # Acquire/release the session advisory lock in the same thread. Never
        # carry its SQLAlchemy connection across an asynchronous suspension.
        service = self.store.delegation
        with service._root_lock(root["id"]):
            tasks, links = self._group(self.store.task(root["id"], root["owner_id"]))
            facts = {task["id"]: self._facts(task) for task in tasks}
            for task in reversed(tasks):
                direct = [link for link in links if link["parent_id"] == task["id"]]
                stopped = facts[task["id"]]["stopped"] and all(link["child_id"] and facts[link["child_id"]].get("groupStopped") for link in direct)
                facts[task["id"]]["groupStopped"] = bool(stopped)
                facts[task["id"]]["groupFailed"] = facts[task["id"]].get("failed", False) or any(
                    link["child_id"] and facts[link["child_id"]].get("groupFailed") for link in direct)
                if stopped:
                    # A protected failure can appear after the cleanup-request
                    # phase. Record its cancellation provenance before making
                    # the root terminal (and therefore absent from future ticks).
                    task = self.store.task(task["id"], task["owner_id"])
                    reason = self._reason(task, self._binding(task))
                    if reason:
                        self._mark_cancel(task, reason)
                    task = self.store.task(task["id"], task["owner_id"])
                    facts[task["id"]].update(self._facts(task))
                    stopped = facts[task["id"]]["stopped"] and all(
                        link["child_id"] and facts[link["child_id"]].get("groupStopped") for link in direct)
                    facts[task["id"]]["groupStopped"] = bool(stopped)
                    facts[task["id"]]["groupFailed"] = facts[task["id"]].get("failed", False) or any(
                        link["child_id"] and facts[link["child_id"]].get("groupFailed") for link in direct)
                    if stopped:
                        status = "failed" if facts[task["id"]]["groupFailed"] else "canceled" if task["cancel_requested"] or facts[task["id"]].get("nativeStatus") == "cancelled" else "completed"
                        self.store.observed(task, status, True)
            if facts[root["id"]]["groupStopped"]:
                self.store.sql("UPDATE af_delegation_roots SET reclaimed=TRUE WHERE root_id=:id AND owner_id=:owner", id=root["id"], owner=root["owner_id"])
        return facts

    async def tick(self) -> dict:
        async with self._tick_lock:
            process_runtime = getattr(self.store, "process_runtime", None)
            process_results = await process_runtime.tick() if process_runtime is not None else []
            query = """SELECT task.id FROM af_tasks task WHERE NOT EXISTS(
                SELECT 1 FROM af_delegation_links own_link WHERE own_link.child_id=task.id)
                AND (NOT task.terminal OR EXISTS(SELECT 1 FROM af_delegation_links link JOIN af_tasks child ON child.id=link.child_id
                WHERE link.root_id=task.id AND NOT child.terminal)) AND task.id>:after ORDER BY task.id LIMIT :limit"""
            roots = self.store.sql(query, after=self._cursor, limit=self.batch_limit)
            if not roots and self._cursor:
                self._cursor = ""
                roots = self.store.sql(query, after="", limit=self.batch_limit)
            self._cursor = roots[-1]["id"] if len(roots) == self.batch_limit else ""
            groups, errors = [], []
            for row in roots:
                try:
                    groups.append(await self.observe_root(row["id"]))
                except Exception as error:
                    errors.append({"rootTaskId": row["id"], "errorType": type(error).__name__})
                await asyncio.sleep(0)
            self.last_result = {"groups": groups, "errors": errors, "processLeases": process_results,
                                "nativeOwner": "agno", "createsExecution": False}
            return self.last_result

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
                self.last_error_type = None
            except Exception as error:
                self.last_error_type = type(error).__name__
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except TimeoutError:
                pass

    async def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="factory-lifecycle-cleanup")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    @asynccontextmanager
    async def lifespan(self, app: Any):
        await self.start()
        try:
            yield
        finally:
            await self.stop()

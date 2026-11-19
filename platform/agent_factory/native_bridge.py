"""Public native AgentOS HTTP lifecycle over the one registered durable executor."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import re
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
import httpx
from agno.db.base import SessionType
from agno.db.utils import deserialize_run, merge_runs_table_with_legacy_blob
from sqlalchemy import select

from .auth import EXECUTOR_ID
from .native_stream import submit_stream


class NativeAdmissionRejected(HTTPException):
    """The native queue explicitly declined this submission before insertion."""


def session_for_run(db, session_id, user_id, run_id):
    """Agno's get_session loads every run. Observe only the requested persisted run."""
    sessions = db._get_table(table_type="sessions")
    if sessions is None:
        return None
    runs = db._get_table(table_type="runs")
    query = select(sessions).where(sessions.c.session_id == session_id, sessions.c.user_id == user_id)
    if runs is not None:
        query = query.add_columns(runs.c.run_data).select_from(sessions.outerjoin(runs,
            (runs.c.session_id == sessions.c.session_id) & (runs.c.run_id == run_id)))
    with db.db_engine.connect() as conn:
        row = conn.execute(query).mappings().first()
    if row is None:
        return None
    record = dict(row)
    data = record.pop('run_data', None)
    history = merge_runs_table_with_legacy_blob([data] if data is not None else [], record.get('runs'))
    record['runs'] = [item for item in history if item.get('run_id') == run_id]
    return record


class NativeBridge:
    def __init__(self, settings: Any, native_db: Any, auth: Any, *, store: Any = None):
        self.settings, self.native_db, self.auth = settings, native_db, auth
        self.store = store
        self._app: Any = None
        self._component_resolver: Callable[[str, str], Mapping[str, Any]] | None = None

    def native_session_id(self, task_id: str, user_id: str) -> str:
        return self.store.native_session_id(self.store.task(task_id, user_id)) if self.store is not None else task_id

    def configure_components(self, resolver: Callable[[str, str], Mapping[str, Any]]) -> None:
        """Install the operator's immutable task/plan resolver, never user routing."""
        if not callable(resolver) or self._component_resolver is not None:
            raise ValueError("Native component resolver is invalid or already configured")
        self._component_resolver = resolver

    def _component(self, session_id: str, user_id: str) -> dict[str, Any]:
        if self._component_resolver is None:
            return {"kind": "agent", "id": EXECUTOR_ID}
        value = self._component_resolver(session_id, user_id)
        if (not isinstance(value, Mapping) or set(value) != {"kind", "id", "revision", "sha256"}
                or value['kind'] not in {'agent', 'workflow'}
                or not isinstance(value['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value['id'])
                or not isinstance(value['revision'], str) or not 1 <= len(value['revision']) <= 128
                or not isinstance(value['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['sha256'])
                or value['kind'] == 'agent' and value['id'] != EXECUTOR_ID):
            raise HTTPException(403, "Native component binding is invalid")
        return dict(value)

    def _component_path(self, run_id: str, component: Mapping[str, Any]) -> str:
        return f"/{component['kind']}s/{quote(component['id'], safe='')}/runs/{quote(run_id, safe='')}"

    @staticmethod
    def _ticket(ticket: Any, run_id: str, session_id: str, user_id: str, component: Mapping[str, Any]) -> None:
        if ticket is not None and (not isinstance(ticket, dict) or ticket.get('id') != run_id
                or ticket.get('session_id') != session_id or ticket.get('user_id') != user_id
                or ticket.get('component_type') != component['kind'] or ticket.get('component_id') != component['id']):
            raise HTTPException(403, "Native ticket identity differs from the task")

    def attach(self, app: Any) -> None:
        # Main owns the native lifespan/worker. This bridge never starts a second
        # serve process, queue, event loop or nested child agent run.
        if self._app is not None and self._app is not app:
            raise RuntimeError("Native bridge is already attached")
        self._app = app

    async def _request(self, method: str, path: str, user_id: str, **kwargs: Any) -> dict[str, Any]:
        if self._app is None:
            raise RuntimeError("Native HTTP application has not been attached")
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {self.auth._issue_native_token(user_id)}"}
        streaming = method == "POST" and path.endswith("/runs") and kwargs.get("data", {}).get("stream") == "true"
        try:
            if streaming:
                response = await submit_stream(self._app, method, path, headers=headers, data=kwargs['data'])
            else:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self._app),
                                             base_url="http://native.agent-factory", timeout=30) as client:
                    response = await client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as error:
            raise HTTPException(503, {"code": "NATIVE_ACK_UNKNOWN", "message": "Native acknowledgement timed out; reconcile the stored task before retrying"}) from error
        if streaming and response.status_code < 400:
            return {}  # Submission resolves the exact durable ticket below.
        try:
            body = response.json()
        except ValueError as error:
            raise HTTPException(502, "Native lifecycle returned an invalid response") from error
        if (method == "POST" and path.endswith("/runs") and response.status_code == 429
                and body == {"message": "Job queue is full", "code": "REQUEST_REJECTED"}):
            raise NativeAdmissionRejected(429, body["message"])
        if response.status_code >= 400:
            raise HTTPException(response.status_code, body.get("detail", body))
        if not isinstance(body, dict):
            raise HTTPException(502, "Native lifecycle returned an unexpected response")
        return body

    async def submit(self, plan: Mapping[str, Any], user_id: str, request_id: str) -> dict[str, Any]:
        if not request_id or len(request_id) > 200:
            raise HTTPException(400, "A bounded request ID is required")
        plan_ref = plan.get("id")
        task_id = plan.get("task_id")
        owner = plan.get("ownerId", plan.get("owner_id", plan.get("user_id", plan.get("owner"))))
        if owner != user_id or not isinstance(plan_ref, str):
            raise HTTPException(403, "Plan ownership does not match the submitting user")
        try:
            task_id = str(UUID(str(task_id)))
        except ValueError as error:
            raise HTTPException(400, "A persisted task UUID is required") from error
        component = self._component(task_id, user_id)
        session_id = self.native_session_id(task_id, user_id)
        declared = plan.get("nativeComponent")
        if ((component["kind"] == "workflow" or declared is not None)
                and declared != (component if "revision" in component else None)):
            raise HTTPException(403, "Plan native component differs from original task binding")
        envelope = {"plan_ref": plan_ref, "user_id": user_id, "task_id": task_id, "request_id": request_id}
        native_key = hashlib.sha256(json.dumps({"owner": user_id, "task": task_id, "request": request_id},
                                              sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        accepted = await self._request("POST", f"/{component['kind']}s/{quote(component['id'], safe='')}/runs", user_id,
            headers={"Idempotency-Key": native_key},
            data={"message": json.dumps(plan.get("inputValues", {}), separators=(",", ":")) if component["kind"] == "workflow" else plan["normalizedGoal"], "session_id": session_id,
                  "background": "true", "stream": "true" if component["kind"] == "agent" else "false",
                  "session_state": json.dumps({"factory_envelope": envelope}, separators=(",", ":"))})
        if component['kind'] == 'workflow':
            return accepted
        original = await self.find_original_run(task_id, user_id, idempotency_key=native_key)
        if original is None or original.get('queue') is None:
            raise HTTPException(503, "NATIVE_ACK_UNKNOWN: accepted stream has no matching durable ticket")
        self._ticket(original['queue'], original['run_id'], session_id, user_id, component)
        return original

    @staticmethod
    def _run_path(run_id: str) -> str:
        return f"/agents/{EXECUTOR_ID}/runs/{quote(run_id, safe='')}"

    async def detail(self, run_id: str, session_id: str, user_id: str, *, native_session: str | None = None) -> dict[str, Any]:
        component = self._component(session_id, user_id)
        session_id = native_session if native_session is not None else self.native_session_id(session_id, user_id)
        kind, identifier = component["kind"], component["id"]
        try:
            result = await self._request("GET", self._component_path(run_id, component), user_id, params={"session_id": session_id})
        except HTTPException as error:
            if error.status_code != 403 and not (kind == "workflow" and error.status_code == 404):
                raise
            # The native session/run HTTP handler fetches the entire history before filtering by ID.
            self.auth.require_member(user_id)
            session = session_for_run(self.native_db, session_id, user_id, run_id)
            if session is None:
                raise HTTPException(404, f"Session with ID {session_id} not found")
            exact = session["runs"]
            if not exact:
                raise HTTPException(404, f"Run with ID {run_id} not found in session {session_id}")
            if session.get(kind + "_id") != identifier or exact[0].get(kind + "_id") != identifier:
                raise HTTPException(403, "Native session or run differs from the task executor")
            matching = [run for run in exact if run.get(kind + "_id") == identifier]
            if len(matching) != 1:
                raise HTTPException(404, "Exact native owner-scoped run not found")
            result = {**deserialize_run(kind, matching[0]).to_dict(), "readOnly": True}
        ticket = self.native_db.get_job(run_id)
        self._ticket(ticket, run_id, session_id, user_id, component)
        result["queue"] = jsonable_encoder(ticket)
        return result

    async def find_original_run(self, session_id: str, user_id: str, *, idempotency_key: str | None = None) -> dict[str, Any] | None:
        """Read original admission; callers validate the ticket before binding it."""
        component = self._component(session_id, user_id)
        task_id = session_id
        task = self.store.task(task_id, user_id) if self.store is not None else None
        session_id = self.store.native_session_id(task) if task is not None else task_id
        kind, identifier = component["kind"], component["id"]
        session_type = SessionType.WORKFLOW if kind == "workflow" else SessionType.AGENT
        try:
            engine = self.native_db.db_engine
            # Agno reuses the resolved table definition. Ticket rows are read on every lookup.
            table = self.native_db._get_table(table_type="jobs")
            tickets = []
            if table is not None:
                with engine.connect() as connection:
                    query = select(table).where(
                        table.c.session_id == session_id, table.c.user_id == user_id,
                        table.c.component_type == kind, table.c.component_id == identifier,
                    )
                    if idempotency_key is not None:
                        query = query.where(table.c.idempotency_key == idempotency_key)
                    elif task is not None:
                        native_key = hashlib.sha256(json.dumps({'owner': user_id, 'task': task_id,
                            'request': task['request_id']}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                        query = query.where(table.c.idempotency_key == native_key)
                    tickets = [dict(row) for row in connection.execute(query.limit(2)).mappings()]
            if len(tickets) > 1:
                raise HTTPException(409, "NATIVE_AMBIGUOUS_ADMISSION: multiple native tickets for one task")
            if tickets:
                ticket = tickets[0]
                return {"run_id": ticket["id"], "session_id": session_id,
                        "status": ticket["status"], "queue": jsonable_encoder(ticket)}
            if idempotency_key is not None or session_id != task_id:
                # Other conversation turns do not prove this task was admitted.
                return None
            session = self.native_db.get_session(session_id, session_type=session_type, user_id=user_id)
            if session is None or getattr(session, kind + "_id", None) != identifier or session.user_id != user_id:
                return None
            runs = [run for run in session.runs or [] if getattr(run, kind + "_id", None) == identifier]
            if len(runs) > 1:
                raise HTTPException(409, "NATIVE_AMBIGUOUS_ADMISSION: multiple native runs for one task")
            if not runs:
                return None
            return {"run_id": runs[0].run_id, "session_id": session_id}
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(503, "Native admission reconciliation is unavailable") from error

    async def continue_run(self, run_id: str, session_id: str, user_id: str,
                           requirements: list[Any], *, command_proof: dict[str, str] | None = None) -> dict[str, Any]:
        # The public native route accepts serialized ToolExecution objects, while
        # detail returns RunRequirement wrappers. Keep the original execution IDs.
        component = self._component(session_id, user_id)
        session_id = self.native_session_id(session_id, user_id)
        if component['kind'] == 'workflow':
            steps = [item.to_dict() if hasattr(item, 'to_dict') else item for item in requirements]
            if not steps or any(not isinstance(item, dict) for item in steps):
                raise HTTPException(400, "Native workflow requirements must be objects")
            return await self._request("POST", self._component_path(run_id, component) + "/continue", user_id,
                data={"session_id": session_id, "background": "true", "stream": "false",
                      "step_requirements": json.dumps(steps)})
        tools = []
        for requirement in requirements:
            value = requirement.to_dict() if hasattr(requirement, "to_dict") else requirement
            if not isinstance(value, dict):
                raise HTTPException(400, "Native continuation requirements must be objects")
            execution = value.get("tool_execution", value)
            if not isinstance(execution, dict) or not execution.get("tool_call_id"):
                raise HTTPException(400, "A native tool execution ID is required")
            tools.append(execution)
        data = {"session_id": session_id, "background": "true", "stream": "false", "tools": json.dumps(tools)}
        if command_proof is not None:
            data["metadata"] = json.dumps({"factoryControlCommand": command_proof})
        return await self._request("POST", self._run_path(run_id) + "/continue", user_id, data=data)


    async def cancel_run(self, run_id: str, session_id: str, user_id: str) -> dict[str, Any]:
        component = self._component(session_id, user_id)
        session_id = self.native_session_id(session_id, user_id)
        return await self._request("POST", self._component_path(run_id, component) + "/cancel", user_id,
                                   params={"session_id": session_id})

"""Public native AgentOS HTTP lifecycle over the one registered durable executor."""
from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
import hashlib
import json
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
import httpx
from agno.db.base import SessionType
from sqlalchemy import MetaData, Table, inspect, select

from .auth import EXECUTOR_ID

INTERNAL_NATIVE: ContextVar[bool] = ContextVar("factory_internal_native", default=False)


class NativeBridge:
    def __init__(self, settings: Any, native_db: Any, auth: Any):
        self.settings, self.native_db, self.auth = settings, native_db, auth
        self._app: Any = None

    def attach(self, app: Any) -> None:
        # Main owns the native lifespan/worker. This bridge never starts a second
        # serve process, queue, event loop or nested child agent run.
        if self._app is not None and self._app is not app:
            raise RuntimeError("Native bridge is already attached")
        self._app = app

    async def _request(self, method: str, path: str, user_id: str, **kwargs: Any) -> dict[str, Any]:
        if self._app is None:
            raise RuntimeError("Native HTTP application has not been attached")
        self.auth.require(user_id, "read" if method == "GET" else "run")
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {self.auth._issue_native_token(user_id)}"}
        trusted_context = INTERNAL_NATIVE.set(True)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self._app),
                                         base_url="http://native.agent-factory", timeout=30) as client:
                response = await client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as error:
            raise HTTPException(503, {"code": "NATIVE_ACK_UNKNOWN", "message": "Native acknowledgement timed out; reconcile the stored task before retrying"}) from error
        finally:
            INTERNAL_NATIVE.reset(trusted_context)
        try:
            body = response.json()
        except ValueError as error:
            raise HTTPException(502, "Native lifecycle returned an invalid response") from error
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
            session_id = str(UUID(str(task_id)))
        except ValueError as error:
            raise HTTPException(400, "A persisted task UUID is required") from error
        envelope = {"plan_ref": plan_ref, "user_id": user_id, "task_id": session_id, "request_id": request_id}
        native_key = hashlib.sha256(json.dumps({"owner": user_id, "task": session_id, "request": request_id},
                                              sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return await self._request("POST", f"/agents/{EXECUTOR_ID}/runs", user_id,
            headers={"Idempotency-Key": native_key},
            data={"message": "Execute the persisted factory plan.", "session_id": session_id,
                  "background": "true", "stream": "false",
                  "session_state": json.dumps({"factory_envelope": envelope}, separators=(",", ":"))})

    @staticmethod
    def _run_path(run_id: str) -> str:
        return f"/agents/{EXECUTOR_ID}/runs/{quote(run_id, safe='')}"

    async def detail(self, run_id: str, session_id: str, user_id: str) -> dict[str, Any]:
        try:
            result = await self._request("GET", self._run_path(run_id), user_id, params={"session_id": session_id})
        except HTTPException as error:
            if error.status_code != 403:
                raise
            # Pinned Agno's agent-run GET requires run rights. Its native session
            # GET is the supported owner-scoped read path; no admin token is used.
            result = await self._request("GET", f"/sessions/{quote(session_id, safe='')}/runs/{quote(run_id, safe='')}",
                user_id, params={"type": "agent", "db_id": self.native_db.id})
            if result.get("run_id") != run_id or result.get("agent_id") != EXECUTOR_ID:
                raise HTTPException(403, "Native session read returned a different executor/run")
            session = self.native_db.get_session(session_id, session_type=SessionType.AGENT, user_id=user_id)
            if session is None or session.agent_id != EXECUTOR_ID or session.user_id != user_id:
                raise HTTPException(403, "Native session ownership differs from the task")
            exact = [run for run in session.runs or [] if run.run_id == run_id and run.agent_id == EXECUTOR_ID]
            if len(exact) != 1:
                raise HTTPException(404, "Exact native owner-scoped run not found")
            # Native session RunSchema omits requirements. Enrich only after its
            # HTTP ownership check, preserving persisted native question types.
            result = {**exact[0].to_dict(), "readOnly": True}
        # Only query the ticket after native HTTP ownership/resource checks succeed.
        # Preserve requirements and the actual status; no synthetic status translation.
        result["queue"] = jsonable_encoder(self.native_db.get_job(run_id))
        return result

    async def find_run(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        """Reconcile an uncertain acknowledgement by exact native owner/session reads.

        Queue commit can precede the session's accepted-run row. Read the native
        ticket first, without replaying submission or changing native queue state.
        """
        self.auth.require(user_id, "read")
        try:
            engine = self.native_db.db_engine
            table_name = self.native_db.job_table_name
            schema = getattr(self.native_db, "db_schema", None)
            tickets = []
            if inspect(engine).has_table(table_name, schema=schema):
                table = Table(table_name, MetaData(), schema=schema, autoload_with=engine)
                with engine.connect() as connection:
                    tickets = [dict(row) for row in connection.execute(select(table).where(
                        table.c.session_id == session_id, table.c.user_id == user_id,
                        table.c.component_type == "agent", table.c.component_id == EXECUTOR_ID,
                    ).limit(2)).mappings()]
            if len(tickets) > 1:
                raise HTTPException(409, "NATIVE_AMBIGUOUS_ADMISSION: multiple native tickets for one task")
            if tickets:
                ticket = tickets[0]
                return {"run_id": ticket["id"], "session_id": session_id,
                        "status": ticket["status"], "queue": jsonable_encoder(ticket)}
            session = self.native_db.get_session(session_id, session_type=SessionType.AGENT, user_id=user_id)
            if session is None or session.agent_id != EXECUTOR_ID:
                return None
            runs = [run for run in session.runs or [] if run.agent_id == EXECUTOR_ID]
            if len(runs) > 1:
                raise HTTPException(409, "NATIVE_AMBIGUOUS_ADMISSION: multiple native runs for one task")
            if not runs:
                return None
            return await self.detail(runs[0].run_id, session_id, user_id)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(503, "Native admission reconciliation is unavailable") from error

    async def continue_run(self, run_id: str, session_id: str, user_id: str,
                           requirements: list[Any], *, command_proof: dict[str, str] | None = None) -> dict[str, Any]:
        # The public native route accepts serialized ToolExecution objects, while
        # detail returns RunRequirement wrappers. Keep the original execution IDs.
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

    async def continue_approved_run(self, run_id: str, session_id: str, user_id: str,
                                    requirements: list[Any], *, command_proof: dict[str, str],
                                    original_proof: dict[str, str], tools_sha256: str,
                                    paused_requirements_sha256: str) -> dict[str, Any]:
        """One repair through the public queue seam; NEVER detached HTTP fallback."""
        from agno.agent import Agent
        from agno.agent.factory import AgentFactory
        from agno.agent.remote import RemoteAgent
        from agno.os.job_queue import acontinue_via_queue, payload_is_queueable
        from .factory_api import native_requirements
        from .store import digest
        self.auth.require(user_id, "run")
        worker = getattr(getattr(self._app, "state", None), "queue_worker", None)
        if worker is None:
            raise HTTPException(409, "APPROVED_RECOVERY_QUEUE: original durable queue is unavailable")
        component = worker.resolve_component("agent", EXECUTOR_ID)
        if (not isinstance(component, Agent) or isinstance(component, (AgentFactory, RemoteAgent))
                or component.id != EXECUTOR_ID):
            raise HTTPException(409, "APPROVED_RECOVERY_QUEUE: exact plain executor is unavailable")
        snapshot = await self.detail(run_id, session_id, user_id)
        ticket = snapshot.get("queue") or {}
        run = snapshot.get("run", snapshot)
        prior = (ticket.get("payload") or {}).get("continue") or {}
        if (str(run.get("status")).lower() not in {"paused", "runstatus.paused"}
                or ticket.get("status") != "paused" or ticket.get("id") != run_id
                or ticket.get("session_id") != session_id or ticket.get("user_id") != user_id
                or ticket.get("component_type") != "agent" or ticket.get("component_id") != EXECUTOR_ID
                or ticket.get("job_type", "run") != "run"
                or prior.get("kwargs", {}).get("metadata", {}).get("factoryControlCommand") != original_proof
                or digest(prior.get("updated_tools")) != tools_sha256
                or digest(native_requirements(snapshot)) != paused_requirements_sha256):
            raise HTTPException(409, "APPROVED_RECOVERY_CHANGED: original paused run/ticket/proof changed")
        tools = [value.get("tool_execution", value) for value in requirements]
        payload = {"updated_tools": tools, "input": None, "continue_from": None,
                   "kwargs": {"metadata": {"factoryControlCommand": command_proof}}}
        if digest(tools) != tools_sha256 or not payload_is_queueable(payload):
            raise HTTPException(409, "APPROVED_RECOVERY_PAYLOAD: original tool continuation is not queueable")
        outcome = await acontinue_via_queue(worker, run_id, payload, stream_requested=False,
                                           component_type="agent", component_id=EXECUTOR_ID)
        if outcome is None or outcome.get("outcome") not in {"queued", "attach"}:
            raise HTTPException(409, "APPROVED_RECOVERY_NOT_QUEUED: reconcile without replay")
        accepted = outcome.get("job") or {}
        actual = (accepted.get("payload") or {}).get("continue") or {}
        if (accepted.get("id") != run_id or accepted.get("session_id") != session_id
                or accepted.get("user_id") != user_id or accepted.get("component_id") != EXECUTOR_ID
                or accepted.get("component_type") != "agent"
                or actual.get("kwargs", {}).get("metadata", {}).get("factoryControlCommand") != command_proof
                or digest(actual.get("updated_tools")) != tools_sha256):
            raise HTTPException(409, "APPROVED_RECOVERY_ACK_UNKNOWN: exact repair proof is unavailable")
        return {"run_id": run_id, "session_id": session_id, "queue": jsonable_encoder(accepted)}

    async def cancel_run(self, run_id: str, session_id: str, user_id: str) -> dict[str, Any]:
        return await self._request("POST", self._run_path(run_id) + "/cancel", user_id,
                                   params={"session_id": session_id})

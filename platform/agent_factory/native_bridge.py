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
        self.auth.require(user_id, "run")
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
        result = await self._request("GET", self._run_path(run_id), user_id, params={"session_id": session_id})
        # Only query the ticket after native HTTP ownership/resource checks succeed.
        # Preserve requirements and the actual status; no synthetic status translation.
        result["queue"] = jsonable_encoder(self.native_db.get_job(run_id))
        return result

    async def find_run(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        """Reconcile an uncertain acknowledgement by exact native owner/session reads.

        Queue commit can precede the session's accepted-run row. Read the native
        ticket first, without replaying submission or changing native queue state.
        """
        self.auth.require(user_id, "run")
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
                           requirements: list[Any]) -> dict[str, Any]:
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
        return await self._request("POST", self._run_path(run_id) + "/continue", user_id,
            data={"session_id": session_id, "background": "true", "stream": "false", "tools": json.dumps(tools)})

    async def cancel_run(self, run_id: str, session_id: str, user_id: str) -> dict[str, Any]:
        return await self._request("POST", self._run_path(run_id) + "/cancel", user_id,
                                   params={"session_id": session_id})

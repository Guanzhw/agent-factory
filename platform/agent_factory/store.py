"""Factory metadata only. Agno owns runs, sessions, queue tickets and tool loops.

Immutable snapshots and admission fingerprints close native assembly gaps. This
store is not a second job scheduler. Uncertain admissions/effects retain capacity.
"""
import base64
import binascii
import hashlib
import json
from threading import Lock
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any
from contextvars import ContextVar
from contextlib import contextmanager

from agno.exceptions import InputCheckError, RunCancelledException
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def require_production_database(engine):
    with engine.connect() as conn:
        if conn.execute(text("SELECT to_regclass('af_bootstrap')")).scalar_one() is not None:
            mode = conn.execute(text("SELECT mode FROM af_bootstrap WHERE id='mode'")).scalar_one_or_none()
            if mode is not None and mode != 'production':
                raise ValueError('Existing demo database cannot be used in production; retained data requires separate review')


# Compatibility exports: custody/evidence semantics belong to trusted adapters.
from .runtime_hooks import effect_unresolved, runtime_custody_held
from .task_status import finalized_status


class Store:
    def __init__(self, url, settings):
        self.engine = create_engine(url, pool_pre_ping=True)
        self._root_lock_engine: Any = None
        self.personal_ssh: Any = None
        self._root_lock_engine_mutex = Lock()
        event.listen(self.engine, "engine_disposed", self.dispose_root_locks)
        self.settings = settings
        self.auth: Any = None
        self.delegation: Any = None
        self.native_db: Any = None
        self.connections: Any = None
        self.lifecycle_observer: Any = None
        self.personal_models: Any = None
        self.personal_tools: Any = None
        self.assistant_events: Any = None
        self.assistant_messages: Any = None
        self.external_execution_handlers: dict[str, Any] = {}
        self.execution_guards: dict[str, Any] = {}
        self.tool_independent_execution_guards: dict[str, Any] = {}
        self._connection: ContextVar[Any] = ContextVar("factory_metadata_connection", default=None)
        self.initialize()

    def root_lock_engine(self):
        """One separately bounded session-lock connection per Store.

        Session advisory locks span committed metadata phases, so they cannot
        occupy the only metadata-pool connection or borrow its transaction.
        Multiple DelegationService handles share this same bounded pool.
        """
        if self._connection.get() is not None:
            raise RuntimeError("Root lock must precede the metadata transaction")
        with self._root_lock_engine_mutex:
            if self._root_lock_engine is None:
                self._root_lock_engine = create_engine(self.engine.url, pool_size=1,
                    max_overflow=0, pool_pre_ping=True)
            return self._root_lock_engine

    def dispose_root_locks(self, _metadata_engine=None):
        with self._root_lock_engine_mutex:
            if self._root_lock_engine is not None:
                self._root_lock_engine.dispose()

    @contextmanager
    def transaction(self, *, read_only=False):
        """Share admission transactions with nested metadata/descendant reads."""
        borrowed = self._connection.get()
        if borrowed is not None:
            yield borrowed
            return
        with self.engine.begin() as conn:
            if read_only and self.engine.dialect.name == "postgresql":
                conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            token = self._connection.set(conn)
            try:
                yield conn
            finally:
                self._connection.reset(token)

    def sql(self, statement, **params):
        connection = self._connection.get()
        if connection is not None:
            result = connection.execute(text(statement), params)
            return [dict(row) for row in result.mappings()] if result.returns_rows else []
        # A standalone SELECT previously opened and committed its own read
        # transaction. AUTOCOMMIT preserves that single-statement snapshot and
        # releases the connection immediately, without BEGIN/COMMIT round trips.
        # Explicit transaction connections above still own all locking reads.
        if statement.lstrip().split(None, 1)[0].upper() == "SELECT":
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                result = conn.execute(text(statement), params)
                return [dict(row) for row in result.mappings()] if result.returns_rows else []
        with self.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return [dict(row) for row in result.mappings()] if result.returns_rows else []

    def initialize(self):
        require_production_database(self.engine)
        statements = [
            "CREATE TABLE IF NOT EXISTS af_browser_auth (id TEXT PRIMARY KEY,kind TEXT NOT NULL,body JSONB NOT NULL)",
            "CREATE INDEX IF NOT EXISTS af_browser_auth_expiry ON af_browser_auth ((CAST(body->>'expires' AS DOUBLE PRECISION)))",
            "CREATE INDEX IF NOT EXISTS af_browser_auth_binding ON af_browser_auth ((body->>'binding')) WHERE kind='flow'",
            "CREATE TABLE IF NOT EXISTS af_plans (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, body JSONB NOT NULL, hash TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_plan_requests (owner_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES af_plans(id), PRIMARY KEY(owner_id,request_id))",
            "CREATE TABLE IF NOT EXISTS af_tasks (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES af_plans(id), request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, run_id TEXT UNIQUE, admission TEXT NOT NULL DEFAULT 'reserved', terminal BOOLEAN NOT NULL DEFAULT FALSE, cancel_requested BOOLEAN NOT NULL DEFAULT FALSE, body JSONB NOT NULL, UNIQUE(owner_id,request_id))",
            "CREATE INDEX IF NOT EXISTS af_tasks_owner_history ON af_tasks(owner_id,(body->>'createdAt') DESC,id DESC)",
            "CREATE TABLE IF NOT EXISTS af_events (id BIGSERIAL PRIMARY KEY, task_id TEXT NOT NULL REFERENCES af_tasks(id), type TEXT NOT NULL, message TEXT NOT NULL, data JSONB NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_control_commands (owner_id TEXT NOT NULL, command_id TEXT NOT NULL, task_ref TEXT NOT NULL, root_task_id TEXT NOT NULL REFERENCES af_tasks(id), action TEXT NOT NULL, fingerprint TEXT NOT NULL, requirement_slot TEXT, state TEXT NOT NULL, body JSONB NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(owner_id,command_id), UNIQUE(owner_id,requirement_slot))",
            "CREATE INDEX IF NOT EXISTS af_control_commands_owner_task ON af_control_commands(owner_id,task_ref)",
            "CREATE TABLE IF NOT EXISTS af_effects (effect_key TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES af_tasks(id), run_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result JSONB)",
            "CREATE TABLE IF NOT EXISTS af_artifacts (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES af_tasks(id), body JSONB NOT NULL, content BYTEA NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_audit (id BIGSERIAL PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_id TEXT NOT NULL, body JSONB NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_bootstrap (id TEXT PRIMARY KEY, mode TEXT NOT NULL)",
        ]
        for statement in statements:
            self.sql(statement)
        self.sql("INSERT INTO af_bootstrap VALUES('mode','production') ON CONFLICT DO NOTHING")

    def audit(self, actor, action, target, body):
        self.sql("INSERT INTO af_audit(actor_id,action,target_id,body,created_at) VALUES(:actor,:action,:target,CAST(:body AS JSONB),:at)",
                 actor=actor, action=action, target=target, body=canonical(body), at=now())

    def save_plan(self, body):
        self.sql("INSERT INTO af_plans VALUES(:id,:owner,CAST(:body AS JSONB),:hash)",
                 id=body["id"], owner=body["ownerId"], body=canonical(body), hash=digest(body))
        return body

    def admit_plan(self, owner, request_id, request, builder):
        fp = digest(request)
        with self.transaction() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "plan:" + owner + ":" + request_id})
            row = conn.execute(text("SELECT * FROM af_plan_requests WHERE owner_id=:owner AND request_id=:key"), {"owner": owner, "key": request_id}).mappings().first()
            if row:
                if row["fingerprint"] != fp:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: plan request changed")
                return self.plan(row["plan_id"], owner)
            token = self._connection.set(conn)
            try:
                plan = builder()
            finally:
                self._connection.reset(token)
            conn.execute(text("INSERT INTO af_plan_requests VALUES(:owner,:key,:fp,:plan)"), {"owner": owner, "key": request_id, "fp": fp, "plan": plan["id"]})
        return plan

    def plan(self, plan_id, owner=None):
        rows = self.sql("SELECT * FROM af_plans WHERE id=:id", id=plan_id)
        if not rows or owner is not None and rows[0]["owner_id"] != owner:
            raise HTTPException(404, "Plan not found")
        row = rows[0]
        if digest(row["body"]) != row["hash"]:
            raise InputCheckError("Immutable plan integrity mismatch")
        return row["body"]

    def latest_personal_task(self, owner, session_id, project_id, native_session_id):
        """Read durable Factory admission even before a native command exists."""
        rows = self.sql("""SELECT t.id,t.plan_id,t.run_id FROM af_tasks t JOIN af_plans p ON p.id=t.plan_id
            WHERE t.owner_id=:owner AND p.owner_id=:owner
            AND t.request_id='personal:' || p.id
            AND p.body->>'application'='personal-agent-command-v1'
            AND p.body->'inputValues'->>'factorySessionId'=:session
            AND p.body->'inputValues'->>'nativeProjectId'=:project
            AND p.body->'inputValues'->>'nativeSessionId'=:native
            AND p.body->'inputValues'->>'action' IN ('prompt','interrupt')
            ORDER BY t.body->>'createdAt' DESC,t.id DESC LIMIT 1""",
            owner=owner, session=session_id, project=project_id, native=native_session_id)
        if not rows: return None
        row = rows[0]
        self.plan(row['plan_id'], owner)  # Check the immutable plan hash before returning its identity.
        return {'planId': row['plan_id'], 'taskId': row['id'], 'nativeRunId': row['run_id'],
                'executionContract': 'personal-external-v1'}

    def reserve_task(self, plan, request_id, *, allocation_id=None, delivery_id=None, private_event_id=None, remote_target=False):
        owner, fp = plan["ownerId"], digest({"planId": plan["id"], "planHash": digest(plan)})
        with self.transaction() as conn:
            # Coordinate original admissions with application completion transactions.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            old = conn.execute(text("SELECT * FROM af_tasks WHERE owner_id=:owner AND request_id=:request"), {"owner": owner, "request": request_id}).mappings().first()
            if old:
                if old["fingerprint"] != fp:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: request ID belongs to a different immutable plan")
                return dict(old), False
            if delivery_id is not None:
                self.assistant_events.validate_admission(conn, owner, delivery_id, request_id, plan)
            if private_event_id is not None:
                self.assistant_events.validate_private_admission(conn, owner, private_event_id, request_id, plan)
            if self.assistant_messages is not None:
                self.assistant_messages.validate_admission(conn, owner, request_id, plan)
            task_id = str(uuid4())
            body = {"createdAt": now(), "updatedAt": now(), "lastStatus": "queued", "requestId": request_id}
            row = conn.execute(text("INSERT INTO af_tasks(id,owner_id,plan_id,request_id,fingerprint,body) VALUES(:id,:owner,:plan,:request,:fp,CAST(:body AS JSONB)) RETURNING *"),
                               {"id": task_id, "owner": owner, "plan": plan["id"], "request": request_id, "fp": fp, "body": canonical(body)}).mappings().first()
            if row is None:
                raise RuntimeError("Task reservation did not persist")
        self.event(task_id, "admission_reserved", "Scoped task reserved; native queue acceptance pending", {"planId": plan["id"]})
        return dict(row), True

    def task(self, identifier, owner=None):
        rows = self.sql("SELECT * FROM af_tasks WHERE id=:id OR run_id=:id", id=identifier)
        if not rows or owner is not None and rows[0]["owner_id"] != owner:
            raise HTTPException(404, "Task not found")
        return rows[0]

    def task_for_request(self, request_id, owner):
        # Recovery is a read of the original owner-bound intent, never admission.
        if not request_id or len(request_id) > 200:
            raise HTTPException(404, "Request receipt not found")
        rows = self.sql("SELECT * FROM af_tasks WHERE owner_id=:owner AND request_id=:request",
                        owner=owner, request=request_id)
        if not rows:
            raise HTTPException(404, "Request receipt not found; admission remains unresolved")
        return rows[0]

    def tasks(self, owner):
        return self.sql("SELECT * FROM af_tasks WHERE owner_id=:owner ORDER BY body->>'createdAt' DESC LIMIT 100", owner=owner)

    def task_history(self, owner, *, limit=50, cursor=None):
        """Owner-scoped keyset projection; never reads execution details."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise HTTPException(422, "History limit must be between 1 and 100")
        boundary = None
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
                    raise ValueError()
                boundary = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
                if (not isinstance(boundary, dict) or set(boundary) != {"v", "owner", "createdAt", "id"}
                        or type(boundary["v"]) is not int or boundary["v"] != 1 or boundary["owner"] != owner
                        or any(not isinstance(boundary[key], str) or not 1 <= len(boundary[key]) <= 100
                               for key in ("createdAt", "id"))):
                    raise ValueError()
                if not self.sql("SELECT id FROM af_tasks WHERE owner_id=:owner AND id=:id AND body->>'createdAt'=:created",
                                owner=owner, id=boundary["id"], created=boundary["createdAt"]):
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError):
                raise HTTPException(400, "Invalid owner-scoped history cursor") from None
        where = "AND (t.body->>'createdAt',t.id)<(:created,:after)" if boundary else ""
        rows = self.sql(f"""SELECT t.id,t.owner_id,t.plan_id,t.admission,t.terminal,t.body->>'createdAt' AS created,
            t.body->>'updatedAt' AS updated,t.body->>'observedAt' AS observed,t.body->>'lastStatus' AS status,
            t.body->>'stoppedStatus' AS stopped_status,
            p.body->>'application' AS application,p.body->'applicationRef' AS application_ref,
            p.body->>'normalizedGoal' AS topic,p.body->>'mode' AS mode
            FROM af_tasks t JOIN af_plans p ON p.id=t.plan_id AND p.owner_id=t.owner_id
            WHERE t.owner_id=:owner {where} ORDER BY t.body->>'createdAt' DESC,t.id DESC LIMIT :count""",
            owner=owner, count=limit + 1, created=boundary["createdAt"] if boundary else None,
            after=boundary["id"] if boundary else None)
        items = []
        for row in rows[:limit]:
            ref = row["application_ref"] or {"id": row["application"], "version": 1}
            status = row["status"] or "unknown"
            if row["admission"] == "rejected":
                status = "failed"
            elif row["admission"] in {"reserved", "unknown"}:
                status = "unknown"
            status = (row["stopped_status"] if row["terminal"] else "finalizing") if row["stopped_status"] else finalized_status(status, row["terminal"])
            items.append({"id": row["id"], "ownerId": row["owner_id"], "planId": row["plan_id"],
                "definitionId": ref["id"], "definitionVersion": ref["version"],
                "input": {"topic": row["topic"], "mode": row["mode"], "scenario": "normal"},
                "status": status, "createdAt": row["created"], "updatedAt": row["updated"], "observedAt": row["observed"]})
            if row['stopped_status']:
                items[-1].update(executionStatus=row['stopped_status'], finalizationPending=not row['terminal'])
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = base64.urlsafe_b64encode(canonical({"v": 1, "owner": owner,
                "createdAt": last["created"], "id": last["id"]}).encode()).decode().rstrip('=')
        return {"items": items, "nextCursor": next_cursor}

    def accept(self, task_id, run_id):
        # A repeated exact acknowledgment cannot renew admission or re-hold a
        # positively stopped task. A first late binding still records native
        # ownership and holds capacity, including after metadata rejection.
        rows = self.sql("""UPDATE af_tasks SET run_id=:run,
            admission=CASE WHEN run_id IS NULL AND admission!='rejected' THEN 'accepted' ELSE admission END,
            terminal=CASE WHEN run_id IS NULL THEN FALSE ELSE terminal END
            WHERE id=:id AND (run_id IS NULL OR run_id=:run) RETURNING id""", id=task_id, run=run_id)
        if not rows:
            raise InputCheckError("Task already bound to another native run")

    def admission_unknown(self, task_id):
        self.sql("UPDATE af_tasks SET admission='unknown' WHERE id=:id AND run_id IS NULL", id=task_id)
        self.event(task_id, "admission_unknown", "Native acknowledgement missing; reconcile before retry", {})

    def admission_failed(self, task_id, message):
        self.sql("UPDATE af_tasks SET admission='rejected',terminal=(run_id IS NULL AND :complete) WHERE id=:id",
                 id=task_id, complete=True)
        self.event(task_id, "admission_rejected", message, {})

    def bind_run(self, ctx):
        envelope = (ctx.session_state or {}).get("factory_envelope", {})
        task = self.task(ctx.session_id)
        if task["owner_id"] != ctx.user_id or task["plan_id"] != envelope.get("plan_ref"):
            raise InputCheckError("Run identity does not match trusted task binding")
        self.accept(task["id"], ctx.run_id)
        plan = self.resolve_run(ctx)
        self.require_plan_execution(ctx.user_id, plan, run_context=ctx)
        return plan

    def resolve_run(self, ctx):
        task = self.task(ctx.run_id)
        if task["owner_id"] != ctx.user_id or task["id"] != ctx.session_id:
            raise InputCheckError("Run owner or session mismatch")
        if task["admission"] == "rejected":
            raise InputCheckError("Current task admission is rejected; execution denied")
        plan = self.plan(task["plan_id"], ctx.user_id)
        return {**plan, "taskId": task["id"], "runId": ctx.run_id}

    def authorize_tool(self, ctx, name):
        plan = self.resolve_run(ctx)
        if self.cancellation_requested(ctx.run_id):
            raise RunCancelledException("Factory cancellation requested before tool execution")
        self.require_plan_execution(ctx.user_id, plan, run_context=ctx, tool_name=name)
        if self.delegation is not None:
            self.delegation.authorize_child(ctx)
        return plan

    def register_execution_guard(self, name, guard, *, tool_independent=False):
        """Declare trusted guard scope without inheriting it across replacements."""
        self.execution_guards[name] = guard
        if tool_independent:
            self.tool_independent_execution_guards[name] = guard
        else:
            self.tool_independent_execution_guards.pop(name, None)

    def require_plan_execution(self, owner, plan, *, run_context=None, tool_name=None):
        if run_context is not None:
            task = self.task(run_context.session_id, owner)
            if task['body'].get('stoppedStatus') is not None:
                raise HTTPException(409, 'NATIVE_EXECUTION_STOPPED: original run cannot start new work')
        self.auth.require_member(owner)
        self.plan(plan['id'], owner)
        checked = {}
        for name, guard in self.execution_guards.items():
            guard(owner, plan, run_context, tool_name)
            checked[name] = guard
        return checked

    def event(self, identifier, event_type, message, data=None):
        task = self.task(identifier)
        self.sql("INSERT INTO af_events(task_id,type,message,data,created_at) VALUES(:id,:type,:message,CAST(:data AS JSONB),:at)",
                 id=task["id"], type=event_type, message=message, data=canonical(data or {}), at=now())

    def model_delta(self, identifier, event_type, text, response_id):
        task = self.task(identifier)
        stamp = now()
        # Keep one ordered row per adjacent model segment, including across refresh.
        self.sql("""WITH latest AS (
                SELECT id,type,data FROM af_events WHERE task_id=:id ORDER BY id DESC LIMIT 1
            ), updated AS (
                UPDATE af_events SET data=jsonb_set(data,'{text}',to_jsonb((data->>'text') || CAST(:text AS TEXT)))
                    || jsonb_build_object('updatedAt', CAST(:at AS TEXT))
                WHERE id=(SELECT id FROM latest WHERE type=:type AND data->>'responseId'=:response)
                RETURNING id
            ) INSERT INTO af_events(task_id,type,message,data,created_at)
                SELECT :id,:type,:message,CAST(:data AS JSONB),:at WHERE NOT EXISTS(SELECT id FROM updated)""",
            id=task['id'], type=event_type, text=text, response=response_id,
            message='正在思考' if event_type == 'model_reasoning_delta' else '正在生成回答',
            data=canonical({'responseId': response_id, 'text': text, 'updatedAt': stamp}), at=stamp)

    def events(self, task_id):
        return [{"id": row["id"], "jobId": task_id, "type": row["type"], "message": row["message"], "data": row["data"], "createdAt": row["created_at"]}
                for row in self.sql("SELECT * FROM af_events WHERE task_id=:id ORDER BY id", id=task_id)]

    def has_failures(self, task_id):
        # A bounded display window cannot erase an earlier protected failure
        # or a persisted failure-driven cleanup cause. Explicit user/native
        # cancellation is excluded, including known no-dispatch rejection.
        return bool(self.sql("""SELECT EXISTS(SELECT 1 FROM af_events WHERE task_id=:id AND (
            type IN ('tool_failed','protected_denied','experiment_failed') OR
            type='lifecycle_cleanup_requested' AND data->>'reason' IN
            ('protected-failure','current-authority-ended','native-failure','admission-rejected'))) AS failed""", id=task_id)[0]["failed"])

    def failure_cleanup_requested(self, task_id):
        return bool(self.sql("SELECT EXISTS(SELECT 1 FROM af_events WHERE task_id=:id AND type='lifecycle_cleanup_requested' AND data->>'reason' IN ('protected-failure','current-authority-ended','native-failure','admission-rejected')) AS failed", id=task_id)[0]["failed"])

    def observe_stopped(self, task, status):
        with self.transaction():
            current = self.sql("SELECT * FROM af_tasks WHERE id=:id FOR UPDATE", id=task['id'])[0]
            status = current['body'].get('stoppedStatus', status)
            body = {**current['body'], 'stoppedStatus': status}
            self.sql("UPDATE af_tasks SET body=CAST(:body AS JSONB) WHERE id=:id", id=task['id'], body=canonical(body))
            self._summary_locked({**current, 'body': body}, status)
        return status

    def observed(self, task, status, terminal):
        # Process reservation takes this same task row lock before inserting its
        # durable binding. Terminal task release cannot race admission.
        with self.transaction():
            rows = self.sql("SELECT * FROM af_tasks WHERE id=:id FOR UPDATE", id=task["id"])
            if not rows:
                return
            self._observed_locked(rows[0], status, terminal)

    def observe_summary(self, task, status):
        """A display observation cannot release custody or undo terminal proof."""
        with self.transaction():
            rows = self.sql("SELECT * FROM af_tasks WHERE id=:id AND owner_id=:owner FOR UPDATE",
                            id=task["id"], owner=task["owner_id"])
            if rows and not rows[0]["terminal"]:
                self._summary_locked(rows[0], status)

    def _summary_locked(self, task, status):
        stamp = now()
        changed = task["body"].get("lastStatus") != status
        body = {**task["body"], "lastStatus": status, "observedAt": stamp}
        if changed:
            body["updatedAt"] = stamp
        self.sql("UPDATE af_tasks SET body=CAST(:body AS JSONB) WHERE id=:id", id=task["id"], body=canonical(body))
        if changed:
            self.event(task["id"], "lifecycle", status, {"status": status})

    def _observed_locked(self, task, status, terminal):
        if terminal and (runtime_custody_held(self, task["id"])
                         or any(effect_unresolved(effect, self) for effect in self.effects(task["id"]))):
            terminal = False
        self._summary_locked(task, status)
        if task["terminal"] != terminal:
            self.sql("UPDATE af_tasks SET terminal=:terminal WHERE id=:id", id=task["id"], terminal=terminal)

    def request_cancel(self, task_id):
        with self.transaction() as conn:
            if self.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            self.sql("UPDATE af_tasks SET cancel_requested=TRUE WHERE id=:id", id=task_id)
            sessions = getattr(self, 'research_sessions', None)
            if sessions is not None:
                sessions.mark_cancel(self, task_id, reason='cancel-requested')
            self.event(task_id, "cancel_requested", "Cancellation requested; waiting for native run and experiments to stop", {})

    def cancellation_requested(self, identifier):
        return self.task(identifier)["cancel_requested"]

    def effect_reserve(self, run_id, key, request):
        task = self.task(run_id)
        effect_key = run_id + ":" + key
        rows = self.sql("INSERT INTO af_effects VALUES(:key,:task,:run,:fp,'UNKNOWN',NULL) ON CONFLICT DO NOTHING RETURNING effect_key", key=effect_key, task=task["id"], run=run_id, fp=digest(request))
        if rows:
            return {"status": "new"}
        old = self.sql("SELECT * FROM af_effects WHERE effect_key=:key", key=effect_key)[0]
        if old["fingerprint"] != digest(request):
            raise ValueError("Effect fingerprint conflict")
        return {"status": "done" if old["status"] in {"DONE", "CANCELLED"} else "unknown", "result": old["result"]}

    def effect_complete(self, run_id, key, result):
        status = "CANCELLED" if isinstance(result, dict) and result.get("cancelled") else "DONE"
        if effect_unresolved({"effect_key": run_id + ":" + key, "status": status, "result": result}, self):
            raise ValueError("Terminal effect requires positive adapter stop evidence")
        self.sql("UPDATE af_effects SET status=:status,result=CAST(:result AS JSONB) WHERE effect_key=:key", key=run_id + ":" + key, status=status, result=canonical(result))

    def effects(self, task_id):
        return self.sql("SELECT effect_key,status,result FROM af_effects WHERE task_id=:id", id=task_id)

    def artifact_write(self, run_id, name, content, media_type="application/json", metadata=None):
        task = self.task(run_id)
        raw = content.encode() if isinstance(content, str) else bytes(content)
        if any(char in name for char in "/\\\r\n"):
            raise ValueError("Artifact name must be a single safe filename")
        provenance: dict[str, Any] = dict(metadata) if metadata is not None else {"evidenceKind": "unverified", "verificationStatus": "unverified"}
        body = {"id": str(uuid4()), "jobId": task["id"], "name": name, "mediaType": media_type, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "createdAt": now(), "provenance": provenance}
        self.sql("INSERT INTO af_artifacts VALUES(:id,:task,CAST(:body AS JSONB),:content)", id=body["id"], task=task["id"], body=canonical(body), content=raw)
        self.event(run_id, "artifact", "Artifact persisted with SHA-256 provenance", {"artifactId": body["id"], "sha256": body["sha256"]})
        return body

    def artifacts(self, task_id):
        return [row["body"] for row in self.sql("SELECT body FROM af_artifacts WHERE task_id=:id ORDER BY body->>'createdAt'", id=task_id)]

    def artifact(self, task_id, artifact_id):
        rows = self.sql("SELECT body,content FROM af_artifacts WHERE task_id=:task AND id=:id", task=task_id, id=artifact_id)
        if not rows:
            raise HTTPException(404, "Artifact not found")
        raw = bytes(rows[0]["content"])
        if hashlib.sha256(raw).hexdigest() != rows[0]["body"]["sha256"]:
            raise HTTPException(409, "Artifact integrity check failed")
        return rows[0]["body"], raw

    def artifact_identity(self, task_id, artifact_id, max_bytes):
        """Hash original checkpoint bytes in bounded chunks under a row lock.

        No deserialization or full checkpoint materialization. The operator
        consumer still supplies current authorization and original provenance.
        """
        if type(max_bytes) is not int or not 1 <= max_bytes <= 2 * 1024**3:
            raise ValueError("CHECKPOINT_READ_BOUND_INVALID")
        with self.engine.begin() as conn:
            suffix = " FOR SHARE" if self.engine.dialect.name == "postgresql" else ""
            row = conn.execute(text("SELECT body,length(content) AS size FROM af_artifacts "
                "WHERE task_id=:task AND id=:id" + suffix), {"task": task_id, "id": artifact_id}).mappings().first()
            if row is None:
                raise HTTPException(404, "Artifact not found")
            size = row["size"]
            body = row["body"] if isinstance(row["body"], dict) else json.loads(row["body"])
            if type(size) is not int or not 0 < size <= max_bytes or body.get("size") != size:
                raise HTTPException(409, "Checkpoint size differs from approved bound")
            hasher = hashlib.sha256()
            for offset in range(0, size, 1024 * 1024):
                length = min(1024 * 1024, size - offset)
                raw = conn.execute(text("SELECT substr(content,:start,:length) FROM af_artifacts "
                    "WHERE task_id=:task AND id=:id"),
                    {"task": task_id, "id": artifact_id, "start": offset + 1, "length": length}).scalar_one()
                if len(raw) != length:
                    raise HTTPException(409, "Checkpoint bytes changed")
                hasher.update(raw)
            fingerprint = hasher.hexdigest()
            if fingerprint != body.get("sha256") or body.get("id") != artifact_id or body.get("jobId") != task_id:
                raise HTTPException(409, "Checkpoint integrity check failed")
            return body, {"sha256": fingerprint, "sizeBytes": size}

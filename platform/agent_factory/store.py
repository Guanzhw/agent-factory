"""Factory metadata only. Agno owns runs, sessions, queue tickets and tool loops.

Immutable snapshots and admission fingerprints close native assembly gaps. This
store is not a second job scheduler. Uncertain admissions/effects retain capacity.
"""
import hashlib
import json
from threading import Lock
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any
from types import SimpleNamespace
from contextvars import ContextVar
from contextlib import contextmanager

from agno.exceptions import InputCheckError
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def effect_unresolved(effect):
    """Native terminal state does not prove an ORX process tree has stopped."""
    if effect.get("status") not in {"DONE", "CANCELLED"}:
        return True
    if str(effect.get("effect_key", "")).endswith(":orx-experiment-launch-v1"):
        result = effect.get("result")
        proof = result.get("stopEvidence") if isinstance(result, dict) else None
        return not isinstance(proof, dict) or proof.get("allStopped") is not True
    return False


class Store:
    def __init__(self, url, settings):
        self.engine = create_engine(url, pool_pre_ping=True)
        self._root_lock_engine: Any = None
        self._root_lock_engine_mutex = Lock()
        event.listen(self.engine, "engine_disposed", self.dispose_root_locks)
        self.settings = settings
        self.auth: Any = None
        self.delegation: Any = None
        self.storage: Any = None
        self.native_db: Any = None
        self.plan_policy: Any = None
        self.material_governance: Any = None
        self.connections: Any = None
        self.execution_bindings: Any = None
        self.applications: Any = None
        self.composition: Any = None
        self.lifecycle_observer: Any = None
        self.event_replay: Any = None
        self.handoff_receiver: Any = None
        self.remote_execution: Any = None
        self.remote_bindings: Any = None
        self.usage_ledger: Any = None
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
    def transaction(self):
        """Share admission transactions with nested metadata/descendant reads."""
        borrowed = self._connection.get()
        if borrowed is not None:
            yield borrowed
            return
        with self.engine.begin() as conn:
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
        statements = [
            "CREATE TABLE IF NOT EXISTS af_materials (id TEXT NOT NULL, version INT NOT NULL, body JSONB NOT NULL, published BOOLEAN NOT NULL DEFAULT FALSE, PRIMARY KEY(id,version))",
            "CREATE TABLE IF NOT EXISTS af_plans (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, body JSONB NOT NULL, hash TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_plan_requests (owner_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES af_plans(id), PRIMARY KEY(owner_id,request_id))",
            "CREATE TABLE IF NOT EXISTS af_tasks (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, plan_id TEXT NOT NULL REFERENCES af_plans(id), request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, run_id TEXT UNIQUE, admission TEXT NOT NULL DEFAULT 'reserved', terminal BOOLEAN NOT NULL DEFAULT FALSE, cancel_requested BOOLEAN NOT NULL DEFAULT FALSE, body JSONB NOT NULL, UNIQUE(owner_id,request_id))",
            "CREATE TABLE IF NOT EXISTS af_events (id BIGSERIAL PRIMARY KEY, task_id TEXT NOT NULL REFERENCES af_tasks(id), type TEXT NOT NULL, message TEXT NOT NULL, data JSONB NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_control_commands (owner_id TEXT NOT NULL, command_id TEXT NOT NULL, task_ref TEXT NOT NULL, root_task_id TEXT NOT NULL REFERENCES af_tasks(id), action TEXT NOT NULL, fingerprint TEXT NOT NULL, requirement_slot TEXT, state TEXT NOT NULL, body JSONB NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(owner_id,command_id), UNIQUE(owner_id,requirement_slot))",
            "CREATE INDEX IF NOT EXISTS af_control_commands_owner_task ON af_control_commands(owner_id,task_ref)",
            "CREATE TABLE IF NOT EXISTS af_disk_holds (task_id TEXT PRIMARY KEY REFERENCES af_tasks(id),owner_id TEXT NOT NULL,bytes BIGINT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_storage_objects (id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,task_id TEXT NOT NULL REFERENCES af_tasks(id),root_id TEXT NOT NULL,evidence BOOLEAN NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL,identity JSONB NOT NULL DEFAULT '{}'::jsonb)",
            "CREATE TABLE IF NOT EXISTS af_retention_plans (id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,object_id TEXT NOT NULL REFERENCES af_storage_objects(id),request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,body JSONB NOT NULL,UNIQUE(owner_id,request_id))",
            "CREATE TABLE IF NOT EXISTS af_effects (effect_key TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES af_tasks(id), run_id TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result JSONB)",
            "CREATE TABLE IF NOT EXISTS af_inference_waits (task_id TEXT PRIMARY KEY REFERENCES af_tasks(id), body JSONB NOT NULL, hash TEXT NOT NULL, state TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_artifacts (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES af_tasks(id), body JSONB NOT NULL, content BYTEA NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_audit (id BIGSERIAL PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_id TEXT NOT NULL, body JSONB NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_resources (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, body JSONB NOT NULL)",
            "CREATE TABLE IF NOT EXISTS af_leases (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, target_id TEXT NOT NULL REFERENCES af_resources(id), request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL, body JSONB NOT NULL, UNIQUE(owner_id,request_id))",
            "CREATE TABLE IF NOT EXISTS af_bootstrap (id TEXT PRIMARY KEY, mode TEXT NOT NULL)",
        ]
        for statement in statements:
            self.sql(statement)
        # Upgrade safety: a pre-fix DONE row without kernel stop proof must not
        # retain a released slot merely because the application was restarted.
        # Preserve immutable effect/result hashes; only re-hold task capacity.
        self.sql("""UPDATE af_tasks task SET terminal=FALSE WHERE task.terminal AND EXISTS(
            SELECT 1 FROM af_effects effect WHERE effect.task_id=task.id
            AND effect.effect_key=task.run_id || :suffix
            AND effect.result->'stopEvidence'->'allStopped' IS DISTINCT FROM 'true'::jsonb)""",
            suffix=":orx-experiment-launch-v1")
        mode = "demo" if self.settings.demo else "production"
        self.sql("INSERT INTO af_bootstrap VALUES('mode',:mode) ON CONFLICT DO NOTHING", mode=mode)
        if self.sql("SELECT mode FROM af_bootstrap WHERE id='mode'")[0]["mode"] != mode:
            raise ValueError("Use a separate clean database when changing demo/production mode")

    def audit(self, actor, action, target, body):
        self.sql("INSERT INTO af_audit(actor_id,action,target_id,body,created_at) VALUES(:actor,:action,:target,CAST(:body AS JSONB),:at)",
                 actor=actor, action=action, target=target, body=canonical(body), at=now())

    def materials(self, published_only=False):
        rows = self.sql("SELECT body,published FROM af_materials WHERE (:all OR published) ORDER BY id,version DESC", all=not published_only)
        values = [{**row["body"], "published": row["published"]} for row in rows]
        if published_only and self.material_governance is not None:
            return self.material_governance.filter_active(values)
        return values

    def add_material(self, body, actor, seed=False):
        material_id = body.get("id") or str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": "material:" + material_id})
            latest = conn.execute(text("SELECT MAX(version) FROM af_materials WHERE id=:id"), {"id": material_id}).scalar() or 0
            body = {**body, "id": material_id, "version": latest + 1, "createdAt": now(), "published": seed}
            body["sha256"] = digest({key: value for key, value in body.items() if key not in {"sha256", "published", "createdAt"}})
            conn.execute(text("INSERT INTO af_materials VALUES(:id,:version,CAST(:body AS JSONB),:published)"),
                         {"id": material_id, "version": body["version"], "body": canonical(body), "published": seed})
        self.audit(actor, "material.seed" if seed else "material.draft", material_id, {"version": body["version"], "sha256": body["sha256"]})
        return body

    def publish_material(self, material_id, version, actor):
        rows = self.sql("UPDATE af_materials SET published=TRUE WHERE id=:id AND version=:version RETURNING body", id=material_id, version=version)
        if not rows:
            raise HTTPException(404, "Material version not found")
        self.audit(actor, "material.publish", material_id, {"version": version})
        return {**rows[0]["body"], "published": True}

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

    def reserve_task(self, plan, request_id):
        owner, fp = plan["ownerId"], digest({"planId": plan["id"], "planHash": digest(plan)})
        with self.transaction() as conn:
            # Serialize admission globally so simultaneous users cannot evade total quotas.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            if self.native_db is not None:
                active = conn.execute(text("SELECT id,run_id FROM af_tasks WHERE NOT terminal AND run_id IS NOT NULL")).mappings().all()
                for candidate in active:
                    native = self.native_db.get_job(candidate["run_id"]) or {}
                    uncertain = any(effect_unresolved(effect) for effect in conn.execute(
                        text("SELECT effect_key,status,result FROM af_effects WHERE task_id=:id"),
                        {"id": candidate["id"]}).mappings())
                    descendants_pending = getattr(self, "delegation", None) and self.delegation.has_pending_children(candidate["id"])
                    if native.get("status") in {"completed", "failed", "cancelled"} and not uncertain and not descendants_pending:
                        conn.execute(text("UPDATE af_tasks SET terminal=TRUE WHERE id=:id"), {"id": candidate["id"]})
                        if self.storage is not None:
                            self.storage.release(candidate["id"])
            old = conn.execute(text("SELECT * FROM af_tasks WHERE owner_id=:owner AND request_id=:request"), {"owner": owner, "request": request_id}).mappings().first()
            if old:
                if old["fingerprint"] != fp:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT: request ID belongs to a different immutable plan")
                return dict(old), False
            count = conn.execute(text("SELECT COUNT(*) FROM af_tasks WHERE NOT terminal")).scalar()
            user_count = conn.execute(text("SELECT COUNT(*) FROM af_tasks WHERE NOT terminal AND owner_id=:owner"), {"owner": owner}).scalar()
            if count >= self.settings.max_total_tasks or user_count >= self.settings.max_user_tasks:
                raise HTTPException(429, "Active task budget exhausted; UNKNOWN tasks retain capacity")
            task_id = str(uuid4())
            body = {"createdAt": now(), "updatedAt": now(), "lastStatus": "queued", "requestId": request_id}
            row = conn.execute(text("INSERT INTO af_tasks(id,owner_id,plan_id,request_id,fingerprint,body) VALUES(:id,:owner,:plan,:request,:fp,CAST(:body AS JSONB)) RETURNING *"),
                               {"id": task_id, "owner": owner, "plan": plan["id"], "request": request_id, "fp": fp, "body": canonical(body)}).mappings().first()
            if row is None:
                raise RuntimeError("Task reservation did not persist")
            if self.storage is not None:
                self.storage.reserve(task_id, owner)
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
        self.sql("UPDATE af_tasks SET admission='rejected',terminal=(run_id IS NULL) WHERE id=:id", id=task_id)
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
        self.require_current_policy()
        if self.plan_policy is not None:
            self.plan_policy.require_context_tool(ctx, name)
        for guard in self.execution_guards.values():
            guard(ctx.user_id, plan, ctx, name)
        if self.auth is None:
            raise PermissionError("Native authorization unavailable")
        self.auth.require(ctx.user_id, "run")
        if getattr(self, "delegation", None):
            self.delegation.authorize_child(ctx)
        if name not in plan["tools"] or plan["status"] != "ready" or self.cancellation_requested(ctx.run_id):
            self.event(ctx.run_id, "protected_denied", "Task authority denied a protected operation", {"tool": name})
            raise PermissionError("Tool outside task authority or cancellation requested")
        return plan

    def require_current_policy(self):
        # Configuration only: per-plan review is checked separately. Keeping this
        # boundary nonrecursive permits persisted ancestor mandate verification.
        if self.settings.temporary_policy == "unset":
            raise HTTPException(409, "POLICY_UNSET: current execution policy denies execution")
        if self.plan_policy is not None:
            if self.plan_policy.current()["name"] == "unset":
                raise HTTPException(409, "POLICY_UNSET: current execution policy denies execution")
        elif not self.settings.demo or self.settings.temporary_policy != "bounded-synthetic":
            raise HTTPException(409, "POLICY_UNSET: plan policy service is unavailable")

    def register_execution_guard(self, name, guard, *, tool_independent=False):
        """Declare trusted guard scope without inheriting it across replacements."""
        self.execution_guards[name] = guard
        if tool_independent:
            self.tool_independent_execution_guards[name] = guard
        else:
            self.tool_independent_execution_guards.pop(name, None)

    def require_plan_execution(self, owner, plan, *, run_context=None):
        self.require_current_policy()
        if self.auth is not None:
            self.auth.require(owner, "run")
        if self.plan_policy is not None:
            self.plan_policy.require_execution(owner, self.plan(plan["id"], owner), run_context=run_context)
        checked = {}
        for name, guard in self.execution_guards.items():
            guard(owner, plan, run_context, None)
            checked[name] = guard
        return checked

    def event(self, identifier, event_type, message, data=None):
        task = self.task(identifier)
        self.sql("INSERT INTO af_events(task_id,type,message,data,created_at) VALUES(:id,:type,:message,CAST(:data AS JSONB),:at)",
                 id=task["id"], type=event_type, message=message[:2000], data=canonical(data or {}), at=now())

    def events(self, task_id):
        return [{"id": row["id"], "jobId": task_id, "type": row["type"], "message": row["message"], "data": row["data"], "createdAt": row["created_at"]}
                for row in self.sql("SELECT * FROM (SELECT * FROM af_events WHERE task_id=:id ORDER BY id DESC LIMIT 1000) AS recent ORDER BY id", id=task_id)]

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

    def observed(self, task, status, terminal):
        if terminal and self.storage is not None:
            self.storage.release(task["id"])
        if task["body"].get("lastStatus") != status:
            body = {**task["body"], "lastStatus": status, "updatedAt": now()}
            self.sql("UPDATE af_tasks SET body=CAST(:body AS JSONB),terminal=:terminal WHERE id=:id", id=task["id"], body=canonical(body), terminal=terminal)
            self.event(task["id"], "lifecycle", status, {"status": status})
        elif task["terminal"] != terminal:
            self.sql("UPDATE af_tasks SET terminal=:terminal WHERE id=:id", id=task["id"], terminal=terminal)

    def request_cancel(self, task_id):
        with self.transaction():
            self.sql("UPDATE af_tasks SET cancel_requested=TRUE WHERE id=:id", id=task_id)
            self.sql("UPDATE af_inference_waits SET state='STOPPING' WHERE task_id=:id AND state IN ('WAITING','RESUMING')", id=task_id)
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
        if effect_unresolved({"effect_key": run_id + ":" + key, "status": status, "result": result}):
            raise ValueError("ORX terminal effect requires positive process-stop evidence")
        self.sql("UPDATE af_effects SET status=:status,result=CAST(:result AS JSONB) WHERE effect_key=:key", key=run_id + ":" + key, status=status, result=canonical(result))

    def effects(self, task_id):
        return self.sql("SELECT effect_key,status,result FROM af_effects WHERE task_id=:id", id=task_id)

    def artifact_write(self, run_id, name, content, media_type="application/json", metadata=None):
        task = self.task(run_id)
        raw = content.encode() if isinstance(content, str) else bytes(content)
        if len(raw) > self.settings.experiment_output_bytes:
            raise ValueError("Artifact exceeds task output budget")
        if len(name) > 120 or any(char in name for char in "/\\\r\n"):
            raise ValueError("Artifact name must be a single safe filename")
        provenance: dict[str, Any] = dict(metadata or {"syntheticFixture": True})
        if self.remote_bindings is not None:
            plan = self.plan(task["plan_id"], task["owner_id"])
            context = SimpleNamespace(session_id=task["id"], run_id=task["run_id"], user_id=task["owner_id"],
                session_state={"factory_envelope": {"plan_ref": plan["id"], "user_id": task["owner_id"],
                    "task_id": task["id"], "request_id": task["request_id"]}})
            root = self.remote_bindings._root(plan, context)
            if root is not None:
                source = plan["executionBindings"]
                effective = self.remote_bindings.historical_manifest(plan, context=context)
                def descriptor(spec):
                    return {key: spec[key] for key in ("adapterId", "revision")}
                provenance.update(modelAdapterId=effective["model"]["adapterId"],
                    environmentAdapterId=effective["environment"]["adapterId"], bindingProvenance={
                        "schema": 1, "sourceExecutionBindingsSha256": source["sha256"],
                        "effectiveExecutionBindingsSha256": effective["sha256"],
                        "receiverBindingProofSha256": root["remoteHandoff"]["bindingProofSha256"],
                        "sourceModel": descriptor(source["model"]), "effectiveModel": descriptor(effective["model"]),
                        "sourceEnvironment": descriptor(source["environment"]),
                        "effectiveEnvironment": descriptor(effective["environment"])})
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

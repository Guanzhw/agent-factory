"""Owner-scoped references to operator-installed opaque connection handles.

No credential, URL, provider installation or grant is accepted from HTTP. Only
redacted immutable metadata is stored in user references/plan snapshots. Current
SQL authority and trusted configuration are rechecked before resolving a handle.
The core's plan/tool guards remain responsible for execution approval and budgets.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, select, text

from .store import digest, now

ConnectionKind = Literal["model", "tool", "knowledge", "environment", "orx"]
KINDS = frozenset({"model", "tool", "knowledge", "environment", "orx"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
SECRET_PREFIX = re.compile(r"^(?:sk-|github_pat_|gh[pousr]_|AKIA|ASIA|Bearer[ :])", re.I)
CAPABILITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
_ABSENT = object()


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or SECRET_PREFIX.match(value):
        raise ValueError("An opaque bounded identifier is required")
    return value


def _capabilities(values):
    if isinstance(values, (str, bytes)):
        raise ValueError("Capabilities must be a bounded collection")
    normalized = frozenset(values)
    if len(normalized) > 30 or any(not isinstance(cap, str) or not CAPABILITY.fullmatch(cap) or SECRET_PREFIX.match(cap) for cap in normalized):
        raise ValueError("Unsupported capability identifier")
    return normalized


@dataclass(frozen=True)
class TrustedConnectionBinding:
    """Operator-only registry entry. Never deserialize this from user input.

    handle_ref identifies a stable opaque vault/adapter handle, not a secret or
    endpoint. Operators must rotate revision/handle_ref when replacing its
    underlying identity/configuration, including across process restarts.
    Unavailable metadata entries intentionally have no executable handle.
    """
    owner: str
    kind: ConnectionKind
    adapter_ref: str
    capabilities: frozenset[str]
    revision: str
    expires_at: datetime | None = None
    available: bool = False
    opaque_handle: Any = field(default=None, repr=False, compare=False)
    handle_ref: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if not isinstance(self.owner, str) or not 1 <= len(self.owner) <= 200 or any(ord(char) < 32 for char in self.owner):
            raise ValueError("A trusted owner identity is required")
        if self.kind not in KINDS or type(self.available) is not bool:
            raise ValueError("Unsupported trusted connection kind or availability")
        _identifier(self.adapter_ref)
        _identifier(self.revision)
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities))
        if self.handle_ref is not None:
            _identifier(self.handle_ref)
        if self.available and (self.opaque_handle is None or self.handle_ref is None):
            raise ValueError("An available binding requires an opaque handle and stable handle reference")
        if not self.available and self.opaque_handle is not None:
            raise ValueError("Unavailable metadata must not carry an executable handle")
        if self.expires_at is not None:
            if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("Trusted expiry must be timezone-aware")
            object.__setattr__(self, "expires_at", self.expires_at.astimezone(timezone.utc))

    def metadata(self):
        # Internal identity metadata only; no handle value/repr/credential.
        return {"owner": self.owner, "kind": self.kind, "adapterRef": self.adapter_ref,
                "capabilities": sorted(self.capabilities), "revision": self.revision,
                "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
                "available": self.available, "handleRef": self.handle_ref}

    @property
    def fingerprint(self):
        return digest(self.metadata())


class ConnectionService:
    def __init__(self, store: Any, auth: Any,
                 trusted_bindings: Mapping[str, TrustedConnectionBinding] | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.store, self.auth = store, auth
        # Operator configuration can be replaced by trusted in-process code.
        # Re-read this mapping at every preflight/resolve; never accept HTTP edits.
        self.trusted_bindings = trusted_bindings if trusted_bindings is not None else {}
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.handle_identities: dict[tuple[str, str, str], Any] = {}
        metadata = MetaData()
        self.versions = Table("af_trusted_connection_versions", metadata,
            Column("registration_ref", String, primary_key=True), Column("owner_id", String, primary_key=True),
            Column("revision", String, primary_key=True), Column("fingerprint", String, nullable=False),
            Column("body", JSON, nullable=False))
        self.references = Table("af_user_connections", metadata,
            Column("ref", String, primary_key=True), Column("owner_id", String, nullable=False),
            Column("version", Integer, nullable=False), Column("registration_ref", String, nullable=False),
            Column("fingerprint", String, nullable=False), Column("body", JSON, nullable=False),
            Column("state", String, nullable=False), Column("created_at", String, nullable=False),
            Column("revoked_at", String))
        self.commands = Table("af_connection_commands", metadata,
            Column("owner_id", String, primary_key=True), Column("request_id", String, primary_key=True),
            Column("fingerprint", String, nullable=False), Column("action", String, nullable=False),
            Column("result_ref", String, nullable=False), Column("created_at", String, nullable=False))
        self.audit = Table("af_audit", MetaData(), autoload_with=store.engine)
        metadata.create_all(store.engine)
        with store.engine.begin() as conn:
            self._lock(conn, "operator")
            for registration_ref, binding in self.trusted_bindings.items():
                self._register(conn, registration_ref, binding)

    def _at(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise HTTPException(503, "CONNECTION_CLOCK_UNAVAILABLE: trusted time is unavailable")
        return value.astimezone(timezone.utc)

    def _lock(self, conn, key):
        if self.store.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "af_connections:" + key})

    @contextmanager
    def _read(self):
        # Composition already owns a metadata transaction. Reuse its exact
        # connection so pinned/current checks see the same state and do not
        # consume another slot from a bounded pool. Nested Store task/plan
        # reads also share a connection opened here when no caller owns one.
        shared = getattr(self.store, "_connection", None)
        borrowed = shared.get() if shared is not None else None
        if borrowed is not None:
            yield borrowed
            return
        with self.store.engine.connect() as conn:
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    @contextmanager
    def _write(self):
        # Task-scoped bind/revoke projections may read the Store while this
        # transaction is active. Publish this owned connection to those reads.
        shared = getattr(self.store, "_connection", None)
        borrowed = shared.get() if shared is not None else None
        if borrowed is not None:
            yield borrowed
            return
        with self.store.engine.begin() as conn:
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    @staticmethod
    def _key(value):
        try:
            return _identifier(value)
        except ValueError as error:
            raise HTTPException(400, "CONNECTION_REFERENCE_INVALID: an opaque reference/request ID is required") from error

    @staticmethod
    def _caps(values):
        try:
            return _capabilities(values)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, "CONNECTION_SCOPE_INVALID: capabilities must be bounded identifiers") from error

    def _register(self, conn, registration_ref, binding):
        _identifier(registration_ref)
        if not isinstance(binding, TrustedConnectionBinding):
            raise ValueError("Only operator-created trusted connection bindings are accepted")
        row = conn.execute(select(self.versions).where(self.versions.c.registration_ref == registration_ref,
            self.versions.c.owner_id == binding.owner, self.versions.c.revision == binding.revision)).mappings().first()
        if row and (row["fingerprint"] != binding.fingerprint or digest(row["body"]) != binding.fingerprint):
            raise ValueError("A trusted connection revision cannot be rebound")
        if not row:
            conn.execute(self.versions.insert().values(registration_ref=registration_ref, owner_id=binding.owner,
                revision=binding.revision, fingerprint=binding.fingerprint, body=binding.metadata()))
        key = (registration_ref, binding.owner, binding.revision)
        previous = self.handle_identities.get(key, _ABSENT)
        if previous is not _ABSENT and previous is not binding.opaque_handle:
            raise ValueError("Rotate the trusted revision when replacing an opaque handle")
        self.handle_identities[key] = binding.opaque_handle

    def _trusted(self, registration_ref, owner, conn):
        binding = self.trusted_bindings.get(registration_ref)
        if binding is None:
            raise HTTPException(404, "CONNECTION_REGISTRATION_NOT_FOUND: trusted owner registration is missing")
        if not isinstance(binding, TrustedConnectionBinding):
            raise HTTPException(409, "CONNECTION_CHANGED: trusted registration is invalid")
        if binding.owner != owner:
            raise HTTPException(404, "CONNECTION_REGISTRATION_NOT_FOUND: trusted owner registration is missing")
        row = conn.execute(select(self.versions).where(self.versions.c.registration_ref == registration_ref,
            self.versions.c.owner_id == owner, self.versions.c.revision == binding.revision)).mappings().first()
        key = (registration_ref, owner, binding.revision)
        original = self.handle_identities.get(key, _ABSENT)
        if not row or row["fingerprint"] != binding.fingerprint or digest(row["body"]) != binding.fingerprint or original is _ABSENT or original is not binding.opaque_handle:
            raise HTTPException(409, "CONNECTION_CHANGED: trusted binding differs from its immutable registration")
        return binding

    def _row(self, conn, owner, reference):
        row = conn.execute(select(self.references).where(self.references.c.ref == reference,
            self.references.c.owner_id == owner)).mappings().first()
        if not row:
            raise HTTPException(404, "CONNECTION_NOT_FOUND: owner connection reference is missing")
        row = dict(row)
        body = row["body"]
        fields = {"ref", "ownerId", "version", "registrationRef", "trustedFingerprint", "kind", "revision", "capabilities", "taskId", "expiresAt"}
        if not isinstance(body, dict) or set(body) != fields or digest(body) != row["fingerprint"] or body.get("ownerId") != owner or body.get("ref") != reference or type(body.get("version")) is not int or body.get("version") != row["version"] or body.get("registrationRef") != row["registration_ref"]:
            raise HTTPException(409, "CONNECTION_INTEGRITY: immutable reference metadata changed")
        if row["state"] not in {"ACTIVE", "REVOKED"}:
            raise HTTPException(409, "CONNECTION_INTEGRITY: current state is invalid")
        return row

    def _task(self, owner, task_id):
        if task_id is None:
            return None
        self._key(task_id)
        task = self.store.task(task_id, owner)
        if task["terminal"] or task["cancel_requested"]:
            raise HTTPException(409, "CONNECTION_TASK_ENDED: task is canceled or terminal")
        self.store.plan(task["plan_id"], owner)  # Integrity/owner only; no recursive execution guard.
        return task["id"]

    def _current(self, conn, owner, row, *, task_id=None):
        if row["state"] == "REVOKED":
            raise HTTPException(409, "CONNECTION_REVOKED: owner reference was revoked")
        try:
            trusted = self._trusted(row["registration_ref"], owner, conn)
        except HTTPException as error:
            if error.status_code == 404:
                raise HTTPException(409, "CONNECTION_NOT_CONFIGURED: trusted registration is missing") from error
            raise
        body = row["body"]
        if trusted.fingerprint != body["trustedFingerprint"] or trusted.revision != body["revision"]:
            raise HTTPException(409, "CONNECTION_CHANGED: reference pins a previous trusted binding")
        if body["kind"] != trusted.kind or body["expiresAt"] != (trusted.expires_at.isoformat() if trusted.expires_at else None) or not self._caps(body["capabilities"]) <= trusted.capabilities:
            raise HTTPException(409, "CONNECTION_INTEGRITY: reference metadata differs from its trusted scope")
        if trusted.expires_at is not None and self._at() >= trusted.expires_at:
            raise HTTPException(409, "CONNECTION_EXPIRED: trusted binding expired")
        if not trusted.available or trusted.opaque_handle is None:
            raise HTTPException(409, "CONNECTION_UNAVAILABLE: trusted adapter is not configured")
        if body["taskId"] is not None:
            current_task = self._task(owner, task_id)
            if current_task is None or current_task != body["taskId"]:
                raise HTTPException(409, "CONNECTION_TASK_SCOPE: reference belongs to a different task")
        elif task_id is not None:
            self._task(owner, task_id)
        return trusted

    def _project(self, conn, owner, row):
        body = row["body"]
        status = "active"
        try:
            self._current(conn, owner, row, task_id=body["taskId"])
        except HTTPException as error:
            code = str(error.detail).split(":", 1)[0]
            status = {"CONNECTION_REVOKED": "revoked", "CONNECTION_EXPIRED": "expired",
                "CONNECTION_UNAVAILABLE": "unavailable", "CONNECTION_NOT_CONFIGURED": "missing",
                "CONNECTION_CHANGED": "changed", "CONNECTION_TASK_ENDED": "task_ended"}.get(code, "unavailable")
        return self._projection(row, status)

    @staticmethod
    def _projection(row, status):
        """Public metadata only; callers own the current-check boundary."""
        body = row["body"]
        return {key: body[key] for key in ("ref", "ownerId", "version", "kind", "revision", "capabilities", "taskId", "registrationRef", "expiresAt")} | {
            "fingerprint": row["fingerprint"], "status": status, "available": status == "active",
            "createdAt": row["created_at"], "revokedAt": row["revoked_at"],
            "allowedActions": ["inspect"] + (["revoke"] if row["state"] != "REVOKED" else [])}

    def _can_bind(self, owner):
        try:
            self.auth.require(owner, "run")
            return True
        except HTTPException as error:
            if error.status_code != 403:
                raise
            return False

    def registrations(self, owner):
        self.auth.require(owner, "read")
        can_bind = self._can_bind(owner)
        values = []
        with self._read() as conn:
            for ref, binding in self.trusted_bindings.items():
                if not isinstance(binding, TrustedConnectionBinding) or binding.owner != owner:
                    continue
                status = "available"
                try:
                    self._trusted(ref, owner, conn)
                    if binding.expires_at is not None and self._at() >= binding.expires_at:
                        status = "expired"
                    elif not binding.available:
                        status = "unavailable"
                except HTTPException:
                    status = "changed"
                values.append({"registrationRef": ref, "kind": binding.kind, "revision": binding.revision,
                    "capabilities": sorted(binding.capabilities), "expiresAt": binding.expires_at.isoformat() if binding.expires_at else None,
                    "status": status, "available": status == "available",
                    "allowedActions": ["inspect", "bind"] if can_bind else ["inspect"]})
        return sorted(values, key=lambda value: value["registrationRef"])

    def inspect(self, owner, reference):
        self.auth.require(owner, "read")
        self._key(reference)
        with self._read() as conn:
            return self._project(conn, owner, self._row(conn, owner, reference))

    def list(self, owner):
        self.auth.require(owner, "read")
        with self._read() as conn:
            rows = conn.execute(select(self.references.c.ref).where(self.references.c.owner_id == owner)
                .order_by(self.references.c.created_at.desc(), self.references.c.ref).limit(100)).scalars()
            return [self._project(conn, owner, self._row(conn, owner, reference)) for reference in rows]

    def _command(self, conn, owner, request_id, fingerprint):
        row = conn.execute(select(self.commands).where(self.commands.c.owner_id == owner,
            self.commands.c.request_id == request_id)).mappings().first()
        if row and row["fingerprint"] != fingerprint:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT: connection request intent changed")
        return row

    def bind(self, owner, registration_ref, request_id, *, capabilities=None, task_id=None):
        self.auth.require(owner, "run")
        self._key(registration_ref)
        self._key(request_id)
        requested = self._caps(capabilities) if capabilities is not None else None
        # Request identity captures the caller's choice, not a later operator
        # configuration. A replay observes the existing reference's current state.
        fingerprint = digest({"operation": "bind", "registrationRef": registration_ref,
            "capabilities": sorted(requested) if requested is not None else None, "taskId": task_id})
        with self._write() as conn:
            self._lock(conn, owner)
            previous = self._command(conn, owner, request_id, fingerprint)
            if previous:
                return self._project(conn, owner, self._row(conn, owner, previous["result_ref"]))
            trusted = self._trusted(registration_ref, owner, conn)
            requested = requested if requested is not None else trusted.capabilities
            if not requested <= trusted.capabilities:
                raise HTTPException(409, "CONNECTION_SCOPE_INVALID: requested capability exceeds trusted binding")
            task_id = self._task(owner, task_id)
            body = {"ref": str(uuid4()), "ownerId": owner, "version": 1, "registrationRef": registration_ref,
                "trustedFingerprint": trusted.fingerprint, "kind": trusted.kind, "revision": trusted.revision,
                "capabilities": sorted(requested), "taskId": task_id,
                "expiresAt": trusted.expires_at.isoformat() if trusted.expires_at else None}
            at = now()
            row = {"ref": body["ref"], "owner_id": owner, "version": 1, "registration_ref": registration_ref,
                "fingerprint": digest(body), "body": body, "state": "ACTIVE", "created_at": at, "revoked_at": None}
            conn.execute(self.references.insert().values(**row))
            conn.execute(self.commands.insert().values(owner_id=owner, request_id=request_id,
                fingerprint=fingerprint, action="bind", result_ref=body["ref"], created_at=at))
            conn.execute(self.audit.insert().values(actor_id=owner, action="connection.bind", target_id=body["ref"],
                body={"ref": body["ref"], "version": 1, "fingerprint": row["fingerprint"], "kind": trusted.kind}, created_at=at))
            return self._project(conn, owner, row)

    def revoke(self, owner, reference, request_id):
        # Evidence read/cleanup remains possible after the run grant is removed.
        self.auth.require(owner, "read")
        self._key(reference)
        self._key(request_id)
        fingerprint = digest({"operation": "revoke", "ref": reference})
        with self._write() as conn:
            self._lock(conn, owner)
            previous = self._command(conn, owner, request_id, fingerprint)
            row = self._row(conn, owner, reference)
            if not previous:
                if row["state"] != "REVOKED":
                    row.update(state="REVOKED", revoked_at=now())
                    conn.execute(self.references.update().where(self.references.c.ref == reference,
                        self.references.c.owner_id == owner).values(state=row["state"], revoked_at=row["revoked_at"]))
                conn.execute(self.commands.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=fingerprint, action="revoke", result_ref=reference, created_at=now()))
                conn.execute(self.audit.insert().values(actor_id=owner, action="connection.revoke", target_id=reference,
                    body={"ref": reference, "fingerprint": row["fingerprint"]}, created_at=now()))
            return self._project(conn, owner, row)

    def _check(self, conn, owner, reference, expected_kind, *, expected_revision=None,
               expected_fingerprint=None, expected_version=None, expected_adapter_ref=None,
               required_capabilities=(), task_id=None):
        self._key(reference)
        if expected_kind not in KINDS:
            raise HTTPException(400, "CONNECTION_KIND_INVALID: a supported expected kind is required")
        row = self._row(conn, owner, reference)
        body = row["body"]
        if body["kind"] != expected_kind or expected_revision is not None and body["revision"] != expected_revision or expected_fingerprint is not None and row["fingerprint"] != expected_fingerprint or expected_version is not None and (type(expected_version) is not int or row["version"] != expected_version):
            raise HTTPException(409, "CONNECTION_PIN_MISMATCH: immutable connection pin differs")
        trusted = self._current(conn, owner, row, task_id=task_id)
        if expected_adapter_ref is not None and trusted.adapter_ref != expected_adapter_ref:
            raise HTTPException(409, "CONNECTION_ADAPTER_MISMATCH: trusted registration belongs to a different adapter")
        required = self._caps(required_capabilities)
        if not required <= set(body["capabilities"]) or not required <= trusted.capabilities:
            raise HTTPException(409, "CONNECTION_SCOPE_INVALID: required capability is outside connection scope")
        return row, trusted

    def preflight(self, owner, reference, expected_kind, *, expected_revision=None,
                  expected_fingerprint=None, expected_version=None, expected_adapter_ref=None,
                  required_capabilities=(), task_id=None):
        self.auth.require(owner, "run")
        with self._read() as conn:
            row, _trusted = self._check(conn, owner, reference, expected_kind,
                expected_revision=expected_revision, expected_fingerprint=expected_fingerprint,
                expected_version=expected_version, expected_adapter_ref=expected_adapter_ref,
                required_capabilities=required_capabilities, task_id=task_id)
            # _check just verified the exact owner/task/pin and current binding.
            # Project that result without repeating the same SQL check inside
            # this boundary. Every later preflight/resolve checks afresh.
            return self._projection(row, "active")

    def resolve(self, owner, reference, expected_kind, *, expected_revision=None,
                expected_fingerprint=None, expected_version=None, expected_adapter_ref=None,
                required_capabilities=(), task_id=None):
        self.auth.require(owner, "run")
        with self._read() as conn:
            _row, trusted = self._check(conn, owner, reference, expected_kind,
                expected_revision=expected_revision, expected_fingerprint=expected_fingerprint,
                expected_version=expected_version, expected_adapter_ref=expected_adapter_ref,
                required_capabilities=required_capabilities, task_id=task_id)
            return trusted.opaque_handle


    def cleanup_handle(self, owner, pin, *, adapter_ref, task_id):
        """Trusted reclaim only: exact old ORX handle, no refreshed execution grant.

        No HTTP route exposes this accessor. A persisted native launch intent
        and the immutable task experiment binding must already exist. Revoked
        or expired owner references remain revoked/expired; changed handles,
        owner/task/source pins and native identities are never substituted.
        """
        if adapter_ref != "openresearch-experiment-v1" or not isinstance(pin, dict):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: only original local experiment reclaim is supported")
        task = self.store.task(task_id, owner)
        native_db = self.store.native_db
        ticket = native_db.get_job(task["run_id"], strict=True) if native_db and task.get("run_id") else None
        expected_native = {"id": task.get("run_id"), "session_id": task_id, "user_id": owner,
                           "component_id": "factory-executor", "component_type": "agent"}
        if not ticket or any(ticket.get(key) != value for key, value in expected_native.items()):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: exact native task identity is unavailable")
        rows = self.store.sql("SELECT * FROM af_orx_task_experiments WHERE task_id=:task AND owner_id=:owner", task=task_id, owner=owner)
        if len(rows) != 1:
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: original experiment binding is unavailable")
        binding_row = rows[0]
        binding = binding_row["binding"]
        if (digest(binding) != binding_row["binding_hash"] or binding_row["plan_id"] != task["plan_id"]
                or binding_row["run_id"] != task["run_id"] or binding.get("ownerId") != owner
                or binding.get("taskId") != task_id or binding.get("planId") != task["plan_id"]
                or binding.get("nativeRunId") != task["run_id"]):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: original experiment identity changed")
        recorded_pin = binding.get("connection", {})
        if any(recorded_pin.get(key) != pin.get(key) for key in ("ref", "version", "fingerprint", "revision", "capabilities")):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: requested handle differs from original execution")
        intent = self.store.sql("SELECT effect_key,fingerprint FROM af_effects WHERE task_id=:task AND run_id=:run",
                                task=task_id, run=task["run_id"])
        expected_key = task["run_id"] + ":orx-experiment-launch-v1"
        request_hash = digest({key: value for key, value in binding.items() if key not in {"projectId", "experimentId"}})
        if not any(effect.get("effect_key") == expected_key and effect.get("fingerprint") == request_hash for effect in intent):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: durable launch intent is unavailable")
        with self._read() as connection:
            row = self._row(connection, owner, pin.get("ref"))
            body = row["body"]
            if (body["kind"] != "orx" or body["taskId"] not in {None, task_id}
                    or row["fingerprint"] != pin.get("fingerprint")
                    or any(body.get(key) != pin.get(key) for key in ("ref", "version", "revision", "capabilities", "taskId"))):
                raise HTTPException(409, "CLEANUP_BINDING_INVALID: immutable owner reference changed")
            trusted = self._trusted(row["registration_ref"], owner, connection)
            if (trusted.fingerprint != body["trustedFingerprint"] or trusted.adapter_ref != adapter_ref
                    or trusted.kind != "orx" or not callable(getattr(trusted.opaque_handle, "create_experiment_adapter", None))):
                raise HTTPException(409, "CLEANUP_BINDING_INVALID: original cleanup handle is unavailable")
            return trusted.opaque_handle


class BindConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registrationRef: str = Field(min_length=1, max_length=200)
    requestId: str = Field(min_length=1, max_length=200)
    capabilities: list[str] | None = Field(default=None, max_length=30)
    taskId: str | None = Field(default=None, min_length=1, max_length=200)


class RevokeConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=200)


def connection_router(auth, service):
    # Root may alias/migrate the old demo-only GET /connections product route.
    # This independent namespace avoids silently shadowing existing routes.
    router = APIRouter(prefix="/api/factory/user-connections", tags=["user-connections"])

    def owner(request):
        return auth.user(request)["id"]

    @router.get("/registrations")
    def registrations(request: Request):
        return service.registrations(owner(request))

    @router.get("")
    def listing(request: Request):
        return service.list(owner(request))

    @router.post("", status_code=201)
    def bind(body: BindConnectionRequest, request: Request):
        return service.bind(owner(request), body.registrationRef, body.requestId,
            capabilities=body.capabilities, task_id=body.taskId)

    @router.get("/{reference}")
    def inspect(reference: str, request: Request):
        return service.inspect(owner(request), reference)

    @router.post("/{reference}/revoke")
    def revoke(reference: str, body: RevokeConnectionRequest, request: Request):
        return service.revoke(owner(request), reference, body.requestId)

    return router

"""Owner-created immutable remote configurations and verified scoped bindings.

Operators install provider implementations/global policy only. Owners create and
reconfigure their own resources. SQL contains credential references, never values.
Verification never creates a session, installs a runtime, or invokes a model.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from .personal_remote_provider import RemoteConnectionError
from .store import digest, now


class PersonalRemoteConnections:
    def __init__(self, connections, providers):
        self.connections, self.providers = connections, providers
        metadata = MetaData()
        self.configs = Table("af_personal_remote_configs", metadata,
            Column("registration_ref", String, primary_key=True), Column("revision", String, primary_key=True),
            Column("owner_id", String, nullable=False), Column("body", JSON, nullable=False),
            Column("fingerprint", String, nullable=False))
        self.resources = Table("af_personal_remotes", metadata,
            Column("registration_ref", String, primary_key=True), Column("owner_id", String, nullable=False),
            Column("config_revision", String, nullable=False), Column("state", String, nullable=False),
            Column("verification", JSON), Column("verification_hash", String),
            Column("created_at", String, nullable=False), Column("updated_at", String, nullable=False))
        metadata.create_all(connections.store.engine)

    def _row(self, conn, owner, reference):
        self.connections._key(reference)
        row = conn.execute(select(self.resources).where(self.resources.c.registration_ref == reference,
            self.resources.c.owner_id == owner)).mappings().first()
        if not row:
            raise HTTPException(404, "REMOTE_NOT_FOUND")
        config = conn.execute(select(self.configs).where(self.configs.c.registration_ref == reference,
            self.configs.c.revision == row["config_revision"], self.configs.c.owner_id == owner)).mappings().first()
        if (not config or digest(config["body"]) != config["fingerprint"]
                or config["body"].get("ownerId") != owner
                or config["body"].get("registrationRef") != reference
                or config["body"].get("revision") != row["config_revision"]):
            raise HTTPException(409, "REMOTE_INTEGRITY")
        return dict(row), config["body"]

    def _provider(self, body):
        provider = self.providers.get(body["providerId"])
        if provider is None or provider.provider_id != body["providerId"]:
            raise HTTPException(409, "REMOTE_PROVIDER_UNAVAILABLE")
        if provider.policy_revision != body["policyRevision"] or provider.kind != body.get("kind", "environment"):
            raise HTTPException(409, "REMOTE_POLICY_CHANGED")
        return provider

    def _projection(self, conn, owner, reference):
        row, body = self._row(conn, owner, reference)
        status = row["state"].lower()
        verified = row["verification"]
        if status == "verified":
            try:
                self.binding(conn, owner, reference)
            except HTTPException as error:
                status = {"REMOTE_VERIFICATION_EXPIRED": "expired", "REMOTE_CREDENTIAL_UNAVAILABLE": "credential_unavailable",
                          "REMOTE_POLICY_CHANGED": "policy_changed"}.get(str(error.detail), "unavailable")
        can_run = self.connections._can_bind(owner)
        return {"registrationRef": reference, "providerId": body["providerId"], "kind": body.get("kind", "environment"),
            "configRevision": body["revision"], "status": status, "available": status == "verified",
            "origin": body["configuration"]["origin"], "projectId": body["configuration"]["projectId"],
            "capabilities": verified["capabilities"] if verified and status == "verified" else [],
            "revision": verified["revision"] if verified else body["revision"],
            "expiresAt": verified["expiresAt"] if verified else None,
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            "allowedActions": ["inspect"] + ([] if status == "revoked" else
                (["revoke"] + (["configure", "verify"] + (["bind"] if status == "verified" else []) if can_run else [])))}

    def list(self, owner):
        self.connections.auth.require(owner, "read")
        with self.connections._read() as conn:
            refs = list(conn.execute(select(self.resources.c.registration_ref).where(
                self.resources.c.owner_id == owner).limit(100)).scalars())
            return [self._projection(conn, owner, ref) for ref in refs]

    def inspect(self, owner, reference):
        self.connections.auth.require(owner, "read")
        with self.connections._read() as conn:
            return self._projection(conn, owner, reference)

    def request_result(self, owner, request_id):
        self.connections.auth.require(owner, 'read')
        self.connections._key(request_id)
        with self.connections._read() as conn:
            command = conn.execute(select(self.connections.commands).where(
                self.connections.commands.c.owner_id == owner,
                self.connections.commands.c.request_id == request_id)).mappings().first()
            if command is None or command['action'] not in {'remote.configure', 'remote.verify', 'remote.revoke'}:
                raise HTTPException(404, 'REMOTE_REQUEST_NOT_FOUND')
            return {'requestId': request_id, 'action': command['action'],
                'remote': self._projection(conn, owner, command['result_ref'])}

    def available_providers(self, owner):
        self.connections.auth.require(owner, "read")
        return [{"providerId": key, "kind": provider.kind, "capabilities": sorted(provider.capabilities),
                 "policyRevision": provider.policy_revision, "requiresCredentialReference": True,
                 "provisionsCompute": False, "namespace": getattr(provider, "namespace", "opencode"),
                 "authModes": list(getattr(provider, "auth_modes", ())),
                 "sessionTemplateSupported": bool(getattr(provider, "session_template_supported", False)),
                 "projectCreationSupported": callable(getattr(provider, "effective_capabilities", None))}
                for key, provider in sorted(self.providers.items())]

    def configure(self, owner, provider_id, configuration, request_id, *, reference=None):
        service = self.connections
        service.auth.require(owner, "run")
        service._key(request_id); service._key(provider_id)
        provider = self.providers.get(provider_id)
        if provider is None:
            raise HTTPException(422, "REMOTE_PROVIDER_UNAVAILABLE")
        try:
            normalized = provider.configure(configuration)
        except RemoteConnectionError as error:
            raise HTTPException(422, str(error)) from None
        # A reference is not authority. The secret backend must confirm the exact
        # authenticated owner, origin and immutable credential revision first.
        if not provider.authorized(owner, normalized):
            raise HTTPException(403, "REMOTE_CREDENTIAL_UNAVAILABLE")
        fingerprint = digest({"operation": "remote.configure", "providerId": provider_id,
                              "configuration": normalized, "reference": reference})
        with service._write() as conn:
            service._lock(conn, owner)
            previous = service._command(conn, owner, request_id, fingerprint)
            if previous:
                return self._projection(conn, owner, previous["result_ref"])
            at = now()
            if reference is not None:
                row, _ = self._row(conn, owner, reference)
                if row["state"] == "REVOKED":
                    raise HTTPException(409, "REMOTE_REVOKED")
            else:
                reference = "remote-" + uuid4().hex
            revision = uuid4().hex
            body = {"registrationRef": reference, "ownerId": owner, "revision": revision,
                "providerId": provider_id, "kind": provider.kind, "policyRevision": provider.policy_revision, "configuration": normalized}
            conn.execute(self.configs.insert().values(registration_ref=reference, revision=revision,
                owner_id=owner, body=body, fingerprint=digest(body)))
            values = dict(config_revision=revision, state="CONFIGURED", verification=None,
                          verification_hash=None, updated_at=at)
            if conn.execute(select(self.resources.c.registration_ref).where(
                    self.resources.c.registration_ref == reference)).first():
                conn.execute(self.resources.update().where(self.resources.c.registration_ref == reference,
                    self.resources.c.owner_id == owner).values(**values))
            else:
                conn.execute(self.resources.insert().values(registration_ref=reference, owner_id=owner,
                    created_at=at, **values))
            conn.execute(service.commands.insert().values(owner_id=owner, request_id=request_id,
                fingerprint=fingerprint, action="remote.configure", result_ref=reference, created_at=at))
            conn.execute(service.audit.insert().values(actor_id=owner, action="remote.configure", target_id=reference,
                body={"providerId": provider_id, "revision": revision}, created_at=at))
            return self._projection(conn, owner, reference)

    def verify(self, owner, reference, request_id):
        service = self.connections
        service.auth.require(owner, "run"); service._key(request_id)
        # Do not hold a SQL transaction/lock while performing bounded remote IO.
        with service._read() as conn:
            row, body = self._row(conn, owner, reference)
            fingerprint = digest({"operation": "remote.verify", "reference": reference, "revision": body["revision"]})
            previous = service._command(conn, owner, request_id, fingerprint)
            if previous:
                return self._projection(conn, owner, reference)
            if row["state"] == "REVOKED":
                raise HTTPException(409, "REMOTE_REVOKED")
            provider = self._provider(body)
        try:
            evidence = provider.verify(owner, body["configuration"])
        except Exception:
            # A failed fresh probe invalidates the old lease. Do not clobber a
            # concurrent reconfiguration or revocation while IO was in flight.
            with service._write() as conn:
                service._lock(conn, owner)
                current, current_body = self._row(conn, owner, reference)
                if current_body == body and current["state"] != "REVOKED":
                    conn.execute(self.resources.update().where(self.resources.c.registration_ref == reference,
                        self.resources.c.owner_id == owner).values(state="FAILED", verification=None,
                        verification_hash=None, updated_at=now()))
            # Never expose transport exceptions, URL, server bodies or credentials.
            raise HTTPException(409, "REMOTE_VERIFICATION_FAILED") from None
        with service._write() as conn:
            service._lock(conn, owner)
            current, current_body = self._row(conn, owner, reference)
            service.auth.require(owner, "run")
            if current["state"] == "REVOKED" or current_body != body or self._provider(body) is not provider:
                raise HTTPException(409, "REMOTE_CONFIGURATION_CHANGED")
            if not provider.authorized(owner, body["configuration"]):
                raise HTTPException(409, "REMOTE_CREDENTIAL_UNAVAILABLE")
            if service._command(conn, owner, request_id, fingerprint):
                return self._projection(conn, owner, reference)
            at = service._at()
            verification = {**evidence, "revision": uuid4().hex, "configRevision": body["revision"],
                "verifiedAt": at.isoformat(), "expiresAt": (at + timedelta(minutes=15)).isoformat(),
                "policyRevision": provider.policy_revision}
            conn.execute(self.resources.update().where(self.resources.c.registration_ref == reference,
                self.resources.c.owner_id == owner).values(state="VERIFIED", verification=verification,
                verification_hash=digest(verification), updated_at=now()))
            conn.execute(service.commands.insert().values(owner_id=owner, request_id=request_id,
                fingerprint=fingerprint, action="remote.verify", result_ref=reference, created_at=now()))
            conn.execute(service.audit.insert().values(actor_id=owner, action="remote.verify", target_id=reference,
                body={"revision": verification["revision"], "configRevision": body["revision"]}, created_at=now()))
            return self._projection(conn, owner, reference)

    def revoke(self, owner, reference, request_id):
        service = self.connections
        service.auth.require(owner, "read"); service._key(request_id)
        fingerprint = digest({"operation": "remote.revoke", "reference": reference})
        with service._write() as conn:
            service._lock(conn, owner)
            self._row(conn, owner, reference)
            if not service._command(conn, owner, request_id, fingerprint):
                conn.execute(self.resources.update().where(self.resources.c.registration_ref == reference,
                    self.resources.c.owner_id == owner).values(state="REVOKED", updated_at=now()))
                conn.execute(service.commands.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=fingerprint, action="remote.revoke", result_ref=reference, created_at=now()))
                conn.execute(service.audit.insert().values(actor_id=owner, action="remote.revoke", target_id=reference,
                    body={"revoked": True}, created_at=now()))
            return self._projection(conn, owner, reference)

    def binding(self, conn, owner, reference):
        from .connections import TrustedConnectionBinding
        row, body = self._row(conn, owner, reference)
        if row["state"] == "REVOKED":
            raise HTTPException(409, "REMOTE_REVOKED")
        if row["state"] != "VERIFIED":
            raise HTTPException(409, "REMOTE_NOT_VERIFIED")
        verification = row["verification"]
        if (not isinstance(verification, dict) or digest(verification) != row["verification_hash"]
                or verification.get("configRevision") != body["revision"]
                or verification.get("policyRevision") != body["policyRevision"]):
            raise HTTPException(409, "REMOTE_INTEGRITY")
        provider = self._provider(body)
        try:
            expires = datetime.fromisoformat(verification["expiresAt"])
            if expires.tzinfo is None or expires.utcoffset() != timedelta(0):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise HTTPException(409, "REMOTE_INTEGRITY") from None
        if self.connections._at() >= expires:
            raise HTTPException(409, "REMOTE_VERIFICATION_EXPIRED")
        if not provider.authorized(owner, body["configuration"]):
            raise HTTPException(409, "REMOTE_CREDENTIAL_UNAVAILABLE")
        capabilities = provider.effective_capabilities(body['configuration']) if callable(getattr(provider, 'effective_capabilities', None)) else provider.capabilities
        if frozenset(verification["capabilities"]) != capabilities:
            raise HTTPException(409, "REMOTE_POLICY_CHANGED")
        return TrustedConnectionBinding(owner, provider.kind, provider.provider_id, capabilities,
            verification["revision"], expires_at=expires.astimezone(timezone.utc), available=True,
            opaque_handle=provider.handle(owner, body["configuration"]),
            handle_ref="remote-handle-" + digest({"configuration": body, "verification": verification}))


class ConfigureRemoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providerId: str = Field(min_length=1, max_length=200)
    origin: str = Field(min_length=1, max_length=512)
    credentialRef: str = Field(min_length=1, max_length=200)
    credentialRevision: str = Field(min_length=1, max_length=200)
    projectId: str | None = Field(default=None, min_length=1, max_length=200)
    projectCreation: Literal[True] | None = None
    authMode: Literal["bearer", "basic-proxy"] | None = None
    sessionTemplateId: str | None = Field(default=None, min_length=1, max_length=160)
    requestId: str = Field(min_length=1, max_length=200)


class RemoteCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=200)


def personal_connection_router(auth, service):
    router = APIRouter(prefix="/api/factory/personal-remotes", tags=["personal-remotes"])
    def owner(request):
        return auth.user(request)["id"]
    @router.get("/providers")
    def providers(request: Request):
        return service.available_providers(owner(request))
    @router.get("")
    def listing(request: Request):
        return service.list(owner(request))
    @router.post("", status_code=201)
    def create(body: ConfigureRemoteRequest, request: Request):
        values = body.model_dump(exclude_none=True)
        return service.configure(owner(request), values.pop("providerId"),
            {key: value for key, value in values.items() if key != "requestId"}, body.requestId)
    @router.get("/requests/{request_id}")
    def request_result(request_id: str, request: Request):
        return service.request_result(owner(request), request_id)
    @router.get("/{reference}")
    def inspect(reference: str, request: Request):
        return service.inspect(owner(request), reference)
    @router.post("/{reference}/configure")
    def configure(reference: str, body: ConfigureRemoteRequest, request: Request):
        values = body.model_dump(exclude_none=True)
        return service.configure(owner(request), values.pop("providerId"),
            {key: value for key, value in values.items() if key != "requestId"}, body.requestId, reference=reference)
    @router.post("/{reference}/verify")
    def verify(reference: str, body: RemoteCommandRequest, request: Request):
        return service.verify(owner(request), reference, body.requestId)
    @router.post("/{reference}/revoke")
    def revoke(reference: str, body: RemoteCommandRequest, request: Request):
        return service.revoke(owner(request), reference, body.requestId)
    return router

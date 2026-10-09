"""Opt-in encrypted credential custody. Never install from owner/model inputs.

Only ciphertext enters SQL. Keys come from trusted operator injection, not SQL or
owner requests. The API must run behind the authenticated browser/CSRF bridge.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import json
import hmac
import secrets
from typing import Protocol
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Column, JSON, LargeBinary, MetaData, String, Table, select

from .personal_remote_provider import RemoteConnectionError, SecretLease, origin

MAX_CREDENTIAL_REQUEST_BYTES = 24_576


class CredentialVaultError(ValueError):
    def __init__(self):
        super().__init__("CREDENTIAL_UNAVAILABLE")


class CredentialRequestRejected(CredentialVaultError):
    """Definitive input/authority conflict with no committed mutation."""


class CredentialVault(Protocol):
    """Organization vaults may replace SQL while preserving exact scope/revision."""
    def create(self, *, owner, provider_id, destination, username, password, request_id=None) -> dict: ...
    def rotate(self, *, owner, reference, revision, username, password, request_id=None) -> dict: ...
    def revoke(self, *, owner, reference, revision, request_id=None) -> dict: ...
    def capabilities(self) -> dict: ...
    def list(self, *, owner) -> list[dict]: ...
    def recover(self, *, owner, request_id) -> dict | None: ...
    def authorize(self, *, owner, reference, revision, provider_id, destination) -> bool: ...
    def resolve(self, *, owner, reference, revision, provider_id, destination) -> SecretLease: ...


class VaultSecretProvider:
    def __init__(self, vault: CredentialVault, provider_id: str):
        self.vault, self.provider_id = vault, provider_id

    def authorize(self, *, owner, reference, revision, destination):
        return self.vault.authorize(owner=owner, reference=reference, revision=revision,
                                    provider_id=self.provider_id, destination=destination)

    def resolve(self, *, owner, reference, revision, destination):
        return self.vault.resolve(owner=owner, reference=reference, revision=revision,
                                  provider_id=self.provider_id, destination=destination)


class EncryptedCredentialVault:
    def __init__(self, engine, master_key: bytes, provider_policies: Mapping[str, Callable[[str], str]]):
        # repr never includes key or an AES object; no environment/file lookup.
        try:
            if not isinstance(master_key, bytes) or len(master_key) != 32:
                raise CredentialVaultError()
            self._cipher = AESGCM(master_key)
            self._intent_key = hmac.digest(master_key, b"factory-vault-command-intent-v1", "sha256")
            self._policies = dict(provider_policies)
            if not self._policies or any(not self._identifier(provider) or not callable(policy)
                    for provider, policy in self._policies.items()):
                raise CredentialVaultError()
            self.engine = engine
            self._read_context: ContextVar | None = None
            metadata = MetaData()
            self.credentials = Table("af_encrypted_credentials", metadata,
                Column("reference", String, primary_key=True), Column("owner_id", String, nullable=False),
                Column("revision", String, nullable=False), Column("provider_id", String, nullable=False),
                Column("destination", String, nullable=False), Column("state", String, nullable=False),
                Column("nonce", LargeBinary, nullable=False), Column("ciphertext", LargeBinary, nullable=False))
            self.commands = Table("af_credential_commands", metadata,
                Column("owner_id", String, primary_key=True), Column("request_id", String, primary_key=True),
                Column("fingerprint", String, nullable=False), Column("result", JSON, nullable=False))
            metadata.create_all(engine)
        except Exception:
            raise CredentialVaultError() from None

    def __repr__(self):
        return "EncryptedCredentialVault(master_key=<redacted>)"

    def bind_read_context(self, context):
        """Trusted startup hook; join metadata reads, never credential writes."""
        if not isinstance(context, ContextVar) or self._read_context not in (None, context):
            raise CredentialVaultError()
        self._read_context = context

    @contextmanager
    def _read(self):
        borrowed = self._read_context.get() if self._read_context is not None else None
        if borrowed is not None:
            if borrowed.engine is not self.engine or borrowed.closed:
                raise CredentialVaultError()
            yield borrowed
        else:
            with self.engine.connect() as conn:
                yield conn

    @staticmethod
    def _identifier(value):
        return isinstance(value, str) and 0 < len(value) <= 200 and all(
            c.isascii() and (c.isalnum() or c in "-_.:@") for c in value)

    def secret_provider(self, provider_id):
        if provider_id not in self._policies:
            raise CredentialVaultError()
        return VaultSecretProvider(self, provider_id)

    def _destination(self, provider_id, destination):
        try:
            normalized = origin(destination)
            policy = self._policies.get(provider_id)
            if policy is None or policy(normalized) != normalized:
                raise CredentialRequestRejected()
            return normalized
        except RemoteConnectionError:
            raise CredentialRequestRejected() from None

    @staticmethod
    def _aad(row):
        return json.dumps(["factory-credential-v1", row["owner_id"], row["reference"], row["revision"],
                           row["provider_id"], row["destination"]], separators=(",", ":")).encode()

    def _encrypt(self, row, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            raise CredentialRequestRejected()
        try:
            SecretLease(username, password)
        except RemoteConnectionError:
            raise CredentialRequestRejected() from None
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(nonce, json.dumps([username, password], ensure_ascii=True).encode(), self._aad(row))
        return {"nonce": nonce, "ciphertext": ciphertext}

    @staticmethod
    def _public(row):
        return {"credentialRef": row["reference"], "credentialRevision": row["revision"],
                "providerId": row["provider_id"], "destination": row["destination"], "status": row["state"].lower()}

    def _row(self, conn, owner, reference, revision, *, current_policy=True):
        if not all(self._identifier(value) for value in (owner, reference, revision)):
            raise CredentialRequestRejected()
        row = conn.execute(select(self.credentials).where(self.credentials.c.owner_id == owner,
            self.credentials.c.reference == reference, self.credentials.c.revision == revision,
            self.credentials.c.state == "ACTIVE")).mappings().first()
        if row is None:
            raise CredentialRequestRejected()
        if current_policy:
            self._destination(row["provider_id"], row["destination"])
        return dict(row)

    def capabilities(self):
        return {"enabled": True, "providerIds": sorted(self._policies)}

    def list(self, *, owner):
        try:
            if not self._identifier(owner):
                raise CredentialRequestRejected()
            with self._read() as conn:
                rows = conn.execute(select(*(self.credentials.c[key] for key in
                    ("reference", "revision", "provider_id", "destination", "state")))
                    .where(self.credentials.c.owner_id == owner)
                                    .order_by(self.credentials.c.reference).limit(100)).mappings().all()
                return [self._public(row) for row in rows]
        except CredentialRequestRejected:
            raise
        except Exception:
            raise CredentialVaultError() from None

    def _command(self, conn, owner, request_id):
        if not self._identifier(owner) or not self._identifier(request_id):
            raise CredentialRequestRejected()
        return conn.execute(select(self.commands).where(self.commands.c.owner_id == owner,
            self.commands.c.request_id == request_id)).mappings().first()

    def recover(self, *, owner, request_id):
        try:
            with self._read() as conn:
                previous = self._command(conn, owner, request_id)
                return previous["result"] if previous else None
        except CredentialRequestRejected:
            raise
        except Exception:
            raise CredentialVaultError() from None

    def _mutate(self, owner, request_id, intent, execute):
        # A keyed, domain-separated fingerprint prevents database-only password
        # guessing. No secret plaintext or unkeyed password hash reaches SQL.
        request_id = uuid4().hex if request_id is None else request_id
        try:
            if not self._identifier(owner) or not self._identifier(request_id):
                raise CredentialRequestRejected()
            fingerprint = hmac.digest(self._intent_key,
                json.dumps([owner, request_id, intent], sort_keys=True, ensure_ascii=True,
                           separators=(",", ":")).encode(), "sha256").hex()
            with self.engine.begin() as conn:
                previous = self._command(conn, owner, request_id)
                if previous:
                    if not hmac.compare_digest(previous["fingerprint"], fingerprint):
                        raise CredentialRequestRejected()
                    return previous["result"]
                # Reserve the immutable request first. Concurrent duplicate calls
                # block here and roll back before making any credential change.
                conn.execute(self.commands.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=fingerprint, result={}))
                result = execute(conn)
                conn.execute(self.commands.update().where(self.commands.c.owner_id == owner,
                    self.commands.c.request_id == request_id).values(result=result))
                return result
        except CredentialRequestRejected:
            raise
        except Exception:
            # A racing exact request may now be committed. This is read-only
            # recovery, never an automatic rerun of a secret mutation.
            try:
                with self.engine.connect() as conn:
                    previous = self._command(conn, owner, request_id)
                    if previous and hmac.compare_digest(previous["fingerprint"], fingerprint):
                        return previous["result"]
            except Exception:
                pass
            raise CredentialVaultError() from None

    def create(self, *, owner, provider_id, destination, username, password, request_id=None):
        def execute(conn):
            row = {"reference": "credential-" + uuid4().hex, "revision": uuid4().hex, "owner_id": owner,
                   "provider_id": provider_id, "destination": self._destination(provider_id, destination), "state": "ACTIVE"}
            row.update(self._encrypt(row, username, password))
            conn.execute(self.credentials.insert().values(**row))
            return self._public(row)
        return self._mutate(owner, request_id,
            ["create", provider_id, destination, username, password], execute)

    def rotate(self, *, owner, reference, revision, username, password, request_id=None):
        def execute(conn):
            row = self._row(conn, owner, reference, revision)
            row["revision"] = uuid4().hex
            values = {"revision": row["revision"], **self._encrypt(row, username, password)}
            result = conn.execute(self.credentials.update().where(self.credentials.c.owner_id == owner,
                self.credentials.c.reference == reference, self.credentials.c.revision == revision,
                self.credentials.c.state == "ACTIVE").values(**values))
            if result.rowcount != 1:
                raise CredentialRequestRejected()
            return self._public(row)
        return self._mutate(owner, request_id,
            ["rotate", reference, revision, username, password], execute)

    def revoke(self, *, owner, reference, revision, request_id=None):
        def execute(conn):
            # Retiring a provider/target policy must not prevent an owner from
            # erasing an exact owned credential. No decryption or use is allowed.
            row = self._row(conn, owner, reference, revision, current_policy=False)
            result = conn.execute(self.credentials.update().where(self.credentials.c.owner_id == owner,
                self.credentials.c.reference == reference, self.credentials.c.revision == revision,
                self.credentials.c.state == "ACTIVE").values(state="REVOKED", ciphertext=b"", nonce=b""))
            if result.rowcount != 1:
                raise CredentialRequestRejected()
            row["state"] = "REVOKED"
            return self._public(row)
        return self._mutate(owner, request_id, ["revoke", reference, revision], execute)

    def authorize(self, *, owner, reference, revision, provider_id, destination):
        try:
            with self._read() as conn:
                row = self._row(conn, owner, reference, revision)
                return (row["provider_id"], row["destination"]) == (provider_id, self._destination(provider_id, destination))
        except Exception:
            return False

    def resolve(self, *, owner, reference, revision, provider_id, destination):
        try:
            with self._read() as conn:
                row = self._row(conn, owner, reference, revision)
                if (row["provider_id"], row["destination"]) != (provider_id, self._destination(provider_id, destination)):
                    raise CredentialVaultError()
                username, password = json.loads(self._cipher.decrypt(row["nonce"], row["ciphertext"], self._aad(row)))
                return SecretLease(username, password)
        except Exception:
            raise CredentialVaultError() from None


async def _body(request: Request, fields: set[str]):
    # No Pydantic validation errors: they can reflect invalid secret input.
    try:
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise CredentialRequestRejected()
        if int(request.headers.get("content-length", "0")) > MAX_CREDENTIAL_REQUEST_BYTES:
            raise CredentialRequestRejected()
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_CREDENTIAL_REQUEST_BYTES:
                raise CredentialRequestRejected()
            data.extend(chunk)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise CredentialRequestRejected()
                result[key] = value
            return result
        body = json.loads(data, object_pairs_hook=unique)
        if not isinstance(body, dict) or set(body) != fields or any(not isinstance(v, str) for v in body.values()):
            raise CredentialRequestRejected()
        return body
    except Exception:
        raise CredentialRequestRejected() from None


def credential_vault_router(auth, vault: CredentialVault):
    router = APIRouter(prefix="/api/factory/personal-credentials", tags=["personal-credentials"])

    async def command(request, operation, reference=None):
        try:
            try:
                owner = auth.user(request)["id"]
                auth.require(owner, "read" if operation == "revoke" else "run")
            except HTTPException as error:
                return JSONResponse({"detail": error.detail if isinstance(error.detail, dict) and error.detail.get("code") == "EXPECTED_OWNER_MISMATCH" else "CREDENTIAL_REQUEST_REJECTED"}, status_code=
                    error.status_code if error.status_code in {401, 403} else 503,
                    headers={"Cache-Control": "private, no-store"})
            fields = {"credentialRevision"} if operation == "revoke" else {"username", "password"}
            fields |= {"providerId", "destination"} if operation == "create" else {"credentialRevision"}
            fields.add("requestId")
            body = await _body(request, fields)
            if operation == "create":
                result = vault.create(owner=owner, provider_id=body["providerId"], destination=body["destination"],
                                      username=body["username"], password=body["password"], request_id=body["requestId"])
            else:
                args = dict(owner=owner, reference=reference, revision=body["credentialRevision"], request_id=body["requestId"])
                if operation == "rotate":
                    args.update(username=body["username"], password=body["password"], request_id=body["requestId"])
                result = getattr(vault, operation)(**args)
            return JSONResponse(result, status_code=201 if operation == "create" else 200,
                                headers={"Cache-Control": "private, no-store"})
        except CredentialRequestRejected:
            return JSONResponse({"detail": "CREDENTIAL_REQUEST_REJECTED"}, status_code=400,
                                headers={"Cache-Control": "private, no-store"})
        except Exception:
            return JSONResponse({"detail": "CREDENTIAL_UNAVAILABLE"}, status_code=503,
                                headers={"Cache-Control": "private, no-store"})

    def read(request, operation, request_id=None):
        try:
            try:
                owner = auth.user(request)["id"]
                auth.require(owner, "read")
            except HTTPException as error:
                return JSONResponse({"detail": error.detail if isinstance(error.detail, dict) and error.detail.get("code") == "EXPECTED_OWNER_MISMATCH" else "CREDENTIAL_REQUEST_REJECTED"}, status_code=
                    error.status_code if error.status_code in {401, 403} else 503,
                    headers={"Cache-Control": "private, no-store"})
            if operation == "capabilities":
                result = vault.capabilities()
            elif operation == "list":
                result = vault.list(owner=owner)
            else:
                result = vault.recover(owner=owner, request_id=request_id)
            return JSONResponse(result if result is not None else {"detail": "CREDENTIAL_REQUEST_NOT_FOUND"},
                status_code=200 if result is not None else 404, headers={"Cache-Control": "private, no-store"})
        except CredentialRequestRejected:
            return JSONResponse({"detail": "CREDENTIAL_REQUEST_REJECTED"}, status_code=400,
                                headers={"Cache-Control": "private, no-store"})
        except Exception:
            return JSONResponse({"detail": "CREDENTIAL_UNAVAILABLE"}, status_code=503,
                headers={"Cache-Control": "private, no-store"})

    @router.get("/capabilities")
    def capabilities(request: Request):
        return read(request, "capabilities")

    @router.get("")
    def listing(request: Request):
        return read(request, "list")

    @router.get("/requests/{request_id}")
    def recovery(request_id: str, request: Request):
        return read(request, "recover", request_id)

    @router.post("")
    async def create(request: Request):
        return await command(request, "create")

    @router.post("/{reference}/rotate")
    async def rotate(reference: str, request: Request):
        return await command(request, "rotate", reference)

    @router.post("/{reference}/revoke")
    async def revoke(reference: str, request: Request):
        return await command(request, "revoke", reference)

    return router

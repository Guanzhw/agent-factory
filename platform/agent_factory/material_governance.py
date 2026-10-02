"""Inert material import, exact-version admin publication and current withdrawal.

Governance metadata never changes a material's immutable body/hash or historical
plans. The factory must wire filter_active and require_materials_current; this
module starts no tool, interpreter, installer, model or external connection.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import math
import re
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator
from sqlalchemy import Boolean, Column, Integer, JSON, MetaData, String, Table, func, select, text

from .catalog import SEEDS
from .plan_policy import ToolContract, tools_for_contract
from .store import digest, now

KINDS = Literal["skill", "tool", "prompt", "knowledge", "model", "environment"]
LICENSES = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "CC-BY-4.0")
SECRET_KEYS = re.compile(r"^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|client[_-]?secret|credentials|private[_-]?key|authorization|cookie)$", re.I)
SECRET_TEXT = re.compile(r"(?:\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}|\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{16,}|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9_.-]{16,}|\bhttps?://[^/\s:@]+:[^/\s@]+@|\b(?:api[_-]?key|password|client[_-]?secret)\s*[:=]\s*['\"]?[^\s'\"]{8,})", re.I)


def _inert_runtime_config(value: Any, *, depth: int = 0, count: list[int] | None = None) -> Any:
    """Data only; installed descriptors still validate their own exact schema.

    Binding config contains no executable resolution hints or user connection
    references. In particular, importing a material never imports Python from
    its content/config, opens a path/URL, or selects a credential.
    """
    count = count if count is not None else [0]
    count[0] += 1
    if depth > 6 or count[0] > 256:
        raise ValueError("Runtime config exceeds bounded JSON complexity")
    if isinstance(value, dict):
        if len(value) > 32:
            raise ValueError("Runtime config object exceeds field budget")
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
                raise ValueError("Runtime config keys must be bounded identifiers")
            compact = re.sub(r"[^a-z0-9]", "", key.lower())
            forbidden = {"factory", "callable", "module", "class", "python", "pythonpath", "command", "cmd",
                         "shell", "script", "executable", "binary", "path", "directory", "cwd", "home", "url",
                         "uri", "endpoint", "host", "port", "env", "environment", "headers", "connectionref", "token", "key"}
            sensitive = ("credential", "secret", "password", "apikey", "accesstoken", "refreshtoken",
                         "privatekey", "authorization", "cookie", "clientsecret", "connection")
            execution_suffixes = ("factory", "callable", "module", "class", "command", "shell", "script", "executable",
                                  "path", "directory", "url", "uri", "endpoint")
            if compact in forbidden or compact.endswith(execution_suffixes) or (compact.startswith(sensitive) and key != "connectionName") or SECRET_KEYS.fullmatch(key):
                raise ValueError("Runtime config cannot carry execution or connection authority")
            if key == "connectionName" and (not isinstance(item, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}", item)):
                raise ValueError("connectionName must be a bounded symbolic application dependency")
            result[key] = _inert_runtime_config(item, depth=depth + 1, count=count)
        return result
    if isinstance(value, list):
        if len(value) > 32:
            raise ValueError("Runtime config list exceeds item budget")
        return [_inert_runtime_config(item, depth=depth + 1, count=count) for item in value]
    if isinstance(value, str):
        if SECRET_TEXT.search(value) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@+-]{0,255}", value):
            raise ValueError("Runtime config strings must be inert identifiers, never paths, URLs or code")
        return value
    if value is None or type(value) is bool:
        return value
    if type(value) in {int, float} and abs(value) <= 10**12 and math.isfinite(value):
        return value
    raise ValueError("Runtime config requires bounded finite JSON scalars")


class RuntimeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    adapterId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    revision: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    config: dict[str, Any]

    @field_validator("adapterId", "revision")
    @classmethod
    def credential_free_identifier(cls, value: str) -> str:
        if SECRET_TEXT.search(value):
            raise ValueError("Runtime identifiers cannot carry credentials")
        return value

    @field_validator("config")
    @classmethod
    def inert_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        result = _inert_runtime_config(value)
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 8192:
            raise ValueError("Runtime binding config exceeds 8 KiB")
        return result


def normalize_runtime_binding(value: Any) -> dict[str, Any]:
    """Normalize inert data only; this does not establish adapter availability."""
    try:
        return RuntimeBinding.model_validate(value).model_dump()
    except ValidationError as error:
        raise HTTPException(422, "Invalid inert runtime binding") from error


class PinnedRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    version: int = Field(strict=True, gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["original", "upstream"] = "original"
    source: str | None = Field(default=None, max_length=1000)
    revision: str | None = Field(default=None, min_length=1, max_length=200)
    notice: str = Field(default="Original manager-authored material.", max_length=4000)


class MaterialDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: KINDS
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    content: str = Field(min_length=1, max_length=16000)
    dependencies: list[PinnedRef] = Field(default_factory=list, max_length=30)
    permissions: list[str] = Field(default_factory=list, max_length=30)
    compatibility: list[str] = Field(default_factory=lambda: ["agno:3.1.0"], max_length=30)
    inputSchema: dict[str, Any] = Field(default_factory=dict)
    outputSchema: dict[str, Any] = Field(default_factory=dict)
    license: str = "MIT"
    provenance: Provenance = Field(default_factory=Provenance)
    runtimeBinding: RuntimeBinding | None = None


@dataclass(frozen=True)
class GovernanceConfig:
    review_mode: Literal["separate-admin", "demo-self-review"] = "separate-admin"
    revision: str = "material-governance-v1"
    tool_contract: ToolContract = "legacy-v1"

    def __post_init__(self):
        tools_for_contract(self.tool_contract)
        if self.tool_contract != "legacy-v1" and self.revision == "material-governance-v1":
            raise ValueError("Registered runtime tools require a distinct governance revision")
        if self.review_mode not in {"separate-admin", "demo-self-review"}:
            raise ValueError("Unsupported material publication review mode")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", self.revision):
            raise ValueError("Material governance revision must be a bounded identifier")

    @property
    def fingerprint(self):
        body = asdict(self)
        if self.tool_contract == "legacy-v1":
            del body["tool_contract"]
        return digest({**body, "licenses": LICENSES, "toolBindings": self.known_tools,
                       "schemaVersion": "structured-material/v1"})

    @property
    def known_tools(self) -> dict[str, str]:
        return tools_for_contract(self.tool_contract)


class MaterialGovernance:
    def __init__(self, store: Any, auth: Any, config: GovernanceConfig | None = None):
        self.store, self.auth = store, auth
        self.metadata = MetaData()
        self.materials = Table("af_materials", MetaData(), autoload_with=store.engine)
        self.audit = Table("af_audit", MetaData(), autoload_with=store.engine)
        self.configs = Table("af_material_governance_configs", self.metadata,
            Column("revision", String, primary_key=True), Column("hash", String, nullable=False), Column("body", JSON, nullable=False))
        self.current_config = Table("af_material_governance_current", self.metadata,
            Column("id", String, primary_key=True), Column("revision", String, nullable=False))
        self.versions = Table("af_material_governance", self.metadata,
            Column("material_id", String, primary_key=True), Column("version", Integer, primary_key=True),
            Column("author_id", String, nullable=False), Column("material_sha", String, nullable=False),
            Column("immutable_digest", String, nullable=False), Column("state", String, nullable=False),
            Column("bootstrap", Boolean, nullable=False, default=False), Column("created_at", String, nullable=False),
            Column("updated_at", String, nullable=False), Column("reason", String), Column("review_id", String))
        self.reviews = Table("af_material_publication_reviews", self.metadata,
            Column("id", String, primary_key=True), Column("material_id", String, nullable=False),
            Column("version", Integer, nullable=False), Column("author_id", String, nullable=False),
            Column("material_sha", String, nullable=False), Column("immutable_digest", String, nullable=False),
            Column("policy_revision", String, nullable=False), Column("policy_hash", String, nullable=False),
            Column("requested_by", String, nullable=False), Column("created_at", String, nullable=False),
            Column("decision", String, nullable=False), Column("reviewer_id", String), Column("decided_at", String))
        self.commands = Table("af_material_commands", self.metadata,
            Column("actor_id", String, primary_key=True), Column("request_id", String, primary_key=True),
            Column("fingerprint", String, nullable=False), Column("action", String, nullable=False),
            Column("result", JSON, nullable=False), Column("created_at", String, nullable=False))
        self.metadata.create_all(store.engine)
        initial = config or GovernanceConfig()
        self._mode(initial)
        with self._write() as conn:
            self._register_config(conn, initial)
            revision = conn.execute(select(self.current_config.c.revision)).scalar()
            if revision is None:
                conn.execute(self.current_config.insert().values(id="current", revision=initial.revision))
            elif revision != initial.revision:
                raise ValueError("Material governance configuration differs from persisted current revision")

    def _mode(self, config):
        if config.review_mode == "demo-self-review" and not self.store.settings.demo:
            raise ValueError("Self-review compatibility is restricted to explicitly configured demo mode")

    def _lock(self, conn, key="af_material_governance"):
        if self.store.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

    @contextmanager
    def _read(self):
        shared = getattr(self.store, "_connection", None)
        existing = shared.get() if shared is not None else None
        if existing is not None:
            yield existing
        else:
            with self.store.engine.connect() as conn:
                yield conn

    @contextmanager
    def _write(self):
        with self.store.engine.begin() as conn:
            self._lock(conn)
            shared = getattr(self.store, "_connection", None)
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    def _register_config(self, conn, config):
        row = conn.execute(select(self.configs).where(self.configs.c.revision == config.revision)).mappings().first()
        if row and row["hash"] != config.fingerprint:
            raise ValueError("A governance revision cannot be rebound")
        if not row:
            conn.execute(self.configs.insert().values(revision=config.revision, hash=config.fingerprint, body=asdict(config)))

    def _config(self, conn):
        row = conn.execute(select(self.configs).join(self.current_config,
            self.current_config.c.revision == self.configs.c.revision)).mappings().first()
        if not row:
            raise HTTPException(503, "Material governance configuration is unavailable")
        config = GovernanceConfig(**row["body"])
        if row["hash"] != config.fingerprint:
            raise HTTPException(409, "Immutable material governance configuration changed")
        self._mode(config)
        return config

    def current(self):
        with self._read() as conn:
            config = self._config(conn)
        return {**asdict(config), "fingerprint": config.fingerprint, "demoCompatibility": config.review_mode == "demo-self-review",
                "taskApprovalSeparate": True, "importExecutesCode": False}

    def replace_configuration(self, config: GovernanceConfig, *, expected_revision: str):
        """Trusted operator method, never registered as a user HTTP mutation."""
        self._mode(config)
        with self._write() as conn:
            if self._config(conn).revision != expected_revision:
                raise HTTPException(409, "GOVERNANCE_REVISION_CONFLICT: configuration changed")
            self._register_config(conn, config)
            conn.execute(self.current_config.update().values(revision=config.revision))
        return self.current()

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", key):
            raise HTTPException(400, "A bounded material governance request ID is required")

    @staticmethod
    def _safe_data(value, depth=0, count=None):
        count = count if count is not None else [0]
        count[0] += 1
        if depth > 12 or count[0] > 3000:
            raise HTTPException(422, "Structured material exceeds bounded JSON complexity")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or SECRET_KEYS.fullmatch(key) or SECRET_TEXT.search(key):
                    raise HTTPException(422, "Credentials belong in trusted connections, not materials")
                if key == "$ref" and (not isinstance(item, str) or not item.startswith("#/")):
                    raise HTTPException(422, "External schema references are unsupported")
                MaterialGovernance._safe_data(item, depth + 1, count)
        elif isinstance(value, list):
            for item in value:
                MaterialGovernance._safe_data(item, depth + 1, count)
        elif isinstance(value, str):
            if SECRET_TEXT.search(value):
                raise HTTPException(422, "Credentials belong in trusted connections, not materials")
        elif isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(422, "Nonfinite JSON numbers are unsupported")
        elif value is not None and not isinstance(value, (int, float, bool)):
            raise HTTPException(422, "Material import accepts JSON values only")

    def validate_definition(self, definition: Mapping, *, imported=False):
        self._safe_data(definition)
        if imported and ("license" not in definition or "provenance" not in definition):
            raise HTTPException(422, "Import requires explicit license and provenance")
        try:
            value = MaterialDefinition.model_validate(definition).model_dump(exclude_none=True)
        except ValidationError as error:
            raise HTTPException(422, "Invalid structured material fields") from error
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 65536:
            raise HTTPException(422, "Material definition exceeds 64 KiB")
        if value["license"] not in LICENSES or "agno:3.1.0" not in value["compatibility"]:
            raise HTTPException(422, "Material license or runtime compatibility is unsupported")
        provenance = value["provenance"]
        if provenance["kind"] == "upstream":
            if not provenance.get("source") or not provenance.get("revision") or not provenance.get("notice", "").strip():
                raise HTTPException(422, "Upstream import requires source, pinned revision and preserved notice")
        if provenance.get("source"):
            try:
                parsed = urlsplit(provenance["source"])
                parsed.port
            except ValueError as error:
                raise HTTPException(422, "Provenance source is malformed") from error
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise HTTPException(422, "Provenance source must be a credential-free HTTPS reference")
        with self._read() as conn:
            known_tools = self._config(conn).known_tools
        if "runtimeBinding" in value and value["kind"] not in {"tool", "model", "knowledge", "environment"}:
            raise HTTPException(422, "Runtime bindings are limited to tool, model, knowledge and environment materials")
        if not set(value["permissions"]) <= set(known_tools.values()):
            raise HTTPException(422, "Material requests authority outside registered capabilities")
        reserved = next((seed for seed in SEEDS if seed[0] == value.get("id")), None)
        if reserved and reserved[1] != value["kind"]:
            raise HTTPException(422, "Reserved material kind cannot change")
        if value["kind"] == "tool":
            if value["content"] not in known_tools or set(value["permissions"]) != {known_tools[value["content"]]}:
                raise HTTPException(422, "Tool material must bind exactly one registered tool and capability")
            if reserved and reserved[3] != value["content"]:
                raise HTTPException(422, "Reserved tool binding cannot change")
        return value

    @staticmethod
    def _immutable(body):
        return digest({key: value for key, value in body.items() if key != "published"})

    def _material(self, conn, mid, version):
        row = conn.execute(select(self.materials).where(self.materials.c.id == mid, self.materials.c.version == version)).mappings().first()
        if not row:
            raise HTTPException(404, "Material version not found")
        body = row["body"]
        actual = digest({key: val for key, val in body.items() if key not in {"sha256", "published", "createdAt"}})
        if body.get("id") != mid or body.get("version") != version or body.get("sha256") != actual:
            raise HTTPException(409, "Immutable material integrity mismatch")
        return dict(row)

    def _version(self, conn, mid, version):
        row = conn.execute(select(self.versions).where(self.versions.c.material_id == mid, self.versions.c.version == version)).mappings().first()
        if not row:
            raise HTTPException(409, "UNREVIEWED_MATERIAL: version has no trusted governance record")
        return dict(row)

    def _admin(self, actor):
        try:
            self.auth.require(actor, "agent_os:admin")
            return True
        except HTTPException as error:
            if error.status_code == 403:
                return False
            raise

    def _owner_admin(self, actor, version):
        self.auth.require(actor, "components:read")
        if actor != version["author_id"] and not self._admin(actor):
            raise HTTPException(404, "Scoped material governance record not found")

    def _active(self, conn, material, config):
        body = material["body"]
        if body.get("kind") == "tool" and (body.get("content") not in config.known_tools or
                set(body.get("permissions", [])) != {config.known_tools.get(body.get("content"))}):
            raise HTTPException(409, "Tool binding is outside the current registered contract")
        version = self._version(conn, body["id"], body["version"])
        if version["material_sha"] != body["sha256"] or version["immutable_digest"] != self._immutable(body):
            raise HTTPException(409, "Material differs from reviewed immutable version")
        if version["state"] != "published" or not material["published"]:
            raise HTTPException(409, "INACTIVE_MATERIAL: exact version is draft, withdrawn or archived")
        if version["bootstrap"]:
            if not self.store.settings.demo:
                raise HTTPException(409, "Demo bootstrap approval cannot authorize production")
        else:
            review = conn.execute(select(self.reviews).where(self.reviews.c.id == version["review_id"])).mappings().first()
            if not review or review["decision"] != "approved" or review["material_sha"] != body["sha256"] or review["immutable_digest"] != self._immutable(body):
                raise HTTPException(409, "Published material lacks exact administrator review")
            if review["reviewer_id"] == version["author_id"] and config.review_mode != "demo-self-review":
                raise HTTPException(409, "REVIEW_SEPARATION_REQUIRED: current policy requires a distinct administrator")
        return version

    def _dependencies(self, conn, body, config, allowed_refs=None):
        visited, visiting = set(), set()

        def visit(ref, depth):
            key = (ref["id"], ref["version"], ref["sha256"])
            if key in visiting:
                raise HTTPException(409, "Pinned material dependency cycle")
            if key in visited:
                return
            if depth > 8 or len(visited) + len(visiting) >= 30:
                raise HTTPException(409, "Pinned dependency closure exceeds bounds")
            if allowed_refs is not None and key not in allowed_refs:
                raise HTTPException(409, "Plan omitted a pinned transitive material dependency")
            material = self._material(conn, ref["id"], ref["version"])
            if material["body"]["sha256"] != ref["sha256"]:
                raise HTTPException(409, "Pinned dependency digest differs from stored material")
            self._active(conn, material, config)
            visiting.add(key)
            for child in material["body"].get("dependencies", []):
                visit(PinnedRef.model_validate(child).model_dump(), depth + 1)
            visiting.remove(key)
            visited.add(key)

        for ref in body.get("dependencies", []):
            visit(ref, 1)

    def _old_command(self, conn, actor, key, fingerprint):
        self._key(key)
        row = conn.execute(select(self.commands).where(self.commands.c.actor_id == actor, self.commands.c.request_id == key)).mappings().first()
        if row and row["fingerprint"] != fingerprint:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT: material governance intent changed")
        return row["result"] if row else None

    def _record(self, conn, actor, key, fingerprint, action, result):
        conn.execute(self.commands.insert().values(actor_id=actor, request_id=key, fingerprint=fingerprint,
                     action=action, result=result, created_at=now()))
        return result

    def create_draft(self, actor, definition, request_id):
        return self._create(actor, [definition], request_id, imported=False)["materials"][0]

    def import_definitions(self, actor, definitions, request_id):
        return self._create(actor, definitions, request_id, imported=True)

    def _create(self, actor, definitions, request_id, imported):
        self.auth.require(actor, "components:write")
        if not isinstance(definitions, list) or not 1 <= len(definitions) <= 30:
            raise HTTPException(422, "Import must contain one through thirty structured definitions")
        values = [self.validate_definition(value, imported=imported) for value in definitions]
        if len(json.dumps(values, ensure_ascii=False).encode()) > 262144:
            raise HTTPException(422, "Structured import exceeds 256 KiB")
        fingerprint = digest({"operation": "import" if imported else "draft", "definitions": values})
        with self._write() as conn:
            old = self._old_command(conn, actor, request_id, fingerprint)
            if old is not None:
                return old
            config = self._config(conn)
            results = []
            for value in values:
                if value["kind"] == "tool" and (value["content"] not in config.known_tools or
                        set(value["permissions"]) != {config.known_tools.get(value["content"])}):
                    raise HTTPException(422, "Tool contract changed before material creation")
                mid = value.get("id") or str(uuid4())
                self._lock(conn, "material:" + mid)
                latest = conn.execute(select(func.max(self.materials.c.version)).where(self.materials.c.id == mid)).scalar() or 0
                if latest:
                    prior = conn.execute(select(self.versions).where(self.versions.c.material_id == mid,
                        self.versions.c.version == latest)).mappings().first()
                    if (prior is None or prior["author_id"] != actor) and not self._admin(actor):
                        raise HTTPException(403, "A manager cannot overwrite another author's material lineage")
                self._dependencies(conn, value, config)
                at = now()
                body = {**value, "id": mid, "version": latest + 1, "createdAt": at, "published": False,
                        "archived": False, "origin": "structured-import" if imported else "manager-authored"}
                body["sha256"] = digest({key: val for key, val in body.items() if key not in {"sha256", "published", "createdAt"}})
                conn.execute(self.materials.insert().values(id=mid, version=latest + 1, body=body, published=False))
                conn.execute(self.versions.insert().values(material_id=mid, version=latest + 1, author_id=actor,
                    material_sha=body["sha256"], immutable_digest=self._immutable(body), state="draft", bootstrap=False,
                    created_at=at, updated_at=at))
                results.append(body)
            self.auth.require(actor, "components:write")
            return self._record(conn, actor, request_id, fingerprint, "material.import" if imported else "material.draft",
                                {"materials": results, "outcomeSource": "persisted_governance_command", "executesCode": False})

    def request_publication(self, actor, material_id, version, request_id):
        self.auth.require(actor, "components:write")
        with self._write() as conn:
            material = self._material(conn, material_id, version)
            governed = self._version(conn, material_id, version)
            self._owner_admin(actor, governed)
            config = self._config(conn)
            fingerprint = digest({"operation": "request-publication", "materialId": material_id, "version": version,
                "sha256": material["body"]["sha256"], "immutableDigest": self._immutable(material["body"]), "policy": config.fingerprint})
            old = self._old_command(conn, actor, request_id, fingerprint)
            if old is not None:
                return old
            if governed["state"] in {"withdrawn", "archived"}:
                raise HTTPException(409, "Inactive material versions cannot be republished; draft a new version")
            self._dependencies(conn, material["body"], config)
            row = {"id": str(uuid4()), "material_id": material_id, "version": version, "author_id": governed["author_id"],
                   "material_sha": material["body"]["sha256"], "immutable_digest": self._immutable(material["body"]),
                   "policy_revision": config.revision, "policy_hash": config.fingerprint, "requested_by": actor,
                   "created_at": now(), "decision": "pending"}
            self.auth.require(actor, "components:write")
            conn.execute(self.reviews.insert().values(**row))
            result = self._review_projection(conn, row)
            return self._record(conn, actor, request_id, fingerprint, "material.review.request", result)

    def _review_projection(self, conn, row):
        material = self._material(conn, row["material_id"], row["version"])
        governed = self._version(conn, row["material_id"], row["version"])
        config = self._config(conn)
        return {"id": row["id"], "materialId": row["material_id"], "version": row["version"], "authorId": row["author_id"],
                "sha256": row["material_sha"], "immutableDigest": row["immutable_digest"], "policyRevision": row["policy_revision"],
                "currentPolicy": row["policy_hash"] == config.fingerprint, "decision": row["decision"],
                "reviewerId": row.get("reviewer_id"), "requestedBy": row["requested_by"], "createdAt": row["created_at"],
                "decidedAt": row.get("decided_at"), "state": governed["state"], "material": material["body"],
                "demoCompatibility": config.review_mode == "demo-self-review", "taskApprovalSeparate": True}

    def decide_publication(self, actor, review_id, approved, request_id):
        self.auth.require(actor, "agent_os:admin")
        if type(approved) is not bool:
            raise HTTPException(400, "A typed material publication decision is required")
        with self._write() as conn:
            row = conn.execute(select(self.reviews).where(self.reviews.c.id == review_id)).mappings().first()
            if not row:
                raise HTTPException(404, "Material publication review not found")
            row = dict(row)
            fingerprint = digest({"operation": "decide-publication", "reviewId": review_id, "approved": approved,
                                  "materialSha": row["material_sha"], "immutableDigest": row["immutable_digest"], "policyHash": row["policy_hash"]})
            old = self._old_command(conn, actor, request_id, fingerprint)
            if old is not None:
                return old
            config = self._config(conn)
            if row["policy_hash"] != config.fingerprint or row["decision"] != "pending":
                raise HTTPException(409, "Publication review is decided or bound to a previous governance policy")
            if config.review_mode == "separate-admin" and actor == row["author_id"]:
                raise HTTPException(403, "A different current administrator must review the author's material")
            material = self._material(conn, row["material_id"], row["version"])
            governed = self._version(conn, row["material_id"], row["version"])
            if governed["state"] in {"withdrawn", "archived"} or row["material_sha"] != material["body"]["sha256"] or row["immutable_digest"] != self._immutable(material["body"]):
                raise HTTPException(409, "Reviewed material changed or became inactive")
            if approved:
                self._dependencies(conn, material["body"], config)
            self.auth.require(actor, "agent_os:admin")
            row.update(decision="approved" if approved else "denied", reviewer_id=actor, decided_at=now())
            conn.execute(self.reviews.update().where(self.reviews.c.id == review_id).values(
                decision=row["decision"], reviewer_id=actor, decided_at=row["decided_at"]))
            if approved:
                conn.execute(self.materials.update().where(self.materials.c.id == row["material_id"], self.materials.c.version == row["version"]).values(published=True))
                conn.execute(self.versions.update().where(self.versions.c.material_id == row["material_id"], self.versions.c.version == row["version"]).values(state="published", review_id=review_id, updated_at=now()))
            result = self._review_projection(conn, row)
            return self._record(conn, actor, request_id, fingerprint, "material.review.decision", result)

    def inspect_review(self, actor, review_id):
        with self._read() as conn:
            row = conn.execute(select(self.reviews).where(self.reviews.c.id == review_id)).mappings().first()
            if not row:
                raise HTTPException(404, "Material publication review not found")
            self._owner_admin(actor, self._version(conn, row["material_id"], row["version"]))
            return self._review_projection(conn, dict(row))

    def list_reviews(self, actor, *, all_authors=False):
        self.auth.require(actor, "agent_os:admin" if all_authors else "components:read")
        with self._read() as conn:
            query = select(self.reviews).order_by(self.reviews.c.created_at.desc()).limit(100)
            if not all_authors:
                query = query.where(self.reviews.c.author_id == actor)
            return [self._review_projection(conn, dict(row)) for row in conn.execute(query).mappings()]

    def inspect_version(self, actor, material_id, version):
        self.auth.require(actor, "components:read")
        with self._read() as conn:
            material = self._material(conn, material_id, version)
            governed = self._version(conn, material_id, version)
            if governed["state"] != "published":
                self._owner_admin(actor, governed)
            return {"material": {**material["body"], "published": material["published"]}, "governance": governed,
                    "immutableBodyPreserved": True}

    def _deactivate(self, actor, material_id, version, request_id, reason, state):
        self.auth.require(actor, "agent_os:admin" if state == "withdrawn" else "components:write")
        if not isinstance(reason, str) or len(reason) > 2000:
            raise HTTPException(422, "Material status reason exceeds bounds")
        self._safe_data(reason)
        with self._write() as conn:
            governed = self._version(conn, material_id, version)
            if state == "archived":
                self._owner_admin(actor, governed)
            self._material(conn, material_id, version)
            fingerprint = digest({"operation": state, "materialId": material_id, "version": version,
                                  "sha256": governed["material_sha"], "reason": reason})
            old = self._old_command(conn, actor, request_id, fingerprint)
            if old is not None:
                return old
            self.auth.require(actor, "agent_os:admin" if state == "withdrawn" else "components:write")
            conn.execute(self.versions.update().where(self.versions.c.material_id == material_id, self.versions.c.version == version).values(state=state, reason=reason, updated_at=now()))
            result = {"materialId": material_id, "version": version, "sha256": governed["material_sha"], "state": state,
                      "reason": reason, "immutableBodyPreserved": True, "outcomeSource": "persisted_governance_command"}
            return self._record(conn, actor, request_id, fingerprint, "material." + state, result)

    def archive(self, actor, material_id, version, request_id, reason=""):
        return self._deactivate(actor, material_id, version, request_id, reason, "archived")

    def withdraw(self, actor, material_id, version, request_id, reason=""):
        return self._deactivate(actor, material_id, version, request_id, reason, "withdrawn")

    def require_materials_current(self, plan):
        refs = plan.get("materialRefs")
        if not isinstance(refs, list) or not 1 <= len(refs) <= 30:
            raise HTTPException(409, "Plan must bind exact approved material versions")
        try:
            pins = [PinnedRef.model_validate(ref).model_dump() for ref in refs]
        except ValidationError as error:
            raise HTTPException(409, "Plan material references are malformed") from error
        allowed = {(ref["id"], ref["version"], ref["sha256"]) for ref in pins}
        with self._read() as conn:
            config = self._config(conn)
            for ref in pins:
                material = self._material(conn, ref["id"], ref["version"])
                if material["body"]["sha256"] != ref["sha256"]:
                    raise HTTPException(409, "Plan material differs from the exact pinned digest")
                self._active(conn, material, config)
                self._dependencies(conn, material["body"], config, allowed)
        return {"allowed": True, "materialRefs": pins, "policyRevision": config.revision}

    def filter_active(self, materials):
        active = []
        with self._read() as conn:
            config = self._config(conn)
            for item in materials:
                try:
                    material = self._material(conn, item["id"], item["version"])
                    self._active(conn, material, config)
                    self._dependencies(conn, material["body"], config)
                    active.append(item)
                except HTTPException as error:
                    if error.status_code not in {404, 409}:
                        raise
        return active

    def adopt_demo_bootstrap(self):
        """Trusted startup only; proves original seed and matching seed audit."""
        if not self.store.settings.demo:
            raise ValueError("Demo bootstrap publication is forbidden in production")
        adopted = []
        with self._write() as conn:
            for mid, kind, name, content, permissions in SEEDS:
                material = self._material(conn, mid, 1)
                body = material["body"]
                if not material["published"] or body.get("kind") != kind or body.get("name") != name or body.get("content") != content or body.get("permissions") != permissions or body.get("origin") != "factory synthetic fixture" or body.get("license") != "MIT" or body.get("dependencies") != []:
                    raise HTTPException(409, "Demo bootstrap seed differs from trusted original")
                proof = conn.execute(select(self.audit.c.id).where(self.audit.c.actor_id == "demo-bootstrap",
                    self.audit.c.action == "material.seed", self.audit.c.target_id == mid,
                    self.audit.c.body["version"].as_integer() == 1,
                    self.audit.c.body["sha256"].as_string() == body["sha256"])).first()
                if not proof:
                    raise HTTPException(409, "Demo bootstrap is missing its original seed receipt")
                existing = conn.execute(select(self.versions).where(self.versions.c.material_id == mid, self.versions.c.version == 1)).mappings().first()
                if not existing:
                    conn.execute(self.versions.insert().values(material_id=mid, version=1, author_id="demo-bootstrap",
                        material_sha=body["sha256"], immutable_digest=self._immutable(body), state="published", bootstrap=True,
                        created_at=body["createdAt"], updated_at=now()))
                    adopted.append(mid)
        return {"adopted": adopted, "approvalMode": "verified-demo-bootstrap", "productionAllowed": False}

    def publish_demo_compatibility(self, actor, material_id, version, request_id):
        self._key(request_id)
        if self.current()["review_mode"] != "demo-self-review" or not self.store.settings.demo:
            raise HTTPException(403, "Explicit demo self-review compatibility is required")
        request_key = digest({"key": request_id, "step": "request"})
        decision_key = digest({"key": request_id, "step": "decision"})
        review = self.request_publication(actor, material_id, version, request_key)
        return self.decide_publication(actor, review["id"], True, decision_key)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=200)


class DraftCommand(Command):
    definition: dict[str, Any]


class ImportCommand(Command):
    definitions: list[dict[str, Any]] = Field(min_length=1, max_length=30)


class ReviewCommand(Command):
    materialId: str = Field(min_length=1, max_length=100)
    version: int = Field(strict=True, gt=0)


class DecisionCommand(Command):
    approved: StrictBool


class StatusCommand(Command):
    reason: str = Field(default="", max_length=2000)


def material_governance_router(auth, service):
    router = APIRouter(prefix="/api/factory/material-governance")

    def actor(request):
        return auth.user(request)["id"]

    @router.get("/policy")
    def policy(request: Request):
        auth.require(actor(request), "components:read")
        return service.current()

    @router.post("/drafts", status_code=201)
    def draft(body: DraftCommand, request: Request):
        return service.create_draft(actor(request), body.definition, body.requestId)

    @router.post("/imports", status_code=201)
    def imported(body: ImportCommand, request: Request):
        return service.import_definitions(actor(request), body.definitions, body.requestId)

    @router.post("/reviews", status_code=201)
    def review(body: ReviewCommand, request: Request):
        return service.request_publication(actor(request), body.materialId, body.version, body.requestId)

    @router.get("/reviews")
    def reviews(request: Request, allAuthors: bool = False):
        return service.list_reviews(actor(request), all_authors=allAuthors)

    @router.get("/reviews/{review_id}")
    def inspect_review(review_id: str, request: Request):
        return service.inspect_review(actor(request), review_id)

    @router.post("/reviews/{review_id}/decision")
    def decide(review_id: str, body: DecisionCommand, request: Request):
        return service.decide_publication(actor(request), review_id, body.approved, body.requestId)

    @router.get("/versions/{material_id}/{version}")
    def inspect(material_id: str, version: int, request: Request):
        return service.inspect_version(actor(request), material_id, version)

    @router.post("/versions/{material_id}/{version}/archive")
    def archive(material_id: str, version: int, body: StatusCommand, request: Request):
        return service.archive(actor(request), material_id, version, body.requestId, body.reason)

    @router.post("/versions/{material_id}/{version}/withdraw")
    def withdraw(material_id: str, version: int, body: StatusCommand, request: Request):
        return service.withdraw(actor(request), material_id, version, body.requestId, body.reason)

    return router

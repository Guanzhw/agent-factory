"""Authenticated current origin authority over operator-selected HTTP.

The receiver never supplies an endpoint, credential or owner grant through this
protocol. A positive response checks the original persisted placement and all
current Factory guards. Cancellation is a separately verified cleanup signal.
The separate scientific-tool-call endpoint debits one stable protected call;
ordinary current-authority checks never debit the scientific budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Any, Callable, Literal, Mapping
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from .remote_handoff import HandoffAuthority, HandoffCancellationRequested
from .plan_policy import KNOWN_TOOLS, tools_for_contract
from .store import digest

# Wire vocabulary is not a grant: both servers still check their selected
# contract, immutable plan, exact mapping and current managed authority.
SCIENTIFIC_TOOLS = {name: tools_for_contract("autoresearch-session-v1")[name]
    for name in ("research_process_run", "research_preparation_verify")}
AUTHORITY_TOOLS = {**KNOWN_TOOLS, **tools_for_contract("bounded-process-v1"), **SCIENTIFIC_TOOLS}

IDENTIFIER = r"^[A-Za-z0-9_.:-]{1,120}$"
IDENTITY = r"^[^\x00-\x1f\x7f]{1,200}$"
HASH = r"^[a-f0-9]{64}$"
UUID_TEXT = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
PATH = "/api/factory/remote-authority/check"
SCIENTIFIC_CUSTODY_PATH = "/api/factory/remote-authority/scientific-custody"
SCIENTIFIC_CALL_PATH = "/api/factory/remote-authority/scientific-tool-call"


class AuthorityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema: StrictInt = Field(ge=1, le=1)
    originRef: str = Field(pattern=IDENTIFIER)
    targetRef: str = Field(pattern=IDENTIFIER)
    originOwner: str = Field(pattern=IDENTITY)
    originTaskId: str = Field(pattern=UUID_TEXT)
    manifestSha256: str = Field(pattern=HASH)
    tool: str | None = Field(pattern=IDENTIFIER)
    receiverIdentity: str = Field(pattern=IDENTITY)
    targetRevision: str = Field(pattern=IDENTIFIER)
    targetFingerprint: str = Field(pattern=HASH)


class AuthorityScientificCall(AuthorityCheck):
    tool: Literal["research_process_run", "research_preparation_verify"]
    callId: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,200}$")
    receiverTaskId: str = Field(pattern=UUID_TEXT)
    nativeRunId: str = Field(pattern=UUID_TEXT)
    phaseScopeSha256: str = Field(pattern=HASH)


class ScientificCallReply(AuthorityScientificCall):
    outcome: Literal["consumed"]
    callProofSha256: str = Field(pattern=HASH)


class AuthorityScientificCustody(AuthorityCheck):
    tool: None
    receiverTaskId: str = Field(pattern=UUID_TEXT)
    nativeRunId: str = Field(pattern=UUID_TEXT)
    phaseScopeSha256: str = Field(pattern=HASH)
    leaseId: str = Field(pattern=UUID_TEXT)


class ScientificCustodyReply(AuthorityScientificCustody):
    outcome: Literal["custody-readable"]
    custodyProofSha256: str = Field(pattern=HASH)


class AuthorityBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    toolCalls: StrictInt = Field(ge=1, le=128)
    maxDepth: StrictInt = Field(ge=1, le=8)
    maxChildren: StrictInt = Field(ge=1, le=64)
    experimentSeconds: StrictInt = Field(ge=1, le=600)
    outputBytes: StrictInt = Field(ge=1024, le=1048576)


class AuthorityScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    capabilities: list[str] = Field(min_length=1, max_length=30)
    tools: list[str] = Field(min_length=1, max_length=30)
    budget: AuthorityBudget
    usageGrantSha256: str | None = Field(default=None, pattern=HASH)

    @model_validator(mode="after")
    def identifiers(self):
        import re
        if len(set(self.capabilities)) != len(self.capabilities) or len(set(self.tools)) != len(self.tools) or any(
                not re.fullmatch(IDENTIFIER, value) for value in [*self.capabilities, *self.tools]):
            raise ValueError("Authority scope requires unique bounded identifiers")
        if not set(self.tools) <= AUTHORITY_TOOLS.keys() or set(self.capabilities) != {AUTHORITY_TOOLS[tool] for tool in self.tools}:
            raise ValueError("Authority scope must exactly match registered tool capabilities")
        return self


class AuthorityReply(AuthorityCheck):
    outcome: Literal["authorized", "cancelled"]
    authority: AuthorityScope | None

    @model_validator(mode="after")
    def outcome_scope(self):
        if (self.outcome == "authorized") != (self.authority is not None):
            raise ValueError("Cancellation cannot contain execution authority")
        if self.authority is not None and self.tool is not None and self.tool not in self.authority.tools:
            raise ValueError("Requested tool is outside returned authority")
        return self


class BoundedAuthorityRoute(APIRoute):
    """Bound before JSON parsing and never echo untrusted validation inputs."""
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def bounded(request: Request):
            declared = request.headers.get("content-length")
            if declared is not None and (not declared.isdecimal() or int(declared) > 8192):
                raise HTTPException(413, "ORIGIN_AUTHORITY_REQUEST_BOUND: bounded schema is required")
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 8192:
                    raise HTTPException(413, "ORIGIN_AUTHORITY_REQUEST_BOUND: bounded schema is required")
                body.extend(chunk)
            request._body = bytes(body)
            if request.url.path in {SCIENTIFIC_CALL_PATH, SCIENTIFIC_CUSTODY_PATH}:
                try:
                    json.loads(body, object_pairs_hook=OriginAuthorityTransport._json_object,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, RecursionError) as error:
                    raise HTTPException(422, "ORIGIN_AUTHORITY_SCHEMA_INVALID: exact typed binding is required") from error
            try:
                return await handler(request)
            except RequestValidationError as error:
                raise HTTPException(422, "ORIGIN_AUTHORITY_SCHEMA_INVALID: exact typed binding is required") from error
        return bounded


def origin_authority_router(auth: Any, handoff_client: Any) -> APIRouter:
    """Install only for operator-configured origin handoff targets.

Native middleware authenticates the receiver actor. Its current read grant and
the selected per-owner receiver mapping bind both endpoints. The scientific
endpoint additionally requires the persisted phase scope and atomic debit fence.
"""
    router = APIRouter(route_class=BoundedAuthorityRoute)

    @router.post(PATH, response_model=AuthorityReply)
    def check(body: AuthorityCheck, request: Request, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        actor = auth.user(request)["id"]
        auth.require(actor, "read")
        target = handoff_client.targets.get(body.targetRef)
        if target is None or target.origin_ref != body.originRef or target.identity_map.get(body.originOwner) != actor or body.receiverIdentity != actor:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: receiver identity is outside the selected target")
        if target.configuration_revision != body.targetRevision or target.fingerprint != body.targetFingerprint:
            raise HTTPException(409, "ORIGIN_AUTHORITY_CONFIG_CHANGED: selected target configuration differs")
        row = handoff_client._row(body.originOwner, body.originTaskId)
        if row["target_ref"] != body.targetRef or row["manifest_hash"] != body.manifestSha256 or row["configuration_hash"] != body.targetFingerprint:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: persisted placement differs")
        # This verifies current source identity/configuration, immutable plan and
        # absence of a local ticket even before interpreting cancellation.
        handoff_client._target(body.originOwner, row, execution=False)
        outcome, scope = "authorized", None
        try:
            authority = handoff_client.authority_callback(body.originOwner, body.originTaskId, body.manifestSha256, body.tool)
            if not isinstance(authority, HandoffAuthority):
                raise HTTPException(503, "ORIGIN_AUTHORITY_UNAVAILABLE: typed current mandate is unavailable")
            proof = (authority.origin_ref, authority.target_ref, authority.receiver_identity, authority.target_revision, authority.target_fingerprint)
            if proof != (body.originRef, body.targetRef, actor, body.targetRevision, body.targetFingerprint):
                raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: current source configuration proof differs")
            scope = AuthorityScope.model_validate({"capabilities": sorted(authority.capabilities), "tools": sorted(authority.tools), "budget": dict(authority.budget),
                "usageGrantSha256": authority.usage_grant_sha256})
        except HandoffCancellationRequested as signal:
            if (signal.owner, signal.task_id, signal.manifest_hash) != (body.originOwner, body.originTaskId, body.manifestSha256):
                raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: cleanup signal differs") from signal
            outcome = "cancelled"
        except (PermissionError, ValidationError) as error:
            raise HTTPException(403, "ORIGIN_AUTHORITY_DENIED: current origin mandate denies this operation") from error
        # Recheck trusted configuration and the authenticated receiver's current
        # rights immediately before producing a positive or cleanup response.
        current = handoff_client.targets.get(body.targetRef)
        if current is None or current.fingerprint != body.targetFingerprint or current.identity_map.get(body.originOwner) != actor:
            raise HTTPException(409, "ORIGIN_AUTHORITY_CONFIG_CHANGED: selected target configuration differs")
        auth.require(actor, "read")
        return AuthorityReply(**body.model_dump(), outcome=outcome, authority=scope)

    @router.post(SCIENTIFIC_CUSTODY_PATH, response_model=ScientificCustodyReply)
    def scientific_custody(body: AuthorityScientificCustody, request: Request, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        actor = auth.user(request)["id"]
        auth.require(actor, "read")
        target = handoff_client.targets.get(body.targetRef)
        if (target is None or target.origin_ref != body.originRef
                or target.identity_map.get(body.originOwner) != actor or body.receiverIdentity != actor
                or target.configuration_revision != body.targetRevision or target.fingerprint != body.targetFingerprint):
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: custody target differs")
        service = getattr(handoff_client.store, "remote_scientific", None)
        if service is None:
            raise HTTPException(503, "ORIGIN_SCIENTIFIC_UNAVAILABLE: custody service unavailable")
        try:
            proof = service.authorize_completed_custody(body.model_dump())
            current = handoff_client.targets.get(body.targetRef)
            if current is None or current.fingerprint != body.targetFingerprint or current.identity_map.get(body.originOwner) != actor:
                raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: custody target changed")
            auth.require(actor, "read")
            if type(proof) is not dict or set(proof) != {"custodyProofSha256"}:
                raise ValueError()
            return ScientificCustodyReply(**body.model_dump(), outcome="custody-readable", **proof)
        except HTTPException:
            raise
        except PermissionError as error:
            raise HTTPException(403, "ORIGIN_AUTHORITY_DENIED: custody mandate denied") from error
        except Exception as error:
            raise HTTPException(503, "ORIGIN_SCIENTIFIC_UNAVAILABLE: custody proof unavailable") from error

    @router.post(SCIENTIFIC_CALL_PATH, response_model=ScientificCallReply)
    def consume_scientific_tool(body: AuthorityScientificCall, request: Request, response: Response):
        # Reuse every actor/configuration/placement/current-authority fence. The
        # check remains read-only, including repeated runtime authority probes.
        mandate = check(AuthorityCheck.model_validate(body.model_dump(include=set(AuthorityCheck.model_fields))),
                        request, response)
        if mandate.outcome != "authorized":
            raise HTTPException(403, "ORIGIN_AUTHORITY_DENIED: cancelled mandate cannot debit a tool call")
        service = getattr(handoff_client.store, "remote_scientific", None)
        if service is None:
            raise HTTPException(503, "ORIGIN_SCIENTIFIC_UNAVAILABLE: scientific debit service is unavailable")
        # The service atomically rechecks persisted scientific scope/current
        # source authority and binds callId to one debit. An unknown HTTP reply
        # is never permission to execute or create a replacement call identity.
        try:
            proof = service.consume_remote_tool(body.model_dump())
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(503, "ORIGIN_SCIENTIFIC_UNAVAILABLE: scientific debit outcome is unavailable") from error
        try:
            if not isinstance(proof, dict) or set(proof) != {"callProofSha256"}:
                raise ValueError("Invalid scientific debit proof")
            return ScientificCallReply(**body.model_dump(), outcome="consumed", **proof)
        except (ValueError, ValidationError) as error:
            raise HTTPException(503, "ORIGIN_SCIENTIFIC_UNAVAILABLE: exact scientific debit proof is unavailable") from error

    return router


@dataclass(frozen=True)
class OriginAuthorityTransport:
    """Operator-installed synchronous guard; no retry, redirect or body credential.

The native runtime invokes this in its trusted guard/tool thread. ``__call__``
only reads authority; ``consume_scientific_tool`` explicitly debits a bound call.
HTTP failures
deny execution; only a fully bound authenticated cancellation reply raises the
native cleanup signal. `.fingerprint` contains public configuration, never a
bearer, callback implementation, credential handle or secret digest.
"""
    base_url: str
    origin_ref: str
    target_ref: str
    target_revision: str
    target_fingerprint: str
    receiver_identity_map: Mapping[str, str]
    credential_provider: Callable[[str], str] = field(repr=False)
    configuration_revision: str = "1"
    timeout_seconds: float = 2
    max_response_bytes: int = 16384

    def __post_init__(self):
        import re
        endpoint = urlsplit(self.base_url)
        if len(self.base_url) > 2048 or any(ord(char) <= 32 for char in self.base_url) or endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("Origin authority requires an operator HTTP origin without credentials")
        if endpoint.scheme == "http" and endpoint.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Cleartext origin authority is restricted to loopback")
        if not callable(self.credential_provider) or not self.receiver_identity_map or len(self.receiver_identity_map) > 100:
            raise ValueError("Origin authority requires a bounded operator identity map and credential callback")
        names = [self.origin_ref, self.target_ref, self.target_revision, self.configuration_revision]
        identities = [*self.receiver_identity_map.keys(), *self.receiver_identity_map.values()]
        if any(not isinstance(name, str) or not re.fullmatch(IDENTIFIER, name) for name in names) or any(
                not isinstance(identity, str) or not re.fullmatch(IDENTITY, identity) for identity in identities) or not re.fullmatch(HASH, self.target_fingerprint):
            raise ValueError("Origin authority configuration requires bounded exact identities/revision/hash")
        if type(self.timeout_seconds) not in {int, float} or not math.isfinite(self.timeout_seconds) or not .1 <= self.timeout_seconds <= 10:
            raise ValueError("Origin authority timeout must be between 0.1 and 10 seconds")
        if type(self.max_response_bytes) is not int or not 1024 <= self.max_response_bytes <= 65536:
            raise ValueError("Origin authority response bound must be between 1024 and 65536 bytes")
        # Own a snapshot rather than retaining a mutable caller's map.
        from types import MappingProxyType
        object.__setattr__(self, "receiver_identity_map", MappingProxyType(dict(self.receiver_identity_map)))

    @property
    def source_configuration(self):
        return {"revision": self.target_revision, "sha256": self.target_fingerprint}

    @property
    def fingerprint(self):
        return digest({"schema": 1, "baseUrl": self.base_url.rstrip("/"), "originRef": self.origin_ref,
            "targetRef": self.target_ref, "targetRevision": self.target_revision, "targetFingerprint": self.target_fingerprint,
            "receiverIdentityMap": dict(self.receiver_identity_map), "revision": self.configuration_revision,
            "timeoutSeconds": self.timeout_seconds, "maxResponseBytes": self.max_response_bytes})

    @staticmethod
    def _json_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate authority JSON field")
            value[key] = item
        return value

    def __call__(self, owner: str, task_id: str, manifest_hash: str, tool: str | None) -> HandoffAuthority:
        receiver = self.receiver_identity_map.get(owner)
        if receiver is None:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: owner has no installed receiver identity")
        try:
            expected = AuthorityCheck(schema=1, originRef=self.origin_ref, targetRef=self.target_ref, originOwner=owner,
                originTaskId=task_id, manifestSha256=manifest_hash, tool=tool, receiverIdentity=receiver,
                targetRevision=self.target_revision, targetFingerprint=self.target_fingerprint)
        except ValidationError as error:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: exact owner task/manifest/tool binding is required") from error
        raw = self._post(owner, PATH, expected.model_dump())
        try:
            reply = AuthorityReply.model_validate(json.loads(raw, object_pairs_hook=self._json_object))
        except (ValueError, ValidationError, RecursionError) as error:
            raise HTTPException(502, "ORIGIN_AUTHORITY_RESPONSE_INVALID: exact typed authority is required") from error
        if reply.model_dump(exclude={"outcome", "authority"}) != expected.model_dump():
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: response identity/configuration/hash differs")
        if reply.outcome == "cancelled":
            raise HandoffCancellationRequested(owner, task_id, manifest_hash)
        if reply.authority is None:
            raise HTTPException(403, "ORIGIN_AUTHORITY_DENIED: no current execution mandate")
        return HandoffAuthority(frozenset(reply.authority.capabilities), frozenset(reply.authority.tools),
            reply.authority.budget.model_dump(), origin_ref=self.origin_ref, target_ref=self.target_ref,
            receiver_identity=receiver, target_revision=self.target_revision, target_fingerprint=self.target_fingerprint,
            usage_grant_sha256=reply.authority.usageGrantSha256)

    def consume_scientific_tool(self, owner: str, task_id: str, manifest_hash: str, tool: str, *,
                               call_id: str, receiver_task_id: str, native_run_id: str,
                               phase_scope_sha256: str) -> dict:
        receiver = self.receiver_identity_map.get(owner)
        if receiver is None:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: owner has no installed receiver identity")
        try:
            expected = AuthorityScientificCall.model_validate({"schema": 1, "originRef": self.origin_ref,
                "targetRef": self.target_ref, "originOwner": owner, "originTaskId": task_id,
                "manifestSha256": manifest_hash, "tool": tool, "receiverIdentity": receiver,
                "targetRevision": self.target_revision, "targetFingerprint": self.target_fingerprint,
                "callId": call_id, "receiverTaskId": receiver_task_id, "nativeRunId": native_run_id,
                "phaseScopeSha256": phase_scope_sha256})
        except ValidationError as error:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: exact scientific call binding is required") from error
        raw = self._post(owner, SCIENTIFIC_CALL_PATH, expected.model_dump())
        try:
            reply = ScientificCallReply.model_validate(json.loads(raw, object_pairs_hook=self._json_object))
        except (ValueError, ValidationError, RecursionError) as error:
            raise HTTPException(502, "ORIGIN_AUTHORITY_RESPONSE_INVALID: exact scientific debit proof is required") from error
        if reply.model_dump(exclude={"outcome", "callProofSha256"}) != expected.model_dump():
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: scientific debit response binding differs")
        return reply.model_dump()

    def check_scientific_custody(self, owner: str, task_id: str, manifest_hash: str, *,
                                receiver_task_id: str, native_run_id: str,
                                phase_scope_sha256: str, lease_id: str) -> dict:
        try:
            expected = AuthorityScientificCustody.model_validate({"schema": 1, "originRef": self.origin_ref,
                "targetRef": self.target_ref, "originOwner": owner, "originTaskId": task_id,
                "manifestSha256": manifest_hash, "tool": None, "receiverIdentity": self.receiver_identity_map.get(owner),
                "targetRevision": self.target_revision, "targetFingerprint": self.target_fingerprint,
                "receiverTaskId": receiver_task_id, "nativeRunId": native_run_id,
                "phaseScopeSha256": phase_scope_sha256, "leaseId": lease_id})
        except ValidationError as error:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: exact custody binding required") from error
        raw = self._post(owner, SCIENTIFIC_CUSTODY_PATH, expected.model_dump())
        try:
            reply = ScientificCustodyReply.model_validate(json.loads(raw, object_pairs_hook=self._json_object))
        except (ValueError, ValidationError, RecursionError) as error:
            raise HTTPException(502, "ORIGIN_AUTHORITY_RESPONSE_INVALID: typed custody proof required") from error
        if reply.model_dump(exclude={"outcome", "custodyProofSha256"}) != expected.model_dump():
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: custody response differs")
        return reply.model_dump()

    def _post(self, owner: str, path: str, body: dict) -> bytes:
        # Fixed internal endpoint callers only; credentials never enter DTOs.
        if path not in {PATH, SCIENTIFIC_CALL_PATH, SCIENTIFIC_CUSTODY_PATH}:
            raise HTTPException(403, "ORIGIN_AUTHORITY_BINDING_DENIED: unsupported authority endpoint")
        try:
            token = self.credential_provider(owner)
            if not isinstance(token, str) or not 1 <= len(token) <= 16384 or any(char.isspace() for char in token):
                raise ValueError("Unavailable operator credential")
        except Exception as error:
            raise HTTPException(403, "ORIGIN_AUTHORITY_AUTH_UNAVAILABLE: operator credential is unavailable") from error
        url = self.base_url.rstrip("/") + path
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False, trust_env=False) as client:
                with client.stream("POST", url, json=body, headers={"Authorization": "Bearer " + token,
                        "Accept": "application/json", "Accept-Encoding": "identity", "Cache-Control": "no-store"}) as response:
                    if response.status_code != 200:
                        raise HTTPException(403 if response.status_code in {401, 403, 404, 409, 422} else 503,
                            "ORIGIN_AUTHORITY_DENIED: origin did not return current verified authority")
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    encoding = response.headers.get("content-encoding", "identity").lower()
                    declared = response.headers.get("content-length")
                    if content_type != "application/json" or encoding != "identity" or declared is not None and (not declared.isdecimal() or int(declared) > self.max_response_bytes):
                        raise HTTPException(502, "ORIGIN_AUTHORITY_RESPONSE_INVALID: bounded uncompressed JSON is required")
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=1024):
                        if len(raw) + len(chunk) > self.max_response_bytes:
                            raise HTTPException(502, "ORIGIN_AUTHORITY_RESPONSE_INVALID: response exceeds its bound")
                        raw.extend(chunk)
        except httpx.HTTPError as error:
            raise HTTPException(503, "ORIGIN_AUTHORITY_UNAVAILABLE: current origin authority cannot be reached") from error
        return bytes(raw)

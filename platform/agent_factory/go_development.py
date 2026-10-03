"""Explicit coding-development model materials; no credential discovery or auto-selection.

An operator installs handles and explicitly enables this profile. Materials carry
only exact adapter identifiers. Billing verification is a current trusted callback,
never a material flag or an inference from account balance. No network preflight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable

import httpx
from fastapi import HTTPException

from .connections import TrustedConnectionBinding
from .execution_bindings import AdapterRegistration, BindingContext
from .opencode_go import GoDevelopmentModel, GoLoopbackTransport
from .go_live import GoLiveCampaign, GoLiveGateError

PROFILE_REVISION = "go-development-v1"
PROVIDER_ADAPTER_ID = "go-development-provider-v1"
CONNECTION_NAME = "goDevelopment"
REGISTRATION_REF = "go-development-model"
APPLICATION_ID = "go-development-checksum"
CAPABILITY = "model:development"
SCOPE = "coding-development"
MODEL_ADAPTER_IDS = {
    "deepseek-v4-flash": "go-development-deepseek-v4-flash-v1",
    "gpt-6-luna": "go-development-gpt-6-luna-v1",
}
PROTOCOLS = {"deepseek-v4-flash": "chat/completions", "gpt-6-luna": "responses"}


@dataclass(frozen=True)
class GoDevelopmentHandle:
    """Trusted callbacks; explicit fixture mode never claims live billing evidence."""
    credential: Callable[[], str] | None = field(default=None, repr=False)
    billing_verified: Callable[[str, str], bool] | None = field(default=None, repr=False)
    async_transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    mode: str = "subscription"
    wire_stream: bool = True
    native_retries: int = 0
    live_campaign: GoLiveCampaign | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.wire_stream) is not bool or type(self.native_retries) is not int or self.native_retries not in {0, 1}:
            raise ValueError("Development streaming/retry settings must be explicitly bounded")
        if self.mode == "subscription" and self.native_retries != 0:
            raise ValueError("Subscription validation cannot retry")
        if self.mode not in {"subscription", "fixture"}:
            raise ValueError("Unsupported development handle mode")
        if self.async_transport is not None and not isinstance(self.async_transport, httpx.AsyncBaseTransport):
            raise ValueError("Development transport must support asynchronous cancellation")
        if self.mode == "fixture":
            if (type(self.async_transport) not in {httpx.MockTransport, GoLoopbackTransport} or self.credential is not None
                    or self.billing_verified is not None or self.live_campaign is not None):
                raise ValueError("Fixture mode requires exact mock or literal-loopback transport and forbids credential or billing callbacks")
        elif not callable(self.credential) or (self.billing_verified is not None and not callable(self.billing_verified)):
            raise ValueError("Trusted development callbacks are required")
        elif self.live_campaign is not None and (type(self.live_campaign) is not GoLiveCampaign
                or self.async_transport is not None or self.billing_verified is not None or not self.wire_stream):
            raise ValueError("Live campaign requires real fixed transport, streaming and no alternate billing callback")

    def credential_callback(self) -> str:
        if self.mode == "fixture":
            return "agent-factory-offline-synthetic-credential"
        if self.credential is None:
            raise ValueError("Trusted development credential is unavailable")
        return self.credential()

    def billing_callback(self, session_id: str, model_id: str) -> bool:
        if self.mode == "fixture":
            return True  # Synthetic transport only; never live billing evidence.
        return self.billing_verified is not None and self.billing_verified(session_id, model_id) is True


def stable_session(context: Any) -> str:
    session = getattr(context, "session_id", None)
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session):
        raise HTTPException(409, "GO_DEVELOPMENT_CONTEXT: original native conversation is required")
    return session


def preflight(handle: GoDevelopmentHandle, *, session_id: str, model_id: str, settings: Any, owner_id: str | None = None) -> dict[str, str]:
    """Fresh billing authorization before credentials/network; default denies."""
    if getattr(settings, "development_profile", "disabled") != "opencode-go" or getattr(settings, "demo", False) is not True:
        raise HTTPException(409, "GO_DEVELOPMENT_DISABLED: explicit demo development profile is required")
    if model_id not in MODEL_ADAPTER_IDS or not isinstance(handle, GoDevelopmentHandle):
        raise HTTPException(409, "GO_DEVELOPMENT_BINDING: exact trusted development model is required")
    if handle.mode == "subscription":
        if handle.live_campaign is None or getattr(settings, "development_live_validation", False) is not True:
            raise HTTPException(409, "GO_LIVE_VALIDATION_PENDING: explicit bounded live campaign required")
        try:
            handle.live_campaign.preflight(model_id, owner_id)
        except GoLiveGateError:
            raise HTTPException(409, "GO_LIVE_CAMPAIGN_DENIED: current bounded campaign is unavailable") from None
        return {"profile": PROFILE_REVISION, "scope": SCOPE, "modelId": model_id,
                "protocol": PROTOCOLS[model_id], "evidenceMode": "live-user-attested"}
    try:
        verified = handle.billing_callback(session_id, model_id)
    except Exception:
        verified = False
    if verified is not True:
        raise HTTPException(409, "GO_SUBSCRIPTION_UNVERIFIED: current subscription-only authorization is required")
    return {"profile": PROFILE_REVISION, "scope": SCOPE, "modelId": model_id,
            "protocol": PROTOCOLS[model_id], "evidenceMode": handle.mode}


def _scope(plan: Any, *, model_id: str) -> None:
    if (plan.get("application") != APPLICATION_ID or (plan.get("applicationRef") or {}).get("id") != APPLICATION_ID
            or plan.get("delegation") or plan.get("mode") != model_id or plan.get("tools") != ["checksum"]
            or plan.get("capabilities") != ["checksum:read"]):
        raise HTTPException(409, "GO_DEVELOPMENT_SCOPE: only the explicitly approved checksum coding application is allowed")


def is_go_plan(plan: Any) -> bool:
    spec = (plan.get("executionBindings") or {}).get("model") or {}
    return plan.get("application") == APPLICATION_ID or spec.get("adapterId") in MODEL_ADAPTER_IDS.values()


def preflight_plan(settings: Any, plan: Any, connections: Any, context: Any = None) -> dict[str, str] | None:
    """Validate an explicit candidate or current task without constructing a model.

    ExecutionBindings validates immutable material/pin digests before this hook;
    resolving the exact pin here rechecks trusted connection state and profile mode.
    """
    if not is_go_plan(plan):
        return None
    spec = (plan.get("executionBindings") or {}).get("model") or {}
    model_id = next((model for model, adapter in MODEL_ADAPTER_IDS.items() if spec.get("adapterId") == adapter), None)
    if model_id is None or spec.get("revision") != "1":
        raise HTTPException(409, "GO_DEVELOPMENT_BINDING: exact development adapter is required")
    _scope(plan, model_id=model_id)
    try:
        _config({key: value for key, value in spec.get("config", {}).items() if key != "connectionName"})
    except (TypeError, ValueError):
        raise HTTPException(409, "GO_DEVELOPMENT_SCOPE: immutable coding scope is required") from None
    if context is not None and getattr(context, "user_id", None) != plan.get("ownerId"):
        raise HTTPException(403, "GO_DEVELOPMENT_CONTEXT: original model owner is required")
    session = stable_session(context) if context is not None else "candidate-preflight"
    pin = spec.get("connection")
    if connections is None or not isinstance(pin, dict) or set(pin) != {"ref", "version", "fingerprint", "kind", "revision", "capabilities", "taskId"}:
        raise HTTPException(409, "GO_DEVELOPMENT_BINDING: exact owner connection is required")
    handle = connections.resolve(plan["ownerId"], pin["ref"], expected_kind="model",
        expected_revision=pin["revision"], expected_fingerprint=pin["fingerprint"], expected_version=pin["version"],
        required_capabilities=(CAPABILITY,), task_id=getattr(context, "session_id", None),
        expected_adapter_ref=PROVIDER_ADAPTER_ID)
    return preflight(handle, session_id=session, model_id=model_id, settings=settings, owner_id=plan["ownerId"])


def trusted_model_binding(owner: str, handle: GoDevelopmentHandle, *, revision: str = PROFILE_REVISION,
                          handle_ref: str = PROFILE_REVISION) -> TrustedConnectionBinding:
    if not isinstance(handle, GoDevelopmentHandle):
        raise ValueError("Only a trusted Go development handle can be registered")
    return TrustedConnectionBinding(owner, "model", PROVIDER_ADAPTER_ID, frozenset({CAPABILITY}), revision,
                                    available=True, opaque_handle=handle, handle_ref=handle_ref)


def _config(value: dict[str, Any]) -> None:
    if value != {"scope": SCOPE}:
        raise ValueError("Go development materials require exact coding-development scope and no overrides")


def model_registrations() -> list[AdapterRegistration]:
    def factory(model_id: str):
        def create(context: BindingContext):
            _config({key: value for key, value in context.spec.get("config", {}).items() if key != "connectionName"})
            if getattr(context.run_context, "user_id", None) != context.plan.get("ownerId"):
                raise HTTPException(403, "GO_DEVELOPMENT_CONTEXT: original model owner is required")
            _scope(context.plan, model_id=model_id)
            session = stable_session(context.run_context)
            handle = context.connection
            preflight(handle, session_id=session, model_id=model_id,
                      settings=context.settings, owner_id=context.run_context.user_id)
            if handle.live_campaign is not None:
                try:
                    handle.live_campaign.authorize(session, model_id, purpose="product", owner_id=context.run_context.user_id)
                except GoLiveGateError:
                    raise HTTPException(409, "GO_LIVE_CAMPAIGN_DENIED: exact product session is unavailable") from None
            return GoDevelopmentModel(model_id=model_id, session_id=session, credential=handle.credential_callback,
                billing_verified=handle.billing_callback, max_output_tokens=256, timeout_seconds=60,
                async_transport=handle.async_transport, wire_stream=handle.wire_stream, native_retries=handle.native_retries,
                live_campaign=handle.live_campaign)
        return create
    return [AdapterRegistration("model", adapter, "1", factory(model), connection_kind="model",
        required_capabilities=(CAPABILITY,), validator=_config, demo_only=True, connection_adapter_ref=PROVIDER_ADAPTER_ID)
        for model, adapter in MODEL_ADAPTER_IDS.items()]


def material_drafts() -> list[dict[str, Any]]:
    """Unpublished immutable definitions. Calling this does not install or select a model."""
    return [{"id": "go-development-" + model, "kind": "model", "name": "Go development " + model,
        "description": "Explicit coding-development model; live use requires independently verified subscription-only billing.",
        "content": "Use only for coding development with approved public or synthetic inputs; no production research grant.",
        "license": "MIT", "compatibility": ["agno:3.1.0"], "dependencies": [], "permissions": [],
        "runtimeBinding": {"adapterId": adapter, "revision": "1", "config": {"connectionName": CONNECTION_NAME, "scope": SCOPE}},
        "provenance": {"kind": "original", "notice": "Original Agent Factory development integration metadata; provider service is external."}}
        for model, adapter in MODEL_ADAPTER_IDS.items()]


def publish_go_development_models(state: dict[str, Any], *, author: str, reviewer: str) -> list[dict[str, Any]]:
    """Explicit operator publication through existing distinct-admin governance."""
    if author == reviewer:
        raise ValueError("A distinct model publication reviewer is required")
    state["auth"].require(author, "components:write")
    state["auth"].require(reviewer, "agent_os:admin")
    governance = state["material_governance"]
    result = []
    for definition in material_drafts():
        identifier = definition["id"]
        material = governance.create_draft(author, definition, PROFILE_REVISION + ":draft:" + identifier)
        review = governance.request_publication(author, identifier, material["version"], PROFILE_REVISION + ":review:" + identifier)
        governance.decide_publication(reviewer, review["id"], True, PROFILE_REVISION + ":approve:" + identifier)
        result.append(next(row for row in state["store"].materials(published_only=True)
                           if row["id"] == identifier and row["version"] == material["version"]))
    return result


def application_definition(models: list[dict[str, Any]], checksum_material: dict[str, Any],
                           environment_material: dict[str, Any]) -> dict[str, Any]:
    """Pure unpublished application metadata, using existing reviewed checksum/environment."""
    def pin(material):
        return {key: material[key] for key in ("id", "version", "sha256")}
    by_id = {model["id"]: model for model in models}
    modes = {}
    for model in MODEL_ADAPTER_IDS:
        modes[model] = {"materialRefs": [pin(by_id["go-development-" + model]),
            pin(checksum_material), pin(environment_material)], "capabilities": ["checksum:read"],
            "toolOrder": ["checksum"], "config": {},
            "connectionRequirements": [{"name": CONNECTION_NAME, "kind": "model",
                # Model capability is enforced by the exact AdapterRegistration
                # and connection pin; application capabilities describe its tools.
                "requiredCapabilities": [], "required": True}],
            "budget": {"toolCalls": 2, "maxDepth": 1, "maxChildren": 1,
                       "experimentSeconds": 8, "outputBytes": 65536}}
    return {"id": APPLICATION_ID, "name": "Go 开发校验", "defaultMode": "deepseek-v4-flash",
        "description": "明确选择的编码开发验证：仅 checksum 工具，非生产科研；离线 fixture 不代表真实订阅或账单证据。",
        "modes": modes, "discoveryKeywords": []}

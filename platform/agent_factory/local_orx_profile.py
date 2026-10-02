"""Explicit no-provider ORX toy application installed through ordinary governance.

This module never grants roles or publishes without two current native admins.
Operator handles/toolchain paths remain outside the manager-authored materials.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .connections import TrustedConnectionBinding
from .execution_bindings import AdapterRegistration, EnvironmentLimits
from .orx_experiment_tools import ADAPTER_ID, MODEL_ADAPTER_ID, TOOL_NAMES, READ_CAPABILITY, RUN_CAPABILITY
from .orx_local import TaskLocalORXProvider

APPLICATION_ID = "orx-local-toy"
PROFILE_REVISION = "local-orx-profile-v1"
ENVIRONMENT_ADAPTER_ID = "local-orx-profile-environment-v1"
CONNECTION_NAME = "localExperiment"
REGISTRATION_REF = "local-orx-reviewed-toy"


def _environment_config(value: dict[str, Any]) -> None:
    if value:
        raise ValueError("The reviewed local toy environment accepts no material-supplied override")


def environment_registration() -> AdapterRegistration:
    return AdapterRegistration("environment", ENVIRONMENT_ADAPTER_ID, "1", lambda _: EnvironmentLimits(
        runtime_id="local-orx-reviewed-toy-v1", timeout_seconds=30, output_bytes=65536,
        memory_bytes=512 * 1024 * 1024, process_limit=8, cpu_percent=25), validator=_environment_config)


def local_profile_settings(*, db_url: str, workspace: Path, provider: TaskLocalORXProvider,
                           owner: str = "alice", port: int = 3104) -> Settings:
    """Local demo-identity settings; caller must supply a dedicated generated store."""
    trusted = TrustedConnectionBinding(owner, "orx", ADAPTER_ID,
        frozenset({READ_CAPABILITY, RUN_CAPABILITY}), PROFILE_REVISION,
        available=True, opaque_handle=provider, handle_ref=PROFILE_REVISION)
    return Settings(db_url=db_url, workspace=workspace, port=port, max_workers=1,
        max_tool_calls=8, experiment_timeout_seconds=30, experiment_output_bytes=65536,
        temporary_policy="admin-review", policy_revision=PROFILE_REVISION,
        material_policy_revision=PROFILE_REVISION, material_review_mode="separate-admin",
        runtime_tool_contract="local-orx-v1", trusted_connections={REGISTRATION_REF: trusted},
        runtime_adapters=[environment_registration()])


def publish_local_orx_application(state: dict[str, Any], *, author: str, reviewer: str) -> dict[str, Any]:
    """Trusted operator action using current distinct admins and native review history.

    Reusing this exact profile is idempotent. A conflicting prior version fails;
    the installer never silently rewrites a previously published definition.
    """
    if author == reviewer:
        raise ValueError("The local toy profile requires a distinct publication reviewer")
    store, auth = state["store"], state["auth"]
    auth.require(author, "components:write")
    auth.require(reviewer, "agent_os:admin")
    governance, applications = state["material_governance"], state["applications"]

    def publish(identifier, kind, adapter, *, tool_name=None, scenario=None):
        config = {"connectionName": CONNECTION_NAME} if kind == "tool" else {}
        if scenario is not None:
            config["scenario"] = scenario
        permissions = ([RUN_CAPABILITY] if tool_name in {TOOL_NAMES[1], TOOL_NAMES[3]}
                       else [READ_CAPABILITY] if kind == "tool" else [])
        material = governance.create_draft(author, {
            "id": identifier, "kind": kind, "name": "ORX toy " + identifier,
            "description": "Original reviewed deterministic local evaluator; no model provider is called.",
            "content": tool_name or "Reviewed task-owned ORX toy workflow",
            "license": "MIT", "compatibility": ["agno:3.1.0"], "dependencies": [],
            "permissions": permissions, "runtimeBinding": {"adapterId": adapter, "revision": "1", "config": config},
            "provenance": {"kind": "original", "notice": "Original Agent Factory no-provider toy recipe."},
        }, PROFILE_REVISION + ":draft:" + identifier)
        review = governance.request_publication(author, identifier, material["version"], PROFILE_REVISION + ":review:" + identifier)
        governance.decide_publication(reviewer, review["id"], True, PROFILE_REVISION + ":approve:" + identifier)
        return next(row for row in store.materials(published_only=True)
                    if row["id"] == identifier and row["version"] == material["version"])

    def pin(value):
        return {key: value[key] for key in ("id", "version", "sha256")}

    model = publish("orx-toy-model", "model", MODEL_ADAPTER_ID)
    environment = publish("orx-toy-environment", "environment", ENVIRONMENT_ADAPTER_ID)
    common = [publish("orx-toy-" + tool_name.rsplit("_", 1)[1], "tool",
              ADAPTER_ID + "-" + tool_name.rsplit("_", 1)[1], tool_name=tool_name)
              for tool_name in (TOOL_NAMES[0], TOOL_NAMES[2], TOOL_NAMES[3], TOOL_NAMES[4])]
    modes = {}
    for mode, scenario in (("success", "success"), ("evaluator_failure", "evaluator_failure"), ("cancellable", "long_running")):
        launch = publish("orx-toy-run-" + mode, "tool", ADAPTER_ID + "-run", tool_name=TOOL_NAMES[1], scenario=scenario)
        modes[mode] = {"materialRefs": [pin(model), pin(environment), *[pin(value) for value in common], pin(launch)],
            "capabilities": [READ_CAPABILITY, RUN_CAPABILITY], "toolOrder": list(TOOL_NAMES),
            "config": {"scenario": scenario, "recipe": "original-mean-squared-error-v1", "zeroPaidProviders": True},
            "connectionRequirements": [{"name": CONNECTION_NAME, "kind": "orx", "requiredCapabilities": [READ_CAPABILITY, RUN_CAPABILITY], "required": True}],
            "budget": {"toolCalls": 8, "maxDepth": 1, "maxChildren": 1, "experimentSeconds": 30, "outputBytes": 65536}}
    application = applications.create_draft(author, {"id": APPLICATION_ID, "name": "ORX 本地 toy 实验",
        "description": "真实固定版本 CLI 的确定性基线/候选评估，无付费模型调用；toy 结果不等于真实模型科研。",
        "defaultMode": "success", "modes": modes, "discoveryKeywords": ["orx toy", "local toy experiment"]},
        PROFILE_REVISION + ":application")
    review = applications.request_publication(author, application["id"], application["version"], PROFILE_REVISION + ":application-review")
    applications.decide_publication(reviewer, review["id"], True, PROFILE_REVISION + ":application-approve")
    return application

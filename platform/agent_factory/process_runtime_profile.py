"""Operator-opted governed process tools and explicit deterministic fixture profile.

No command, executable, path or environment is accepted from model arguments.
The target is an immutable material pin; its provider is selected by the operator remote-target registry.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from .config import Settings
from .execution_bindings import AdapterRegistration, EnvironmentLimits
from .usage_ledger import PricingRevision

APPLICATION_ID = "bounded-process-fixture-v1"
MODEL_ID = "bounded-process-fixture-model-v1"
PROVIDER_ID = "controlled-process-fixture"
TOOL_ID = "bounded-process-run-v1"
ENVIRONMENT_ID = "bounded-process-environment-v1"
TOOL_NAME = "bounded_process_run"
PERMISSION = "compute:local"
INSTRUCTIONS = "Call bounded_process_run once. Report its original process receipt and evidence. Do not invent results or request commands."


def _target(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", value) is None:
        raise ValueError("PROCESS_TARGET_PIN_INVALID")
    return value


class ProcessFixtureModel(Model):
    """Synthetic workflow driver; never a production model substitute."""
    def __init__(self):
        super().__init__(id=MODEL_ID, name="Controlled process fixture", provider=PROVIDER_ID, retries=0)

    def _response(self, messages):
        results = [message for message in messages if message.role == "tool" and message.tool_name == TOOL_NAME]
        if results:
            if any(message.tool_call_error for message in results):
                raise ValueError("PROCESS_FIXTURE_TOOL_REJECTED")
            return ModelResponse(role="assistant", content=json.dumps({"status": "controlled-fixture-complete",
                "evidenceKind": "native-process-receipt", "modelExecution": "controlled-fixture"}))
        return ModelResponse(role="assistant", tool_calls=[{"id": "bounded-process-fixture-call", "type": "function",
            "function": {"name": TOOL_NAME, "arguments": "{}"}}])

    def invoke(self, messages, **kwargs):
        return self._response(messages)

    async def ainvoke(self, messages, **kwargs):
        return self._response(messages)

    def invoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def registrations(*, target_ref, owner="alice", include_fixture_model=False):
    target_ref = _target(target_ref)

    def config(value):
        if type(value) is not dict or value != {"targetRef": target_ref}:
            raise ValueError("PROCESS_TARGET_PIN_INVALID")

    def runner(ctx):
        config(dict(ctx.spec["config"]))

        @tool
        async def bounded_process_run(run_context: RunContext) -> str:
            """Execute only the approved fixed process target and return its durable receipt."""
            if (any(getattr(run_context, key, None) != getattr(ctx.run_context, key, None)
                    for key in ("user_id", "session_id", "run_id"))
                    or run_context.user_id != ctx.plan.get("ownerId")):
                raise ValueError("PROCESS_TOOL_CONTEXT_INVALID")
            ctx.store.authorize_tool(run_context, TOOL_NAME)
            result = await ctx.store.process_runtime.run(run_context, {"targetRef": target_ref})
            return json.dumps(result, sort_keys=True, allow_nan=False)
        return bounded_process_run

    def fixture(ctx):
        config(dict(ctx.spec["config"]))
        if (ctx.settings.demo is not True or ctx.run_context.user_id != owner
                or ctx.plan.get("ownerId") != owner or ctx.plan.get("application") != APPLICATION_ID
                or (ctx.plan.get("applicationRef") or {}).get("id") != APPLICATION_ID
                or ctx.plan.get("mode") != "controlled-fixture" or ctx.plan.get("delegation")
                or ctx.plan.get("tools") != [TOOL_NAME] or ctx.plan.get("capabilities") != [PERMISSION]):
            raise ValueError("PROCESS_FIXTURE_SCOPE_INVALID")
        return ProcessFixtureModel()

    def environment(ctx):
        config(dict(ctx.spec["config"]))
        return EnvironmentLimits(runtime_id="bounded-process-v1", timeout_seconds=5,
            output_bytes=65536, memory_bytes=128 * 1024 * 1024)

    entries = [AdapterRegistration("tool", TOOL_ID, "1", runner, tool_name=TOOL_NAME,
        permissions=(PERMISSION,), validator=config),
        AdapterRegistration("environment", ENVIRONMENT_ID, "1", environment, validator=config)]
    if include_fixture_model:
        entries.append(AdapterRegistration("model", MODEL_ID, "1", fixture, validator=config, demo_only=True))
    return entries


def process_settings(*, db_url, workspace: Path, target_ref, remote_targets, owner="alice"):
    """Explicit synthetic model settings; caller supplies trusted fixed-target provider."""
    target_ref = _target(target_ref)
    return Settings(db_url=db_url, workspace=workspace, max_workers=1, max_tool_calls=2,
        runtime_tool_contract="bounded-process-v1", temporary_policy="admin-review",
        policy_revision=APPLICATION_ID, material_policy_revision=APPLICATION_ID,
        runtime_adapters=registrations(target_ref=target_ref, owner=owner, include_fixture_model=True),
        remote_targets=remote_targets,
        usage_pricing=(PricingRevision(MODEL_ID, "1", PROVIDER_ID, MODEL_ID, "controlled-local-zero-v1",
            local_model_type=ProcessFixtureModel, per_attempt_input_tokens=32768, per_attempt_output_tokens=4096),))


def publish_process_application(state, *, target_ref, author, reviewer):
    target_ref = _target(target_ref)
    if author == reviewer:
        raise ValueError("Distinct publication reviewer required")
    state["auth"].require(author, "components:write")
    state["auth"].require(reviewer, "agent_os:admin")
    governance, applications = state["material_governance"], state["applications"]
    materials = []
    for kind, name, adapter in (("prompt", "instructions", None), ("model", "model", MODEL_ID),
                              ("tool", TOOL_NAME, TOOL_ID), ("environment", "environment", ENVIRONMENT_ID)):
        identifier = APPLICATION_ID + "-" + name
        definition = {"id": identifier, "kind": kind, "name": "Bounded process " + name,
            "description": "Operator-pinned process target with controlled model workflow.",
            "content": INSTRUCTIONS if kind == "prompt" else name, "license": "MIT",
            "compatibility": ["agno:3.1.0"], "dependencies": [],
            "permissions": [PERMISSION] if kind == "tool" else [],
            "provenance": {"kind": "original", "notice": "Controlled model fixture; process receipts prove only their bounded execution."}}
        if adapter is not None:
            definition["runtimeBinding"] = {"adapterId": adapter, "revision": "1", "config": {
                "targetRef": target_ref}}
        key = identifier + ":" + target_ref
        material = governance.create_draft(author, definition, key + ":draft")
        review = governance.request_publication(author, identifier, material["version"], key + ":review")
        governance.decide_publication(reviewer, review["id"], True, key + ":approve")
        materials.append(material)
    definition = {"id": APPLICATION_ID, "name": "受控进程执行", "defaultMode": "controlled-fixture",
        "description": "固定 operator 目标的原生执行与凭据；模型为确定性测试 fixture。", "discoveryKeywords": [],
        "modes": {"controlled-fixture": {"materialRefs": [{key: row[key] for key in ("id", "version", "sha256")} for row in materials],
            "capabilities": [PERMISSION], "toolOrder": [TOOL_NAME], "config": {},
            "connectionRequirements": [],
            "budget": {"toolCalls": 2, "maxDepth": 1, "maxChildren": 1, "experimentSeconds": 5, "outputBytes": 65536}}}}
    key = APPLICATION_ID + ":" + target_ref
    application = applications.create_draft(author, definition, key + ":draft")
    review = applications.request_publication(author, application["id"], application["version"], key + ":review")
    applications.decide_publication(reviewer, review["id"], True, key + ":approve")
    return application

"""Explicit governed scientific synthesis fixture; no network or provider credentials."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from .config import Settings
from .connections import TrustedConnectionBinding
from .execution_bindings import AdapterRegistration, EnvironmentLimits
from .literature_synthesis import (FIXTURE_PROVIDER, INSTRUCTIONS, KNOWLEDGE_ADAPTER_ID,
    SCIENTIFIC_CAPABILITY, build_source_context, knowledge_registration, validate_synthesis_report)
from .usage_ledger import PricingRevision

APPLICATION_ID = "public-literature-synthesis-fixture-v1"
MODEL_ID = "controlled-scientific-synthesis-v1"
TOOL_ID = "validated-literature-synthesis-save-v1"
ENVIRONMENT_ID = "controlled-literature-environment-v1"
TOOL_NAME = "save_literature_synthesis"
CONNECTION_NAME = "scientificFixture"
REGISTRATION_REF = "controlled-scientific-fixture-binding"
PERMISSION = "research:read"


@dataclass(frozen=True)
class ControlledScientificFixture:
    """Exact local handle: no arbitrary callbacks, transports or credentials."""
    revision: str = "1"


def trusted_model_binding(owner):
    return TrustedConnectionBinding(owner, "model", FIXTURE_PROVIDER,
        frozenset({SCIENTIFIC_CAPABILITY}), "1", opaque_handle=ControlledScientificFixture(),
        available=True, handle_ref=REGISTRATION_REF)


def _validate(report, context):
    return validate_synthesis_report(report, context, provider_id=FIXTURE_PROVIDER,
        capabilities=(SCIENTIFIC_CAPABILITY,), execution_mode="controlled-fixture")


class ScientificFixtureModel(Model):
    def __init__(self, context):
        super().__init__(id=MODEL_ID, name="Controlled scientific workflow fixture", provider=FIXTURE_PROVIDER, retries=0)
        self._context = context

    def _response(self, messages):
        # Require the native immutable-plan knowledge injection, not a prompt
        # supplied by the caller or a model-supplied provenance flag.
        expected = self._context.content
        injected = []
        for message in messages:
            if message.role == "system":
                for line in str(message.content).splitlines():
                    line = line.removeprefix("- ")  # Native Agno renders instruction lists as bullets.
                    if line.startswith("FACTORY_KNOWLEDGE_CONTEXT="):
                        injected.append(json.loads(line.split("=", 1)[1])["content"])
        if expected not in injected:
            raise ValueError("SYNTHESIS_KNOWLEDGE_NOT_INJECTED")
        results = [message for message in messages if message.role == "tool" and message.tool_name == TOOL_NAME]
        if results:
            if any(message.tool_call_error for message in results):
                raise ValueError("SYNTHESIS_TOOL_REJECTED")
            return ModelResponse(role="assistant", content=json.dumps({"status": "controlled-fixture-complete",
                "evidenceKind": "controlled_model_synthesis", "semanticReview": "required"}))
        source = next(row for row in self._context.provenance["snapshot"]["evidence"]["sources"] if row["excerpt"])
        report = {"schema": 1, "claims": [{"text": "The selected source record titled " +
            source["title"] + " contains the quoted limited excerpt; this is not a scientific finding.",
            "sourceIds": [source["sourceId"]], "quotes": [{"sourceId": source["sourceId"], "text": source["excerpt"]}]}],
            "limitations": ["Only the supplied bounded excerpt was inspected; full text may be missing.",
                "Deterministic controlled fixture, not scientific synthesis quality validation. Independent semantic review is required."]}
        _validate(report, self._context)
        return ModelResponse(role="assistant", tool_calls=[{"id": "controlled-synthesis-report", "type": "function",
            "function": {"name": TOOL_NAME, "arguments": json.dumps({"report": report})}}])

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


def registrations(question, evidence_projection, *, owner="alice"):
    source_context = build_source_context(question, evidence_projection)
    fingerprint = source_context.provenance["snapshotSha256"]

    def config(value):
        if value != {"snapshotSha256": fingerprint}:
            raise ValueError("SYNTHESIS_SNAPSHOT_PIN_INVALID")

    def scope(ctx):
        config({key: value for key, value in ctx.spec["config"].items() if key != "connectionName"})
        if (ctx.settings.demo is not True or ctx.plan.get("application") != APPLICATION_ID
                or (ctx.plan.get("applicationRef") or {}).get("id") != APPLICATION_ID
                or ctx.plan.get("mode") != "controlled-fixture" or ctx.run_context.user_id != owner
                or ctx.plan.get("delegation") or ctx.plan.get("tools") != [TOOL_NAME]
                or ctx.plan.get("capabilities") != [PERMISSION]
                or ctx.run_context.user_id != ctx.plan.get("ownerId")):
            raise ValueError("SYNTHESIS_FIXTURE_SCOPE_INVALID")

    def model(ctx):
        scope(ctx)
        if type(ctx.connection) is not ControlledScientificFixture or ctx.connection.revision != "1":
            raise ValueError("SYNTHESIS_FIXTURE_HANDLE_INVALID")
        return ScientificFixtureModel(source_context)

    def saver(ctx):
        scope(ctx)
        @tool
        def save_literature_synthesis(run_context: RunContext, report: dict) -> str:
            """Validate exact source citations and persist a controlled synthesis report."""
            if any(getattr(run_context, key, None) != getattr(ctx.run_context, key, None)
                   for key in ("user_id", "session_id", "run_id")):
                raise ValueError("SYNTHESIS_TOOL_CONTEXT_INVALID")
            store = ctx.store
            store.authorize_tool(run_context, TOOL_NAME)
            checked = _validate(report, source_context)
            document = {**checked, "evidenceKind": "controlled_model_synthesis",
                "citationIntegrityVerified": True, "modelExecution": "controlled-fixture"}
            encoded = json.dumps(document, sort_keys=True, ensure_ascii=False)
            original_hash = hashlib.sha256(encoded.encode()).hexdigest()
            key = "literature-synthesis-report-v1"
            reserved = store.effect_reserve(run_context.run_id, key,
                {"snapshotSha256": fingerprint, "reportSha256": original_hash})
            if reserved["status"] == "done":
                return json.dumps(reserved["result"])
            if reserved["status"] != "new":
                raise ValueError("SYNTHESIS_EFFECT_UNKNOWN_NO_REPLAY")
            metadata = {"evidenceKind": "controlled_model_synthesis", "snapshotSha256": fingerprint,
                "citationIntegrityVerified": True, "semanticReview": "required", "modelAdapterId": MODEL_ID,
                "modelExecution": "controlled-fixture", "sourceEvidenceKind": checked["sourceEvidenceKind"]}
            # Fresh native authority for each individual write. No private path,
            # owner or session comes from the untrusted model report.
            store.authorize_tool(run_context, TOOL_NAME)
            artifact = store.artifact_write(run_context.run_id, "literature-synthesis.json", encoded, metadata=metadata)
            # Indented code text cannot turn source/model strings into active
            # Markdown links, HTML or executable rich content.
            markdown = "# Controlled literature synthesis fixture\n\n" + "\n".join(
                "    " + line for line in json.dumps(report, ensure_ascii=False, indent=2).splitlines())
            markdown += "\n\nCitation structure checked; semantic review required. Snapshot: " + fingerprint
            store.authorize_tool(run_context, TOOL_NAME)
            companion = store.artifact_write(run_context.run_id, "literature-synthesis.md", markdown,
                media_type="text/markdown", metadata=metadata)
            result = {"artifactId": artifact["id"], "markdownArtifactId": companion["id"],
                "originalReportSha256": original_hash, "snapshotSha256": fingerprint,
                "citationIntegrityVerified": True, "semanticReview": "required"}
            store.authorize_tool(run_context, TOOL_NAME)
            store.effect_complete(run_context.run_id, key, result)
            return json.dumps(result)
        return save_literature_synthesis

    return [knowledge_registration(question, evidence_projection, owner_id=owner),
        AdapterRegistration("model", MODEL_ID, "1", model, connection_kind="model",
            required_capabilities=(SCIENTIFIC_CAPABILITY,), connection_adapter_ref=FIXTURE_PROVIDER,
            validator=config, demo_only=True),
        AdapterRegistration("tool", TOOL_ID, "1", saver, tool_name=TOOL_NAME,
            permissions=(PERMISSION,), validator=config, demo_only=True),
        AdapterRegistration("environment", ENVIRONMENT_ID, "1", lambda ctx: EnvironmentLimits(),
            validator=config, demo_only=True)]


def synthesis_settings(*, db_url, workspace: Path, question, evidence_projection, owner="alice"):
    return Settings(db_url=db_url, workspace=workspace, max_workers=1, max_tool_calls=2,
        runtime_tool_contract="scientific-synthesis-fixture-v1",
        temporary_policy="read-only-auto", policy_revision=APPLICATION_ID, material_policy_revision=APPLICATION_ID,
        runtime_adapters=registrations(question, evidence_projection, owner=owner),
        trusted_connections={REGISTRATION_REF: trusted_model_binding(owner)},
        usage_pricing=(PricingRevision(MODEL_ID, "1", FIXTURE_PROVIDER, MODEL_ID, "controlled-local-zero-v1",
            local_model_type=ScientificFixtureModel, per_attempt_input_tokens=32768, per_attempt_output_tokens=4096),))


def publish_synthesis_application(state, question, evidence_projection, *, author, reviewer):
    if author == reviewer:
        raise ValueError("Distinct publication reviewer required")
    state["auth"].require(author, "components:write")
    state["auth"].require(reviewer, "agent_os:admin")
    context = build_source_context(question, evidence_projection)
    fingerprint = context.provenance["snapshotSha256"]
    governance, applications = state["material_governance"], state["applications"]
    materials = []
    for kind, name, adapter in (("knowledge", "sources", KNOWLEDGE_ADAPTER_ID),
            ("prompt", "instructions", None), ("model", "model", MODEL_ID),
            ("tool", TOOL_NAME, TOOL_ID), ("environment", "environment", ENVIRONMENT_ID)):
        identifier = APPLICATION_ID + "-" + name
        definition = {"id": identifier, "kind": kind, "name": "Controlled literature " + name,
            "description": "Controlled offline model workflow; independent scientific review required.",
            "content": context.content if kind == "knowledge" else INSTRUCTIONS if kind == "prompt" else name,
            "license": "MIT", "compatibility": ["agno:3.1.0"], "dependencies": [],
            "permissions": [PERMISSION] if kind == "tool" else [],
            "provenance": {"kind": "original", "notice": "Controlled workflow fixture. Source records retain separate provenance; not a scientific finding."}}
        if adapter is not None:
            definition["runtimeBinding"] = {"adapterId": adapter, "revision": "1",
                "config": {"snapshotSha256": fingerprint, **({"connectionName": CONNECTION_NAME} if kind == "model" else {})}}
        material = governance.create_draft(author, definition, identifier + ":draft:" + fingerprint)
        review = governance.request_publication(author, identifier, material["version"], identifier + ":review:" + fingerprint)
        governance.decide_publication(reviewer, review["id"], True, identifier + ":approve:" + fingerprint)
        materials.append(material)
    definition = {"id": APPLICATION_ID, "name": "受控文献综合流程", "defaultMode": "controlled-fixture",
        "description": "离线原生流程与引用完整性验证；科研语义仍需人工审查。", "discoveryKeywords": [],
        "modes": {"controlled-fixture": {"materialRefs": [{key: row[key] for key in ("id", "version", "sha256")} for row in materials],
            "capabilities": [PERMISSION], "toolOrder": [TOOL_NAME], "config": {},
            "connectionRequirements": [{"name": CONNECTION_NAME, "kind": "model", "requiredCapabilities": [], "required": True}],
            "budget": {"toolCalls": 2, "maxDepth": 1, "maxChildren": 1, "experimentSeconds": 8, "outputBytes": 65536}}}}
    application = applications.create_draft(author, definition, APPLICATION_ID + ":draft:" + fingerprint)
    review = applications.request_publication(author, application["id"], application["version"], APPLICATION_ID + ":review:" + fingerprint)
    applications.decide_publication(reviewer, review["id"], True, APPLICATION_ID + ":approve:" + fingerprint)
    return application

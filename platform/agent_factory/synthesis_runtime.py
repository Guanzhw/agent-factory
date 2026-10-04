"""Static governed adapters resolve owner-bound source snapshots from each plan.

Only deterministic local scientific workflow fixtures are supported. Creating
these declarations neither publishes materials nor grants any connection.
"""
from __future__ import annotations

import re
from typing import Any

from .execution_bindings import AdapterRegistration, EnvironmentLimits
from .literature_synthesis import FIXTURE_PROVIDER, INSTRUCTIONS, SCIENTIFIC_CAPABILITY, build_source_context
from .literature_synthesis_profile import (CONNECTION_NAME, PERMISSION, TOOL_NAME,
    ControlledScientificFixture, ScientificFixtureModel, MODEL_ID as FIXTURE_MODEL_ID)
from .usage_ledger import PricingRevision

APPLICATION_ID = "source-grounded-synthesis-fixture-v1"
SCOPE = "plan-bound-synthesis-v1"
REVISION = "1"
MODEL_ID = "plan-bound-scientific-model-v1"
KNOWLEDGE_ID = "plan-bound-scientific-sources-v1"
TOOL_ID = "plan-bound-scientific-save-v1"
ENVIRONMENT_ID = "plan-bound-scientific-environment-v1"


def _require(value):
    if not value:
        raise ValueError("SYNTHESIS_RUNTIME_SCOPE_INVALID")


def _config(value):
    _require(type(value) is dict and value == {"scope": SCOPE})


def _scope(ctx):
    _config({key: value for key, value in ctx.spec.get("config", {}).items() if key != "connectionName"})
    owner = getattr(ctx.run_context, "user_id", None)
    _require(type(owner) is str and bool(owner) and ctx.plan.get("ownerId") == owner)
    _require(ctx.settings.demo is True and getattr(ctx.settings, "source_synthesis_enabled", False) is True
             and type(ctx.plan.get("application")) is str and bool(ctx.plan["application"])
             and (ctx.plan.get("applicationRef") or {}).get("id") == ctx.plan["application"]
             and ctx.plan.get("mode") == "controlled-fixture" and not ctx.plan.get("delegation")
             and ctx.plan.get("tools") == [TOOL_NAME] and ctx.plan.get("capabilities") == [PERMISSION])
    return owner


def resolve_context(ctx):
    """Resolve only a server-created reference inside the immutable native plan."""
    owner = _scope(ctx)
    ref = ctx.plan.get("sourceSnapshotRef")
    _require(type(ref) is dict and set(ref) == {"id", "fingerprint"}
             and type(ref["id"]) is str and 1 <= len(ref["id"]) <= 128
             and type(ref["fingerprint"]) is str and re.fullmatch(r"[a-f0-9]{64}", ref["fingerprint"]))
    snapshot = ctx.store.synthesis_sources.revalidate(owner, ref["id"], expected_fingerprint=ref["fingerprint"])
    _require(type(snapshot) is dict and snapshot.get("fingerprint") == ref["fingerprint"])
    context = build_source_context(snapshot["question"], snapshot["projection"])
    _require(context.provenance["snapshotSha256"] == snapshot.get("contextFingerprint"))
    return context


def registrations():
    def knowledge(ctx):
        return resolve_context(ctx)

    def model(ctx):
        context = resolve_context(ctx)
        _require(type(ctx.connection) is ControlledScientificFixture and ctx.connection.revision == "1")
        return ScientificFixtureModel(context)

    def environment(ctx):
        resolve_context(ctx)
        return EnvironmentLimits()

    def saver(ctx):
        # Shared implementation owns citation validation, bounded artifacts and
        # durable effects; no second saver or orchestration is introduced here.
        from .literature_synthesis_profile import make_synthesis_saver
        context = resolve_context(ctx)

        def revalidate():
            current = resolve_context(ctx)
            _require(current == context)

        return make_synthesis_saver(ctx, context, revalidate=revalidate)

    return [AdapterRegistration("knowledge", KNOWLEDGE_ID, REVISION, knowledge, validator=_config, demo_only=True),
        AdapterRegistration("model", MODEL_ID, REVISION, model, connection_kind="model",
            required_capabilities=(SCIENTIFIC_CAPABILITY,), connection_adapter_ref=FIXTURE_PROVIDER,
            validator=_config, demo_only=True),
        AdapterRegistration("tool", TOOL_ID, REVISION, saver, tool_name=TOOL_NAME,
            permissions=(PERMISSION,), validator=_config, demo_only=True),
        AdapterRegistration("environment", ENVIRONMENT_ID, REVISION, environment, validator=_config, demo_only=True)]


def material_drafts():
    """Six inert material definitions for the normal separate-review workflow."""
    rows: list[dict[str, Any]] = []
    for kind, name, adapter in (("skill", "method", None), ("prompt", "instructions", None),
            ("knowledge", "sources", KNOWLEDGE_ID), ("model", "model", MODEL_ID),
            ("tool", TOOL_NAME, TOOL_ID), ("environment", "environment", ENVIRONMENT_ID)):
        row: dict[str, Any] = {"id": SCOPE + "-" + name, "kind": kind,
            "name": "受控文献综合 · " + name,
            "description": "从任务固定来源快照检查引用结构；科研语义必须独立人工审查。",
            "content": INSTRUCTIONS if kind in {"skill", "prompt"} else name if kind == "tool" else "Owner-bound plan snapshot; controlled fixture execution only.",
            "license": "MIT", "compatibility": ["agno:3.1.0"], "dependencies": [],
            "permissions": [PERMISSION] if kind == "tool" else [],
            "provenance": {"kind": "original", "notice": "Controlled offline workflow fixture; not scientific quality validation."}}
        if adapter:
            row["runtimeBinding"] = {"adapterId": adapter, "revision": REVISION,
                "config": {"scope": SCOPE, **({"connectionName": CONNECTION_NAME} if kind == "model" else {})}}
        rows.append(row)
    return rows


def application_definition(materials: list[dict[str, Any]]):
    """Pure draft; caller must obtain governed material and application reviews."""
    expected = {row["id"]: row["kind"] for row in material_drafts()}
    _require(type(materials) is list and len(materials) == len(expected))
    _require({row.get("id"): row.get("kind") for row in materials} == expected)
    refs = []
    for row in materials:
        _require(type(row.get("version")) is int and row["version"] > 0
                 and type(row.get("sha256")) is str and re.fullmatch(r"[a-f0-9]{64}", row["sha256"]))
        refs.append({key: row[key] for key in ("id", "version", "sha256")})
    return {"id": APPLICATION_ID, "name": "固定来源的受控文献综合", "defaultMode": "controlled-fixture",
        "description": "选择已有来源证据、审查新计划、运行离线综合并检查产物；科研语义仍需人工审查。",
        "discoveryKeywords": [], "modes": {"controlled-fixture": {"materialRefs": refs,
            "capabilities": [PERMISSION], "toolOrder": [TOOL_NAME], "config": {},
            "connectionRequirements": [{"name": CONNECTION_NAME, "kind": "model", "requiredCapabilities": [], "required": True}],
            "budget": {"toolCalls": 2, "maxDepth": 1, "maxChildren": 1, "experimentSeconds": 8, "outputBytes": 65536}}}}


def pricing_registration():
    """Named local fixture accounting, not provider invoice evidence."""
    return PricingRevision(MODEL_ID, REVISION, FIXTURE_PROVIDER, FIXTURE_MODEL_ID,
        "controlled-local-zero-v1", local_model_type=ScientificFixtureModel,
        per_attempt_input_tokens=32768, per_attempt_output_tokens=4096)


def inspect_synthesis_evidence(store, owner, task_id):
    """Verify historical artifacts independently of stored success flags."""
    import hashlib
    import json
    from fastapi import HTTPException
    from .literature_synthesis import validate_synthesis_report

    task = store.task(task_id, owner)  # Ownership must precede every private read.
    plan = store.plan(task["plan_id"], owner)
    ref = plan.get("sourceSnapshotRef")
    if ref is None:
        return None
    empty = {"schema": 1, "status": "pending", "evidenceKind": "controlled_model_synthesis",
             "snapshotRef": None, "snapshotSha256": None, "sourceEvidenceKind": None,
             "sourceCurrent": None, "report": None, "citationStructureVerified": False,
             "semanticReview": "required", "scientificConclusionVerified": False, "artifactIds": None}
    try:
        _require(type(ref) is dict and set(ref) == {"id", "fingerprint"})
        snapshot = store.synthesis_sources.read(owner, ref["id"])
        _require(snapshot["fingerprint"] == ref["fingerprint"])
        context = build_source_context(snapshot["question"], snapshot["projection"])
        fingerprint = context.provenance["snapshotSha256"]
        _require(fingerprint == snapshot["contextFingerprint"])
        model_binding = plan.get("executionBindings", {}).get("model", {})
        _require(model_binding.get("adapterId") == MODEL_ID and model_binding.get("revision") == REVISION)
        artifacts = store.artifacts(task_id)
        reports = [row for row in artifacts if row.get("name") == "literature-synthesis.json"]
        companions = [row for row in artifacts if row.get("name") == "literature-synthesis.md"]
        if not reports and not companions:
            return empty
        _require(len(reports) == len(companions) == 1)
        report, companion = reports[0], companions[0]
        expected = {"ownerId": owner, "taskId": task_id, "planId": plan["id"],
                    "planFingerprint": plan["fingerprint"], "sourceSnapshotRef": ref,
                    "evidenceKind": "controlled_model_synthesis", "snapshotSha256": fingerprint,
                    "citationIntegrityVerified": True, "semanticReview": "required", "modelAdapterId": MODEL_ID,
                    "modelExecution": "controlled-fixture", "sourceEvidenceKind": context.provenance["sourceEvidenceKind"]}
        raw_files = []
        for artifact, media in ((report, "application/json"), (companion, "text/markdown")):
            _require(artifact.get("jobId") == task_id and artifact.get("mediaType") == media)
            _require(type(artifact.get("size")) is int and 0 < artifact["size"] <= 65536)
            metadata = artifact.get("provenance")
            _require(type(metadata) is dict and all(type(metadata.get(key)) is type(value) and metadata.get(key) == value
                                                   for key, value in expected.items()))
            stored, raw = store.artifact(task_id, artifact["id"])
            _require(stored == artifact and type(raw) is bytes and len(raw) == artifact["size"]
                     and hashlib.sha256(raw).hexdigest() == artifact["sha256"])
            raw_files.append(raw)
        document = json.loads(raw_files[0])
        _require(type(document) is dict)
        checked = validate_synthesis_report(document.get("report"), context, provider_id=FIXTURE_PROVIDER,
            capabilities=(SCIENTIFIC_CAPABILITY,), execution_mode="controlled-fixture")
        expected_document = {**checked, "evidenceKind": "controlled_model_synthesis",
                             "citationIntegrityVerified": True, "modelExecution": "controlled-fixture"}
        _require(json.dumps(document, sort_keys=True) == json.dumps(expected_document, sort_keys=True))
        original_hash = hashlib.sha256(json.dumps(expected_document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        markdown = raw_files[1].decode("utf-8")
        header = "# Controlled literature synthesis fixture\n\n"
        footer = "\n\nCitation structure checked; semantic review required. Snapshot: " + fingerprint
        _require(markdown.startswith(header) and markdown.endswith(footer))
        lines = markdown[len(header):-len(footer)].splitlines()
        _require(bool(lines) and all(line.startswith("    ") for line in lines))
        _require(json.loads("\n".join(line[4:] for line in lines)) == checked["report"])
        effects = [row for row in store.effects(task_id) if row.get("effect_key") == task["run_id"] + ":literature-synthesis-report-v1"]
        _require(len(effects) == 1 and effects[0].get("status") == "DONE")
        _require(effects[0].get("result") == {"artifactId": report["id"], "markdownArtifactId": companion["id"],
            "originalReportSha256": original_hash, "snapshotSha256": fingerprint,
            "citationIntegrityVerified": True, "semanticReview": "required"})
        source_current = True
        try:
            current = store.synthesis_sources.revalidate(owner, ref["id"], expected_fingerprint=ref["fingerprint"])
            _require(current == snapshot)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, HTTPException, RuntimeError):
            source_current = False
        return {**empty, "status": "ready", "snapshotRef": dict(ref), "snapshotSha256": fingerprint,
                "sourceEvidenceKind": checked["sourceEvidenceKind"], "sourceCurrent": source_current,
                "report": checked["report"], "citationStructureVerified": True,
                "artifactIds": {"json": report["id"], "markdown": companion["id"]}}
    except (ValueError, TypeError, KeyError, AttributeError, OSError, HTTPException, RuntimeError):
        return {**empty, "status": "invalid"}


def validate_plan_source(store, plan):
    """Fresh source custody check used by native execution guards, never grants."""
    execution = plan.get("executionBindings") or {}
    items = [execution.get("model", {}), execution.get("environment", {}),
             *execution.get("tools", []), *execution.get("knowledge", [])]
    related = plan.get("sourceSnapshotRef") is not None or any(
        row.get("adapterId") in {MODEL_ID, TOOL_ID, KNOWLEDGE_ID, ENVIRONMENT_ID} for row in items)
    if not related:
        return
    settings = store.settings
    _require(settings.demo is True and getattr(settings, "source_synthesis_enabled", False) is True
             and settings.temporary_policy == "admin-review")
    _require(plan.get("mode") == "controlled-fixture" and plan.get("tools") == [TOOL_NAME]
             and plan.get("capabilities") == [PERMISSION] and not plan.get("delegation")
             and not plan.get("remoteHandoff"))
    expected: list[tuple[Any, str]] = [(execution.get("model"), MODEL_ID), (execution.get("environment"), ENVIRONMENT_ID)]
    _require(type(execution.get("tools")) is list and len(execution["tools"]) == 1
             and type(execution.get("knowledge")) is list and len(execution["knowledge"]) == 1)
    expected.extend([(execution["tools"][0], TOOL_ID), (execution["knowledge"][0], KNOWLEDGE_ID)])
    for spec, adapter in expected:
        _require(type(spec) is dict and spec.get("adapterId") == adapter and spec.get("revision") == REVISION)
        _config({key: value for key, value in spec.get("config", {}).items() if key != "connectionName"})
    _require(execution["tools"][0].get("toolName") == TOOL_NAME)
    ref = plan.get("sourceSnapshotRef")
    _require(type(ref) is dict and set(ref) == {"id", "fingerprint"}
             and type(ref["id"]) is str and 1 <= len(ref["id"]) <= 128
             and type(ref["fingerprint"]) is str and re.fullmatch(r"[a-f0-9]{64}", ref["fingerprint"]))
    _require((plan.get("bindingManifest") or {}).get("sourceSnapshotRef") == ref)
    owner = plan.get("ownerId")
    _require(type(owner) is str and bool(owner))
    snapshot = store.synthesis_sources.revalidate(owner, ref["id"], expected_fingerprint=ref["fingerprint"])
    _require(snapshot["fingerprint"] == ref["fingerprint"] and snapshot["question"] == plan.get("normalizedGoal"))
    context = build_source_context(snapshot["question"], snapshot["projection"])
    _require(context.provenance["snapshotSha256"] == snapshot["contextFingerprint"])

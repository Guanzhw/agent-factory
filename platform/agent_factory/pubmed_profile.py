"""Explicit governed host-HTTP PubMed evidence; no Linux containment claim."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path

import httpx
from agno.exceptions import RunCancelledException
from agno.models.response import ModelResponse
from agno.run import RunContext

from .config import Settings
from .connections import TrustedConnectionBinding
from .execution_bindings import AdapterRegistration, EnvironmentLimits
from .orx_experiment_tools import LocalORXWorkflowModel, _limits
from .orx_literature_tools import report_bundle
from .store import digest
from .usage_ledger import PricingRevision

APPLICATION_ID = "public-literature-host-v1"
PROFILE = APPLICATION_ID
ADAPTER_ID = "public-pubmed-http-v1"
MODEL_ID = "public-pubmed-local-model-v1"
ENVIRONMENT_ID = "public-pubmed-host-environment-v1"
TOOL = "pubmed_sources_report"
REVISION = "2"
CAPABILITY = "research:read"
CONNECTION_NAME = "publicPubMed"
REGISTRATION_REF = "reviewed-public-pubmed-host-v1"
CONFIG = {"queryId": "public-rag-v1", "limit": 2}


@dataclass(frozen=True)
class PubMedProvider:
    owner_id: str
    transport: httpx.MockTransport | None = None

    def __post_init__(self):
        if not self.owner_id or (self.transport is not None and type(self.transport) is not httpx.MockTransport):
            raise ValueError("An owner and exact offline MockTransport or public transport are required")

    async def retrieve(self, *, before_dispatch):
        from .pubmed_retrieval import retrieve
        return await retrieve(query_id=CONFIG["queryId"], limit=CONFIG["limit"], transport=self.transport, before_dispatch=before_dispatch)


_PROVIDER_RETRIEVE = PubMedProvider.retrieve


def _provider(value, owner):
    if (type(value) is not PubMedProvider or value.owner_id != owner
            or type(value).retrieve is not _PROVIDER_RETRIEVE
            or getattr(value.retrieve, "__func__", None) is not _PROVIDER_RETRIEVE
            or (value.transport is not None and type(value.transport) is not httpx.MockTransport)):
        raise PermissionError("Current trusted PubMed provider identity differs")


def _config(value):
    if value != CONFIG:
        raise ValueError("Only the immutable public PubMed query profile is allowed")


def _empty(value):
    if value:
        raise ValueError("The host evidence profile has no material overrides")


@dataclass
class PubMedEvidenceModel(LocalORXWorkflowModel):
    id: str = MODEL_ID
    name: str = "Public bibliography and excerpts, no provider"
    provider: str = "local-deterministic"

    def _response(self, messages):
        completed = [message for message in messages if message.role == "tool"]
        if completed:
            value = {}
            try:
                value = json.loads(completed[-1].content)
            except (ValueError, TypeError):
                pass
            failed = any(message.tool_call_error for message in completed) or bool(value.get("retrievalError"))
            status = "retrieval-failed" if failed else "evidence-ready" if value.get("sources") else "no-sources"
            return ModelResponse(role="assistant", content=json.dumps({"status": status,
                "notice": "书目与有界摘录证据；零来源或检索失败不代表研究成功。未调用模型服务，未生成科研综合结论。"}, ensure_ascii=False))
        return ModelResponse(role="assistant", tool_calls=[{"id": "pubmed-evidence-once", "type": "function",
            "function": {"name": TOOL, "arguments": "{}"}}])


def _tool_factory(context):
    _config({key: value for key, value in context.spec.get("config", {}).items() if key != "connectionName"})
    owner, task = context.run_context.user_id, context.run_context.session_id
    handle, fixed = context.connection, context.spec["connection"]
    _provider(handle, owner)

    def authorize(ctx):
        if (ctx.user_id, ctx.session_id, ctx.run_id) != (owner, task, context.run_context.run_id):
            raise PermissionError("PubMed callable belongs to another task")
        plan = context.store.resolve_run(ctx)
        if plan["id"] != context.plan["id"] or plan.get("fingerprint") != context.plan.get("fingerprint"):
            raise PermissionError("Immutable PubMed plan changed")
        context.store.authorize_tool(ctx, TOOL)
        if context.store.cancellation_requested(ctx.run_id):
            raise RunCancelledException("Public retrieval cancelled")
        current = context.store.connections.resolve(owner, fixed["ref"], "orx", expected_version=fixed["version"],
            expected_revision=fixed["revision"], expected_fingerprint=fixed["fingerprint"],
            expected_adapter_ref=ADAPTER_ID, required_capabilities=(CAPABILITY,), task_id=task)
        _provider(current, owner)
        if current is not handle:
            raise PermissionError("Current trusted PubMed provider changed")
        return plan

    async def pubmed_sources_report(run_context: RunContext) -> str:
        """Retrieve the reviewed PubMed query and save bibliography/excerpt evidence."""
        plan = authorize(run_context)
        environment = context.store.execution_bindings.environment_limits(plan, run_context)
        output, timeout, _ = _limits(context.settings, plan, environment)
        fingerprint = digest({"plan": plan["fingerprint"], "tool": TOOL, "config": CONFIG, "connection": fixed})
        key = "pubmed-evidence:" + fingerprint[:40]
        reservation = context.store.effect_reserve(run_context.run_id, key, {"fingerprint": fingerprint})
        if reservation["status"] == "done":
            return json.dumps(reservation["result"], ensure_ascii=False)
        if reservation["status"] == "unknown":
            raise PermissionError("Unknown PubMed retrieval effect; automatic replay refused")
        from .pubmed_retrieval import PubMedRetrievalError
        retrieval_error = None
        operation = asyncio.create_task(handle.retrieve(before_dispatch=lambda: authorize(run_context)))
        try:
            async with asyncio.timeout(timeout):
                while not operation.done():
                    await asyncio.wait({operation}, timeout=.25)
                    authorize(run_context)
                retrieved = await operation
        except PubMedRetrievalError as error:
            retrieval_error = error.code
            retrieved = {"sources": [], "evidenceMode": "controlled-fixture" if handle.transport is not None else "live-public-fetch",
                         "provenance": {"retrievalHttpStatus": error.http_status}}
        finally:
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        authorize(run_context)
        kind = "controlled_literature_fixture" if handle.transport is not None else "public_literature_excerpt"
        sources = [{**source, "evidenceKind": kind} for source in retrieved["sources"]]
        provenance = {**retrieved.get("provenance", {}), "evidenceKind": kind, "contractRevision": REVISION,
            "mode": "bibliography-excerpts-no-provider", "ownerId": owner, "taskId": task,
            "planId": plan["id"], "planFingerprint": plan["fingerprint"], "connection": fixed,
            "effectFingerprint": fingerprint, "tool": TOOL, "transportBoundary": "bounded-host-http",
            "retrievalErrors": [retrieval_error] if retrieval_error else []}
        document = {"mode": provenance["mode"], "evidenceMode": retrieved.get("evidenceMode"),
                    "sources": sources, "provenance": provenance, "retrievalError": retrieval_error}
        raw = json.dumps(document, ensure_ascii=False, sort_keys=True).encode()
        report, bundle = report_bundle(sources, provenance)
        if max(len(raw), len(report), len(bundle)) > output:
            raise ValueError("PubMed evidence exceeds approved output bound")
        artifacts = []
        for name, content, media in (("literature-sources-" + fingerprint[:16] + ".json", raw, "application/json"),
                ("literature-report-" + fingerprint[:16] + ".md", report, "text/markdown; charset=utf-8"),
                ("literature-evidence-" + fingerprint[:16] + ".zip", bundle, "application/zip")):
            authorize(run_context)
            artifacts.append(context.store.artifact_write(task, name, content, media, provenance))
        authorize(run_context)
        result = {**document, "artifacts": [{key: item[key] for key in ("id", "name", "sha256")} for item in artifacts]}
        context.store.effect_complete(run_context.run_id, key, result)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)
    return pubmed_sources_report


def registrations():
    return [AdapterRegistration("model", MODEL_ID, "1", lambda _: PubMedEvidenceModel(), demo_only=True, validator=_empty),
        AdapterRegistration("environment", ENVIRONMENT_ID, "1", lambda _: EnvironmentLimits(
            runtime_id="public-pubmed-bounded-host-http", timeout_seconds=30, output_bytes=65536), demo_only=True, validator=_empty),
        AdapterRegistration("tool", ADAPTER_ID, REVISION, _tool_factory, tool_name=TOOL, connection_kind="orx",
            required_capabilities=(CAPABILITY,), permissions=(CAPABILITY,), demo_only=True,
            validator=_config, connection_adapter_ref=ADAPTER_ID)]


def pubmed_settings(*, db_url: str, workspace: Path, provider: PubMedProvider, owner="alice", port=3107):
    _provider(provider, owner)
    trusted = TrustedConnectionBinding(owner, "orx", ADAPTER_ID, frozenset({CAPABILITY}), PROFILE,
        available=True, opaque_handle=provider, handle_ref=PROFILE)
    return Settings(db_url=db_url, workspace=workspace, port=port, demo=True, max_workers=1,
        max_tool_calls=1, experiment_timeout_seconds=30, experiment_output_bytes=65536,
        storage_task_reserve_bytes=8 * 1024 * 1024, temporary_policy="admin-review",
        policy_revision=PROFILE, material_policy_revision=PROFILE, material_review_mode="separate-admin",
        runtime_tool_contract="pubmed-host-evidence-v1", trusted_connections={REGISTRATION_REF: trusted},
        runtime_adapters=registrations(), usage_pricing=(PricingRevision(MODEL_ID, "1", "local-deterministic",
            MODEL_ID, "zero-local-v1", local_model_type=PubMedEvidenceModel),))


def publish_pubmed_application(state, *, author, reviewer):
    if author == reviewer:
        raise ValueError("A distinct publication reviewer is required")
    state["auth"].require(author, "components:write")
    state["auth"].require(reviewer, "agent_os:admin")
    governance, applications, store = state["material_governance"], state["applications"], state["store"]
    materials = []
    for kind, adapter, revision in (("model", MODEL_ID, "1"), ("environment", ENVIRONMENT_ID, "1"), ("tool", ADAPTER_ID, REVISION)):
        identifier = PROFILE + "-" + kind
        item = governance.create_draft(author, {"id": identifier, "kind": kind, "name": "PubMed 文献证据 " + kind,
            "description": "独立主机 HTTP 公共书目与有界摘要；无模型综合，不声称容器隔离。", "content": TOOL if kind == "tool" else kind,
            "license": "MIT", "compatibility": ["agno:3.1.0"], "dependencies": [], "permissions": [CAPABILITY] if kind == "tool" else [],
            "runtimeBinding": {"adapterId": adapter, "revision": revision,
                "config": {"connectionName": CONNECTION_NAME, **CONFIG} if kind == "tool" else {}},
            "provenance": {"kind": "original", "notice": "Original host-HTTP public bibliography workflow; no model provider."}}, PROFILE + ":draft:" + kind)
        review = governance.request_publication(author, identifier, item["version"], PROFILE + ":review:" + kind)
        governance.decide_publication(reviewer, review["id"], True, PROFILE + ":approve:" + kind)
        materials.append(next(row for row in store.materials(published_only=True) if row["id"] == identifier and row["version"] == item["version"]))
    app = applications.create_draft(author, {"id": APPLICATION_ID, "name": "PubMed 公开文献证据（主机 HTTP）",
        "description": "书目与摘要证据；无模型综合，不声称容器隔离。", "defaultMode": "bibliography", "discoveryKeywords": ["公开文献", "PubMed", "public literature"],
        "modes": {"bibliography": {"materialRefs": [{key: item[key] for key in ("id", "version", "sha256")} for item in materials],
            "capabilities": [CAPABILITY], "toolOrder": [TOOL], "config": {},
            "connectionRequirements": [{"name": CONNECTION_NAME, "kind": "orx", "requiredCapabilities": [CAPABILITY], "required": True}],
            "budget": {"toolCalls": 1, "maxDepth": 1, "maxChildren": 1, "experimentSeconds": 30, "outputBytes": 65536}}}}, PROFILE + ":application")
    review = applications.request_publication(author, app["id"], app["version"], PROFILE + ":app-review")
    applications.decide_publication(reviewer, review["id"], True, PROFILE + ":app-approve")
    return app

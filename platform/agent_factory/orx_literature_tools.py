"""Governed, no-provider bibliography/excerpt evidence; never model synthesis."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import zipfile
from typing import Any
from urllib.parse import quote

from agno.exceptions import RunCancelledException
from agno.run import RunContext

from .openresearch import OpenResearchError
from .retrieval_diagnostics import safe_retrieval_diagnostic
from .orx_experiment_tools import _limits
from .orx_pins import approved_pin
from .orx_retrieval import LinuxRetrievalAdapter
from .orx_tools import ORX_ADAPTER_ID, CAPABILITY
from .store import digest

REVISION = "2"
TOOLS = {"orx_discover": ORX_ADAPTER_ID, "orx_paper": "openresearch-paper-v1",
         "orx_text": "openresearch-text-v1", "orx_sources_report": "openresearch-sources-report-v1"}
PUBLIC_QUERIES = {"public-rag-v1": "retrieval augmented generation"}
ARXIV = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?\Z")
LEGACY_ARXIV = re.compile(r"[a-z-]+/\d{7}(?:v\d+)?\Z")


def source_url(identifier: str) -> str:
    if ARXIV.fullmatch(identifier) or LEGACY_ARXIV.fullmatch(identifier):
        return "https://arxiv.org/abs/" + identifier
    if re.fullmatch(r"(?:pmid:)?\d{1,20}", identifier):
        return "https://pubmed.ncbi.nlm.nih.gov/" + identifier.removeprefix("pmid:") + "/"
    if re.fullmatch(r"W\d{1,30}", identifier):
        return "https://openalex.org/" + identifier
    if re.fullmatch(r"10\.\d{4,9}/[A-Za-z0-9._;()/:-]{1,300}", identifier) and ".." not in identifier.split("/"):
        return "https://doi.org/" + quote(identifier, safe="/():;._-")
    raise ValueError("Expected a canonical public source identifier")


def excerpt(text: str, *, field: str) -> dict[str, Any]:
    # A short contiguous quotation, with an exact locator in the hashed CLI
    # rendition/metadata field. A CLI hash is explicitly not a PDF/source hash.
    start = len(text) - len(text.lstrip())
    words = list(re.finditer(r"\S+", text[start:]))[:20]
    end = min(start + 160, start + words[-1].end()) if words else start
    return {"excerpt": text[start:end], "locator": {"kind": "unicode_character_range",
            "field": field, "start": start, "endExclusive": end, "line": text.count("\n", 0, start) + 1}}


def evidence_record(identifier: str, text: str, *, status: str, field: str,
                    title: str = "", error_code: str | None = None) -> dict[str, Any]:
    return {"sourceId": identifier, "url": source_url(identifier), "title": title[:240],
            "sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
            "hashScope": "decoded_cli_rendition" if field == "stdout" else "metadata_abstract",
            "textStatus": status, "fullTextAvailable": status == "extracted_text",
            "missingFullTextReason": None if status == "extracted_text" else status,
            "errorCode": error_code, **excerpt(text, field=field)}


def validate_config(value):
    if set(value) - {"queryId", "corpus", "limit"}:
        raise ValueError("Only a reviewed public query ID, corpus and result limit are configurable")
    if value.get("queryId") not in PUBLIC_QUERIES:
        raise ValueError("An installed immutable public query profile is required")
    if value.get("corpus", "pubmed") not in {"pubmed", "biorxiv", "openalex", "keyword"}:
        raise ValueError("Unsupported free public corpus")
    if type(value.get("limit", 2)) is not int or not 1 <= value.get("limit", 2) <= 3:
        raise ValueError("Public retrieval permits one through three results")


def _sources(store, ctx):
    records = {}
    for item in store.artifacts(ctx.session_id):
        provenance = item.get("provenance", {})
        if (provenance.get("evidenceKind") not in {"public_literature_excerpt", "controlled_literature_fixture"} or provenance.get("contractRevision") != REVISION
                or not item.get("name", "").startswith("literature-sources-") or not item["name"].endswith(".json")):
            continue
        _, raw = store.artifact(ctx.session_id, item["id"])
        document = json.loads(raw)
        for source in document.get("sources", []):
            previous = records.get(source["sourceId"], {})
            if not source.get("title"):
                source["title"] = previous.get("title", "")
            if not source.get("excerpt") and previous.get("excerpt"):
                source = {**previous, "lastTextAttemptStatus": source["textStatus"],
                          "lastRetrievalError": source["errorCode"],
                          **({"missingFullTextReason": source["missingFullTextReason"], "errorCode": source["errorCode"]}
                             if not previous.get("fullTextAvailable") else {})}
            records[source["sourceId"]] = source
    return list(records.values())


def report_bundle(sources, provenance):
    from html import escape

    def plain(value):
        # Source-controlled strings remain text, never Markdown links or HTML.
        text = escape(str(value), quote=True).replace("\r", " ").replace("\n", " ")
        text = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)
        return text.replace(":", "&#58;")

    def error_text(value):
        if isinstance(value, str) and value in {"COMMAND_FAILED", "TIMEOUT", "OUTPUT_LIMIT"}:
            return "`" + value + "`"
        return plain(value)

    kinds = {source.get("evidenceKind") for source in sources}
    kinds.add(provenance.get("evidenceKind"))
    public, controlled = "public_literature_excerpt", "controlled_literature_fixture"
    if public in kinds and controlled in kinds:
        provenance_label = "混合来源：包含受控合成夹具；不得作为完整真实公开检索验收。"
    elif controlled in kinds:
        provenance_label = "受控合成夹具：来源内容为测试证据，不代表真实公开检索成功。"
    elif kinds == {public}:
        provenance_label = "公开检索来源记录；不代表科研结论或全文均已验证。"
    else:
        provenance_label = "来源类型未完整核对；不得据此认定真实公开检索成功。"
    full_count = sum(source.get("fullTextAvailable") is True
                     and source.get("textStatus") == "extracted_text" for source in sources)
    excerpt_count = sum(bool(source.get("excerpt")) for source in sources)
    errors = provenance.get("retrievalErrors") or []
    report = ["# 文献来源证据", "", "模式：书目 / 有界摘录。未调用模型，不提供模型综合或科研结论。",
              "证据来源：" + provenance_label, "",
              f"来源记录数：{len(sources)}；已取得提取正文：{full_count}；含有界摘录：{excerpt_count}。",
              f"检索失败记录数：{len(errors)}。记录数及任务完成状态不等于文献研究成功。", "",
              "哈希覆盖 CLI 文本呈现或元数据摘要，并非原始论文/PDF。定位符指向该呈现。", ""]
    for source in sources:
        report += ["## " + plain(source.get("title") or source["sourceId"]),
                   "", "来源 ID：" + plain(source["sourceId"]), "", "来源地址（文本）：" + plain(source["url"]),
                   "", "来源类型：" + plain(source.get("evidenceKind", "未提供")),
                   "", "正文状态：" + plain(source["textStatus"]),
                   "", "未取得全文原因：" + plain(source.get("missingFullTextReason") or "无已记录原因"),
                   "", "最近正文尝试状态：" + plain(source.get("lastTextAttemptStatus", "未提供")),
                   "", "错误记录：" + error_text(source.get("lastRetrievalError") or source.get("errorCode") or "无已记录错误"),
                   "", "SHA-256：" + plain(source["sha256"]),
                   "", "哈希范围：" + plain(source.get("hashScope", "未提供")),
                   "", "定位：" + plain(json.dumps(source["locator"], ensure_ascii=False)), "",
                   "摘录：" + plain(source["excerpt"] or "（未取得可验证摘录）"), ""]
    if not sources:
        report += ["未取得来源记录；不得将空结果当作完成文献研究。", ""]
    if errors:
        report += ["检索失败记录：" + ", ".join(error_text(error) for error in errors), ""]
    raw = ("\n".join(report) + "\n").encode()
    evidence = json.dumps({"schema": 1, "mode": "bibliography-excerpts-no-provider", "sources": sources,
                           "provenance": provenance}, ensure_ascii=False, sort_keys=True, indent=2).encode()
    manifest = json.dumps({"schema": 1, "files": {"report.md": hashlib.sha256(raw).hexdigest(),
                         "sources.json": hashlib.sha256(evidence).hexdigest()}}, sort_keys=True).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in (("report.md", raw), ("sources.json", evidence), ("manifest.json", manifest)):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return raw, buffer.getvalue()


def register_literature_adapters(bindings):
    registrations = []
    for name, adapter_id in TOOLS.items():
        def factory(context, selected=name):
            config = {key: value for key, value in context.spec.get("config", {}).items() if key != "connectionName"}
            validate_config(config)
            fixed = context.spec["connection"]
            handle = context.connection
            if not callable(getattr(handle, "create_retrieval_adapter", None)):
                raise OpenResearchError("CONNECTION_NOT_CONFIGURED", "A bounded public retrieval provider is required")
            owner, task_id = context.run_context.user_id, context.run_context.session_id
            adapter = None

            def authorize(ctx):
                if (ctx.user_id != owner or ctx.session_id != task_id or ctx.run_id != context.run_context.run_id):
                    raise PermissionError("Literature callable belongs to another task")
                plan = context.store.resolve_run(ctx)
                if plan["id"] != context.plan["id"] or plan.get("fingerprint") != context.plan.get("fingerprint"):
                    raise PermissionError("Immutable literature plan changed")
                context.store.authorize_tool(ctx, selected)
                if context.store.cancellation_requested(ctx.run_id):
                    raise RunCancelledException("Literature retrieval cancelled")
                current = context.store.connections.resolve(owner, fixed["ref"], "orx",
                    expected_version=fixed["version"], expected_revision=fixed["revision"],
                    expected_fingerprint=fixed["fingerprint"], expected_adapter_ref=ORX_ADAPTER_ID,
                    required_capabilities=(CAPABILITY,), task_id=task_id)
                if current is not handle:
                    raise PermissionError("Current retrieval provider changed")
                return plan

            async def execute(ctx, identifier: str = ""):
                retrieval_error = None
                retrieval_diagnostics = []
                nonlocal adapter
                plan = authorize(ctx)
                environment = bindings.environment_limits(plan, ctx)
                output, timeout, bounds = _limits(context.settings, plan, environment)
                sources = _sources(context.store, ctx)
                if selected in {"orx_paper", "orx_text"}:
                    source_url(identifier)
                    if identifier not in {source["sourceId"] for source in sources}:
                        raise PermissionError("Paper must be in this task's verified discovery evidence")
                fingerprint = digest({"plan": plan["fingerprint"], "tool": selected, "config": config,
                    "sourceId": identifier, "connection": fixed,
                    "sources": sources if selected == "orx_sources_report" else None})
                key = "orx-literature:" + fingerprint[:40]
                reservation = context.store.effect_reserve(ctx.run_id, key, {"fingerprint": fingerprint})
                if reservation["status"] == "done":
                    return json.dumps(reservation["result"], ensure_ascii=False)
                if reservation["status"] == "unknown":
                    raise OpenResearchError("UNKNOWN_EFFECT", "Unacknowledged retrieval must be reconciled; automatic retry refused")
                provenance = {"evidenceKind": "public_literature_excerpt", "contractRevision": REVISION,
                    "mode": "bibliography-excerpts-no-provider", "ownerId": owner, "taskId": task_id,
                    "planId": plan["id"], "planFingerprint": plan["fingerprint"], "connection": fixed,
                    "sourceRevision": approved_pin().revision, "binarySha256": approved_pin().sha256,
                    "effectFingerprint": fingerprint, "tool": selected}
                if selected == "orx_sources_report":
                    failures = []
                    controlled = any(source.get("evidenceKind") == "controlled_literature_fixture" for source in sources)
                    for item in context.store.artifacts(task_id):
                        if item.get("name", "").startswith("literature-sources-"):
                            _, raw = context.store.artifact(task_id, item["id"])
                            error = json.loads(raw).get("retrievalError")
                            if error: failures.append(error)
                            controlled |= item.get("provenance", {}).get("evidenceKind") == "controlled_literature_fixture"
                    provenance["retrievalErrors"] = failures
                    if controlled:
                        provenance["evidenceKind"] = "controlled_literature_fixture"
                    report, bundle = report_bundle(sources, provenance)
                    if max(len(report), len(bundle)) > output:
                        raise OpenResearchError("OUTPUT_LIMIT", "Evidence bundle exceeds the selected output limit")
                    authorize(ctx)
                    artifacts = [context.store.artifact_write(task_id, "literature-report-" + fingerprint[:16] + ".md", report,
                                  "text/markdown; charset=utf-8", provenance),
                                 context.store.artifact_write(task_id, "literature-evidence-" + fingerprint[:16] + ".zip", bundle,
                                  "application/zip", provenance)]
                    result = {"mode": provenance["mode"], "sources": sources,
                              "artifacts": [{k: a[k] for k in ("id", "name", "sha256")} for a in artifacts]}
                else:
                    if adapter is None:
                        # The existing storage inventory owns the immutable
                        # scope; evidence and container receipts cannot enter
                        # the reclaimable-scratch retention flow.
                        scope = context.store.storage.directory(task_id, "orx-literature-v2", evidence=True)
                        adapter = handle.create_retrieval_adapter(owner_id=owner, task_id=task_id, scope=scope,
                            authorize=lambda _: authorize(ctx), pin=approved_pin(), max_output_bytes=output,
                            command_timeout=min(timeout, 15), environment=bounds)
                    if (not isinstance(adapter, LinuxRetrievalAdapter) or adapter.owner_id != owner
                            or adapter.task_id != task_id or adapter.pin != approved_pin()
                            or adapter.environment != bounds or adapter.max_output_bytes > output
                            or not 0 < adapter.command_timeout <= min(timeout, 15) or not adapter.enabled):
                        raise OpenResearchError("CONTAINMENT_INVALID", "Selected retrieval resource boundary differs")
                    current_adapter = adapter
                    async def retrieve():
                        nonlocal retrieval_error
                        if selected == "orx_discover":
                            try:
                                hits = await current_adapter.discover(PUBLIC_QUERIES[config["queryId"]], corpus=config.get("corpus", "pubmed"), limit=config.get("limit", 2))
                            except OpenResearchError as error:
                                if error.code not in {"COMMAND_FAILED", "TIMEOUT", "OUTPUT_LIMIT"}:
                                    raise
                                retrieval_error = error.code
                                retrieval_diagnostics.append(safe_retrieval_diagnostic(error, "discover"))
                                return []
                            return [evidence_record(str(hit["id"]), str(hit.get("abstract") or ""),
                                status="abstract_only" if hit.get("abstract") else "metadata_only",
                                field="abstract", title=str(hit.get("title") or "")) for hit in hits]
                        # alphaXiv overview is a generated report, not primary-source
                        # text. For arXiv, both tools request extracted text only.
                        full = bool(ARXIV.fullmatch(identifier))
                        # The pinned adapter cannot explicitly request full
                        # text for legacy arXiv IDs. Its default paper route
                        # would return a generated overview: never use that as
                        # a primary-source abstract/excerpt.
                        if LEGACY_ARXIV.fullmatch(identifier) or (selected == "orx_text" and not full):
                            return [evidence_record(identifier, "", status="full_text_unsupported", field="stdout")]
                        try:
                            command = await current_adapter.paper(identifier, full=full)
                            return [evidence_record(identifier, command.stdout,
                                status=("extracted_text" if full else "abstract_only") if command.stdout.strip() else "empty_response", field="stdout")]
                        except OpenResearchError as error:
                            if error.code not in {"COMMAND_FAILED", "TIMEOUT", "OUTPUT_LIMIT"}:
                                raise
                            retrieval_diagnostics.append(safe_retrieval_diagnostic(error, "text" if selected == "orx_text" else "paper"))
                            return [evidence_record(identifier, "", status="retrieval_failed", field="stdout", error_code=error.code)]
                    operation = asyncio.create_task(retrieve())
                    try:
                        async with asyncio.timeout(timeout):
                            while not operation.done():
                                await asyncio.wait({operation}, timeout=.25)
                                authorize(ctx)
                            retrieved = await operation
                    finally:
                        if not operation.done():
                            operation.cancel()
                        await asyncio.gather(operation, return_exceptions=True)
                    containment = adapter.containment_evidence()
                    if not containment["allStopped"]:
                        raise OpenResearchError("CLEANUP_UNCONFIRMED", "Retrieval process stop is unconfirmed")
                    provenance["containment"] = containment
                    provenance["retrievalDiagnostics"] = retrieval_diagnostics
                    if type(adapter) is not LinuxRetrievalAdapter:
                        provenance["evidenceKind"] = "controlled_literature_fixture"
                    for source in retrieved:
                        source["evidenceKind"] = provenance["evidenceKind"]
                    authorize(ctx)
                    result = {"mode": provenance["mode"], "sources": retrieved, "retrievalError": retrieval_error,
                              "retrievalDiagnostics": retrieval_diagnostics}
                    artifact = context.store.artifact_write(task_id, "literature-sources-" + fingerprint[:16] + ".json",
                        json.dumps(result, ensure_ascii=False, sort_keys=True), metadata=provenance)
                    result["artifactId"] = artifact["id"]
                authorize(ctx)
                context.store.effect_complete(ctx.run_id, key, result)
                return json.dumps(result, ensure_ascii=False, sort_keys=True)

            async def orx_discover(run_context: RunContext) -> str:
                """Retrieve the immutable reviewed public query (one to three sources)."""
                return await execute(run_context)

            async def orx_paper(paper_id: str, run_context: RunContext) -> str:
                """Read a discovered paper's metadata/excerpt; report missing full text."""
                return await execute(run_context, paper_id)

            async def orx_text(paper_id: str, run_context: RunContext) -> str:
                """Read discovered arXiv extracted text, never an AI-generated overview."""
                return await execute(run_context, paper_id)

            async def orx_sources_report(run_context: RunContext) -> str:
                """Save a bibliography/excerpt report and hashed downloadable evidence ZIP."""
                return await execute(run_context)

            return {"orx_discover": orx_discover, "orx_paper": orx_paper,
                    "orx_text": orx_text, "orx_sources_report": orx_sources_report}[selected]
        registrations.append(bindings.register("tool", adapter_id, REVISION, factory,
            tool_name=name, connection_kind="orx", connection_adapter_ref=ORX_ADAPTER_ID,
            required_capabilities=(CAPABILITY,), permissions=(CAPABILITY,), validator=validate_config))
    return registrations


from dataclasses import dataclass
from agno.models.response import ModelResponse
from .orx_experiment_tools import LocalORXWorkflowModel

MODEL_ID = "local-literature-evidence-model-v1"


@dataclass
class LiteratureEvidenceModel(LocalORXWorkflowModel):
    id: str = "factory-literature-evidence-v1"
    name: str = "Bibliography and excerpts, no provider"
    provider: str = "local-deterministic"

    def _response(self, messages):
        latest = {}
        paper_ids = set()
        text_ids = set()
        errors = []
        for message in messages:
            if message.role != "tool":
                continue
            if message.tool_call_error:
                errors.append("Approved literature tool failed; inspect task evidence")
                continue
            try:
                value = json.loads(message.content)
            except (TypeError, ValueError):
                errors.append("Invalid literature tool response")
                continue
            latest[message.tool_name] = value
            ids = {row["sourceId"] for row in value.get("sources", [])}
            if message.tool_name == "orx_paper":
                paper_ids.update(ids)
                text_ids.update(row["sourceId"] for row in value.get("sources", []) if row.get("fullTextAvailable"))
            if message.tool_name == "orx_text": text_ids.update(ids)
        def call(name, arguments):
            return ModelResponse(role="assistant", tool_calls=[{"id": "literature-" + str(len(messages)),
                "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}])
        if errors:
            return ModelResponse(role="assistant", content=json.dumps({"status": "blocked", "errors": errors,
                "mode": "bibliography-excerpts-no-provider", "notice": "No model synthesis or provider call."}))
        if "orx_discover" not in latest: return call("orx_discover", {})
        for source in latest["orx_discover"].get("sources", []):
            identifier = source["sourceId"]
            if identifier not in paper_ids: return call("orx_paper", {"paper_id": identifier})
            if identifier not in text_ids: return call("orx_text", {"paper_id": identifier})
        if "orx_sources_report" not in latest: return call("orx_sources_report", {})
        result = latest["orx_sources_report"]
        return ModelResponse(role="assistant", content=json.dumps({"status": "evidence-ready" if result["sources"] else "blocked-no-sources",
            **result, "notice": "书目与摘录证据；未调用模型，未生成科研综合结论。"}, ensure_ascii=False))

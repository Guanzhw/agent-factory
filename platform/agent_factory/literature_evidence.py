"""Bounded read-only projection of owner-scoped persisted literature artifacts."""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
import zlib
from typing import Any, cast

from fastapi import HTTPException

from .orx_literature_tools import REVISION, source_url

APPLICATION_ID = "public-literature-evidence-v2"
MODE = "bibliography-excerpts-no-provider"
KINDS = {"public_literature_excerpt", "controlled_literature_fixture"}
STATUSES = {"extracted_text", "abstract_only", "metadata_only", "full_text_unsupported", "retrieval_failed", "empty_response"}
ERRORS = {"COMMAND_FAILED", "TIMEOUT", "OUTPUT_LIMIT"}
MAX_BYTES = 2 * 1024 * 1024


def require(value):
    if not value:
        raise ValueError("Invalid persisted literature evidence")


def integer(value, maximum=MAX_BYTES):
    return type(value) is int and 0 <= value <= maximum


def source_projection(row):
    require(type(row) is dict)
    identifier = row.get("sourceId")
    require(isinstance(identifier, str) and 1 <= len(identifier) <= 320)
    require(row.get("url") == source_url(identifier))
    title, excerpt = row.get("title"), row.get("excerpt")
    require(isinstance(title, str) and len(title) <= 240)
    require(isinstance(excerpt, str) and len(excerpt) <= 160)
    status = row.get("textStatus")
    require(isinstance(status, str) and status in STATUSES)
    require(type(row.get("fullTextAvailable")) is bool and row["fullTextAvailable"] == (status == "extracted_text"))
    missing = row.get("missingFullTextReason")
    require(missing is None if row["fullTextAvailable"] else isinstance(missing, str) and missing in STATUSES - {"extracted_text"})
    digest = row.get("sha256")
    require(digest is None or isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest))
    require(not excerpt or digest is not None)
    locator = cast(dict[str, Any], row.get("locator"))
    require(type(locator) is dict and locator.get("kind") == "unicode_character_range")
    require(locator.get("field") in ("abstract", "stdout"))
    require(all(integer(locator.get(key)) for key in ("start", "endExclusive", "line")))
    require(locator["line"] >= 1 and locator["endExclusive"] - locator["start"] == len(excerpt))
    require(row.get("hashScope") == ("decoded_cli_rendition" if locator["field"] == "stdout" else "metadata_abstract"))
    require(row.get("evidenceKind") in ("public_literature_excerpt", "controlled_literature_fixture"))
    return {key: row[key] for key in ("sourceId", "url", "title", "textStatus", "fullTextAvailable", "sha256",
        "excerpt", "locator", "hashScope", "missingFullTextReason")}


def inspect_literature_evidence(store, owner_id, task_id):
    # Owner lookup precedes artifact enumeration/read, including invalid evidence.
    task = store.task(task_id, owner_id)
    plan = store.plan(task["plan_id"], owner_id)
    if plan.get("application") != APPLICATION_ID:
        return None
    result = {"schema": 1, "status": "pending", "evidenceKind": "unknown", "mode": MODE,
              "sourceCount": 0, "sources": [], "retrievalErrors": [], "reportArtifactId": None, "bundleArtifactId": None}
    try:
        artifacts = store.artifacts(task_id)
        bundles = [row for row in artifacts if row.get("name", "").startswith("literature-evidence-") and row["name"].endswith(".zip")]
        if not bundles:
            return result
        require(len(bundles) == 1)
        bundle = bundles[0]
        expected = {"ownerId": owner_id, "taskId": task_id, "planId": plan["id"],
                    "planFingerprint": plan["fingerprint"], "contractRevision": REVISION,
                    "mode": MODE, "tool": "orx_sources_report"}
        provenance = bundle.get("provenance")
        require(type(provenance) is dict and all(provenance.get(key) == value for key, value in expected.items()))
        require(provenance.get("evidenceKind") in ("public_literature_excerpt", "controlled_literature_fixture"))
        require(integer(bundle.get("size")) and bundle["size"] > 0)
        _, raw = store.artifact(task_id, bundle["id"])
        require(len(raw) == bundle["size"] and hashlib.sha256(raw).hexdigest() == bundle["sha256"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            require(len(infos) == 3 and {info.filename for info in infos} == {"sources.json", "report.md", "manifest.json"})
            require(all(0 <= info.file_size <= MAX_BYTES and not info.flag_bits & 1 for info in infos))
            files = {info.filename: archive.read(info) for info in infos}
        manifest = json.loads(files["manifest.json"])
        require(type(manifest) is dict and manifest.get("schema") == 1 and manifest.get("files") == {
            key: hashlib.sha256(files[key]).hexdigest() for key in ("sources.json", "report.md")})
        manifest = cast(dict[str, Any], manifest)
        document = json.loads(files["sources.json"])
        require(type(document) is dict and document.get("schema") == 1 and document.get("mode") == MODE)
        document = cast(dict[str, Any], document)
        embedded = cast(dict[str, Any], document.get("provenance"))
        require(type(embedded) is dict and all(embedded.get(key) == value for key, value in expected.items()))
        require(embedded.get("evidenceKind") == provenance["evidenceKind"])
        errors = embedded.get("retrievalErrors", [])
        require(type(errors) is list and len(errors) <= 30 and all(isinstance(v, str) and v in ERRORS for v in errors))
        require(errors == provenance.get("retrievalErrors", []))
        sources = cast(list[dict[str, Any]], document.get("sources"))
        require(type(sources) is list and len(sources) <= 3)
        rows = [source_projection(row) for row in sources]
        require(len({row["sourceId"] for row in rows}) == len(rows))
        kind = provenance["evidenceKind"]
        if any(row["evidenceKind"] == "controlled_literature_fixture" for row in sources):
            kind = "controlled_literature_fixture"
        reports = [row for row in artifacts if row.get("name", "").startswith("literature-report-") and row["name"].endswith(".md")]
        require(len(reports) == 1)
        report = reports[0]
        require(integer(report.get("size")) and report["size"] == len(files["report.md"]))
        require(report.get("sha256") == manifest["files"]["report.md"])
        _, report_raw = store.artifact(task_id, report["id"])
        require(report_raw == files["report.md"] and hashlib.sha256(report_raw).hexdigest() == report["sha256"])
        require(all(report.get("provenance", {}).get(key) == value for key, value in expected.items()))
        require(report["provenance"].get("evidenceKind") == provenance["evidenceKind"])
        return {**result, "status": "ready" if rows else "no-sources", "evidenceKind": kind,
                "sourceCount": len(rows), "sources": rows, "retrievalErrors": sorted(set(errors)),
                "reportArtifactId": report["id"], "bundleArtifactId": bundle["id"]}
    except (ValueError, TypeError, KeyError, AttributeError, OSError, HTTPException, zipfile.BadZipFile, RuntimeError, zlib.error, EOFError):
        # Never leak persisted/private content or claim successful evidence on corruption.
        return {**result, "status": "invalid"}

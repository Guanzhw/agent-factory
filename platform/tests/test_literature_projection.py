"""Persisted owner-scoped projection, with no provider or retrieval effects."""
import copy
import hashlib
import unittest
from fastapi import HTTPException
from agent_factory.literature_evidence import inspect_literature_evidence
from agent_factory.orx_literature_tools import evidence_record, report_bundle


class EvidenceStore:
    def __init__(self, sources=None, *, kind="controlled_literature_fixture", errors=None):
        self.plan_body = {"application": "public-literature-evidence-v2", "id": "plan", "fingerprint": "f" * 64}
        self.provenance = {"ownerId": "alice", "taskId": "task", "planId": "plan", "planFingerprint": "f" * 64,
            "contractRevision": "2", "mode": "bibliography-excerpts-no-provider", "tool": "orx_sources_report",
            "evidenceKind": kind, "retrievalErrors": errors or []}
        self.sources = sources if sources is not None else [{**evidence_record("123", "Synthetic excerpt", status="abstract_only", field="abstract"), "evidenceKind": kind}]
        self.reads = 0
        self.rebuild()

    def rebuild(self):
        report, bundle = report_bundle(self.sources, self.provenance)
        self.content = {"report": report, "bundle": bundle}
        self.rows = [{"id": key, "name": name, "size": len(self.content[key]),
            "sha256": hashlib.sha256(self.content[key]).hexdigest(), "provenance": copy.deepcopy(self.provenance)}
            for key, name in (("report", "literature-report-fixed.md"), ("bundle", "literature-evidence-fixed.zip"))]

    def task(self, task, owner):
        if (task, owner) != ("task", "alice"): raise HTTPException(404)
        return {"plan_id": "plan"}

    def plan(self, plan, owner):
        assert (plan, owner) == ("plan", "alice")
        return self.plan_body

    def artifacts(self, task):
        self.reads += 1
        assert task == "task"
        return self.rows

    def artifact(self, task, artifact):
        assert task == "task"
        return next(row for row in self.rows if row["id"] == artifact), self.content[artifact]


class LiteratureProjectionTests(unittest.TestCase):
    def test_owned_controlled_and_public_provenance_preserved(self):
        for kind in ("controlled_literature_fixture", "public_literature_excerpt"):
            with self.subTest(kind=kind):
                result = inspect_literature_evidence(EvidenceStore(kind=kind), "alice", "task")
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["evidenceKind"], kind)
                self.assertEqual(result["sourceCount"], 1)
                self.assertEqual(result["sources"][0]["hashScope"], "metadata_abstract")
                self.assertFalse(result["sources"][0]["fullTextAvailable"])
                self.assertNotIn("ownerId", result)

    def test_owner_denied_before_artifact_read_and_unrelated_application_omitted(self):
        store = EvidenceStore()
        with self.assertRaises(HTTPException): inspect_literature_evidence(store, "bob", "task")
        self.assertEqual(store.reads, 0)
        store.plan_body["application"] = "auto-research"
        self.assertIsNone(inspect_literature_evidence(store, "alice", "task"))
        self.assertEqual(store.reads, 0)

    def test_zero_sources_failure_is_not_ready_and_pending_distinct(self):
        store = EvidenceStore([], errors=["COMMAND_FAILED"])
        result = inspect_literature_evidence(store, "alice", "task")
        self.assertEqual(result["status"], "no-sources")
        self.assertEqual(result["retrievalErrors"], ["COMMAND_FAILED"])
        store.rows = []
        self.assertEqual(inspect_literature_evidence(store, "alice", "task")["status"], "pending")

    def test_tampered_bytes_owner_plan_hash_locator_and_duplicate_sources_invalid(self):
        mutations = [lambda s: s.content.update(bundle=s.content["bundle"] + b"tamper"),
            lambda s: s.rows[1]["provenance"].update(ownerId="bob"),
            lambda s: s.plan_body.update(fingerprint="changed"),
            lambda s: s.sources[0]["locator"].update(endExclusive=99),
            lambda s: s.sources.append(copy.deepcopy(s.sources[0])),
            lambda s: s.sources[0].update(url="javascript:alert(1)"),
            lambda s: s.sources[0].update(fullTextAvailable=True),
            lambda s: s.provenance.update(retrievalErrors=["private-error-message"])]
        for index, mutate in enumerate(mutations):
            store = EvidenceStore(); mutate(store)
            if index >= 3: store.rebuild()
            result = inspect_literature_evidence(store, "alice", "task")
            self.assertEqual(result["status"], "invalid", index)
            self.assertEqual(result["sources"], [])
            self.assertNotIn("private-error-message", str(result))

    def test_mixed_source_provenance_conservatively_controlled(self):
        store = EvidenceStore(kind="public_literature_excerpt")
        store.sources[0]["evidenceKind"] = "controlled_literature_fixture"
        store.rebuild()
        result = inspect_literature_evidence(store, "alice", "task")
        self.assertEqual(result["evidenceKind"], "controlled_literature_fixture")
        self.assertEqual(result["status"], "ready")

    def test_standalone_report_bytes_missing_or_corrupt_are_not_verified_by_metadata(self):
        for content in (b'corrupt report', b''):
            store = EvidenceStore()
            store.content['report'] = content
            result = inspect_literature_evidence(store, 'alice', 'task')
            self.assertEqual(result['status'], 'invalid')
            self.assertIsNone(result['reportArtifactId'])
        store = EvidenceStore()
        store.rows = [row for row in store.rows if row['id'] != 'report']
        self.assertEqual(inspect_literature_evidence(store, 'alice', 'task')['status'], 'invalid')

    def test_corrupt_deflate_inside_rehashed_zip_fails_closed(self):
        import io
        import struct
        import zipfile
        store = EvidenceStore()
        raw = bytearray(store.content['bundle'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entry = archive.infolist()[0]
        offset = entry.header_offset
        name_size, extra_size = struct.unpack_from('<HH', raw, offset + 26)
        payload_start = offset + 30 + name_size + extra_size
        # Reserved DEFLATE block type: outer ZIP metadata and artifact hash
        # remain consistent, but the decoder raises zlib.error before CRC.
        raw[payload_start] = (raw[payload_start] & 0xf8) | 0x07
        store.content['bundle'] = bytes(raw)
        store.rows[1]['sha256'] = hashlib.sha256(raw).hexdigest()
        self.assertEqual(inspect_literature_evidence(store, 'alice', 'task')['status'], 'invalid')

    def test_oversized_zip_member_is_rejected_before_decompression(self):
        import io
        import zipfile
        from unittest.mock import patch
        from agent_factory.literature_evidence import MAX_BYTES
        store = EvidenceStore()
        with zipfile.ZipFile(io.BytesIO(store.content['bundle'])) as archive:
            infos = archive.infolist()
        infos[0].file_size = MAX_BYTES + 1
        with patch('agent_factory.literature_evidence.zipfile.ZipFile.infolist', return_value=infos), \
                patch('agent_factory.literature_evidence.zipfile.ZipFile.read', side_effect=AssertionError('must not decompress')) as read:
            self.assertEqual(inspect_literature_evidence(store, 'alice', 'task')['status'], 'invalid')
            read.assert_not_called()

"""Evidence integrity and immutable least-capability contract regressions."""
import hashlib
import io
import json
from types import SimpleNamespace
import unittest
import zipfile

from agent_factory.openresearch import OpenResearchError
from agent_factory.orx_pins import approved_pin, LINUX_SHA256, WINDOWS_SHA256
from agent_factory.orx_literature_tools import evidence_record, report_bundle, source_url, validate_config, LiteratureEvidenceModel
from agent_factory.orx_experiment_tools import register_orx_experiment_adapters, TOOL_NAMES
from agent_factory.plan_policy import PlanPolicyConfig


class LiteratureEvidenceTests(unittest.TestCase):
    def test_platform_pins_fail_closed(self):
        self.assertEqual(approved_pin('linux').sha256, LINUX_SHA256)
        self.assertEqual(approved_pin('win32').sha256, WINDOWS_SHA256)
        for platform in ('darwin', 'freebsd', 'linux-other'):
            with self.assertRaises(OpenResearchError): approved_pin(platform)

    def test_source_id_rejects_url_paths_and_traversal(self):
        for value in ('https://example.org', '/etc/passwd', '10.1000/../secret', '-file', 'Wfoo'):
            with self.assertRaises(ValueError): source_url(value)
        self.assertEqual(source_url('pmid:123'), 'https://pubmed.ncbi.nlm.nih.gov/123/')
        self.assertEqual(source_url('2401.12345'), 'https://arxiv.org/abs/2401.12345')

    def test_excerpt_locator_hash_and_bundle_integrity(self):
        text = '\n  ' + ' '.join('original%d' % n for n in range(80))
        record = evidence_record('123', text, status='abstract_only', field='stdout')
        locator = record['locator']
        self.assertEqual(text[locator['start']:locator['endExclusive']], record['excerpt'])
        self.assertEqual(record['sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertLessEqual(len(record['excerpt']), 160)
        self.assertFalse(record['fullTextAvailable'])
        report, bundle = report_bundle([record], {'fixture': True})
        self.assertIn('未调用模型'.encode(), report)
        self.assertEqual(bundle, report_bundle([record], {'fixture': True})[1])
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(set(archive.namelist()), {'report.md', 'sources.json', 'manifest.json'})
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
        self.assertNotIn(text.encode(), bundle)

    def test_standalone_report_distinguishes_public_controlled_mixed_and_unverified(self):
        record = evidence_record('123', 'A short source abstract', status='abstract_only', field='abstract')
        public = {**record, 'evidenceKind': 'public_literature_excerpt'}
        controlled = {**record, 'sourceId': '456', 'evidenceKind': 'controlled_literature_fixture'}
        cases = [([public], {'evidenceKind': 'public_literature_excerpt'}, '公开检索来源记录'),
                 ([controlled], {'evidenceKind': 'controlled_literature_fixture'}, '受控合成夹具'),
                 ([public, controlled], {'evidenceKind': 'controlled_literature_fixture'}, '混合来源'),
                 ([record], {}, '来源类型未完整核对')]
        for sources, provenance, label in cases:
            with self.subTest(label=label):
                report, bundle = report_bundle(sources, provenance)
                text = report.decode()
                self.assertIn(label, text)
                self.assertIn(f'来源记录数：{len(sources)}', text)
                self.assertIn('未调用模型，不提供模型综合或科研结论', text)
                self.assertIn('并非原始论文/PDF', text)
                with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                    self.assertEqual(archive.read('report.md'), report)
                    document = json.loads(archive.read('sources.json'))
                    self.assertEqual(document['sources'], sources)
                    self.assertEqual(document['provenance'], provenance)
                    for name, expected in json.loads(archive.read('manifest.json'))['files'].items():
                        self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)

    def test_report_retains_zero_source_failure_and_partial_text_availability(self):
        report, _ = report_bundle([], {'evidenceKind': 'public_literature_excerpt', 'retrievalErrors': ['COMMAND_FAILED']})
        self.assertIn('来源记录数：0', report.decode())
        self.assertIn('检索失败记录数：1', report.decode())
        self.assertIn(b'`COMMAND_FAILED`', report)
        self.assertIn('不得将空结果当作完成文献研究', report.decode())
        record = evidence_record('123', 'located text', status='extracted_text', field='stdout')
        record.update(evidenceKind='public_literature_excerpt', lastTextAttemptStatus='fetch_failed', lastRetrievalError='NETWORK_ERROR')
        report, _ = report_bundle([record], {'evidenceKind': 'public_literature_excerpt'})
        self.assertIn('已取得提取正文：1', report.decode())
        self.assertIn('最近正文尝试状态：fetch', report.decode())
        self.assertIn('错误记录：NETWORK', report.decode())
        self.assertIn('哈希范围：decoded', report.decode())

    def test_markdown_source_strings_are_text_while_json_preserves_original_facts(self):
        hostile = '[click](javascript:alert(1)) <img src=x onerror=alert(1)>\n# forged'
        record = evidence_record('123', hostile, status='abstract_only', field='abstract', title=hostile)
        record['url'] = 'javascript:alert(1)'
        before = json.dumps(record, sort_keys=True)
        report, bundle = report_bundle([record], {'retrievalErrors': [hostile]})
        text = report.decode()
        self.assertNotIn('[click](', text)
        self.assertNotIn('<img', text)
        self.assertNotIn('javascript:', text)
        self.assertNotIn('\n# forged', text)
        self.assertIn('&lt;img', text)
        self.assertEqual(json.dumps(record, sort_keys=True), before)
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            self.assertEqual(json.loads(archive.read('sources.json'))['sources'], [record])

    def test_reviewed_query_has_no_paths_endpoints_or_unbounded_limit(self):
        validate_config({'queryId': 'public-rag-v1', 'limit': 1})
        for value in ({'query': 'x', 'url': 'https://example.org'}, {'query': 'x', 'limit': 4}, {'query': '-x'}):
            with self.assertRaises(ValueError): validate_config(value)

    def test_old_and_new_registration_caps_are_distinct(self):
        registrations = {}
        def register(kind, adapter, revision, factory, **kwargs):
            registrations[adapter, revision] = kwargs
        register_orx_experiment_adapters(SimpleNamespace(register=register))
        self.assertEqual(len(registrations), 10)
        for tool in TOOL_NAMES:
            adapter = 'openresearch-experiment-v1-' + tool.rsplit('_', 1)[1]
            self.assertEqual(set(registrations[adapter, '1']['required_capabilities']), {'research:read', 'compute:local'})
            current = registrations[adapter, '2']
            self.assertEqual(current['required_capabilities'], current['permissions'])
            self.assertEqual(len(current['required_capabilities']), 1)
        old = PlanPolicyConfig(tool_contract='local-orx-v1', revision='old-v1')
        new = PlanPolicyConfig(tool_contract='orx-evidence-v2', revision='new-v2')
        self.assertNotIn('orx_text', old.known_tools)
        self.assertIn('orx_text', new.read_only_tools)

    def test_model_does_not_invent_sources_or_synthesis_on_empty_retrieval(self):
        model = LiteratureEvidenceModel()
        messages = [SimpleNamespace(role='tool', tool_name='orx_discover', content='{"sources": []}', tool_call_error=False)]
        self.assertEqual(model.invoke(messages).tool_calls[0]['function']['name'], 'orx_sources_report')
        messages.append(SimpleNamespace(role='tool', tool_name='orx_sources_report', content='{"sources": [], "artifacts": []}', tool_call_error=False))
        final = model.invoke(messages)
        self.assertFalse(final.tool_calls)
        self.assertEqual(json.loads(final.content)['status'], 'blocked-no-sources')


class RetrievalStartupCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_during_container_start_retains_late_process_ownership(self):
        import asyncio
        import os
        from pathlib import Path
        import sys
        import tempfile
        import threading
        from unittest.mock import patch
        from agent_factory.orx_retrieval import LinuxRetrievalAdapter
        if os.name == 'nt': self.skipTest('POSIX retrieval process group cleanup')
        started, release = threading.Event(), threading.Event()
        stopped = []
        def argv(*_):
            started.set()
            if not release.wait(3): raise AssertionError('Test startup barrier expired')
            return [sys.executable, '-c', 'import time; time.sleep(30)']
        with tempfile.TemporaryDirectory() as directory:
            adapter = object.__new__(LinuxRetrievalAdapter)
            adapter.scope = Path(directory)
            adapter.env = {'HOME': directory}
            adapter.container = SimpleNamespace(exec_argv=argv, process_ids=lambda: [], terminate=lambda: stopped.append(True))
            actual_spawn = asyncio.create_subprocess_exec
            children = []
            async def tracked(*args, **kwargs):
                process = await actual_spawn(*args, **kwargs)
                children.append(process)
                return process
            with patch('agent_factory.orx_retrieval.asyncio.create_subprocess_exec', side_effect=tracked):
                operation = asyncio.create_task(adapter._spawn(('--version',)))
                await asyncio.to_thread(started.wait, 3)
                operation.cancel()
                release.set()
                with self.assertRaises(asyncio.CancelledError): await operation
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].returncode)
            self.assertEqual(stopped, [True])

"""Portable delivery authority and selection; native CLI checked separately."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import select

from research.delivery import ResearchDelivery
from research.evidence import EvidenceSelection
from research.projects import ProjectCommand
from research.workflow import Decision
import test_research_rounds as fixtures


class ResearchDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ResearchRoundsTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.start()
        self.rounds = self.fixture.service
        self.delivery = ResearchDelivery(self.rounds)
        self.command = ProjectCommand(requestId='create-delivery', expectedVersion=1)

    def test_empty_sources_owner_only_and_duplicate_manifest_has_no_generic_copy(self):
        first = self.delivery.create('alice', self.fixture.project, self.command)
        self.assertIn('published_records', first['missingEvidence'])
        self.assertEqual(self.delivery.create('alice', self.fixture.project, self.command), first)
        self.assertEqual(self.delivery.list('bob')['items'], [])
        with self.assertRaises(HTTPException): self.delivery.read('bob', first['id'])
        self.assertEqual(self.fixture.content.list('alice')['items'], [])

    def test_every_source_rechecked_and_safe_directory_does_not_leak_summary(self):
        self.fixture.finish()
        manifest = self.delivery.create('alice', self.fixture.project, self.command)
        self.assertEqual(self.delivery.read('bob', manifest['id']), manifest)
        self.assertEqual(set(self.delivery.list('bob')['items'][0]), {'id', 'ownerId', 'createdAt'})
        sources = self.fixture.content.list('bob')['items']
        self.assertNotIn('research.delivery', json.dumps(sources))
        self.fixture.content.set_visibility('alice', manifest['sourceIds'][0], 'personal', 'withdraw-original')
        self.assertEqual(self.delivery.list('bob')['items'], [])
        for action in (self.delivery.read, self.delivery.download):
            with self.assertRaises(HTTPException): action('bob', manifest['id'])
        with patch.object(self.fixture.content, 'read', side_effect=RuntimeError('DB failure')):
            with self.assertRaises(RuntimeError): self.delivery.list('alice')

    def test_zip_is_built_after_authorization_transaction_and_size_is_bounded(self):
        self.fixture.finish()
        manifest = self.delivery.create('alice', self.fixture.project, self.command)
        from zipfile import ZipFile
        original = ZipFile.writestr
        def checked(bundle, *args, **kwargs):
            self.assertIsNone(self.fixture.store._connection.get())
            return original(bundle, *args, **kwargs)
        with patch.object(ZipFile, 'writestr', checked):
            self.assertTrue(self.delivery.download('bob', manifest['id']).startswith(b'PK'))
        self.delivery.maximum = 1
        with self.assertRaises(HTTPException) as error: self.delivery.download('bob', manifest['id'])
        self.assertEqual(error.exception.status_code, 413)

    def test_capture_uses_confirmed_fields_original_output_and_transactional_selection(self):
        f = self.fixture
        operation = {'id': 'operation', 'taskId': f.task, 'nativeRunId': f.run, 'closed': True,
            'observation': {'state': 'COMPLETED', 'output': {'taskId': 'child', 'runId': 'child-run'}}}
        f.custody.start.return_value = operation
        f.custody.read.return_value = operation
        asyncio.run(self.rounds.launch(f.ctx, Decision(action='experiment', reason='Measure',
            hypothesis='Test', conditions='Controlled', goal='Measure')))
        pin = {'id': 'cli-material', 'version': 1, 'sha256': 'a' * 64}
        config = EvidenceSelection(toolMaterial=pin, fields={'metrics': 'measurement'})
        proof = {'taskId': 'child', 'runId': 'child-run', 'planId': 'plan', 'materialRef': pin,
            'operationRef': pin, 'binding': {'toolName': 'measure'}, 'receipts': [
                {'effectKey': 'child-run:personal-tool:one', 'output': {'measurement': {'value': 3},
                    'privateCanary': 'PRIVATE_NOT_SELECTED'}}]}
        f.native.tool_results.return_value = proof
        recorded = []
        def write(name, raw):
            recorded.append(json.loads(raw))
            return {'jobId': f.task, 'id': 'artifact', 'sha256': 'b' * 64, 'size': len(raw.encode())}
        context = SimpleNamespace(write_artifact=write)
        with f.store.transaction() as conn:
            attempt = conn.execute(select(f.legacy.attempts)).mappings().one()
        with f.store.transaction() as conn, self.assertRaises(HTTPException) as mismatch:
            self.rounds.evidence.capture(conn, 'alice', attempt, operation,
                EvidenceSelection(toolMaterial={**pin, 'sha256': 'c' * 64}, fields={'metrics': 'measurement'}), context)
        self.assertEqual(mismatch.exception.detail, 'RESEARCH_EVIDENCE_MATERIAL_MISMATCH')
        self.assertEqual(recorded, [])
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with f.store.transaction() as conn:
                self.rounds.evidence.capture(conn, 'alice', attempt, operation, config, context)
                raise RuntimeError('rollback')
        with f.store.transaction() as conn:
            self.assertIsNone(conn.execute(select(f.legacy.attempts.c.selection)).scalar_one())
            selected = self.rounds.evidence.capture(conn, 'alice', attempt, operation, config, context)
        self.assertNotIn('PRIVATE_NOT_SELECTED', json.dumps(recorded))
        self.assertEqual(recorded[-1]['value'], {'value': 3})
        self.assertEqual(selected['missingEvidence'], ['run_recipe', 'source'])
        with f.store.transaction() as conn, patch.object(context, 'write_artifact', Mock(side_effect=AssertionError('duplicate write'))):
            self.assertEqual(self.rounds.evidence.capture(conn, 'alice', attempt, operation, config, context), selected)
        f.native.tool_results.assert_called_with('alice', 'child', 'child-run')

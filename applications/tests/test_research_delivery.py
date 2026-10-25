"""Portable delivery authority and selection; native CLI checked separately."""
import asyncio
import json
from io import BytesIO
from zipfile import ZipFile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.application_content import ContentPublication
from research.delivery import ResearchDelivery
from research.evidence import EvidenceSelection, _valid_value
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
        self.assertEqual(first['remainingQuestions'], {'status': 'not_provided'})
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

    def test_peer_sources_restrict_access_without_exporting_dependency_only_evidence(self):
        content = self.fixture.content
        peer = content.publish('bob', ContentPublication(
            source={'application': 'research', 'record': 'peer-only', 'revision': '1'}, visibility='team',
            content={'privateToSelectedExport': 'DEPENDENCY_NOT_SELECTED',
                'selectedEvidence': {'items': [{'reference': {'artifactId': 'not-selected'}}]}}), 'peer-source-publish')
        selected = content.publish('alice', ContentPublication(
            source={'application': 'research', 'record': 'selected-result', 'revision': '1'},
            visibility='team', sourceContentIds=[peer['id']],
            content={'kind': 'research.round', 'analysis': 'Actual selected rich body',
                'selectedEvidence': {'items': [], 'missingEvidence': ['source']}}), 'selected-source-publish')
        with self.fixture.store.transaction() as conn:
            conn.execute(self.rounds.rounds.update().where(self.rounds.rounds.c.id == self.fixture.row['id'])
                .values(terminal_record=selected['id'], terminal={'state': 'completed'}))
        manifest = self.delivery.create('alice', self.fixture.project, self.command)
        self.assertEqual(set(manifest['sourceIds']), {peer['id'], selected['id']})
        self.assertEqual(manifest['recordIds'], [selected['id']])
        self.assertEqual(manifest['records'][0]['analysis'], 'Actual selected rich body')
        with patch.object(content, 'artifact', side_effect=AssertionError('dependency artifact exported')):
            raw = self.delivery.download('bob', manifest['id'])
        with ZipFile(BytesIO(raw)) as bundle:
            self.assertEqual(bundle.namelist(), ['manifest.json'])
            self.assertNotIn(b'DEPENDENCY_NOT_SELECTED', bundle.read('manifest.json'))
        content.set_visibility('bob', peer['id'], 'personal', 'withdraw-peer-source')
        self.assertEqual(self.delivery.list('alice')['items'], [])
        for action in (lambda: self.delivery.read('alice', manifest['id']),
                       lambda: self.delivery.download('alice', manifest['id']),
                       lambda: content.read('alice', selected['id'])):
            with self.assertRaises(HTTPException) as denied:
                action()
            self.assertIn(denied.exception.status_code, {403, 404})

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
        proof['receipts'][0]['output']['recipe'] = {
            'command': ['python', 'source.py'], 'dependencies': True, 'data': None, 'expected': {}}
        with self.assertRaisesRegex(RuntimeError, 'isolate recipe fixture'):
            with f.store.transaction() as conn:
                missing = self.rounds.evidence.capture(conn, 'alice', attempt, operation,
                    EvidenceSelection(toolMaterial=pin, fields={'run_recipe': 'recipe'}), context)
                self.assertIn('run_recipe', missing['missingEvidence'])
                self.assertEqual(missing['artifacts'], [])
                self.assertEqual(recorded, [])
                raise RuntimeError('isolate recipe fixture')
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

    def test_current_recipe_prerequisites_are_explicit_and_not_truthy_placeholders(self):
        valid = {'command': ['python', 'source.py'], 'dependencies': [], 'data': [1, 2], 'expected': {'value': 3}}
        self.assertTrue(_valid_value('run_recipe', valid))
        for changes in ({'dependencies': True}, {'dependencies': 1}, {'data': None}, {'data': True},
                        {'expected': {}}, {'expected': {'value': float('nan')}}, {'command': ['']}):
            with self.subTest(changes=changes):
                self.assertFalse(_valid_value('run_recipe', {**valid, **changes}))

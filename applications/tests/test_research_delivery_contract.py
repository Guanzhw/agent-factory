"""Complete delivery bytes and original ending authority over real SQLite storage."""
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from agent_factory.application_content import ContentPublication
from fixture_content_artifacts import artifact_ref, install_artifacts
from research.delivery import delivery_router, ResearchDelivery
from research.peer_sources import ResearchPeerSources
from research.projects import EndProject, ProjectCommand
from research.workflow import Decision
import test_research_rounds as fixtures


class ResearchDeliveryContractTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ResearchRoundsFixture('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.start()
        self.delivery = ResearchDelivery(self.f.service)
        self.command = ProjectCommand(requestId='complete-delivery', expectedVersion=1)

    def record(self, body, *, artifacts=(), reference=None, visibility='team', owner='alice'):
        return self.f.content.publish(owner, ContentPublication(source={
            'application': 'research', 'record': str(uuid4()), 'revision': 'terminal'},
            content=body if reference is None else None, contentArtifact=reference,
            artifacts=list(artifacts), visibility=visibility), 'publish:' + str(uuid4()))

    def select_records(self, records):
        with self.f.projects.db.write() as conn:
            for index, record in enumerate(records):
                if index == 0:
                    conn.execute(self.f.service.rounds.update().where(self.f.service.rounds.c.id == self.f.row['id'])
                                 .values(terminal={'state': 'completed'}, terminal_record=record['id']))
                else:
                    conn.execute(self.f.service.rounds.insert().values(**{
                        **self.f.row, 'id': str(uuid4()), 'allocation_id': str(uuid4()),
                        'factory_request': 'other:' + str(uuid4()), 'task_id': str(uuid4()),
                        'terminal': {'state': 'completed'}, 'terminal_record': record['id']}))

    def test_two_legal_large_records_round_trip_without_body_copies(self):
        bodies = [{'kind': 'research.round.terminal', 'analysis': char * 7900,
                   'outcome': 'not_met'} for char in ('a', 'b')]
        records = [self.record(body) for body in bodies]
        self.select_records(records)
        result = self.delivery.create('alice', self.f.project, self.command)
        self.assertEqual(result['records'], bodies)
        self.assertEqual(self.delivery.read('bob', result['id']), result)
        self.assertEqual(self.delivery.create('alice', self.f.project, self.command), result)
        with self.f.projects.db.read() as conn:
            stored = conn.execute(select(self.delivery.deliveries.c.body)).scalar_one()
        self.assertNotIn('records', stored)
        with ZipFile(BytesIO(self.delivery.download('bob', result['id']))) as bundle:
            self.assertEqual(json.loads(bundle.read('manifest.json'))['records'], bodies)
        # Old snapshots keep their original identity; obsolete copied text is never trusted.
        with self.f.projects.db.write() as conn:
            conn.execute(self.delivery.deliveries.update().values(body={**stored, 'records': [{'obsolete': 'copy'}]}))
        self.assertEqual(self.delivery.read('bob', result['id'])['records'], bodies)

    def test_chinese_body_and_twenty_selected_artifacts_export_once(self):
        _, run = install_artifacts(self.f.store, task_id=self.f.task, run_id=self.f.run)
        raw = b'{"role":"metrics","value":{"measured":3}}'
        selected = [artifact_ref(self.f.store, run, raw, name=f'metric-{i}.json') for i in range(20)]
        body = {'analysis': '分析' * 1900, 'outcome': 'not_met', 'selectedEvidence': {
            'items': [{'reference': ref, 'role': 'metrics', 'size': len(raw), 'field': 'metrics',
                       'effectKey': 'original:' + str(i)} for i, ref in enumerate(selected)], 'missingEvidence': []}}
        reference = artifact_ref(self.f.store, run, json.dumps(body, ensure_ascii=False).encode())
        record = self.record(body, artifacts=selected, reference=reference)
        self.select_records([record])
        manifest = self.delivery.create('alice', self.f.project, self.command)
        self.assertEqual(manifest['records'], [body])
        with ZipFile(BytesIO(self.delivery.download('bob', manifest['id']))) as bundle:
            self.assertEqual(len(bundle.namelist()), 21)
            self.assertNotIn('evidence/' + reference['artifactId'], bundle.namelist())
            self.assertEqual(json.loads(bundle.read('manifest.json'))['records'], [body])
        self.f.store.sql('UPDATE af_artifacts SET content=:raw WHERE id=:id', raw=b'corrupt', id=selected[0]['artifactId'])
        for action in (self.delivery.read, self.delivery.download):
            with self.assertRaises(HTTPException) as damaged: action('bob', manifest['id'])
            self.assertEqual(damaged.exception.status_code, 409)
        self.f.store.sql('DELETE FROM af_artifacts WHERE id=:id', id=selected[0]['artifactId'])
        with self.assertRaises(HTTPException) as missing: self.delivery.read('bob', manifest['id'])
        self.assertEqual(missing.exception.status_code, 404)

    def test_actual_zip_boundary_is_shared_and_failed_create_has_no_receipt(self):
        self.select_records([self.record({'outcome': 'not_met'})])
        first = self.delivery.create('alice', self.f.project, self.command)
        size = len(self.delivery.download('alice', first['id']))
        self.delivery.maximum = size - 1
        app = FastAPI()
        app.include_router(delivery_router(self.f.auth, self.delivery))
        with patch.object(self.f.auth, 'user', return_value={'id': 'alice'}), TestClient(app) as client:
            response = client.post('/api/factory/research/projects/' + self.f.project + '/deliveries',
                json={'requestId': 'boundary-delivery', 'expectedVersion': 1})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()['detail'], 'RESEARCH_DELIVERY_TOO_LARGE')
        for action in (self.delivery.read, self.delivery.download):
            with self.assertRaises(HTTPException) as too_large:
                action('alice', first['id'])
            self.assertEqual(too_large.exception.status_code, 413)
        with self.f.projects.db.read() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.delivery.deliveries)).scalar_one(), 1)
            self.assertIsNone(conn.execute(select(self.f.projects.commands).where(
                self.f.projects.commands.c.request_id == 'boundary-delivery')).first())
        self.delivery.maximum = size
        accepted = self.delivery.create('alice', self.f.project, ProjectCommand(requestId='boundary-delivery', expectedVersion=1))
        self.assertEqual(len(self.delivery.download('alice', accepted['id'])), size)

    def end(self, *, reason='未达标；剩余问题：需要独立复现。\n保留完整负结果。'):
        return self.f.projects.change('alice', self.f.project, 'end', EndProject(
            requestId='original-ending', expectedVersion=1, outcome='not_met', reason=reason))['ending']

    def test_manual_ending_is_exact_and_old_or_early_snapshots_are_not_backfilled(self):
        self.select_records([self.record({'outcome': 'not_met'})])
        early = self.delivery.create('alice', self.f.project, self.command)
        ending = self.end()
        command = ProjectCommand(requestId='after-original-ending', expectedVersion=1)
        manifest = self.delivery.create('alice', self.f.project, command)
        expected = {'ownerId': 'alice', 'sourceIds': [], **ending}
        self.assertEqual(manifest['ending'], expected)
        self.assertEqual(manifest['ending']['resourceCleanup'], 'not_observed')
        self.assertNotIn('actor', manifest['ending'])
        with ZipFile(BytesIO(self.delivery.download('bob', manifest['id']))) as bundle:
            self.assertEqual(json.loads(bundle.read('manifest.json'))['ending'], expected)
        self.assertEqual(self.delivery.create('alice', self.f.project, command)['ending'], expected)
        self.assertIsNone(self.delivery.read('alice', early['id']).get('ending'))
        with self.f.projects.db.write() as conn:
            old = dict(early); old.pop('ending', None)
            for field in ('id', 'ownerId', 'createdAt'): old.pop(field)
            conn.execute(self.delivery.deliveries.update().where(self.delivery.deliveries.c.id == early['id']).values(body=old))
        self.assertIsNone(self.delivery.read('alice', early['id']).get('ending'))

    def test_unpublished_round_dependencies_protect_ending_even_for_source_owner(self):
        sources = ResearchPeerSources(self.f.store, self.f.content)
        self.f.service.peer_sources = self.f.projects.peer_sources = sources
        peer = self.record({'analysis': 'dependency only'})
        sources.bind(self.f.row['id'], self.f.project, [peer['id']], [])
        self.end()
        manifest = self.delivery.create('alice', self.f.project, self.command)
        self.assertEqual(manifest['sourceIds'], [peer['id']])
        self.assertEqual(manifest['ending']['sourceIds'], [peer['id']])
        self.assertEqual(manifest['records'], [])
        self.assertNotIn('dependency only', json.dumps(manifest))
        self.f.content.set_visibility('alice', peer['id'], 'personal', 'withdraw-ending-dependency')
        for actor in ('alice', 'bob'):
            self.assertEqual(self.delivery.list(actor)['items'], [])
            for action in (self.delivery.read, self.delivery.download):
                with self.assertRaises(HTTPException): action(actor, manifest['id'])
        with self.assertRaises(HTTPException):
            self.delivery.create('alice', self.f.project, ProjectCommand(requestId='after-withdrawal', expectedVersion=1))

    def test_peer_only_sources_do_not_bypass_ending_owner_disable(self):
        sources = ResearchPeerSources(self.f.store, self.f.content)
        self.f.service.peer_sources = self.f.projects.peer_sources = sources
        peer = self.record({'analysis': 'peer only'}, owner='bob')
        sources.bind(self.f.row['id'], self.f.project, [peer['id']], [])
        self.end()
        manifest = self.delivery.create('alice', self.f.project, self.command)
        self.assertEqual(self.delivery.read('bob', manifest['id'])['ending']['ownerId'], 'alice')
        self.f.auth.directory.set_disabled('alice', True)
        self.assertEqual(self.delivery.list('bob')['items'], [])
        for action in (self.delivery.read, self.delivery.download):
            with self.assertRaises(HTTPException): action('bob', manifest['id'])

    def test_automatic_ending_retains_analysis_status_and_unpublished_round_is_missing(self):
        self.f.service.context(self.f.ctx)
        self.f.service.record_decision(self.f.ctx, Decision(action='stop', outcome='not_met', reason='原负结论').model_dump())
        self.f.finish()
        ending = self.f.projects.read('alice', self.f.project)['ending']
        with self.f.projects.db.write() as conn:
            unpublished = {**self.f.row, 'id': str(uuid4()), 'allocation_id': str(uuid4()),
                'factory_request': 'unpublished-original', 'task_id': str(uuid4()),
                'terminal': {'sharing': 'publication_failed'}, 'terminal_record': None}
            conn.execute(self.f.service.rounds.insert().values(**unpublished))
        manifest = self.delivery.create('alice', self.f.project, self.command)
        self.assertEqual(manifest['ending'], {'ownerId': 'alice', 'sourceIds': [], **ending})
        self.assertEqual(manifest['ending']['verificationStatus'], 'agent_analysis')
        self.assertIn('round_not_published:' + unpublished['id'], manifest['missingEvidence'])
        self.assertNotIn('round_not_terminal:' + unpublished['id'], manifest['missingEvidence'])

    def test_selected_personal_record_still_allows_original_owner(self):
        self.select_records([self.record({'analysis': 'own selected'}, visibility='personal')])
        self.end()
        manifest = self.delivery.create('alice', self.f.project, self.command)
        self.assertEqual(self.delivery.read('alice', manifest['id'])['records'], [{'analysis': 'own selected'}])
        with self.assertRaises(HTTPException): self.delivery.read('bob', manifest['id'])

    def test_withdrawal_during_external_zip_build_prevents_creation(self):
        record = self.record({'analysis': 'selected'})
        self.select_records([record])
        original = ZipFile.writestr
        def withdraw(bundle, *args, **kwargs):
            self.assertIsNone(self.f.store._connection.get())
            self.f.content.set_visibility('alice', record['id'], 'personal', 'during-package-build')
            return original(bundle, *args, **kwargs)
        # An ending dependency enforces the original team rule even for Alice.
        sources = ResearchPeerSources(self.f.store, self.f.content)
        self.f.service.peer_sources = self.f.projects.peer_sources = sources
        sources.bind(self.f.row['id'], self.f.project, [record['id']], [])
        self.end()
        with patch.object(ZipFile, 'writestr', withdraw), self.assertRaises(HTTPException):
            self.delivery.create('alice', self.f.project, self.command)
        with self.f.projects.db.read() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.delivery.deliveries)).scalar_one(), 0)

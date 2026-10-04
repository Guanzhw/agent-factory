"""Governed native bibliography/artifacts with explicitly controlled transport.

Actual Linux/public transport is a separate opt-in case; it may be blocked and
must never be counted as live success from this fixture's invented source.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient

from pg_fixture import IsolatedPostgres
from agent_factory.main import create_app
from agent_factory.local_literature_profile import literature_settings, publish_literature_application, REGISTRATION_REF, CONNECTION_NAME
from agent_factory.orx_retrieval import LinuxRetrievalAdapter, TaskLinuxRetrievalProvider
from agent_factory.openresearch import CommandResult, OpenResearchError


class ControlledRetrieval(LinuxRetrievalAdapter):
    def __init__(self, **kwargs):
        self.owner_id, self.task_id = kwargs['owner_id'], kwargs['task_id']
        self.pin, self.environment = kwargs['pin'], kwargs['environment']
        self.max_output_bytes, self.command_timeout = kwargs['max_output_bytes'], kwargs['command_timeout']
        self.authorize, self.enabled = kwargs['authorize'], True

    async def discover(self, query, *, corpus, limit):
        self.authorize('discover')
        return [{'id': '123', 'title': 'Invented controlled source fixture', 'abstract': 'Original synthetic excerpt for artifact integrity verification.'}]

    async def paper(self, paper_id, *, full=False):
        self.authorize('paper')
        text = 'Original synthetic abstract; no live literature request was made.'
        return CommandResult(('fixture',), text, '', 0, 0, hashlib.sha256(text.encode()).hexdigest())

    def containment_evidence(self):
        return {'kind': 'controlled_transport_fixture', 'allStopped': True, 'activeProcesses': 0}


class ControlledProvider:
    def create_retrieval_adapter(self, **kwargs): return ControlledRetrieval(**kwargs)


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated loopback PostgreSQL')
class LiteraturePostgresTests(unittest.TestCase):
    def provider(self): return ControlledProvider()

    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix='factory-literature-')
        self.addCleanup(self.workspace.cleanup)
        self.settings = literature_settings(db_url=self.database.url, workspace=Path(self.workspace.name), provider=self.provider())
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store = self.state['store']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.state['auth'].authorization.unassign('bob', 'factory-user')
        self.state['auth'].authorization.assign('bob', 'factory-manager')
        self.application = publish_literature_application(self.state, author='manager', reviewer='bob')
        self.connection = self.state['connections'].bind('alice', REGISTRATION_REF, 'literature-connection', capabilities=['research:read'])
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def request(self, method, path, body=None, owner='alice'):
        token = self.state['auth']._issue_native_token(owner)
        response = self.client.request(method, '/api/factory' + path, json=body, headers={'Authorization': 'Bearer ' + token})
        self.assertTrue(response.is_success, response.text)
        return response.json()

    def run_evidence(self):
        def post(path, body, owner='alice'):
            return self.request('POST', path, {'requestId': str(uuid4()), **body}, owner)
        proposal = post('/compositions/proposals', {'goal': 'Public literature source evidence, no provider',
            'mode': 'bibliography', 'applicationRef': {key: self.application[key] for key in ('id', 'version', 'sha256')},
            'connectionRefs': {CONNECTION_NAME: self.connection['ref']}})
        self.assertEqual(proposal['candidate']['status'], 'ready', proposal)
        plan = post('/compositions/proposals/' + proposal['id'] + '/accept', {})
        review = post('/plan-reviews', {'planId': plan['id']})
        post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, 'manager')
        job = post('/instances', {'planId': plan['id']})
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            detail = self.request('GET', '/jobs/' + job['id'])
            if detail['job']['status'] in {'completed', 'failed', 'unknown', 'canceled'}: break
            time.sleep(.1)
        self.assertEqual(detail['job']['status'], 'completed', detail)
        return job['id'], detail

    def test_native_review_queue_sources_report_and_owner_download(self):
        task, detail = self.run_evidence()
        projection = detail['literatureEvidence']
        self.assertEqual(projection['status'], 'ready')
        self.assertEqual(projection['sourceCount'], 1)
        self.assertEqual(projection['evidenceKind'], 'controlled_literature_fixture')
        self.assertFalse(projection['sources'][0]['fullTextAvailable'])
        bundle = next(a for a in detail['artifacts'] if a['name'].endswith('.zip'))
        headers = {'Authorization': 'Bearer ' + self.state['auth']._issue_native_token('alice')}
        path = '/api/factory/jobs/' + task + '/artifacts/' + bundle['id']
        downloaded = self.client.get(path, headers=headers)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(hashlib.sha256(downloaded.content).hexdigest(), bundle['sha256'])
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            sources = json.loads(archive.read('sources.json'))['sources']
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]['sourceId'], '123')
            self.assertFalse(sources[0]['fullTextAvailable'])
            self.assertEqual(sources[0]['missingFullTextReason'], 'full_text_unsupported')
            self.assertIn('Original synthetic', sources[0]['excerpt'])
        other = self.client.get(path, headers={'Authorization': 'Bearer ' + self.state['auth']._issue_native_token('bob')})
        self.assertEqual(other.status_code, 404)
        evidence = [a for a in detail['artifacts'] if a['name'].startswith('literature-sources-')]
        self.assertTrue(all(a['provenance']['evidenceKind'] == 'controlled_literature_fixture' for a in evidence))


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL') and os.getenv('FACTORY_LITERATURE_PUBLIC_ACCEPTANCE') == '1',
                     'Explicit opt-in: one small public/free query through the approved Linux container')
class ActualLiteraturePostgresTests(LiteraturePostgresTests):
    def provider(self): return TaskLinuxRetrievalProvider(Path(os.environ['FACTORY_ORX_BINARY']))

    def setUp(self):
        super().setUp()
        self.addCleanup(self.remove_containers)

    def remove_containers(self):
        import subprocess
        for marker in Path(self.workspace.name).rglob('factory-linux-container.json'):
            saved = json.loads(marker.read_text())
            value = json.loads(subprocess.check_output(['docker', 'inspect', saved['containerId']], text=True))[0]
            self.assertEqual(value['Config']['Labels']['agent-factory.orx-spec'], saved['specSha256'])
            self.assertIn(str(marker.parent), [item['Source'] for item in value['Mounts'] if item['RW']])
            self.assertFalse(value['State']['Running'])
            subprocess.run(['docker', 'rm', saved['containerId']], check=True, capture_output=True)

    def test_native_review_queue_sources_report_and_owner_download(self):
        task, detail = self.run_evidence()
        artifacts = detail['artifacts']
        evidence = [a for a in artifacts if a['name'].startswith('literature-sources-')]
        self.assertTrue(evidence)
        for item in evidence:
            proof = item['provenance']['containment']
            self.assertEqual(proof['kind'], 'linux_task_container')
            self.assertTrue(proof['allStopped'])
            self.assertEqual(proof['network'], 'bridge')
        bundle = next(a for a in artifacts if a['name'].endswith('.zip'))
        _, raw = self.store.artifact(task, bundle['id'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            body = json.loads(archive.read('sources.json'))
        result = {'actualTransport': True, 'liveSourceSuccess': bool(body['sources']),
            'sourceCount': len(body['sources']), 'errors': body['provenance'].get('retrievalErrors', []),
            'taskId': task, 'bundleSha256': hashlib.sha256(raw).hexdigest(),
            'containment': [item['provenance']['containment'] for item in evidence]}
        directory = os.getenv('FACTORY_LITERATURE_EVIDENCE_DIR')
        if directory:
            output = Path(directory); output.mkdir(parents=True, exist_ok=True)
            (output/'actual-result.json').write_text(json.dumps(result, indent=2))
            (output/'literature-evidence.zip').write_bytes(raw)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                (output/'report.md').write_bytes(archive.read('report.md'))
        print('ACTUAL_LITERATURE_RESULT=' + json.dumps(result), flush=True)
        if not body['sources']:
            self.assertTrue(result['errors'], 'Empty source outcome must disclose transport failure')


class FailedProvider:
    def create_retrieval_adapter(self, **kwargs):
        class Failed(ControlledRetrieval):
            async def discover(self, query, *, corpus, limit):
                raise OpenResearchError('COMMAND_FAILED', 'Controlled unavailable public endpoint')
        return Failed(**kwargs)


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated loopback PostgreSQL')
class FailedLiteraturePostgresTests(LiteraturePostgresTests):
    def provider(self): return FailedProvider()

    def test_native_review_queue_sources_report_and_owner_download(self):
        task, detail = self.run_evidence()
        self.assertEqual(detail['job']['status'], 'completed')
        evidence = detail['literatureEvidence']
        self.assertEqual(evidence['status'], 'no-sources')
        self.assertEqual(evidence['sourceCount'], 0)
        self.assertEqual(evidence['retrievalErrors'], ['COMMAND_FAILED'])
        self.assertEqual(evidence['evidenceKind'], 'controlled_literature_fixture')
        self.assertIn('未取得文献来源', detail['job']['validationStatus'])
        other = self.client.get('/api/factory/jobs/' + task,
            headers={'Authorization': 'Bearer ' + self.state['auth']._issue_native_token('bob')})
        self.assertEqual(other.status_code, 404)
        again = self.request('GET', '/jobs/' + task)
        self.assertEqual(again['literatureEvidence'], evidence)
        self.assertEqual(len(again['artifacts']), len(detail['artifacts']))
        bundle = next(a for a in detail['artifacts'] if a['name'].endswith('.zip'))
        self.assertEqual(bundle['provenance']['evidenceKind'], 'controlled_literature_fixture')
        _, raw = self.store.artifact(task, bundle['id'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            evidence = json.loads(archive.read('sources.json'))
            self.assertEqual(evidence['sources'], [])
            self.assertEqual(evidence['provenance']['retrievalErrors'], ['COMMAND_FAILED'])
            self.assertIn('未取得来源'.encode(), archive.read('report.md'))
            self.assertIn(b'COMMAND_FAILED', archive.read('report.md'))
        source_artifact = next(row for row in detail['artifacts'] if row['name'].startswith('literature-sources-'))
        _, source_bytes = self.store.artifact(task, source_artifact['id'])
        diagnostic = {'schema': 1, 'stage': 'discover', 'code': 'COMMAND_FAILED',
                      'failureClass': 'command-exit', 'transportCause': 'UNKNOWN'}
        self.assertEqual(source_artifact['provenance']['retrievalDiagnostics'], [diagnostic])
        self.assertEqual(json.loads(source_bytes)['retrievalDiagnostics'], [diagnostic])
        self.assertNotIn('Controlled unavailable public endpoint', source_bytes.decode())
        self.assertNotIn('Controlled unavailable public endpoint', json.dumps(source_artifact['provenance']))
        self.assertEqual(len(self.store.effects(task)), 2, 'Exactly one query and one report; no automatic repeated requests')


class LegacyArxivProvider:
    def create_retrieval_adapter(self, **kwargs):
        class LegacyArxiv(ControlledRetrieval):
            async def discover(self, query, *, corpus, limit):
                return [{'id': 'math/0211159', 'title': 'Invented legacy-ID fixture',
                         'abstract': 'Original controlled abstract; not a generated overview.'}]
            async def paper(self, paper_id, *, full=False):
                raise AssertionError('Legacy arXiv default overview must never be fetched as source text')
        return LegacyArxiv(**kwargs)


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated loopback PostgreSQL')
class LegacyArxivLiteraturePostgresTests(LiteraturePostgresTests):
    def provider(self): return LegacyArxivProvider()

    def test_native_review_queue_sources_report_and_owner_download(self):
        task, detail = self.run_evidence()
        bundle = next(a for a in detail['artifacts'] if a['name'].endswith('.zip'))
        _, raw = self.store.artifact(task, bundle['id'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            source = json.loads(archive.read('sources.json'))['sources'][0]
            self.assertEqual(source['sourceId'], 'math/0211159')
            self.assertEqual(source['textStatus'], 'abstract_only')
            self.assertEqual(source['missingFullTextReason'], 'full_text_unsupported')
            self.assertFalse(source['fullTextAvailable'])
            self.assertIn('Original controlled abstract', source['excerpt'])

"""Real native Factory/PG path with explicit synthetic PubMed HTTP responses."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

import httpx
from fastapi.testclient import TestClient

from pg_fixture import IsolatedPostgres
from agent_factory.main import create_app
from agent_factory.pubmed_profile import (
    PubMedProvider, pubmed_settings, publish_pubmed_application, REGISTRATION_REF,
    CONNECTION_NAME, TOOL,
)


class FixtureBody(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
    async def __aiter__(self):
        yield self.data


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated loopback PostgreSQL')
class PubMedProfilePostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix='factory-pubmed-fixture-')
        self.addCleanup(self.workspace.cleanup)
        self.requests = []
        self.after_request = None
        self.http_status = 200
        async def respond(request):
            self.requests.append(request)
            if self.after_request:
                self.after_request()
            if request.url.path.endswith('esearch.fcgi'):
                data = b'{"esearchresult":{"idlist":["123"]}}'
                media = 'application/json'
            else:
                data = b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Invented controlled PubMed fixture</ArticleTitle><Abstract><AbstractText>Original synthetic abstract for evidence verification only.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
                media = 'application/xml'
            return httpx.Response(self.http_status, headers={'content-type': media}, stream=FixtureBody(data))
        settings = pubmed_settings(db_url=self.database.url, workspace=Path(self.workspace.name),
            provider=PubMedProvider('alice', httpx.MockTransport(respond)))
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store = self.state['store']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.state['auth'].authorization.unassign('bob', 'factory-user')
        self.state['auth'].authorization.assign('bob', 'factory-manager')
        self.application = publish_pubmed_application(self.state, author='manager', reviewer='bob')
        self.connection = self.state['connections'].bind('alice', REGISTRATION_REF, str(uuid4()), capabilities=['research:read'])
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def request(self, method, path, body=None, owner='alice'):
        token = self.state['auth']._issue_native_token(owner)
        response = self.client.request(method, '/api/factory' + path, json=body,
                                       headers={'Authorization': 'Bearer ' + token})
        self.assertTrue(response.is_success, response.text)
        return response.json()

    def submit(self):
        def post(path, body, owner='alice'):
            return self.request('POST', path, {'requestId': str(uuid4()), **body}, owner)
        proposal = post('/compositions/proposals', {'goal': 'Public PubMed bibliography evidence without synthesis',
            'mode': 'bibliography', 'applicationRef': {key: self.application[key] for key in ('id', 'version', 'sha256')},
            'connectionRefs': {CONNECTION_NAME: self.connection['ref']}})
        self.assertEqual(proposal['candidate']['status'], 'ready', proposal)
        plan = post('/compositions/proposals/' + proposal['id'] + '/accept', {})
        self.assertEqual(plan['tools'], [TOOL])
        review = post('/plan-reviews', {'planId': plan['id']})
        post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, 'manager')
        return post('/instances', {'planId': plan['id']})['id'], plan

    def wait_detail(self, task):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            detail = self.request('GET', '/jobs/' + task)
            if detail['job']['status'] in {'completed', 'failed', 'unknown', 'canceled', 'cancelled'}:
                return detail
            time.sleep(.1)
        self.fail('Native PubMed fixture did not settle within observation bound')

    def test_governed_native_sources_owner_download_hash_and_provenance(self):
        task, plan = self.submit()
        detail = self.wait_detail(task)
        self.assertEqual(detail['job']['status'], 'completed', detail)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(self.store.effects(task)), 1)
        self.assertEqual(self.store.effects(task)[0]['status'], 'DONE')
        projection = detail['literatureEvidence']
        self.assertEqual(projection['sourceCount'], 1)
        self.assertEqual(projection['evidenceKind'], 'controlled_literature_fixture')
        self.assertEqual(len(detail['artifacts']), 3)
        for artifact in detail['artifacts']:
            provenance = artifact['provenance']
            self.assertEqual(provenance['ownerId'], 'alice')
            self.assertEqual(provenance['planId'], plan['id'])
            self.assertEqual(provenance['contractRevision'], '2')
            self.assertEqual(provenance['tool'], TOOL)
            self.assertEqual(provenance['transportBoundary'], 'bounded-host-http')
            self.assertNotIn('containment', provenance)
        bundle = next(item for item in detail['artifacts'] if item['name'].endswith('.zip'))
        path = '/api/factory/jobs/' + task + '/artifacts/' + bundle['id']
        def download(owner):
            return self.client.get(path, headers={'Authorization': 'Bearer ' + self.state['auth']._issue_native_token(owner)})
        raw = download('alice')
        self.assertEqual(raw.status_code, 200)
        self.assertEqual(hashlib.sha256(raw.content).hexdigest(), bundle['sha256'])
        self.assertEqual(download('bob').status_code, 404)
        with zipfile.ZipFile(io.BytesIO(raw.content)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            for name, expected in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
            source = json.loads(archive.read('sources.json'))['sources'][0]
            self.assertFalse(source['fullTextAvailable'])
            self.assertEqual(source['textStatus'], 'abstract_only')
            self.assertIn('Original synthetic', source['excerpt'])

    def test_connection_revocation_during_await_blocks_artifacts(self):
        def revoke():
            self.after_request = None
            self.state['connections'].revoke('alice', self.connection['ref'], str(uuid4()))
        self.after_request = revoke
        task, _ = self.submit()
        self.wait_detail(task)
        self.assertEqual(self.store.artifacts(task), [])
        self.assertEqual(len(self.requests), 1, "Revoked authority must prevent efetch dispatch")
        self.assertEqual(self.store.effects(task)[0]['status'], 'UNKNOWN')

    def test_durable_cancel_during_await_blocks_artifacts(self):
        def cancel():
            self.after_request = None
            tasks = self.store.sql("SELECT id FROM af_tasks WHERE owner_id='alice'")
            self.assertEqual(len(tasks), 1)
            self.store.request_cancel(tasks[0]['id'])
        self.after_request = cancel
        task, _ = self.submit()
        self.wait_detail(task)
        self.assertTrue(self.store.task(task)['cancel_requested'])
        self.assertEqual(len(self.requests), 1, "Durable cancellation must prevent efetch dispatch")
        self.assertEqual(self.store.artifacts(task), [])
        self.assertEqual(self.store.effects(task)[0]['status'], 'UNKNOWN')

    def test_durable_unknown_effect_refuses_replay_before_http(self):
        reserve = self.store.effect_reserve
        def already_unknown(run_id, key, request):
            self.assertEqual(reserve(run_id, key, request)['status'], 'new')
            return reserve(run_id, key, request)
        with patch.object(self.store, 'effect_reserve', side_effect=already_unknown):
            task, _ = self.submit()
            self.wait_detail(task)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.store.artifacts(task), [])
        self.assertEqual(len(self.store.effects(task)), 1)
        self.assertEqual(self.store.effects(task)[0]['status'], 'UNKNOWN')

    def test_recognized_retrieval_failure_writes_explicit_empty_evidence(self):
        self.http_status = 503
        task, _ = self.submit()
        detail = self.wait_detail(task)
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(len(self.requests), 1)
        evidence = detail["literatureEvidence"]
        self.assertEqual(evidence["status"], "no-sources")
        self.assertEqual(evidence["sourceCount"], 0)
        self.assertEqual(evidence["retrievalErrors"], ["HTTP_STATUS"])
        self.assertEqual(self.store.effects(task)[0]["status"], "DONE")
        bundle = next(item for item in detail["artifacts"] if item["name"].endswith(".zip"))
        _, raw = self.store.artifact(task, bundle["id"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            value = json.loads(archive.read("sources.json"))
            self.assertEqual(value["sources"], [])
            self.assertEqual(value["provenance"]["retrievalErrors"], ["HTTP_STATUS"])
            self.assertIn("未取得来源".encode(), archive.read("report.md"))

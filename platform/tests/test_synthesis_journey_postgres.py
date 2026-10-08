# pyright: reportMissingImports=false
"""Owner source-artifact selection through native controlled synthesis, no live IO."""
from dataclasses import replace
import hashlib
import asyncio
import threading
from unittest.mock import patch
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from agent_factory.main import create_app
from agent_factory import synthesis_runtime
from agent_factory.literature_synthesis_profile import (trusted_model_binding, ScientificFixtureModel,
    REGISTRATION_REF, CONNECTION_NAME)
from agent_factory.literature_synthesis import SCIENTIFIC_CAPABILITY
from agent_factory.pubmed_profile import PubMedProvider, pubmed_settings, publish_pubmed_application
from agent_factory.pubmed_profile import REGISTRATION_REF as PUBMED_REF, CONNECTION_NAME as PUBMED_CONNECTION
from pg_fixture import IsolatedPostgres


class SyntheticBody(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        yield self.data


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL/native queue')
class SynthesisJourneyPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        workspace = tempfile.TemporaryDirectory(prefix='source-synthesis-journey-')
        self.addCleanup(workspace.cleanup)
        self.requests = []
        def handler(request):
            self.requests.append(request)
            if request.url.path.endswith('esearch.fcgi'):
                raw, media = b'{"esearchresult":{"idlist":["123"]}}', 'application/json'
            else:
                raw = b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Controlled source journey</ArticleTitle><Abstract><AbstractText>Synthetic bounded excerpt for citation integrity testing only.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
                media = 'application/xml'
            return httpx.Response(200, headers={'content-type': media}, stream=SyntheticBody(raw))
        settings = pubmed_settings(db_url=database.url, workspace=Path(workspace.name),
            provider=PubMedProvider('alice', httpx.MockTransport(handler)))
        self.settings = replace(settings, source_synthesis_enabled=True, max_tool_calls=2,
            trusted_connections={**settings.trusted_connections, REGISTRATION_REF: trusted_model_binding("alice")})
        self.start()
        self.addCleanup(self.stop)
        self.state['auth'].authorization.unassign('bob', 'factory-user')
        self.state['auth'].authorization.assign('bob', 'factory-manager')
        self.pubmed_app = publish_pubmed_application(self.state, author='manager', reviewer='bob')
        self.pubmed_connection = self.state['connections'].bind('alice', PUBMED_REF, str(uuid4()), capabilities=['research:read'])
        self.model_connection = self.state['connections'].bind('alice', REGISTRATION_REF, str(uuid4()), capabilities=[SCIENTIFIC_CAPABILITY])
        self.synthesis_app = self.publish_synthesis()

    def start(self):
        app = create_app(self.settings)
        self.state = app.app.state.factory
        self.store = self.state['store']
        self.client = TestClient(app).__enter__()  # pyright: ignore[reportArgumentType]

    def stop(self):
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None
            self.store.engine.dispose()
            self.store.native_db.db_engine.dispose()

    def request(self, method, path, body=None, *, owner='alice', status=200):
        assert self.client is not None
        token = self.state['auth']._issue_native_token(owner)
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + token})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def post(self, path, body=None, *, owner='alice', status=201):
        return self.request('POST', path, {'requestId': str(uuid4()), **(body or {})}, owner=owner, status=status)

    def approve(self, plan):
        review = self.post('/plan-reviews', {'planId': plan['id']})
        self.post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, owner='manager', status=200)

    def detail(self, task):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            result = self.request('GET', '/jobs/' + task)
            if result['job']['status'] in {'completed', 'failed', 'cancelled', 'canceled', 'unknown'}:
                return result
            time.sleep(.05)
        self.fail('Controlled native task did not reach terminal state')

    def source(self):
        proposal = self.post('/compositions/proposals', {'goal': 'Controlled bibliography evidence for selected sources',
            'mode': 'bibliography', 'applicationRef': {key: self.pubmed_app[key] for key in ('id', 'version', 'sha256')},
            'connectionRefs': {PUBMED_CONNECTION: self.pubmed_connection['ref']}})
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept')
        self.approve(plan)
        task = self.post('/instances', {'planId': plan['id']}, status=202)['id']
        self.assertEqual(self.detail(task)['job']['status'], 'completed')
        preview = self.request('GET', '/synthesis/sources/' + task)
        self.assertEqual(preview['projection']['evidenceKind'], 'controlled_literature_fixture')
        return task, preview

    def snapshot(self, task, preview, **changes):
        body = {'sourceTaskId': task, 'sourceIds': [preview['projection']['sources'][0]['sourceId']],
            'question': 'Describe only the selected synthetic source excerpt.', 'expectedFingerprint': preview['fingerprint'],
            'requestId': str(uuid4()), **changes}
        return self.request('POST', '/synthesis/snapshots', body, status=201), body

    def test_source_selection_cross_owner_stale_missing_and_changed_artifact_fail_closed(self):
        task, preview = self.source()
        snapshot, request = self.snapshot(task, preview)
        self.request('GET', '/synthesis/sources/' + task, owner='bob', status=404)
        self.request('GET', '/synthesis/snapshots/' + snapshot['id'], owner='bob', status=404)
        self.request('POST', '/synthesis/snapshots', {**request, 'requestId': str(uuid4())}, owner='bob', status=404)
        self.request('POST', '/synthesis/snapshots', {**request, 'requestId': str(uuid4()),
            'expectedFingerprint': 'f' * 64}, status=409)
        self.request('POST', '/synthesis/snapshots', {**request, 'requestId': str(uuid4()),
            'sourceIds': ['not-selected-source']}, status=422)
        artifact_id = preview['projection']['bundleArtifactId']
        metadata, original = self.store.artifact(task, artifact_id)
        try:
            self.store.sql('UPDATE af_artifacts SET content=:content WHERE id=:id', content=b'controlled corruption', id=artifact_id)
            self.request('GET', '/synthesis/snapshots/' + snapshot['id'] + '/current', status=409)
        finally:
            self.store.sql('UPDATE af_artifacts SET content=:content WHERE id=:id', content=original, id=artifact_id)
        self.assertEqual(self.request('GET', '/synthesis/snapshots/' + snapshot['id'] + '/current')['fingerprint'], snapshot['fingerprint'])
        # Missing evidence must fail even though the immutable snapshot remains readable.
        self.store.sql('DELETE FROM af_artifacts WHERE id=:id', id=artifact_id)
        self.request('GET', '/synthesis/snapshots/' + snapshot['id'] + '/current', status=409)
        self.assertEqual(self.request('GET', '/synthesis/snapshots/' + snapshot['id'])['fingerprint'], snapshot['fingerprint'])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(hashlib.sha256(original).hexdigest(), metadata['sha256'])


    def publish_synthesis(self):
        governance = self.state['material_governance']
        materials = []
        for definition in synthesis_runtime.material_drafts():
            draft = governance.create_draft('manager', definition, str(uuid4()))
            review = governance.request_publication('manager', draft['id'], draft['version'], str(uuid4()))
            governance.decide_publication('bob', review['id'], True, str(uuid4()))
            materials.append(draft)
        app = self.state['applications'].create_draft('manager', synthesis_runtime.application_definition(materials), str(uuid4()))
        review = self.state['applications'].request_publication('manager', app['id'], app['version'], str(uuid4()))
        self.state['applications'].decide_publication('bob', review['id'], True, str(uuid4()))
        return app

    def synthesis_plan(self, snapshot, *, accept_request=None):
        proposal = self.post('/compositions/proposals', {'goal': snapshot['question'], 'mode': 'controlled-fixture',
            'applicationRef': {key: self.synthesis_app[key] for key in ('id', 'version', 'sha256')},
            'connectionRefs': {CONNECTION_NAME: self.model_connection['ref']},
            'sourceSnapshotRef': {key: snapshot[key] for key in ('id', 'fingerprint')}})
        self.assertEqual(proposal['candidate']['status'], 'ready', proposal)
        command = accept_request or {'requestId': str(uuid4())}
        plan = self.request('POST', '/compositions/proposals/' + proposal['id'] + '/accept', command, status=201)
        return plan, proposal, command

    def run_synthesis(self, plan):
        self.approve(plan)
        task = self.post('/instances', {'planId': plan['id']}, status=202)['id']
        detail = self.detail(task)
        self.assertEqual(detail['job']['status'], 'completed', detail)
        artifact = next(row for row in detail['artifacts'] if row['name'] == 'literature-synthesis.json')
        assert self.client is not None
        token = self.state['auth']._issue_native_token('alice')
        path = f"/api/factory/jobs/{task}/artifacts/{artifact['id']}"
        response = self.client.get(path, headers={'Authorization': 'Bearer ' + token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), artifact['sha256'])
        return task, detail, response.json(), path

    def test_selected_snapshot_approved_plan_native_report_and_owner_download(self):
        source, preview = self.source()
        snapshot, _ = self.snapshot(source, preview)
        plan, _, _ = self.synthesis_plan(snapshot)
        self.assertEqual(plan['sourceSnapshotRef'], {key: snapshot[key] for key in ('id', 'fingerprint')})
        self.post('/instances', {'planId': plan['id']}, status=409)
        task, detail, report, path = self.run_synthesis(plan)
        self.assertEqual(report['snapshotSha256'], snapshot['contextFingerprint'])
        self.assertTrue(report['citationIntegrityVerified'])
        self.assertFalse(report['scientificConclusionVerified'])
        self.assertEqual(report['semanticReview'], 'required')
        self.assertEqual(report['report']['claims'][0]['sourceIds'], snapshot['sourceIds'])
        self.assertEqual(len(detail['artifacts']), 2)
        self.request('GET', path.removeprefix('/api/factory'), owner='bob', status=404)
        self.assertEqual(len(self.store.effects(task)), 1)
        self.assertEqual(len(self.requests), 2)

    def test_lost_snapshot_and_accept_responses_restart_preserve_original_plan(self):
        source, preview = self.source()
        snapshot, command = self.snapshot(source, preview)
        plan, proposal, accept_command = self.synthesis_plan(snapshot)
        # Both commands committed before the operator lost their response.
        self.stop()
        self.start()
        recovered = self.request('POST', '/synthesis/snapshots', command, status=201)
        self.assertEqual(recovered, snapshot)
        recovered_plan = self.request('POST', '/compositions/proposals/' + proposal['id'] + '/accept', accept_command, status=201)
        self.assertEqual(recovered_plan, plan)
        self.assertEqual(self.request('GET', '/synthesis/snapshots/' + snapshot['id'] + '/current'), snapshot)
        task, _, _, _ = self.run_synthesis(recovered_plan)
        self.assertEqual(self.store.task(task, 'alice')['plan_id'], plan['id'])
        self.assertEqual(len(self.requests), 2)

    def test_current_revocation_and_cancel_at_model_boundary_create_no_report(self):
        source, preview = self.source()
        snapshot, _ = self.snapshot(source, preview)
        for action in ('cancel', 'revoke'):
            with self.subTest(action=action):
                plan, _, _ = self.synthesis_plan(snapshot)
                self.approve(plan)
                entered, release = threading.Event(), threading.Event()
                original = ScientificFixtureModel.ainvoke
                async def paused(model, *args, **kwargs):
                    entered.set()
                    if not await asyncio.to_thread(release.wait, 10):
                        raise TimeoutError('Controlled model boundary not released')
                    return await original(model, *args, **kwargs)
                with patch.object(ScientificFixtureModel, 'ainvoke', paused):
                    task = self.post('/instances', {'planId': plan['id']}, status=202)['id']
                    try:
                        self.assertTrue(entered.wait(10))
                        if action == 'cancel':
                            self.request('POST', '/jobs/' + task + '/cancel', {}, status=200)
                        else:
                            self.state['connections'].revoke('alice', self.model_connection['ref'], str(uuid4()))
                        release.set()
                        self.assertNotEqual(self.detail(task)['job']['status'], 'completed')
                        self.assertEqual(self.store.artifacts(task), [])
                    finally:
                        release.set()

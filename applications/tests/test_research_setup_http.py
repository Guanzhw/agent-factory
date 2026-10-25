"""Portable real HTTP setup-to-agreement contract; no native execution proof."""
import time
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research.projects import ResearchProjects, projects_router
from research.setup import setup_router
import test_research_setup as fixtures


class ResearchSetupHttpTests(unittest.TestCase):
    setUp = fixtures.ResearchSetupTests.setUp
    database = fixtures.ResearchSetupTests.database
    no_dispatch = fixtures.ResearchSetupTests.no_dispatch
    configure = fixtures.ResearchSetupTests.configure
    counts = fixtures.ResearchSetupTests.counts

    def test_published_setup_pin_and_personal_binding_survive_project_confirmation(self):
        self.configure()
        projects = ResearchProjects(self.store, self.auth, Mock())
        app = FastAPI()
        @app.middleware('http')
        async def identity(request, call_next):
            request.state.authenticated = True
            request.state._agno_auth_complete = True
            request.state.user_id = request.headers.get('x-test-owner', 'alice')
            return await call_next(request)
        app.include_router(setup_router(self.auth, self.setup))
        app.include_router(projects_router(self.auth, projects))
        with TestClient(app) as client:
            before = self.counts()
            candidates = client.get('/api/factory/research/setup')
            self.assertEqual(candidates.status_code, 200, candidates.text)
            self.assertEqual(candidates.json()['workflowPin'], self.pin)
            self.assertEqual(self.counts(), before)
            draft = client.post('/api/factory/research/setup/drafts', json=self.body.model_dump())
            self.assertEqual(draft.status_code, 200, draft.text)
            self.assertEqual(self.counts()[:2], before[:2])
            setup_path = '/api/factory/research/setup/' + draft.json()['id']
            published = client.post(setup_path + '/publish', json={'requestId': 'http-publish-original'})
            self.assertEqual(published.status_code, 200, published.text)
            receipt = published.json()
            self.assertEqual(client.get('/api/factory/research/setup/requests/http-publish-original').json(), receipt)
            self.assertEqual(client.get(setup_path, headers={'x-test-owner': 'bob'}).status_code, 404)
            created = client.post('/api/factory/research/projects', json={'requestId': 'setup-http-project', 'title': 'Exact configured project'})
            self.assertEqual(created.status_code, 201, created.text)
            project_path = '/api/factory/research/projects/' + created.json()['id']
            execution = {'applicationRef': receipt['applicationRef'], 'mode': 'research',
                'connectionRefs': receipt['connectionRefs'], 'deadline': time.time() + 120,
                'perRoundCaps': {'rounds': 1, 'toolCalls': 8}}
            agreement = {'objective': 'Use configured resources', 'evaluation': 'Actual evidence',
                'stopConditions': 'Original budget', 'budget': {'rounds': 1, 'toolCalls': 8}, 'execution': execution}
            revision = client.post(project_path + '/goals', json={
                'requestId': 'setup-http-goal', 'expectedVersion': 0, 'agreement': agreement})
            self.assertEqual(revision.status_code, 200, revision.text)
            confirmed = client.post(project_path + '/confirm', json={'requestId': 'setup-http-confirm', 'expectedVersion': 1})
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            self.assertEqual(confirmed.json()['goals'][0]['agreement']['execution']['applicationRef'], receipt['applicationRef'])
            self.assertEqual(confirmed.json()['goals'][0]['agreement']['execution']['connectionRefs'], receipt['connectionRefs'])
            self.assertFalse(confirmed.json()['execution']['available'])
            self.assertEqual(self.apps.require_current(receipt['applicationRef'])['modes']['research']['nativeComponent'], self.pin)

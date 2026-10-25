"""Research agreement behavior with real local auth and owned SQLite metadata."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent_factory.assistant_endpoints import AssistantEndpoints, EndpointConfiguration
from research.projects import (Agreement, Budget, CreateProject, EndProject, ProjectCommand,
    ResearchProjects, ReviseGoal, projects_router)
import test_applications_composition as fixtures


def agreement(objective='Original research goal'):
    return Agreement(objective=objective, evaluation='Compare measured scores',
        stopConditions='Stop at the agreed threshold or resource budget',
        budget=Budget(rounds=3, toolCalls=12), resourceRefs={'model': 'existing-model-reference'})


class ResearchProjectsTests(fixtures.ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.endpoints = AssistantEndpoints(self.store, self.auth, self.applications)
        self.service = ResearchProjects(self.store, self.auth, self.endpoints)

    def project(self, owner='alice', key='project-original'):
        return self.service.create(owner, CreateProject(requestId=key, title='独立研究项目'))

    def test_project_receipt_restart_isolation_and_disabled_member(self):
        original = self.project()
        reopened = ResearchProjects(self.store, self.auth, self.endpoints)
        self.assertEqual(reopened.create('alice', CreateProject(requestId='project-original', title='独立研究项目')), original)
        with self.assertRaises(HTTPException) as conflict:
            reopened.create('alice', CreateProject(requestId='project-original', title='Changed title'))
        self.assertEqual(conflict.exception.status_code, 409)
        with self.assertRaises(HTTPException) as denied:
            reopened.read('bob', original['id'])
        self.assertEqual(denied.exception.status_code, 404)
        self.assertEqual(reopened.list('bob')['items'], [])
        self.auth.directory.set_disabled('alice', True)
        with self.assertRaises(HTTPException) as disabled:
            reopened.read('alice', original['id'])
        self.assertEqual(disabled.exception.status_code, 403)

    def test_goal_confirmation_revision_history_and_stale_write(self):
        project = self.project(); identifier = project['id']
        with self.assertRaises(HTTPException) as missing:
            self.service.change('alice', identifier, 'confirm', ProjectCommand(requestId='confirm-no-goal', expectedVersion=0))
        self.assertEqual(missing.exception.detail['code'], 'RESEARCH_AGREEMENT_REQUIRED')
        revision = ReviseGoal(requestId='goal-version-one', expectedVersion=0, agreement=agreement())
        first = self.service.change('alice', identifier, 'revise', revision)
        self.assertEqual(first['state'], 'draft')
        confirmed = self.service.change('alice', identifier, 'confirm', ProjectCommand(requestId='confirm-version-one', expectedVersion=1))
        self.assertEqual(confirmed['state'], 'ready')
        self.assertFalse(confirmed['execution']['available'])
        second = self.service.change('alice', identifier, 'revise', ReviseGoal(
            requestId='goal-version-two', expectedVersion=1, agreement=agreement('Revised research goal')))
        self.assertEqual(second['state'], 'draft')
        self.assertEqual(second['goals'][0], confirmed['goals'][0])
        self.assertIsNone(second['goals'][1]['confirmedAt'])
        self.assertEqual(second['goals'][0]['agreement']['budget'], second['goals'][1]['agreement']['budget'])
        with self.assertRaises(HTTPException) as stale:
            self.service.change('alice', identifier, 'confirm', ProjectCommand(requestId='confirm-stale-goal', expectedVersion=1))
        self.assertEqual(stale.exception.detail['code'], 'RESEARCH_GOAL_VERSION_CONFLICT')
        self.assertEqual(self.service.change('alice', identifier, 'revise', revision), first)
        self.assertEqual(self.service.read('alice', identifier), second)

    def test_not_met_end_preserves_reason_without_claiming_cleanup(self):
        identifier = self.project()['id']
        self.service.change('alice', identifier, 'revise', ReviseGoal(
            requestId='ending-goal-one', expectedVersion=0, agreement=agreement()))
        ending = EndProject(requestId='end-not-met-one', expectedVersion=1, outcome='not_met', reason='No evidence supports continuing within this budget')
        ended = self.service.change('alice', identifier, 'end', ending)
        self.assertEqual(ended['state'], 'ended')
        self.assertEqual(ended['ending']['resourceCleanup'], 'not_observed')
        self.assertEqual(ended['ending']['outcome'], 'not_met')
        self.assertEqual(len(ended['goals']), 1)
        self.assertEqual(self.service.change('alice', identifier, 'end', ending), ended)
        with self.assertRaises(HTTPException) as closed:
            self.service.change('alice', identifier, 'revise', ReviseGoal(
                requestId='closed-goal-two', expectedVersion=1, agreement=agreement('Must not overwrite')))
        self.assertEqual(closed.exception.detail['code'], 'RESEARCH_PROJECT_ENDED')

    def test_assistant_relation_requires_owner_and_project_can_exist_without_it(self):
        definition = self.publish()
        endpoint = self.endpoints.configure('alice', EndpointConfiguration(name='Alice assistant',
            applicationRef=fixtures.pin(definition), mode='literature'), 'alice-assistant-original')
        linked = self.service.create('alice', CreateProject(requestId='linked-project-one', title='Linked', assistantId=endpoint['id']))
        self.assertEqual(linked['assistantId'], endpoint['id'])
        with self.assertRaises(HTTPException) as denied:
            self.service.create('bob', CreateProject(requestId='foreign-assistant', title='Forbidden', assistantId=endpoint['id']))
        self.assertEqual(denied.exception.status_code, 404)
        self.assertIsNone(self.project('bob', 'bob-own-project')['assistantId'])

    def test_budget_validation_matches_metering_semantics_and_rejects_secret_fields(self):
        self.assertEqual(Budget(rounds=1, toolCalls=1).model_dump(),
            {'rounds': 1, 'toolCalls': 1, 'tokenLimit': None, 'amountMicros': None, 'currency': None})
        Budget(rounds=1, toolCalls=1, tokenLimit=0, amountMicros=0, currency='USD')
        for values in ({'tokenLimit': None, 'amountMicros': 3, 'currency': 'USD'},
                       {'tokenLimit': 10}, {'rounds': True}, {'toolCalls': 0}):
            with self.assertRaises(ValidationError):
                Budget.model_validate({'rounds': 1, 'toolCalls': 1, **values})
        with self.assertRaises(ValidationError):
            Agreement.model_validate({**agreement().model_dump(), 'apiKey': 'synthetic-canary'})

    def test_http_contract_exposes_no_placeholder_execution(self):
        # Only request identity injection is synthetic; service membership is real.
        api = FastAPI()
        @api.middleware('http')
        async def identity(request, call_next):
            request.state.authenticated = True
            request.state._agno_auth_complete = True
            request.state.user_id = request.headers.get('x-test-owner', 'alice')
            return await call_next(request)
        api.include_router(projects_router(self.auth, self.service))
        with TestClient(api) as client:
            created = client.post('/api/factory/research/projects', json={'requestId': 'http-project-one', 'title': 'HTTP项目'})
            self.assertEqual(created.status_code, 201, created.text)
            project = created.json()
            self.assertEqual(client.get('/api/factory/research/projects/' + project['id'], headers={'x-test-owner': 'bob'}).status_code, 404)
            goal = client.post('/api/factory/research/projects/' + project['id'] + '/goals',
                json={'requestId': 'http-goal-one', 'expectedVersion': 0, 'agreement': agreement().model_dump()})
            self.assertEqual(goal.status_code, 200, goal.text)
            confirmation = client.post('/api/factory/research/projects/' + project['id'] + '/confirm',
                json={'requestId': 'http-confirm-one', 'expectedVersion': 1})
            self.assertEqual(confirmation.status_code, 200, confirmation.text)
            self.assertFalse(confirmation.json()['execution']['available'])
            self.assertEqual(client.post('/api/factory/research/projects/' + project['id'] + '/start', json={}).status_code, 404)
            self.assertEqual(client.get('/api/factory/research/projects?limit=0').status_code, 422)
            self.assertEqual(client.post('/api/factory/research/projects', json={'requestId': 'http-bad-owner', 'title': 'X', 'ownerId': 'bob'}).status_code, 422)

"""Endpoint persistence/authority with native member storage; no model execution."""
from copy import deepcopy
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from agent_factory.assistant_endpoints import (
    AssistantEndpoints, EndpointConfiguration, assistant_endpoints_router,
)
from test_applications_composition import ApplicationCompositionFixture, app_definition, pin


class AssistantEndpointsTests(ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.service = AssistantEndpoints(self.store, self.auth, self.applications)
        self.application = self.publish()
        self.configuration = EndpointConfiguration(name='Alice assistant', applicationRef=pin(self.application),
            mode='literature', connectionRefs={'model': 'alice-private-model-reference'})

    def configure(self, owner='alice', key='endpoint-create-1'):
        return self.service.configure(owner, self.configuration, key)

    def test_restart_repeated_configuration_retains_identity_and_conflicts_do_not_rewrite(self):
        original = self.configure()
        self.store.engine.dispose()
        self.service = AssistantEndpoints(self.store, self.auth, self.applications)
        self.assertEqual(self.configure(), original)
        changed = self.configuration.model_copy(update={'name': 'Changed intent'})
        with self.assertRaises(HTTPException) as caught:
            self.service.configure('alice', changed, 'endpoint-create-1')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.service.owned('alice', original['id']), original)
        other = self.configure('bob')
        self.assertNotEqual(other['id'], original['id'])
        with self.service.db.read() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.service.endpoints)).scalar(), 2)

    def test_team_discovery_cannot_read_resources_or_change_owner_configuration(self):
        original = self.configure()
        visible = self.service.get('bob', original['id'])
        self.assertEqual(visible, self.service.list('bob')['items'][0])
        self.assertEqual(visible['ownerId'], 'alice')
        self.assertNotIn('defaults', visible)
        self.assertNotIn('alice-private-model-reference', str(visible))
        for action in (lambda: self.service.owned('bob', original['id']),
                       lambda: self.service.set_enabled('bob', original['id'], False, 'disable-owner-1')):
            with self.assertRaises(HTTPException) as caught:
                action()
            self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.service.owned('alice', original['id']), original)

    def test_disable_and_member_revocation_are_current_without_changing_original_receipt(self):
        original = self.configure()
        disabled = self.service.set_enabled('alice', original['id'], False, 'disable-owner-1')
        self.assertFalse(disabled['enabled'])
        self.assertEqual(self.service.set_enabled('alice', original['id'], False, 'disable-owner-1'), disabled)
        self.assertEqual(self.service.list('bob')['items'], [])
        self.assertFalse(self.service.get('alice', original['id'])['enabled'])
        with self.assertRaises(HTTPException):
            self.service.resolve(original['id'])
        self.assertEqual(self.configure(), original)
        self.assertFalse(self.service.owned('alice', original['id'])['enabled'])
        self.service.set_enabled('alice', original['id'], True, 'enable-owner-1')
        self.auth.directory.set_disabled('alice', True)
        self.assertEqual(self.service.list('bob')['items'], [])
        for action in (lambda: self.service.resolve(original['id']),
                       lambda: self.service.get('alice', original['id']),
                       lambda: self.service.set_enabled('alice', original['id'], False, 'disable-owner-2')):
            with self.assertRaises(HTTPException) as caught:
                action()
            self.assertEqual(caught.exception.status_code, 403)

    def test_exact_application_mode_and_withdrawal_checked_before_admission(self):
        for changes in ({'mode': 'missing'}, {'applicationRef': {**pin(self.application), 'sha256': '0' * 64}}):
            config = EndpointConfiguration.model_validate({**self.configuration.model_dump(), **changes})
            with self.assertRaises(HTTPException):
                self.service.configure('alice', config, 'invalid-endpoint-1')
        original = self.configure()
        before = deepcopy(original)
        resolved = self.service.resolve(original['id'])
        self.assertEqual(resolved['defaults']['applicationRef'], pin(self.application))
        self.applications.withdraw('manager', self.application['id'], 1, 'withdraw-app-1', 'Fixture withdrawal')
        with self.assertRaises(HTTPException):
            self.service.resolve(original['id'])
        self.assertEqual(self.service.owned('alice', original['id']), before)
        with self.assertRaises(HTTPException):
            self.service.configure('alice', self.configuration, 'new-endpoint-1')

    def test_discovery_pagination_and_directory_failures_are_not_swallowed(self):
        ids = {self.configure(key='endpoint-create-' + str(i))['id'] for i in range(3)}
        seen, after = [], ''
        while True:
            page = self.service.list('bob', after=after, limit=1)
            seen.extend(item['id'] for item in page['items'])
            if page['nextCursor'] is None:
                break
            after = page['nextCursor']
        self.assertEqual(set(seen), ids)
        self.assertEqual(len(seen), len(ids))
        member = self.auth.require_member
        def unavailable(owner):
            if owner == 'alice':
                raise HTTPException(503, 'Fixture directory unavailable')
            member(owner)
        with patch.object(self.auth, 'require_member', side_effect=unavailable):
            with self.assertRaises(HTTPException) as caught:
                self.service.list('bob')
        self.assertEqual(caught.exception.status_code, 503)

    def test_text_input_schema_accepts_goal_only_and_rejects_incompatible_modes(self):
        plain = self.configure()
        self.assertFalse(self.service.resolve(plain['id'])['textInput'])
        goal = {'type': 'string', 'maxLength': 100}
        cases = (
            ('required-goal', {'goal': goal}, ['goal'], True),
            ('optional-extra', {'goal': goal, 'note': goal}, ['goal'], True),
            ('required-extra', {'goal': goal, 'dataset': goal}, ['goal', 'dataset'], False),
            ('numeric-goal', {'goal': {'type': 'integer'}}, ['goal'], False),
            ('missing-goal', {'note': goal}, [], False),
        )
        for name, properties, required, accepted in cases:
            with self.subTest(schema=name):
                definition = app_definition(self.store, identifier='text-schema-' + name)
                definition['modes']['literature']['inputSchema'] = {
                    'type': 'object', 'additionalProperties': False,
                    'properties': properties, 'required': required}
                published = self.publish(definition)
                config = EndpointConfiguration.model_validate({**self.configuration.model_dump(),
                    'applicationRef': pin(published)})
                if accepted:
                    configured = self.service.configure('alice', config, 'schema-' + name)
                    self.assertTrue(self.service.resolve(configured['id'])['textInput'])
                    self.assertNotIn('textInput', self.service.get('bob', configured['id']))
                else:
                    with self.assertRaises(HTTPException) as caught:
                        self.service.configure('alice', config, 'schema-' + name)
                    self.assertEqual(caught.exception.status_code, 422)
                    self.assertEqual(caught.exception.detail, 'ASSISTANT_TEXT_INPUT_INCOMPATIBLE')

    def test_http_boundaries_reject_owner_secret_and_arbitrary_execution_overrides(self):
        app = FastAPI()
        @app.middleware('http')
        async def fixture_identity(request, call_next):
            request.state.authenticated = True
            request.state._agno_auth_complete = True
            request.state.user_id = request.headers.get('x-fixture-owner', 'alice')
            return await call_next(request)
        app.include_router(assistant_endpoints_router(self.auth, self.service))
        with TestClient(app) as client:
            body = {**self.configuration.model_dump(), 'requestId': 'http-endpoint-1'}
            for extra in ({'ownerId': 'bob'}, {'credentials': {'password': 'synthetic-canary'}},
                          {'inputValues': {'runTraining': True}}, {'goal': 'override'}, {'mode': 'missing'}):
                response = client.post('/api/factory/assistants', json={**body, **extra})
                self.assertEqual(response.status_code, 422, response.text)
            response = client.post('/api/factory/assistants', json={**body, 'name': 'password=synthetic-canary'})
            self.assertEqual(response.status_code, 422)
            created = client.post('/api/factory/assistants', json=body)
            self.assertEqual(created.status_code, 201, created.text)
            endpoint_id = created.json()['id']
            peer = client.get('/api/factory/assistants/' + endpoint_id, headers={'x-fixture-owner': 'bob'})
            self.assertNotIn('connectionRefs', peer.text)
            denied = client.post('/api/factory/assistants/' + endpoint_id + '/state',
                headers={'x-fixture-owner': 'bob'}, json={'requestId': 'http-disable-1', 'enabled': False})
            self.assertEqual(denied.status_code, 404)
            self.assertEqual(client.get('/api/factory/assistants?limit=0').status_code, 422)
            self.assertEqual(client.get('/api/factory/assistants?limit=101').status_code, 422)

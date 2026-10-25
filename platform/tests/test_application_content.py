"""Portable authorization/transaction tests; artifact execution is tested on PostgreSQL."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, String, Table, func, select

from agent_factory.application_content import ApplicationContent, ContentPublication, application_content_router
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from test_applications_composition import ApplicationCompositionFixture


class ApplicationContentTests(ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.sharing = ResourceSharing(self.store, self.auth)
        self.service = ApplicationContent(self.store, self.auth, self.sharing)
        self.body = ContentPublication(source={'application': 'research', 'record': 'experiment-1', 'revision': '1'},
            content={'state': 'negative-result', 'analysis': 'Agent interpretation'}, visibility='team')

    def publish(self, key='publication-1'):
        return self.service.publish('alice', self.body, key)

    def test_snapshot_restart_and_conflict_do_not_mutate_original(self):
        original = self.publish()
        self.service = ApplicationContent(self.store, self.auth, self.sharing)
        self.assertEqual(self.publish(), original)
        self.assertEqual(original['verificationStatus'], 'unverified')
        changed = self.body.model_copy(update={'content': {'state': 'success'}})
        with self.assertRaises(HTTPException) as caught:
            self.service.publish('alice', changed, 'publication-1')
        self.assertEqual(caught.exception.status_code, 409)
        peer = self.service.read('bob', original['id'])
        self.assertFalse(peer['isOwner'])
        peer['content']['state'] = 'overwritten locally'
        self.assertEqual(self.service.read('alice', original['id'])['content'], self.body.content)
        with self.assertRaises(HTTPException):
            self.service.set_visibility('bob', original['id'], 'personal', 'peer-mutation')

    def test_revoke_and_replay_never_restore_access_and_membership_is_current(self):
        original = self.publish()
        self.service.set_visibility('alice', original['id'], 'team', 'explicit-share')
        self.service.set_visibility('alice', original['id'], 'personal', 'revoke-share')
        self.assertEqual(self.publish()['visibility'], 'personal')
        self.assertEqual(self.service.set_visibility('alice', original['id'], 'team', 'explicit-share')['visibility'], 'personal')
        self.assertEqual(self.service.list('bob')['items'], [])
        with self.assertRaises(HTTPException):
            self.service.read('bob', original['id'])
        self.service.set_visibility('alice', original['id'], 'team', 'reshare-content')
        for owner in ('alice', 'bob'):
            self.auth.directory.set_disabled(owner, True)
            with self.assertRaises(HTTPException):
                self.service.read('bob', original['id'])
            self.auth.directory.set_disabled(owner, False)

    def test_domain_revision_and_publication_rollback_then_retry_together(self):
        metadata = MetaData()
        domain = Table('fixture_domain_revision', metadata, Column('id', String, primary_key=True))
        metadata.create_all(self.store.engine)
        with self.assertRaisesRegex(RuntimeError, 'fixture rollback'):
            with Store.transaction(self.store) as conn:
                conn.execute(domain.insert().values(id='revision-1'))
                self.publish()
                raise RuntimeError('fixture rollback')
        with self.store.engine.connect() as conn:
            for table in (domain, self.service.contents, self.service.commands, self.sharing.resources):
                self.assertEqual(conn.execute(select(func.count()).select_from(table)).scalar(), 0)
        with Store.transaction(self.store) as conn:
            conn.execute(domain.insert().values(id='revision-1'))
            published = self.publish()
        self.assertEqual(self.publish()['id'], published['id'])
        self.assertEqual(len(self.service.list('bob')['items']), 1)

    def test_http_rejects_impersonation_verification_secrets_and_unbounded_payload(self):
        app = FastAPI()
        @app.middleware('http')
        async def fixture_identity(request, call_next):
            request.state.authenticated = True
            request.state._agno_auth_complete = True
            request.state.user_id = 'alice'
            return await call_next(request)
        app.include_router(application_content_router(self.auth, self.service))
        with TestClient(app) as client:
            body = {**self.body.model_dump(), 'requestId': 'http-content-1'}
            for extra in ({'ownerId': 'bob'}, {'verificationStatus': 'verified'},
                          {'content': {'password': 'synthetic-secret'}}, {'content': {'text': 'x' * 17000}},
                          {'artifacts': [{'path': '/tmp/private-file'}]}):
                response = client.post('/api/factory/application-content', json={**body, **extra})
                self.assertEqual(response.status_code, 422, response.text)
            response = client.post('/api/factory/application-content', json=body)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(client.get('/api/factory/application-content?limit=0').status_code, 422)

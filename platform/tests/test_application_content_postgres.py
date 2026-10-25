"""Real native checksum artifacts and same-transaction publication on PostgreSQL."""
import os
import unittest

from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table, func, select

from agent_factory.application_content import ContentPublication
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ApplicationContentPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.prefix = '/api/factory/application-content'

    def test_exact_owned_artifact_shared_without_job_access_then_revoked_after_restart(self):
        fixture = self.fixture
        app = fixture.publish_http()
        fixture.login('alice')
        started = fixture.client.post('/api/factory/application-interface/v1/starts', json={
            'application': app['id'], 'applicationRef': fixtures.pin(app), 'mode': 'literature',
            'goal': 'Perform a text audit for original synthetic evidence', 'requestId': 'content-native-start'})
        self.assertEqual(started.status_code, 202, started.text)
        detail = fixture.wait_job(started.json()['job']['id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)
        task_id = detail['job']['id']
        original = detail['artifacts'][0]
        unshared = fixture.store.artifact_write(task_id, 'private.txt', b'private fixture')
        reference = {'taskId': task_id, 'artifactId': original['id'], 'sha256': original['sha256']}
        body = {'source': {'application': 'research', 'record': 'experiment-1', 'revision': '1'},
            'content': {'result': 'synthetic checksum evidence'}, 'artifacts': [reference],
            'visibility': 'team', 'requestId': 'content-native-publish'}
        bad = fixture.client.post(self.prefix, json={**body, 'artifacts': [{**reference, 'sha256': '0' * 64}]})
        self.assertEqual(bad.status_code, 409, bad.text)
        published = fixture.client.post(self.prefix, json=body)
        self.assertEqual(published.status_code, 201, published.text)
        identifier = published.json()['id']
        fixture.login('bob')
        stolen = fixture.client.post(self.prefix, json={**body, 'requestId': 'bob-forged-artifact'})
        self.assertEqual(stolen.status_code, 404, stolen.text)
        url = self.prefix + '/' + identifier
        self.assertEqual(fixture.client.get(url).status_code, 200)
        downloaded = fixture.client.get(url + '/artifacts/' + original['id'])
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, fixture.store.artifact(task_id, original['id'])[1])
        self.assertEqual(downloaded.headers['cache-control'], 'private, no-store')
        self.assertTrue(downloaded.headers['content-disposition'].startswith('attachment;'))
        self.assertEqual(fixture.client.get(url + '/artifacts/' + unshared['id']).status_code, 404)
        self.assertEqual(fixture.client.get('/api/factory/jobs/' + task_id).status_code, 404)
        self.assertEqual(fixture.client.get('/api/factory/jobs/' + task_id + '/artifacts/' + original['id']).status_code, 404)
        service = fixture.state['application_content']
        service.set_visibility('alice', identifier, 'personal', 'content-native-revoke')
        fixture.stop(); fixture.start(); fixture.login('alice')
        replay = fixture.client.post(self.prefix, json=body)
        self.assertEqual(replay.json()['id'], identifier)
        self.assertEqual(replay.json()['visibility'], 'personal')
        fixture.login('bob')
        self.assertEqual(fixture.client.get(url + '/artifacts/' + original['id']).status_code, 404)
        service = fixture.state['application_content']
        service.set_visibility('alice', identifier, 'team', 'content-native-reshare')
        fixture.store.sql('UPDATE af_artifacts SET content=:raw WHERE id=:id', raw=b'tampered', id=original['id'])
        self.assertEqual(fixture.client.get(url + '/artifacts/' + original['id']).status_code, 409)
        fixture.store.sql('DELETE FROM af_artifacts WHERE id=:id', id=original['id'])
        self.assertEqual(fixture.client.get(url + '/artifacts/' + original['id']).status_code, 404)

    def test_domain_publication_visibility_and_receipt_are_one_transaction(self):
        fixture = self.fixture
        service = fixture.state['application_content']
        metadata = MetaData()
        domain = Table('fixture_domain_revision', metadata, Column('id', String, primary_key=True))
        metadata.create_all(fixture.store.engine)
        body = ContentPublication(source={'application': 'research', 'record': 'experiment-1', 'revision': '1'},
            content={'result': 'negative'}, visibility='team')
        with self.assertRaisesRegex(RuntimeError, 'rollback publication'):
            with fixture.store.transaction() as conn:
                conn.execute(domain.insert().values(id='revision-1'))
                publication = service.publish('alice', body, 'pg-content-atomic')
                with fixture.store.engine.connect() as observer:
                    self.assertEqual(observer.execute(select(func.count()).select_from(domain)).scalar(), 0)
                    self.assertEqual(observer.execute(select(func.count()).select_from(service.contents)).scalar(), 0)
                raise RuntimeError('rollback publication')
        with self.assertRaises(HTTPException):
            service.read('bob', publication['id'])
        with fixture.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(service.commands)).scalar(), 0)
        with fixture.store.transaction() as conn:
            conn.execute(domain.insert().values(id='revision-1'))
            committed = service.publish('alice', body, 'pg-content-atomic')
        self.assertEqual(service.publish('alice', body, 'pg-content-atomic')['id'], committed['id'])
        self.assertEqual(service.read('bob', committed['id'])['content'], {'result': 'negative'})

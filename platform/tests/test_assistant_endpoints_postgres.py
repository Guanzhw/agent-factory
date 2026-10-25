"""Wired endpoint HTTP and concurrent metadata receipts on isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest

from fastapi import HTTPException
from sqlalchemy import func, select

from agent_factory.assistant_endpoints import EndpointConfiguration
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AssistantEndpointsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.definition = self.fixture.publish_http()
        self.config = EndpointConfiguration(name='Stable fixture assistant',
            applicationRef=fixtures.pin(self.definition), mode='literature',
            connectionRefs={'model': 'alice-private-reference'})
        self.prefix = '/api/factory/assistants'

    def test_http_restart_owner_isolation_and_withdrawn_application(self):
        fixture = self.fixture
        fixture.login('alice')
        body = {**self.config.model_dump(), 'requestId': 'pg-endpoint-create'}
        created = fixture.client.post(self.prefix, json=body)
        self.assertEqual(created.status_code, 201, created.text)
        original = created.json()
        fixture.stop(); fixture.start(); fixture.login('alice')
        repeated = fixture.client.post(self.prefix, json=body)
        self.assertEqual(repeated.status_code, 201, repeated.text)
        self.assertEqual(repeated.json(), original)
        conflict = fixture.client.post(self.prefix, json={**body, 'name': 'Changed configuration'})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        fixture.login('bob')
        summary = fixture.client.get(self.prefix + '/' + original['id'])
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertNotIn('defaults', summary.json())
        self.assertNotIn('alice-private-reference', summary.text)
        denied = fixture.client.post(self.prefix + '/' + original['id'] + '/state',
            json={'requestId': 'pg-peer-disable', 'enabled': False})
        self.assertEqual(denied.status_code, 404, denied.text)
        fixture.apps.withdraw('manager', self.definition['id'], 1, 'pg-withdraw-app')
        with self.assertRaises(HTTPException) as caught:
            fixture.state['assistant_endpoints'].resolve(original['id'])
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(fixture.state['assistant_endpoints'].owned('alice', original['id']), original)
        fixture.login('alice')
        rejected = fixture.client.post(self.prefix, json={**body, 'requestId': 'pg-new-endpoint'})
        self.assertEqual(rejected.status_code, 409, rejected.text)

    def test_concurrent_duplicate_configuration_has_one_identity_and_disable_survives_restart(self):
        fixture = self.fixture
        service = fixture.state['assistant_endpoints']
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: service.configure('alice', self.config, 'pg-concurrent-config'), range(3)))
        self.assertTrue(all(item == results[0] for item in results))
        with service.db.read() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(service.endpoints)).scalar(), 1)
        endpoint_id = results[0]['id']
        service.set_enabled('alice', endpoint_id, False, 'pg-disable-endpoint')
        fixture.stop(); fixture.start()
        service = fixture.state['assistant_endpoints']
        self.assertFalse(service.owned('alice', endpoint_id)['enabled'])
        self.assertEqual(service.list('bob')['items'], [])
        with self.assertRaises(HTTPException):
            service.resolve(endpoint_id)
        self.assertEqual(service.configure('alice', self.config, 'pg-concurrent-config'), results[0])
        self.assertFalse(service.owned('alice', endpoint_id)['enabled'])

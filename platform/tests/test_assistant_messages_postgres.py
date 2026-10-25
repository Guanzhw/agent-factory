"""Actual native queue and PostgreSQL message receipts; synthetic model only."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest
from unittest.mock import AsyncMock, patch

from agent_factory.assistant_endpoints import EndpointConfiguration
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AssistantMessagesPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        definition = self.fixture.publish_http()
        endpoint = self.fixture.state['assistant_endpoints'].configure('bob', EndpointConfiguration(
            name='Bob synthetic assistant', applicationRef=fixtures.pin(definition), mode='literature'), 'message-endpoint')
        self.endpoint_id = endpoint['id']
        self.path = '/api/factory/assistants/' + self.endpoint_id + '/messages'
        self.body = {'requestId': 'message-native-001', 'text': 'Summarize the synthetic checksum evidence.'}
        self.fixture.login('alice')

    def test_concurrent_messages_use_one_recipient_native_task_and_private_receipts(self):
        fixture = self.fixture
        submit = AsyncMock(wraps=fixture.state['bridge'].submit)
        with patch.object(fixture.state['bridge'], 'submit', submit):
            with ThreadPoolExecutor(max_workers=3) as pool:
                replies = list(pool.map(lambda _: fixture.client.post(self.path, json=self.body), range(3)))
            for reply in replies:
                self.assertEqual(reply.status_code, 202, reply.text)
            identifiers = {reply.json()['id'] for reply in replies}
            self.assertEqual(len(identifiers), 1)
            self.assertEqual(submit.await_count, 1)
        receipt_path = '/api/factory/assistant-message-requests/' + self.body['requestId']
        receipt = fixture.client.get(receipt_path)
        self.assertEqual(receipt.status_code, 200, receipt.text)
        value = receipt.json()
        task_id = value['delivery']['taskId']
        self.assertEqual(fixture.store.task(task_id)['owner_id'], 'bob')
        self.assertEqual(fixture.client.get('/api/factory/jobs/' + task_id).status_code, 404)
        self.assertNotIn('handoff', value); self.assertNotIn('planId', value)
        fixture.login('manager')
        self.assertEqual(fixture.client.get('/api/factory/assistant-messages/' + value['id']).status_code, 404)
        fixture.login('bob')
        self.assertEqual(fixture.client.get('/api/factory/assistant-messages/' + value['id']).status_code, 200)
        detail = fixture.wait_job(task_id)
        self.assertEqual(detail['job']['status'], 'completed', detail)
        self.assertTrue(detail['artifacts'])

    def test_lost_native_ack_restart_and_endpoint_disable_do_not_replay(self):
        fixture = self.fixture
        submit = AsyncMock(side_effect=TimeoutError('synthetic unconfirmed native acknowledgement'))
        with patch.object(fixture.state['bridge'], 'submit', submit):
            first = fixture.client.post(self.path, json=self.body)
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(first.json()['delivery']['state'], 'unknown')
            self.assertEqual(submit.await_count, 1)
        original = first.json()
        task_id = original['delivery']['taskId']
        fixture.state['assistant_endpoints'].set_enabled('bob', self.endpoint_id, False, 'stop-message-intake')
        fixture.stop(); fixture.start(); fixture.login('alice')
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock()) as after_restart:
            repeated = fixture.client.post(self.path, json=self.body)
            self.assertEqual(repeated.status_code, 202, repeated.text)
            self.assertEqual(repeated.json(), original)
            self.assertEqual(after_restart.await_count, 0)
            changed = fixture.client.post(self.path, json={**self.body, 'text': 'Different original intent'})
            self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual([task['id'] for task in fixture.store.tasks('bob')], [task_id])

    def test_required_goal_schema_reaches_original_native_plan(self):
        fixture = self.fixture
        definition = fixtures.app_definition(fixture.store, identifier='message-schema-fixture')
        definition['modes']['literature']['inputSchema'] = {
            'type': 'object', 'additionalProperties': False, 'required': ['goal'],
            'properties': {'goal': {'type': 'string', 'minLength': 2, 'maxLength': 100}}}
        draft = fixture.apps.create_draft('manager', definition, 'message-schema-draft')
        fixture.apps.publish('manager', draft['id'], draft['version'], 'message-schema-publish')
        endpoint = fixture.state['assistant_endpoints'].configure('bob', EndpointConfiguration(
            name='Bob schema assistant', applicationRef=fixtures.pin(draft), mode='literature'), 'schema-endpoint')
        path = '/api/factory/assistants/' + endpoint['id'] + '/messages'
        response = fixture.client.post(path, json=self.body)
        self.assertEqual(response.status_code, 202, response.text)
        task_id = response.json()['delivery']['taskId']
        task = fixture.store.task(task_id, 'bob')
        self.assertEqual(fixture.store.plan(task['plan_id'], 'bob')['inputValues'], {'goal': self.body['text']})
        fixture.login('bob')
        detail = fixture.wait_job(task_id)
        self.assertEqual(detail['job']['status'], 'completed', detail)

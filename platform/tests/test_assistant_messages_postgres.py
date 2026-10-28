"""Actual native queue and PostgreSQL message receipts; synthetic model only."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import os
from threading import Event
import unittest
from unittest.mock import AsyncMock, patch

from agent_factory.assistant_endpoints import EndpointConfiguration
from agent_factory.assistant_messages import SendAssistantMessage
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
            messages = fixture.state['assistant_messages']
            recovered = fixture.client.portal.call(partial(messages.recover, 'bob', original['id']))
            self.assertEqual(recovered, original)
            after_restart.assert_not_called()
            changed = fixture.client.post(self.path, json={**self.body, 'text': 'Different original intent'})
            self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual([task['id'] for task in fixture.store.tasks('bob')], [task_id])

    def assert_unbudgeted_revocation_before_admission(self, revoke, expected_status):
        fixture = self.fixture
        runs = fixture.state['assistant_messages'].runs
        original = runs._prepare
        prepared, resume = Event(), Event()

        def pause(*args):
            result = original(*args)
            prepared.set()
            if not resume.wait(10):
                raise TimeoutError('message preparation barrier was not released')
            return result

        with patch.object(runs, '_prepare', pause), \
                patch.object(fixture.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('synthetic ack'))) as submit:
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(fixture.client.post, self.path, json=self.body)
                try:
                    self.assertTrue(prepared.wait(10))
                    revoke()
                finally:
                    resume.set()
                result = response.result(timeout=15)
            self.assertEqual(result.status_code, expected_status, result.text)
            submit.assert_not_called()
        self.assertEqual(fixture.store.tasks('bob'), [])
        self.assertEqual(len(fixture.store.sql('SELECT id FROM af_assistant_messages')), 1)

    def test_unbudgeted_endpoint_disable_after_prepare_blocks_new_task(self):
        self.assert_unbudgeted_revocation_before_admission(lambda:
            self.fixture.state['assistant_endpoints'].set_enabled('bob', self.endpoint_id, False, 'race-disable'), 409)

    def test_unbudgeted_sender_disable_after_prepare_blocks_new_task(self):
        self.assert_unbudgeted_revocation_before_admission(lambda:
            self.fixture.auth.directory.set_disabled('alice', True), 403)

    def test_unbudgeted_prepared_request_requires_original_plan_and_full_fingerprint(self):
        fixture = self.fixture
        messages = fixture.state['assistant_messages']
        message, _ = messages.reserve('alice', self.endpoint_id, SendAssistantMessage.model_validate(self.body))
        endpoint = messages.endpoints.resolve(self.endpoint_id)
        body = messages._start_body(message, endpoint)
        plan, request_id = messages.runs._prepare('bob', body)
        other, _ = messages.runs._prepare('bob', body.model_copy(update={'requestId': 'other-plan', 'goal': 'Other goal'}))
        fixture.login('bob')
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('synthetic ack'))) as submit:
            response = fixture.client.post('/api/factory/instances', json={'planId': other['id'], 'requestId': request_id})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['message'], 'ASSISTANT_MESSAGE_ADMISSION_MISMATCH')
            # Simulate a stored prepared request whose full inputs differ even though its plan ID matches.
            fixture.store.sql('UPDATE af_plan_requests SET fingerprint=:fingerprint WHERE owner_id=:owner AND request_id=:request',
                fingerprint='0' * 64, owner='bob', request=request_id)
            response = fixture.client.post('/api/factory/instances', json={'planId': plan['id'], 'requestId': request_id})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['message'], 'ASSISTANT_MESSAGE_ADMISSION_MISMATCH')
            submit.assert_not_called()
        self.assertEqual(fixture.store.tasks('bob'), [])

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

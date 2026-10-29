"""Private receiver budgets on real PG/native admission; synthetic model only."""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import func, select, text

from agent_factory.assistant_endpoints import AutomaticBudget, EndpointConfiguration
from agent_factory.assistant_events import ContentEvent, EventSubscription
from agent_factory.assistant_messages import SendAssistantMessage
from agent_factory.application_content import ContentPublication
from agent_factory.store import digest
import test_assistant_messages_postgres as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL/native queue')
class PrivateMessageBudgetPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.AssistantMessagesPostgresTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.fixture = self.base.fixture
        self.store = self.fixture.store
        self.messages = self.fixture.state['assistant_messages']
        self.endpoints = self.fixture.state['assistant_endpoints']
        self.scopes = self.store.local_budget_scopes
        self.caps = dict(rounds=1, toolCalls=10, tokenLimit=None, amountMicros=None, currency=None)
        self.deadline = time.time() + 120
        self.scopes.create_scope('bob', 'private-qa', digest({'test': 'private-qa'}),
            {**self.caps, 'rounds': 4, 'toolCalls': 40}, self.deadline)
        original = self.endpoints.owned('bob', self.base.endpoint_id)
        self.configuration = EndpointConfiguration(name='Bounded private QA',
            applicationRef=original['applicationRef'], mode=original['mode'],
            automaticBudget=AutomaticBudget(scopeId='private-qa', caps=self.caps, deadline=self.deadline))
        self.endpoint = self.endpoints.configure('bob', self.configuration, 'private-budget-endpoint')
        self.path = '/api/factory/assistants/' + self.endpoint['id'] + '/messages'
        self.body = SendAssistantMessage.model_validate(self.base.body)

    def reserve(self):
        return self.messages.reserve('alice', self.endpoint['id'], self.body)[0]

    def count(self, table):
        with self.store.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(table)).scalar_one()

    def test_concurrent_private_send_has_one_budget_and_original_input(self):
        bridge = self.fixture.state['bridge']
        with patch.object(bridge, 'submit', AsyncMock(wraps=bridge.submit)) as submit:
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda _: self.fixture.client.post(self.path, json=self.body.model_dump()), range(2)))
            for reply in replies:
                self.assertEqual(reply.status_code, 202, reply.text)
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.count(self.scopes.allocations), 1)
        self.assertEqual(self.count(self.fixture.state['application_content'].contents), 0)
        value = self.messages.read('alice', replies[0].json()['id'])
        task_id = value['delivery']['taskId']
        original = self.messages.message_for_task('bob', task_id)
        self.assertEqual(original['text'], self.body.text)
        self.assertEqual(original['messageId'], value['id'])
        self.assertEqual(original['senderId'], 'alice')
        with self.assertRaises(HTTPException):
            self.messages.message_for_task('alice', task_id)
        with self.assertRaises(HTTPException):
            self.messages.read('manager', value['id'])

    def test_prepare_crash_recovers_original_budget_and_existing_task_stays_read_only(self):
        message = self.reserve()
        self.assertEqual(self.messages.read('alice', message['id'])['delivery']['state'], 'unconfirmed')
        with self.store.transaction() as conn:
            allocation = self.scopes.request_allocation(conn, 'bob', 'application-start:' + self.messages._request_id(message))
        self.assertIsNotNone(allocation)
        bridge = self.fixture.state['bridge']
        with patch.object(bridge, 'submit', AsyncMock(wraps=bridge.submit)) as submit:
            first = self.fixture.client.portal.call(partial(self.messages.recover, 'bob', message['id']))
            self.endpoints.set_enabled('bob', self.endpoint['id'], False, 'disable-after-admission')
            second = self.fixture.client.portal.call(partial(self.messages.recover, 'bob', message['id']))
            self.assertEqual(first['delivery']['taskId'], second['delivery']['taskId'])
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.count(self.scopes.allocations), 1)

    def test_rollback_leaves_no_message_or_allocation(self):
        original = self.scopes.bind_request
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Synthetic rollback after original mapping')
        with patch.object(self.scopes, 'bind_request', fail), self.assertRaises(RuntimeError):
            self.reserve()
        self.assertEqual(self.count(self.messages.messages), 0)
        self.assertEqual(self.count(self.scopes.allocations), 0)
        self.assertEqual(self.count(self.scopes.requests), 0)

    def test_fresh_public_handoff_cannot_bypass_disabled_endpoint(self):
        message = self.reserve()
        body = self.messages._start_body(message, self.endpoints.resolve(self.endpoint['id']))
        plan, key = self.messages.runs._prepare('bob', body)
        self.endpoints.set_enabled('bob', self.endpoint['id'], False, 'disable-before-reserve')
        self.fixture.login('bob')
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            reply = self.fixture.client.post('/api/factory/instances', json={'planId': plan['id'], 'requestId': key})
            self.assertEqual(reply.status_code, 409, reply.text)
            submit.assert_not_awaited()
        self.assertEqual(self.store.tasks('bob'), [])

    def test_complete_request_fingerprint_rejects_changed_binding_fields(self):
        message = self.reserve()
        body = self.messages._start_body(message, self.endpoints.resolve(self.endpoint['id']))
        plan, key = self.messages.runs._prepare('bob', body)
        expected = body.model_dump(exclude={'interfaceVersion', 'requestId'})
        self.fixture.login('bob')
        # Inject a persisted prepared-request mismatch while retaining the same
        # valid immutable plan: the fresh gate must check the entire request.
        for field, changed in (('connectionRefs', {'model': 'other-owner-ref'}),
                               ('materialChoices', {'model': {'id': 'other', 'version': 1, 'sha256': 'a' * 64}}),
                               ('inputValues', {'goal': body.goal, 'extra': 'changed'})):
            with self.subTest(field=field), self.store.transaction() as conn:
                conn.execute(text('UPDATE af_plan_requests SET fingerprint=:fp WHERE owner_id=:owner AND request_id=:key'),
                    {'fp': digest({**expected, field: changed}), 'owner': 'bob', 'key': key})
            with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
                reply = self.fixture.client.post('/api/factory/instances', json={'planId': plan['id'], 'requestId': key})
                self.assertEqual(reply.status_code, 409, reply.text)
                self.assertIn('ASSISTANT_MESSAGE_ADMISSION_MISMATCH', reply.text)
                submit.assert_not_awaited()
        self.assertEqual(self.store.tasks('bob'), [])

    def test_p3_reuses_one_receiver_allocation(self):
        events = self.fixture.state['assistant_events']
        content = self.fixture.state['application_content']
        publication = content.publish('alice', ContentPublication(source={
            'application': 'fixture', 'record': 'original', 'revision': '1'},
            content={'result': 'synthetic evidence'}, visibility='team'), 'event-content')
        events.configure('bob', EventSubscription(endpointId=self.endpoint['id'], namespace='fixture',
            eventType='evidence', scopeId='private-qa', caps=self.caps, deadline=self.deadline,
            maxDepth=1, maxCandidates=1), 'private-subscription')
        with self.store.transaction() as conn:
            event = events.emit(conn, 'alice', ContentEvent(namespace='fixture', eventType='evidence',
                contentId=publication['id'], candidates=[self.endpoint['id']], deadline=self.deadline), 'private-event')
        delivery = events.prepare(event['id'], self.endpoint['id'])
        self.assertEqual(self.count(self.scopes.allocations), 1)
        message = self.messages.read('bob', delivery['message_id'])
        with self.store.transaction() as conn:
            self.assertEqual(self.scopes.request_allocation(conn, 'bob',
                'application-start:assistant-message:' + message['id']), delivery['allocation_id'])
        self.assertEqual(events.prepare(event['id'], self.endpoint['id'])['id'], delivery['id'])
        self.assertEqual(self.count(self.scopes.allocations), 1)

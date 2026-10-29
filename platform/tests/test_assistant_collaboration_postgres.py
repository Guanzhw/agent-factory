"""Private event routing on real PostgreSQL/native admission; scripted model only."""
import asyncio
from functools import partial
import os
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy import func, select

from agent_factory.application_interface import ApplicationStart
from agent_factory.assistant_endpoints import AutomaticBudget, EndpointConfiguration
from agent_factory.assistant_events import AssistantEvents
from agent_factory.assistant_messages import SendAssistantMessage
from agent_factory.store import digest
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class AssistantCollaborationPostgresTests(unittest.TestCase):
    def setUp(self):
        self.deliver_batch = AssistantEvents.deliver_batch
        worker = patch.object(AssistantEvents, 'deliver_batch', AsyncMock(return_value=(0, 0)))
        worker.start()
        self.addCleanup(worker.stop)
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.definition = self.fixture.publish_http()
        self.bind()
        self.origin_body = ApplicationStart(requestId='private-origin-task',
            application=self.definition['id'], applicationRef=fixtures.pin(self.definition),
            mode='literature', goal='Original synthetic private collaboration task.')
        started = self.call(self.messages.runs.start, 'alice', self.origin_body)
        self.origin_id = started['job']['id']
        self.fixture.login('alice')
        self.assertEqual(self.fixture.wait_job(self.origin_id)['job']['status'], 'completed')
        caps = dict(rounds=1, toolCalls=10, tokenLimit=None, amountMicros=None, currency=None)
        deadline = time.time() + 300
        self.scopes.create_scope('bob', 'private-event-budget', digest({'fixture': 'receiver commitment'}),
            {**caps, 'rounds': 4, 'toolCalls': 40}, deadline)
        self.endpoint = self.fixture.state['assistant_endpoints'].configure('bob', EndpointConfiguration(
            name='Private synthetic receiver', applicationRef=fixtures.pin(self.definition), mode='literature',
            automaticBudget=AutomaticBudget(scopeId='private-event-budget', caps=caps, deadline=deadline)),
            'private-event-endpoint')

    def bind(self):
        self.store = self.fixture.store
        self.service = self.fixture.state['assistant_events']
        self.messages = self.service.messages
        self.scopes = self.store.local_budget_scopes
        self.hooks = SimpleNamespace(deliver_collaboration=AsyncMock(return_value=False),
            validate_collaboration_admission=Mock())
        self.store.application_runtime.register('private-event-fixture', self.hooks,
            applications=[(self.definition['id'], self.definition['version'])])

    def call(self, function, *args, **kwargs):
        return self.fixture.client.portal.call(partial(function, *args, **kwargs))

    def reserve(self, request_id='private-question-001'):
        with self.store.transaction() as conn:
            message, _ = self.messages.reserve('alice', self.endpoint['id'], SendAssistantMessage(
                requestId=request_id, text='Only this synthetic question is shared.'))
            event = self.service.emit_collaboration(conn, 'alice', message['id'], self.origin_id)
        return message, event

    def deliver(self):
        return self.call(self.deliver_batch, self.service)

    def count(self, table):
        with self.store.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(table)).scalar_one()

    def test_same_transaction_rollback_identity_and_owner_only_metadata(self):
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.store.transaction():
                self.reserve()
                raise RuntimeError('rollback')
        for table in (self.service.events, self.messages.messages, self.scopes.allocations):
            self.assertEqual(self.count(table), 0)
        message, event = self.reserve()
        self.assertEqual(self.reserve()[1]['id'], event['id'])
        self.assertEqual(event['body'], {'kind': 'private-collaboration',
            'messageId': message['id'], 'originTaskId': self.origin_id})
        self.assertEqual(self.count(self.fixture.state['application_content'].contents), 0)
        self.assertEqual(self.count(self.service.deliveries), 0)
        for actor in ('bob', 'manager'):
            with self.assertRaises(HTTPException) as caught:
                self.service.event(actor, event['id'])
            self.assertEqual(caught.exception.status_code, 404)
        with self.store.transaction() as conn, self.assertRaises(HTTPException):
            self.service.emit_collaboration(conn, 'bob', message['id'], self.origin_id)
        with self.store.engine.connect() as conn, self.assertRaises(RuntimeError):
            self.service.emit_collaboration(conn, 'alice', message['id'], self.origin_id)
        with self.assertRaises(HTTPException):
            self.service.prepare(event['id'], self.endpoint['id'])

    def test_committed_message_survives_restart_and_original_budget_is_recovered_once(self):
        message, event = self.reserve()
        original = self.messages.read('alice', message['id'])
        self.assertIsNone(original['delivery']['taskId'])
        with self.store.transaction() as conn:
            allocation = self.scopes.request_allocation(conn, 'bob',
                'application-start:' + self.messages._request_id(message))
        self.fixture.stop()
        self.fixture.start()
        self.bind()
        bridge = self.fixture.state['bridge']
        with patch.object(bridge, 'submit', AsyncMock(wraps=bridge.submit)) as submit:
            self.deliver()
            self.deliver()
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.count(self.scopes.allocations), 1)
        receipt = self.messages.read('alice', message['id'])
        task = self.store.task(receipt['delivery']['taskId'], 'bob')
        with self.store.transaction() as conn:
            self.assertEqual(self.scopes._allocation(conn, 'bob', allocation)['task_id'], task['id'])
        self.assertFalse(self.service.event('alice', event['id'])['scanned'])
        self.fixture.login('bob')
        self.assertEqual(self.fixture.wait_job(task['id'])['job']['status'], 'completed')
        self.messages.reply_for_task('bob', task['id'], 'Synthetic private answer; no publication.')
        self.hooks.deliver_collaboration.return_value = True
        self.deliver()
        self.assertTrue(self.service.event('alice', event['id'])['scanned'])
        self.hooks.deliver_collaboration.assert_awaited_with(self.store,
            self.store.task(self.origin_id, 'alice'), event['id'], message['id'])
        calls = self.hooks.deliver_collaboration.await_count
        self.deliver()
        self.assertEqual(self.hooks.deliver_collaboration.await_count, calls)
        self.assertEqual(self.count(self.fixture.state['application_content'].contents), 0)
        self.assertEqual(self.count(self.service.deliveries), 0)

    def test_missing_handler_and_handler_error_stay_pending_and_other_event_progresses(self):
        _, first = self.reserve()
        _, second = self.reserve('private-question-002')
        del self.hooks.deliver_collaboration
        self.deliver()
        self.assertFalse(self.service.event('alice', first['id'])['scanned'])
        async def callback(store, origin, event_id, message_id):
            if event_id == first['id']:
                raise RuntimeError('Synthetic deferred application observation')
            return True
        self.hooks.deliver_collaboration = AsyncMock(side_effect=callback)
        self.deliver()
        first_state = self.service.event('alice', first['id'])
        self.assertFalse(first_state['scanned'])
        self.assertEqual(first_state['errorCode'], 'RuntimeError')
        self.assertTrue(self.service.event('alice', second['id'])['scanned'])
        with self.service.db.read() as conn:
            self.assertGreater(self.service._row(conn, self.service.events, first['id'])['attempted_at'], 0)

    def test_shutdown_after_selection_blocks_recipient_native_insert_then_same_request_recovers(self):
        message, event = self.reserve()
        stopping = asyncio.Event()
        self.service.admission_stopping = stopping
        original = self.store.reserve_task
        def stop_at_insert(plan, request_id, **options):
            if plan['ownerId'] == 'bob':
                self.assertEqual(options['private_event_id'], event['id'])
                stopping.set()
            return original(plan, request_id, **options)
        bridge = self.fixture.state['bridge']
        with patch.object(self.store, 'reserve_task', stop_at_insert), \
                patch.object(bridge, 'submit', AsyncMock(wraps=bridge.submit)) as submit:
            self.deliver()
            submit.assert_not_awaited()
        self.assertIsNone(self.messages.read('alice', message['id'])['delivery']['taskId'])
        self.assertEqual(self.service.event('alice', event['id'])['errorCode'], 'ASSISTANT_DELIVERY_STOPPING')
        self.hooks.deliver_collaboration.assert_not_awaited()
        stopping.clear()
        self.deliver()
        receipt = self.messages.read('alice', message['id'])
        task = self.store.task(receipt['delivery']['taskId'], 'bob')
        stopping.set()
        with patch.object(self.messages.runs, 'start', AsyncMock()) as start:
            repeated = self.call(self.messages.recover, 'bob', message['id'], private_event_id=event['id'])
            start.assert_not_awaited()
        self.assertEqual(repeated['delivery']['taskId'], task['id'])
        self.assertEqual(original(self.store.plan(task['plan_id'], 'bob'), task['request_id'],
            private_event_id=event['id'])[1], False)
        self.assertEqual(self.count(self.scopes.allocations), 1)

    def test_shutdown_blocks_sender_continuation_at_native_insert_and_original_hook_rechecks(self):
        _, event = self.reserve()
        stopping = asyncio.Event()
        self.service.admission_stopping = stopping
        body = self.origin_body.model_copy(update={'requestId': 'private-followup-task'})
        async def callback(store, origin, event_id, message_id):
            await self.messages.runs.start('alice', body, private_event_id=event_id)
            return True
        self.hooks.deliver_collaboration.side_effect = callback
        original = self.store.reserve_task
        def stop_at_insert(plan, request_id, **options):
            if request_id == 'application-start:' + body.requestId:
                self.assertEqual(options['private_event_id'], event['id'])
                stopping.set()
            return original(plan, request_id, **options)
        with patch.object(self.store, 'reserve_task', stop_at_insert):
            self.deliver()
        self.assertEqual([task['id'] for task in self.store.tasks('alice')], [self.origin_id])
        self.hooks.validate_collaboration_admission.assert_not_called()
        self.assertFalse(self.service.event('alice', event['id'])['scanned'])
        stopping.clear()
        self.deliver()
        self.assertEqual(len(self.store.tasks('alice')), 2)
        self.hooks.validate_collaboration_admission.assert_called_once()
        args = self.hooks.validate_collaboration_admission.call_args.args
        self.assertEqual(args[:4], (self.store, self.store.task(self.origin_id, 'alice'), event['id'],
            'application-start:' + body.requestId))
        self.assertTrue(self.service.event('alice', event['id'])['scanned'])

    def test_existing_unknown_recipient_task_is_not_replayed(self):
        message, event = self.reserve()
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(
                side_effect=HTTPException(503, 'synthetic acknowledgement lost'))) as submit:
            self.deliver()
            self.assertEqual(submit.await_count, 1)
        before = self.messages.read('alice', message['id'])
        self.assertEqual(before['delivery']['state'], 'unknown')
        with patch.object(self.messages.runs, 'start', AsyncMock()) as start:
            self.deliver()
            start.assert_not_awaited()
        self.assertEqual(self.messages.read('alice', message['id'])['delivery']['taskId'],
            before['delivery']['taskId'])
        self.assertFalse(self.service.event('alice', event['id'])['scanned'])
        self.assertEqual(self.count(self.scopes.allocations), 1)

    def test_wrong_recipient_request_and_unavailable_original_sender_guard_reject_before_insert(self):
        _, event = self.reserve()
        body = self.origin_body.model_copy(update={'requestId': 'unbound-private-request'})
        with self.assertRaises(HTTPException) as caught:
            self.call(self.messages.runs.start, 'bob', body, private_event_id=event['id'])
        self.assertEqual(caught.exception.detail, 'ASSISTANT_COLLABORATION_BINDING_MISMATCH')
        self.assertEqual(self.store.tasks('bob'), [])
        del self.hooks.validate_collaboration_admission
        with self.assertRaises(HTTPException) as caught:
            self.call(self.messages.runs.start, 'alice', body, private_event_id=event['id'])
        self.assertEqual(caught.exception.detail, 'ASSISTANT_COLLABORATION_OWNER_UNAVAILABLE')
        self.assertEqual([task['id'] for task in self.store.tasks('alice')], [self.origin_id])

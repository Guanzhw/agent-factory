"""Portable transactional routing; budget/native guarantees require PostgreSQL tests."""
import asyncio
import time
from types import MethodType
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy import func, select

from agent_factory.application_content import ApplicationContent, ContentPublication
from agent_factory.assistant_endpoints import AssistantEndpoints, EndpointConfiguration
from agent_factory.assistant_events import AssistantEvents, ContentEvent, EventSubscription, error_code
from agent_factory.assistant_messages import AssistantMessages
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from test_applications_composition import ApplicationCompositionFixture, pin


class AssistantEventsTests(ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.store.transaction = MethodType(Store.transaction, self.store)
        self.endpoints = AssistantEndpoints(self.store, self.auth, self.applications)
        app = self.publish()
        self.endpoint = self.endpoints.configure('bob', EndpointConfiguration(name='Peer', applicationRef=pin(app),
            mode='literature'), 'peer-endpoint')
        self.content = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.publication = self.content.publish('alice', ContentPublication(source={
            'application': 'research', 'record': 'experiment-1', 'revision': '1'},
            content={'result': 'negative'}, visibility='team'), 'publish-content')
        self.messages = AssistantMessages(self.store, self.auth, self.endpoints, Mock())
        self.scopes = Mock()
        self.store.local_budget_scopes = self.scopes
        self.scopes.settle.return_value = {'state': 'HELD'}
        self.deadline = time.time() + 300
        self.scopes._scope.return_value = {'state': 'ACTIVE', 'body': {'deadline': self.deadline}}
        self.service = AssistantEvents(self.store, self.auth, self.endpoints, self.content, self.messages, self.scopes)
        self.config = EventSubscription(endpointId=self.endpoint['id'], namespace='research', eventType='record',
            scopeId='bob-scope', caps={'rounds': 1, 'toolCalls': 1, 'tokenLimit': None,
                'amountMicros': None, 'currency': None}, deadline=self.deadline, maxDepth=1, maxCandidates=2)
        self.event = ContentEvent(namespace='research', eventType='record', contentId=self.publication['id'],
            candidates=[self.endpoint['id']], deadline=self.deadline)

    def emit(self, key='event-emit', **kwargs):
        with self.store.transaction() as conn:
            return self.service.emit(conn, 'alice', self.event, key, **kwargs)

    def test_author_reads_rejection_before_task_without_receiver_private_fields_or_execution(self):
        event = self.emit()
        self.assertEqual(self.service.event('alice', event['id'])['deliveries'], [])
        with self.service.db.write() as conn:
            conn.execute(self.service.deliveries.insert().values(id='rejected-delivery',
                event_id=event['id'], endpoint_id=self.endpoint['id'], state='rejected',
                error='LOCAL_BUDGET_EXHAUSTED', attempted_at=time.time()))
        self.assertEqual(self.service.event('alice', event['id']), {
            'id': event['id'], 'scanned': False, 'errorCode': None,
            'deliveries': [{'id': 'rejected-delivery', 'endpointId': self.endpoint['id'],
                'state': 'rejected', 'errorCode': 'LOCAL_BUDGET_EXHAUSTED'}]})
        for owner, identifier in [('bob', event['id']), ('alice', 'missing-event')]:
            with self.subTest(owner=owner, identifier=identifier), self.assertRaises(HTTPException) as caught:
                self.service.event(owner, identifier)
            self.assertEqual(caught.exception.status_code, 404)
        self.scopes.allocate.assert_not_called()
        self.messages.runs.start.assert_not_called()

    def test_emit_requires_domain_transaction_and_rolls_back_intent_receipt(self):
        with self.store.engine.connect() as conn:
            with self.assertRaises(RuntimeError):
                self.service.emit(conn, 'alice', self.event, 'outside-domain')
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.store.transaction() as conn:
                self.service.emit(conn, 'alice', self.event, 'event-emit')
                raise RuntimeError('rollback')
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.service.events)).scalar(), 0)
        event = self.emit()
        self.assertEqual(self.emit()['id'], event['id'])
        self.event = self.event.model_copy(update={'eventType': 'other'})
        with self.assertRaises(HTTPException) as caught:
            self.emit()
        self.assertEqual(caught.exception.status_code, 409)

    def test_exact_subscription_and_candidates_deduplicate_allocation_and_message(self):
        event = self.emit()
        self.assertIsNone(self.service.prepare(event['id'], self.endpoint['id']))
        self.scopes.allocate.assert_not_called()
        subscription = self.service.configure('bob', self.config, 'subscribe-peer')
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        self.assertEqual(self.service.prepare(event['id'], self.endpoint['id']), delivery)
        self.scopes.allocate.assert_called_once()
        self.scopes.bind_request.assert_called_once()
        names = [call[0] for call in self.scopes.mock_calls]
        self.assertLess(names.index('admission_lock'), names.index('allocate'))
        self.assertLess(names.index('allocate'), names.index('bind_request'))
        binding = self.scopes.bind_request.call_args
        self.assertEqual(binding.args[1:3], ('bob', delivery['allocation_id']))
        self.assertEqual(binding.args[3], 'application-start:assistant-message:' + delivery['message_id'])
        self.assertEqual(binding.kwargs, {'delivery_id': delivery['id']})
        self.assertEqual(delivery['subscription_id'], subscription['id'])
        with self.service.db.read() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.messages.messages)).scalar(), 1)
        with self.assertRaises(HTTPException):
            self.service.configure('alice', self.config, 'forge-subscription')
        with self.assertRaises(HTTPException):
            self.service.configure('bob', self.config, 'duplicate-subscription')

    def test_revoke_blocks_original_delivery_at_admission_and_new_subscription_cannot_replace_it(self):
        subscription = self.service.configure('bob', self.config, 'subscribe-peer')
        event = self.emit()
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        self.scopes._allocation.return_value = {'scope_id': 'bob-scope'}
        with self.service.db.read() as conn:
            message = self.messages._row(conn, delivery['message_id'])
        request = 'application-start:' + self.messages._request_id(message)
        plan = {'ownerId': 'bob', 'applicationRef': self.endpoint['defaults']['applicationRef'],
            'mode': 'literature', 'normalizedGoal': message['text']}
        with self.store.transaction() as conn:
            self.service.validate_admission(conn, 'bob', delivery['id'], request, plan, delivery['allocation_id'])
        self.service.set_enabled('bob', subscription['id'], False, 'disable-subscription')
        self.service.configure('bob', self.config, 'replacement-subscription')
        with self.store.transaction() as conn, self.assertRaises(HTTPException):
            self.service.validate_admission(conn, 'bob', delivery['id'], request, plan, delivery['allocation_id'])
        self.assertEqual(self.service.prepare(event['id'], self.endpoint['id'])['subscription_id'], subscription['id'])

    def test_expiry_content_revocation_and_depth_are_enforced_before_allocation(self):
        self.service.configure('bob', self.config, 'subscribe-peer')
        self.content.set_visibility('alice', self.publication['id'], 'personal', 'content-revoke')
        event = self.emit()
        with self.assertRaises(HTTPException):
            self.service.prepare(event['id'], self.endpoint['id'])
        self.scopes.allocate.assert_not_called()
        self.content.set_visibility('alice', self.publication['id'], 'team', 'content-restore')
        with self.service.db.write() as conn:
            conn.execute(self.service.events.update().where(self.service.events.c.id == event['id']).values(depth=2))
        with self.assertRaises(HTTPException):
            self.service.prepare(event['id'], self.endpoint['id'])
        with self.service.db.write() as conn:
            conn.execute(self.service.events.update().where(self.service.events.c.id == event['id']).values(depth=0, deadline=0))
        with self.assertRaises(HTTPException):
            self.service.prepare(event['id'], self.endpoint['id'])
        self.scopes.allocate.assert_not_called()

    def test_automatic_lineage_uses_bound_original_task_and_cannot_extend_deadline(self):
        self.service.configure('bob', self.config, 'subscribe-peer')
        event = self.emit()
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        publication = self.content.publish('bob', ContentPublication(source={
            'application': 'research', 'record': 'reply-1', 'revision': '1'}, content={}, visibility='team'), 'bob-content')
        reply = self.event.model_copy(update={'contentId': publication['id'], 'deadline': self.deadline + 100})
        self.scopes._allocation.return_value = {'task_id': 'original-task'}
        with self.store.transaction() as conn:
            with self.assertRaises(HTTPException):
                self.service.emit(conn, 'bob', reply, 'reply-event', parent_delivery_id=delivery['id'], task_id='other-task')
            child = self.service.emit(conn, 'bob', reply, 'reply-event', parent_delivery_id=delivery['id'], task_id='original-task')
        self.assertEqual((child['root_id'], child['depth'], child['deadline']), (event['id'], 1, event['deadline']))

    def test_stopping_before_scan_and_after_prepare_never_admits_a_new_message(self):
        self.service.configure('bob', self.config, 'subscribe-peer')
        event = self.emit()
        stopping = asyncio.Event()
        stopping.set()
        asyncio.run(self.service.deliver_batch(stopping=stopping))
        self.scopes.allocate.assert_not_called()
        stopping.clear()
        original = self.service.prepare
        def prepare_and_stop(*args):
            result = original(*args)
            stopping.set()
            return result
        self.service.prepare = prepare_and_stop
        asyncio.run(self.service.deliver_batch(stopping=stopping))
        self.messages.runs.start.assert_not_called()
        self.scopes.allocate.assert_called_once()
        self.assertEqual(self.service.prepare(event['id'], self.endpoint['id'])['state'], 'pending')

    def test_failed_event_and_pending_message_rotate_without_blocking_following_items(self):
        self.service.configure('bob', self.config, 'subscribe-peer')
        first, second = sorted([self.emit('event-first'), self.emit('event-second')], key=lambda event: event['id'])
        prepare = self.service.prepare
        def fail_first(event_id, endpoint_id):
            if event_id == first['id']:
                raise HTTPException(503, 'synthetic dependency unavailable')
            return prepare(event_id, endpoint_id)
        self.messages.recover = AsyncMock(side_effect=RuntimeError('synthetic sensitive detail must not persist'))
        with patch.object(self.service, 'prepare', side_effect=fail_first):
            asyncio.run(self.service.deliver_batch(limit=2))
        with self.service.db.read() as conn:
            failed = self.service._row(conn, self.service.events, first['id'])
            progressed = self.service._row(conn, self.service.events, second['id'])
            delivery = conn.execute(select(self.service.deliveries)).mappings().one()
        self.assertFalse(failed['scanned'])
        self.assertEqual(failed['error'], 'HTTPException')
        self.assertTrue(progressed['scanned'])
        self.assertEqual(delivery['error'], 'RuntimeError')
        self.assertGreater(delivery['attempted_at'], 0)
        self.assertEqual(delivery['state'], 'pending')
        self.assertNotIn('sensitive detail', str(delivery))
        self.messages.recover = AsyncMock(return_value={})
        self.scopes.settle.return_value = {'state': 'HELD'}
        asyncio.run(self.service.deliver_batch(limit=2))
        self.assertEqual(self.messages.recover.await_count, 2)

    def test_terminal_no_task_failure_is_fenced_and_does_not_retry_or_release_hold(self):
        from sqlalchemy import Column, MetaData, String, Table
        metadata = MetaData()
        Table('af_tasks', metadata, Column('id', String, primary_key=True),
              Column('owner_id', String), Column('request_id', String))
        metadata.create_all(self.store.engine)
        self.service.configure('bob', self.config, 'subscribe-peer')
        self.emit()
        self.messages.recover = AsyncMock(side_effect=HTTPException(404, 'revoked'))
        asyncio.run(self.service.deliver_batch())
        asyncio.run(self.service.deliver_batch())
        self.assertEqual(self.messages.recover.await_count, 1)
        self.scopes.settle.assert_called_once()
        with self.service.db.read() as conn:
            delivery = dict(conn.execute(select(self.service.deliveries)).mappings().one())
            self.assertEqual(delivery['state'], 'rejected')
            self.assertIsNotNone(delivery['allocation_id'])
            with self.assertRaises(HTTPException) as caught:
                self.service.validate_admission(conn, 'bob', delivery['id'], 'unused', {}, delivery['allocation_id'])
            self.assertEqual(caught.exception.detail, 'ASSISTANT_EVENT_DELIVERY_MISMATCH')

    def test_original_task_delivery_reads_bound_references_without_creating_work(self):
        from sqlalchemy import Column, MetaData, String, Table
        metadata = MetaData()
        tasks = Table('af_tasks', metadata, Column('id', String, primary_key=True),
            Column('owner_id', String), Column('request_id', String), Column('run_id', String))
        metadata.create_all(self.store.engine)
        self.store.sql = MethodType(Store.sql, self.store)
        self.store.task = MethodType(Store.task, self.store)
        self.service.configure('bob', self.config, 'subscribe-peer')
        event = self.emit()
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        with self.store.engine.begin() as conn:
            conn.execute(tasks.insert().values(id='original-task', owner_id='bob', request_id='original-request'))
        self.scopes.request_delivery.return_value = delivery['id']
        self.scopes.request_allocation.return_value = delivery['allocation_id']
        self.scopes._allocation.return_value = {'task_id': 'original-task', 'scope_id': 'bob-scope'}
        self.scopes.reset_mock()
        self.messages.recover = AsyncMock()
        expected = {'contentId': self.publication['id'], 'eventId': event['id'],
            'deliveryId': delivery['id'], 'rootId': event['id'], 'depth': 0,
            'scopeId': 'bob-scope', 'allocationId': delivery['allocation_id']}
        self.assertEqual(self.service.delivery_for_task('bob', 'original-task'), expected)
        with self.assertRaises(HTTPException) as denied:
            self.service.delivery_for_task('alice', 'original-task')
        self.assertEqual(denied.exception.status_code, 404)
        self.scopes._allocation.return_value = {'task_id': 'different-task', 'scope_id': 'bob-scope'}
        with self.assertRaises(HTTPException) as invalid:
            self.service.delivery_for_task('bob', 'original-task')
        self.assertEqual(invalid.exception.detail, 'ASSISTANT_EVENT_TASK_BINDING_MISMATCH')
        self.scopes.request_delivery.return_value = None
        self.assertIsNone(self.service.delivery_for_task('bob', 'original-task'))
        self.scopes.allocate.assert_not_called()
        self.scopes.bind_request.assert_not_called()
        self.messages.recover.assert_not_called()

    def test_depth_above_twenty_remains_bounded_by_receiver_configuration(self):
        config = EventSubscription.model_validate({**self.config.model_dump(), 'maxDepth': 40})
        self.service.configure('bob', config, 'deep-subscription')
        event = self.emit()
        with self.service.db.write() as conn:
            conn.execute(self.service.events.update().where(self.service.events.c.id == event['id']).values(depth=30))
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        self.assertEqual(delivery['state'], 'pending')
        second = self.emit('too-deep-event')
        with self.service.db.write() as conn:
            conn.execute(self.service.events.update().where(self.service.events.c.id == second['id']).values(depth=41))
        with self.assertRaises(HTTPException) as denied:
            self.service.prepare(second['id'], self.endpoint['id'])
        self.assertEqual(denied.exception.detail, 'ASSISTANT_EVENT_PROPAGATION_LIMIT')
        self.scopes.allocate.assert_called_once()
        self.assertEqual(self.scopes.allocate.call_args.args[-1]['rounds'], 1)

    def test_safe_error_codes_and_arbitrary_messages_are_distinguished(self):
        for detail in ('LOCAL_BUDGET_EXHAUSTED', {'code': 'RESOURCE_NOT_FOUND', 'message': 'private detail'}):
            expected = detail if isinstance(detail, str) else detail['code']
            self.assertEqual(error_code(HTTPException(409, detail)), expected)
        for detail in ('provider password=private', 'CODE: private detail', 'A' * 121,
                       'SYNTHETIC_PRIVATE_TOKEN_ABCDEF', {'code': 'SYNTHETIC_PRIVATE_TOKEN_ABCDEF'},
                       {'code': 'unsafe code'}, {'message': 'secret'}, {'code': 123}):
            self.assertEqual(error_code(HTTPException(409, detail)), 'HTTPException')
        self.assertEqual(error_code(RuntimeError('private detail')), 'RuntimeError')
        self.service.configure('bob', self.config, 'subscribe-peer')
        event = self.emit()
        with patch.object(self.service, 'prepare', side_effect=HTTPException(409, {'code': 'RESOURCE_NOT_FOUND', 'message': 'private'})):
            asyncio.run(self.service.deliver_batch())
        with self.service.db.read() as conn:
            saved = self.service._row(conn, self.service.events, event['id'])
            delivery = conn.execute(select(self.service.deliveries)).mappings().one()
        self.assertEqual(saved['error'], 'RESOURCE_NOT_FOUND')
        self.assertEqual(delivery['error'], 'RESOURCE_NOT_FOUND')
        self.assertNotIn('private', str(saved) + str(delivery))

"""Real PostgreSQL event atomicity and allocation deduplication; no paid execution."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from threading import Event
import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import func, select

from agent_factory.application_content import ContentPublication
from agent_factory.assistant_endpoints import EndpointConfiguration
from agent_factory.assistant_events import AssistantEvents, ContentEvent, EventSubscription
from agent_factory.store import digest
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AssistantEventsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.deliver_batch = AssistantEvents.deliver_batch
        self.loop_patch = patch.object(AssistantEvents, 'deliver_batch', AsyncMock(return_value=(0, 0)))
        self.loop_patch.start()
        self.addCleanup(self.loop_patch.stop)
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        fixture = self.fixture
        app = fixture.publish_http()
        self.service = fixture.state['assistant_events']
        self.scopes = fixture.store.local_budget_scopes
        self.endpoint = fixture.state['assistant_endpoints'].configure('bob', EndpointConfiguration(
            name='Peer receiver', applicationRef=fixtures.pin(app), mode='literature'), 'pg-peer-endpoint')
        self.deadline = time.time() + 300
        self.caps = {'rounds': 1, 'toolCalls': 10, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        self.scopes.create_scope('bob', 'pg-peer-scope', digest({'fixture': 'explicit receiver commitment'}),
            self.caps, self.deadline)
        self.config = EventSubscription(endpointId=self.endpoint['id'], namespace='research', eventType='record',
            scopeId='pg-peer-scope', caps=self.caps, deadline=self.deadline, maxDepth=1, maxCandidates=2)
        self.subscription = self.service.configure('bob', self.config, 'pg-peer-subscribe')
        self.publication = fixture.state['application_content'].publish('alice', ContentPublication(
            source={'application': 'research', 'record': 'experiment-1', 'revision': '1'},
            content={'result': 'synthetic negative result'}, visibility='team'), 'pg-peer-content')
        self.event = ContentEvent(namespace='research', eventType='record', contentId=self.publication['id'],
            candidates=[self.endpoint['id']], deadline=self.deadline)

    def emit(self, key):
        with self.fixture.store.transaction() as conn:
            return self.service.emit(conn, 'alice', self.event, key)

    def test_actual_task_capacity_recovers_original_delivery_and_allocation(self):
        fixture = self.fixture
        messages = self.service.messages
        endpoint = self.service.endpoints.resolve(self.endpoint['id'])
        release = Event()
        original_invoke = fixtures.DemoModel.ainvoke
        original_stream = fixtures.DemoModel.ainvoke_stream

        async def wait_for_release():
            if not await asyncio.to_thread(release.wait, 15):
                raise TimeoutError('synthetic capacity model was not released')

        async def blocked_invoke(model, *args, **kwargs):
            await wait_for_release()
            return await original_invoke(model, *args, **kwargs)

        async def blocked_stream(model, *args, **kwargs):
            await wait_for_release()
            async for item in original_stream(model, *args, **kwargs):
                yield item

        bridge = fixture.state['bridge']
        with patch.object(fixtures.DemoModel, 'ainvoke', blocked_invoke), \
                patch.object(fixtures.DemoModel, 'ainvoke_stream', blocked_stream), \
                patch.object(bridge, 'submit', AsyncMock(wraps=bridge.submit)) as submit:
            try:
                blockers = []
                for index in range(fixture.settings.max_user_tasks):
                    body = messages._start_body({'id': 'capacity-blocker-' + str(index),
                        'text': 'Hold the synthetic native task capacity.'}, endpoint)
                    # Ordinary application requests do not claim message identities.
                    body = body.model_copy(update={'requestId': 'capacity-blocker-' + str(index)})
                    result = fixture.client.portal.call(partial(messages.runs.start, 'bob', body))
                    blockers.append(result['job']['id'])
                self.assertEqual(submit.await_count, len(blockers))
                event = self.emit('pg-capacity-event')
                fixture.client.portal.call(partial(self.deliver_batch, self.service))
                with fixture.store.engine.connect() as conn:
                    original = dict(conn.execute(select(self.service.deliveries).where(
                        self.service.deliveries.c.event_id == event['id'])).mappings().one())
                    allocation = self.scopes._allocation(conn, 'bob', original['allocation_id'])
                    request_id = 'application-start:assistant-message:' + original['message_id']
                    self.assertEqual(self.scopes.request_allocation(conn, 'bob', request_id), allocation['id'])
                    self.assertIsNone(allocation['task_id'])
                    self.assertEqual(allocation['state'], 'ALLOCATED')
                self.assertEqual(original['state'], 'pending')
                self.assertEqual(original['error'], 'ACTIVE_TASK_CAPACITY_EXHAUSTED')
                self.assertEqual(submit.await_count, len(blockers))
                self.assertEqual(self.scopes.settle('bob', allocation['id'])['state'], 'HELD')
            finally:
                release.set()
            fixture.login('bob')
            for task_id in blockers:
                self.assertEqual(fixture.wait_job(task_id)['job']['status'], 'completed')
            fixture.client.portal.call(partial(self.deliver_batch, self.service))
            recovered = self.service.delivery('bob', original['id'])
            for key in ('id', 'message_id', 'allocation_id', 'event_id'):
                self.assertEqual(recovered[key], original[key])
            with fixture.store.engine.connect() as conn:
                allocation = self.scopes._allocation(conn, 'bob', original['allocation_id'])
                self.assertEqual(conn.execute(select(func.count()).select_from(self.scopes.allocations)).scalar(), 1)
            task = fixture.store.task(allocation['task_id'], 'bob')
            self.assertEqual(task['request_id'], request_id)
            self.assertEqual(fixture.wait_job(task['id'])['job']['status'], 'completed')
            fixture.client.portal.call(partial(self.deliver_batch, self.service))
            self.assertEqual(self.service.delivery('bob', original['id'])['state'], 'settled')
            self.assertEqual(submit.await_count, len(blockers) + 1)

    def test_concurrent_prepare_allocates_exactly_once_and_second_event_exhausts_scope(self):
        event = self.emit('pg-event-first')
        with ThreadPoolExecutor(max_workers=2) as pool:
            deliveries = list(pool.map(lambda _: self.service.prepare(event['id'], self.endpoint['id']), range(2)))
        self.assertEqual(deliveries[0], deliveries[1])
        with self.fixture.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.scopes.allocations)).scalar(), 1)
            self.assertEqual(conn.execute(select(func.count()).select_from(self.service.messages.messages)).scalar(), 1)
        second = self.emit('pg-event-second')
        with self.assertRaises(HTTPException) as caught:
            self.service.prepare(second['id'], self.endpoint['id'])
        self.assertEqual(caught.exception.status_code, 429)
        allocation = self.scopes.settle('bob', deliveries[0]['allocation_id'])
        self.assertEqual(allocation['state'], 'HELD')
        with self.fixture.store.engine.connect() as conn:
            held = self.scopes._allocation(conn, 'bob', deliveries[0]['allocation_id'])
            scope = self.scopes._scope(conn, 'bob', 'pg-peer-scope')
            self.assertEqual(held['state'], 'ALLOCATED')
            self.assertIsNone(held['task_id'])
            self.assertEqual((scope['rounds'], scope['held_tools'], scope['settled_tools']), (1, 10, 0))
        self.fixture.stop(); self.fixture.start()
        service = self.fixture.state['assistant_events']
        self.assertEqual(service.prepare(event['id'], self.endpoint['id']), deliveries[0])
        with self.fixture.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(service.messages.messages)).scalar(), 1)

    def test_domain_emit_rollback_and_current_revocation_prevent_delivery(self):
        content = self.fixture.state['application_content']
        with self.assertRaisesRegex(RuntimeError, 'abort domain'):
            with self.fixture.store.transaction() as conn:
                publication = content.publish('alice', ContentPublication(source={
                    'application': 'research', 'record': 'rollback', 'revision': '1'}, content={}, visibility='team'),
                    'pg-rollback-content')
                emitted = self.service.emit(conn, 'alice', self.event.model_copy(update={'contentId': publication['id']}),
                    'pg-rollback-event')
                with self.fixture.store.engine.connect() as observer:
                    self.assertIsNone(observer.execute(select(self.service.events.c.id).where(
                        self.service.events.c.id == emitted['id'])).first())
                raise RuntimeError('abort domain')
        with self.assertRaises(HTTPException):
            content.read('bob', publication['id'])
        event = self.emit('pg-current-event')
        content.set_visibility('alice', self.publication['id'], 'personal', 'pg-revoke-content')
        with self.assertRaises(HTTPException):
            self.service.prepare(event['id'], self.endpoint['id'])
        with self.fixture.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.scopes.allocations)).scalar(), 0)

    def recover(self, delivery):
        return self.fixture.client.portal.call(partial(self.service.messages.recover, 'bob', delivery['message_id'],
            allocation_id=delivery['allocation_id'], delivery_id=delivery['id']))

    def test_revocation_commits_after_initial_check_before_reservation_and_dispatch_is_zero(self):
        event = self.emit('pg-race-event')
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        checked, resume = Event(), Event()
        start = self.service.messages.runs.start
        async def paused(*args, **kwargs):
            checked.set()
            if not await asyncio.to_thread(resume.wait, 10):
                raise TimeoutError('admission barrier not released')
            return await start(*args, **kwargs)
        with patch.object(self.service.messages.runs, 'start', paused), \
                patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.recover, delivery)
                try:
                    self.assertTrue(checked.wait(10))
                    self.fixture.state['application_content'].set_visibility('alice', self.publication['id'],
                        'personal', 'pg-race-revoke')
                finally:
                    resume.set()
                with self.assertRaises(HTTPException):
                    future.result(timeout=15)
            submit.assert_not_called()
        self.assertEqual(self.fixture.store.tasks('bob'), [])
        with self.fixture.store.engine.connect() as conn:
            allocation = self.scopes._allocation(conn, 'bob', delivery['allocation_id'])
            self.assertIsNone(allocation['task_id'])
            self.assertEqual(allocation['state'], 'ALLOCATED')

    def test_reservation_commits_before_revocation_retains_original_identity_without_redispatch(self):
        event = self.emit('pg-admitted-event')
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        committed, resume = Event(), Event()
        async def paused_submit(*args, **kwargs):
            committed.set()
            if not await asyncio.to_thread(resume.wait, 10):
                raise TimeoutError('native barrier not released')
            raise TimeoutError('synthetic unconfirmed native acknowledgement')
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(side_effect=paused_submit)) as submit:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.recover, delivery)
                try:
                    self.assertTrue(committed.wait(10))
                    before = self.fixture.store.tasks('bob')
                    self.assertEqual(len(before), 1)
                    with self.fixture.store.engine.connect() as conn:
                        allocation = self.scopes._allocation(conn, 'bob', delivery['allocation_id'])
                        self.assertEqual(allocation['task_id'], before[0]['id'])
                    self.service.set_enabled('bob', self.subscription['id'], False, 'pg-admitted-disable')
                finally:
                    resume.set()
                first = future.result(timeout=15)
            repeated = self.recover(delivery)
            self.assertEqual(first['delivery']['taskId'], repeated['delivery']['taskId'])
            self.assertEqual(first['delivery']['taskId'], before[0]['id'])
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.scopes.settle('bob', delivery['allocation_id'])['state'], 'HELD')

    def test_actual_background_delivery_wakes_offline_receiver_with_bound_scope(self):
        self.fixture.stop()
        self.loop_patch.stop()
        self.fixture.start()
        self.service = self.fixture.state['assistant_events']
        self.scopes = self.fixture.store.local_budget_scopes
        event = self.emit('pg-background-event')
        deadline = time.monotonic() + 15
        delivery = None
        while time.monotonic() < deadline:
            with self.fixture.store.engine.connect() as conn:
                delivery = conn.execute(select(self.service.deliveries).where(
                    self.service.deliveries.c.event_id == event['id'])).mappings().first()
                if delivery and delivery['allocation_id']:
                    allocation = self.scopes._allocation(conn, 'bob', delivery['allocation_id'])
                    if allocation['task_id'] is not None:
                        break
            time.sleep(.05)
        else:
            self.fail('background delivery did not bind a native task')
        self.fixture.login('bob')
        detail = self.fixture.wait_job(allocation['task_id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)
        self.assertEqual(len(self.fixture.store.tasks('bob')), 1)
        self.assertEqual(delivery['owner_id'], 'bob')
        with self.fixture.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.scopes.allocations)).scalar(), 1)
        self.fixture.stop()

    def test_stopping_after_recovery_check_before_reservation_blocks_fresh_dispatch(self):
        event = self.emit('pg-stop-event')
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        checked, resume = Event(), Event()
        self.service.admission_stopping = asyncio.Event()
        start = self.service.messages.runs.start
        async def paused(*args, **kwargs):
            checked.set()
            if not await asyncio.to_thread(resume.wait, 10):
                raise TimeoutError('stop barrier not released')
            return await start(*args, **kwargs)
        with patch.object(self.service.messages.runs, 'start', paused), \
                patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.recover, delivery)
                try:
                    self.assertTrue(checked.wait(10))
                    self.service.admission_stopping.set()
                finally:
                    resume.set()
                with self.assertRaises(HTTPException) as caught:
                    future.result(timeout=15)
                self.assertEqual(caught.exception.detail, 'ASSISTANT_DELIVERY_STOPPING')
            submit.assert_not_called()
        self.assertEqual(self.fixture.store.tasks('bob'), [])

    def test_public_instances_cannot_bypass_prepared_delivery_revocation_without_keywords(self):
        event = self.emit('pg-public-bypass-event')
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        with self.service.db.read() as conn:
            message = self.service.messages._row(conn, delivery['message_id'])
        endpoint = self.service.endpoints.resolve(delivery['endpoint_id'])
        body = self.service.messages._start_body(message, endpoint)
        plan, request_id = self.service.messages.runs._prepare('bob', body)
        with self.fixture.store.engine.connect() as conn:
            self.assertEqual(self.scopes.request_allocation(conn, 'bob', request_id), delivery['allocation_id'])
            self.assertEqual(self.scopes.request_delivery(conn, 'bob', request_id), delivery['id'])
        self.fixture.state['application_content'].set_visibility('alice', self.publication['id'],
            'personal', 'pg-public-revoke')
        self.fixture.login('bob')
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            response = self.fixture.client.post('/api/factory/instances', json={
                'planId': plan['id'], 'requestId': request_id})
            self.assertEqual(response.status_code, 404, response.text)
            submit.assert_not_called()
        self.assertEqual(self.fixture.store.tasks('bob'), [])
        with self.fixture.store.engine.connect() as conn:
            allocation = self.scopes._allocation(conn, 'bob', delivery['allocation_id'])
            self.assertIsNone(allocation['task_id'])
            self.assertEqual(allocation['state'], 'ALLOCATED')

    def test_application_cleanup_observes_shutdown_fence_before_attempting_prepared_delivery(self):
        event = self.emit('pg-cleanup-event')
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        self.fixture.stop()
        observations = []

        @asynccontextmanager
        async def application_lifespan(app):
            yield
            state = app.state.factory
            service = state['assistant_events']
            self.assertIsNotNone(service.admission_stopping)
            self.assertTrue(service.admission_stopping.is_set())
            with self.assertRaises(HTTPException) as caught:
                await service.messages.recover('bob', delivery['message_id'],
                    allocation_id=delivery['allocation_id'], delivery_id=delivery['id'])
            self.assertEqual(caught.exception.detail, 'ASSISTANT_DELIVERY_STOPPING')
            self.assertEqual(state['store'].tasks('bob'), [])
            with state['store'].engine.connect() as conn:
                allocation = state['store'].local_budget_scopes._allocation(conn, 'bob', delivery['allocation_id'])
                self.assertIsNone(allocation['task_id'])
                self.assertEqual(allocation['state'], 'ALLOCATED')
            observations.append('application cleanup fenced before any fresh task')

        create_app = fixtures.create_app
        with patch.object(fixtures, 'create_app', side_effect=lambda settings: create_app(
                settings, lifespan_context=application_lifespan)):
            self.fixture.start()
        self.service = self.fixture.state['assistant_events']
        self.assertFalse(self.service.admission_stopping.is_set())
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            self.fixture.stop()
            submit.assert_not_called()
        self.assertEqual(observations, ['application cleanup fenced before any fresh task'])

    def test_original_task_input_port_uses_actual_request_and_allocation_binding(self):
        event = self.emit('pg-input-event')
        delivery = self.service.prepare(event['id'], self.endpoint['id'])
        with self.service.db.read() as conn:
            message = self.service.messages._row(conn, delivery['message_id'])
        endpoint = self.service.endpoints.resolve(delivery['endpoint_id'])
        body = self.service.messages._start_body(message, endpoint)
        plan, request_id = self.service.messages.runs._prepare('bob', body)
        task, fresh = self.fixture.store.reserve_task(plan, request_id)
        self.assertTrue(fresh)
        expected = {'contentId': self.publication['id'], 'eventId': event['id'],
            'deliveryId': delivery['id'], 'rootId': event['id'], 'depth': 0,
            'scopeId': 'pg-peer-scope', 'allocationId': delivery['allocation_id']}
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            self.assertEqual(self.service.delivery_for_task('bob', task['id']), expected)
            with self.assertRaises(HTTPException) as denied:
                self.service.delivery_for_task('alice', task['id'])
            self.assertEqual(denied.exception.status_code, 404)
            self.fixture.state['application_content'].set_visibility('alice', self.publication['id'],
                'personal', 'pg-input-content-revoke')
            self.assertEqual(self.service.delivery_for_task('bob', task['id']), expected)
            with self.assertRaises(HTTPException):
                self.fixture.state['application_content'].read('bob', expected['contentId'])
            manual_plan, manual_request = self.service.messages.runs._prepare('bob',
                body.model_copy(update={'requestId': 'manual-original-request'}))
            manual, manual_fresh = self.fixture.store.reserve_task(manual_plan, manual_request)
            self.assertTrue(manual_fresh)
            self.assertIsNone(self.service.delivery_for_task('bob', manual['id']))
            with self.fixture.store.transaction() as conn:
                conn.execute(self.service.deliveries.update().where(self.service.deliveries.c.id == delivery['id'])
                    .values(owner_id='alice'))
            with self.assertRaises(HTTPException) as mismatch:
                self.service.delivery_for_task('bob', task['id'])
            self.assertEqual(mismatch.exception.detail, 'ASSISTANT_EVENT_TASK_BINDING_MISMATCH')
            submit.assert_not_called()
        with self.fixture.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.scopes.allocations)).scalar(), 1)
        self.assertEqual(len(self.fixture.store.tasks('bob')), 2)

"""A04: real native execution of a synthetic two-member event cycle."""
from contextlib import contextmanager
from dataclasses import replace
import os
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_factory.application_content import ContentPublication
from agent_factory.assistant_endpoints import EndpointConfiguration
from agent_factory.assistant_events import ContentEvent, EventSubscription
from agent_factory.store import digest
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AssistantEventCyclePostgresTests(unittest.TestCase):
    def setUp(self):
        self.endpoints = {}
        self.deadline = time.time() + 120
        create_app = fixtures.create_app

        def constructed(settings):
            app = create_app(replace(settings, storage_low_water_bytes=1, storage_task_reserve_bytes=4096))
            state = app.app.state.factory
            store, content, events = state['store'], state['application_content'], state['assistant_events']

            @contextmanager
            def finalization_context(conn, task):
                with content.db.write(), events.db.write():
                    def finalize(completion):
                        self.assertEqual(completion['settlement']['state'], 'SETTLED')
                        origin = events.delivery_for_task(task['owner_id'], task['id'])
                        self.assertIsNotNone(origin)
                        peer = 'alice' if task['owner_id'] == 'bob' else 'bob'
                        publication = content.publish(task['owner_id'], ContentPublication(source={
                            'application': 'cycle-fixture', 'record': task['id'], 'revision': '1'},
                            content={'result': task['body']['stoppedStatus'], 'kind': 'synthetic'},
                            visibility='team'), 'cycle-content:' + task['id'])
                        events.emit(conn, task['owner_id'], ContentEvent(namespace='cycle-fixture',
                            eventType='completed', contentId=publication['id'],
                            candidates=[self.endpoints[peer]], deadline=self.deadline),
                            'cycle-event:' + task['id'], parent_delivery_id=origin['deliveryId'], task_id=task['id'])
                    yield finalize

            store.application_runtime.register('cycle-fixture',
                SimpleNamespace(finalization_context=finalization_context),
                applications=(('synthetic-text-audit', 1),), finalizes=True)
            return app

        constructor = patch.object(fixtures, 'create_app', side_effect=constructed)
        constructor.start()
        self.addCleanup(constructor.stop)
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_two_native_receivers_cycle_until_original_scope_refuses_third_admission(self):
        fixture = self.fixture
        app = fixture.publish_http()
        events, content = fixture.state['assistant_events'], fixture.state['application_content']
        scopes = fixture.store.local_budget_scopes
        caps = {'rounds': 1, 'toolCalls': 10, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        for owner in ('alice', 'bob'):
            endpoint = fixture.state['assistant_endpoints'].configure(owner, EndpointConfiguration(
                name='Cycle receiver', applicationRef=fixtures.pin(app), mode='literature'), 'cycle-endpoint')
            self.endpoints[owner] = endpoint['id']
            scopes.create_scope(owner, 'cycle-' + owner, digest({'owner': owner}), caps, self.deadline)
            events.configure(owner, EventSubscription(endpointId=endpoint['id'], namespace='cycle-fixture',
                eventType='completed', scopeId='cycle-' + owner, caps=caps, deadline=self.deadline,
                maxDepth=5, maxCandidates=1), 'cycle-subscription')
        publication = content.publish('alice', ContentPublication(source={
            'application': 'cycle-fixture', 'record': 'seed', 'revision': '1'},
            content={'result': 'synthetic seed'}, visibility='team'), 'cycle-seed')
        with fixture.store.transaction() as conn:
            original = events.emit(conn, 'alice', ContentEvent(namespace='cycle-fixture', eventType='completed',
                contentId=publication['id'], candidates=[self.endpoints['bob']], deadline=self.deadline), 'cycle-seed')

        deadline = time.monotonic() + 20
        deliveries = []
        while time.monotonic() < deadline:
            deliveries = fixture.store.sql('SELECT * FROM af_assistant_event_deliveries')
            if sorted(row['state'] for row in deliveries) == ['rejected', 'settled', 'settled']:
                break
            time.sleep(.05)
        self.assertEqual(sorted(row['state'] for row in deliveries), ['rejected', 'settled', 'settled'], deliveries)
        rejected = next(row for row in deliveries if row['state'] == 'rejected')
        self.assertEqual(rejected['error'], 'LOCAL_BUDGET_EXHAUSTED')
        self.assertIsNone(rejected['allocation_id'])
        lineage = fixture.store.sql('SELECT id,root_id,depth,scanned FROM af_assistant_events ORDER BY depth')
        self.assertEqual([row['depth'] for row in lineage], [0, 1, 2])
        self.assertEqual({row['root_id'] for row in lineage}, {original['id']})
        self.assertTrue(all(row['scanned'] for row in lineage))
        identities = []
        for owner in ('alice', 'bob'):
            tasks = fixture.store.tasks(owner)
            self.assertEqual(len(tasks), 1)
            task = tasks[0]
            self.assertTrue(task['terminal'])
            self.assertEqual(task['body']['stoppedStatus'], 'completed')
            self.assertEqual(fixture.store.native_db.get_job(task['run_id'])['status'], 'completed')
            scope = scopes.inspect(owner, 'cycle-' + owner)
            self.assertEqual(scope['allocatedRounds'], 1)
            self.assertEqual(len(scope['allocations']), 1)
            allocation = scope['allocations'][0]
            self.assertEqual(allocation['state'], 'SETTLED')
            self.assertEqual(allocation['taskId'], task['id'])
            identities.append((task['id'], task['run_id'], allocation['allocationId']))
        for _ in range(3):
            self.assertEqual(fixture.client.portal.call(events.deliver_batch), (0, 0))
        self.assertEqual(fixture.store.sql('SELECT id,root_id,depth,scanned FROM af_assistant_events ORDER BY depth'), lineage)
        for index, owner in enumerate(('alice', 'bob')):
            task = fixture.store.tasks(owner)
            self.assertEqual(len(task), 1)
            scope = scopes.inspect(owner, 'cycle-' + owner)
            self.assertEqual(scope['allocatedRounds'], 1)
            self.assertEqual(len(scope['allocations']), 1)
            self.assertEqual((task[0]['id'], task[0]['run_id'], scope['allocations'][0]['allocationId']), identities[index])

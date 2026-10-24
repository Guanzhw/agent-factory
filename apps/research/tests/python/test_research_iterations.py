"""Portable activity state-machine checks, not native ORX or PostgreSQL proof."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine, select

from agent_factory_research.research_iterations import IterationPreset, ResearchIterations
from agent_factory_research.services import ResearchServices


CAPS = dict(rounds=2, toolCalls=8, tokenLimit=None, amountMicros=None, currency=None)
BASELINE = dict(kind='reviewedSeed', sha256='a' * 64, datasetSha256='b' * 64,
                evaluatorSha256='c' * 64, metricValue=16)


class MemoryStore:
    def __init__(self):
        self.engine = create_engine('sqlite://')
        self.connection = None
        self.tasks = {}
        self.local_budget_scopes = Scopes(self)

    def task(self, identifier, owner=None):
        return self.tasks[identifier]

    def effects(self, identifier):
        return []

    def admission_failed(self, identifier, message):
        self.tasks[identifier].update(admission='rejected', terminal=True)

    @contextmanager
    def transaction(self, *, read_only=False):
        if self.connection is not None:
            yield self.connection
            return
        with self.engine.begin() as conn:
            self.connection = conn
            try:
                yield conn
            finally:
                self.connection = None


class Scopes:
    """Transactional budget seam: reserves caps; production supplies stop proof."""
    def __init__(self, store):
        self.store = store
        self.held = False
        metadata = MetaData()
        self.rows = Table('fake_scopes', metadata, Column('id', String, primary_key=True), Column('body', JSON))
        metadata.create_all(store.engine)

    def lock(self, conn):
        assert conn is self.store.connection

    def read(self, identifier):
        return deepcopy(self.store.connection.execute(select(self.rows.c.body).where(self.rows.c.id == identifier)).scalar_one())

    def write(self, identifier, body):
        self.store.connection.execute(self.rows.update().where(self.rows.c.id == identifier).values(body=body))

    def create_scope(self, owner, scope_id, commitment_sha, caps, deadline):
        self.store.connection.execute(self.rows.insert().values(id=scope_id, body=dict(owner=owner, caps=caps, allocations={}, cancelled=False)))

    def allocate(self, conn, owner, scope_id, allocation_id, intent_sha, caps):
        value = self.read(scope_id)
        assert value['owner'] == owner
        if value['cancelled']:
            raise HTTPException(409, 'CANCELLED')
        if sum(a['caps']['toolCalls'] for a in value['allocations'].values()) + caps['toolCalls'] > value['caps']['toolCalls']:
            raise HTTPException(429, 'LOCAL_BUDGET_EXHAUSTED')
        value['allocations'][allocation_id] = dict(caps=caps, intent=intent_sha)
        self.write(scope_id, value)
        return dict(allocationId=allocation_id, scopeId=scope_id, state='ALLOCATED')

    def bind_root(self, conn, owner, allocation_id, task_id, plan_sha):
        assert conn is self.store.connection and task_id and plan_sha

    def settle(self, owner, allocation_id):
        assert self.store.connection is None
        return dict(state='HELD' if self.held else 'SETTLED', allocationId=allocation_id,
                    toolCalls=1, settledTokens=None, settledAmountMicros=None)

    def inspect(self, owner, scope_id):
        return self.read(scope_id)

    def cancel(self, owner, scope_id):
        value = self.read(scope_id)
        value['cancelled'] = True
        self.write(scope_id, value)


class Driver:
    def __init__(self, store):
        self.store = store
        self.reserved, self.dispatched, self.cancelled = [], [], []
        self.fail_dispatch = False
        self.observations = {}

    def reserve(self, owner, activity, round):
        assert self.store.connection is not None
        self.reserved.append(round)
        self.store.tasks['task-' + round['id']] = dict(id='task-' + round['id'], run_id=None,
                                                       admission='reserved', terminal=False)
        return dict(taskId='task-' + round['id'], planId='plan-' + round['id'], planSha256='d' * 64)

    async def dispatch(self, owner, round):
        assert self.store.connection is None
        self.dispatched.append(round['taskId'])
        if self.fail_dispatch:
            raise TimeoutError('lost acknowledgement')

    async def observe(self, owner, round):
        assert self.store.connection is None
        return deepcopy(self.observations.get(round['id'], dict(state='unknown', taskId=round['taskId'], runId=None)))

    async def cancel(self, owner, round):
        assert self.store.connection is None
        with self.store.transaction():
            assert self.store.local_budget_scopes.read(round['activityId'])['cancelled']
        self.cancelled.append(round['taskId'])

    def stopped(self, round, *, value=0, evaluation=True):
        baseline = round['baselineSource']
        result = dict(state='stopped', taskId=round['taskId'], runId='run-' + round['id'], evaluation=None, sourcePin=None)
        if evaluation:
            result.update(evaluation=dict(artifactId='eval-' + round['id'], sha256='e' * 64,
                          metric='mean_squared_error', baselineValue=baseline['metricValue'], candidateValue=value,
                          baselineSourceSha256=baseline['sha256'], candidateSourceSha256='f' * 64,
                          datasetSha256=baseline['datasetSha256'], evaluatorSha256=baseline['evaluatorSha256']),
                          sourcePin=dict(kind='sourceArtifact', ownerId='alice', taskId=round['taskId'],
                          artifactId='source-' + round['id'], sha256='f' * 64,
                          datasetSha256=baseline['datasetSha256'], evaluatorSha256=baseline['evaluatorSha256']))
        self.observations[round['id']] = result


class ResearchIterationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.engine.dispose)
        self.driver = Driver(self.store)
        self.research = ResearchServices(factory_store=self.store, installed=True)
        self.auth = SimpleNamespace(require_member=lambda owner: None)
        self.preset = IterationPreset('toy', 'alice', 'preset-v1', {'dataset': 'b' * 64}, BASELINE,
                                      {**CAPS, 'rounds': 1, 'toolCalls': 4}, 10)
        self.service = self.reopen()
        self.deadline = time.time() + 100

    def reopen(self):
        return ResearchIterations(self.store, self.auth, research=self.research,
                                  presets={'toy': self.preset}, round_driver=self.driver)

    async def start(self, **kwargs):
        return await self.service.start('alice', 'toy', 'Improve toy', 'request-1',
                                        caps=kwargs.get('caps', CAPS), deadline=self.deadline)

    async def test_two_independent_rounds_promote_then_tie_stop(self):
        first = await self.start()
        activity = first['activity']['id']
        round1 = first['rounds'][0]
        self.driver.stopped(round1)
        settled = await self.service.reconcile('alice', activity)
        self.assertEqual(settled['activity']['status'], 'ready')
        second = await self.service.advance('alice', activity, round1['id'], 'advance-1')
        round2 = second['rounds'][1]
        self.assertEqual(round2['baselineSource']['kind'], 'sourceArtifact')
        self.assertEqual(round2['baselineSource']['metricValue'], 0)
        self.assertEqual(round2['baselineSource']['taskId'], round1['taskId'])
        self.assertNotEqual(round1['taskId'], round2['taskId'])
        self.assertEqual(round2['deadline'], self.deadline)
        await self.service.advance('alice', activity, round1['id'], 'advance-1')
        self.assertEqual(len(self.driver.dispatched), 2)
        self.driver.stopped(round2)
        final = await self.service.reconcile('alice', activity)
        self.assertEqual(final['activity']['stopReason'], 'tie')
        with self.assertRaises(HTTPException):
            await self.service.advance('alice', activity, round2['id'], 'advance-2')
        self.assertEqual(len(self.driver.reserved), 2)

    async def test_lost_ack_restart_and_read_never_dispatch_again(self):
        self.driver.fail_dispatch = True
        with self.assertRaises(TimeoutError):
            await self.start()
        self.service = self.reopen()
        replay = await self.start()
        identifier = replay['activity']['id']
        await self.service.reconcile('alice', identifier)
        self.assertEqual(self.service.inspect('alice', identifier)['activity']['status'], 'unknown')
        self.assertEqual(len(self.driver.dispatched), 1)
        with self.assertRaises(HTTPException):
            await self.service.advance('alice', identifier, replay['rounds'][0]['id'], 'advance')

    async def test_stop_without_evaluation_does_not_promote(self):
        first = await self.start()
        self.driver.stopped(first['rounds'][0], evaluation=False)
        result = await self.service.reconcile('alice', first['activity']['id'])
        self.assertEqual(result['activity']['stopReason'], 'evaluation_unavailable')
        self.assertEqual(result['activity']['baselineSource'], BASELINE)

    async def test_stop_with_unresolved_usage_stays_held(self):
        first = await self.start()
        self.driver.stopped(first['rounds'][0])
        self.store.local_budget_scopes.held = True
        result = await self.service.reconcile('alice', first['activity']['id'])
        self.assertEqual(result['activity']['status'], 'unknown')
        self.assertEqual(result['activity']['baselineSource'], BASELINE)

    async def test_metric_and_source_mismatch_rejected(self):
        first = await self.start()
        round = first['rounds'][0]
        for field, bad in [('candidateValue', float('nan')), ('baselineValue', 17),
                           ('candidateSourceSha256', '0' * 64), ('datasetSha256', '0' * 64)]:
            with self.subTest(field=field):
                self.driver.stopped(round)
                self.driver.observations[round['id']]['evaluation'][field] = bad
                with self.assertRaises(HTTPException):
                    await self.service.reconcile('alice', first['activity']['id'])
        self.assertEqual(self.service.inspect('alice', first['activity']['id'])['activity']['baselineSource'], BASELINE)

    async def test_cancel_fences_new_work_and_stops_original(self):
        first = await self.start()
        identifier = first['activity']['id']
        cancelled = await self.service.cancel('alice', identifier)
        self.assertTrue(cancelled['activity']['cancelRequested'])
        self.assertEqual(self.driver.cancelled, [first['rounds'][0]['taskId']])
        self.driver.stopped(first['rounds'][0])
        final = await self.service.reconcile('alice', identifier)
        self.assertEqual(final['activity']['stopReason'], 'cancelled')
        await self.service.cancel('alice', identifier)
        self.assertEqual(self.service.inspect('alice', identifier)['activity']['status'], 'stopped')
        self.assertEqual(len(self.driver.dispatched), 1)

    async def test_budget_exhaustion_stops_without_second_reservation(self):
        first = await self.start(caps={**CAPS, 'toolCalls': 4})
        self.driver.stopped(first['rounds'][0])
        await self.service.reconcile('alice', first['activity']['id'])
        final = await self.service.advance('alice', first['activity']['id'], first['rounds'][0]['id'], 'advance')
        self.assertEqual(final['activity']['stopReason'], 'budget_exhausted')
        self.assertEqual(len(final['rounds']), 1)
        self.assertEqual(len(self.driver.reserved), 1)

    async def test_owner_and_request_conflict(self):
        first = await self.start()
        with self.assertRaises(HTTPException) as denied:
            self.service.inspect('bob', first['activity']['id'])
        self.assertEqual(denied.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            await self.start(caps={**CAPS, 'toolCalls': 9})
        self.assertEqual(len(self.driver.reserved), 1)

    async def test_reservation_failure_rolls_back_activity_and_scope(self):
        def fail(*args):
            raise HTTPException(409, 'NATIVE_RESERVATION_FAILED')
        self.driver.reserve = fail
        with self.assertRaises(HTTPException):
            await self.start()
        with self.store.transaction() as conn:
            self.assertEqual(conn.execute(select(self.service.activities)).all(), [])
            self.assertEqual(conn.execute(select(self.store.local_budget_scopes.rows)).all(), [])

    async def test_expired_or_unmetered_rejected_before_dispatch(self):
        self.deadline = time.time() - 1
        with self.assertRaises(HTTPException):
            await self.start()
        self.deadline = time.time() + 100
        with self.assertRaises(HTTPException):
            await self.start(caps={**CAPS, 'tokenLimit': 10, 'amountMicros': 10, 'currency': 'USD'})
        self.assertEqual(self.driver.dispatched, [])

    async def test_next_round_deadline_and_round_limit_are_terminal(self):
        first = await self.start()
        self.driver.stopped(first['rounds'][0])
        await self.service.reconcile('alice', first['activity']['id'])
        with patch('agent_factory_research.research_iterations.time.time', return_value=self.deadline - 1):
            result = await self.service.advance('alice', first['activity']['id'], first['rounds'][0]['id'], 'advance')
        self.assertEqual(result['activity']['stopReason'], 'deadline')
        replay = await self.service.advance('alice', first['activity']['id'], first['rounds'][0]['id'], 'advance')
        self.assertEqual(replay['activity']['stopReason'], 'deadline')
        self.assertEqual(len(self.driver.dispatched), 1)

    async def test_cancel_between_reserve_and_dispatch_never_starts_work(self):
        original = self.service._dispatch
        async def cancel_before_dispatch(owner, identifier):
            await self.service.cancel(owner, identifier)
            await original(owner, identifier)
        self.service._dispatch = cancel_before_dispatch
        result = await self.start()
        self.assertEqual(result['activity']['status'], 'canceling')
        self.assertEqual(self.driver.dispatched, [])
        self.driver.stopped(result['rounds'][0], evaluation=False)
        self.driver.observations[result['rounds'][0]['id']]['runId'] = None
        settled = await self.service.reconcile('alice', result['activity']['id'])
        self.assertEqual(settled['activity']['stopReason'], 'cancelled')
        self.assertEqual(self.driver.dispatched, [])

    async def test_expiry_after_reservation_cancels_without_crossing_dispatch_fence(self):
        original = self.service._dispatch
        async def expire_before_dispatch(owner, identifier):
            with patch('agent_factory_research.research_iterations.time.time', return_value=self.deadline):
                await original(owner, identifier)
        self.service._dispatch = expire_before_dispatch
        result = await self.start()
        round = result['rounds'][0]
        self.assertFalse(round['dispatchAttempted'])
        self.assertEqual(result['activity']['stopReason'], 'deadline')
        self.assertEqual(self.driver.cancelled, [round['taskId']])
        self.assertEqual(self.driver.dispatched, [])
        self.driver.stopped(round, evaluation=False)
        self.driver.observations[round['id']]['runId'] = None
        settled = await self.service.reconcile('alice', result['activity']['id'])
        self.assertEqual(settled['activity']['status'], 'stopped')
        self.assertEqual(settled['activity']['stopReason'], 'deadline')
        self.assertEqual(self.driver.dispatched, [])

    async def test_expiry_of_dispatched_paused_round_cancels_original_and_keeps_hold(self):
        first = await self.start()
        round = first['rounds'][0]
        self.driver.observations[round['id']] = dict(state='pending', taskId=round['taskId'],
                                                    runId='original-run', approvalRequired=True)
        self.store.local_budget_scopes.held = True
        with patch('agent_factory_research.research_iterations.time.time', return_value=self.deadline + 1):
            pending = await self.service.reconcile('alice', first['activity']['id'])
        self.assertEqual(self.driver.cancelled, [round['taskId']])
        self.assertEqual(self.driver.dispatched, [round['taskId']])
        self.assertEqual(pending['activity']['status'], 'canceling')
        self.assertEqual(pending['activity']['stopReason'], 'deadline')
        self.driver.stopped(round, evaluation=False)
        self.driver.observations[round['id']]['runId'] = 'original-run'
        still_held = await self.service.reconcile('alice', first['activity']['id'])
        self.assertEqual(still_held['activity']['status'], 'canceling')
        self.store.local_budget_scopes.held = False
        settled = await self.service.reconcile('alice', first['activity']['id'])
        self.assertEqual(settled['activity']['status'], 'stopped')
        self.assertEqual(settled['activity']['stopReason'], 'deadline')
        self.assertEqual(self.driver.dispatched, [round['taskId']])

    async def test_definite_preflight_rejection_is_recorded_without_reopening_dispatch(self):
        rejected = []
        self.store.task = lambda identity, owner: {'id': identity, 'run_id': None}
        self.store.admission_failed = lambda identity, message: rejected.append(identity)
        async def reject(owner, round):
            return {'notSubmitted': True, 'reason': 'preflight_rejected'}
        self.driver.dispatch = reject
        first = await self.start()
        round = first['rounds'][0]
        self.assertTrue(round['dispatchAttempted'])
        self.assertTrue(round['dispatchRejected'])
        self.assertEqual(rejected, [round['taskId']])
        self.driver.stopped(round, evaluation=False)
        self.driver.observations[round['id']]['runId'] = None
        final = await self.service.reconcile('alice', first['activity']['id'])
        self.assertEqual(final['activity']['status'], 'stopped')
        self.assertEqual(final['activity']['stopReason'], 'evaluation_unavailable')
        await self.service._dispatch('alice', first['activity']['id'])
        self.assertEqual(rejected, [round['taskId']])
        self.assertEqual(self.driver.dispatched, [])

    async def test_original_task_lookup_owner_scoped_and_detached(self):
        first = await self.start()
        round = first['rounds'][0]
        found = self.service.round_for_task('alice', round['taskId'])
        self.assertEqual(found, round)
        found['baselineSource']['sha256'] = 'mutated'
        self.assertEqual(self.service.round_for_task('alice', round['taskId']), round)
        for owner, task in [('bob', round['taskId']), ('alice', 'unrelated')]:
            with self.assertRaises(HTTPException) as denied:
                self.service.round_for_task(owner, task)
            self.assertEqual(denied.exception.status_code, 404)
        self.assertEqual(len(self.driver.dispatched), 1)

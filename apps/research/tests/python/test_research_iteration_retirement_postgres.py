"""PG/profile retirement without an ORX installation or native worker.

The stopped case supplies a controlled native-stop observation. It proves
original persisted task/tool accounting, not real ORX/process stop evidence.
"""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.native_component import component_identity
from agent_factory_server.main import create_app, factory_state
from agent_factory_research.orx_local import TaskLocalORXProvider
from agent_factory_research.research_iteration_profile import PROFILE_ID, local_iteration_profile_settings
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ResearchIterationRetirementPostgresTests(unittest.TestCase):
    def setUp(self):
        database = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        workspace = Path(self.enterContext(TemporaryDirectory(prefix='iteration-retirement-')))
        # Metadata installation accepts trusted paths, but this test must never
        # instantiate an adapter or start either toolchain or native lifecycle.
        provider = TaskLocalORXProvider(binary=workspace / 'unavailable-orx',
            source_archive=workspace / 'unavailable-source', git_binary=workspace / 'unavailable-git',
            python_binary=workspace / 'unavailable-python')
        self.enterContext(patch.object(TaskLocalORXProvider, 'create_experiment_adapter',
            side_effect=AssertionError('Retirement metadata must not launch ORX')))
        settings = local_iteration_profile_settings(db_url=database.url, workspace=workspace, provider=provider)
        self.app = create_app(settings)
        self.state = factory_state(self.app)
        self.store, self.auth, self.research = self.state['store'], self.state['auth'], self.state['research']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.addCleanup(self.store.dispose_root_locks)
        self.addCleanup(self.research.release)
        self.service = self.research.iterations
        self.driver = self.service.driver
        self.coordinator = self.research.iteration_coordinator
        self.submit = self.enterContext(patch.object(self.state['bridge'], 'submit', new_callable=AsyncMock))
        self.find_original = self.enterContext(patch.object(self.state['bridge'], 'find_original_run',
                                                           new_callable=AsyncMock, return_value=None))
        self.caps = dict(rounds=2, toolCalls=16, tokenLimit=None, amountMicros=None, currency=None)
        self.deadline = time.time() + 300

    def start(self):
        return asyncio.run(self.service.start('alice', PROFILE_ID, 'Retire only this original local round',
            'retirement-original', caps=self.caps, deadline=self.deadline))

    def only_activity(self):
        with self.store.transaction(read_only=True) as conn:
            return conn.execute(select(self.service.activities.c.id)).scalar_one()

    def disable_and_retire(self, activity):
        self.auth.directory.set_disabled('alice', True)
        with self.assertRaises(HTTPException) as denied:
            self.auth.require_member('alice')
        self.assertEqual(denied.exception.status_code, 403)
        asyncio.run(self.coordinator._one('alice', activity))
        with self.assertRaises(HTTPException):
            self.service.inspect('alice', activity)
        return self.service._inspect('alice', activity)

    def assert_retired_identity(self, before, after):
        self.assertEqual(len(after['rounds']), 1)
        for key in ('id', 'taskId', 'planId', 'planSha256', 'allocationId', 'requestId', 'intentSha256'):
            self.assertEqual(after['rounds'][0][key], before['rounds'][0][key])
        self.assertEqual(after['activity']['baselineSource'], before['activity']['baselineSource'])
        self.assertEqual(after['activity']['stopReason'], 'owner_unavailable')
        self.assertTrue(after['activity']['cancelRequested'])
        self.assertEqual(after['budget']['allocatedRounds'], 1)
        self.assertEqual(after['budget']['state'], 'CANCELLED')
        self.assertIsNone(after['budget']['usage'])

    def test_disabled_before_dispatch_fence_rejects_original_and_settles_zero(self):
        with patch.object(self.service, '_dispatch', new_callable=AsyncMock):
            initial = self.start()
        round = initial['rounds'][0]
        self.assertFalse(round['dispatchAttempted'])
        result = self.disable_and_retire(initial['activity']['id'])
        self.assert_retired_identity(initial, result)
        task = self.store.task(round['taskId'], 'alice')
        self.assertEqual(task['admission'], 'rejected')
        self.assertTrue(task['terminal'])
        self.assertIsNone(task['run_id'])
        self.assertEqual(result['rounds'][0]['state'], 'SETTLED')
        self.assertEqual(result['rounds'][0]['settlement']['toolCalls'], 0)
        self.assertEqual(result['budget']['heldToolCalls'], 0)
        self.assertEqual(result['activity']['status'], 'stopped')
        self.submit.assert_not_awaited()

    def test_disabled_unknown_dispatch_without_receipt_stays_held_and_never_resubmits(self):
        self.submit.side_effect = TimeoutError('Controlled original native acknowledgement loss')
        with self.assertRaises(TimeoutError):
            self.start()
        activity = self.only_activity()
        before = self.service.inspect('alice', activity)
        self.assertTrue(before['rounds'][0]['dispatchAttempted'])
        result = self.disable_and_retire(activity)
        self.assert_retired_identity(before, result)
        self.assertEqual(result['rounds'][0]['state'], 'UNKNOWN')
        self.assertEqual(result['budget']['heldToolCalls'], 8)
        self.assertEqual(result['budget']['allocations'][0]['state'], 'BOUND')
        self.assertIsNone(self.store.task(before['rounds'][0]['taskId'], 'alice')['run_id'])
        asyncio.run(self.coordinator._one('alice', activity))
        again = self.service._inspect('alice', activity)
        self.assertEqual(again, result)
        self.assertEqual(self.submit.await_count, 1)
        self.assertGreaterEqual(self.find_original.await_count, 1)

    def test_disabled_positive_original_stop_settles_persisted_tool_usage_without_promotion(self):
        run_id = str(uuid4())
        self.submit.return_value = {'run_id': run_id}
        initial = self.start()
        round = initial['rounds'][0]
        task = self.store.task(round['taskId'], 'alice')
        plan = self.store.plan(round['planId'], 'alice')
        kind, component = component_identity(plan)
        stamp = int(time.time())
        self.store.native_db.enqueue_job(dict(id=run_id, component_type=kind, component_id=component,
            job_type='run', session_id=task['id'], user_id='alice', payload={}, status='queued',
            attempt=0, max_attempts=1, available_at=stamp, created_at=stamp))
        context = SimpleNamespace(run_id=run_id, session_id=task['id'], user_id='alice')
        charged = self.store.delegation.consume_tool_budget(context, 'controlled-original-tool', plan['tools'][0])
        self.assertTrue(charged['charged'])
        self.assertFalse(self.store.delegation.consume_tool_budget(
            context, 'controlled-original-tool', plan['tools'][0])['charged'])
        self.store.observed(task, 'completed', True)
        native_stop = dict(id=run_id, session_id=task['id'], user_id='alice', status='completed')
        # A controlled stop seam, never presented as a real native/ORX run.
        # Do not let the real observer overwrite it from the deliberately queued
        # metadata ticket; production native-stop integration has separate tests.
        with patch.object(self.store.lifecycle_observer, 'observe_root', new_callable=AsyncMock), \
                patch.object(self.driver, '_native', return_value=native_stop), \
                patch.object(self.driver, 'verified_evaluation', side_effect=AssertionError('No promotion after revocation')):
            result = self.disable_and_retire(initial['activity']['id'])
        self.assert_retired_identity(initial, result)
        self.assertEqual(result['activity']['status'], 'stopped')
        self.assertEqual(result['rounds'][0]['runId'], run_id)
        self.assertEqual(result['rounds'][0]['settlement']['toolCalls'], 1)
        self.assertEqual(result['budget']['settledToolCalls'], 1)
        self.assertEqual(result['budget']['heldToolCalls'], 0)
        self.assertEqual(self.submit.await_count, 1)
        asyncio.run(self.coordinator._one('alice', initial['activity']['id']))
        self.assertEqual(self.service._inspect('alice', initial['activity']['id']), result)

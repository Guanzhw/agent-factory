"""Native queue second attempt precedes observer; no provider replay after rejection."""
import asyncio
from dataclasses import replace
import os
from threading import Event
import unittest
from unittest.mock import patch

from agno.os.job_queue import QueueWorker
from agno.run import RunContext
from agno.exceptions import InputCheckError

from agent_factory.lifecycle_observer import FactoryLifecycleObserver
from agent_factory.store import Store
import test_research_qa_postgres as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class ResearchQAProtocolFencePostgresTests(unittest.TestCase):
    def run_ordered(self, *, malicious=False, transient=False):
        fixture = fixtures.ResearchQANativeTests('runTest')
        self.addCleanup(fixture.doCleanups)
        release = Event()
        self.addCleanup(release.set)
        attempts, states, observed = [], [], []
        original_claim = QueueWorker._execute_claimed_inner
        original_observe = FactoryLifecycleObserver.observe_root
        original_state = fixtures.factory_state
        def state(app):
            result = original_state(app)
            states.append(result)
            return result
        async def claim(worker, job, ownership=None):
            attempts.append({key: job[key] for key in ('id', 'attempt', 'max_attempts', 'session_id')})
            try:
                return await original_claim(worker, job, ownership)
            finally:
                if job['attempt'] == 2:
                    release.set()
        async def observe(observer, identifier):
            if not await asyncio.to_thread(release.wait, 20):
                raise AssertionError('Second native attempt did not finish before observer')
            observed.append(identifier)
            return await original_observe(observer, identifier)
        with patch.object(QueueWorker, '_execute_claimed_inner', claim), \
                patch.object(FactoryLifecycleObserver, 'observe_root', observe), \
                patch.object(fixtures, 'factory_state', state):
            try:
                fixture.run_qa(malicious=malicious, transient=transient)
            finally:
                release.set()
        self.assertEqual([entry['attempt'] for entry in attempts], [1, 2])
        self.assertEqual({entry['max_attempts'] for entry in attempts}, {2})
        self.assertEqual(len({entry['id'] for entry in attempts}), 1)
        self.assertEqual(len({entry['session_id'] for entry in attempts}), 1)
        self.assertTrue(observed)
        return states[0]['store']

    def test_permanent_rejection_fences_second_attempt_before_observer_and_survives_store_reopen(self):
        store = self.run_ordered(malicious=True)
        task = store.tasks('alice')[0]
        self.assertTrue(task['cancel_requested'])
        self.assertTrue(task['terminal'])
        self.assertEqual(task['body']['stoppedStatus'], 'failed')
        rejection = [event for event in store.events(task['id']) if event['type'] == 'protected_denied'
                     and event['data'].get('code') == 'PERSONAL_MODEL_TOOL_NOT_DECLARED']
        self.assertEqual(len(rejection), 1)
        reopened = Store(store.settings.db_url, store.settings)
        self.addCleanup(reopened.engine.dispose)
        self.addCleanup(reopened.dispose_root_locks)
        self.assertTrue(reopened.cancellation_requested(task['id']))
        self.assertTrue(reopened.has_failures(task['id']))
        self.assertEqual(reopened.task(task['id'])['run_id'], task['run_id'])

    def test_ordinary_transport_failure_retains_actual_second_attempt_and_success(self):
        store = self.run_ordered(transient=True)
        task = store.tasks('alice')[0]
        self.assertEqual(task['body']['stoppedStatus'], 'completed')
        self.assertFalse(task['cancel_requested'])
        self.assertFalse(store.has_failures(task['id']))
        context = RunContext(session_id=task['id'], run_id=task['run_id'], user_id='alice')
        events_before = store.events(task['id'])
        original_cancel = store.request_cancel
        def fail_after_cancel(identifier):
            original_cancel(identifier)
            raise RuntimeError('Synthetic transaction failure after cancel write')
        with patch.object(store, 'request_cancel', fail_after_cancel), self.assertRaisesRegex(RuntimeError, 'Synthetic transaction'):
            store.reject_model_protocol(context)
        self.assertFalse(store.task(task['id'])['cancel_requested'])
        self.assertEqual(store.events(task['id']), events_before)
        for field, value in (('session_id', task['run_id']), ('run_id', 'foreign-run'), ('user_id', 'bob')):
            changed = replace(context, **{field: value})
            with self.assertRaises(InputCheckError):
                store.reject_model_protocol(changed)
        self.assertFalse(store.task(task['id'])['cancel_requested'])
        self.assertEqual(store.events(task['id']), events_before)

"""Wired native model/tool boundaries after budget revocation; no external IO."""
import os
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from agno.models.message import Message
from agno.run import RunContext
from agno.run.agent import RunOutput
from fastapi import HTTPException

from agent_factory.model_dispatch import DelegatingModel
from agent_factory.store import digest
from core_native_fixture import FixtureModel
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AssistantBudgetGuardPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        fixture = self.fixture
        definition = fixture.publish_http()
        proposal = fixture.composition.propose('alice', 'Perform a text audit for original synthetic evidence',
            application=definition['id'], request_id='guard-proposal')
        plan = fixture.composition.accept('alice', proposal['id'], 'guard-accept')
        store = fixture.store
        self.scopes = store.local_budget_scopes
        self.deadline = time.time() + 300
        # Unmetered allocation exercises the execution guard, not a coincidental
        # provider-ledger denial; tool and round bounds still apply.
        caps = {'rounds': 1, 'toolCalls': 10, 'tokenLimit': None,
                'amountMicros': None, 'currency': None}
        self.scopes.create_scope('alice', 'entry-scope', digest({'commitment': 'synthetic'}), caps, self.deadline)
        with store.transaction() as conn:
            self.scopes.allocate(conn, 'alice', 'entry-scope', 'entry-allocation', digest(plan), caps)
            task, _ = store.reserve_task(plan, 'entry-original-request')
            self.scopes.bind_root(conn, 'alice', 'entry-allocation', task['id'], digest(plan))
        run_id = str(uuid4())
        store.accept(task['id'], run_id)
        self.task_id = task['id']
        self.context = RunContext(run_id=run_id, session_id=task['id'], user_id='alice',
            session_state={'factory_envelope': {'plan_ref': plan['id'], 'user_id': 'alice',
                'task_id': task['id'], 'request_id': task['request_id']}})
        response = RunOutput(run_id=run_id, session_id=task['id'], user_id='alice', session_state=self.context.session_state)
        self.model = DelegatingModel(store.execution_bindings)._select((), {'run_response': response})
        self.checksum = next(tool for tool in store.execution_bindings.tools_for(plan, self.context)
                             if getattr(tool, '__name__', '') == 'checksum')

    def exercise_boundaries(self, close):
        original = FixtureModel._response
        with patch.object(FixtureModel, '_response', autospec=True,
                          side_effect=lambda model, messages: original(model, messages)) as provider:
            self.model.invoke(messages=[Message(role='user', content='Synthetic evidence')])
            self.checksum(text='Before boundary', run_context=self.context)
            self.assertEqual(provider.call_count, 1)
            store = self.fixture.store
            completed_before = [event for event in store.events(self.task_id) if event['type'] == 'checksum_completed']
            self.assertEqual(len(completed_before), 1)
            close()
            for entry in (lambda: self.model.invoke(messages=[Message(role='user', content='After boundary')]),
                          lambda: self.checksum(text='After boundary', run_context=self.context)):
                with self.assertRaises(HTTPException) as denied:
                    entry()
                self.assertEqual(denied.exception.status_code, 409)
                self.assertEqual(denied.exception.detail, 'LOCAL_BUDGET_CLOSED_OR_EXPIRED')
            self.assertEqual(provider.call_count, 1)
            self.assertEqual([event for event in store.events(self.task_id)
                              if event['type'] == 'checksum_completed'], completed_before)
            self.assertEqual(store.task(self.task_id)['id'], self.task_id)
            self.assertEqual(self.scopes.inspect('alice', 'entry-scope')['allocations'][0]['state'], 'BOUND')

    def test_cancelled_scope_blocks_retained_native_model_and_tool(self):
        self.exercise_boundaries(lambda: self.scopes.cancel('alice', 'entry-scope'))

    def test_expired_scope_blocks_retained_native_model_and_tool(self):
        with patch('agent_factory.local_budget_scopes.time', wraps=time) as clock:
            clock.time.return_value = self.deadline - 1
            self.exercise_boundaries(lambda: setattr(clock.time, 'return_value', self.deadline + 1))

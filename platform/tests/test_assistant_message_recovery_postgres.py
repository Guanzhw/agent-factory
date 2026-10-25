"""Real reservation barriers; synthetic native component, no external model."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from functools import partial
import os
from threading import Barrier, Event, Lock
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from agent_factory.assistant_messages import SendAssistantMessage
from agent_factory.store import digest
import test_assistant_messages_postgres as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AssistantMessageRecoveryPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.AssistantMessagesPostgresTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.fixture = self.base.fixture
        self.messages = self.fixture.state['assistant_messages']
        self.scopes = self.fixture.store.local_budget_scopes
        caps = {'rounds': 1, 'toolCalls': 10, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        self.scopes.create_scope('bob', 'recovery-scope', digest({'scope': 'synthetic'}), caps, time.time() + 120)
        with self.fixture.store.transaction() as conn:
            self.scopes.allocate(conn, 'bob', 'recovery-scope', 'recovery-allocation', digest(self.base.body), caps)

    def reserve(self):
        message, fresh = self.messages._reserve('alice', self.base.endpoint_id,
                                               SendAssistantMessage.model_validate(self.base.body))
        self.assertTrue(fresh)
        return message

    def recover(self, message):
        return self.fixture.client.portal.call(partial(self.messages.recover, 'bob', message['id'],
                                                      allocation_id='recovery-allocation'))

    def test_two_recoverers_both_observe_no_task_but_native_dispatches_once(self):
        message = self.reserve()
        barrier, lock, observations = Barrier(2), Lock(), []
        original = self.messages._receipt

        def receipt(value):
            result = original(value)
            with lock:
                wait = len(observations) < 2
                if wait:
                    observations.append(result)
            if wait:
                self.assertIsNone(result['taskId'])
                barrier.wait(10)
            return result

        with patch.object(self.messages, '_receipt', receipt), \
                patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(wraps=self.fixture.state['bridge'].submit)) as submit:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.recover(message), range(2)))
            self.assertEqual(submit.await_count, 1)
        ids = {result['delivery']['taskId'] for result in results}
        self.assertEqual(len(ids), 1)
        self.assertNotIn(None, ids)
        self.assertEqual(len(self.fixture.store.tasks('bob')), 1)
        self.fixture.login('bob')
        detail = self.fixture.wait_job(ids.pop())
        self.assertEqual(detail['job']['status'], 'completed', detail)

    def test_original_sender_paused_before_start_resumes_without_second_dispatch(self):
        saved, resume = Event(), Event()
        original = self.messages._reserve
        captured = []

        def reserve(*args):
            result = original(*args)
            captured.append(result[0])
            saved.set()
            if not resume.wait(10):
                raise TimeoutError('test sender barrier not released')
            return result

        with patch.object(self.messages, '_reserve', reserve), \
                patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(wraps=self.fixture.state['bridge'].submit)) as submit:
            with ThreadPoolExecutor(max_workers=1) as pool:
                sender = pool.submit(self.fixture.client.post, self.base.path, json=self.base.body)
                try:
                    self.assertTrue(saved.wait(10))
                    recovered = self.recover(captured[0])
                finally:
                    resume.set()
                response = sender.result(timeout=15)
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()['delivery']['taskId'], recovered['delivery']['taskId'])
            self.assertEqual(submit.await_count, 1)
        self.fixture.login('bob')
        detail = self.fixture.wait_job(recovered['delivery']['taskId'])
        self.assertEqual(detail['job']['status'], 'completed', detail)

    def test_reservation_committed_before_bridge_interruption_remains_original(self):
        message = self.reserve()
        async def interrupted(*args, **kwargs):
            # A different connection must already see the task and its allocation.
            with self.fixture.store.engine.connect() as conn:
                rows = conn.exec_driver_sql('SELECT task_id FROM af_local_budget_allocations WHERE id=\'recovery-allocation\'').all()
                self.assertIsNotNone(rows[0][0])
                self.assertEqual(len(self.fixture.store.tasks('bob')), 1)
            raise TimeoutError('synthetic interruption at native submission boundary')
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(side_effect=interrupted)) as submit:
            first = self.recover(message)
            self.assertEqual(first['delivery']['state'], 'unknown')
            self.assertEqual(self.recover(message), first)
            self.assertEqual(submit.await_count, 1)
        self.fixture.stop(); self.fixture.start()
        self.messages = self.fixture.state['assistant_messages']
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            self.assertEqual(self.recover(message), first)
            submit.assert_not_called()

    def test_native_acceptance_with_lost_ack_is_never_resubmitted(self):
        message = self.reserve()
        original = self.fixture.state['bridge'].submit
        async def lose_ack(*args, **kwargs):
            await original(*args, **kwargs)
            raise TimeoutError('synthetic loss after actual native acceptance')
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(side_effect=lose_ack)) as submit:
            first = self.recover(message)
            self.assertIsNotNone(first['delivery']['taskId'])
            repeated = self.recover(message)
            self.assertEqual(repeated['delivery']['taskId'], first['delivery']['taskId'])
            self.assertEqual(submit.await_count, 1)
        self.fixture.login('bob')
        detail = self.fixture.wait_job(first['delivery']['taskId'])
        self.assertEqual(detail['job']['status'], 'completed', detail)

    def test_process_interruption_after_reservation_does_not_retry_reserved_task(self):
        class SimulatedProcessExit(BaseException):
            pass
        message = self.reserve()
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(side_effect=SimulatedProcessExit)) as submit:
            with self.assertRaises(SimulatedProcessExit):
                asyncio.run(self.messages.recover('bob', message['id'], allocation_id='recovery-allocation'))
            receipt = self.messages.read('bob', message['id'])
            self.assertEqual(receipt['delivery']['state'], 'reserved')
            self.assertIsNotNone(receipt['delivery']['taskId'])
            self.assertEqual(submit.await_count, 1)
        self.fixture.stop(); self.fixture.start()
        self.messages = self.fixture.state['assistant_messages']
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            self.assertEqual(self.recover(message), receipt)
            submit.assert_not_called()

    def start_original(self, message, allocation_id):
        endpoint = self.messages.endpoints.resolve(message['endpoint_id'])
        body = self.messages._start_body(message, endpoint)
        return self.fixture.client.portal.call(partial(self.messages.runs.start, 'bob', body,
                                                      allocation_id=allocation_id))

    def test_binding_failure_rolls_back_task_and_allocation_before_dispatch(self):
        message = self.reserve()
        original = self.scopes.bind_root
        def fail_after_binding(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('synthetic failure after allocation update')
        with patch.object(self.scopes, 'bind_root', fail_after_binding), \
                patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            with self.assertRaisesRegex(RuntimeError, 'after allocation update'):
                self.recover(message)
            submit.assert_not_called()
        self.assertEqual(self.fixture.store.tasks('bob'), [])
        with self.fixture.store.engine.connect() as conn:
            row = conn.exec_driver_sql("SELECT task_id,state FROM af_local_budget_allocations WHERE id='recovery-allocation'").one()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], 'ALLOCATED')
        self.assertEqual(self.messages.read('bob', message['id'])['delivery']['state'], 'prepared')

    def test_original_binding_reentry_and_other_allocation_rejection(self):
        message = self.reserve()
        caps = {'rounds': 1, 'toolCalls': 10, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        self.scopes.create_scope('bob', 'other-scope', digest({'scope': 'other'}), caps, time.time() + 120)
        with self.fixture.store.transaction() as conn:
            self.scopes.allocate(conn, 'bob', 'other-scope', 'other-allocation', digest(self.base.body), caps)
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('synthetic lost ack'))) as submit:
            first = self.start_original(message, 'recovery-allocation')
            repeated = self.start_original(message, 'recovery-allocation')
            self.assertEqual(repeated['job']['id'], first['job']['id'])
            with self.assertRaises(HTTPException) as caught:
                self.start_original(message, 'other-allocation')
            self.assertEqual(caught.exception.detail, 'LOCAL_BUDGET_BINDING_CONFLICT')
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(len(self.fixture.store.tasks('bob')), 1)

    def test_unbudgeted_original_task_cannot_be_bound_later(self):
        message = self.reserve()
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('synthetic lost ack'))) as submit:
            first = self.start_original(message, None)
            with self.assertRaises(HTTPException) as caught:
                self.start_original(message, 'recovery-allocation')
            self.assertEqual(caught.exception.detail, 'LOCAL_BUDGET_BINDING_CONFLICT')
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.fixture.store.tasks('bob')[0]['id'], first['job']['id'])
        with self.fixture.store.engine.connect() as conn:
            bound = conn.exec_driver_sql("SELECT task_id FROM af_local_budget_allocations WHERE id='recovery-allocation'").scalar_one()
        self.assertIsNone(bound)

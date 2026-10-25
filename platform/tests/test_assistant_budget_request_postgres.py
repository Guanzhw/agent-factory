"""Public handoff must retain the trusted request's original budget binding."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import httpx
from sqlalchemy import select

from agent_factory.application_runs import factory_request_id
from agent_factory.store import digest
from agent_factory.remote_handoff import HandoffTarget
import test_assistant_message_recovery_postgres as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AssistantBudgetRequestPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.AssistantMessageRecoveryPostgresTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.fixture, self.scopes = self.base.fixture, self.base.scopes
        self.message = self.base.reserve()
        self.request_id = factory_request_id(self.base.messages._request_id(self.message))
        self.fixture.login('bob')

    def handoff_race(self, *, cancel):
        prepared, resume = Event(), Event()
        runs = self.base.messages.runs
        original = runs._prepare
        captured = []

        def pause(*args):
            result = original(*args)
            captured.append(result)
            prepared.set()
            if not resume.wait(15):
                raise TimeoutError('trusted preparation barrier not released')
            return result

        bridge = self.fixture.state['bridge']
        with patch.object(runs, '_prepare', pause), patch.object(bridge, 'submit', AsyncMock(wraps=bridge.submit)) as submit:
            with ThreadPoolExecutor(max_workers=1) as pool:
                trusted = pool.submit(self.base.start_original, self.message, 'recovery-allocation')
                try:
                    self.assertTrue(prepared.wait(10))
                    plan, key = captured[0]
                    self.assertEqual(key, self.request_id)
                    if cancel:
                        self.scopes.cancel('bob', 'recovery-scope')
                    response = self.fixture.client.post('/api/factory/instances',
                        json={'planId': plan['id'], 'requestId': key})
                    if cancel:
                        self.assertEqual(response.status_code, 409, response.text)
                        self.assertEqual(self.fixture.store.tasks('bob'), [])
                        self.assertEqual(submit.await_count, 0)
                    else:
                        self.assertEqual(response.status_code, 202, response.text)
                        task_id = self.fixture.store.tasks('bob')[0]['id']
                        with self.fixture.store.engine.connect() as conn:
                            bound = conn.execute(select(self.scopes.allocations.c.task_id).where(
                                self.scopes.allocations.c.id == 'recovery-allocation')).scalar_one()
                        self.assertEqual(bound, task_id)
                        self.assertEqual(submit.await_count, 1)
                finally:
                    resume.set()
                if cancel:
                    with self.assertRaises(HTTPException) as caught:
                        trusted.result(timeout=15)
                    self.assertEqual(caught.exception.status_code, 409)
                    self.assertEqual(submit.await_count, 0)
                else:
                    result = trusted.result(timeout=15)
                    self.assertEqual(result['job']['id'], task_id)
                    self.assertEqual(submit.await_count, 1)
        if not cancel:
            detail = self.fixture.wait_job(task_id)
            self.assertEqual(detail['job']['status'], 'completed', detail)

    def test_public_handoff_wins_reservation_but_inherits_original_budget(self):
        self.handoff_race(cancel=False)

    def test_cancelled_scope_blocks_public_handoff_and_original_trusted_start(self):
        self.handoff_race(cancel=True)

    def test_unbudgeted_task_cannot_be_adopted_by_request_binding(self):
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('synthetic lost ack'))) as submit:
            first = self.base.start_original(self.message, None)
            with self.assertRaises(HTTPException) as caught:
                with self.fixture.store.transaction() as conn:
                    self.scopes.bind_request(conn, 'bob', 'recovery-allocation', self.request_id)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(self.fixture.store.tasks('bob')[0]['id'], first['job']['id'])
        with self.fixture.store.engine.connect() as conn:
            task_id = conn.execute(select(self.scopes.allocations.c.task_id).where(
                self.scopes.allocations.c.id == 'recovery-allocation')).scalar_one()
        self.assertIsNone(task_id)

    def test_request_binding_is_idempotent_but_cannot_change_allocation(self):
        caps = {'rounds': 1, 'toolCalls': 10, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        self.scopes.create_scope('bob', 'other-scope', digest({'scope': 'other'}), caps, time.time() + 120)
        with self.fixture.store.transaction() as conn:
            self.scopes.allocate(conn, 'bob', 'other-scope', 'other-allocation', digest(self.base.base.body), caps)
        for _ in range(2):
            with self.fixture.store.transaction() as conn:
                self.scopes.bind_request(conn, 'bob', 'recovery-allocation', self.request_id)
        with self.assertRaises(HTTPException) as caught:
            with self.fixture.store.transaction() as conn:
                self.scopes.bind_request(conn, 'bob', 'other-allocation', self.request_id)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.fixture.store.tasks('bob'), [])

    def test_other_plan_cannot_claim_budgeted_request_before_or_after_prepare(self):
        messages = self.base.messages
        endpoint = messages.endpoints.resolve(self.message['endpoint_id'])
        body = messages._start_body(self.message, endpoint)
        other_body = body.model_copy(update={'requestId': 'other-prepared-request', 'goal': 'A different synthetic question.'})
        other_plan, _ = messages.runs._prepare('bob', other_body)
        with self.fixture.store.transaction() as conn:
            self.scopes.bind_request(conn, 'bob', 'recovery-allocation', self.request_id)
        bridge = self.fixture.state['bridge']
        with patch.object(bridge, 'submit', AsyncMock(wraps=bridge.submit)) as submit:
            for prepared in (False, True):
                with self.subTest(original_prepared=prepared):
                    if prepared:
                        original_plan, key = messages.runs._prepare('bob', body)
                        self.assertEqual(key, self.request_id)
                        self.assertNotEqual(original_plan['id'], other_plan['id'])
                    response = self.fixture.client.post('/api/factory/instances',
                        json={'planId': other_plan['id'], 'requestId': self.request_id})
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(self.fixture.store.tasks('bob'), [])
                    submit.assert_not_called()
            result = self.base.start_original(self.message, 'recovery-allocation')
            self.assertEqual(result['planId'], original_plan['id'])
            self.assertEqual(submit.await_count, 1)
        detail = self.fixture.wait_job(result['job']['id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)

    def test_bound_plan_cannot_start_with_an_unbudgeted_new_request_key(self):
        messages = self.base.messages
        endpoint = messages.endpoints.resolve(self.message['endpoint_id'])
        body = messages._start_body(self.message, endpoint)
        with self.fixture.store.transaction() as conn:
            self.scopes.bind_request(conn, 'bob', 'recovery-allocation', self.request_id)
        plan, _ = messages.runs._prepare('bob', body)
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            response = self.fixture.client.post('/api/factory/instances',
                json={'planId': plan['id'], 'requestId': 'replacement-unbudgeted-key'})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['message'], 'LOCAL_BUDGET_REQUEST_PLAN_CONFLICT')
            self.assertEqual(self.fixture.store.tasks('bob'), [])
            submit.assert_not_called()

    def test_local_budget_root_cannot_select_remote_before_or_after_reservation(self):
        messages = self.base.messages
        endpoint = messages.endpoints.resolve(self.message['endpoint_id'])
        body = messages._start_body(self.message, endpoint)
        with self.fixture.store.transaction() as conn:
            self.scopes.bind_request(conn, 'bob', 'recovery-allocation', self.request_id)
        plan, _ = messages.runs._prepare('bob', body)
        network_calls = []
        def transport(request):
            network_calls.append(request.url.path)
            raise AssertionError('Budgeted local root reached remote transport')
        handoff = self.fixture.state['handoff_client']
        target = HandoffTarget('budget-remote-fixture', 'synthetic-origin', 'http://remote.invalid',
            {'bob': 'synthetic-receiver'}, lambda owner: {}, transport=httpx.MockTransport(transport),
            supported_application_contracts=(1, 2))
        with patch.dict(handoff.targets, {target.reference: target}), \
                patch.object(handoff, 'reserve', wraps=handoff.reserve) as reserve, \
                patch.object(handoff, 'prepare', AsyncMock(wraps=handoff.prepare)) as prepare, \
                patch.object(handoff, 'dispatch', AsyncMock(wraps=handoff.dispatch)) as dispatch:
            for reserved in (False, True):
                with self.subTest(already_reserved=reserved):
                    if reserved:
                        task, fresh = self.fixture.store.reserve_task(plan, self.request_id)
                        self.assertTrue(fresh)
                        self.assertEqual(task['admission'], 'reserved')
                        self.assertIsNone(task['run_id'])
                    response = self.fixture.client.post('/api/factory/instances', json={
                        'planId': plan['id'], 'requestId': self.request_id, 'executionTargetRef': target.reference})
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(response.json()['message'], 'LOCAL_BUDGET_ORIGINAL_ROOT_REQUIRED')
                    self.assertEqual(len(self.fixture.store.tasks('bob')), int(reserved))
                    prepare.assert_not_called()
                    dispatch.assert_not_called()
            self.fixture.store.sql('DELETE FROM af_local_budget_requests WHERE owner_id=:owner AND request_id=:request',
                owner='bob', request=self.request_id)
            legacy = self.fixture.client.post('/api/factory/instances', json={
                'planId': plan['id'], 'requestId': self.request_id, 'executionTargetRef': target.reference})
            self.assertEqual(legacy.status_code, 409, legacy.text)
            self.assertEqual(legacy.json()['message'], 'LOCAL_BUDGET_ORIGINAL_ROOT_REQUIRED')
            changed_key = self.fixture.client.post('/api/factory/instances', json={
                'planId': plan['id'], 'requestId': 'legacy-bound-plan-new-key'})
            self.assertEqual(changed_key.status_code, 409, changed_key.text)
            self.assertEqual(changed_key.json()['message'], 'LOCAL_BUDGET_REQUEST_PLAN_CONFLICT')
            self.assertEqual(len(self.fixture.store.tasks('bob')), 1)
            prepare.assert_not_called()
            dispatch.assert_not_called()
            self.assertEqual(reserve.call_count, 3)
        self.assertEqual(network_calls, [])
        self.assertEqual(self.fixture.store.sql('SELECT task_id FROM af_remote_placements'), [])

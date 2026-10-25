"""Trusted recovery decisions only; native uniqueness is covered by PG tests."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import test_assistant_messages as fixtures


class AssistantMessageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AssistantMessagesTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service = self.fixture.service
        self.message, fresh = self.service._reserve('alice', 'bobs-assistant', self.fixture.body)
        self.assertTrue(fresh)
        self.key = self.service._request_id(self.message)

    def recover(self, recipient='bob'):
        return asyncio.run(self.service.recover(recipient, self.message['id'], allocation_id='original-allocation'))

    def test_absent_and_prepared_use_original_identity_inputs_and_allocation(self):
        for prepared in (False, True):
            with self.subTest(prepared=prepared):
                self.fixture.runs.receipts.clear()
                if prepared:
                    self.fixture.runs.receipts[('bob', self.key)] = {
                        'state': 'prepared', 'taskId': None, 'runId': None}
                self.fixture.endpoints.text_input = True
                with patch.object(self.fixture.runs, 'start', AsyncMock()) as start:
                    self.recover()
                owner, body = start.call_args.args
                self.assertEqual(owner, 'bob')
                self.assertEqual(body.requestId, self.key)
                self.assertEqual(body.inputValues, {'goal': self.fixture.body.text})
                self.assertEqual(body.connectionRefs, {'model': 'bobs-private-model-ref'})
                self.assertEqual(start.call_args.kwargs, {'allocation_id': 'original-allocation'})

    def test_existing_tasks_only_read_even_when_endpoint_disabled(self):
        self.fixture.endpoints.enabled = False
        for state in ('reserved', 'unknown', 'accepted'):
            with self.subTest(state=state):
                self.fixture.runs.receipts[('bob', self.key)] = {
                    'state': state, 'taskId': 'original-task', 'runId': None}
                with patch.object(self.fixture.runs, 'start', AsyncMock()) as start:
                    result = self.recover()
                start.assert_not_called()
                self.assertEqual(result['delivery']['taskId'], 'original-task')
                self.assertEqual(result['delivery']['state'], state)

    def test_current_member_endpoint_and_receiver_checks_prevent_new_start(self):
        with patch.object(self.fixture.runs, 'start', AsyncMock()) as start:
            with self.assertRaises(HTTPException): self.recover('charlie')
            self.fixture.endpoints.enabled = False
            with self.assertRaises(HTTPException): self.recover()
            self.fixture.endpoints.enabled = True
            self.fixture.auth.members.remove('alice')
            with self.assertRaises(HTTPException): self.recover()
        start.assert_not_called()

    def test_database_or_unrelated_missing_receipt_errors_do_not_authorize_start(self):
        for error in (TimeoutError('synthetic DB failure'), HTTPException(404, 'OTHER_NOT_FOUND')):
            with self.subTest(error=error), patch.object(self.fixture.runs, '_request_receipt', side_effect=error), \
                    patch.object(self.fixture.runs, 'start', AsyncMock()) as start:
                with self.assertRaises(type(error)): self.recover()
                start.assert_not_called()

    def test_outer_transaction_rejected_and_public_duplicate_stays_read_only(self):
        with self.fixture.engine.begin() as conn:
            token = self.fixture.store._connection.set(conn)
            try:
                with self.assertRaisesRegex(RuntimeError, 'committed message transaction'): self.recover()
            finally:
                self.fixture.store._connection.reset(token)
        with patch.object(self.fixture.runs, 'start', AsyncMock()) as start:
            result = self.fixture.send()
        start.assert_not_called()
        self.assertEqual(result['delivery']['state'], 'unconfirmed')

    def test_trusted_delivery_identity_passes_only_to_absent_task_admission(self):
        with patch.object(self.fixture.runs, 'start', AsyncMock()) as start:
            asyncio.run(self.service.recover('bob', self.message['id'],
                allocation_id='original-allocation', delivery_id='original-delivery'))
        self.assertEqual(start.call_args.kwargs, {
            'allocation_id': 'original-allocation', 'delivery_id': 'original-delivery'})
        self.assertEqual(start.call_args.args[1].requestId, self.key)
        self.fixture.runs.receipts[('bob', self.key)] = {
            'state': 'unknown', 'taskId': 'original-task', 'runId': None}
        with patch.object(self.fixture.runs, 'start', AsyncMock()) as start:
            asyncio.run(self.service.recover('bob', self.message['id'],
                allocation_id='original-allocation', delivery_id='original-delivery'))
        start.assert_not_called()

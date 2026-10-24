"""Original-receipt validation before control writes; synthetic HTTP/SQL only."""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

from fastapi import HTTPException

import test_remote_scientific_handoff_policy as policy


class ScientificCleanupReceiptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Reuse a receipt with real binding proof and scientific evidence. The
        # core _save_receipt and research policy validators remain executable.
        self.fixture = policy.ScientificHandoffPolicyTests()
        self.fixture.setUp()
        f = self.fixture
        f.row['body']['receipt'] = deepcopy(f.receipt)
        self.client = f.client
        self.client._scientific_cleanup_target = Mock(return_value=(f.row, f.target))
        self.client._row = Mock(return_value=f.row)
        self.client._request = AsyncMock(return_value=deepcopy(f.receipt))
        self.client._save_receipt = Mock(wraps=self.client._save_receipt)

    def assert_readonly_sql(self):
        for call in self.fixture.conn.execute.call_args_list:
            sql = str(call.args[0]).lstrip().upper()
            self.assertTrue(sql.startswith('SELECT'), sql)
            self.assertNotIn('FOR UPDATE', sql)

    async def read(self, *, reconcile=False):
        f = self.fixture
        return await self.client.scientific_cleanup_receipt(
            'alice', f.row['task_id'], expected_scope=f.scope, reconcile=reconcile)

    async def test_invalid_lookup_is_rejected_before_any_control_post(self):
        f = self.fixture
        for mutation in ('receipt_id', 'owner', 'native_identity', 'binding_proof', 'scope'):
            with self.subTest(mutation=mutation):
                receipt = deepcopy(f.receipt)
                if mutation == 'receipt_id':
                    receipt['id'] = 'foreign-receipt'
                elif mutation == 'owner':
                    receipt['originOwnerId'] = 'bob'
                elif mutation == 'native_identity':
                    receipt['native']['queue']['id'] = 'foreign-run'
                elif mutation == 'binding_proof':
                    receipt['receiverBindingProof']['sha256'] = '0' * 64
                else:
                    receipt['scientificEvidence']['scope']['originChildTaskId'] = 'foreign-child'
                self.client._request.reset_mock()
                self.client._request.return_value = receipt
                with self.assertRaises((HTTPException, ValueError)):
                    await self.read(reconcile=True)
                self.assertEqual([c.args[2] for c in self.client._request.await_args_list], ['GET'])
                f.store.observed.assert_not_called()
                self.assert_readonly_sql()

    async def test_history_has_no_post_or_persistence(self):
        result = await self.read()
        self.assertEqual(result['id'], self.fixture.receipt['id'])
        self.assertEqual([c.args[2] for c in self.client._request.await_args_list], ['GET'])
        self.assertEqual([c.kwargs for c in self.client._save_receipt.call_args_list], [{'persist': False}])
        self.fixture.store.observed.assert_not_called()
        self.assert_readonly_sql()

    async def test_valid_control_posts_only_original_receipt_then_persists(self):
        f = self.fixture
        await self.read(reconcile=True)
        requests = self.client._request.await_args_list
        self.assertEqual([c.args[2] for c in requests], ['GET', 'POST'])
        self.assertEqual(requests[1].args[3],
                         '/api/factory/remote-handoffs/' + quote(f.receipt['id'], safe='') + '/reconcile')
        self.assertEqual([c.kwargs for c in self.client._save_receipt.call_args_list],
                         [{'persist': False}, {'persist': True}])
        f.store.observed.assert_called_once()
        writes = [str(c.args[0]) for c in f.conn.execute.call_args_list
                  if str(c.args[0]).lstrip().upper().startswith('UPDATE')]
        self.assertEqual(len(writes), 1)

"""Research delegation keeps original request identity and custody boundaries."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from agent_factory_research.delegation_compatibility import ResearchDelegationService


class ResearchDelegationCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scientific = SimpleNamespace(prepare_placement=Mock(return_value={'scope': 'original'}),
            origin_phase=AsyncMock(), cleanup_phase=AsyncMock(), cancel_original=AsyncMock())
        self.client = SimpleNamespace(scientific_service=self.scientific,
            _science=Mock(return_value=self.scientific), reserve=Mock(),
            prepare=AsyncMock(), dispatch=AsyncMock(), receipt=AsyncMock())
        self.store = SimpleNamespace(handoff_client=self.client, handoff_receiver=None,
            plan=Mock(return_value={}), sql=Mock(return_value=[{'child_id': 'child'}]),
            effects=Mock(return_value=[{'status': 'UNKNOWN'}]))
        self.service = ResearchDelegationService(None, self.store, None, None)
        self.parent = {'id': 'parent', 'plan_id': 'parent-plan'}
        self.task = {'id': 'child', 'owner_id': 'alice', 'plan_id': 'child-plan',
            'run_id': None, 'admission': 'unknown', 'cancel_requested': False}
        self.placement = {'targetRef': 'receiver', 'phase': 'training'}

    def test_original_scientific_request_fingerprint_fields_are_preserved(self):
        request = self.service._creation_request('alice', self.parent, '  train  ', 'experiment', self.placement)
        self.assertEqual(request, {'owner': 'alice', 'parent': 'parent', 'goal': 'train',
            'mode': 'experiment', 'scientificPlacement': self.placement})
        self.client._science.assert_called_once_with()
        self.client.reserve.assert_not_called()

    def test_receiver_scientific_phase_cannot_delegate_further(self):
        self.store.plan.return_value = {'remoteHandoff': {'receiptId': 'original-receipt'}}
        receiver = SimpleNamespace(scientific_service=object(),
            _row=Mock(return_value={'body': {'scientificEnvelope': {'scope': 'original'}}}))
        self.store.handoff_receiver = receiver
        with self.assertRaisesRegex(HTTPException, 'Receiver scientific phases cannot delegate further'):
            self.service._creation_request('alice', self.parent, 'train', 'experiment', None)
        receiver._row.assert_called_once_with('original-receipt', 'alice')
        self.client.reserve.assert_not_called()

    async def test_unknown_existing_placement_only_reads_original_receipt(self):
        self.client.reserve.return_value = {'state': 'UNKNOWN'}
        self.client.receipt.return_value = {'state': 'UNKNOWN', 'remoteTaskId': 'original-child'}
        plan = {'id': 'child-plan'}
        receipt = await self.service._dispatch_placement('alice', self.parent, self.task,
            plan, self.placement, 'original-native-request')
        self.assertEqual(receipt, {'state': 'UNKNOWN', 'remoteTaskId': 'original-child'})
        self.scientific.prepare_placement.assert_called_once_with('alice', self.parent, self.task, plan, self.placement)
        self.client.reserve.assert_called_once_with('alice', 'child-plan', 'receiver', 'original-native-request',
            scientific_envelope={'scope': 'original'})
        self.client.receipt.assert_awaited_once_with('alice', 'child')
        self.client.prepare.assert_not_awaited()
        self.client.dispatch.assert_not_awaited()

    async def test_canceled_child_requires_original_cleanup_stop_proof(self):
        self.task['cancel_requested'] = True
        self.scientific.cleanup_phase.return_value = {'status': 'unknown', 'allStopped': False,
            'receipt': {'remoteTaskId': 'original-child'}}
        facts = await self.service._facts(self.task)
        self.assertTrue(facts['unknown'])
        self.assertTrue(facts['pending'])
        self.assertFalse(facts['stopped'])
        self.assertEqual(facts['snapshot'], {'remoteTaskId': 'original-child'})
        self.scientific.cleanup_phase.assert_awaited_once_with('alice', 'child')
        self.scientific.origin_phase.assert_not_awaited()
        self.assertEqual(self.store.sql.call_args.kwargs, {'id': 'child', 'owner': 'alice'})

    async def test_placement_cancel_uses_owner_scoped_original_child_only(self):
        self.assertTrue(await self.service._cancel_placement('alice', self.task))
        self.assertEqual(self.store.sql.call_args.kwargs, {'id': 'child', 'owner': 'alice'})
        self.scientific.cancel_original.assert_awaited_once_with('alice', 'child')
        self.store.sql.return_value = []
        self.assertFalse(await self.service._cancel_placement('alice', self.task))
        self.scientific.cancel_original.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()

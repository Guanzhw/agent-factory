"""Pure phase projection/control routing; no PostgreSQL or live provider proof."""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock

from types import SimpleNamespace

from agent_factory_research.services import ResearchServices
from agent_factory_research.autoresearch_remote_children import AutoResearchRemoteChildren

from test_remote_scientific_origin import Fixture


class RemoteScientificPhaseReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.fresh = await self.f.receipt()
        self.f.handoff.receipt = AsyncMock(return_value=deepcopy(self.fresh))
        self.f.handoff.reconcile = AsyncMock(return_value=deepcopy(self.fresh))
        self.f.handoff.scientific_cleanup_receipt = AsyncMock(return_value=deepcopy(self.fresh))
        self.f.handoff_row['body']['receipt']['applicationStatus'] = 'running'
        self.f.store.sql = Mock(wraps=self.f.store.sql)

    def assert_no_writes(self):
        statements = [call.args[0].strip().upper() for call in self.f.store.sql.call_args_list]
        self.assertTrue(all(s.startswith('SELECT') and 'FOR UPDATE' not in s for s in statements), statements)

    async def test_history_uses_fresh_response_without_updating_journal(self):
        result = await self.f.service.origin_phase('alice', self.f.child['id'])
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['allStopped'])
        self.assert_no_writes()
        self.f.handoff.reconcile.assert_not_awaited()
        self.assertEqual(self.f.handoff_row['body']['receipt']['applicationStatus'], 'running')

    async def test_cleanup_history_is_pure_and_keeps_original_scope(self):
        self.f.child['cancel_requested'] = True
        await self.f.service.cleanup_phase('alice', self.f.child['id'])
        self.f.handoff.scientific_cleanup_receipt.assert_awaited_once_with(
            'alice', self.f.child['id'], expected_scope=self.f.envelope['scope'], reconcile=False)
        self.assert_no_writes()

    async def test_control_uses_latest_persisted_receipt_and_journal_cas(self):
        result = await self.f.service.reconcile_phase('alice', self.f.child['id'])
        self.assertEqual(result['status'], 'running')
        self.f.handoff.reconcile.assert_awaited_once_with('alice', self.f.child['id'])
        self.f.handoff.receipt.assert_not_awaited()
        statements = [call.args[0] for call in self.f.store.sql.call_args_list]
        self.assertTrue(any('FOR UPDATE' in s for s in statements))
        self.assertTrue(any('IS NOT DISTINCT FROM' in s for s in statements))

    async def test_cleanup_control_reconciles_only_original_custody(self):
        self.f.child['cancel_requested'] = True
        await self.f.service.reconcile_phase('alice', self.f.child['id'], cleanup=True)
        self.f.handoff.scientific_cleanup_receipt.assert_awaited_once_with(
            'alice', self.f.child['id'], expected_scope=self.f.envelope['scope'], reconcile=True)
        self.f.handoff.reconcile.assert_not_awaited()

    async def test_history_rejects_scope_drift_without_writing(self):
        self.f.handoff.receipt.return_value['scientificEvidence']['scope']['originChildTaskId'] = 'changed'
        with self.assertRaisesRegex(ValueError, "REMOTE_SCIENTIFIC_EVIDENCE_INVALID"):
            await self.f.service.origin_phase('alice', self.f.child['id'])
        self.assert_no_writes()

    async def test_finalizing_is_nonterminal_for_controller(self):
        self.f.handoff.receipt.return_value['applicationStatus'] = 'finalizing'
        result = await self.f.service.origin_phase('alice', self.f.child['id'])
        self.assertEqual(result['status'], 'running')
        self.assertFalse(result['allStopped'])

    async def test_controller_observation_uses_control_reader(self):
        controller = object.__new__(AutoResearchRemoteChildren)
        controller.store = self.f.store
        controller.reader = None
        controller._child = Mock(return_value=self.f.child)
        controller._scope_binding = Mock(return_value={})
        body = {'binding': {'ownerId': 'alice'}, 'phases': {'preparation': {}}}
        result = {'scope': self.f.envelope['scope'], 'receipt': self.fresh,
                  'status': 'completed', 'allStopped': True}
        science = SimpleNamespace(reconcile_phase=AsyncMock(return_value=result))
        controller.research = ResearchServices(self.f.store, installed=True, remote_scientific=science)
        await controller._observe(body, 'preparation')
        await controller._observe(body, 'preparation', cleanup=True)
        self.assertEqual(science.reconcile_phase.await_count, 2)
        self.assertEqual([c.kwargs for c in science.reconcile_phase.await_args_list],
                         [{'cleanup': False}, {'cleanup': True}])

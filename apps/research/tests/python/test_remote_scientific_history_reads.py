# pyright: reportMissingImports=false
"""History projection preserves validated custody without lifecycle writes."""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.store import digest
import test_remote_scientific_receiver as fixtures


class ScientificHistoryReadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = fixtures.ReceiverTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.store = self.fixture.store

    def forbid_writes(self):
        original = self.store.sql
        def read(statement, **values):
            if not statement.startswith('SELECT') or 'FOR UPDATE' in statement:
                raise AssertionError('History attempted a lifecycle write or row lock')
            return original(statement, **values)
        self.store.sql = read
        self.store.transaction = Mock(side_effect=AssertionError('History opened write transaction'))

    async def test_projection_validates_claims_without_retaining_new_rows(self):
        receipt, provider = self.fixture.projection_fixture()
        before = deepcopy(self.store.rows)
        self.forbid_writes()
        value = await self.service.project_evidence(receipt, persist=False)
        self.assertIsNone(value['checkpoint'])
        self.assertIsNotNone(value['lease'])
        provider.read_launch_proof.assert_not_called()
        self.fixture.project.checkpoints.identity.assert_not_called()
        self.assertEqual(self.store.rows, before)
        self.assertEqual(self.store.evidence, {})
        self.service.inspect_phase.assert_awaited_once_with('receiver-alice', 'task-training', persist=False)
        self.assertEqual(receipt['scientificObservation'], 'persisted-original-custody')

    async def test_history_preserves_verified_claims_without_rereading_provider(self):
        receipt, provider = self.fixture.projection_fixture()
        expected = await self.service.project_evidence(receipt)
        retained = deepcopy(self.store.evidence)
        provider.read_launch_proof.side_effect = AssertionError('History inspected provider')
        self.fixture.project.checkpoints.identity.side_effect = AssertionError('History reread artifact')
        self.forbid_writes()
        value = await self.service.project_evidence(receipt, persist=False)
        self.assertEqual(value, expected)
        self.assertTrue(receipt['scientificClaimsRetained'])
        self.assertEqual(self.store.evidence, retained)

    async def test_read_merges_retained_claims_but_rejects_conflicts(self):
        receipt, _ = self.fixture.projection_fixture()
        full = await self.service.project_evidence(receipt)
        retained = deepcopy(self.store.evidence)
        stale = deepcopy(full)
        for key in ('launchProof', 'checkpoint', 'evaluation', 'preparation'):
            stale[key] = None
        self.forbid_writes()
        merged = self.service._retain_evidence(receipt, stale, persist=False)
        self.assertEqual(merged, full)
        self.assertEqual(merged['lease'], stale['lease'])
        self.assertEqual(self.store.evidence, retained)
        conflict = deepcopy(full)
        conflict['checkpoint']['checkpoint']['sha256'] = 'e' * 64
        with self.assertRaises(ValueError):
            self.service._retain_evidence(receipt, conflict, persist=False)

    async def test_read_rejects_changed_original_identity(self):
        receipt, _ = self.fixture.projection_fixture()
        self.store.tasks['task-training']['run_id'] = 'replacement'
        self.forbid_writes()
        with self.assertRaises(ValueError):
            await self.service.project_evidence(receipt, persist=False)

    async def test_unbound_history_does_not_bind_a_lost_acknowledgement(self):
        receipt, _ = self.fixture.projection_fixture()
        body = self.store.rows['receipt-training']['body']
        del body['receiver']
        del body['nativeRunId']
        self.forbid_writes()
        value = await self.service.project_evidence(receipt, persist=False)
        self.assertIsNone(value['lease'])
        self.assertIsNone(value['checkpoint'])
        self.assertNotIn('receiver', body)
        self.service.inspect_phase.assert_not_awaited()

    async def test_inspection_reads_validated_durable_custody_without_provider_effects(self):
        self.fixture.completed_prep()
        ctx = self.fixture.bind('training')
        self.service.require_phase(ctx, 'training')
        body = self.store.rows['receipt-training']['body']
        body.update(state='UNKNOWN', targetFingerprint='f' * 64,
                    runtimeSnapshot={'body': {'synthetic': True}, 'sha256': digest({'synthetic': True})})
        runtime = self.fixture.research.research_runtime
        runtime._original.return_value = {'owner_id': 'receiver-alice', 'native_run_id': 'run-training', 'lease_id': 'original-lease'}
        runtime.resources.targets[body['config']['targetRef']] = object()
        lease = {'id': 'original-lease', 'state': 'UNKNOWN', 'capacityHeld': True}
        runtime._custody = Mock(return_value=(lease, None, None, None))
        runtime.observe_lease = AsyncMock(side_effect=AssertionError('History reconciled custody'))
        self.forbid_writes()
        result = await self.service.inspect_phase('receiver-alice', 'task-training', persist=False)
        self.assertEqual(result['lease'], lease)
        runtime._custody.assert_called_once_with('original-lease')
        runtime.observe_lease.assert_not_awaited()
        self.fixture.assembler.restore_phase.assert_not_called()
        runtime.resources.targets.clear()
        with self.assertRaises(ValueError):
            await self.service.inspect_phase('receiver-alice', 'task-training', persist=False)
        self.fixture.assembler.restore_phase.assert_not_called()

    async def test_no_dispatch_proof_does_not_write(self):
        self.fixture.completed_prep()
        self.fixture.bind('training')
        expected = self.service.cancel_before_dispatch('receiver-alice', 'task-training')
        receipt = fixtures.peer.shell() | {'id': 'receipt-training', 'remoteTaskId': 'task-training',
            'remotePlanId': 'plan-training', 'remoteRunId': 'run-training', 'manifestHash': digest(self.fixture.source)}
        self.forbid_writes()
        self.assertEqual(self.service.no_dispatch_proof(receipt), expected)

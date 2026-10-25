"""Deterministic storage-contention projection; no PostgreSQL/provider execution."""
from copy import deepcopy
from threading import Event
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from agent_factory.store import digest
from agent_factory_research.autoresearch_remote_children import AutoResearchRemoteChildren
import test_remote_scientific_receiver as receiver


BUSY = ('RETENTION_BUSY: another original fence is active',
        'RETENTION_BUSY: reconcile the original plan')


class EvidenceContentionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = receiver.ReceiverTests()
        self.f.setUp()

    async def test_busy_checkpoint_is_pending_then_next_observation_verifies(self):
        f = self.f
        receipt, _ = f.projection_fixture()
        available = Event()
        original = f.project.checkpoints.identity.return_value
        def fenced(*args):
            if not available.is_set():
                raise HTTPException(409, BUSY[0])
            return original
        f.project.checkpoints.identity.side_effect = fenced
        pending = await f.service.project_evidence(receipt)
        self.assertIsNone(pending['checkpoint'])
        self.assertIsNone(pending['launchProof'])
        self.assertFalse(f.store.evidence)
        self.assertFalse(AutoResearchRemoteChildren._complete(
            {'status': 'completed', 'allStopped': True}, pending, 'training'))
        available.set()
        complete = await f.service.project_evidence(receipt)
        self.assertIsNotNone(complete['checkpoint'])
        self.assertEqual(f.project.checkpoints.identity.call_count, 2)
        f.research.research_runtime.submit.assert_not_called()

    async def test_busy_preserves_only_verified_claims_without_writing(self):
        f = self.f
        receipt, _ = f.projection_fixture()
        verified = await f.service.project_evidence(receipt)
        saved = deepcopy(f.store.evidence)
        for detail in BUSY:
            with self.subTest(detail=detail):
                f.project.checkpoints.identity.side_effect = HTTPException(409, detail)
                self.assertEqual(await f.service.project_evidence(receipt), verified)
                self.assertTrue(receipt['scientificClaimsRetained'])
                self.assertEqual(f.store.evidence, saved)

    async def test_other_conflicts_and_revocation_are_not_downgraded(self):
        f = self.f
        receipt, _ = f.projection_fixture()
        for code, detail in ((409, 'CHECKPOINT_CHANGED'), (403, 'revoked'),
                             (409, BUSY[0] + ' extra'), (503, BUSY[0])):
            with self.subTest(code=code, detail=detail):
                error = HTTPException(code, detail)
                f.project.checkpoints.identity.side_effect = error
                with self.assertRaises(HTTPException) as caught:
                    await f.service.project_evidence(receipt)
                self.assertIs(caught.exception, error)
                self.assertFalse(f.store.evidence)

    async def test_busy_cannot_hide_identity_change(self):
        f = self.f
        receipt, _ = f.projection_fixture()
        def replace(*args):
            f.store.rows['receipt-training']['body']['nativeRunId'] = 'replacement'
            raise HTTPException(409, BUSY[0])
        f.project.checkpoints.identity.side_effect = replace
        with self.assertRaises(ValueError):
            await f.service.project_evidence(receipt)
        self.assertFalse(f.store.evidence)

    async def test_evaluation_busy_discards_this_round_checkpoint_and_launch(self):
        f = self.f
        receipt, _ = f.projection_fixture()
        body = f.store.rows['receipt-training']['body']
        prior = deepcopy(body)
        body['binding']['scope']['phase'] = 'evaluation'
        f.store.rows['receipt-training']['phase'] = 'evaluation'
        body['bindingSha256'] = digest(body['binding'])
        f.service._prior = Mock(return_value={'training': prior})
        verifier = AsyncMock(side_effect=HTTPException(409, BUSY[1]))
        f.assembler.evaluation_service.return_value.verify = verifier
        result = await f.service.project_evidence(receipt)
        verifier.assert_awaited_once()
        f.project.checkpoints.identity.assert_called_once()
        for name in ('launchProof', 'checkpoint', 'evaluation'):
            self.assertIsNone(result[name])
        self.assertFalse(f.store.evidence)

    async def test_preparation_busy_does_not_invent_verified_reference(self):
        f = self.f
        f.completed_prep()
        body = f.store.rows['receipt-preparation']['body']
        f.assembler.preparation_receipt.return_value = deepcopy(body['receipt'])
        f.project.preparation.identity.side_effect = HTTPException(409, BUSY[0])
        receipt = receiver.peer.shell('preparation') | {'id': 'receipt-preparation',
            'remoteTaskId': 'task-preparation', 'remotePlanId': 'plan-preparation',
            'remoteRunId': 'run-preparation', 'manifestHash': digest(f.source)}
        result = await f.service.project_evidence(receipt)
        self.assertIsNone(result['preparation'])
        self.assertIsNone(result['lease'])
        self.assertFalse(f.store.evidence)

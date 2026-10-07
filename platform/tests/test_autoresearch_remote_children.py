# pyright: reportMissingImports=false
"""Durable coordinator seams with real pure evidence validators; no peer execution."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from agent_factory.autoresearch_remote_children import AutoResearchRemoteChildren
from agent_factory.remote_scientific_evidence import project_scientific_evidence
from agent_factory.store import digest
import test_autoresearch_children as local_fixture
import test_remote_scientific_evidence as peer


class Store(local_fixture.MemoryStore):
    def __init__(self):
        super().__init__(); self.links = []; self.children = {}
    def task(self, identifier, owner):
        if identifier in self.children:
            value = self.children[identifier]
            if value['owner_id'] != owner: raise PermissionError('owner denied')
            return deepcopy(value)
        return super().task(identifier, owner)
    def sql(self, statement, **values):
        if statement.startswith('SELECT * FROM af_delegation_links'):
            return [deepcopy(v) for v in self.links if v['request_id'] == values['request']
                and v['parent_id'] == values['parent'] and v['owner_id'] == values['owner']]
        return super().sql(statement.replace('af_autoresearch_remote_experiments', 'af_autoresearch_experiments'), **values)


class RemoteChildrenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(); self.candidate = {'hypothesis': 'synthetic', 'trainPy': '# original candidate', 'validated': {}}
        self.preset = SimpleNamespace(fingerprint='5'*64, limits={'maxExperiments': 1},
            manifest=peer.contract()['comparisonManifest'])
        self.service = SimpleNamespace(current=Mock(return_value=self.preset),
            row=Mock(return_value={'body': {'candidates': {'id': self.candidate}}}))
        self.ctx = SimpleNamespace(run_context=SimpleNamespace(user_id='alice', session_id='parent', run_id='native-parent'))
        self.children = AutoResearchRemoteChildren(self.store, Mock(), self.service,
            target_ref='one-receiver', project_id='original-project', project_pin='4'*64,
            manifest=self.preset.manifest, poll_seconds=.01)
        self.store.remote_scientific = SimpleNamespace(drive_outcome=Mock(return_value=None), start_phase=AsyncMock(), origin_phase=AsyncMock(side_effect=self.observe),
            cleanup_phase=AsyncMock(side_effect=self.observe),
            cancel_original=AsyncMock())
        self.store.delegation.create = AsyncMock(side_effect=self.create)
        self.observed = {}; self.lost_ack = False

    async def create(self, owner, parent, goal, mode, request, *, scientific_placement):
        phase = scientific_placement['phase']
        entry = self.store.row['body']['phases'][phase]
        self.assertEqual(entry['state'], 'DISPATCH_UNKNOWN')
        self.assertEqual(entry['placement'], scientific_placement)
        child = 'child-' + phase
        # Origin projection deliberately has no native run identity.
        self.store.children[child] = {'id': child, 'owner_id': owner, 'plan_id': 'plan-' + phase, 'run_id': None}
        self.store.links.append({'owner_id': owner, 'parent_id': parent, 'request_id': request,
            'child_id': child, 'plan_id': 'plan-' + phase})
        scope = {**peer.scope(phase), **scientific_placement['scopeBinding'], 'originChildTaskId': child}
        if phase == 'preparation':
            receipt = peer.shell(phase)
            receipt.update(originTaskId=child)
            producer = {k: v for k, v in peer.contract()['training'].items() if k not in {'checkpoint', 'variantSha256'}}
            receipt['scientificEvidence'] = project_scientific_evidence(receipt, scope=scope,
                preparation={'schema': 1, **producer, 'artifactId': 'original-prep', 'artifactSha256': 'a'*64})
        else:
            receipt = peer.receipt(phase, released=True, result=True)
            receipt.update(originTaskId=child)
            receipt['scientificEvidence']['scope'] = scope
        self.observed[child] = {'scope': scope, 'receipt': receipt, 'status': 'completed', 'allStopped': True}
        if self.lost_ack: raise ConnectionError('synthetic lost reply')
        return {}

    async def observe(self, owner, child):
        self.assertEqual(owner, 'alice')
        return deepcopy(self.observed[child])

    async def test_three_original_remote_phases_done_replay_revalidates_without_native_origin_ids(self):
        result = await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertTrue(result['independentResult']); self.assertFalse(result['scientificConclusionVerified'])
        self.assertEqual(self.store.delegation.create.await_count, 3)
        self.assertEqual(await self.children.experiment(self.ctx, self.candidate, 'original-call'), result)
        self.assertEqual(self.store.delegation.create.await_count, 3)
        self.observed['child-training']['receipt']['scientificEvidence']['checkpoint']['checkpoint']['sha256'] = '0'*64
        with self.assertRaises(ValueError): await self.children.result_verifier(self.ctx, result)

    async def test_pending_review_polls_start_on_original_child_without_new_delegation(self):
        pending = True
        async def observe(owner, child):
            nonlocal pending
            value = await self.observe(owner, child)
            if pending:
                pending = False
                value['status'] = 'pending'
                value['allStopped'] = False
            return value
        self.store.remote_scientific.origin_phase.side_effect = observe
        await self.children.experiment(self.ctx, self.candidate, 'original-call')
        calls = self.store.remote_scientific.start_phase.await_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(self.store.delegation.create.await_count, 3)

    async def test_unknown_receipt_keeps_original_identity_while_parent_authority_valid(self):
        first = True
        async def observe(owner, child):
            nonlocal first
            value = await self.observe(owner, child)
            if first:
                first = False
                value.update(status='unknown', allStopped=False)
            return value
        self.store.remote_scientific.origin_phase.side_effect = observe
        await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertEqual(self.store.delegation.create.await_count, 3)
        calls = self.store.remote_scientific.start_phase.await_args_list
        self.assertEqual(calls[0], calls[1])

    async def test_lost_drive_ack_observes_original_only_after_validated_intent(self):
        self.store.remote_scientific.drive_outcome.return_value = {'driveRequested': True}
        self.store.remote_scientific.start_phase.side_effect = [HTTPException(503,
            'REMOTE_ACK_UNKNOWN: read the original owner-bound receipt'), None, None]
        result = await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertTrue(result['independentResult'])
        self.store.remote_scientific.drive_outcome.assert_called_once_with('alice', 'child-preparation')
        self.assertEqual(self.store.delegation.create.await_count, 3)

    async def test_503_without_original_drive_intent_is_not_swallowed(self):
        self.store.remote_scientific.start_phase.side_effect = HTTPException(503,
            'REMOTE_ACK_UNKNOWN: read the original owner-bound receipt')
        with self.assertRaises(HTTPException):
            await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertEqual(self.store.delegation.create.await_count, 1)
        self.assertEqual(self.store.remote_scientific.origin_phase.await_count, 0)

    async def test_unrelated_503_is_not_swallowed_even_with_intent(self):
        self.store.remote_scientific.drive_outcome.return_value = {'driveRequested': True}
        self.store.remote_scientific.start_phase.side_effect = HTTPException(503, 'different failure')
        with self.assertRaises(HTTPException):
            await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.store.remote_scientific.drive_outcome.assert_not_called()

    async def test_lost_reply_original_identity_is_not_redispatched(self):
        self.lost_ack = True
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertEqual(self.store.row['body']['state'], 'UNKNOWN')
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_EXPERIMENT_UNKNOWN'):
            await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertEqual(self.store.delegation.create.await_count, 1)
        self.assertTrue(await self.children.cleanup(self.ctx))

    async def test_cross_parent_scope_is_rejected_before_next_phase(self):
        async def corrupted(owner, child):
            value = await self.observe(owner, child)
            value['scope']['originParentRunId'] = 'another-parent'
            return value
        self.store.remote_scientific.origin_phase.side_effect = corrupted
        with self.assertRaises(ValueError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_parent_revocation_prevents_next_phase(self):
        original = self.observe
        async def revoke(owner, child):
            result = await original(owner, child)
            self.store.task_value['cancel_requested'] = True
            return result
        self.store.remote_scientific.origin_phase.side_effect = revoke
        with self.assertRaises(ValueError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_changed_candidate_and_project_pin_cannot_adopt_intent(self):
        self.lost_ack = True
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        changed = {**self.candidate, 'trainPy': '# changed'}
        self.service.row.return_value['body']['candidates']['changed'] = changed
        with self.assertRaises(ValueError): await self.children.experiment(self.ctx, changed, 'original-call')
        self.children.project_pin = 'f'*64
        with self.assertRaises(ValueError): self.children._read('native-parent')
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_released_gpu_without_native_stop_is_not_complete(self):
        value = peer.receipt('training', released=True, result=True)
        observed = {'status': 'completed', 'allStopped': False}
        self.assertFalse(self.children._complete(observed, value['scientificEvidence'], 'training'))

    async def test_revoked_parent_cleanup_uses_original_custody_cancel(self):
        self.lost_ack = True
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.store.task_value['cancel_requested'] = True
        self.service.current.side_effect = PermissionError('revoked')
        self.store.remote_scientific.origin_phase.side_effect = PermissionError('public read revoked')
        self.observed['child-preparation'].update(status='running', allStopped=False)
        async def cancel(owner, child):
            self.assertEqual((owner, child), ('alice', 'child-preparation'))
            self.observed[child].update(status='cancelled', allStopped=True)
        self.store.remote_scientific.cancel_original.side_effect = cancel
        self.assertTrue(await self.children.cleanup(self.ctx))
        self.store.remote_scientific.cancel_original.assert_awaited_once()
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def _training_dispatch_unknown(self, *, never_dispatched):
        async def create(*args, **kwargs):
            await self.create(*args, **kwargs)
            if kwargs['scientific_placement']['phase'] != 'training':
                return {}
            observed = self.observed['child-training']
            scope = observed['scope']
            value = peer.shell('training') if never_dispatched else peer.receipt('training')
            value['originTaskId'] = 'child-training'
            if never_dispatched:
                value['scientificEvidence'] = project_scientific_evidence(value, scope=scope)
                value['scientificNoDispatch'] = {'schema': 1, 'scopeSha256': digest(scope),
                    'receiverTaskId': value['remoteTaskId'], 'receiverPlanId': value['remotePlanId'],
                    'receiverNativeRunId': value['remoteRunId']}
            else:
                value['scientificEvidence']['scope'] = scope
            observed.update(receipt=value, status='cancelled', allStopped=True)
            raise ConnectionError('controlled original reply lost')
        self.store.delegation.create.side_effect = create
        with self.assertRaises(ConnectionError):
            await self.children.experiment(self.ctx, self.candidate, 'original-call')

    async def test_never_dispatched_original_training_positive_proof_can_cleanup(self):
        await self._training_dispatch_unknown(never_dispatched=True)
        self.assertTrue(await self.children.cleanup(self.ctx))
        self.assertEqual(self.store.delegation.create.await_count, 2)

    async def test_launched_held_training_cannot_cleanup_with_native_terminal_alone(self):
        await self._training_dispatch_unknown(never_dispatched=False)
        self.assertFalse(await self.children.cleanup(self.ctx, timeout_seconds=.03))
        self.assertEqual(self.store.delegation.create.await_count, 2)

    async def test_cancel_lost_ack_does_not_claim_cleanup_or_retry_dispatch(self):
        self.lost_ack = True
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.store.remote_scientific.cancel_original.side_effect = ConnectionError('cancel reply lost')
        self.assertFalse(await self.children.cleanup(self.ctx))
        self.store.remote_scientific.cleanup_phase.assert_not_awaited()
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_missing_original_link_cleanup_remains_unknown(self):
        self.lost_ack = True
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        self.store.links.clear()
        self.assertFalse(await self.children.cleanup(self.ctx))
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_persisted_placement_tamper_fails(self):
        self.lost_ack = True
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original-call')
        body = self.store.row['body']; body['phases']['preparation']['placement']['targetRef'] = 'replacement'
        body['phases']['preparation']['placementSha256'] = digest(body['phases']['preparation']['placement'])
        with self.assertRaises(ValueError): self.children._read('native-parent')
        self.assertEqual(json.loads(json.dumps(body))['state'], 'UNKNOWN')

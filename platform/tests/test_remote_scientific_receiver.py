# pyright: reportMissingImports=false
"""Synthetic receiver store seams; no PostgreSQL, GPU, network or provider execution."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.remote_scientific_receiver import RemoteScientificProject, RemoteScientificReceiver
from agent_factory.remote_scientific_profile import call_id
from agent_factory.store import digest
from agent_factory.gpu_custody import evidence_fingerprint
from fastapi import HTTPException
import test_remote_scientific_evidence as peer


class Store:
    def __init__(self):
        self.rows = {}; self.tasks = {}; self.plans = {}; self.handoffs = {}; self.leases = []; self.evidence = {}
        self.remote_bindings = SimpleNamespace()
        self.event = Mock()
        self.settings = SimpleNamespace(temporary_policy='admin-review')
        self.lifecycle_observer = SimpleNamespace(_binding=Mock(return_value={'status': 'paused', 'persistedRunStatus': 'paused'}))
        self.handoff_receiver = SimpleNamespace(_row=lambda rid, owner: deepcopy(self.handoffs[rid]), authorize=Mock(),
            _origin=Mock(return_value=SimpleNamespace(authorize=SimpleNamespace(consume_scientific_tool=Mock(return_value={'callProofSha256': 'a'*64})))))
        self.process_runtime = SimpleNamespace(_context=lambda task: SimpleNamespace(user_id=task['owner_id'],
            session_id=task['id'], run_id=task['run_id']))
        self.research_runtime = SimpleNamespace(_original=Mock(return_value=None), submit=AsyncMock(), inspect_task=AsyncMock(),
            _paused=Mock(return_value={'toolCallId': call_id('training'), 'id': 'requirement', 'version': 1}),
            resources=SimpleNamespace(targets={}, _authorize=Mock(), _target_fingerprint=Mock(return_value='f'*64)))
    @contextmanager
    def transaction(self):
        yield None

    def task(self, identifier, owner):
        task = self.tasks[identifier]
        if task['owner_id'] != owner: raise PermissionError('wrong owner')
        return deepcopy(task)
    def plan(self, identifier, owner): return deepcopy(self.plans[identifier])
    def sql(self, statement, **v):
        if statement.startswith('CREATE'): return []
        if statement.startswith('SELECT id FROM af_leases'): return deepcopy(self.leases)
        if statement.startswith('SELECT task_id FROM af_process_runs'): return []
        if statement.startswith('SELECT * FROM af_remote_scientific_evidence'):
            return [deepcopy(self.evidence[v['id']])] if v['id'] in self.evidence else []
        if statement.startswith('INSERT INTO af_remote_scientific_evidence'):
            self.evidence.setdefault(v['id'], {'receipt_id': v['id'], 'owner_id': v['owner'],
                'scope_hash': v['scope'], 'fingerprint': v['fp'], 'body': json.loads(v['body'])})
            return []
        if statement.startswith('UPDATE af_remote_scientific_evidence'):
            self.evidence[v['id']].update(fingerprint=v['fp'], body=json.loads(v['body']))
            return []
        if statement.startswith('INSERT'):
            if v['id'] not in self.rows and not any(r['group_key'] == v['group'] and r['phase'] == v['phase'] for r in self.rows.values()):
                self.rows[v['id']] = {'receipt_id': v['id'], 'owner_id': v['owner'], 'project_id': v['project'],
                    'group_key': v['group'], 'phase': v['phase'], 'body': json.loads(v['body'])}
            return []
        if statement.startswith('UPDATE'):
            row = self.rows[v['id']]
            if row['body'] != json.loads(v['original']): return []
            row['body'] = json.loads(v['body']); return [{'receipt_id': v['id']}]
        if 'WHERE receipt_id' in statement:
            return [deepcopy(self.rows[v['id']])] if v['id'] in self.rows else []
        if 'WHERE group_key' in statement:
            return [deepcopy(r) for r in self.rows.values() if r['group_key'] == v['group']]
        raise AssertionError(statement)


class ReceiverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(); self.candidate = {'trainPy': '# synthetic changed source'}
        self.manifest = peer.contract()['comparisonManifest']
        self.assembler = Mock(store=self.store, owner='receiver-alice', manifest=self.manifest, committed_entry_reader=None)
        self.assembler._candidate.return_value = ({}, 'b'*64)
        self.assembler.side_effect = lambda phase, candidate, prior, context: {'targetRef': 'target-'+phase,
            'comparisonManifest': self.manifest, 'comparisonManifestSha256': peer.scope()['comparisonManifestSha256'], 'variantSha256': 'b'*64}
        self.baseline = {'schema': 1, 'status': 'completed', 'comparisonIdentitySha256': peer.scope()['comparisonManifestSha256'],
            'variantSha256': self.manifest['baselineSourceManifestSha256'], 'valBpb': 1.2}
        self.reader = AsyncMock(return_value=self.baseline)
        self.project = RemoteScientificProject('receiver-alice', '4'*64, self.assembler, Mock(), Mock(), self.manifest, self.reader)
        self.service = RemoteScientificReceiver(self.store, Mock(), {'project': self.project}, SimpleNamespace(submit=AsyncMock()),
                                                poll_seconds=.01, max_polls=1)
        self.source = {'id': 'origin-plan'}

    def prepare(self, phase='preparation', rid=None):
        rid = rid or 'receipt-'+phase
        scope = peer.scope(phase) | {'candidateSha256': digest(self.candidate), 'sourceManifestSha256': digest(self.source)}
        envelope = {'schema': 1, 'projectId': 'project', 'scope': scope, 'candidate': self.candidate}
        self.service.prepare_binding(rid, self.source, envelope, 'receiver-alice')
        return rid, envelope

    def bind(self, phase='preparation'):
        rid, _ = self.prepare(phase)
        task = {'id': 'task-'+phase, 'owner_id': 'receiver-alice', 'plan_id': 'plan-'+phase,
                'run_id': 'run-'+phase, 'terminal': False, 'cancel_requested': False}
        plan = {'id': task['plan_id'], 'fingerprint': 'c'*64, 'remoteHandoff': {'receiptId': rid}}
        self.store.tasks[task['id']] = task; self.store.plans[plan['id']] = plan
        self.store.handoffs[rid] = {'body': {'remotePlan': plan, 'remoteTaskId': task['id']},
            'manifest_hash': digest(self.source), 'origin_task': peer.scope(phase)['originChildTaskId'],
            'origin_ref': 'cloud', 'origin_owner': 'alice'}
        self.service.bind_task(rid, task)
        return self.service._context(task['owner_id'], task['id'])

    def completed_prep(self):
        ctx = self.bind()
        self.service.require_phase(ctx, 'preparation')
        body = self.store.rows['receipt-preparation']['body']
        body.update(state='COMPLETED', receipt={'execution': {'taskId': 'original-preparation'}, 'artifact': {'id': 'token'}})
        self.store.lifecycle_observer._binding.return_value = {'status': 'completed', 'persistedRunStatus': 'completed'}
        return ctx

    def test_prepare_inert_exact_replay_and_conflict_denied(self):
        rid, envelope = self.prepare()
        self.service.prepare_binding(rid, self.source, envelope, 'receiver-alice')
        self.assembler.register_phase.assert_not_called(); self.store.research_runtime.submit.assert_not_called()
        for changes in ({'schema': True}, {'candidate': {'trainPy': 'different'}}, {'projectId': 'missing'}):
            with self.assertRaises((ValueError, KeyError)):
                self.service.prepare_binding(rid, self.source, envelope | changes, 'receiver-alice')
        with self.assertRaises(ValueError): self.service.prepare_binding('replacement', self.source, envelope, 'receiver-alice')
        self.assertEqual(len(self.store.rows), 1)

    def test_binding_replacement_native_run_and_plan_rejected(self):
        ctx = self.bind(); self.service.require_phase(ctx, 'preparation')
        self.store.tasks['task-preparation']['run_id'] = 'replacement'
        with self.assertRaises(ValueError): self.service.require_phase(ctx, 'preparation')
        self.store.tasks['task-preparation']['run_id'] = 'run-preparation'
        self.store.plans['plan-preparation']['fingerprint'] = 'd'*64
        with self.assertRaises(ValueError): self.service.require_phase(ctx, 'preparation')

    def test_binding_ignores_concurrent_observer_metadata_but_not_identity(self):
        self.bind()
        stale = self.store.task('task-preparation', 'receiver-alice')
        self.store.tasks['task-preparation'].update(terminal=True, body={'updatedAt': 'synthetic-new-observation'})
        bound = self.service.bind_task('receipt-preparation', stale)
        self.assertEqual(bound['nativeRunId'], 'run-preparation')
        self.store.tasks['task-preparation']['run_id'] = 'replacement'
        with self.assertRaises(ValueError): self.service.bind_task('receipt-preparation', stale)

    def test_equivalent_first_ticket_cas_loss_preserves_concurrent_phase_state(self):
        self.bind()
        self.store.rows['receipt-preparation']['body'].pop('nativeRunId')
        original_save = self.service._save
        def concurrent_bind(original, body):
            fresh = deepcopy(body)
            fresh.update(state='UNKNOWN', driveRequest={'status': 'UNKNOWN'}, concurrentMarker='preserved')
            self.store.rows['receipt-preparation']['body'] = fresh
            return original_save(original, body)
        self.service._save = concurrent_bind
        result = self.service.bind_task('receipt-preparation', self.store.task('task-preparation', 'receiver-alice'))
        self.assertEqual(result['nativeRunId'], 'run-preparation')
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['driveRequest'], {'status': 'UNKNOWN'})
        self.assertEqual(result['concurrentMarker'], 'preserved')
        self.assertEqual(result, self.service._read('receipt-preparation'))

    def test_first_ticket_cas_loss_cannot_adopt_different_committed_identity(self):
        self.bind()
        original_save = self.service._save
        for field in ('nativeRunId', 'receiver'):
            body = self.store.rows['receipt-preparation']['body']
            body.pop('nativeRunId', None)
            body['receiver'] = {'taskId': 'task-preparation', 'planId': 'plan-preparation',
                'planSha256': digest(self.store.plans['plan-preparation'])}
            def conflicting_bind(original, body):
                fresh = deepcopy(body)
                if field == 'nativeRunId': fresh[field] = 'replacement-native'
                else: fresh[field]['taskId'] = 'replacement-task'
                self.store.rows['receipt-preparation']['body'] = fresh
                return original_save(original, body)
            self.service._save = conflicting_bind
            with self.assertRaises(ValueError):
                self.service.bind_task('receipt-preparation', self.store.task('task-preparation', 'receiver-alice'))

    async def test_preparation_needs_actual_call_debit_and_retains_original_producer(self):
        ctx = self.bind()
        with self.assertRaises(ValueError): await self.service.verify_preparation(ctx)
        self.service.consume_tool(ctx, 'preparation', call_id('preparation'))
        original = {'execution': {'taskId': 'original-preparation', 'nativeRunId': 'original-prep-run'}, 'artifact': {'id': 'token'}}
        self.assembler.preparation_receipt.return_value = original
        self.assertEqual(await self.service.verify_preparation(ctx), original)
        self.store.lifecycle_observer._binding.return_value = {'status': 'completed', 'persistedRunStatus': 'completed'}
        self.store.tasks['task-preparation']['terminal'] = True
        self.assertEqual(await self.service.drive_phase('receiver-alice', 'task-preparation'), original)
        self.store.research_runtime.submit.assert_not_called()

    def test_lost_debit_ack_cannot_reconsume_or_allocate(self):
        ctx = self.bind()
        debit = self.store.handoff_receiver._origin.return_value.authorize.consume_scientific_tool
        debit.side_effect = ConnectionError('synthetic lost ack')
        with self.assertRaises(ConnectionError): self.service.consume_tool(ctx, 'preparation', call_id('preparation'))
        with self.assertRaises(ValueError): self.service.consume_tool(ctx, 'preparation', call_id('preparation'))
        self.assertEqual(debit.call_count, 1); self.store.research_runtime.submit.assert_not_called()

    async def test_registration_unknown_preserves_snapshot_and_never_replays(self):
        self.completed_prep(); ctx = self.bind('training')
        def register(ctx, phase, candidate, prior, pin, *, persist_snapshot):
            self.assertEqual(self.service._read('receipt-training')['state'], 'DISPATCH_UNKNOWN')
            persist_snapshot({'schema': 1, 'synthetic': True})
            raise ConnectionError('synthetic registration lost ack')
        self.assembler.register_phase.side_effect = register
        with self.assertRaises(ConnectionError): await self.service.drive_phase('receiver-alice', 'task-training')
        body = self.service._read('receipt-training')
        self.assertEqual(body['state'], 'UNKNOWN'); self.assertEqual(body['runtimeSnapshot']['body'], {'schema': 1, 'synthetic': True})
        with self.assertRaises(ValueError): await self.service.drive_phase('receiver-alice', 'task-training')
        self.assertEqual(self.assembler.register_phase.call_count, 1); self.store.research_runtime.submit.assert_not_called()
        row = self.service.committed_entry(ctx, 'training', self.candidate, body['config'])
        self.assertEqual(row['parent_task_id'], 'task-training'); self.assertEqual(row['parent_run_id'], 'run-training')
        self.assertNotIn('cloud-parent', self.store.tasks)
        self.assertNotIn('cloud-parent-run', self.store.rows)

    async def test_inspect_missing_original_never_registers_or_dispatches(self):
        self.bind()
        result = await self.service.inspect_phase('receiver-alice', 'task-preparation')
        self.assertIsNone(result['lease']); self.assembler.register_phase.assert_not_called()
        self.assembler.restore_phase.assert_not_called(); self.store.research_runtime.submit.assert_not_called()

    async def test_fresh_training_snapshot_precedes_allocate_and_original_approval(self):
        self.completed_prep(); self.bind('training')
        def register(ctx, phase, candidate, prior, pin, *, persist_snapshot):
            self.assertEqual(prior['preparation']['receipt']['execution']['taskId'], 'original-preparation')
            persist_snapshot({'schema': 1, 'synthetic': True})
            self.store.research_runtime.resources.targets[pin['targetRef']] = object()
        self.assembler.register_phase.side_effect = register
        lease = peer.lease(released=True) | {'localTaskId': 'task-training', 'nativeRunId': 'run-training', 'planId': 'plan-training'}
        async def submit(owner, task_id):
            body = self.service._read('receipt-training')
            self.assertIn('runtimeSnapshot', body)
            self.assertEqual(body['debitState'], 'CONFIRMED')
            self.assertEqual(body['state'], 'DISPATCH_UNKNOWN')
            return lease
        self.store.research_runtime.submit.side_effect = submit
        self.project.checkpoints.import_completed.return_value = {'id': 'original-checkpoint'}
        result = await self.service.drive_phase('receiver-alice', 'task-training')
        self.assertEqual(result['artifact'], {'id': 'original-checkpoint'})
        self.assertEqual(result['execution']['nativeRunId'], 'run-training')
        self.assertEqual(self.service._read('receipt-training')['state'], 'COMPLETED')
        args = self.service.commands.submit.await_args.args
        self.assertEqual(args[:2], ('receiver-alice', 'task-training'))
        self.assertEqual(args[2].requirementId, 'requirement')
        self.assertEqual(args[2].version, 1)
        self.assertEqual(self.store.research_runtime.submit.await_count, 1)
        with self.assertRaises(ValueError): await self.service.drive_phase('receiver-alice', 'task-training')
        self.assertEqual(self.store.research_runtime.submit.await_count, 1)

    async def test_custody_inspect_survives_run_revocation_without_dispatch(self):
        self.completed_prep(); ctx = self.bind('training')
        self.service.require_phase(ctx, 'training')
        body = self.store.rows['receipt-training']['body']
        body.update(state='UNKNOWN', targetFingerprint='f'*64,
                    runtimeSnapshot={'body': {'synthetic': True}, 'sha256': digest({'synthetic': True})})
        self.store.research_runtime._original.return_value = {'owner_id': 'receiver-alice', 'native_run_id': 'run-training', 'lease_id': 'original-lease'}
        self.store.research_runtime.observe_lease = AsyncMock(return_value={'id': 'original-lease', 'state': 'UNKNOWN'})
        self.service.auth.require.side_effect = PermissionError('run revoked')
        result = await self.service.inspect_phase('receiver-alice', 'task-training')
        self.assertEqual(result['lease']['id'], 'original-lease')
        self.assembler.restore_phase.assert_called_once()
        self.store.research_runtime.observe_lease.assert_awaited_once_with('original-lease')
        self.store.research_runtime.submit.assert_not_called()

    async def test_prepared_projection_is_empty_not_a_stop_claim(self):
        rid, envelope = self.prepare()
        receipt = peer.shell('preparation') | {'id': rid, 'remoteTaskId': None, 'remotePlanId': None,
            'remoteRunId': None, 'manifestHash': digest(self.source)}
        value = await self.service.project_evidence(receipt)
        self.assertEqual(value['scope'], envelope['scope'])
        for key in ('lease', 'launchProof', 'checkpoint', 'evaluation', 'preparation'):
            self.assertIsNone(value[key])
        self.assembler.register_phase.assert_not_called()
        self.store.research_runtime.submit.assert_not_called()

    async def test_preparation_projection_keeps_original_producer_not_receiver_child(self):
        ctx = self.bind(); self.service.require_phase(ctx, 'preparation')
        execution = {key: value for key, value in peer.contract()['training'].items() if key not in ('checkpoint', 'variantSha256')}
        original = {'execution': execution, 'artifact': {'id': 'original-token'}}
        self.store.rows['receipt-preparation']['body']['receipt'] = original
        self.assembler.preparation_receipt.return_value = original
        self.project.preparation.identity.return_value = ({'id': 'original-token'}, {'sha256': 'e'*64})
        receipt = peer.shell('preparation') | {'id': 'receipt-preparation', 'remoteTaskId': 'task-preparation',
            'remotePlanId': 'plan-preparation', 'remoteRunId': 'run-preparation', 'manifestHash': digest(self.source)}
        value = await self.service.project_evidence(receipt)
        self.assertEqual(value['preparation']['taskId'], execution['taskId'])
        self.assertNotEqual(value['preparation']['taskId'], receipt['remoteTaskId'])
        self.assertEqual(value['preparation']['artifactSha256'], 'e'*64)
        self.assertIsNone(value['lease'])

    async def test_start_drive_persists_before_scheduling_and_duplicate_never_reschedules(self):
        self.bind()
        self.store.lifecycle_observer._binding.return_value = {'status': 'running', 'persistedRunStatus': 'running'}
        self.service.max_polls = 10
        self.service.drive_phase = AsyncMock()
        reply = await self.service.start_drive('receiver-alice', 'task-preparation')
        self.assertEqual(reply['driveRequest']['status'], 'PENDING')
        self.assertEqual(self.service._read('receipt-preparation')['driveRequest'], reply['driveRequest'])
        self.assertEqual(await self.service.start_drive('receiver-alice', 'task-preparation'), reply)
        self.assertEqual(len(self.service._drives), 1)
        await self.service.close()
        self.assertEqual(self.service._read('receipt-preparation')['state'], 'UNKNOWN')
        self.assertEqual(self.service._read('receipt-preparation')['driveRequest']['status'], 'UNKNOWN')
        self.service.drive_phase.assert_not_awaited()
        self.assertEqual((await self.service.start_drive('receiver-alice', 'task-preparation'))['driveRequest']['status'], 'UNKNOWN')
        self.assertFalse(self.service._drives)

    async def test_pending_intent_after_restart_is_read_only_and_never_a_launch_grant(self):
        self.bind(); body = self.store.rows['receipt-preparation']['body']
        body['driveRequest'] = {'schema': 1, 'status': 'PENDING', 'taskId': 'task-preparation', 'nativeRunId': 'run-preparation',
            'planSha256': body['receiver']['planSha256'], 'bindingSha256': body['bindingSha256']}
        self.service.drive_phase = AsyncMock()
        await self.service.start_drive('receiver-alice', 'task-preparation')
        self.assertFalse(self.service._drives); self.service.drive_phase.assert_not_awaited()

    async def test_waiter_rejects_replaced_native_run_before_drive(self):
        self.bind(); self.service.drive_phase = AsyncMock()
        self.store.lifecycle_observer._binding.return_value = {'status': 'running', 'persistedRunStatus': 'running'}
        await self.service.start_drive('receiver-alice', 'task-preparation')
        workers = tuple(self.service._drives.values())
        self.store.tasks['task-preparation']['run_id'] = 'replacement'
        await asyncio.gather(*workers)
        self.assertEqual(self.service._read('receipt-preparation')['state'], 'UNKNOWN')
        self.service.drive_phase.assert_not_awaited()
        self.assertEqual(self.store.event.call_args.args[3], {'errorType': 'ValueError'})

    async def test_waiter_checks_actual_ready_native_status_and_bounded_capacity(self):
        self.bind(); self.service.max_polls = 10
        self.store.lifecycle_observer._binding.return_value = {'status': 'running', 'persistedRunStatus': 'running'}
        self.service.drive_phase = AsyncMock()
        await self.service.start_drive('receiver-alice', 'task-preparation')
        await asyncio.sleep(.001)
        self.service.drive_phase.assert_not_awaited()
        self.completed_prep(); self.bind('training')
        with self.assertRaises(ValueError): await self.service.start_drive('receiver-alice', 'task-training')
        await self.service.close()
        self.service.drive_phase.assert_not_awaited()

    async def test_waiter_drives_original_ready_task_once(self):
        self.bind(); self.service.max_polls = 1
        self.store.lifecycle_observer._binding.return_value = {'status': 'completed', 'persistedRunStatus': 'completed'}
        self.store.tasks['task-preparation']['terminal'] = True
        async def done(owner, task_id):
            self.assertEqual((owner, task_id), ('receiver-alice', 'task-preparation'))
            body = self.service._read('receipt-preparation'); updated = deepcopy(body); updated['state'] = 'COMPLETED'
            self.service._save(body, updated)
        self.service.drive_phase = AsyncMock(side_effect=done)
        await self.service.start_drive('receiver-alice', 'task-preparation')
        await asyncio.gather(*tuple(self.service._drives.values()))
        self.assertEqual(self.service._read('receipt-preparation')['driveRequest']['status'], 'COMPLETED')
        await self.service.start_drive('receiver-alice', 'task-preparation')
        self.assertEqual(self.service.drive_phase.await_count, 1)

    async def test_cancel_cas_blocks_pending_waiter_and_preserves_positive_barrier(self):
        self.completed_prep(); self.bind('training')
        self.store.lifecycle_observer._binding.return_value = {'status': 'running', 'persistedRunStatus': 'running'}
        self.service.max_polls = 10
        await self.service.start_drive('receiver-alice', 'task-training')
        await asyncio.sleep(.001)
        proof = self.service.cancel_before_dispatch('receiver-alice', 'task-training')
        assert proof is not None
        self.assertEqual(proof['receiverNativeRunId'], 'run-training')
        workers = tuple(self.service._drives.values())
        await asyncio.gather(*workers)
        await self.service.close()
        self.assertEqual(self.service._read('receipt-training')['state'], 'CANCELLED_NO_DISPATCH')
        self.assertEqual(self.service._read('receipt-training')['driveRequest']['status'], 'CANCELLED_NO_DISPATCH')
        self.store.research_runtime.submit.assert_not_called()
        self.assertEqual(self.service.cancel_before_dispatch('receiver-alice', 'task-training'), proof)
        with self.assertRaises(ValueError): await self.service.drive_phase('receiver-alice', 'task-training')
        self.store.research_runtime.submit.assert_not_called()

    async def test_no_dispatch_requires_cas_not_just_absent_lease(self):
        self.completed_prep(); self.bind('training')
        row = self.store.rows['receipt-training']['body']; row['state'] = 'DISPATCH_UNKNOWN'
        self.assertIsNone(self.service.cancel_before_dispatch('receiver-alice', 'task-training'))
        row['state'] = 'PREPARED'; self.store.leases = [{'id': 'uncatalogued-original'}]
        with self.assertRaises(ValueError): self.service.cancel_before_dispatch('receiver-alice', 'task-training')
        self.store.leases = []; self.store.research_runtime._original.return_value = {'lease_id': 'original'}
        with self.assertRaises(ValueError): self.service.cancel_before_dispatch('receiver-alice', 'task-training')
        self.store.research_runtime._original.return_value = None
        save = self.service._save
        def lose_cas(original, body):
            self.store.rows['receipt-training']['body']['state'] = 'DISPATCH_UNKNOWN'
            return save(original, body)
        self.service._save = lose_cas
        self.assertIsNone(self.service.cancel_before_dispatch('receiver-alice', 'task-training'))
        self.assertNotIn('noDispatch', self.service._read('receipt-training'))

    async def test_cas_proof_projection_binds_original_receiver_identity(self):
        self.completed_prep(); self.bind('training')
        proof = self.service.cancel_before_dispatch('receiver-alice', 'task-training')
        receipt = peer.shell() | {'id': 'receipt-training', 'remoteTaskId': 'task-training',
            'remotePlanId': 'plan-training', 'remoteRunId': 'run-training', 'manifestHash': digest(self.source)}
        self.assertEqual(self.service.no_dispatch_proof(receipt), proof)
        self.assertIsNone((await self.service.project_evidence(receipt))['lease'])
        with self.assertRaises(ValueError): self.service.no_dispatch_proof(receipt | {'remoteRunId': 'replacement'})
        self.store.leases = [{'id': 'unexpected'}]
        with self.assertRaises(ValueError): self.service.no_dispatch_proof(receipt)

    def projection_fixture(self):
        self.bind('training')
        value = peer.lease(released=True)
        value.update(localTaskId='task-training', nativeRunId='run-training', planId='plan-training')
        value['processBinding'].update(taskId='task-training', nativeRunId='run-training', planId='plan-training')
        value['gpuEvidence']['bindingFingerprint'] = evidence_fingerprint(value)
        body = self.store.rows['receipt-training']['body']
        body['targetFingerprint'] = 'f'*64
        body['config'] = self.assembler('training', self.candidate, {}, context=None)
        body['configSha256'] = digest(body['config'])
        body['receipt'] = {'execution': {'ownerId': 'receiver-alice', 'taskId': 'task-training', 'nativeRunId': 'run-training',
            'planId': 'plan-training', 'planFingerprint': 'c'*64, 'leaseId': value['id'], 'providerJobId': value['providerJobId']},
            'artifact': {'id': 'original-checkpoint'}}
        self.service.inspect_phase = AsyncMock(return_value={'lease': value})
        provider = Mock(); provider.read_launch_proof.return_value = peer.launch()
        self.store.research_runtime.resources._provider = Mock(return_value=provider)
        self.project.checkpoints.identity.return_value = ({'id': 'original-checkpoint'}, {'sha256': 'a'*64, 'sizeBytes': 16})
        receipt = peer.shell() | {'id': 'receipt-training', 'remoteTaskId': 'task-training',
            'remotePlanId': 'plan-training', 'remoteRunId': 'run-training', 'manifestHash': digest(self.source)}
        return receipt, provider

    async def test_canceled_projection_uses_retained_claims_and_fresh_custody_only(self):
        receipt, provider = self.projection_fixture()
        before = self.service._read('receipt-training')
        first = await self.service.project_evidence(receipt)
        self.assertIsNotNone(first['checkpoint'])
        self.assertEqual(self.service._read('receipt-training'), before)
        self.assertIn('receipt-training', self.store.evidence)
        self.assertNotIn('lease', self.store.evidence['receipt-training']['body'])
        self.store.tasks['task-training']['cancel_requested'] = True
        self.project.checkpoints.identity.side_effect = ValueError('scientific grant ended')
        provider.read_launch_proof.side_effect = ValueError('must not reread scientific proof')
        second = await self.service.project_evidence(receipt)
        self.assertEqual(second, first)
        self.assertTrue(receipt['scientificClaimsRetained'])
        self.assertEqual(getattr(self.service.inspect_phase, 'await_count'), 2)
        self.assertEqual(self.project.checkpoints.identity.call_count, 1)
        self.assertEqual(provider.read_launch_proof.call_count, 1)

    async def test_late_empty_projection_merges_newer_claims_without_changing_fresh_lease(self):
        receipt, _ = self.projection_fixture()
        full = await self.service.project_evidence(receipt)
        stale = deepcopy(full)
        for key in ('launchProof', 'checkpoint', 'evaluation', 'preparation'):
            stale[key] = None
        cache = deepcopy(self.store.evidence)
        phase = self.service._read('receipt-training')
        merged = self.service._retain_evidence(receipt, stale)
        self.assertEqual(merged, full)
        self.assertEqual(merged['lease'], stale['lease'])
        self.assertTrue(receipt['scientificClaimsRetained'])
        self.assertEqual(self.store.evidence, cache)
        self.assertEqual(self.service._read('receipt-training'), phase)
        # Cached claims cannot replace an incompatible fresh custody snapshot.
        stale['lease'] = None
        with self.assertRaises(ValueError): self.service._retain_evidence(receipt, stale)
        # A non-null conflicting claim is never silently replaced by history.
        conflict = deepcopy(full); conflict['checkpoint']['checkpoint']['sha256'] = 'e'*64
        with self.assertRaises(ValueError): self.service._retain_evidence(receipt, conflict)
        self.assertEqual(self.store.evidence, cache)

    async def test_phase_advancing_during_inspect_uses_new_receipt_and_verifies_artifacts(self):
        receipt, _ = self.projection_fixture()
        expected = deepcopy(self.store.rows['receipt-training']['body'])
        state = deepcopy(getattr(self.service.inspect_phase, 'return_value'))
        self.store.rows['receipt-training']['body'].pop('receipt')
        self.store.rows['receipt-training']['body'].pop('targetFingerprint')
        async def advance(owner, task_id):
            self.store.rows['receipt-training']['body'] = deepcopy(expected)
            return state
        self.service.inspect_phase = AsyncMock(side_effect=advance)
        projected = await self.service.project_evidence(receipt)
        self.assertIsNotNone(projected['checkpoint'])
        self.project.checkpoints.identity.assert_called_once()
        # Even with retained claims available, the newly observed active receipt
        # must reverify artifacts and surface integrity failures.
        self.store.rows['receipt-training']['body'].pop('receipt')
        self.store.rows['receipt-training']['body'].pop('targetFingerprint')
        self.project.checkpoints.identity.side_effect = ValueError('advanced artifact corrupt')
        with self.assertRaisesRegex(ValueError, 'advanced artifact corrupt'):
            await self.service.project_evidence(receipt)

    async def test_phase_identity_changed_during_inspect_is_rejected(self):
        receipt, _ = self.projection_fixture()
        state = deepcopy(getattr(self.service.inspect_phase, 'return_value'))
        async def replace(owner, task_id):
            self.store.rows['receipt-training']['body']['nativeRunId'] = 'replacement-native'
            return state
        self.service.inspect_phase = AsyncMock(side_effect=replace)
        with self.assertRaises(ValueError): await self.service.project_evidence(receipt)
        self.project.checkpoints.identity.assert_not_called()

    async def test_authority_ended_retains_but_authorized_corruption_is_not_hidden(self):
        receipt, _ = self.projection_fixture()
        first = await self.service.project_evidence(receipt)
        self.project.checkpoints.identity.side_effect = ValueError('artifact integrity invalid')
        with self.assertRaisesRegex(ValueError, 'artifact integrity invalid'):
            await self.service.project_evidence(receipt)
        self.store.handoff_receiver.authorize.side_effect = HTTPException(409, 'original parent ended')
        self.assertEqual(await self.service.project_evidence(receipt), first)
        self.assertTrue(receipt['scientificClaimsRetained'])
        self.store.handoff_receiver.authorize.side_effect = HTTPException(503, 'authority unavailable')
        with self.assertRaises(HTTPException): await self.service.project_evidence(receipt)

    async def test_never_observed_canceled_phase_does_not_invent_claims(self):
        receipt, provider = self.projection_fixture()
        self.store.tasks['task-training']['cancel_requested'] = True
        projected = await self.service.project_evidence(receipt)
        self.assertIsNotNone(projected['lease'])
        self.assertIsNone(projected['checkpoint']); self.assertIsNone(projected['launchProof'])
        self.assertFalse(receipt['scientificClaimsRetained'])
        self.assertFalse(self.store.evidence)
        self.project.checkpoints.identity.assert_not_called(); provider.read_launch_proof.assert_not_called()

    async def test_retained_claims_are_immutable_and_scope_bound(self):
        receipt, _ = self.projection_fixture()
        await self.service.project_evidence(receipt)
        self.project.checkpoints.identity.return_value = ({'id': 'original-checkpoint'}, {'sha256': 'b'*64, 'sizeBytes': 16})
        with self.assertRaises(ValueError): await self.service.project_evidence(receipt)
        self.store.tasks['task-training']['cancel_requested'] = True
        self.store.evidence['receipt-training']['body']['scope']['candidateSha256'] = 'f'*64
        with self.assertRaises(ValueError): await self.service.project_evidence(receipt)

    def custody_fixture(self):
        self.projection_fixture()
        task = self.store.tasks['task-training']; task['terminal'] = True
        body = self.store.rows['receipt-training']['body']; body['state'] = 'COMPLETED'
        lease = getattr(self.service.inspect_phase, 'return_value')['lease']
        lease.update(connectionRef=body['config']['targetRef'], targetFingerprint='f'*64)
        ticket = {'id': task['run_id'], 'status': 'completed', 'persistedRunStatus': 'completed'}
        self.store.research_runtime._original.return_value = {'lease_id': lease['id'], 'owner_id': 'receiver-alice', 'native_run_id': task['run_id']}
        self.store.research_runtime._custody = Mock(side_effect=lambda _: (lease, object(), deepcopy(task), ticket))
        origin = self.store.handoff_receiver._origin.return_value
        origin.configuration_revision, origin.fingerprint = '2', 'd'*64
        reply = {'schema': 1, 'tool': None, 'outcome': 'custody-readable', 'originRef': 'cloud', 'originOwner': 'alice',
            'originTaskId': body['binding']['scope']['originChildTaskId'], 'manifestSha256': digest(self.source),
            'receiverIdentity': 'receiver-alice', 'receiverTaskId': task['id'], 'nativeRunId': task['run_id'],
            'phaseScopeSha256': digest(body['binding']['scope']), 'leaseId': lease['id'],
            'custodyProofSha256': 'a'*64, 'targetRevision': '3', 'targetFingerprint': 'e'*64, 'targetRef': 'receiver'}
        origin.authorize.check_scientific_custody = Mock(return_value=reply)
        self.store.handoff_receiver._check_row = Mock()
        self.store.remote_bindings = SimpleNamespace(inspect=Mock(return_value={
            'receiptId': 'receipt-training', 'receiverOwner': 'receiver-alice', 'receiverPlanId': task['plan_id'],
            'manifestHash': digest(self.source), 'receiverConfiguration': {'revision': '2', 'sha256': 'd'*64},
            'sourceConfiguration': {'revision': '3', 'sha256': 'e'*64}}))
        return self.service._context('receiver-alice', task['id']), lease, ticket, origin.authorize.check_scientific_custody

    def test_completed_checkpoint_custody_uses_distinct_readonly_proof_not_execution(self):
        ctx, lease, _, check = self.custody_fixture()
        self.assertIsNone(self.service.require_completed_custody('receiver-alice', ctx.plan, ctx.run_context))
        check.assert_called_once_with('alice', 'cloud-child-training', digest(self.source),
            receiver_task_id='task-training', native_run_id='run-training',
            phase_scope_sha256=digest(self.service._read('receipt-training')['binding']['scope']), lease_id=lease['id'])
        self.store.handoff_receiver.authorize.assert_not_called()
        self.project.checkpoints.identity.assert_not_called()
        self.store.research_runtime.submit.assert_not_called()
        self.assertFalse(self.store.evidence)

    def test_completed_custody_denies_changed_original_and_nonpositive_stop(self):
        ctx, lease, ticket, check = self.custody_fixture()
        for mutate, restore in (
            (lambda: self.store.tasks['task-training'].update(cancel_requested=True), lambda: self.store.tasks['task-training'].update(cancel_requested=False)),
            (lambda: ticket.update(status='paused'), lambda: ticket.update(status='completed')),
            (lambda: ticket.update(persistedRunStatus='paused'), lambda: ticket.update(persistedRunStatus='completed')),
            (lambda: lease.update(capacityHeld=True), lambda: lease.update(capacityHeld=False)),
            (lambda: self.store.rows['receipt-training']['body'].update(state='UNKNOWN'), lambda: self.store.rows['receipt-training']['body'].update(state='COMPLETED'))):
            mutate()
            with self.assertRaises(ValueError): self.service.require_completed_custody('receiver-alice', ctx.plan, ctx.run_context)
            restore()
        check.assert_not_called()
        check.return_value['leaseId'] = 'replacement-lease'
        with self.assertRaises(ValueError): self.service.require_completed_custody('receiver-alice', ctx.plan, ctx.run_context)

    def test_readonly_custody_denial_and_postcheck_cancellation_never_grant_execution(self):
        ctx, _, _, check = self.custody_fixture()
        check.side_effect = HTTPException(403, 'current origin custody denied')
        with self.assertRaises(HTTPException): self.service.require_completed_custody('receiver-alice', ctx.plan, ctx.run_context)
        check.side_effect = lambda *args, **kwargs: self.store.tasks['task-training'].update(cancel_requested=True) or check.return_value
        with self.assertRaises(ValueError): self.service.require_completed_custody('receiver-alice', ctx.plan, ctx.run_context)
        self.store.research_runtime.submit.assert_not_called()

    async def test_baseline_fresh_identity_check_and_no_effects(self):
        expected = {'schema': 1, 'projectId': 'project', 'projectPin': '4'*64, 'observation': self.baseline}
        self.assertEqual(await self.service.project_baseline('receiver-alice', 'project', '4'*64), expected)
        await self.service.project_baseline('receiver-alice', 'project', '4'*64)
        self.assertEqual(self.reader.await_count, 2)
        with self.assertRaises(ValueError): await self.service.project_baseline('receiver-alice', 'project', '5'*64)
        self.reader.return_value = self.baseline | {'variantSha256': 'b'*64}
        with self.assertRaises(ValueError): await self.service.project_baseline('receiver-alice', 'project', '4'*64)
        self.store.research_runtime.submit.assert_not_called()

# pyright: reportMissingImports=false
"""Controlled custody/state tests only; no native queue/process/scientific proof."""
from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.autoresearch_children import AutoResearchChildren, phase_pin, positive_lease
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.store import digest
from test_research_manifest import example_manifest


def pin():
    manifest = example_manifest()
    return {'targetRef': 'operator-target', 'comparisonManifestSha256': manifest_fingerprint(manifest),
        'variantSha256': '1' * 64, 'comparisonManifest': manifest}


class MemoryStore:
    def __init__(self):
        self.row = None
        self.task_value = {'id': 'parent', 'owner_id': 'alice', 'run_id': 'native-parent',
            'plan_id': 'parent-plan', 'terminal': False, 'cancel_requested': False}
        self.plan_value: dict[str, Any] = {'id': 'parent-plan', 'fingerprint': '2' * 64}
        self.lifecycle_observer = SimpleNamespace(_binding=Mock(return_value={'status': 'paused', 'persistedRunStatus': 'paused'}))
        self.delegation = SimpleNamespace(create=AsyncMock(side_effect=ConnectionError('controlled lost acknowledgment')))
        self.process_runtime = SimpleNamespace(resources=SimpleNamespace(targets={'operator-target': 'target'}, _authorize=Mock(return_value='target'), _target_fingerprint=Mock(return_value='3' * 64)))
        self.research_runtime = self.process_runtime
    def task(self, identifier, owner):
        if identifier != self.task_value['id'] or owner != self.task_value['owner_id']:
            raise PermissionError('controlled owner denial')
        return deepcopy(self.task_value)
    def plan(self, identifier, owner):
        if identifier != self.plan_value['id'] or owner != 'alice':
            raise PermissionError('controlled plan denial')
        return deepcopy(self.plan_value)
    def sql(self, statement, **values):
        if statement.startswith('CREATE'): return []
        if statement.startswith('INSERT'):
            if self.row is not None: return []
            self.row = {'parent_run_id': values['run'], 'owner_id': values['owner'],
                'parent_task_id': values['parent'], 'call_id': values['call'], 'fingerprint': values['fp'],
                'body': json.loads(values['body'])}
            return [{'parent_run_id': values['run']}]
        if statement.startswith('SELECT * FROM af_autoresearch_experiments'):
            return [deepcopy(self.row)] if self.row is not None else []
        if statement.startswith('UPDATE'):
            assert self.row is not None
            if 'original' in values and self.row['body'] != json.loads(values['original']): return []
            self.row['body'] = json.loads(values['body'])
            return [{'parent_run_id': values['run']}] if 'RETURNING' in statement else []
        raise AssertionError('Unexpected synthetic SQL')


class ScientificCustodyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.candidate = {'hypothesis': 'synthetic hypothesis', 'trainPy': '# bounded synthetic source\n', 'validated': {'manifest': '4' * 64}}
        self.preset = SimpleNamespace(fingerprint='5' * 64, limits={'maxExperiments': 1}, manifest=example_manifest())
        self.service = SimpleNamespace(current=Mock(return_value=self.preset),
            row=Mock(return_value={'body': {'candidates': {'candidate': self.candidate}}}))
        self.ctx = SimpleNamespace(run_context=SimpleNamespace(user_id='alice', session_id='parent', run_id='native-parent'))
        self.config = Mock(return_value=pin())
        self.config.phase_target.return_value = SimpleNamespace(owners=frozenset({'alice'}))
        self.children = AutoResearchChildren(self.store, Mock(), self.service,
            phase_config=self.config, preparation=Mock(), checkpoints=Mock())

    async def test_original_dispatching_job_is_observed_without_second_allocation(self):
        child = {'id': 'child', 'owner_id': 'alice', 'run_id': 'child-run', 'plan_id': 'child-plan'}
        finished = {'id': 'lease', 'state': 'RECLAIMED', 'ownerId': 'alice', 'localTaskId': 'child',
            'nativeRunId': 'child-run', 'planId': 'child-plan', 'capacityHeld': False,
            'executionStatus': 'COMPLETED', 'exitCode': 0, 'providerJobId': 'original-job',
            'stopEvidence': {'allStopped': True}, 'gpuEvidence': {'state': 'RELEASED'}}
        runtime = SimpleNamespace(_config=Mock(return_value=('ref', {}, 'variant')),
            _paused=Mock(return_value={'id': 'requirement', 'version': 1}),
            submit=AsyncMock(return_value={**finished, 'state': 'UNKNOWN', 'executionStatus': 'DISPATCHING', 'capacityHeld': True}),
            inspect_task=AsyncMock(return_value=finished))
        self.store.research_runtime = runtime
        self.store.plan = Mock(return_value={'id': 'child-plan'})
        self.children._bound = Mock()
        self.children._child = Mock(return_value=child)
        self.children._wait = AsyncMock()
        self.children._receipt = Mock(return_value={'original': True})
        self.service.commands = SimpleNamespace(submit=AsyncMock())
        self.store.lifecycle_observer._binding.side_effect = [
            {'status': 'paused', 'persistedRunStatus': 'paused'},
            {'status': 'completed', 'persistedRunStatus': 'completed'}]
        self.assertEqual(await self.children._drive(self.ctx, 'training', {'requestId': 'original-request'}), {'original': True})
        runtime.submit.assert_awaited_once_with('alice', 'child')
        runtime.inspect_task.assert_awaited_once_with('alice', 'child')
        self.service.commands.submit.assert_awaited_once()
        self.store.lifecycle_observer._binding.side_effect = None
        self.store.lifecycle_observer._binding.return_value = {'status': 'paused', 'persistedRunStatus': 'paused'}
        for extra in ({'providerJobId': None}, {'preDispatchFailure': {'dispatchAttempted': False}}):
            runtime.submit.return_value = {**finished, 'state': 'UNKNOWN', 'executionStatus': 'DISPATCHING', **extra}
            runtime.inspect_task.reset_mock()
            with self.assertRaisesRegex(ValueError, 'CHILD_PROCESS_UNKNOWN'):
                await self.children._drive(self.ctx, 'training', {'requestId': 'original-request'})
            runtime.inspect_task.assert_not_awaited()

    async def test_preparation_verification_reads_original_and_never_dispatches(self):
        self.children.require_child = Mock(return_value=pin())
        self.store.authorize_tool = Mock()
        receipt = {'execution': {'taskId': 'original-producer', 'nativeRunId': 'original-run'},
                   'artifact': {'id': 'original-artifact'}}
        self.config.preparation_receipt.return_value = receipt
        self.assertEqual(await self.children.verify_preparation(self.ctx), receipt)
        self.assertEqual(self.children.require_child.call_count, 2)
        self.store.authorize_tool.assert_called_once_with(self.ctx.run_context, 'research_preparation_verify')
        self.store.delegation.create.assert_not_awaited()
        self.assertIsNone(self.store.row)
        child = {'id': 'verifier', 'run_id': 'verifier-run', 'plan_id': 'verifier-plan'}
        combined = self.children._preparation_receipt(child)
        self.assertEqual(combined['execution']['taskId'], 'original-producer')
        self.assertEqual(combined['verification']['taskId'], 'verifier')
        with self.assertRaises(ValueError):
            self.children._preparation_receipt({**child, 'id': 'original-producer'})

    async def test_commit_before_delegation_and_lost_ack_never_replays(self):
        async def lost(*args):
            body = self.children._read('native-parent')
            self.assertEqual(body['phases']['preparation']['state'], 'DISPATCH_UNKNOWN')
            self.assertEqual(body['candidate'], self.candidate)
            self.assertEqual(args[3], 'scientific-preparation')
            self.assertEqual(args[4], body['phases']['preparation']['requestId'])
            raise ConnectionError('controlled lost acknowledgment')
        self.store.delegation.create.side_effect = lost
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original-mcp-call')
        self.assertEqual(self.children._read('native-parent')['state'], 'UNKNOWN')
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_EXPERIMENT_UNKNOWN'):
            await self.children.experiment(self.ctx, self.candidate, 'original-mcp-call')
        self.assertEqual(self.store.delegation.create.await_count, 1)
        self.assertEqual(self.config.call_count, 1)

    async def test_new_call_cannot_bypass_unknown_original_candidate(self):
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original')
        with self.assertRaises(ValueError): await self.children.experiment(self.ctx, self.candidate, 'replacement')
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_actual_durable_pause_and_one_experiment_required(self):
        for ticket in ({'status': 'running', 'persistedRunStatus': 'paused'}, {'status': 'paused', 'persistedRunStatus': 'running'}):
            self.store.lifecycle_observer._binding.return_value = ticket
            with self.assertRaises(ValueError): await self.children.experiment(self.ctx, self.candidate, 'original')
        self.assertIsNone(self.store.row)
        self.store.delegation.create.assert_not_called()

    async def test_revocation_after_intent_prevents_child_creation(self):
        calls = 0
        def authority(_ctx):
            nonlocal calls
            calls += 1
            if calls >= 3: raise PermissionError('controlled revocation')
            return self.preset
        self.service.current.side_effect = authority
        with self.assertRaises(PermissionError): await self.children.experiment(self.ctx, self.candidate, 'original')
        self.store.delegation.create.assert_not_called()
        self.assertEqual(self.children._read('native-parent')['state'], 'UNKNOWN')

    async def test_candidate_bytes_and_phase_pin_tamper_fail_closed(self):
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original')
        assert self.store.row is not None
        original = deepcopy(self.store.row)
        self.store.row['body']['candidate']['trainPy'] = '# replaced'
        with self.assertRaises(ValueError): self.children._read('native-parent')
        self.store.row = original
        self.store.row['body']['phases']['preparation']['config']['targetRef'] = 'other-target'
        with self.assertRaises(ValueError): self.children._read('native-parent')

    def test_phase_manifest_exact_hash_and_no_extra_user_fields(self):
        value = pin(); self.assertEqual(phase_pin(value), value)
        for altered in ({**value, 'comparisonManifestSha256': '0' * 64}, {**value, 'launch': True}, {**value, 'variantSha256': 'not-a-sha'}):
            with self.assertRaises(ValueError): phase_pin(altered)

    def test_completion_requires_original_owner_run_success_and_gpu_release(self):
        task = self.store.task_value
        lease = {'ownerId': 'alice', 'localTaskId': 'parent', 'nativeRunId': 'native-parent', 'planId': 'parent-plan',
            'state': 'RECLAIMED', 'capacityHeld': False, 'executionStatus': 'COMPLETED', 'exitCode': 0,
            'providerJobId': 'original-job', 'stopEvidence': {'allStopped': True}, 'gpuEvidence': {'state': 'RELEASED'}}
        self.assertEqual(positive_lease(lease, task, gpu=True), lease)
        for change in ({'ownerId': 'bob'}, {'nativeRunId': 'new'}, {'capacityHeld': True}, {'exitCode': False},
            {'executionStatus': 'FAILED'}, {'stopEvidence': {'allStopped': False}}, {'gpuEvidence': {'state': 'UNKNOWN'}}):
            with self.assertRaises(ValueError): positive_lease({**lease, **change}, task, gpu=True)
        self.assertEqual(digest(lease), digest(deepcopy(lease)))

    async def test_cleanup_no_experiment_requires_original_identity_but_not_run_grant(self):
        self.service.current.side_effect = PermissionError('revoked')
        self.assertTrue(await self.children.cleanup(self.ctx))
        self.service.current.assert_not_called()
        self.ctx.run_context.run_id = 'replacement'
        self.assertFalse(await self.children.cleanup(self.ctx))

    async def test_cleanup_missing_original_child_never_asserts_stopped(self):
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original')
        self.assertFalse(await self.children.cleanup(self.ctx))
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_cleanup_certifies_children_separately_from_still_paused_parent(self):
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original')
        child = {'id': 'original-child'}
        self.children._child = Mock(return_value=child)
        self.store.lifecycle_observer._facts = Mock(return_value={'stopped': True, 'unknown': False})
        self.service.current.side_effect = PermissionError('revoked')
        self.assertTrue(await self.children.cleanup(self.ctx))
        self.store.lifecycle_observer._facts.assert_called_once_with(child)
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_cleanup_cancels_original_without_owner_read_or_run_grants(self):
        with self.assertRaises(ConnectionError): await self.children.experiment(self.ctx, self.candidate, 'original')
        child = {'id': 'original-child'}
        self.children._child = Mock(return_value=child)
        self.store.delegation._facts = AsyncMock(side_effect=PermissionError('read revoked'))
        self.service.current.side_effect = PermissionError('run revoked')
        self.store.lifecycle_observer._facts = Mock(side_effect=[{'stopped': False, 'unknown': True},
            {'stopped': True, 'unknown': False}])
        self.store.lifecycle_observer.observe_root = AsyncMock()
        self.store.request_cancel = Mock()
        self.assertTrue(await self.children.cleanup(self.ctx))
        self.store.request_cancel.assert_called_once_with('original-child')
        self.store.lifecycle_observer.observe_root.assert_awaited_once_with('parent')
        self.store.delegation._facts.assert_not_awaited()
        self.assertEqual(self.store.delegation.create.await_count, 1)

    async def test_runtime_snapshot_is_durable_immutable_and_preserved_after_registration(self):
        snapshot = {'schema': 1, 'binding': {'parentRunId': 'native-parent'}, 'source': 'synthetic'}
        def register(ctx, phase, candidate, prior, config, *, persist_snapshot):
            self.assertEqual(persist_snapshot(snapshot), snapshot)
            self.assertEqual(persist_snapshot(deepcopy(snapshot)), snapshot)
            with self.assertRaises(ValueError):
                persist_snapshot({**snapshot, 'source': 'replacement'})
        self.config.register_phase.side_effect = register
        with self.assertRaises(ConnectionError):
            await self.children.experiment(self.ctx, self.candidate, 'original')
        body = self.children._read('native-parent')
        self.assertEqual(body['phases']['preparation']['runtimeSnapshot'],
                         {'sha256': digest(snapshot), 'body': snapshot})
        self.assertEqual(body['phases']['preparation']['targetFingerprint'], '3' * 64)
        self.store.row['body']['phases']['preparation']['runtimeSnapshot']['body']['source'] = 'tampered'
        with self.assertRaises(ValueError): self.children._read('native-parent')

    async def test_concrete_registration_after_intent_and_provider_rejection_before_dispatch(self):
        def registered(ctx, phase, candidate, prior, config, *, persist_snapshot):
            body = self.children._read('native-parent')
            self.assertEqual(body['phases'][phase]['config'], config)
            self.assertEqual(candidate, self.candidate)
            self.assertEqual(prior, {})
        self.config.register_phase.side_effect = registered
        self.config.verify_phase.side_effect = ValueError('synthetic actual source mismatch')
        with self.assertRaises(ValueError):
            await self.children.experiment(self.ctx, self.candidate, 'original')
        self.config.register_phase.assert_called_once()
        self.store.delegation.create.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_EXPERIMENT_UNKNOWN'):
            await self.children.experiment(self.ctx, self.candidate, 'original')
        self.config.register_phase.assert_called_once()

    def test_child_plan_requires_exact_application_preset_root_and_local_scope(self):
        self.preset.id = 'scientific-preset'
        self.store.process_runtime._context = Mock(return_value=self.ctx.run_context)
        self.store.plan_value['applicationRef'] = {'id': 'app', 'version': 1}
        plan = {'applicationRef': {'id': 'app', 'version': 1},
            'delegation': {'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': 1}}
        context = SimpleNamespace(plan=deepcopy(plan), spec={'config': {'presetId': self.preset.id, 'phase': 'training'}})
        self.children._child_plan(context, 'training', self.store.task_value)
        for change in ({'applicationRef': {'id': 'app', 'version': 2}}, {'remoteHandoff': {'enabled': True}},
                {'delegation': {'parentTaskId': 'parent', 'rootTaskId': 'foreign', 'depth': 1}},
                {'delegation': {'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': True}}):
            context.plan = {**plan, **change}
            with self.assertRaises(ValueError): self.children._child_plan(context, 'training', self.store.task_value)
        context.plan = plan; context.spec['config']['presetId'] = 'other-preset'
        with self.assertRaises(ValueError): self.children._child_plan(context, 'training', self.store.task_value)

    async def test_result_verifier_rechecks_original_receipts_and_rejects_injected_flags(self):
        phases = {}
        children = {}
        leases = {}
        for phase in ('preparation', 'training', 'evaluation'):
            child = {'id': phase, 'owner_id': 'alice', 'run_id': 'native-' + phase, 'plan_id': 'plan-' + phase}
            children[phase] = child
            lease = {'id': 'lease-' + phase, 'ownerId': 'alice', 'localTaskId': phase,
                'nativeRunId': child['run_id'], 'planId': child['plan_id'], 'state': 'RECLAIMED',
                'capacityHeld': False, 'executionStatus': 'COMPLETED', 'exitCode': 0,
                'providerJobId': 'job-' + phase, 'stopEvidence': {'allStopped': True}, 'gpuEvidence': {'state': 'RELEASED'}}
            leases[lease['id']] = lease
            self.children.store.plan = Mock(return_value={'fingerprint': '9' * 64})
            receipt = self.children._receipt(child, lease, {'id': 'artifact-' + phase} if phase != 'evaluation' else None)
            phases[phase] = {'state': 'COMPLETED', 'config': pin(), 'targetFingerprint': '3' * 64,
                'receipt': receipt, 'requestId': phase}
        original = deepcopy(phases['preparation']['receipt'])
        original['execution'].update(taskId='original-preparation', nativeRunId='original-preparation-run')
        self.config.preparation_receipt.return_value = original
        phases['preparation']['receipt'] = self.children._preparation_receipt(children['preparation'])
        body = {'candidate': self.candidate, 'phases': phases, 'state': 'DONE'}
        self.children._bound = Mock(return_value=body)
        self.children._child = Mock(side_effect=lambda owner, parent, entry: children[entry['requestId']])
        self.store.lifecycle_observer._binding.return_value = {'status': 'completed', 'persistedRunStatus': 'completed'}
        resources = self.store.process_runtime.resources
        resources.inspect = Mock(side_effect=lambda owner, lease: deepcopy(leases[lease]))
        self.store.process_runtime._original = Mock(side_effect=lambda child: None if child == 'preparation' else {'lease_id': 'lease-' + child})
        self.store.research_runtime = self.store.process_runtime
        self.children.checkpoints.identity.return_value = ({'id': 'artifact-training'}, {'sha256': '7' * 64, 'sizeBytes': 100})
        from agent_factory.research_evaluation_service import ResearchEvaluationService
        verifier = object.__new__(ResearchEvaluationService)
        verifier.verify = AsyncMock(return_value={'evaluatorCustodyVerified': True})
        self.config.evaluation_service.return_value = verifier
        result = await self.children._verified_result(self.ctx, body)
        body['result'] = result
        self.assertEqual(result['originalReferences']['checkpoint'], {'artifactId': 'artifact-training', 'sha256': '7' * 64})
        self.assertEqual(result['originalReferences']['training']['providerJobId'], 'job-training')
        self.assertEqual(await self.children.result_verifier(self.ctx, result), result)
        self.assertEqual(self.config.verify_phase.call_count, 6)
        self.children.preparation.input_pin.assert_called_with('alice', 'original-preparation', 'artifact-preparation')
        with self.assertRaises(ValueError): await self.children.result_verifier(self.ctx, {**result, 'scientificConclusionVerified': True})
        leases['lease-training']['capacityHeld'] = True
        with self.assertRaises(ValueError): await self.children.result_verifier(self.ctx, result)
        self.assertEqual(verifier.verify.await_count, 2)

    async def test_current_preset_manifest_mismatch_blocks_self_consistent_phase_before_dispatch(self):
        def changed_config(*args, **kwargs):
            self.preset.manifest = {**example_manifest(), 'baselineSourceManifestSha256': 'a' * 64}
            return pin()
        self.config.side_effect = changed_config
        with self.assertRaises(ValueError):
            await self.children.experiment(self.ctx, self.candidate, 'original')
        self.config.register_phase.assert_not_called()
        self.store.delegation.create.assert_not_called()

    async def test_retained_phase_rechecks_current_manifest_even_when_preset_fingerprint_stays_same(self):
        with self.assertRaises(ConnectionError):
            await self.children.experiment(self.ctx, self.candidate, 'original')
        body = self.children._bound(self.ctx)
        self.preset.manifest = {**example_manifest(), 'baselineSourceManifestSha256': 'a' * 64}
        with self.assertRaises(ValueError): self.children._bound(self.ctx)
        with self.assertRaises(ValueError): self.children._verify_phase(self.ctx, 'preparation', body, 'target')
        self.assertEqual(self.store.delegation.create.await_count, 1)

    def test_native_enriched_plan_accepts_only_original_runtime_ids(self):
        context = SimpleNamespace(run_context=self.ctx.run_context, plan=deepcopy(self.store.plan_value))
        self.children._runtime_plan(context, self.store.task_value)
        context.plan.update(taskId='parent', runId='native-parent')
        self.children._runtime_plan(context, self.store.task_value)
        original = deepcopy(context.plan)
        for changed in ({'taskId': 'foreign'}, {'runId': 'replacement'}, {'taskId': None}, {'extra': 'unapproved'}):
            context.plan = {**original, **changed}
            with self.assertRaises(ValueError): self.children._runtime_plan(context, self.store.task_value)

    async def test_completed_custody_read_keeps_original_pins_without_active_dispatch_grant(self):
        with self.assertRaises(ConnectionError):
            await self.children.experiment(self.ctx, self.candidate, 'original')
        body = self.children._read('native-parent')
        body['phases']['training'] = deepcopy(body['phases']['preparation'])
        parent = deepcopy(self.store.task_value)
        child = {**parent, 'id': 'child', 'run_id': 'child-native', 'plan_id': 'child-plan', 'terminal': True}
        self.preset.id = 'scientific-preset'
        parent_plan = {**self.store.plan_value, 'applicationRef': {'id': 'app', 'version': 1}}
        child_plan = {**parent_plan, 'id': 'child-plan', 'mode': 'scientific-training',
            'delegation': {'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': 1}}
        self.store.task = Mock(side_effect=lambda identifier, owner: deepcopy(child if identifier == 'child' else parent))
        self.store.plan = Mock(side_effect=lambda identifier, owner: deepcopy(child_plan if identifier == 'child-plan' else parent_plan))
        self.store.process_runtime._context = Mock(return_value=self.ctx.run_context)
        self.store.delegation.authorize_child = Mock(side_effect=PermissionError('completed child cannot dispatch'))
        self.store.delegation._link = Mock(return_value={'owner_id': 'alice', 'plan_id': 'child-plan',
            'parent_id': 'parent', 'root_id': 'parent', 'depth': 1})
        self.store.lifecycle_observer._binding.return_value = {'status': 'completed', 'persistedRunStatus': 'completed'}
        self.children._bound = Mock(return_value=body)
        self.children._child = Mock(return_value=child)
        ctx = SimpleNamespace(run_context=SimpleNamespace(user_id='alice', session_id='child', run_id='child-native'),
            plan=child_plan, spec={'config': {'presetId': self.preset.id, 'phase': 'training'}})
        self.config.verify_phase.reset_mock()
        self.config.verify_phase.side_effect = RuntimeError('Retention lock must precede metadata transaction')
        self.assertEqual(self.children.require_child_custody(ctx, 'training'), pin())
        self.store.delegation.authorize_child.assert_not_called()
        self.config.verify_authority.assert_called_once()
        self.config.verify_phase.assert_not_called()
        with self.assertRaises(PermissionError): self.children.require_child(ctx, 'training')
        self.store.delegation._link.return_value['root_id'] = 'foreign'
        with self.assertRaises(ValueError): self.children.require_child_custody(ctx, 'training')
        self.store.delegation._link.return_value['root_id'] = 'parent'
        self.service.current.side_effect = PermissionError('parent revoked')
        with self.assertRaises(PermissionError): self.children.require_child_custody(ctx, 'training')


    async def test_separate_preparation_target_never_needs_new_registry_or_restoration(self):
        self.store.process_runtime.resources.targets.clear()
        self.store.process_runtime.resources._authorize.side_effect = AssertionError('legacy provider must not be registered')
        with self.assertRaises(ConnectionError):
            await self.children.experiment(self.ctx, self.candidate, 'original')
        body = self.children._read('native-parent')
        self.assertEqual(body['phases']['preparation']['targetFingerprint'], '3'*64)
        self.children._restore_phase(self.ctx, 'preparation', body)
        self.config.restore_phase.assert_not_called()
        self.config.phase_target.assert_called_with('preparation', pin())
        self.store.process_runtime.resources._authorize.assert_not_called()
        self.assertEqual(self.store.process_runtime.resources.targets, {})
        self.config.phase_target.return_value = SimpleNamespace(owners=frozenset({'bob'}))
        with self.assertRaises(ValueError): self.children._phase_target('alice', 'preparation', pin())

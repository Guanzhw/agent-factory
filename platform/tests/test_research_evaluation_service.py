# pyright: reportMissingImports=false
"""Strict controlled custody doubles; no DB, execution, file loading or provider."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.store import digest
from agent_factory.research_manifest import manifest_fingerprint
from test_research_evaluation import example_contract, output


class ResearchEvaluationServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.contract = example_contract()
        self.raw_checkpoint = b'synthetic checkpoint bytes'
        self.contract['training']['checkpoint'].update(sizeBytes=len(self.raw_checkpoint), sha256=hashlib.sha256(self.raw_checkpoint).hexdigest())
        self.records, self.plans, self.rows = {}, {}, {}
        self.training_provider = SimpleNamespace(read_completed_output=Mock(side_effect=AssertionError('Never read training output')))
        self.evaluator_provider = SimpleNamespace(read_completed_output=Mock(side_effect=lambda *_: output(self.contract)))
        self.targets = {'training': SimpleNamespace(provider=self.training_provider, pin='training-pin'),
                        'evaluation': SimpleNamespace(provider=self.evaluator_provider, pin='evaluation-pin')}
        for field, reference in (('training', 'training'), ('evaluatorExecution', 'evaluation')):
            execution = self.contract[field]
            lease = {'ownerId': 'alice', 'id': execution['leaseId'], 'localTaskId': execution['taskId'],
                'nativeRunId': execution['nativeRunId'], 'planId': execution['planId'], 'providerJobId': execution['providerJobId'],
                'state': 'RECLAIMED', 'capacityHeld': False, 'executionStatus': 'COMPLETED', 'exitCode': 0,
                'executionGuard': {'manifestSha256': manifest_fingerprint(self.contract['comparisonManifest']), 'variantSha256': self.contract['training']['variantSha256']},
                'stopEvidence': {'allStopped': True}, 'connectionRef': reference, 'targetFingerprint': self.targets[reference].pin}
            task = {'id': execution['taskId'], 'owner_id': 'alice', 'run_id': execution['nativeRunId'],
                    'plan_id': execution['planId'], 'cancel_requested': False}
            self.records[execution['leaseId']] = (lease, self.targets[reference], task, {})
            self.plans[execution['planId']] = {'id': execution['planId'], 'fingerprint': execution['planFingerprint']}
            self.rows[execution['taskId']] = {'task_id': execution['taskId'], 'owner_id': 'alice',
                'native_run_id': execution['nativeRunId'], 'lease_id': execution['leaseId'], 'effect_key': 'research-process-run-v1'}
        self.current_manifest = deepcopy(self.contract['comparisonManifest'])
        self.current_variant = self.contract['training']['variantSha256']
        runtime = SimpleNamespace(_custody=lambda identifier: self.records[identifier], _context=lambda task: task,
            _config=lambda task, plan: ('training' if task['id'] == 'train-task' else 'evaluation', self.current_manifest, self.current_variant))
        self.auth = SimpleNamespace(require=Mock())
        self.store = SimpleNamespace(sql=Mock(side_effect=lambda query, **args: [self.rows[args['task']]]),
            plan=lambda identifier, owner: self.plans[identifier], require_plan_execution=Mock())
        self.resources = SimpleNamespace(targets=self.targets, _target_fingerprint=lambda target: target.pin,
            execution_runtime=Mock(return_value=runtime), _authorize=Mock(side_effect=lambda owner, ref: self.targets[ref]))
        self.metadata = {'id': 'checkpoint-artifact', 'jobId': self.contract['training']['taskId'],
            'size': len(self.raw_checkpoint), 'sha256': hashlib.sha256(self.raw_checkpoint).hexdigest(),
            'provenance': {key: self.contract['training'][key] for key in ('nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256')}}
        self.reader = Mock(side_effect=lambda *_: (deepcopy(self.metadata),
            {'sha256': hashlib.sha256(self.raw_checkpoint).hexdigest(), 'sizeBytes': len(self.raw_checkpoint)}))
        self.mapping = {digest(self.contract['comparisonManifest']['evaluator']): 'evaluation'}
        self.service = ResearchEvaluationService(self.store, self.auth, self.resources, self.mapping, checkpoint_reader=self.reader)

    async def test_repeat_original_reader_only_and_no_execution_claim(self):
        first = await self.service.verify('alice', self.contract)
        second = await self.service.verify('alice', self.contract)
        self.assertEqual(first, second)
        self.assertTrue(first['evaluatorCustodyVerified'])
        self.assertFalse(first['executionVerified'])
        self.assertFalse(first['scientificConclusionVerified'])
        self.assertEqual(self.reader.call_count, 4)
        self.assertEqual(self.evaluator_provider.read_completed_output.call_count, 2)
        self.training_provider.read_completed_output.assert_not_called()
        self.assertEqual(self.store.require_plan_execution.call_count, 8)
        self.assertEqual(first['evaluatorExecution'], self.contract['evaluatorExecution'])

    async def test_wrong_target_fingerprint_and_training_masquerade(self):
        self.targets['evaluation'].pin = 'drift'
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.targets['evaluation'].pin = 'evaluation-pin'
        self.targets['evaluation'].provider = self.training_provider
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.evaluator_provider.read_completed_output.assert_not_called()
        self.training_provider.read_completed_output.assert_not_called()

    async def test_unknown_false_stop_or_wrong_identity_never_read(self):
        for changes in ({'state': 'UNKNOWN'}, {'capacityHeld': True}, {'exitCode': False},
                        {'stopEvidence': {'allStopped': False}}, {'providerJobId': 'other'}, {'executionStatus': 'FAILED'}):
            lease = self.records['evaluate-lease'][0]
            original = deepcopy(lease)
            lease.update(changes)
            with self.assertRaises(ValueError):
                await self.service.verify('alice', self.contract)
            lease.clear(); lease.update(original)
        self.evaluator_provider.read_completed_output.assert_not_called()
        with self.assertRaises(ValueError):
            await self.service.verify('bob', self.contract)

    async def test_current_revocation_after_output_is_not_verified(self):
        def output_and_revoke(*_):
            self.store.require_plan_execution.side_effect = PermissionError('controlled revocation')
            return output(self.contract)
        self.evaluator_provider.read_completed_output.side_effect = output_and_revoke
        with self.assertRaises(PermissionError):
            await self.service.verify('alice', self.contract)
        self.assertEqual(self.evaluator_provider.read_completed_output.call_count, 1)

    async def test_checkpoint_bytes_and_provenance_checked_before_and_after(self):
        self.raw_checkpoint = b'tamper'
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.evaluator_provider.read_completed_output.assert_not_called()
        self.raw_checkpoint = b'synthetic checkpoint bytes'
        def output_and_tamper(*_):
            self.metadata['provenance']['nativeRunId'] = 'other'
            return output(self.contract)
        self.evaluator_provider.read_completed_output.side_effect = output_and_tamper
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.assertEqual(self.reader.call_count, 3)

    async def test_wrong_manifest_variant_effect_and_reused_checkpoint_denied(self):
        for field, replacement in (('manifestSha256', '0' * 64), ('variantSha256', '0' * 64)):
            guard = self.records['train-lease'][0]['executionGuard']
            original = guard[field]
            guard[field] = replacement
            with self.assertRaises(ValueError):
                await self.service.verify('alice', self.contract)
            guard[field] = original
        self.current_manifest['protocol']['seed'] = 2
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.current_manifest = deepcopy(self.contract['comparisonManifest'])
        self.current_variant = '0' * 64
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.current_variant = self.contract['training']['variantSha256']
        self.rows['evaluate-task']['effect_key'] = 'bounded-process-run-v1'
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.rows['evaluate-task']['effect_key'] = 'research-process-run-v1'
        self.metadata['provenance']['variantSha256'] = '0' * 64
        with self.assertRaises(ValueError):
            await self.service.verify('alice', self.contract)
        self.evaluator_provider.read_completed_output.assert_not_called()

    async def test_default_streaming_reader_and_no_large_artifact_materialization(self):
        self.store.artifact_identity = self.reader
        service = ResearchEvaluationService(self.store, self.auth, self.resources, self.mapping)
        await service.verify('alice', self.contract)
        self.assertEqual(self.reader.call_args.args[2], len(self.raw_checkpoint))
        self.contract['comparisonManifest']['artifactLimits']['checkpointBytes'] = 2**40
        self.contract['training']['checkpoint']['sizeBytes'] = 2 * 1024**3 + 1
        self.reader.reset_mock()
        with self.assertRaises(ValueError):
            await service.verify('alice', self.contract)
        self.reader.assert_not_called()

    def test_operator_registration_and_reader_required(self):
        with self.assertRaisesRegex(ValueError, 'RESEARCH_CHECKPOINT_READER_REQUIRED'):
            ResearchEvaluationService(self.store, self.auth, self.resources, self.mapping)
        with self.assertRaises(ValueError):
            ResearchEvaluationService(self.store, self.auth, self.resources, {'not-hash': 'evaluation'}, checkpoint_reader=self.reader)
        with self.assertRaises(ValueError):
            ResearchEvaluationService(self.store, self.auth, self.resources, {next(iter(self.mapping)): 'missing'}, checkpoint_reader=self.reader)


if __name__ == '__main__':
    unittest.main()

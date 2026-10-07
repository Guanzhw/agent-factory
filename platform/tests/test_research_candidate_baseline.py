"""Original installed verifier with synthetic custody; no real GPU or database."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from agent_factory.gpu_custody import GpuBinding, evidence_fingerprint
from agent_factory.research_manifest import manifest_fingerprint
import test_research_evaluation_service as fixtures

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts'))

spec = importlib.util.spec_from_file_location('candidate_baseline',
    Path(__file__).parents[2] / 'scripts/research_candidate_baseline.py')
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RetainedBaselineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = fixtures.ResearchEvaluationServiceTests()
        self.fixture.setUp()
        f = self.fixture
        variant = f.contract['comparisonManifest']['baselineSourceManifestSha256']
        f.contract['training']['variantSha256'] = variant
        f.current_variant = variant
        f.metadata['provenance']['variantSha256'] = variant
        for lease, _, task, ticket in f.records.values():
            lease['executionGuard']['variantSha256'] = variant
            task['terminal'] = True
            ticket.update(status='completed', persistedRunStatus='completed')
            lease.update(fingerprint='d' * 64, gpuBinding=GpuBinding('a' * 64, 'b' * 64).to_dict(),
                stopEvidence={'allStopped': True, 'kind': 'original-root-reaped-and-no-live-process-group-members'},
                processBinding={'taskId': task['id'], 'nativeRunId': task['run_id'],
                    'planId': task['plan_id'], 'bindingFingerprint': 'e' * 64})
            lease['gpuEvidence'] = {'schema': 1, 'bindingFingerprint': evidence_fingerprint(lease),
                'state': 'RELEASED', 'releaseProof': {'kind': 'original-process-stopped-and-device-released',
                    'processBindingFingerprint': 'e' * 64, 'deviceObservationSha256': 'f' * 64}}
        execution = f.contract['evaluatorExecution']
        self.receipt = {'progress': {**{key: execution[key] for key in
            ('taskId', 'planId', 'nativeRunId', 'leaseId', 'providerJobId')}, 'phase': 'COMPLETED',
            'cleanupConfirmed': True, 'cancelRequested': False},
            'lease': deepcopy(f.records['evaluate-lease'][0]),
            'imported': await f.service.verify('alice', f.contract)}
        f.evaluator_provider.read_completed_output.reset_mock()

    async def verify(self, **overrides):
        f = self.fixture
        args = {'service': f.service, 'owner': 'alice', 'contract': f.contract,
            'retained_receipt': self.receipt,
            'expected_manifest_sha256': manifest_fingerprint(f.contract['comparisonManifest'])}
        return await module.verify_retained_baseline(**{**args, **overrides})

    async def test_rereads_actual_evaluator_and_returns_detached_observation(self):
        observed = await self.verify()
        self.assertEqual(observed, self.receipt['imported']['observation'])
        observed['valBpb'] = 99
        self.assertEqual(self.receipt['imported']['observation']['valBpb'], 1.25)
        self.assertEqual(self.fixture.evaluator_provider.read_completed_output.call_count, 1)

    async def test_retained_metric_tamper_is_not_baseline_authentication(self):
        self.receipt['imported']['observation']['valBpb'] = .001
        with self.assertRaises(ValueError):
            await self.verify()

    async def test_manifest_and_original_progress_mismatch_reject_before_output(self):
        with self.assertRaises(ValueError):
            await self.verify(expected_manifest_sha256='0' * 64)
        self.receipt['progress']['taskId'] = 'different-task'
        with self.assertRaises(ValueError):
            await self.verify()
        self.fixture.evaluator_provider.read_completed_output.assert_not_called()

    async def test_native_or_gpu_unknown_reject_without_reconciliation(self):
        f = self.fixture
        for changes in ({'status': 'running'}, {'persistedRunStatus': None}):
            ticket = f.records['evaluate-lease'][3]
            old = deepcopy(ticket); ticket.update(changes)
            with self.assertRaises(ValueError):
                await self.verify()
            ticket.clear(); ticket.update(old)
        f.records['train-lease'][0]['gpuEvidence']['state'] = 'UNKNOWN'
        with self.assertRaises(ValueError):
            await self.verify()
        f.evaluator_provider.read_completed_output.assert_not_called()

    async def test_release_chain_tamper_rejects(self):
        self.fixture.records['train-lease'][0]['gpuEvidence']['releaseProof']['processBindingFingerprint'] = '0' * 64
        with self.assertRaises(ValueError):
            await self.verify()

    async def test_checkpoint_and_revocation_rechecked(self):
        f = self.fixture
        f.raw_checkpoint = b'tampered'
        with self.assertRaises(ValueError):
            await self.verify()
        f.raw_checkpoint = b'synthetic checkpoint bytes'
        f.store.require_plan_execution.side_effect = PermissionError('synthetic revoke')
        with self.assertRaises(PermissionError):
            await self.verify()

    async def test_post_output_native_change_rejects(self):
        f = self.fixture
        original = f.evaluator_provider.read_completed_output.side_effect
        def changed(*args):
            f.records['train-lease'][3]['status'] = 'running'
            return original(*args)
        f.evaluator_provider.read_completed_output.side_effect = changed
        with self.assertRaises(ValueError):
            await self.verify()

    async def test_synthetic_or_candidate_variant_cannot_be_retained_baseline(self):
        self.fixture.targets['training'].synthetic_fixture = True
        with self.assertRaises(ValueError):
            await self.verify()
        self.fixture.contract['training']['variantSha256'] = '0' * 64
        with self.assertRaises(ValueError):
            await self.verify()


class BaselineSnapshotTests(unittest.TestCase):
    def setUp(self):
        from test_research_evaluation import example_contract
        from agent_factory.research_profile import SOURCE_SHA256
        self.contract = example_contract()
        self.config = {'workspace': '/synthetic/original', 'upstreamRoot': '/synthetic/upstream', 'microbatch': 1}
        self.files = {f'/synthetic/upstream/{name}': b'synthetic source' for name in SOURCE_SHA256}
        self.journals = {}
        self.original_contract = {'boundsProfile': 'complete-venv-32768-v1'}
        self.add('environment/interpreter-contract.json', self.original_contract)
        for stage in ('training', 'evaluation'):
            execution = self.contract['training' if stage == 'training' else 'evaluatorExecution']
            program = '/synthetic/original/' + stage + '-program'
            cache = '/synthetic/original/' + stage + '-cache'
            receipt = {'progress': {'leaseId': execution['leaseId']}, 'imported': self.contract['training']}
            self.add(stage + '-receipt.json', receipt)
            runconfig = {key: {} for key in ('inputRootIdentity', 'tokenizer', 'tokenBytes', 'dataset')}
            runconfig.update(inputRoot='/synthetic/data', outputCheckpoint={'synthetic': True},
                comparisonManifest=self.contract['comparisonManifest'],
                evaluationContract=self.contract if stage == 'evaluation' else None)
            self.add(stage + '-program/run-config.json', runconfig)
            self.add(stage + '-program/program.seal.json', {'root_identity': {'inode': 2, 'device': 1},
                'comparison_manifest_sha256': manifest_fingerprint(self.contract['comparisonManifest']),
                'inputs': [{'kind': 'environment', 'label': str(i)} for i in range(3)]})
            self.journals[stage] = {'spec': {'working_directory': program,
                'working_directory_identity': [1, 2], 'interpreter_contract': json.dumps(self.original_contract),
                'environment': [[key, cache] for key in
                    ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR')]}}

    def add(self, relative, value):
        self.files['/synthetic/original/' + relative] = json.dumps(value).encode()

    def build(self):
        with patch('run_research_baseline.read_private', side_effect=lambda path, *_args, **_kwargs: self.files[str(path)]), \
             patch('run_research_baseline.identity', return_value={'device': 1, 'inode': 2}), \
             patch('agent_factory.research_profile.verify_upstream_source'), \
             patch('audit_released_research_custody.journal_read', side_effect=lambda path:
                   (self.journals['evaluation' if 'evaluation-custody' in str(path) else 'training'], None)):
            return module.build_baseline_snapshots(self.config)

    def test_original_inputs_not_candidate_inputs_are_reconstructed(self):
        value = self.build()
        self.assertEqual(value['contract'], self.contract)
        self.assertIsNone(value['runConfig']['evaluationContract'])
        for snapshot in value['snapshots'].values():
            self.assertEqual(snapshot['schema'], 1)
            self.assertEqual(snapshot['upstreamFiles'], snapshot['candidateFiles'])
            self.assertIsNone(snapshot['capturedInputs']['operatorInputs']['outputCheckpoint'])
            self.assertEqual(snapshot['programIdentity'], {'device': 1, 'inode': 2})

    def test_original_directory_or_contract_drift_fails(self):
        self.journals['training']['spec']['working_directory_identity'] = [1, 3]
        with self.assertRaises(ValueError):
            self.build()
        self.journals['training']['spec']['working_directory_identity'] = [1, 2]
        self.journals['evaluation']['spec']['interpreter_contract'] = '{}'
        with self.assertRaises(ValueError):
            self.build()

"""Synthetic source-only wiring: no baseline data, provider, controller or GPU run."""
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import autoresearch_scientific_preset as module
from agent_factory import research_training_adapter as adapter
from agent_factory.research_manifest import manifest_fingerprint
from test_research_manifest import example_manifest
from test_research_training_adapter import synthetic_files


class ScientificPresetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.files = synthetic_files()
        self.manifest = example_manifest()
        self.observation = {'schema': 1, 'status': 'completed',
            'comparisonIdentitySha256': manifest_fingerprint(self.manifest),
            'variantSha256': self.manifest['baselineSourceManifestSha256'], 'valBpb': 1.5}
        self.config = module.OperatorScientificConfig('synthetic-project', 'Synthetic project', 'alice', 'Research',
            self.manifest, {'maxExperiments': 1}, Mock(return_value=self.files), Mock(return_value=self.observation))
        fake_source = {'commit': 'synthetic-only', 'sourceSha256': {}}
        for target in (module, adapter):
            p = patch.object(target, 'verify_upstream_source', return_value=fake_source)
            p.start(); self.addCleanup(p.stop)

    def preset(self, **kwargs):
        return module.make_preset(self.config, runtime_factory=Mock(), **kwargs)

    def candidate(self, preset):
        train = self.files['train.py'].decode().replace('EMBEDDING_LR = 0.5', 'EMBEDDING_LR = 0.25')
        return {'hypothesis': 'Synthetic only', 'trainPy': train, 'validated': preset.candidate_validator(train)}

    def result(self):
        return {'cleanupConfirmed': True, 'independentResult': True, 'scientificConclusionVerified': False,
            'originalReferences': {**{phase: {key: phase + '-' + key for key in
                ('taskId', 'nativeRunId', 'planId', 'leaseId', 'providerJobId')} for phase in ('training', 'evaluation')},
                'checkpoint': {'artifactId': 'original-checkpoint', 'sha256': 'a' * 64}}}

    async def test_missing_subordinate_binding_unavailable_and_never_executes(self):
        preset = self.preset()
        self.assertTrue(preset.blockers)
        self.assertTrue(preset.external_session)
        with self.assertRaises(ValueError): await preset.experiment(None, self.candidate(preset), 'call')

    def test_real_eleven_literal_validator_context_and_fresh_baseline(self):
        preset = self.preset()
        result = preset.context_reader()
        self.assertEqual(result['programMd'], self.files['program.md'].decode())
        self.assertEqual(result['baselineObservation'], self.observation)
        valid = self.candidate(preset)['validated']
        self.assertEqual(len(valid['adaptation']['editableParameters']), 11)
        self.assertFalse(valid['executionVerified'])
        for train in (self.files['train.py'].decode().replace('DEPTH = 8', 'DEPTH = 9'),
                      self.files['train.py'].decode().replace('EMBEDDING_LR = 0.5', 'EMBEDDING_LR = True'),
                      self.files['train.py'].decode() + '\nimport arbitrary\n'):
            with self.assertRaises(ValueError): preset.candidate_validator(train)
        self.config.baseline_reader.return_value = {**self.observation, 'comparisonIdentitySha256': 'f'*64}
        with self.assertRaises(ValueError): preset.context_reader()

    async def test_subordinate_guard_and_custody_verifier_required_original_references(self):
        executor, verifier = AsyncMock(return_value={'untrusted': 'receipt-reference'}), AsyncMock(return_value=self.result())
        preset = self.preset(subordinate_executor=executor, result_verifier=verifier)
        current = Mock(return_value=preset)
        ctx = SimpleNamespace(store=SimpleNamespace(autoresearch=SimpleNamespace(current=current)))
        candidate = self.candidate(preset)
        value = await preset.experiment(ctx, candidate, 'original-call')
        executor.assert_awaited_once(); verifier.assert_awaited_once_with(ctx, {'untrusted': 'receipt-reference'})
        self.assertEqual(current.call_count, 3)
        self.assertEqual(value, self.result()); self.assertIsNot(value, verifier.return_value)
        executor.await_args.kwargs['parent_guard']()
        current.return_value = replace(preset, owner_id='bob')
        with self.assertRaises(ValueError): executor.await_args.kwargs['parent_guard']()

    async def test_revocation_unknown_and_forged_result_never_replay_or_promote(self):
        executor, verifier = AsyncMock(), AsyncMock(return_value={'cleanupConfirmed': True, 'independentResult': True})
        preset = self.preset(subordinate_executor=executor, result_verifier=verifier)
        current = Mock(return_value=preset)
        ctx = SimpleNamespace(store=SimpleNamespace(autoresearch=SimpleNamespace(current=current)))
        candidate = self.candidate(preset)
        unknown = ValueError('ORIGINAL_CUSTODY_UNKNOWN'); executor.side_effect = unknown
        with self.assertRaises(ValueError) as caught: await preset.experiment(ctx, candidate, 'call')
        self.assertIs(caught.exception, unknown); executor.assert_awaited_once(); verifier.assert_not_awaited()
        executor.reset_mock(); executor.side_effect = None
        with self.assertRaises(ValueError): await preset.experiment(ctx, candidate, 'different-call')
        executor.assert_awaited_once(); verifier.assert_awaited_once()
        executor.reset_mock(); current.side_effect = PermissionError('synthetic revoked')
        with self.assertRaises(PermissionError): await preset.experiment(ctx, candidate, 'denied-call')
        executor.assert_not_awaited()

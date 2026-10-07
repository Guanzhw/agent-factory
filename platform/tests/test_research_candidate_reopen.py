"""Real reconstructed provider fingerprints, mocked source/DB; no GPU dispatch."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_research_candidate_assembly as fixture  # pyright: ignore[reportMissingImports]
import test_research_evaluation as evaluation_fixture  # pyright: ignore[reportMissingImports]
from agent_factory.research_device_observer import NvidiaSmiObserver
from agent_factory.resources import PersistentResourceService

_spec = importlib.util.spec_from_file_location('candidate_reopen_under_test',
    Path(__file__).resolve().parents[2] / 'scripts/research_candidate_reopen.py')
assert _spec is not None and _spec.loader is not None
reopen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reopen)


@unittest.skipUnless(sys.platform == 'linux', 'Linux private provider construction')
class CandidateReopenTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.CandidateAssemblyTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.config = {'limits': vars(self.case.limits), 'receiverNamespaceSha256': 'a' * 64,
            'deviceUuid': 'GPU-12345678', 'nvidiaSmi': {'executable': '/usr/bin/nvidia-smi', 'sha256': 'e' * 64}}
        import hashlib
        from agent_factory.gpu_custody import GpuBinding
        from agent_factory.research_manifest import manifest_fingerprint
        self.case.binding = GpuBinding('a' * 64, hashlib.sha256(b'GPU-12345678').hexdigest())
        self.case.manifest['device']['identitySha256'] = self.case.binding.identity_key
        self.case.captured['manifestSha256'] = manifest_fingerprint(self.case.manifest)
        self.addCleanup(patch.stopall)
        patch.object(fixture, 'DeviceObserver', side_effect=lambda: NvidiaSmiObserver(
            Path('/usr/bin/nvidia-smi'), 'e' * 64, 'GPU-12345678', self.case.binding, 'task-local-real-observer-v1')).start()

    def application(self, **kw):
        original = fixture.assembly.research_application
        with patch.object(fixture.assembly, 'research_application', wraps=original) as called:
            result = self.case.application(**kw)
        args = called.call_args.kwargs
        snapshot = reopen.make_snapshot(stage='evaluation' if args['training'] else 'training',
            captured_inputs=args['captured_inputs'], environment_pins=args['environment_pins'],
            launch_spec=args['launch_spec'], program_identity=args['program_identity'],
            cache_root=args['cache_root'], cache_identity=args['cache_identity'], custody_root=args['custody_root'],
            upstream_files={'train.py': b'synthetic original'}, candidate_files={'train.py': b'synthetic candidate'},
            training=args['training'], microbatch=8)
        state = result['state']
        state['resources'] = state['store'].research_runtime.resources
        return result, snapshot

    def test_training_and_evaluation_reconstruct_exact_target_and_policy_fingerprints(self):
        training, snapshot = self.application()
        restored = reopen.reconstruct_research_target(training['state'], self.config, snapshot)
        fingerprint = PersistentResourceService._target_fingerprint
        self.assertEqual(fingerprint(restored['target']), fingerprint(training['target']))
        self.assertEqual(restored['driver'].configuration_fingerprint,
                         training['target'].provider._program_verifier.configuration_fingerprint)
        with self.assertRaisesRegex(ValueError, 'RESEARCH_REOPEN_DISPATCH_FORBIDDEN'):
            restored['driver']._guard()
        record = evaluation_fixture.example_contract()['training']
        record['variantSha256'] = self.case.candidate_variant
        evaluation, snapshot = self.application(previous=training, training=record, training_store=training['checkpoints'])
        restored = reopen.reconstruct_research_target(evaluation['state'], self.config, snapshot)
        self.assertEqual(fingerprint(restored['target']), fingerprint(evaluation['target']))
        self.assertEqual(restored['driver']._evaluation.configuration_fingerprint,
                         evaluation['target'].provider._program_verifier._evaluation.configuration_fingerprint)

    def test_snapshot_roundtrips_json_and_is_detached(self):
        import json
        training, snapshot = self.application()
        copied = json.loads(json.dumps(snapshot))
        restored = reopen.reconstruct_research_target(training['state'], self.config, copied)
        self.assertEqual(restored['reference'], 'training')
        snapshot['capturedInputs']['manifestSha256'] = '0' * 64
        self.assertNotEqual(snapshot['capturedInputs']['manifestSha256'], self.case.captured['manifestSha256'])

    def test_missing_original_root_rejected_without_creation(self):
        training, snapshot = self.application()
        missing = Path(snapshot['custodyRoot']) / 'missing'
        snapshot['custodyRoot'] = str(missing)
        with self.assertRaisesRegex(ValueError, 'RESEARCH_CANDIDATE_REOPEN_INVALID'):
            reopen.reconstruct_research_target(training['state'], self.config, snapshot)
        self.assertFalse(missing.exists())

    def test_preparation_reconstructs_original_driver_and_provider(self):
        from agent_factory.process_enforcement import ProcessSpec, ProcessLimits
        from agent_factory.research_preparation_driver import PreparationDriver
        from agent_factory.research_preparation_provider import PreparationProvider
        import test_research_preparation_driver as prep_fixture  # pyright: ignore[reportMissingImports]
        from unittest.mock import Mock
        training, _ = self.application()
        root = self.case.driver_fixture.root / 'prep-original'
        root.mkdir(mode=0o700)
        custody = self.case.driver_fixture.root / 'prep-custody'
        custody.mkdir(mode=0o700)
        identity = {'device': root.stat().st_dev, 'inode': root.stat().st_ino}
        executable = str(self.case.interpreter.target)
        snapshot = reopen.make_preparation_snapshot(program_root=root, program_identity=identity,
            custody_root=custody, executable=executable, executable_sha256=self.case.interpreter.sha,
            tokenizer_json=prep_fixture.tokenizer(), preparation_manifest_sha256='d' * 64)
        original = PreparationDriver(root=root, root_identity=identity, tokenizer_json=prep_fixture.tokenizer(),
            reserve=Mock(), manifest_sha256='d' * 64)
        spec = ProcessSpec(executable, self.case.interpreter.sha,
            ('-I', '-B', str(root / 'prepare.py'), str(root / 'run-config.json')))
        provider = PreparationProvider(training['state']['store'], custody, spec,
            ProcessLimits(file_size_bytes=65536, wall_seconds=5), driver=original)
        restored = reopen.reconstruct_preparation_target(training['state'], snapshot)
        self.assertEqual(restored['driver'].configuration_fingerprint, original.configuration_fingerprint)
        self.assertEqual(restored['target'].provider.configuration_fingerprint, provider.configuration_fingerprint)
        self.assertEqual(restored['reference'], 'preparation')
        self.assertNotIn('preflightSeconds', snapshot)
        self.assertEqual(set(snapshot), {'schema', 'stage', 'programRoot', 'programIdentity', 'custodyRoot',
            'executable', 'executableSha256', 'tokenizerHex', 'preparationManifestSha256'})
        arguments = dict(program_root=root, program_identity=identity, custody_root=custody,
            executable=executable, executable_sha256=self.case.interpreter.sha,
            tokenizer_json=prep_fixture.tokenizer(), preparation_manifest_sha256='d' * 64)
        self.assertEqual(reopen.make_preparation_snapshot(**arguments, preflight_seconds=0), snapshot)
        for padding in (7, 30):
            with self.subTest(padding=padding):
                padded_snapshot = reopen.make_preparation_snapshot(**arguments, preflight_seconds=padding)
                self.assertEqual(padded_snapshot, {**snapshot, 'preflightSeconds': padding})
                padded_provider = PreparationProvider(training['state']['store'], custody, spec,
                    ProcessLimits(file_size_bytes=65536, wall_seconds=5), driver=original,
                    preflight_seconds=padding)
                padded = reopen.reconstruct_preparation_target(training['state'], padded_snapshot)
                self.assertEqual(padded['target'].provider.configuration_fingerprint,
                                 padded_provider.configuration_fingerprint)
                self.assertNotEqual(padded['target'].provider.configuration_fingerprint,
                                    provider.configuration_fingerprint)
                self.assertEqual(padded['target'].max_seconds, 5 + padding)
                self.assertEqual(padded['target'].provider.limits.wall_seconds, 5)
                self.assertEqual(padded['driver'].configuration_fingerprint, original.configuration_fingerprint)
        for invalid in (True, False, -1, 31, 1.5, '7', None):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'RESEARCH_CANDIDATE_REOPEN_INVALID'):
                    reopen.make_preparation_snapshot(**arguments, preflight_seconds=invalid)
                with self.assertRaisesRegex(ValueError, 'RESEARCH_CANDIDATE_REOPEN_INVALID'):
                    reopen.reconstruct_preparation_target(training['state'], {**snapshot, 'preflightSeconds': invalid})


    def test_invalid_stage_or_manifest_rejected(self):
        training, snapshot = self.application()
        for change in ({'stage': 'preparation'}, {'schema': 2}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                reopen.reconstruct_research_target(training['state'], self.config, {**snapshot, **change})
        snapshot['capturedInputs']['manifestSha256'] = '0' * 64
        with self.assertRaises(ValueError):
            reopen.reconstruct_research_target(training['state'], self.config, snapshot)


if __name__ == '__main__':
    unittest.main()

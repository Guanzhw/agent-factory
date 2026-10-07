"""Real constructor interop with synthetic sources; no PG, GPU, or subprocess."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
import sys
import unittest
from unittest.mock import Mock, patch

import importlib.util

_spec = importlib.util.spec_from_file_location('candidate_assembly_under_test',
    Path(__file__).resolve().parents[2] / 'scripts/research_candidate_assembly.py')
assert _spec is not None and _spec.loader is not None
assembly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assembly)
from agent_factory.gpu_custody import GpuBinding
from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.resources import PersistentResourceService, RemoteTarget
from agent_factory.store import digest
import test_research_interpreter as interpreter_fixture  # pyright: ignore[reportMissingImports]
import test_research_local_driver as driver_fixture  # pyright: ignore[reportMissingImports]
import test_research_evaluation as evaluation_fixture  # pyright: ignore[reportMissingImports]


class DeviceObserver:
    configuration_fingerprint = 'd' * 64

    def __call__(self, request):
        raise AssertionError('Device must not be probed while constructing applications')


@unittest.skipUnless(sys.platform == 'linux', 'Linux private provider construction')
class CandidateAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.driver_fixture = driver_fixture.LocalDriverTests()
        self.driver_fixture.setUp()
        self.addCleanup(self.driver_fixture.doCleanups)
        self.interpreter = interpreter_fixture.InterpreterTests()
        self.interpreter.setUp()
        self.addCleanup(self.interpreter.doCleanups)
        fixture = self.driver_fixture
        fixture.bundle['generatedFiles']['train_candidate.py'] = b'# distinct synthetic candidate\n'
        fixture.bundle['receipt']['generatedSha256']['train_candidate.py'] = hashlib.sha256(fixture.bundle['generatedFiles']['train_candidate.py']).hexdigest()
        patch.object(assembly, 'build_training_bundle', return_value=fixture.bundle).start()
        self.candidate_variant = assembly.derive_local_identities({}, {})['identities']['candidate']['sha256']
        self.binding = GpuBinding('a' * 64, 'b' * 64)
        self.limits = ResearchProcessLimits()
        self.manifest = deepcopy(fixture.manifest)
        self.manifest['protocol']['totalWallSeconds'] = 900
        self.manifest['device']['identitySha256'] = self.binding.identity_key
        self.preparation = SimpleNamespace(input_pin=Mock(return_value=deepcopy(fixture.config['tokenBytes'])))
        self.captured = {'comparisonManifest': self.manifest, 'manifestSha256': manifest_fingerprint(self.manifest),
            'operatorInputs': deepcopy(fixture.config)}
        self.created = []

        def store(_url, settings):
            return SimpleNamespace(settings=settings, engine=SimpleNamespace(dispose=Mock()))

        def create_app(settings):
            state_store = SimpleNamespace(settings=settings, storage=SimpleNamespace(objects=fixture.output),
                artifact=Mock(), plan=Mock())
            auth = SimpleNamespace(require=Mock())
            resources = PersistentResourceService(state_store, auth, settings.remote_targets)
            state_store.research_runtime = SimpleNamespace(resources=resources)
            state = {'store': state_store, 'auth': auth}
            self.created.append(state)
            return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(factory=state)))

        self.addCleanup(patch.stopall)
        patch.object(assembly, 'Store', side_effect=store).start()
        patch.object(assembly, 'create_app', side_effect=create_app).start()
        self.prior = RemoteTarget('Controlled preparation stand-in', 'compute', frozenset({'alice'}),
            provider=cast(Any, SimpleNamespace()), synthetic_fixture=True)
        self.contract = self.interpreter.capture()

    def application(self, *, previous=None, training=None, training_store=None):
        fixture = self.driver_fixture
        label = 'evaluation' if training is not None else 'training'
        program = fixture.root / (label + '-program'); program.mkdir(mode=0o700)
        cache = fixture.root / (label + '-cache'); cache.mkdir(mode=0o700)
        custody = fixture.root / (label + '-custody'); custody.mkdir(mode=0o700)
        environment = {key: str(cache) for key in ('HOME', 'TORCHINDUCTOR_CACHE_DIR',
            'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR')}
        environment.update(PYTHONPYCACHEPREFIX=str(program), PYTHONNOUSERSITE='1',
            HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        entry = 'evaluate.py' if training is not None else 'train_candidate.py'
        spec = UvResearchProcessSpec(str(self.interpreter.link), self.interpreter.sha,
            ('-B', str(program / entry), '--config', str(program / 'run-config.json')),
            str(program), tuple(sorted(environment.items())),
            (program.stat().st_dev, program.stat().st_ino), self.contract)
        prior_targets = previous['settings'].remote_targets if previous else {'preparation': self.prior}
        return assembly.research_application(db_url='postgresql+psycopg://invalid/no-network',
            workspace=fixture.root / 'workspace', upstream_files={}, candidate_files={}, captured_inputs=self.captured,
            environment_pins=tuple(fixture.environment), launch_spec=spec,
            program_identity=driver_fixture.identity(program), cache_root=cache,
            cache_identity=driver_fixture.identity(cache), custody_root=custody,
            limits=self.limits, gpu_binding=self.binding, device_observer=DeviceObserver(),
            preparation=self.preparation, preparation_task_id='prep', preparation_artifact_id='prep-artifact',
            prior_targets=prior_targets,
            prior_adapters=previous['settings'].runtime_adapters if previous else [],
            prior_pricing=previous['settings'].usage_pricing if previous else (),
            training=training, training_store=training_store, microbatch=8)

    def test_training_then_evaluation_real_constructors_preserve_custody_and_registry(self):
        training = self.application()
        train_record = evaluation_fixture.example_contract()['training']
        train_record['variantSha256'] = self.candidate_variant
        evaluation = self.application(previous=training, training=train_record, training_store=training['checkpoints'])
        self.assertEqual(training['target'].provider._program_verifier._entrypoint, 'train_candidate.py')
        self.assertEqual(evaluation['target'].provider._program_verifier._entrypoint, 'evaluate.py')
        self.assertTrue(all(row.adapter_id.endswith('-candidate-training')
                            for row in training['settings'].runtime_adapters))
        for item, target in ((training, 'training'), (evaluation, 'evaluation')):
            driver = item['target'].provider._program_verifier
            self.assertEqual(driver._variant, self.candidate_variant)
            self.assertEqual(driver._manifest, self.manifest)
            for registration in item['settings'].runtime_adapters[-4:]:
                config = {'targetRef': target, 'comparisonManifestSha256': manifest_fingerprint(self.manifest),
                          'variantSha256': self.candidate_variant}
                registration.validator(config)
                with self.assertRaises(ValueError):
                    registration.validator({**config, 'variantSha256': self.manifest['baselineSourceManifestSha256']})
        for item in (training, evaluation):
            self.assertEqual(item['settings'].runtime_tool_contract, 'research-bootstrap-v1')
            self.assertEqual(item['settings'].policy_revision, 'task-research-bootstrap-v1')
            self.assertEqual(item['settings'].material_policy_revision, 'task-research-bootstrap-v1')
            self.assertEqual(item['settings'].temporary_policy, 'admin-review')
            self.assertEqual(item['settings'].max_workers, 1)
            self.assertIs(item['checkpoints'].store, item['state']['store'])
            self.assertFalse(item['syntheticProvider'])  # real adapter configured, NOT execution proof
        self.assertIs(evaluation['settings'].remote_targets['training'], training['target'])
        self.assertIs(evaluation['settings'].remote_targets['preparation'], self.prior)
        self.assertEqual(training['target'].capacity_pool, evaluation['target'].capacity_pool)
        self.assertEqual(training['target'].provider.limits, evaluation['target'].provider.limits)
        prior = training['settings'].runtime_adapters
        current = evaluation['settings'].runtime_adapters
        self.assertEqual(current[:len(prior)], prior)
        self.assertTrue(all(row.adapter_id.endswith('-candidate-evaluation') for row in current[len(prior):]))
        pricing = evaluation['settings'].usage_pricing
        self.assertEqual(pricing[:len(training['settings'].usage_pricing)], training['settings'].usage_pricing)
        self.assertTrue(pricing[-1].adapter_id.endswith('-candidate-evaluation'))
        service = evaluation['state']['research_evaluation']
        self.assertIs(service.store, evaluation['state']['store'])
        self.assertIs(service._reader.__self__, evaluation['checkpoints'])
        self.assertEqual(service._targets[digest(self.manifest['evaluator'])][0], 'evaluation')
        self.assertIs(evaluation['pending']['state'], evaluation['state'])

    def test_preparation_binding_is_retained_and_fresh_guard_rejects_drift(self):
        training = self.application()
        driver = training['target'].provider._program_verifier
        config = json.loads(driver._operator_json)
        self.assertEqual(config['tokenBytes'], self.preparation.input_pin.return_value)
        driver._guard()
        changed = deepcopy(self.preparation.input_pin.return_value)
        changed['binding']['providerJobId'] = 'replaced-preparation'
        self.preparation.input_pin.return_value = changed
        with self.assertRaisesRegex(ValueError, '^RESEARCH_CANDIDATE_ASSEMBLY_INVALID$'):
            driver._guard()
        training['state']['store'].artifact.assert_not_called()

    def test_evaluator_resolver_reads_original_checkpoint_store_and_binds_new_execution(self):
        training = self.application()
        record = evaluation_fixture.example_contract()['training']
        record['variantSha256'] = self.candidate_variant
        evaluation = self.application(previous=training, training=record, training_store=training['checkpoints'])
        actual = {key: record['checkpoint'][key] for key in ('sha256', 'sizeBytes')}
        binding = evaluation_fixture.example_contract()['evaluatorExecution']
        original = training['state']['store']
        reference = {'storageObjectId': 'original-object', 'basename': 'checkpoint.safetensors',
            'rootIdentity': {'device': 1, 'inode': 2}, 'binding': {'synthetic': 'original binding'}}
        original.artifact.return_value = ({}, json.dumps(reference).encode())
        resolver = evaluation['target'].provider._program_verifier._evaluation
        with patch.object(training['checkpoints'], 'identity', return_value=({}, actual)) as identity:
            value = resolver({}, binding)
        identity.assert_called_once_with(record['taskId'], record['checkpoint']['artifactId'],
                                        self.manifest['artifactLimits']['checkpointBytes'])
        self.assertEqual(value['evaluationContract']['training'], record)
        self.assertEqual(value['evaluationContract']['evaluatorExecution'], binding)
        self.assertEqual(value['checkpoint']['root'], str(original.storage.objects / 'original-object'))
        self.assertEqual(value['checkpoint']['binding'], reference['binding'])
        evaluation['state']['store'].artifact.assert_not_called()
        self.assertEqual(evaluation['pending']['evaluationContract'], value['evaluationContract'])

    def test_noop_is_rejected_before_store_creation(self):
        fixture = self.driver_fixture
        fixture.bundle['generatedFiles']['train_candidate.py'] = fixture.bundle['generatedFiles']['train_baseline.py']
        with patch.object(assembly, 'Store') as store:
            with self.assertRaisesRegex(ValueError, 'RESEARCH_CANDIDATE_ASSEMBLY_INVALID'):
                self.application()
            store.assert_not_called()

    def test_changed_baseline_identity_is_rejected_before_store_creation(self):
        self.manifest['baselineSourceManifestSha256'] = '0' * 64
        self.captured['manifestSha256'] = manifest_fingerprint(self.manifest)
        with patch.object(assembly, 'Store') as store:
            with self.assertRaisesRegex(ValueError, 'RESEARCH_CANDIDATE_ASSEMBLY_INVALID'):
                self.application()
            store.assert_not_called()

    def test_wrong_evaluation_variant_is_rejected_before_store_creation(self):
        record = evaluation_fixture.example_contract()['training']
        record['variantSha256'] = '0' * 64
        with patch.object(assembly, 'Store') as store:
            with self.assertRaisesRegex(ValueError, 'RESEARCH_CANDIDATE_ASSEMBLY_INVALID'):
                self.application(training=record, training_store=Mock())
            store.assert_not_called()


if __name__ == '__main__':
    unittest.main()

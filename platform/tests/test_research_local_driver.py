"""Offline driver composition. Source adaptation/attestation are explicit mocks.

No generated source is imported, no training/checkpoint deserialization occurs,
and no hardware/environment-verification result is claimed by these fixtures.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import unittest
from unittest.mock import patch

from agent_factory import research_local_driver as subject
from agent_factory.process_enforcement import ResearchProcessSpec
from agent_factory.research_manifest import SOURCE_SHA256, manifest_fingerprint
from agent_factory.research_staging import InputPin, RootIdentity, pin_bytes, SEAL
from agent_factory.store import digest
from test_research_manifest import example_manifest  # pyright: ignore[reportMissingImports]


class FixtureObserver:
    configuration_fingerprint = '9' * 64
    def __call__(self, request):
        return {'schema': 1, 'status': 'VERIFIED', 'requestSha256': digest(request),
                'observationSha256': digest({'syntheticObserverOnly': request})}


class FixtureReservation:
    configuration_fingerprint = '8' * 64
    def __init__(self, root):
        self.root, self.bindings = root, []
    def __call__(self, binding):
        self.bindings.append(deepcopy(binding))
        return {'root': str(self.root), 'basename': 'checkpoint.safetensors',
                'rootIdentity': identity(self.root)}


def identity(root):
    info = root.stat()
    return {'device': info.st_dev, 'inode': info.st_ino}


@unittest.skipUnless(os.name == 'posix', 'Private POSIX operator staging')
class LocalDriverTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.program, self.inputs, self.output, self.cache = [self.root / name for name in ('program', 'inputs', 'output', 'cache')]
        for path in (self.program, self.inputs, self.output, self.cache):
            path.mkdir(mode=0o700)
        lock_hash = hashlib.sha256(b'fixture lock').hexdigest()
        self.addCleanup(patch.stopall)
        patch.dict(SOURCE_SHA256, {'uv.lock': lock_hash}).start()
        self.manifest = example_manifest()
        self.manifest['protocol']['seed'] = 42
        self.environment = []
        for label, key, raw in (
            ('environment-lockfile', 'lockfileSha256', b'fixture lock'),
            ('environment-inventory', 'installedInventory', b'fixture inventory'),
            ('environment-kernel', 'runtimeKernel', b'fixture kernel')):
            row = self.file(label, raw)
            self.environment.append(InputPin(label, 'environment', str(self.inputs),
                RootIdentity(**identity(self.inputs)), pin_bytes(label, raw)))
            self.manifest['environment'][key] = row['sha256'] if key == 'lockfileSha256' else self.artifact(row)
        tokenizer = self.file('tokenizer.json', b'{"synthetic":true}')
        token_bytes = self.file('token-bytes.safetensors', b'synthetic bytes; no tensors imported')
        self.manifest['tokenizer'] = {'tokenizer': self.artifact(tokenizer), 'tokenBytes': self.artifact(token_bytes)}
        shards = [{'id': name, **self.file(name + '.bin', name.encode())} for name in ('train', 'validation')]
        self.manifest['dataset']['shards'] = [{'id': row['id'], **self.artifact(row)} for row in shards]
        self.manifest['dataset']['validationShardIds'] = ['validation']
        self.plan = {'id': 'plan-original', 'ownerId': 'alice', 'fingerprint': 'f' * 64}
        self.record = {'binding': {'id': 'lease-original', 'ownerId': 'alice', 'localTaskId': 'task-original',
            'nativeRunId': 'native-original', 'planId': self.plan['id'], 'planHash': digest(self.plan),
            'executionGuard': {'manifestSha256': manifest_fingerprint(self.manifest), 'variantSha256': '1' * 64}},
            'processPin': {'id': 'provider-original'}}
        prep = {'ownerId': 'alice', 'taskId': 'prep', 'nativeRunId': 'prep-native', 'planId': 'prep-plan',
            'planFingerprint': 'a' * 64, 'leaseId': 'prep-lease', 'providerJobId': 'prep-job',
            'variantSha256': '1' * 64, 'manifestSha256': manifest_fingerprint(self.manifest)}
        self.config = {'inputRoot': str(self.inputs), 'inputRootIdentity': identity(self.inputs),
            'tokenizer': tokenizer, 'tokenBytes': {**token_bytes, 'root': str(self.inputs),
                'rootIdentity': identity(self.inputs), 'binding': prep},
            'dataset': {'shards': shards, 'validationShardIds': ['validation']}, 'outputCheckpoint': None}
        generated = {name: b'# synthetic source; never imported\n' for name in
            ('trusted_architecture.py', 'trusted_data.py', 'train_baseline.py', 'train_candidate.py', 'evaluate.py')}
        self.bundle = {'generatedFiles': generated, 'receipt': {
            'candidateSource': {'baselineManifestSha256': '1' * 64, 'candidateManifestSha256': '2' * 64},
            'generatedSha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in generated.items()},
            'approvedMicrobatch': 8, 'evidenceKind': 'synthetic-adapter-test-double'}}
        patch.object(subject, 'build_training_bundle', return_value=self.bundle).start()
        derived = subject.derive_local_identities({}, {})['identities']
        self.variant = derived['baseline']['sha256']
        self.manifest['baselineSourceManifestSha256'] = self.variant
        self.manifest['evaluator']['code'] = self.artifact(derived['evaluatorCode'])
        self.manifest['evaluator']['configuration'] = self.artifact(derived['evaluatorConfiguration'])
        self.record['binding']['executionGuard'] = {'manifestSha256': manifest_fingerprint(self.manifest),
                                                    'variantSha256': self.variant}
        self.reservation = FixtureReservation(self.output)
        self.guards = []

    @staticmethod
    def artifact(row):
        return {key: row[key] for key in ('sha256', 'sizeBytes')}

    def file(self, name, raw):
        path = self.inputs / name
        path.write_bytes(raw)
        path.chmod(0o600)
        return {'basename': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}

    def driver(self, **changes):
        entrypoint = changes.get('entrypoint', 'train_baseline.py')
        environment = {key: str(self.cache) for key in
            ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR')}
        environment['PYTHONPYCACHEPREFIX'] = str(self.program)
        environment.update({key: '1' for key in
            ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE')})
        spec = ResearchProcessSpec(str(Path(sys.executable).resolve()), 'a' * 64,
            ('-B', str(self.program / entrypoint), '--config', str(self.program / 'run-config.json')),
            str(self.program), tuple(sorted(environment.items())),
            (self.program.stat().st_dev, self.program.stat().st_ino))
        arguments: dict[str, Any] = dict(entrypoint='train_baseline.py', comparison_manifest=self.manifest,
            variant_sha256=self.variant, program_root=self.program,
            program_root_identity=RootIdentity(**identity(self.program)), operator_config=self.config,
            environment_pins=tuple(self.environment), plan_reader=lambda identifier, owner: deepcopy(self.plan),
            before_effect=lambda: self.guards.append(True), reserve_output=self.reservation,
            environment_verifier=FixtureObserver(), launch_spec=spec, cache_root=self.cache,
            cache_root_identity=RootIdentity(**identity(self.cache)))
        arguments.update(changes)
        return subject.build_local_driver({}, {}, **arguments)

    def test_dynamic_ids_are_sealed_without_static_fingerprint_cycle(self):
        driver = self.driver()
        static = driver.configuration_fingerprint
        proof = driver(self.record)
        config = json.loads((self.program / 'run-config.json').read_bytes())
        self.assertEqual(config['binding']['providerJobId'], 'provider-original')
        self.assertEqual(config['binding']['planFingerprint'], self.plan['fingerprint'])
        self.assertNotEqual(config['binding']['planFingerprint'], self.record['binding']['planHash'])
        self.assertEqual(proof['sourceSha256'], static)
        self.assertNotEqual(proof['descriptorSha256'], static)
        self.assertEqual(set(proof), {'schema', 'descriptorSha256', 'sourceSha256', 'manifestSha256',
                                     'variantSha256', 'checkpoint', 'evaluationContractSha256'})
        self.assertIsNone(proof['checkpoint'])
        self.assertIsNone(proof['evaluationContractSha256'])
        self.assertEqual(driver(self.record), proof)
        self.assertGreaterEqual(len(self.guards), 4)
        changed = deepcopy(self.record)
        changed['processPin']['id'] = 'other-provider'
        with self.assertRaises(ValueError):
            driver(changed)
        self.assertEqual(json.loads((self.program / 'run-config.json').read_bytes()), config)

    def test_original_plan_digest_and_variant_guard_are_required(self):
        driver = self.driver()
        for field, value in (('planHash', '0' * 64), ('ownerId', 'bob')):
            record = deepcopy(self.record)
            record['binding'][field] = value
            with self.assertRaises(ValueError):
                driver(record)
        record = deepcopy(self.record)
        record['binding']['executionGuard']['variantSha256'] = '2' * 64
        with self.assertRaises(ValueError):
            driver(record)
        self.assertEqual(list(self.program.iterdir()), [])

    def test_runtime_source_drift_and_environment_missing_block(self):
        driver = self.driver()
        pins = subject._runtime_pins()
        with patch.object(subject, '_runtime_pins', return_value=(replace(pins[0], sha256='0' * 64), *pins[1:])):
            with self.assertRaises(ValueError):
                driver(self.record)
        with self.assertRaises(ValueError):
            self.driver(environment_verifier=None)
        observer = FixtureObserver()
        with patch.object(FixtureObserver, '__call__', return_value=True):
            with self.assertRaises(ValueError):
                self.driver(environment_verifier=observer)(self.record)
        self.assertFalse((self.program / SEAL).exists())

    def test_config_manifest_bytes_disagreement_cannot_be_sealed(self):
        config = deepcopy(self.config)
        config['dataset']['shards'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.driver(operator_config=config)(self.record)
        self.assertEqual(list(self.program.iterdir()), [])
        (self.inputs / 'train.bin').write_bytes(b'edited')
        with self.assertRaises(ValueError):
            self.driver()(self.record)
        self.assertFalse((self.program / SEAL).exists())

    def test_partial_unknown_never_adopted_or_reserves_new_output(self):
        (self.program / 'train_baseline.py').write_bytes(b'partial')
        with self.assertRaises(ValueError):
            self.driver()(self.record)
        self.assertEqual(self.reservation.bindings, [])

    def test_checkpoint_evaluation_crosslinks_original_training_and_new_eval(self):
        training = {'ownerId': 'alice', 'taskId': 'training-task', 'nativeRunId': 'training-native',
            'planId': 'training-plan', 'planFingerprint': 'd' * 64, 'leaseId': 'training-lease',
            'providerJobId': 'training-provider', 'variantSha256': self.variant}
        raw = b'synthetic checkpoint bytes'
        row = self.file('input-checkpoint.safetensors', raw)
        artifact = {'artifactId': 'original-checkpoint-artifact', **self.artifact(row)}
        def evaluation(record, binding):
            return {'checkpoint': {**row, 'root': str(self.inputs), 'rootIdentity': identity(self.inputs),
                'binding': {**training, 'manifestSha256': manifest_fingerprint(self.manifest)}},
                'evaluationContract': {'schema': 1, 'evidenceKind': 'offline_research_evaluation_contract',
                    'comparisonManifest': self.manifest, 'training': {**training, 'checkpoint': artifact},
                    'evaluatorExecution': {key: binding[key] for key in subject._EXECUTION}}}
        setattr(evaluation, 'configuration_fingerprint', '7' * 64)
        driver = self.driver(entrypoint='evaluate.py', reserve_output=None, evaluation_factory=evaluation)
        proof = driver(self.record)
        self.assertEqual(proof['checkpoint'], artifact)
        self.assertEqual(len(proof['evaluationContractSha256']), 64)
        seal = json.loads((self.program / SEAL).read_bytes())
        self.assertEqual(seal['checkpoint_artifact_id'], artifact['artifactId'])
        self.assertEqual(seal['evaluation_contract_sha256'], proof['evaluationContractSha256'])
        self.assertEqual(len(seal['environment_verification_sha256']), 64)
        self.assertIsNone(json.loads((self.program / 'run-config.json').read_bytes())['outputCheckpoint'])

    def test_derived_baseline_does_not_include_candidate_training_edits(self):
        first = subject.derive_local_identities({}, {})['identities']
        self.bundle['generatedFiles']['train_candidate.py'] = b'# another synthetic candidate'
        second = subject.derive_local_identities({}, {})['identities']
        self.assertEqual(first['baseline'], second['baseline'])
        self.assertEqual(first['evaluatorCode'], second['evaluatorCode'])
        self.assertNotEqual(first['candidate'], second['candidate'])
        self.assertNotEqual(first['baseline']['sha256'], '1' * 64)

    def test_unbound_evaluator_and_raw_upstream_baseline_rejected(self):
        changed = deepcopy(self.manifest)
        changed['baselineSourceManifestSha256'] = '1' * 64
        with self.assertRaises(ValueError):
            self.driver(comparison_manifest=changed)
        changed = deepcopy(self.manifest)
        changed['evaluator']['code']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.driver(comparison_manifest=changed)

    def test_actual_argv_working_directory_and_cache_contract_are_pinned(self):
        driver = self.driver()
        driver.validate_spec(driver._spec)
        for spec in (replace(driver._spec, argv=('-c', 'raise SystemExit')),
                     replace(driver._spec, working_directory=str(self.inputs)),
                     replace(driver._spec, environment=tuple((key, '/tmp' if key == 'TMPDIR' else value)
                                                            for key, value in driver._spec.environment))):
            with self.assertRaises(ValueError):
                driver.validate_spec(spec)
        self.cache.rename(self.root / 'old-cache')
        self.cache.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            driver(self.record)

    def test_bytecode_prefix_mandatory_sealed_and_separate_from_compiler_cache(self):
        driver = self.driver()
        self.assertEqual(dict(driver._spec.environment)['PYTHONPYCACHEPREFIX'], str(self.program))
        self.assertEqual(driver._spec.argv[0], '-B')
        for replacement in (None, str(self.cache), '/tmp'):
            environment = dict(driver._spec.environment)
            if replacement is None:
                environment.pop('PYTHONPYCACHEPREFIX')
            else:
                environment['PYTHONPYCACHEPREFIX'] = replacement
            spec = replace(driver._spec, environment=tuple(sorted(environment.items())))
            # Reject at construction, not merely by comparison with another spec.
            with self.assertRaises(ValueError):
                self.driver(launch_spec=spec)
        driver(self.record)
        self.assertTrue(all(path.is_file() for path in self.program.iterdir()))
        # A cache tree could hide stale compiled code; exact-root validation rejects it.
        (self.program / 'usr').mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            driver(self.record)

    def test_configuration_is_detached_and_actual_runtime_files_are_operator_independent(self):
        driver = self.driver()
        original = driver.configuration_fingerprint
        self.config['inputRoot'] = '/untrusted'
        self.bundle['generatedFiles']['train_baseline.py'] = b'arbitrary replacement'
        proof = driver(self.record)
        self.assertEqual(proof['sourceSha256'], original)
        self.assertEqual(len(subject._runtime_pins()), 15)
        self.assertTrue({'research_interpreter.py', 'process_enforcement_guardian.py'} <=
                        {pin.basename for pin in subject._runtime_pins()})
        self.assertTrue(all(asdict(pin)['sha256'] for pin in subject._runtime_pins()))


class BytecodePrefixRegressionTests(unittest.TestCase):
    def test_real_python_old_timestamp_cache_cannot_override_redirected_source(self):
        """Only our tiny stdlib fixture executes; no generated research source."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / 'owned_bytecode_fixture.py'
            script = root / 'read_owned_fixture.py'
            prefix = root / 'empty-sealed-prefix'
            prefix.mkdir(mode=0o700)
            old_source, new_source = b"value = 'old'\n", b"value = 'new'\n"
            self.assertEqual(len(old_source), len(new_source))
            module.write_bytes(old_source)
            stamp = module.stat()
            compiled_path = py_compile.compile(str(module), doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            assert isinstance(compiled_path, str)
            compiled = Path(compiled_path)
            original_bytecode = compiled.read_bytes()
            module.write_bytes(new_source)
            os.utime(module, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertEqual(module.stat().st_size, stamp.st_size)
            self.assertEqual(module.stat().st_mtime_ns, stamp.st_mtime_ns)
            script.write_text('import owned_bytecode_fixture\nprint(owned_bytecode_fixture.value)\n')
            # Never inherit provider credentials, import-path overrides, or active
            # environment settings into either controlled child. Windows alone
            # requires its non-secret OS directory for ordinary process startup.
            environment = {'PYTHONNOUSERSITE': '1'}
            if os.name == 'nt' and os.environ.get('SYSTEMROOT'):
                environment['SYSTEMROOT'] = os.environ['SYSTEMROOT']
            command = [sys.executable, '-B', '-S', str(script)]
            old = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                                 text=True, timeout=10, check=False)
            self.assertEqual(old.returncode, 0, 'Controlled old-cache probe failed')
            self.assertEqual(old.stdout.strip(), 'old')
            redirected = subprocess.run(command, cwd=root,
                env={**environment, 'PYTHONPYCACHEPREFIX': str(prefix)},
                capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(redirected.returncode, 0, 'Controlled redirected-cache probe failed')
            self.assertEqual(redirected.stdout.strip(), 'new')
            self.assertEqual(list(prefix.iterdir()), [])
            self.assertEqual(compiled.read_bytes(), original_bytecode)


if __name__ == '__main__':
    unittest.main()

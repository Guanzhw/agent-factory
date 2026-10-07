"""Trusted operator launch closure over the existing research process provider.

Static source/configuration identity excludes future journal IDs. A separate
sealed descriptor binds the actual original journal IDs at launch. No HTTP,
process launch, imports of generated code, ML installation or lifecycle lives here.
"""
from dataclasses import asdict
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import re
from typing import Any, cast

from .process_enforcement import ResearchProcessSpec, UvResearchProcessSpec
from .research_checkpoint import _flags, _root, _stamp, checkpoint_binding
from .research_evaluation import evaluation_contract_fingerprint
from .research_manifest import manifest_fingerprint, validate_manifest
from .research_staging import (
    FilePin, InputPin, ProgramDescriptor, RootIdentity, SEAL, pin_bytes,
    stage_own_bundle, verify_staged_program,
)
from .research_torch_runtime import validate_runtime_configuration
from .research_training_adapter import REVISION, build_training_bundle
from .store import digest

ERROR = 'RESEARCH_LOCAL_DRIVER_INVALID'


class ResearchDriverFailure(ValueError):
    """Fixed prelaunch phase only; never exception messages or input contents."""
    def __init__(self, phase):
        self.phase = phase
        super().__init__(ERROR)

_RUNTIME_FILES = ('research_torch_runtime.py', 'research_checkpoint.py',
    'research_manifest.py', 'research_evaluation.py', 'research_assessment.py',
    'research_profile.py', 'research_candidate.py', 'research_training_adapter.py',
    'research_staging.py', 'research_local_driver.py', 'process_enforcement.py',
    'process_enforcement_guardian.py', 'research_interpreter.py', 'store.py', '__init__.py')
_BASE_KEYS = {'inputRoot', 'inputRootIdentity', 'tokenizer', 'tokenBytes', 'dataset', 'outputCheckpoint'}
_EXECUTION = ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId')


def _require(value):
    if not value:
        raise ValueError(ERROR)


def _encoded(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    _require(len(raw) <= 1024**2)
    return raw


def _sync(function, *args) -> Any:
    value = function(*args)
    if inspect.iscoroutine(value):
        value.close()
    _require(not inspect.isawaitable(value) and value is not False)
    return value


def _runtime_pins():
    """Read only this actually installed package; no operator substitute paths."""
    nofollow, directory, nonblock = _flags()
    package = Path(__file__).absolute().parent
    _require('..' not in package.parts)
    fd = os.open(package.anchor, os.O_RDONLY | directory | nofollow)
    try:
        for part in package.parts[1:]:
            child = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        getuid = getattr(os, 'getuid', None)
        _require(callable(getuid))
        uid = getuid() if callable(getuid) else -1
        _require(info.st_uid == uid and not info.st_mode & 0o022)
        pins = []
        for name in _RUNTIME_FILES:
            source_fd = os.open(name, os.O_RDONLY | nofollow | nonblock, dir_fd=fd)
            try:
                source = os.fstat(source_fd)
                _require(stat.S_ISREG(source.st_mode) and source.st_uid == uid
                         and source.st_nlink == 1 and not source.st_mode & 0o022
                         and source.st_dev == info.st_dev and 0 < source.st_size <= 4 * 1024**2)
                hasher = hashlib.sha256()
                remaining = source.st_size
                while remaining:
                    block = os.read(source_fd, min(remaining, 1024**2))
                    _require(bool(block))
                    hasher.update(block)
                    remaining -= len(block)
                _require(os.read(source_fd, 1) == b'' and _stamp(os.fstat(source_fd)) == _stamp(source)
                         and _stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) == _stamp(source))
                pins.append(FilePin(name, hasher.hexdigest(), source.st_size))
            finally:
                os.close(source_fd)
        current = os.stat(package, follow_symlinks=False)
        _require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino))
        return tuple(pins)
    finally:
        os.close(fd)


def _derived_identities(bundle, runtime_pins):
    generated = bundle['generatedFiles']
    shared = {name: asdict(pin_bytes(name, generated[name]))
              for name in ('trusted_architecture.py', 'trusted_data.py')}
    runtime_files = [asdict(pin) for pin in runtime_pins]
    values = {}
    for key, name in (('baseline', 'train_baseline.py'), ('candidate', 'train_candidate.py'),
                      ('evaluatorCode', 'evaluate.py')):
        body = {'schema': 1, 'adaptationRevision': REVISION,
                'entrypoint': asdict(pin_bytes(name, generated[name])),
                'sharedGenerated': shared, 'trustedRuntimeFiles': runtime_files}
        raw = _encoded(body)
        values[key] = {'content': raw, 'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}
    raw = _encoded({'schema': 1, 'adaptationRevision': REVISION,
        'microbatch': bundle['receipt']['approvedMicrobatch'], 'seed': 42,
        'sequenceLength': 2048, 'evaluationBudgetTokens': 20971520,
        'metric': 'val_bpb', 'initialCheckpoint': None})
    values['evaluatorConfiguration'] = {'content': raw, 'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}
    return values


def derive_local_identities(upstream_files, candidate_files, *, microbatch=8):
    """Derive actual adapted identities before constructing the inert manifest.

    Local identities are deliberately distinct from upstream source manifests.
    Each variant excludes the other variant's generated training source.
    """
    try:
        bundle = build_training_bundle(upstream_files, candidate_files, microbatch=microbatch)
        return {'identities': _derived_identities(bundle, _runtime_pins()),
                'adaptationReceipt': deepcopy(bundle['receipt'])}
    except (OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def _input(label, kind, root, root_identity, row):
    return InputPin(label, kind, root, RootIdentity(**root_identity),
                    FilePin(row['basename'], row['sha256'], row['sizeBytes']))


def _inputs(config, environment: tuple[InputPin, ...]) -> tuple[InputPin, ...]:
    pins = [_input('tokenizer', 'tokenizer', config['inputRoot'], config['inputRootIdentity'], config['tokenizer'])]
    token = config['tokenBytes']
    pins.append(_input('token-bytes', 'tokenBytes', token['root'], token['rootIdentity'], token))
    for shard in config['dataset']['shards']:
        label = 'shard-' + hashlib.sha256(shard['id'].encode()).hexdigest()[:32]
        pins.append(_input(label, 'data', config['inputRoot'], config['inputRootIdentity'], shard))
    if config['checkpoint'] is not None:
        checkpoint = config['checkpoint']
        pins.append(_input('evaluation-checkpoint', 'checkpoint', checkpoint['root'], checkpoint['rootIdentity'], checkpoint))
    return tuple(pins) + environment


class _LocalDriver:
    def __init__(self, bundle, *, entrypoint, comparison_manifest, variant_sha256,
                 program_root, program_root_identity, operator_config, environment_pins,
                 plan_reader, before_effect, reserve_output, evaluation_factory, environment_verifier,
                 launch_spec, cache_root, cache_root_identity):
        _require(entrypoint in {'train_baseline.py', 'train_candidate.py', 'evaluate.py'})
        _require(type(program_root_identity) is RootIdentity and type(operator_config) is dict
                 and set(operator_config) == _BASE_KEYS and callable(plan_reader) and callable(before_effect))
        _require(type(environment_pins) is tuple and all(type(pin) is InputPin and pin.kind == 'environment'
                 for pin in environment_pins))
        environment_pins = cast(tuple[InputPin, ...], environment_pins)
        environment = {pin.label: pin for pin in environment_pins}
        _require(len(environment) == len(environment_pins) == 3 and set(environment) ==
                 {'environment-lockfile', 'environment-inventory', 'environment-kernel'})
        manifest = validate_manifest(comparison_manifest)
        _require(manifest['initialCheckpoint'] is None and manifest['protocol']['seed'] == 42)
        _require(environment['environment-lockfile'].file.sha256 == manifest['environment']['lockfileSha256'])
        for label, key in (('environment-inventory', 'installedInventory'), ('environment-kernel', 'runtimeKernel')):
            pin = environment[label].file
            _require({'sha256': pin.sha256, 'sizeBytes': pin.size_bytes} == manifest['environment'][key])
        receipt = bundle['receipt']
        self._runtime = _runtime_pins()
        derived = _derived_identities(bundle, self._runtime)
        baseline = derived['baseline']['sha256']
        candidate = derived['candidate']['sha256']
        for field, key in (('code', 'evaluatorCode'), ('configuration', 'evaluatorConfiguration')):
            _require(manifest['evaluator'][field] == {name: derived[key][name] for name in ('sha256', 'sizeBytes')})
        _require(manifest['baselineSourceManifestSha256'] == baseline)
        expected = baseline if entrypoint == 'train_baseline.py' else candidate
        _require(variant_sha256 in {baseline, candidate} if entrypoint == 'evaluate.py' else variant_sha256 == expected)
        _require(callable(environment_verifier))
        environment_policy = getattr(environment_verifier, 'configuration_fingerprint', None)
        _require(type(environment_policy) is str and re.fullmatch('[a-f0-9]{64}', environment_policy))
        evaluation_policy = getattr(evaluation_factory, 'configuration_fingerprint', None)
        if evaluation_factory is not None:
            _require(type(evaluation_policy) is str and re.fullmatch('[a-f0-9]{64}', evaluation_policy))
        storage_policy = getattr(reserve_output, 'configuration_fingerprint', None)
        if reserve_output is not None:
            _require(type(storage_policy) is str and re.fullmatch('[a-f0-9]{64}', storage_policy))
        _require(operator_config['outputCheckpoint'] is None)
        _require((entrypoint == 'evaluate.py' and callable(evaluation_factory) and reserve_output is None
                  and operator_config['outputCheckpoint'] is None)
                 or (entrypoint != 'evaluate.py' and evaluation_factory is None and callable(reserve_output)))
        _require(set(bundle['generatedFiles']) == set(receipt['generatedSha256']))
        self._generated = {name: bytes(raw) for name, raw in bundle['generatedFiles'].items()}
        _require(all(hashlib.sha256(raw).hexdigest() == receipt['generatedSha256'][name]
                     for name, raw in self._generated.items()))
        self._root, self._identity = Path(program_root).absolute(), program_root_identity
        self._entrypoint, self._manifest, self._variant = entrypoint, manifest, variant_sha256
        _require(type(cache_root_identity) is RootIdentity and type(launch_spec) in {ResearchProcessSpec, UvResearchProcessSpec})
        self._cache_root, self._cache_identity = Path(cache_root).absolute(), cache_root_identity
        self._spec = cast(ResearchProcessSpec, launch_spec)
        self.validate_spec(launch_spec)
        self._operator_json = _encoded(operator_config)
        self._environment = environment_pins
        self._plan_reader, self._guard = plan_reader, before_effect
        self._reserve, self._evaluation = reserve_output, evaluation_factory
        self._environment_verifier, self._environment_policy = environment_verifier, environment_policy
        self._storage_policy = storage_policy
        self._evaluation_policy = evaluation_policy
        self._microbatch = receipt['approvedMicrobatch']
        self._fingerprint = digest({'revision': 'research-local-driver-v1', 'entrypoint': entrypoint,
            'programRoot': str(self._root), 'rootIdentity': asdict(program_root_identity),
            'bundleReceipt': receipt, 'runtimeFiles': [asdict(pin) for pin in self._runtime],
            'manifest': manifest, 'variantSha256': variant_sha256,
            'operatorConfig': json.loads(self._operator_json),
            'environmentPins': [asdict(pin) for pin in environment_pins],
            'environmentVerifierPolicy': environment_policy, 'storagePolicy': storage_policy,
            'evaluationResolverPolicy': evaluation_policy,
            'launchSpec': asdict(launch_spec), 'cacheRoot': str(self._cache_root),
            'cacheRootIdentity': asdict(cache_root_identity)})

    @property
    def configuration_fingerprint(self):
        return self._fingerprint

    @property
    def entrypoint_path(self):
        return str(self._root / self._entrypoint)

    @property
    def config_path(self):
        return str(self._root / 'run-config.json')

    def validate_spec(self, spec):
        """Provider construction must call this before accepting a launch spec."""
        _require(type(spec) in {ResearchProcessSpec, UvResearchProcessSpec} and spec == self._spec
                 and spec.argv == ('-B', self.entrypoint_path, '--config', self.config_path)
                 and spec.working_directory == str(self._root)
                 and spec.working_directory_identity == (self._identity.device, self._identity.inode))
        _require(self._cache_root != self._root and self._root not in self._cache_root.parents
                 and self._cache_root not in self._root.parents)
        environment = dict(spec.environment)
        # -B forbids writes but alone still permits reading existing .pyc files.
        # The exact sealed root has no cache directories, so redirect reads too.
        _require(environment.get('PYTHONPYCACHEPREFIX') == str(self._root))
        for key in ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR'):
            _require(environment.get(key) == str(self._cache_root))
        if 'HF_HOME' in environment:
            _require(environment['HF_HOME'] == str(self._cache_root))
        for path, identity in ((self._root, self._identity), (self._cache_root, self._cache_identity)):
            fd = _root(path, asdict(identity))
            os.close(fd)

    def __call__(self, record):
        phase = 'binding-validation'
        try:
            _sync(self._guard)
            self.validate_spec(self._spec)
            _require(_runtime_pins() == self._runtime)
            lease = record['binding']
            plan = _sync(self._plan_reader, lease['planId'], lease['ownerId'])
            _require(type(plan) is dict and plan['id'] == lease['planId'] and plan['ownerId'] == lease['ownerId']
                     and digest(plan) == lease['planHash'])
            manifest_sha = manifest_fingerprint(self._manifest)
            _require(lease['executionGuard']['manifestSha256'] == manifest_sha
                     and lease['executionGuard']['variantSha256'] == self._variant)
            binding = checkpoint_binding({'ownerId': lease['ownerId'], 'taskId': lease['localTaskId'],
                'nativeRunId': lease['nativeRunId'], 'planId': lease['planId'],
                'planFingerprint': plan['fingerprint'], 'leaseId': lease['id'],
                'providerJobId': record['processPin']['id'], 'variantSha256': self._variant,
                'manifestSha256': manifest_sha})
            root_fd = _root(self._root, asdict(self._identity))
            try:
                existing = set(os.listdir(root_fd))
            finally:
                os.close(root_fd)
            _require(not existing or SEAL in existing)
            config = {**json.loads(self._operator_json), 'schema': 1, 'comparisonManifest': self._manifest,
                      'binding': binding, 'checkpoint': None, 'evaluationContract': None}
            checkpoint_identity, contract_sha = None, None
            if self._reserve is not None:
                _require(self._reserve.configuration_fingerprint == self._storage_policy)
                _sync(self._guard)
                config['outputCheckpoint'] = _sync(self._reserve, dict(binding))
            if self._evaluation is not None:
                _require(self._evaluation.configuration_fingerprint == self._evaluation_policy)
                evaluation = _sync(self._evaluation, deepcopy(record), dict(binding))
                _require(type(evaluation) is dict and set(evaluation) == {'checkpoint', 'evaluationContract'})
                config.update(deepcopy(evaluation))
            phase = 'runtime-config-validation'
            config = validate_runtime_configuration(config,
                mode='evaluate' if self._entrypoint == 'evaluate.py' else 'train', microbatch=self._microbatch)
            if config['evaluationContract'] is not None:
                contract = config['evaluationContract']
                _require(contract['training']['variantSha256'] == self._variant
                         and all(contract['evaluatorExecution'][key] == binding[key] for key in _EXECUTION))
                checkpoint_identity = dict(contract['training']['checkpoint'])
                contract_sha = evaluation_contract_fingerprint(contract)
            phase = 'environment-verification'
            _require(self._environment_verifier.configuration_fingerprint == self._environment_policy)
            environment_request = {'environment': deepcopy(self._manifest['environment']),
                'runtimeKernel': deepcopy(self._manifest['environment']['runtimeKernel']),
                'sampleSetSha256': self._manifest['dataset']['sampleSetSha256'],
                'configurationFingerprint': self._environment_policy,
                'launchSpec': asdict(self._spec), 'trustedRuntimePackage': str(Path(__file__).absolute().parent),
                'trustedRuntimeFiles': [asdict(pin) for pin in self._runtime],
                'runtimeConfig': deepcopy(config),
                'environmentPins': [asdict(pin) for pin in self._environment]}
            environment_receipt = _sync(self._environment_verifier, deepcopy(environment_request))
            _require(type(environment_receipt) is dict and set(environment_receipt) ==
                {'schema', 'status', 'requestSha256', 'observationSha256'}
                and type(environment_receipt['schema']) is int and environment_receipt['schema'] == 1
                and environment_receipt['status'] == 'VERIFIED'
                and environment_receipt['requestSha256'] == digest(environment_request)
                and type(environment_receipt['observationSha256']) is str
                and re.fullmatch('[a-f0-9]{64}', environment_receipt['observationSha256']))
            phase = 'config-staging'
            files = {**self._generated, 'run-config.json': _encoded(config)}
            descriptor = ProgramDescriptor(self._entrypoint,
                tuple(pin_bytes(name, raw) for name, raw in sorted(files.items())),
                manifest_sha, self._variant, self._identity, _inputs(config, self._environment),
                checkpoint_artifact_id=checkpoint_identity['artifactId'] if checkpoint_identity else None,
                evaluation_contract_sha256=contract_sha,
                environment_verification_sha256=digest(environment_receipt))
            if not existing:
                _sync(self._guard)
                stage_own_bundle(self._root, files, self._guard, descriptor=descriptor)
            else:
                _require(SEAL in existing)  # Never adopt a partial/unknown staging root.
            phase = 'staged-program-verification'
            verified = verify_staged_program(self._root, descriptor)
            _require(_runtime_pins() == self._runtime)
            _sync(self._guard)
            return {'schema': 1, 'descriptorSha256': verified['descriptorSha256'],
                'sourceSha256': self.configuration_fingerprint, 'manifestSha256': manifest_sha,
                'variantSha256': self._variant, 'checkpoint': checkpoint_identity,
                'evaluationContractSha256': contract_sha}
        except (OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError):
            raise ResearchDriverFailure(phase) from None


def build_local_driver(upstream_files, candidate_files, *, entrypoint, comparison_manifest,
                       variant_sha256, program_root, program_root_identity, operator_config,
                       environment_pins, plan_reader, before_effect, reserve_output=None,
                       evaluation_factory=None, environment_verifier=None, launch_spec=None,
                       cache_root=None, cache_root_identity=None, microbatch=8):
    """Adapt pinned source bytes offline; return a trusted launch-verifier closure.

    Callback/configuration arguments belong only to operator bootstrap code.
    before_effect synchronously rechecks authority/storage custody and raises on
    denial. reserve_output binds the preselected output to the original binding.
    evaluation_factory resolves an original checkpoint and builds the evaluator
    contract with this journal's IDs. Neither callback grants model authority.
    """
    try:
        bundle = build_training_bundle(upstream_files, candidate_files, microbatch=microbatch)
        return _LocalDriver(bundle, entrypoint=entrypoint, comparison_manifest=comparison_manifest,
            variant_sha256=variant_sha256, program_root=program_root,
            program_root_identity=program_root_identity, operator_config=operator_config,
            environment_pins=environment_pins, plan_reader=plan_reader, before_effect=before_effect,
            reserve_output=reserve_output, evaluation_factory=evaluation_factory,
            environment_verifier=environment_verifier, launch_spec=launch_spec,
            cache_root=cache_root, cache_root_identity=cache_root_identity)
    except (OSError, TypeError, ValueError, KeyError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None

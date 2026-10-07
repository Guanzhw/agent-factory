"""Concrete same-control-plane candidate providers within an operator envelope.

Constructs inert drivers; never starts an application, task, process, or baseline.
Target registration requires a previously committed original experiment phase.
All roots/specs/devices/limits originate in trusted operator configuration.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
import math
import os
import re
from pathlib import Path
from typing import cast

from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec, open_working_directory
from agent_factory.research_bootstrap_assembly import _Reservation, _Evaluation, REVISION as BOOTSTRAP_REVISION
from agent_factory.research_environment_observer import ResearchEnvironmentObserver
from agent_factory.research_local_driver import _LocalDriver, build_local_driver, derive_local_identities
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_manifest import manifest_fingerprint, validate_manifest
from agent_factory.research_preparation_provider import PreparationProvider
from agent_factory.research_staging import RootIdentity
from agent_factory.research_training_adapter import build_training_bundle
from agent_factory.resources import ComputePool, RemoteTarget, PersistentResourceService
from agent_factory.store import canonical, digest
from research_candidate_reopen import make_snapshot


def require(value):
    if not value:
        raise ValueError('AUTORESEARCH_SCIENTIFIC_ASSEMBLY_INVALID')


@dataclass(frozen=True)
class ScientificStage:
    spec: UvResearchProcessSpec
    program_identity: RootIdentity
    cache_root: Path
    cache_identity: RootIdentity
    custody_root: Path


class ScientificPhaseAssembler:
    def __init__(self, state, *, owner, upstream_files, captured_inputs, environment_pins,
                 stages, limits, gpu_binding, device_observer, preparation, checkpoints,
                 preparation_target_ref, preparation_reference, microbatch=1, bounds_profile=None):
        require(set(stages) == {'training', 'evaluation'} and all(type(v) is ScientificStage for v in stages.values())
            and type(limits) is ResearchProcessLimits and callable(device_observer))
        self.state, self.store, self.owner = state, state['store'], owner
        self.files, self.inputs = deepcopy(upstream_files), deepcopy(captured_inputs)
        self.manifest = validate_manifest(self.inputs['comparisonManifest'])
        require(manifest_fingerprint(self.manifest) == self.inputs['manifestSha256']
            and self.manifest['device']['identitySha256'] == gpu_binding.identity_key
            and self.manifest['protocol']['totalWallSeconds'] == limits.wall_seconds)
        self.environment, self.stages = tuple(environment_pins), dict(stages)
        self.limits, self.gpu, self.observer = limits, gpu_binding, device_observer
        self.preparation, self.checkpoints, self.prep_ref = preparation, checkpoints, preparation_target_ref
        require(type(preparation_reference) is dict and set(preparation_reference) == {'taskId', 'artifactId'}
            and all(type(v) is str and 1 <= len(v) <= 200 for v in preparation_reference.values()))
        self.preparation_reference = deepcopy(preparation_reference)
        self.microbatch, self.bounds = microbatch, bounds_profile
        self.pending = {}
        self.phase_stages = {}
        self.phase_intents = {}
        self.base_custody = {phase: self._directory_identity(stage.custody_root) for phase, stage in self.stages.items()}
        self.evaluation_registrations = {}
        self.evaluation_services = {}
        target = self.store.process_runtime.resources.targets[preparation_target_ref]
        require(type(target.provider) is PreparationProvider and target.owners == frozenset({owner}))
        self.prep_target = target

    def _candidate(self, candidate):
        require(type(candidate) is dict and type(candidate.get('trainPy')) is str)
        files = {**self.files, 'train.py': cast(str, candidate['trainPy']).encode('utf-8')}
        derived = derive_local_identities(self.files, files, microbatch=self.microbatch)
        identities = derived['identities']
        require(identities['baseline']['sha256'] == self.manifest['baselineSourceManifestSha256'])
        for field, name in (('code', 'evaluatorCode'), ('configuration', 'evaluatorConfiguration')):
            require(self.manifest['evaluator'][field] == {k: identities[name][k] for k in ('sha256', 'sizeBytes')})
        require(identities['candidate']['sha256'] != identities['baseline']['sha256'])
        return files, identities['candidate']['sha256']

    def preparation_receipt(self):
        """Read original producer custody; never export/reseal or dispatch work."""
        ref = self.preparation_reference
        # Immutable expected identity only; no authority is inferred from it.
        # The final fresh reader validates original custody and bytes before return.
        pin = deepcopy(self.inputs['operatorInputs']['tokenBytes'])
        require(pin == self.inputs['operatorInputs']['tokenBytes']
            and {k: pin[k] for k in ('sha256', 'sizeBytes')} == self.manifest['tokenizer']['tokenBytes'])
        binding = pin['binding']
        require(binding['ownerId'] == self.owner and binding['taskId'] == ref['taskId'])
        runtime = self.store.process_runtime
        original = runtime._original(ref['taskId'])
        require(original is not None and original['lease_id'] == binding['leaseId']
            and original['native_run_id'] == binding['nativeRunId'] and original['owner_id'] == self.owner)
        lease, target, task, _ = runtime._custody(binding['leaseId'])
        plan = self.store.plan(binding['planId'], self.owner)
        require(target is self.prep_target and lease['connectionRef'] == self.prep_ref
            and lease['ownerId'] == self.owner and lease['localTaskId'] == binding['taskId']
            and lease['nativeRunId'] == binding['nativeRunId'] and lease['planId'] == binding['planId']
            and lease['providerJobId'] == binding['providerJobId'] and plan['fingerprint'] == binding['planFingerprint']
            and task['id'] == ref['taskId'] and not task['cancel_requested']
            and lease['state'] == 'RECLAIMED' and lease['capacityHeld'] is False
            and lease['executionStatus'] == 'COMPLETED' and type(lease['exitCode']) is int and lease['exitCode'] == 0
            and lease.get('stopEvidence', {}).get('allStopped') is True)
        artifact, _ = self.store.artifact(ref['taskId'], ref['artifactId'])
        require(artifact['id'] == ref['artifactId'] and artifact['jobId'] == ref['taskId']
            and all(artifact['provenance'].get(k) == v for k, v in binding.items()))
        # Revalidate original storage bytes and authority after reading metadata.
        require(self.preparation.input_pin(self.owner, ref['taskId'], ref['artifactId']) == pin)
        fields = ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId')
        return {'execution': {k: binding[k] for k in fields}, 'artifact': deepcopy(artifact)}

    def _token(self, prior):
        prep = prior['preparation']
        require(prep['state'] == 'COMPLETED'
            and {key: prep['receipt'][key] for key in ('execution', 'artifact')} == self.preparation_receipt())
        return deepcopy(self.inputs['operatorInputs']['tokenBytes'])

    def _training(self, prior, variant):
        train = prior['training']; require(train['state'] == 'COMPLETED')
        receipt = train['receipt']
        metadata, actual = self.checkpoints.identity(receipt['execution']['taskId'], receipt['artifact']['id'],
            self.manifest['artifactLimits']['checkpointBytes'])
        require(metadata['id'] == receipt['artifact']['id'] and train['config']['variantSha256'] == variant)
        return {**receipt['execution'], 'variantSha256': variant,
            'checkpoint': {'artifactId': metadata['id'], **actual}}

    @staticmethod
    def _directory_identity(path):
        info = os.stat(path, follow_symlinks=False)
        pin = RootIdentity(info.st_dev, info.st_ino)
        fd = open_working_directory(str(path), (pin.device, pin.inode))
        os.close(fd)
        return pin

    def _envelope(self):
        return digest({'limits': asdict(self.limits), 'gpu': self.gpu.to_dict(),
            'observer': self.observer.configuration_fingerprint,
            'manifest': self.manifest, 'inputs': self.inputs,
            'environment': [asdict(pin) for pin in self.environment],
            'microbatch': self.microbatch, 'bounds': self.bounds,
            'stages': {phase: {'spec': asdict(stage.spec), 'program': asdict(stage.program_identity),
                'cacheRoot': str(stage.cache_root), 'cache': asdict(stage.cache_identity),
                'custodyRoot': str(stage.custody_root), 'custody': asdict(self.base_custody[phase])}
                for phase, stage in self.stages.items()}})

    def _intent(self, ctx, phase, candidate):
        require(ctx.run_context.user_id == self.owner and type(ctx.run_context.run_id) is str
            and bool(ctx.run_context.run_id) and type(ctx.run_context.session_id) is str
            and bool(ctx.run_context.session_id))
        return {'ownerId': self.owner, 'parentTaskId': ctx.run_context.session_id,
            'parentRunId': ctx.run_context.run_id, 'phase': phase,
            'candidateSha256': digest(candidate), 'envelopeSha256': self._envelope()}

    def __call__(self, phase, candidate, prior, *, context):
        require(phase in {'preparation', 'training', 'evaluation'})
        _, variant = self._candidate(candidate)
        intent = self._intent(context, phase, candidate)
        ref = self.prep_ref if phase == 'preparation' else 'ar-science-' + digest(intent)[:48]
        pin = {'targetRef': ref, 'comparisonManifest': deepcopy(self.manifest),
            'comparisonManifestSha256': manifest_fingerprint(self.manifest), 'variantSha256': variant}
        # Pure intent only: no mkdir, provider constructor, registry mutation or launch.
        self.phase_intents[ref] = intent
        return pin

    def _namespace(self, phase, intent, *, saved=None):
        base = self.stages[phase]
        name = 'ar-' + digest(intent)[:48]
        roots = ((Path(base.spec.working_directory), base.program_identity),
            (base.cache_root, base.cache_identity), (base.custody_root, self.base_custody[phase]))
        actual = []
        for index, (parent, identity) in enumerate(roots):
            fd = open_working_directory(str(parent), (identity.device, identity.inode))
            try:
                if saved is None:
                    # No reuse after a crash before snapshot commit. Preserve unknown
                    # partial namespaces; never delete or reset an existing directory.
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                path = parent / name
                flags = os.O_RDONLY | cast(int, getattr(os, 'O_DIRECTORY', None)) | cast(int, getattr(os, 'O_NOFOLLOW', None))
                child_fd = os.open(name, flags, dir_fd=fd)
                try:
                    info = os.fstat(child_fd)
                    pin = RootIdentity(info.st_dev, info.st_ino)
                    # The trusted inode comes from the held original parent, not
                    # a fresh pathname lookup after mkdir (parent replacement).
                    current_fd = open_working_directory(str(path), (pin.device, pin.inode))
                    os.close(current_fd)
                    parent_check = open_working_directory(str(parent), (identity.device, identity.inode))
                    os.close(parent_check)
                finally:
                    os.close(child_fd)
                if saved is not None:
                    require(asdict(pin) == saved[index])
                actual.append((path, pin))
            finally:
                os.close(fd)
        (program, program_pin), (cache, cache_pin), (custody, _) = actual
        environment = dict(base.spec.environment)
        environment['PYTHONPYCACHEPREFIX'] = str(program)
        for key in ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR'):
            environment[key] = str(cache)
        if 'HF_HOME' in environment: environment['HF_HOME'] = str(cache)
        entry = 'evaluate.py' if phase == 'evaluation' else 'train_candidate.py'
        spec = replace(base.spec, working_directory=str(program),
            working_directory_identity=(program_pin.device, program_pin.inode),
            argv=('-B', str(program / entry), '--config', str(program / 'run-config.json')),
            environment=tuple(environment.items()))
        return ScientificStage(spec, program_pin, cache, cache_pin, custody), [asdict(pin) for _, pin in actual]

    def _build(self, phase, candidate, prior, pin, stage, inputs, training, *, stop_only=False):
        files, variant = self._candidate(candidate)
        environment = {item.label: item for item in self.environment}
        env_verifier = ResearchEnvironmentObserver(environment['environment-inventory'],
            environment['environment-kernel'], bounds_profile=self.bounds)
        pending = {'state': self.state, 'checkpoints': self.checkpoints}
        evaluation = _Evaluation(pending, self.checkpoints, training, self.manifest,
            self.manifest['artifactLimits']['checkpointBytes']) if training is not None else None
        reservation = None if training is not None else _Reservation(pending, self.limits.disk_bytes)
        def guard():
            if stop_only: raise ValueError('AUTORESEARCH_RESTORED_DISPATCH_FORBIDDEN')
            require(self._token(prior) == inputs['tokenBytes'])
            if training is not None: require(self._training(prior, variant) == training)
        driver = build_local_driver(self.files, files,
            entrypoint='evaluate.py' if phase == 'evaluation' else 'train_candidate.py',
            comparison_manifest=self.manifest, variant_sha256=variant,
            program_root=Path(stage.spec.working_directory), program_root_identity=stage.program_identity,
            operator_config=inputs, environment_pins=self.environment, plan_reader=self.store.plan,
            before_effect=guard, reserve_output=reservation, evaluation_factory=evaluation,
            environment_verifier=env_verifier, launch_spec=stage.spec, cache_root=stage.cache_root,
            cache_root_identity=stage.cache_identity, microbatch=self.microbatch)
        provider = ResearchLocalProvider(self.store, stage.custody_root, stage.spec, self.limits,
            gpu_binding=self.gpu, source_fingerprint=driver.configuration_fingerprint,
            manifest_fingerprint=manifest_fingerprint(self.manifest), observer=self.observer, program_verifier=driver,
            stop_only=stop_only)
        memory, disk = self.limits.address_space_mb, math.ceil(self.limits.disk_bytes / 1024**2)
        target = RemoteTarget('Original scientific ' + phase, 'compute', frozenset({self.owner}), provider=provider,
            synthetic_fixture=False, max_cpu=1, max_memory_mb=memory, max_disk_mb=disk,
            max_seconds=int(self.limits.wall_seconds), gpu_binding=self.gpu,
            capacity_pool=ComputePool('research-device', 1, memory, disk, 1, 1))
        self.phase_stages[pin['targetRef']] = stage
        return target

    def _register(self, phase, candidate, prior, pin, target):
        resources = self.store.process_runtime.resources
        require(self.store.research_runtime.resources is resources)
        for registry in (resources.targets, self.state['settings'].remote_targets):
            previous = registry.get(pin['targetRef'])
            require(previous is None or previous is target)
        PersistentResourceService(self.store, self.state['auth'], {**resources.targets, pin['targetRef']: target})
        if phase == 'evaluation':
            record = {'pin': deepcopy(pin), 'candidate': deepcopy(candidate), 'prior': deepcopy(prior),
                'target': target, 'fingerprint': resources._target_fingerprint(target)}
            previous = self.evaluation_registrations.get(pin['targetRef'])
            require(previous is None or previous == record)
            self.evaluation_registrations[pin['targetRef']] = record
        for registry in (resources.targets, self.state['settings'].remote_targets):
            registry[pin['targetRef']] = target
        self.pending[pin['targetRef']] = target
        return target

    def verify_authority(self, phase, candidate, prior, pin, target):
        """Original metadata only: safe inside admission transactions, no retention locks."""
        files, variant = self._candidate(candidate)
        require(pin['variantSha256'] == variant and pin['comparisonManifest'] == self.manifest
            and pin['comparisonManifestSha256'] == manifest_fingerprint(self.manifest)
            and target.owners == frozenset({self.owner}) and target.synthetic_fixture is False)
        if phase == 'preparation':
            require(target is self.prep_target and pin['targetRef'] == self.prep_ref
                and type(target.provider) is PreparationProvider)
            return
        provider = target.provider
        require(type(provider) is ResearchLocalProvider and provider.spec == self.phase_stages[pin['targetRef']].spec
            and provider.limits == self.limits and target.gpu_binding == self.gpu)
        driver = provider._program_verifier
        require(type(driver) is _LocalDriver and driver._manifest == self.manifest and driver._variant == variant
            and driver._entrypoint == ('evaluate.py' if phase == 'evaluation' else 'train_candidate.py')
            and driver._generated == build_training_bundle(self.files, files, microbatch=self.microbatch)['generatedFiles']
            and driver.configuration_fingerprint == provider._source)
        driver.validate_spec(provider.spec)
        require(json.loads(driver._operator_json)['tokenBytes'] == self.inputs['operatorInputs']['tokenBytes'])
        if phase == 'evaluation':
            evaluation = driver._evaluation
            require(type(evaluation) is _Evaluation)
            train = prior['training']; receipt = train['receipt']
            require(train['state'] == 'COMPLETED' and train['config']['variantSha256'] == variant)
            expected = {**receipt['execution'], 'variantSha256': variant}
            actual = evaluation.training
            require(type(actual) is dict and set(actual) == set(expected) | {'checkpoint'}
                and all(actual[key] == value for key, value in expected.items()))
            checkpoint = actual['checkpoint']
            require(type(checkpoint) is dict and set(checkpoint) == {'artifactId', 'sha256', 'sizeBytes'}
                and checkpoint['artifactId'] == receipt['artifact']['id']
                and type(checkpoint['sha256']) is str and re.fullmatch('[a-f0-9]{64}', checkpoint['sha256']) is not None
                and type(checkpoint['sizeBytes']) is int and 0 < checkpoint['sizeBytes'] <= self.manifest['artifactLimits']['checkpointBytes']
                and evaluation.manifest == self.manifest and evaluation.maximum == self.manifest['artifactLimits']['checkpointBytes']
                and evaluation.configuration_fingerprint == driver._evaluation_policy
                and evaluation.configuration_fingerprint == digest({'revision': BOOTSTRAP_REVISION,
                    'purpose': 'independent-original-evaluator', 'training': actual,
                    'manifestSha256': manifest_fingerprint(self.manifest), 'maximum': evaluation.maximum}))

    def verify_phase(self, phase, candidate, prior, pin, target):
        self.verify_authority(phase, candidate, prior, pin, target)
        if phase == 'preparation':
            self.preparation_receipt()
            return
        driver = target.provider._program_verifier
        require(json.loads(driver._operator_json)['tokenBytes'] == self._token(prior))
        if phase == 'evaluation':
            require(driver._evaluation.training == self._training(prior, pin['variantSha256']))

    def _committed(self, ctx, phase, candidate, pin):
        rows = self.store.sql('SELECT * FROM af_autoresearch_experiments WHERE parent_run_id=:run', run=ctx.run_context.run_id)
        require(len(rows) == 1)
        row = rows[0]
        require(row['owner_id'] == self.owner == ctx.run_context.user_id
            and row['parent_task_id'] == ctx.run_context.session_id and row['body']['candidate'] == candidate
            and row['body']['phases'][phase]['config'] == pin)
        return row['body']['phases'][phase]

    def register_phase(self, ctx, phase, candidate, prior, pin, *, persist_snapshot):
        entry = self._committed(ctx, phase, candidate, pin)
        intent = self._intent(ctx, phase, candidate)
        require(self.phase_intents.get(pin['targetRef']) == intent)
        if phase == 'preparation':
            self.verify_phase(phase, candidate, prior, pin, self.prep_target)
            return self._register(phase, candidate, prior, pin, self.prep_target)
        require(callable(persist_snapshot) and pin['targetRef'] == 'ar-science-' + digest(intent)[:48])
        if 'runtimeSnapshot' in entry:
            wrapped = entry['runtimeSnapshot']
            require(wrapped['sha256'] == digest(wrapped['body']))
            return self.restore_phase(ctx, phase, candidate, prior, pin, wrapped['body'])
        require(pin['targetRef'] not in self.store.process_runtime.resources.targets)
        inputs = deepcopy(self.inputs['operatorInputs']); inputs['tokenBytes'] = self._token(prior)
        training = self._training(prior, pin['variantSha256']) if phase == 'evaluation' else None
        stage, identities = self._namespace(phase, intent)
        target = self._build(phase, candidate, prior, pin, stage, inputs, training)
        self.verify_phase(phase, candidate, prior, pin, target)
        files, _ = self._candidate(candidate)
        captured = deepcopy(self.inputs); captured['operatorInputs'] = inputs
        snapshot = {'schema': 1, 'kind': 'autoresearch-scientific-phase-v1', 'intent': intent,
            'pin': deepcopy(pin), 'limits': asdict(self.limits), 'gpu': self.gpu.to_dict(),
            'observerFingerprint': self.observer.configuration_fingerprint, 'rootIdentities': identities,
            'poolFingerprint': cast(ComputePool, target.capacity_pool).fingerprint,
            'providerFingerprint': cast(ResearchLocalProvider, target.provider).configuration_fingerprint,
            'targetFingerprint': self.store.process_runtime.resources._target_fingerprint(target),
            'launch': make_snapshot(stage=phase, captured_inputs=captured, environment_pins=self.environment,
                launch_spec=stage.spec, program_identity=asdict(stage.program_identity), cache_root=stage.cache_root,
                cache_identity=asdict(stage.cache_identity), custody_root=stage.custody_root,
                upstream_files=self.files, candidate_files=files, training=training,
                microbatch=self.microbatch, bounds_profile=self.bounds)}
        snapshot = json.loads(canonical(snapshot))
        require(len(canonical(snapshot).encode()) <= 40 * 1024**2)
        require(persist_snapshot(deepcopy(snapshot)) == snapshot)
        return self._register(phase, candidate, prior, pin, target)

    def restore_phase(self, ctx, phase, candidate, prior, pin, snapshot):
        entry = self._committed(ctx, phase, candidate, pin)
        wrapped = entry.get('runtimeSnapshot')
        require(type(wrapped) is dict and wrapped.get('body') == snapshot and wrapped.get('sha256') == digest(snapshot))
        fields = {'schema', 'kind', 'intent', 'pin', 'limits', 'gpu', 'observerFingerprint', 'rootIdentities',
            'poolFingerprint', 'providerFingerprint', 'targetFingerprint', 'launch'}
        require(type(snapshot) is dict and set(snapshot) == fields and type(snapshot['schema']) is int
            and snapshot['schema'] == 1 and snapshot['kind'] == 'autoresearch-scientific-phase-v1'
            and len(canonical(snapshot).encode()) <= 40 * 1024**2 and phase in {'training', 'evaluation'})
        intent = self._intent(ctx, phase, candidate)
        require(snapshot['intent'] == intent and snapshot['pin'] == pin
            and pin['targetRef'] == 'ar-science-' + digest(intent)[:48]
            and snapshot['limits'] == asdict(self.limits) and snapshot['gpu'] == self.gpu.to_dict()
            and snapshot['observerFingerprint'] == self.observer.configuration_fingerprint)
        stage, _ = self._namespace(phase, intent, saved=snapshot['rootIdentities'])
        launch = snapshot['launch']
        captured = launch['capturedInputs']
        require(captured == self.inputs)
        files, _ = self._candidate(candidate)
        expected = make_snapshot(stage=phase, captured_inputs=captured, environment_pins=self.environment,
            launch_spec=stage.spec, program_identity=asdict(stage.program_identity), cache_root=stage.cache_root,
            cache_identity=asdict(stage.cache_identity), custody_root=stage.custody_root,
            upstream_files=self.files, candidate_files=files, training=launch['training'],
            microbatch=self.microbatch, bounds_profile=self.bounds)
        require(launch == json.loads(canonical(expected)) and (phase == 'training') == (launch['training'] is None))
        target = self._build(phase, candidate, prior, pin, stage, captured['operatorInputs'], launch['training'], stop_only=True)
        resources = self.store.process_runtime.resources
        require(cast(ResearchLocalProvider, target.provider).configuration_fingerprint == snapshot['providerFingerprint']
            and cast(ComputePool, target.capacity_pool).fingerprint == snapshot['poolFingerprint']
            and resources._target_fingerprint(target) == snapshot['targetFingerprint'])
        # No fresh run grant or scientific reader is needed to reconstruct custody.
        # Restored driver's launch callback rejects all new staging/dispatch.
        return self._register(phase, candidate, prior, pin, target)

    def evaluation_service(self, pin):
        require(type(pin) is dict and set(pin) == {'targetRef', 'comparisonManifest',
            'comparisonManifestSha256', 'variantSha256'})
        record = self.evaluation_registrations.get(pin['targetRef'])
        require(record is not None and record['pin'] == pin)
        assert record is not None
        resources = self.store.research_runtime.resources
        require(resources is self.store.process_runtime.resources)
        target = record['target']
        require(resources.targets.get(pin['targetRef']) is target
            and self.state['settings'].remote_targets.get(pin['targetRef']) is target
            and resources._target_fingerprint(target) == record['fingerprint'])
        self.verify_phase('evaluation', record['candidate'], record['prior'], pin, target)
        if pin['targetRef'] not in self.evaluation_services:
            self.evaluation_services[pin['targetRef']] = ResearchEvaluationService(self.store,
                self.state['auth'], resources, {digest(self.manifest['evaluator']): pin['targetRef']},
                checkpoint_reader=self.checkpoints.identity)
        return self.evaluation_services[pin['targetRef']]

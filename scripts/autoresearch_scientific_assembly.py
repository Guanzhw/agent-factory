"""Concrete same-control-plane candidate providers within an operator envelope.

Constructs inert drivers; never starts an application, task, process, or baseline.
Target registration requires a previously committed original experiment phase.
All roots/specs/devices/limits originate in trusted operator configuration.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import hashlib
import math
from pathlib import Path
from typing import cast

from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec
from agent_factory.research_bootstrap_assembly import _Reservation, _Evaluation
from agent_factory.research_environment_observer import ResearchEnvironmentObserver
from agent_factory.research_local_driver import _LocalDriver, build_local_driver, derive_local_identities
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.research_manifest import manifest_fingerprint, validate_manifest
from agent_factory.research_preparation_provider import PreparationProvider
from agent_factory.research_preparation_driver import PreparationDriver
from agent_factory.research_staging import RootIdentity
from agent_factory.research_training_adapter import build_training_bundle
from agent_factory.resources import ComputePool, RemoteTarget, PersistentResourceService
from agent_factory.store import digest


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
                 preparation_target_ref, microbatch=1, bounds_profile=None):
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
        self.microbatch, self.bounds = microbatch, bounds_profile
        self.pending = {}
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

    def _token(self, prior):
        prep = prior['preparation']
        require(prep['state'] == 'COMPLETED')
        receipt = prep['receipt']
        pin = self.preparation.input_pin(self.owner, receipt['execution']['taskId'], receipt['artifact']['id'])
        require({k: pin[k] for k in ('sha256', 'sizeBytes')} == self.manifest['tokenizer']['tokenBytes'])
        return pin

    def _training(self, prior, variant):
        train = prior['training']; require(train['state'] == 'COMPLETED')
        receipt = train['receipt']
        metadata, actual = self.checkpoints.identity(receipt['execution']['taskId'], receipt['artifact']['id'],
            self.manifest['artifactLimits']['checkpointBytes'])
        require(metadata['id'] == receipt['artifact']['id'] and train['config']['variantSha256'] == variant)
        return {**receipt['execution'], 'variantSha256': variant,
            'checkpoint': {'artifactId': metadata['id'], **actual}}

    def __call__(self, phase, candidate, prior):
        require(phase in {'preparation', 'training', 'evaluation'})
        files, variant = self._candidate(candidate)
        if phase == 'preparation':
            target, ref = self.prep_target, self.prep_ref
        else:
            stage = self.stages[phase]
            require(type(stage.spec) is UvResearchProcessSpec)
            inputs = deepcopy(self.inputs['operatorInputs']); inputs['tokenBytes'] = self._token(prior)
            environment = {pin.label: pin for pin in self.environment}
            env_verifier = ResearchEnvironmentObserver(environment['environment-inventory'],
                environment['environment-kernel'], bounds_profile=self.bounds)
            pending = {'state': self.state, 'checkpoints': self.checkpoints}
            training = self._training(prior, variant) if phase == 'evaluation' else None
            evaluation = _Evaluation(pending, self.checkpoints, training, self.manifest,
                self.manifest['artifactLimits']['checkpointBytes']) if training is not None else None
            reservation = None if training is not None else _Reservation(pending, self.limits.disk_bytes)
            def guard():
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
                manifest_fingerprint=manifest_fingerprint(self.manifest), observer=self.observer, program_verifier=driver)
            memory, disk = self.limits.address_space_mb, math.ceil(self.limits.disk_bytes / 1024**2)
            target = RemoteTarget('Original scientific ' + phase, 'compute', frozenset({self.owner}), provider=provider,
                synthetic_fixture=False, max_cpu=1, max_memory_mb=memory, max_disk_mb=disk,
                max_seconds=int(self.limits.wall_seconds), gpu_binding=self.gpu,
                capacity_pool=ComputePool('research-device', 1, memory, disk, 1, 1))
            ref = 'ar-science-' + digest({'candidate': digest(candidate), 'phase': phase,
                'provider': provider.configuration_fingerprint})[:48]
        pin = {'targetRef': ref, 'comparisonManifest': deepcopy(self.manifest),
            'comparisonManifestSha256': manifest_fingerprint(self.manifest), 'variantSha256': variant}
        self.verify_phase(phase, candidate, prior, pin, target)
        self.pending[ref] = target
        return pin

    def verify_phase(self, phase, candidate, prior, pin, target):
        files, variant = self._candidate(candidate)
        require(pin['variantSha256'] == variant and pin['comparisonManifest'] == self.manifest
            and pin['comparisonManifestSha256'] == manifest_fingerprint(self.manifest)
            and target.owners == frozenset({self.owner}) and target.synthetic_fixture is False)
        if phase == 'preparation':
            require(target is self.prep_target and pin['targetRef'] == self.prep_ref
                and type(target.provider) is PreparationProvider and type(target.provider.driver) is PreparationDriver)
            driver = target.provider.driver
            require({'sha256': hashlib.sha256(driver.raw).hexdigest(), 'sizeBytes': len(driver.raw)}
                == self.manifest['tokenizer']['tokenizer'])
            require(driver.configuration_fingerprint == target.provider._source)
            driver.validate_spec(target.provider.spec)
            return
        provider = target.provider
        require(type(provider) is ResearchLocalProvider and provider.spec == self.stages[phase].spec
            and provider.limits == self.limits and target.gpu_binding == self.gpu)
        driver = provider._program_verifier
        require(type(driver) is _LocalDriver and driver._manifest == self.manifest and driver._variant == variant
            and driver._entrypoint == ('evaluate.py' if phase == 'evaluation' else 'train_candidate.py')
            and driver._generated == build_training_bundle(self.files, files, microbatch=self.microbatch)['generatedFiles']
            and driver.configuration_fingerprint == provider._source)
        driver.validate_spec(provider.spec)
        require(json.loads(driver._operator_json)['tokenBytes'] == self._token(prior))
        if phase == 'evaluation':
            require(type(driver._evaluation) is _Evaluation and driver._evaluation.training == self._training(prior, variant))

    def register_phase(self, ctx, phase, candidate, prior, pin):
        rows = self.store.sql('SELECT * FROM af_autoresearch_experiments WHERE parent_run_id=:run', run=ctx.run_context.run_id)
        require(len(rows) == 1)
        row = rows[0]
        require(row['owner_id'] == self.owner == ctx.run_context.user_id
            and row['parent_task_id'] == ctx.run_context.session_id and row['body']['candidate'] == candidate
            and row['body']['phases'][phase]['config'] == pin)
        target = self.pending[pin['targetRef']]
        self.verify_phase(phase, candidate, prior, pin, target)
        resources = self.store.process_runtime.resources
        require(self.store.research_runtime.resources is resources)
        for registry in (resources.targets, self.state['settings'].remote_targets):
            previous = registry.get(pin['targetRef'])
            require(previous is None or previous is target)
        # Reuse the production registry constructor's alias/pool conflict checks
        # before any insertion; constructor is validation-only, with no SQL/effects.
        PersistentResourceService(self.store, self.state['auth'], {**resources.targets, pin['targetRef']: target})
        for registry in (resources.targets, self.state['settings'].remote_targets):
            registry[pin['targetRef']] = target
        return target

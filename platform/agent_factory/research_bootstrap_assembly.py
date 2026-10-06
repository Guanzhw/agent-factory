"""Trusted development wiring for original preparation/training/evaluation jobs.

No public JSON adapter registry, provider credentials or task identities enter
this module. Callers supply locally captured input evidence and existing pinned
executables. The application still creates its native identities and approvals.
"""
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path

from .config import Settings
from .gpu_custody import GpuBinding
from .main import create_app
from .process_enforcement import ProcessLimits, ProcessSpec, ResearchProcessLimits, UvResearchProcessSpec
from .process_runtime_profile import process_settings
from .research_checkpoint_store import ResearchCheckpointStore
from .research_environment_observer import ResearchEnvironmentObserver
from .research_evaluation import validate_evaluation_contract
from .research_evaluation_service import ResearchEvaluationService
from .research_local_driver import build_local_driver
from .research_local_provider import ResearchLocalProvider
from .research_manifest import manifest_fingerprint, validate_manifest
from .research_preparation_driver import PreparationDriver
from .research_preparation_provider import PreparationProvider
from .research_preparation_store import ResearchPreparationStore
from .research_runtime_profile import research_settings
from .research_staging import RootIdentity
from .resources import ComputePool, RemoteTarget
from .store import Store, digest

REVISION = 'task-research-bootstrap-v1'


def _require(value):
    if not value:
        raise ValueError('RESEARCH_BOOTSTRAP_ASSEMBLY_INVALID')


def development_settings(settings):
    """Keep one policy identity across the preparation and research phases."""
    _require(settings.demo is True and settings.host == '127.0.0.1'
             and settings.temporary_policy == 'admin-review' and settings.max_workers == 1)
    return replace(settings, runtime_tool_contract='research-bootstrap-v1',
        policy_revision=REVISION, material_policy_revision=REVISION,
        plan_review_ttl_seconds=86400)


def prepare_application(*, db_url, workspace, program_root, program_identity,
                        custody_root, executable, executable_sha256, tokenizer_json,
                        preparation_manifest_sha256, owner='alice', diagnostics=None):
    """Construct the original bounded preparation target; execute nothing."""
    workspace, program_root = Path(workspace), Path(program_root)
    pending = {}
    def at(stage):
        if diagnostics is not None:
            diagnostics.at(stage)
    at('PREPARATION_SETTINGS')
    bootstrap_settings = development_settings(Settings(db_url=db_url, workspace=workspace,
        max_workers=1, temporary_policy='admin-review'))
    at('PREPARATION_DATABASE')
    bootstrap = Store(db_url, bootstrap_settings)
    try:
        at('PREPARATION_DRIVER')
        driver = PreparationDriver(root=program_root, root_identity=program_identity,
            tokenizer_json=tokenizer_json, manifest_sha256=preparation_manifest_sha256,
            reserve=lambda *args, **kwargs: pending['preparation'].reserve(*args, **kwargs))
        at('PREPARATION_PROCESS_SPEC')
        spec = ProcessSpec(executable, executable_sha256,
            ('-I', '-B', str(program_root / 'prepare.py'), str(program_root / 'run-config.json')))
        limits = ProcessLimits(file_size_bytes=65536, wall_seconds=5)
        at('PREPARATION_PROVIDER')
        provider = PreparationProvider(bootstrap, Path(custody_root), spec, limits, driver=driver)
        at('PREPARATION_TARGET')
        target = RemoteTarget('Task-local safe tokenizer preparation', 'compute', frozenset({owner}),
            provider=provider, synthetic_fixture=False, max_cpu=1, max_memory_mb=128,
            max_disk_mb=4, max_seconds=5, capacity_pool=ComputePool('research-preparation', 1, 128, 4, 1, 1))
        at('PREPARATION_APPLICATION_SETTINGS')
        settings = development_settings(process_settings(db_url=db_url, workspace=workspace,
            target_ref='preparation', remote_targets={'preparation': target}, owner=owner))
        at('PREPARATION_CREATE_APP')
        app = create_app(settings)
        state = app.app.state.factory
        store = state['store']
        at('PREPARATION_STORE')
        preparation = ResearchPreparationStore(store, state['auth'], store.process_runtime.resources,
            store.storage, preparation_manifest_sha256=preparation_manifest_sha256,
            source_sha256=driver.configuration_fingerprint)
        pending['preparation'] = preparation
        return {'app': app, 'state': state, 'preparation': preparation, 'target': target,
                'providerStore': bootstrap, 'settings': settings}
    except BaseException as error:
        if diagnostics is not None:
            diagnostics.capture(error)
        at('PREPARATION_ASSEMBLY_CLEANUP')
        bootstrap.engine.dispose()
        raise



class _Reservation:
    def __init__(self, pending, disk_bytes):
        self.pending, self.disk_bytes = pending, disk_bytes
        self.configuration_fingerprint = digest({'revision': REVISION, 'diskBytes': disk_bytes,
            'purpose': 'original-training-checkpoint'})

    def __call__(self, binding):
        return self.pending['checkpoints'].reserve(binding, disk_bytes=self.disk_bytes)


class _Evaluation:
    def __init__(self, pending, training_store, training, manifest, maximum):
        self.pending, self.training_store = pending, training_store
        self.training, self.manifest, self.maximum = deepcopy(training), deepcopy(manifest), maximum
        self.configuration_fingerprint = digest({'revision': REVISION,
            'purpose': 'independent-original-evaluator', 'training': training,
            'manifestSha256': manifest_fingerprint(manifest), 'maximum': maximum})

    def __call__(self, _record, binding):
        training = self.training
        _, actual = self.training_store.identity(training['taskId'], training['checkpoint']['artifactId'], self.maximum)
        _require(actual == {key: training['checkpoint'][key] for key in ('sha256', 'sizeBytes')})
        store = self.training_store.store
        _, raw = store.artifact(training['taskId'], training['checkpoint']['artifactId'])
        reference = json.loads(raw)
        contract = validate_evaluation_contract({'schema': 1,
            'evidenceKind': 'offline_research_evaluation_contract', 'comparisonManifest': self.manifest,
            'training': training, 'evaluatorExecution': {key: binding[key] for key in
                ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId')}})
        self.pending['evaluationContract'] = contract
        checkpoint = {**actual, 'root': str(store.storage.objects / reference['storageObjectId']),
            'basename': reference['basename'], 'rootIdentity': reference['rootIdentity'],
            'binding': reference['binding']}
        return {'checkpoint': checkpoint, 'evaluationContract': contract}


def research_application(*, db_url, workspace, upstream_files, captured_inputs,
        environment_pins, launch_spec, program_identity, cache_root, cache_identity,
        custody_root, limits, gpu_binding, device_observer, preparation,
        preparation_task_id, preparation_artifact_id, prior_targets, prior_adapters,
        prior_pricing, training_store=None, training=None, owner='alice', microbatch=1,
        bounds_profile=None):
    """Wire a training or independent evaluator stage from captured original inputs.

    prior registrations retain the exact preparation (and, for evaluation,
    training) authority and provider fingerprints. Keep their provider stores
    alive until the complete controller has stopped and returned custody.
    """
    _require(type(launch_spec) is UvResearchProcessSpec and type(limits) is ResearchProcessLimits
             and type(gpu_binding) is GpuBinding and callable(device_observer)
             and (training is None) == (training_store is None))
    manifest = validate_manifest(captured_inputs['comparisonManifest'])
    _require(manifest_fingerprint(manifest) == captured_inputs['manifestSha256']
             and manifest['device']['identitySha256'] == gpu_binding.identity_key
             and manifest['protocol']['totalWallSeconds'] == limits.wall_seconds)
    inputs = deepcopy(captured_inputs['operatorInputs'])
    _require(inputs['tokenBytes'] == preparation.input_pin(owner, preparation_task_id, preparation_artifact_id))
    environment = {pin.label: pin for pin in environment_pins}
    observer = ResearchEnvironmentObserver(environment['environment-inventory'],
        environment['environment-kernel'], bounds_profile=bounds_profile)
    pending = {}
    bootstrap = Store(db_url, development_settings(Settings(db_url=db_url, workspace=Path(workspace),
        max_workers=1, temporary_policy='admin-review')))
    try:
        evaluating = training is not None
        reference = 'evaluation' if evaluating else 'training'
        _require(reference not in prior_targets)
        resolver = _Evaluation(pending, training_store, training, manifest,
            manifest['artifactLimits']['checkpointBytes']) if evaluating else None
        reservation = None if evaluating else _Reservation(pending, limits.disk_bytes)

        def guard():
            _require(preparation.input_pin(owner, preparation_task_id, preparation_artifact_id) == inputs['tokenBytes'])

        driver = build_local_driver(upstream_files, upstream_files,
            entrypoint='evaluate.py' if evaluating else 'train_baseline.py',
            comparison_manifest=manifest, variant_sha256=manifest['baselineSourceManifestSha256'],
            program_root=Path(launch_spec.working_directory), program_root_identity=RootIdentity(**program_identity),
            operator_config=inputs, environment_pins=tuple(environment_pins),
            plan_reader=lambda *args: pending['state']['store'].plan(*args), before_effect=guard,
            reserve_output=reservation, evaluation_factory=resolver, environment_verifier=observer,
            launch_spec=launch_spec, cache_root=Path(cache_root), cache_root_identity=RootIdentity(**cache_identity),
            microbatch=microbatch)
        provider = ResearchLocalProvider(bootstrap, Path(custody_root), launch_spec, limits,
            gpu_binding=gpu_binding, source_fingerprint=driver.configuration_fingerprint,
            manifest_fingerprint=manifest_fingerprint(manifest), observer=device_observer, program_verifier=driver)
        memory, disk = limits.address_space_mb, math.ceil(limits.disk_bytes / 1024**2)
        target = RemoteTarget('Task-local original research ' + reference, 'compute', frozenset({owner}),
            provider=provider, synthetic_fixture=False, max_cpu=1, max_memory_mb=memory,
            max_disk_mb=disk, max_seconds=int(limits.wall_seconds), gpu_binding=gpu_binding,
            capacity_pool=ComputePool('research-device', 1, memory, disk, 1, 1))
        settings = research_settings(db_url=db_url, workspace=Path(workspace), target_ref=reference,
            remote_targets={**prior_targets, reference: target}, comparison_manifest=manifest, owner=owner)
        # Distinct adapter IDs keep previous immutable plans executable for evidence reads.
        if evaluating:
            from .research_runtime_profile import registrations
            settings = replace(settings,
                runtime_adapters=registrations(target_ref=reference, comparison_manifest=manifest,
                    owner=owner, adapter_suffix='-evaluation'),
                usage_pricing=tuple(replace(item, adapter_id=item.adapter_id + '-evaluation') for item in settings.usage_pricing))
        settings = development_settings(replace(settings,
            runtime_adapters=[*prior_adapters, *settings.runtime_adapters],
            usage_pricing=(*prior_pricing, *settings.usage_pricing)))
        app = create_app(settings)
        state = app.app.state.factory
        checkpoints = ResearchCheckpointStore(state['store'], state['auth'],
            state['store'].research_runtime.resources, state['store'].storage)
        pending.update(state=state, checkpoints=checkpoints)
        if evaluating:
            state['research_evaluation'] = state['store'].research_evaluation = ResearchEvaluationService(state['store'], state['auth'],
                state['store'].research_runtime.resources, {digest(manifest['evaluator']): reference},
                checkpoint_reader=checkpoints.identity)
        return {'app': app, 'state': state, 'checkpoints': checkpoints, 'target': target,
                'settings': settings, 'providerStore': bootstrap, 'pending': pending,
                'orchestrationKind': 'deterministic-development-control', 'syntheticProvider': False}
    except BaseException:
        bootstrap.engine.dispose()
        raise

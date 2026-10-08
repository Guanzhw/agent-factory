"""External trusted candidate wiring over the unchanged installed research runtime.

No source monkeypatch, alternate lifecycle, GPU execution or credential acquisition.
Callers retain provider stores and publish with the matching candidate suffix.
"""
from copy import deepcopy
from dataclasses import replace
import math
from pathlib import Path

from agent_factory.config import Settings
from agent_factory.gpu_custody import GpuBinding
from agent_factory.main import create_app
from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec
from agent_factory.research_bootstrap_assembly import _Reservation, _Evaluation
from agent_factory.research_bootstrap_policy import development_settings
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.research_environment_observer import ResearchEnvironmentObserver
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_local_driver import build_local_driver, derive_local_identities
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.research_manifest import manifest_fingerprint, validate_manifest
from agent_factory.research_runtime_profile import research_settings, registrations
from agent_factory.research_staging import RootIdentity
from agent_factory.research_training_adapter import build_training_bundle
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store, digest


def _require(value):
    if not value:
        raise ValueError('RESEARCH_CANDIDATE_ASSEMBLY_INVALID')


def research_application(*, db_url, workspace, upstream_files, candidate_files, captured_inputs,
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
    derived = derive_local_identities(upstream_files, candidate_files, microbatch=microbatch)
    bundle = build_training_bundle(upstream_files, candidate_files, microbatch=microbatch)
    _require(bundle['generatedFiles']['train_candidate.py'] != bundle['generatedFiles']['train_baseline.py'])
    identities = derived['identities']
    variant = identities['candidate']['sha256']
    _require(manifest['baselineSourceManifestSha256'] == identities['baseline']['sha256'])
    for field, identity in (('code', 'evaluatorCode'), ('configuration', 'evaluatorConfiguration')):
        _require(manifest['evaluator'][field] == {
            key: identities[identity][key] for key in ('sha256', 'sizeBytes')})
    _require(training is None or training.get('variantSha256') == variant)
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
        suffix = '-candidate-evaluation' if evaluating else '-candidate-training'
        _require(reference not in prior_targets)
        resolver = _Evaluation(pending, training_store, training, manifest,
            manifest['artifactLimits']['checkpointBytes']) if evaluating else None
        reservation = None if evaluating else _Reservation(pending, limits.disk_bytes)

        def guard():
            _require(preparation.input_pin(owner, preparation_task_id, preparation_artifact_id) == inputs['tokenBytes'])

        driver = build_local_driver(upstream_files, candidate_files,
            entrypoint='evaluate.py' if evaluating else 'train_candidate.py',
            comparison_manifest=manifest, variant_sha256=variant,
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
            remote_targets={**prior_targets, reference: target}, comparison_manifest=manifest, owner=owner, variant_sha256=variant)
        # Candidate adapters cannot overwrite retained baseline or preparation authority.
        settings = replace(settings,
            runtime_adapters=registrations(target_ref=reference, comparison_manifest=manifest,
                owner=owner, variant_sha256=variant, adapter_suffix=suffix),
            usage_pricing=tuple(replace(item, adapter_id=item.adapter_id + suffix) for item in settings.usage_pricing))
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

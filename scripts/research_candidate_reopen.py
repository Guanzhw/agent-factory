"""Reconstruct existing research targets from inert original launch snapshots.

No app/lifespan, task creation, allocation or dispatch. Callers supply an opened
existing state. Reconstructed drivers reject every new staging/launch effect.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
from typing import Any, cast

from agent_factory.gpu_custody import GpuBinding
from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec
from agent_factory.research_bootstrap_assembly import _Reservation, _Evaluation
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.research_device_observer import NvidiaSmiObserver
from agent_factory.research_environment_observer import ResearchEnvironmentObserver
from agent_factory.research_local_driver import ScientificRuntimePin, build_local_driver, derive_local_identities
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.research_manifest import manifest_fingerprint, validate_manifest
from agent_factory.research_staging import FilePin, InputPin, RootIdentity
from agent_factory.resources import ComputePool, RemoteTarget

_FIELDS = {'schema', 'stage', 'capturedInputs', 'environmentPins', 'launchSpec', 'programIdentity',
           'cacheRoot', 'cacheIdentity', 'custodyRoot', 'upstreamFiles', 'candidateFiles', 'training',
           'microbatch', 'boundsProfile'}


def _require(value):
    if not value:
        raise ValueError('RESEARCH_CANDIDATE_REOPEN_INVALID')


def _stop_only():
    raise ValueError('RESEARCH_REOPEN_DISPATCH_FORBIDDEN')


def make_snapshot(*, stage, captured_inputs, environment_pins, launch_spec, program_identity,
                  cache_root, cache_identity, custody_root, upstream_files, candidate_files,
                  training=None, microbatch=1, bounds_profile=None):
    """Return private JSON-compatible original inputs; caller persists before dispatch."""
    _require(stage in {'training', 'evaluation'} and (stage == 'training') == (training is None))
    return deepcopy({'schema': 1, 'stage': stage, 'capturedInputs': captured_inputs,
        'environmentPins': [asdict(pin) for pin in environment_pins], 'launchSpec': asdict(launch_spec),
        'programIdentity': program_identity, 'cacheRoot': str(cache_root), 'cacheIdentity': cache_identity,
        'custodyRoot': str(custody_root), 'upstreamFiles': {name: raw.hex() for name, raw in upstream_files.items()},
        'candidateFiles': {name: raw.hex() for name, raw in candidate_files.items()}, 'training': training,
        'microbatch': microbatch, 'boundsProfile': bounds_profile})


def _files(value):
    _require(type(value) is dict and 1 <= len(value) <= 256)
    _require(all(type(name) is str and type(raw) is str and len(raw) <= 8 * 1024**2
                 for name, raw in value.items()))
    value = cast(dict[str, str], value)
    _require(sum(len(raw) for raw in value.values()) <= 32 * 1024**2)
    return {name: bytes.fromhex(raw) for name, raw in value.items()}


def reconstruct_research_target(state, config, snapshot, *, candidate=True, owner='alice',
                                scientific_runtime: ScientificRuntimePin | None = None):
    """Rebuild original training/evaluation authority; caller checks persisted custody.

    State requires store/auth/resources/storage, with native/lifecycle services
    attached by its owner. No provider operation is performed by construction.
    Candidate false selects the original baseline entrypoint and identity.
    """
    _require(type(snapshot) is dict and set(snapshot) == _FIELDS and snapshot['schema'] == 1)
    snap = deepcopy(snapshot)
    stage, training = snap['stage'], snap['training']
    _require(stage in {'training', 'evaluation'} and (stage == 'training') == (training is None))
    upstream, proposed = _files(snap['upstreamFiles']), _files(snap['candidateFiles'])
    if not candidate:
        _require(upstream == proposed)
    manifest = validate_manifest(snap['capturedInputs']['comparisonManifest'])
    _require(manifest_fingerprint(manifest) == snap['capturedInputs']['manifestSha256'])
    derived = derive_local_identities(upstream, proposed, microbatch=snap['microbatch'],
                                      scientific_runtime=scientific_runtime)['identities']
    variant = derived['candidate' if candidate else 'baseline']['sha256']
    _require(training is None or training['variantSha256'] == variant)
    spec_data = snap['launchSpec']
    spec_data['argv'] = tuple(spec_data['argv'])
    spec_data['environment'] = tuple(tuple(pair) for pair in spec_data['environment'])
    spec_data['working_directory_identity'] = tuple(spec_data['working_directory_identity'])
    spec = UvResearchProcessSpec(**spec_data)
    # Constructors must only reopen existing namespaces, never create new roots.
    for root in (spec.working_directory, snap['cacheRoot'], snap['custodyRoot']):
        path = Path(root)
        _require(path.is_absolute() and path.is_dir() and not path.is_symlink())
    pins = tuple(InputPin(label=row['label'], kind=row['kind'], root=row['root'],
        root_identity=RootIdentity(**row['root_identity']), file=FilePin(**row['file'])) for row in snap['environmentPins'])
    limits = ResearchProcessLimits(**config['limits'])
    gpu = GpuBinding(config['receiverNamespaceSha256'], hashlib.sha256(config['deviceUuid'].encode()).hexdigest())
    _require(manifest['device']['identitySha256'] == gpu.identity_key
             and manifest['protocol']['totalWallSeconds'] == limits.wall_seconds)
    device = NvidiaSmiObserver(Path(config['nvidiaSmi']['executable']), config['nvidiaSmi']['sha256'],
        config['deviceUuid'], gpu, 'task-local-real-observer-v1')
    environment = {pin.label: pin for pin in pins}
    observer = ResearchEnvironmentObserver(environment['environment-inventory'], environment['environment-kernel'],
        bounds_profile=snap['boundsProfile'])
    store, auth, resources = state['store'], state['auth'], state['resources']
    checkpoints = ResearchCheckpointStore(store, auth, resources, store.storage)
    pending = {'state': state, 'checkpoints': checkpoints}
    resolver = _Evaluation(pending, checkpoints, training, manifest, manifest['artifactLimits']['checkpointBytes']) if training else None
    reservation = None if training else _Reservation(pending, limits.disk_bytes)
    driver = build_local_driver(upstream, proposed,
        entrypoint='evaluate.py' if training else 'train_candidate.py' if candidate else 'train_baseline.py',
        comparison_manifest=manifest, variant_sha256=variant, program_root=Path(spec.working_directory),
        program_root_identity=RootIdentity(**snap['programIdentity']), operator_config=snap['capturedInputs']['operatorInputs'],
        environment_pins=pins, plan_reader=store.plan, before_effect=_stop_only,
        reserve_output=reservation, evaluation_factory=resolver, environment_verifier=observer,
        launch_spec=spec, cache_root=Path(snap['cacheRoot']), cache_root_identity=RootIdentity(**snap['cacheIdentity']),
        microbatch=snap['microbatch'], scientific_runtime=scientific_runtime)
    provider = ResearchLocalProvider(store, Path(snap['custodyRoot']), spec, limits,
        gpu_binding=gpu, source_fingerprint=driver.configuration_fingerprint,
        manifest_fingerprint=manifest_fingerprint(manifest), observer=device, program_verifier=driver)
    memory, disk = limits.address_space_mb, math.ceil(limits.disk_bytes / 1024**2)
    target = RemoteTarget('Task-local original research ' + stage, 'compute', frozenset({owner}),
        provider=provider, synthetic_fixture=False, max_cpu=1, max_memory_mb=memory,
        max_disk_mb=disk, max_seconds=int(limits.wall_seconds), gpu_binding=gpu,
        capacity_pool=ComputePool('research-device', 1, memory, disk, 1, 1))
    return {'target': target, 'driver': driver, 'checkpoints': checkpoints, 'pending': pending, 'reference': stage}


def make_preparation_snapshot(*, program_root, program_identity, custody_root, executable,
                              executable_sha256, tokenizer_json, preparation_manifest_sha256, preflight_seconds=0):
    """Persist the original preparation inputs before its native dispatch."""
    _require(type(preflight_seconds) is int and 0 <= preflight_seconds <= 30)
    return deepcopy({'schema': 1, 'stage': 'preparation', 'programRoot': str(program_root),
        'programIdentity': program_identity, 'custodyRoot': str(custody_root), 'executable': executable,
        'executableSha256': executable_sha256, 'tokenizerHex': tokenizer_json.hex(),
        'preparationManifestSha256': preparation_manifest_sha256,
        **({'preflightSeconds': preflight_seconds} if preflight_seconds else {})})


def reconstruct_preparation_target(state, snapshot, *, owner='alice'):
    """Reopen preparation's original provider without executing its reserve hook."""
    from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
    from agent_factory.research_preparation_driver import PreparationDriver
    from agent_factory.research_preparation_provider import PreparationProvider
    _require(type(snapshot) is dict and set(snapshot) - {'preflightSeconds'} == {'schema', 'stage', 'programRoot', 'programIdentity',
        'custodyRoot', 'executable', 'executableSha256', 'tokenizerHex', 'preparationManifestSha256'}
        and snapshot['schema'] == 1 and snapshot['stage'] == 'preparation')
    snapshot = cast(dict[str, Any], snapshot)
    preflight = snapshot.get('preflightSeconds', 0)
    _require(type(preflight) is int and 0 <= preflight <= 30)
    _require(type(snapshot['tokenizerHex']) is str and len(snapshot['tokenizerHex']) <= 2 * 1024**2)
    for name in ('programRoot', 'custodyRoot'):
        path = Path(snapshot[name])
        _require(path.is_absolute() and path.is_dir() and not path.is_symlink())
    root = Path(snapshot['programRoot'])
    driver = PreparationDriver(root=root, root_identity=snapshot['programIdentity'],
        tokenizer_json=bytes.fromhex(snapshot['tokenizerHex']), manifest_sha256=snapshot['preparationManifestSha256'],
        reserve=lambda *args, **kwargs: _stop_only())
    spec = ProcessSpec(snapshot['executable'], snapshot['executableSha256'],
        ('-I', '-B', str(root / 'prepare.py'), str(root / 'run-config.json')))
    limits = ProcessLimits(file_size_bytes=65536, wall_seconds=5)
    provider = PreparationProvider(state['store'], Path(snapshot['custodyRoot']), spec, limits, driver=driver, preflight_seconds=preflight)
    target = RemoteTarget('Task-local safe tokenizer preparation', 'compute', frozenset({owner}),
        provider=provider, synthetic_fixture=False, max_cpu=1, max_memory_mb=128,
        max_disk_mb=4, max_seconds=5 + preflight, capacity_pool=ComputePool('research-preparation', 1, 128, 4, 1, 1))
    return {'target': target, 'driver': driver, 'reference': 'preparation'}

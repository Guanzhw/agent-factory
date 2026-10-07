"""Reauthenticate retained baseline evidence through original installed custody.

The caller reconstructs the original providers and services without entering an
application lifespan. Files or hashes alone never establish a baseline score.
This module neither initializes services nor dispatches, resumes or stops work.
"""
from copy import deepcopy
import asyncio
import json
from pathlib import Path

from agent_factory.gpu_custody import validate_gpu_evidence
from agent_factory.research_evaluation import validate_evaluation_contract
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_manifest import manifest_fingerprint


def _require(value):
    if not value:
        raise ValueError('RESEARCH_RETAINED_BASELINE_UNVERIFIED')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def build_baseline_snapshots(config):
    """Read original sealed stage inputs for faithful provider reconstruction.

These snapshots are reconstruction inputs, not authenticated historical facts.
The real provider's derived fingerprint must match the original database binding
when the verifier reads custody. In particular the observed cache inode cannot
be accepted as a new historical pin without that full fingerprint comparison.
No inventory, directory, receipt, contract or identity is created here.
    """
    from run_research_baseline import read_private, unique, identity
    from audit_released_research_custody import journal_read
    from agent_factory.research_profile import SOURCE_SHA256, verify_upstream_source

    def read(path):
        return json.loads(read_private(path, 16 * 1024**2), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE')))

    workspace = Path(config['workspace'])
    identity(workspace)
    upstream = {name: read_private(Path(config['upstreamRoot']) / name,
                                  8 * 1024**2, private=False) for name in SOURCE_SHA256}
    verify_upstream_source(upstream)
    training_receipt = read(workspace / 'training-receipt.json')
    evaluation_receipt = read(workspace / 'evaluation-receipt.json')
    snapshots = {}
    runconfigs = {}
    for stage, receipt in (('training', training_receipt), ('evaluation', evaluation_receipt)):
        _require(type(receipt) is dict and type(receipt.get('progress')) is dict)
        lease_id = receipt['progress']['leaseId']
        _require(type(lease_id) is str and lease_id
                 and all(c.isascii() and (c.isalnum() or c in '_-') for c in lease_id))
        program = workspace / (stage + '-program')
        runconfig = read(program / 'run-config.json')
        seal = read(program / 'program.seal.json')
        journal, _ = journal_read(workspace / (stage + '-custody') / lease_id / 'custody.sqlite')
        spec = journal['spec']
        _require(spec['working_directory'] == str(program))
        # JSON key order is not a source of identity: compare explicit fields.
        _require(spec['working_directory_identity'] ==
                 [seal['root_identity']['device'], seal['root_identity']['inode']])
        manifest = runconfig['comparisonManifest']
        _require(manifest_fingerprint(manifest) == seal['comparison_manifest_sha256'])
        environment = [pin for pin in seal['inputs'] if pin['kind'] == 'environment']
        _require(len(environment) == 3)
        cache = workspace / (stage + '-cache')
        spec_env = dict(spec['environment'])
        _require(all(spec_env.get(key) == str(cache) for key in
            ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR')))
        original_contract = read(workspace / 'environment' / 'interpreter-contract.json')
        _require(_canonical(json.loads(spec['interpreter_contract'])) == _canonical(original_contract))
        operator = {key: deepcopy(runconfig[key]) for key in
            ('inputRoot', 'inputRootIdentity', 'tokenizer', 'tokenBytes', 'dataset')}
        operator['outputCheckpoint'] = None
        snapshots[stage] = {'schema': 1, 'stage': stage,
            'capturedInputs': {'comparisonManifest': manifest,
                'manifestSha256': manifest_fingerprint(manifest), 'operatorInputs': operator},
            'environmentPins': environment, 'launchSpec': spec,
            'programIdentity': seal['root_identity'], 'cacheRoot': str(cache),
            'cacheIdentity': identity(cache), 'custodyRoot': str(workspace / (stage + '-custody')),
            'upstreamFiles': {key: value.hex() for key, value in upstream.items()},
            'candidateFiles': {key: value.hex() for key, value in upstream.items()},
            'training': deepcopy(training_receipt['imported']) if stage == 'evaluation' else None,
            'microbatch': config['microbatch'], 'boundsProfile': original_contract.get('boundsProfile')}
        runconfigs[stage] = runconfig
    contract = validate_evaluation_contract(runconfigs['evaluation']['evaluationContract'])
    _require(_canonical(contract['training']) == _canonical(training_receipt['imported'])
             and _canonical(snapshots['training']['capturedInputs']) ==
                 _canonical(snapshots['evaluation']['capturedInputs']))
    return {'snapshots': snapshots, 'contract': contract,
            'receipt': evaluation_receipt, 'runConfig': runconfigs['training']}


def authorize_baseline(inputs):
    """Synchronous CLI gate before candidate preparation or native startup.

Reconstruction uses only original baseline files. Existing-schema service
composition may perform idempotent metadata/configuration operations; it never
seeds identities, publishes material, opens a lifespan or dispatches a process.
    """
    from dataclasses import replace
    from bootstrap_research_control import read_database_url
    from research_candidate_state import open_state
    from research_candidate_reopen import reconstruct_research_target
    from agent_factory.config import Settings
    from agent_factory.research_bootstrap_policy import development_settings
    from agent_factory.research_runtime_profile import research_settings, registrations
    from agent_factory.process_runtime_profile import process_settings
    from agent_factory.research_checkpoint_store import ResearchCheckpointStore
    from agent_factory.store import digest

    original = inputs['baselineConfig']
    captured = build_baseline_snapshots(original)
    _require(_canonical(captured['receipt']) == _canonical(inputs['baselineReceipt'])
             and _canonical(captured['runConfig']) == _canonical(inputs['baselineRunConfig']))
    manifest = captured['contract']['comparisonManifest']
    _require(manifest_fingerprint(manifest) == inputs['manifestSha256'])
    db = read_database_url(original['databaseUrlFile'])
    workspace = Path(original['workspace'])
    basic = development_settings(Settings(db_url=db, workspace=workspace, max_workers=1,
                                           temporary_policy='admin-review'))
    with open_state(basic) as provider_state:
        targets = {stage: reconstruct_research_target(provider_state, original, snapshot,
                   candidate=False)['target'] for stage, snapshot in captured['snapshots'].items()}
        settings = research_settings(db_url=db, workspace=workspace, target_ref='evaluation',
            remote_targets=targets, comparison_manifest=manifest)
        preparation = process_settings(db_url=db, workspace=workspace, target_ref='preparation',
                                       remote_targets={})
        training_adapters = registrations(target_ref='training', comparison_manifest=manifest)
        evaluation_adapters = registrations(target_ref='evaluation', comparison_manifest=manifest,
                                            adapter_suffix='-evaluation')
        settings = development_settings(replace(settings,
            runtime_adapters=[*preparation.runtime_adapters, *training_adapters, *evaluation_adapters],
            usage_pricing=(*preparation.usage_pricing, *settings.usage_pricing,
                *(replace(price, adapter_id=price.adapter_id + '-evaluation') for price in settings.usage_pricing))))
        with open_state(settings, full_verification=True) as state:
            checkpoints = ResearchCheckpointStore(state['store'], state['auth'], state['resources'],
                                                   state['store'].storage)
            service = ResearchEvaluationService(state['store'], state['auth'], state['resources'],
                {digest(manifest['evaluator']): 'evaluation'}, checkpoint_reader=checkpoints.identity)
            observed = asyncio.run(verify_retained_baseline(service=service, owner='alice',
                contract=captured['contract'], retained_receipt=captured['receipt'],
                expected_manifest_sha256=inputs['manifestSha256']))
    _require(_canonical(observed) == _canonical(inputs['observation']))
    return observed


def _terminal_custody(service, owner, contract):
    """Require positive original native and GPU closure without reconciliation."""
    for field in ('training', 'evaluatorExecution'):
        execution = contract[field]
        lease, _ = service._execution(owner, execution, contract['comparisonManifest'],
                                      training=field == 'training')
        runtime = service.resources.execution_runtime('research-process-run-v1')
        current, _, task, ticket = runtime._custody(execution['leaseId'])
        _require(current == lease and task.get('terminal') is True
                 and ticket.get('status') == 'completed'
                 and ticket.get('persistedRunStatus') == 'completed'
                 and (lease.get('gpuEvidence') or {}).get('state') == 'RELEASED'
                 and ((lease.get('gpuEvidence') or {}).get('releaseProof') or {}).get('kind')
                    == 'original-process-stopped-and-device-released')
        # The durable lease projection stores RECLAIMED, not the provider's
        # redundant released flag. Match PersistentResourceService._update's
        # validation projection; never derive this from OS idleness.
        validate_gpu_evidence(lease, {**lease, 'released': True})


async def verify_retained_baseline(*, service, owner, contract, retained_receipt,
                                   expected_manifest_sha256):
    """Return a detached original observation only after live custody rechecks.

``service`` is the installed real verifier with independently reconstructed
original providers. ``retained_receipt`` is the original evaluation controller
receipt, including its imported evaluator proof. The expected manifest is the
operator-pinned baseline comparison hash, not a new candidate manifest.
    """
    _require(type(service) is ResearchEvaluationService)
    checked = validate_evaluation_contract(contract)
    manifest = checked['comparisonManifest']
    _require(manifest_fingerprint(manifest) == expected_manifest_sha256
             and checked['training']['variantSha256'] == manifest['baselineSourceManifestSha256'])
    _require(type(retained_receipt) is dict and set(retained_receipt) == {'progress', 'lease', 'imported'})
    retained = deepcopy(retained_receipt)
    progress, lease = retained['progress'], retained['lease']
    _require(type(progress) is dict and type(lease) is dict and type(retained['imported']) is dict)
    execution = checked['evaluatorExecution']
    _require(progress.get('phase') == 'COMPLETED' and progress.get('cleanupConfirmed') is True
             and progress.get('cancelRequested') is False)
    for key in ('taskId', 'planId', 'nativeRunId', 'leaseId', 'providerJobId'):
        _require(progress.get(key) == execution[key])
    for key, field in (('id', 'leaseId'), ('ownerId', 'ownerId'), ('localTaskId', 'taskId'),
                       ('nativeRunId', 'nativeRunId'), ('planId', 'planId'), ('providerJobId', 'providerJobId')):
        _require(lease.get(key) == execution[field])
    _require(lease.get('state') == 'RECLAIMED' and lease.get('capacityHeld') is False
             and lease.get('executionStatus') == 'COMPLETED' and type(lease.get('exitCode')) is int
             and lease['exitCode'] == 0 and (lease.get('stopEvidence') or {}).get('allStopped') is True)
    await asyncio.to_thread(_terminal_custody, service, owner, checked)
    verified = await service.verify(owner, checked)
    _require(verified.get('evidenceKind') == 'original_evaluator_custody'
             and verified.get('evaluatorCustodyVerified') is True
             and verified.get('launchInputsVerified') is True
             and verified.get('trainingSyntheticFixture') is False
             and verified.get('evaluatorSyntheticFixture') is False
             and verified['observation']['status'] == 'completed'
             and _canonical(verified) == _canonical(retained['imported']))
    await asyncio.to_thread(_terminal_custody, service, owner, checked)
    return deepcopy(verified['observation'])

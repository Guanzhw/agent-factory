"""Pure, bounded scientific evidence on an authenticated existing handoff.

The caller authenticates the peer, expected scope and current authority and builds
projections from verified original receiver stores/providers. Hashes and schemas
are not attestations. This module performs no I/O or lifecycle changes.

Scope contains schema=1 and the exact cloud parent/run/plan, delegated child,
source manifest, phase, candidate, comparison, variant and receiver-science pins.
One training/evaluation handoff describes at most one receiver-root lease.
Preparation has no phase lease: its optional proof describes the retained ORIGINAL
producer (owner/task/nativeRun/plan/planFingerprint/lease/providerJob plus artifact
ID and SHA256), which may differ from the receiver child. It is never stop proof.
Optional receipt.scientificNoDispatch binds schema=1, scopeSha256 and original
receiverTaskId/receiverPlanId/receiverNativeRunId to a durable receiver CAS that
precludes dispatch. It cannot coexist with a lease or replace prior launch evidence.
The caller must still authenticate the receiver and prove native termination.

checkpoint is the existing evaluation-contract training object. evaluation is
{contract, result}, where result is the receiver's original evaluator service
output. These supplied records still require authenticated receiver verification;
executionVerified/scientificConclusionVerified remain false.
"""
from copy import deepcopy
import json
import re
from typing import Any, cast

from .gpu_custody import validate_binding, validate_gpu_evidence
from .remote_process_evidence import project_process_evidence, validate_process_evidence
from .research_assessment import assess_observations
from .research_evaluation import validate_evaluation_contract, evaluation_contract_fingerprint
from .research_manifest import manifest_fingerprint
from .store import digest

ERROR = 'REMOTE_SCIENTIFIC_EVIDENCE_INVALID'
_SCOPE_IDS = {'originParentTaskId', 'originParentRunId', 'originChildTaskId'}
_SCOPE_HASHES = {'originParentPlanSha256', 'sourceManifestSha256', 'candidateSha256',
                 'comparisonManifestSha256', 'variantSha256', 'receiverSciencePinSha256'}
_SCOPE = {'schema', 'phase'} | _SCOPE_IDS | _SCOPE_HASHES
_FIELDS = {'schema', 'scope', 'lease', 'launchProof', 'checkpoint', 'evaluation', 'preparation'}
_EXTRA = {'planFingerprint', 'targetFingerprint', 'executionGuard', 'gpuBinding', 'gpuEvidence'}
_EXECUTION = {'ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId'}
_RECEIPT_IDS = ('id', 'originTaskId', 'remoteOwnerId', 'remoteTaskId', 'remotePlanId', 'remoteRunId')
_MAX_BYTES = 256 * 1024


def _require(value):
    if not value:
        raise ValueError(ERROR)


def _keys(value, fields):
    _require(type(value) is dict and set(value) == fields)


def _id(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value) is not None)


def _hash(value):
    _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None)


def _owner(value):
    _require(type(value) is str and 1 <= len(value) <= 200
             and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def _schema(value):
    _require(type(value['schema']) is int and value['schema'] == 1)


def validate_scientific_scope(value):
    """Detached immutable scope shape; the caller resolves its actual authority."""
    try:
        _keys(value, _SCOPE); _schema(value)
        for key in _SCOPE_IDS:
            _id(value[key])
        for key in _SCOPE_HASHES:
            _hash(value[key])
        _require(value['originParentTaskId'] != value['originChildTaskId']
                 and value['phase'] in ('preparation', 'training', 'evaluation'))
        return deepcopy(value)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def _execution(value):
    _keys(value, _EXECUTION)
    for key in _EXECUTION:
        (_hash if key == 'planFingerprint' else _owner if key == 'ownerId' else _id)(value[key])


def _matches_execution(value, lease):
    _execution(value)
    for field, source in (('ownerId', 'ownerId'), ('taskId', 'localTaskId'), ('nativeRunId', 'nativeRunId'),
                          ('planId', 'planId'), ('planFingerprint', 'planFingerprint'),
                          ('leaseId', 'id'), ('providerJobId', 'providerJobId')):
        _require(value[field] == lease[source])


def _base_receipt(receipt, lease):
    # Reuse existing root-process schema and monotonic original-identity checks.
    base = None if lease is None else {key: value for key, value in lease.items() if key not in _EXTRA}
    return {**receipt, 'processLeases': {'schema': 1, 'complete': True,
                                       'leases': [] if base is None else [base]}}


def _lease(receipt, lease, scope):
    _require(type(lease) is dict and _EXTRA <= set(lease))
    validate_process_evidence(_base_receipt(receipt, lease))
    for key in ('planFingerprint', 'targetFingerprint'):
        _hash(lease[key])
    guard = lease['executionGuard']
    _keys(guard, {'id', 'version', 'toolCallId', 'toolArgsSha256', 'manifestSha256', 'variantSha256'})
    guard = cast(dict[str, Any], guard)
    _id(guard['id']); _id(guard['toolCallId']); _hash(guard['toolArgsSha256'])
    _require(type(guard['version']) is int and 0 <= guard['version'] < 2**48
             and guard['manifestSha256'] == scope['comparisonManifestSha256']
             and guard['variantSha256'] == scope['variantSha256'])
    validate_binding(lease['gpuBinding'])
    if lease['gpuEvidence'] is None:
        # A durable reservation may precede any provider observation.
        _require(lease['providerJobId'] is None and lease['processBinding'] is None
                 and lease['capacityHeld'] is True and lease['stopEvidence'] is None)
    else:
        validate_gpu_evidence(lease, {**lease, 'released': lease['state'] == 'RECLAIMED'})


def _released(lease):
    return (lease is not None and lease['state'] == 'RECLAIMED' and lease['capacityHeld'] is False
            and type(lease['stopEvidence']) is dict and lease['stopEvidence']['allStopped'] is True
            and type(lease['gpuEvidence']) is dict and lease['gpuEvidence']['state'] == 'RELEASED')


def _completed(lease):
    _require(_released(lease) and lease['executionStatus'] == 'COMPLETED'
             and type(lease['exitCode']) is int and lease['exitCode'] == 0)


def _checkpoint(value, scope):
    _keys(value, _EXECUTION | {'variantSha256', 'checkpoint'})
    _execution({key: value[key] for key in _EXECUTION})
    _require(value['variantSha256'] == scope['variantSha256'])
    artifact = value['checkpoint']
    _keys(artifact, {'artifactId', 'sha256', 'sizeBytes'})
    _id(artifact['artifactId']); _hash(artifact['sha256'])
    _require(type(artifact['sizeBytes']) is int and 0 < artifact['sizeBytes'] <= 2 * 1024**3)


def _launch(proof, lease, scope, checkpoint):
    _keys(proof, {'schema', 'descriptorSha256', 'sourceSha256', 'manifestSha256', 'variantSha256',
                  'checkpoint', 'evaluationContractSha256', 'leaseBindingSha256',
                  'processIdentitySha256', 'executionVerified'})
    _schema(proof); _completed(lease)
    for key in ('descriptorSha256', 'sourceSha256', 'leaseBindingSha256', 'processIdentitySha256'):
        _hash(proof[key])
    _require(proof['executionVerified'] is False
             and proof['manifestSha256'] == scope['comparisonManifestSha256']
             and proof['variantSha256'] == scope['variantSha256']
             and proof['leaseBindingSha256'] == lease['processBinding']['bindingFingerprint'])
    if scope['phase'] == 'training':
        _require(proof['checkpoint'] is None and proof['evaluationContractSha256'] is None)
    else:
        _require(checkpoint is not None and proof['checkpoint'] == checkpoint['checkpoint'])
        _hash(proof['evaluationContractSha256'])


def _evaluation(value, lease, scope, checkpoint, launch):
    _keys(value, {'contract', 'result'})
    contract = validate_evaluation_contract(value['contract'])
    _require(manifest_fingerprint(contract['comparisonManifest']) == scope['comparisonManifestSha256']
             and contract['training'] == checkpoint)
    _matches_execution(contract['evaluatorExecution'], lease)
    fingerprint = evaluation_contract_fingerprint(contract)
    _require(launch['evaluationContractSha256'] == fingerprint)
    result = value['result']
    _keys(result, {'schema', 'evidenceKind', 'evaluationContractSha256', 'observation', 'rawSha256',
                   'executionVerified', 'scientificConclusionVerified', 'evaluatorCustodyVerified',
                   'launchInputsVerified', 'trainingSyntheticFixture', 'evaluatorSyntheticFixture',
                   'trainingExecution', 'evaluatorExecution', 'checkpoint'})
    _schema(result); _hash(result['rawSha256'])
    _require(result['evidenceKind'] == 'original_evaluator_custody'
             and result['evaluationContractSha256'] == fingerprint
             and result['executionVerified'] is False and result['scientificConclusionVerified'] is False
             and result['evaluatorCustodyVerified'] is True and result['launchInputsVerified'] is True
             and type(result['trainingSyntheticFixture']) is bool and type(result['evaluatorSyntheticFixture']) is bool
             and result['trainingExecution'] == {key: contract['training'][key] for key in _EXECUTION}
             and result['evaluatorExecution'] == contract['evaluatorExecution']
             and result['checkpoint'] == checkpoint['checkpoint'])
    observation = result['observation']
    assess_observations(observation, observation)
    _require(observation['comparisonIdentitySha256'] == scope['comparisonManifestSha256']
             and observation['variantSha256'] == scope['variantSha256'])


def _validated(receipt, expected_scope):
    _require(type(receipt) is dict)
    evidence = receipt['scientificEvidence']
    _keys(evidence, _FIELDS); _schema(evidence)
    _require(len(json.dumps(evidence, ensure_ascii=True, allow_nan=False).encode()) <= _MAX_BYTES)
    scope = validate_scientific_scope(evidence['scope'])
    _require(scope == validate_scientific_scope(expected_scope)
             and receipt['originTaskId'] == scope['originChildTaskId']
             and receipt['manifestHash'] == scope['sourceManifestSha256'])
    _id(receipt['id']); _owner(receipt['remoteOwnerId'])
    for key in ('remoteTaskId', 'remotePlanId', 'remoteRunId'):
        if receipt.get(key) is not None:
            _id(receipt[key])
    lease, launch, checkpoint, evaluation, preparation = (evidence[key] for key in
        ('lease', 'launchProof', 'checkpoint', 'evaluation', 'preparation'))
    if preparation is not None:
        _keys(preparation, {'schema', 'artifactId', 'artifactSha256'} | _EXECUTION)
        _schema(preparation); _id(preparation['artifactId']); _hash(preparation['artifactSha256'])
        _execution({key: preparation[key] for key in _EXECUTION})
        _require(preparation['ownerId'] == receipt['remoteOwnerId'])
    if scope['phase'] == 'preparation':
        _require(all(value is None for value in (lease, launch, checkpoint, evaluation)))
        return deepcopy(evidence)
    if lease is None:
        _require(all(value is None for value in (launch, checkpoint, evaluation)))
        return deepcopy(evidence)
    _lease(receipt, lease, scope)
    if checkpoint is not None:
        _checkpoint(checkpoint, scope)
        _require(checkpoint['ownerId'] == receipt['remoteOwnerId'])
        if scope['phase'] == 'training':
            _completed(lease)
            _matches_execution({key: checkpoint[key] for key in _EXECUTION}, lease)
            _require(launch is not None)
    if launch is not None:
        _launch(launch, lease, scope, checkpoint)
    if evaluation is not None:
        _require(scope['phase'] == 'evaluation' and launch is not None and checkpoint is not None)
        _evaluation(evaluation, lease, scope, checkpoint, launch)
    return deepcopy(evidence)


def _no_dispatch(receipt, evidence):
    proof = receipt.get('scientificNoDispatch')
    if proof is None:
        return None
    _keys(proof, {'schema', 'scopeSha256', 'receiverTaskId', 'receiverPlanId', 'receiverNativeRunId'})
    _schema(proof); _hash(proof['scopeSha256'])
    _require(evidence['scope']['phase'] in ('training', 'evaluation')
             and proof['scopeSha256'] == digest(evidence['scope'])
             and all(evidence[key] is None for key in ('lease', 'launchProof', 'checkpoint', 'evaluation')))
    for key, field in (('receiverTaskId', 'remoteTaskId'), ('receiverPlanId', 'remotePlanId'), ('receiverNativeRunId', 'remoteRunId')):
        _id(proof[key]); _require(proof[key] == receipt[field])
    _require(not (receipt.get('processLeases') or {}).get('leases'))
    return proof


def validate_scientific_evidence(receipt, *, expected_scope, previous=None):
    """Validate supplied shape and original identity, not peer trust or native terminal state."""
    try:
        evidence = _validated(receipt, expected_scope)
        no_dispatch = _no_dispatch(receipt, evidence)
        if previous is not None:
            old = _validated(previous, expected_scope)
            old_no_dispatch = _no_dispatch(previous, old)
            if old_no_dispatch is not None:
                _require(no_dispatch == old_no_dispatch)
            if no_dispatch is not None:
                _require(old['lease'] is None and all(old[key] is None for key in ('launchProof', 'checkpoint', 'evaluation'))
                         and not (previous.get('processLeases') or {}).get('leases'))
            for key in (*_RECEIPT_IDS, 'manifestHash'):
                if previous.get(key) is not None:
                    _require(receipt.get(key) == previous[key])
            prior, current = old['lease'], evidence['lease']
            validate_process_evidence(_base_receipt(receipt, current), _base_receipt(previous, prior))
            if prior is not None:
                _require(current is not None)
                for key in _EXTRA - {'gpuEvidence'}:
                    _require(current[key] == prior[key])
                if prior['gpuEvidence'] is not None:
                    _require(current['gpuEvidence'] is not None)
                    validate_gpu_evidence(prior, {**current, 'released': current['state'] == 'RECLAIMED'})
            for key in ('launchProof', 'checkpoint', 'evaluation', 'preparation'):
                if old[key] is not None:
                    _require(evidence[key] == old[key])
        return evidence
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def project_scientific_evidence(receipt, *, scope, lease=None, launch_proof=None,
                                checkpoint=None, evaluation=None, preparation=None):
    """Project trusted original records only; never look up or authenticate a source."""
    try:
        projected = None
        if lease is not None:
            projected = project_process_evidence([lease])['leases'][0]
            projected.update({key: deepcopy(lease[key]) for key in _EXTRA - {'gpuEvidence'}})
            # A durable reservation exists before any provider observation.
            # Only absent observation is optional; immutable GPU binding is not.
            projected['gpuEvidence'] = deepcopy(lease.get('gpuEvidence'))
        evidence = {'schema': 1, 'scope': deepcopy(scope), 'lease': projected,
                    'launchProof': deepcopy(launch_proof), 'checkpoint': deepcopy(checkpoint),
                    'evaluation': deepcopy(evaluation), 'preparation': deepcopy(preparation)}
        return validate_scientific_evidence({**receipt, 'scientificEvidence': evidence}, expected_scope=scope)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def scientific_stopped(receipt, *, expected_scope):
    """Positive process/GPU stop or CAS no-dispatch proof; native terminal still required."""
    evidence = validate_scientific_evidence(receipt, expected_scope=expected_scope)
    return _no_dispatch(receipt, evidence) is not None or _released(evidence['lease'])


def scientific_native_stopped(receipt):
    """Exact original queue AND persisted-run terminal evidence, never a grant."""
    try:
        native = receipt['native']; queue = native['queue']
        if type(native) is not dict or type(queue) is not dict or native.get('detailUnavailable'):
            return False
        expected = {'run_id': receipt['remoteRunId'], 'session_id': receipt['remoteTaskId'],
                    'user_id': receipt['remoteOwnerId']}
        for key, value in expected.items():
            _id(value)
            queue_key = 'id' if key == 'run_id' else key
            if native.get(key) != value or queue.get(queue_key) != value:
                return False
        if (native.get('agent_id') != 'factory-executor' or queue.get('component_id') != 'factory-executor'
                or queue.get('component_type') != 'agent'):
            return False
        terminal = {'completed', 'failed', 'error', 'cancelled', 'canceled'}
        for status in (native.get('status'), queue.get('status')):
            if type(status) is not str or status.lower().removeprefix('runstatus.') not in terminal:
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False

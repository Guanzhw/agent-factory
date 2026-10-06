"""Pure independent-evaluator contracts, not evaluator custody or execution proof.

Only the lifecycle service can establish which configured process produced bytes.
Even valid evaluator-shaped training stdout remains untrusted after these checks.
"""
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from .research_assessment import assess_observations
from .research_manifest import manifest_fingerprint, validate_manifest

_ERROR = 'RESEARCH_EVALUATION_INVALID'
_EXECUTION = 'ownerId taskId nativeRunId planId planFingerprint leaseId providerJobId'


def _require(condition):
    if not condition:
        raise ValueError(_ERROR)


def _keys(value, fields):
    _require(type(value) is dict and all(type(key) is str for key in value) and set(value) == set(fields.split()))


def _hash(value):
    _require(type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None)


def _id(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value) is not None)


def _owner(value):
    _require(type(value) is str and 1 <= len(value) <= 200
        and all(ord(character) >= 32 and ord(character) != 127 for character in value))


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()


def validate_evaluation_contract(value: Any) -> dict[str, Any]:
    """Bind two distinct declared executions and a bounded checkpoint reference.

    No ID, hash, completion, artifact bytes or operator identity is authenticated
    here. The returned contract is a detached value with a reproducible digest.
    """
    try:
        _keys(value, 'schema evidenceKind comparisonManifest training evaluatorExecution')
        _require(type(value['schema']) is int and value['schema'] == 1)
        _require(type(value['evidenceKind']) is str and value['evidenceKind'] == 'offline_research_evaluation_contract')
        manifest = validate_manifest(value['comparisonManifest'])
        training, evaluator = value['training'], value['evaluatorExecution']
        _keys(training, _EXECUTION + ' variantSha256 checkpoint')
        _keys(evaluator, _EXECUTION)
        for execution in (training, evaluator):
            for field in _EXECUTION.split():
                (_hash if field == 'planFingerprint' else _owner if field == 'ownerId' else _id)(execution[field])
        _require(training['ownerId'] == evaluator['ownerId'])
        for field in ('taskId', 'nativeRunId', 'leaseId', 'providerJobId'):
            _require(training[field] != evaluator[field])
        _hash(training['variantSha256'])
        checkpoint = training['checkpoint']
        _keys(checkpoint, 'artifactId sha256 sizeBytes')
        _id(checkpoint['artifactId'])
        _hash(checkpoint['sha256'])
        _require(type(checkpoint['sizeBytes']) is int and 0 < checkpoint['sizeBytes'] <= manifest['artifactLimits']['checkpointBytes'])
        return deepcopy(value)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError(_ERROR) from None


def evaluation_contract_fingerprint(value: Any) -> str:
    return _fingerprint(validate_evaluation_contract(value))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError(_ERROR)


def validate_evaluator_output(contract: Any, raw: bytes) -> dict[str, Any]:
    """Parse bounded exact JSON into an unverified PR35-compatible observation.

    A caller supplying candidate stdout gets no execution attestation. Root's
    service must independently resolve and read the original evaluator process.
    """
    checked = validate_evaluation_contract(contract)
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= checked['comparisonManifest']['artifactLimits']['resultBytes'])
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        _keys(value, 'schema evaluationContractSha256 status metric')
        _require(type(value['schema']) is int and value['schema'] == 1)
        _hash(value['evaluationContractSha256'])
        _require(value['evaluationContractSha256'] == _fingerprint(checked))
        _keys(value['metric'], 'id value')
        _require(type(value['metric']['id']) is str and value['metric']['id'] == 'val_bpb')
        observation = {'schema': 1, 'status': value['status'],
            'comparisonIdentitySha256': manifest_fingerprint(checked['comparisonManifest']),
            'variantSha256': checked['training']['variantSha256'], 'valBpb': value['metric']['value']}
        # Reuse the exact observation schema, including nonzero crash-sentinel
        # rejection. This comparison is validation only; discard its advice.
        assess_observations(observation, observation)
        return {'schema': 1, 'evidenceKind': 'offline_evaluator_output',
            'evaluationContractSha256': _fingerprint(checked), 'observation': observation,
            'rawSha256': hashlib.sha256(raw).hexdigest(),
            'executionVerified': False, 'scientificConclusionVerified': False}
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None

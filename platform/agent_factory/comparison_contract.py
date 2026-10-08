"""Inert baseline/candidate contracts; never executes or authorizes workloads."""
from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, cast

_ERROR = "COMPARISON_CONTRACT_INVALID"


def _require(value):
    if not value:
        raise ValueError(_ERROR)


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names.split()))


def _hash(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _identifier(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", value) is not None


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and abs(value) <= 10**12


def _path(value):
    return (type(value) is str and 1 <= len(value) <= 160 and all(
        part not in {"", ".", ".."} and re.fullmatch(r"[A-Za-z0-9_.-]+", part)
        for part in value.split("/")))


def fingerprint(value):
    """Canonical inert JSON digest; no external byte verification is implied."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _files(value):
    _require(type(value) is dict and 1 <= len(value) <= 30)
    _require(all(_path(path) and _hash(digest) for path, digest in value.items()))


def validate_contract(value):
    """Validate predeclared scope; this is neither publication nor plan approval."""
    try:
        _keys(value, "schema evidenceKind dataset evaluator baselineFiles allowedChanges metric seed authority materialRefs")
        _require(type(value['schema']) is int and value['schema'] == 1 and value['evidenceKind'] == 'offline_comparison_contract')
        dataset, evaluator = value['dataset'], value['evaluator']
        _keys(dataset, 'path sha256 origin license sampleSetSha256 sampleCount')
        _require(_path(dataset['path']) and _hash(dataset['sha256']) and _hash(dataset['sampleSetSha256']))
        _require(dataset['origin'] in {'public', 'synthetic'} and _identifier(dataset['license']))
        _require(_integer(dataset['sampleCount'], 1, 10000))
        _keys(evaluator, 'path sha256 protocolRevision')
        _require(_path(evaluator['path']) and _hash(evaluator['sha256']) and _identifier(evaluator['protocolRevision']))
        _require(dataset['path'] != evaluator['path'])
        _files(value['baselineFiles'])
        _require(all(value['baselineFiles'].get(item['path']) == item['sha256'] for item in (dataset, evaluator)))
        changes = value['allowedChanges']
        _require(type(changes) is list and 1 <= len(changes) <= 20 and all(_path(path) for path in changes))
        _require(len(set(changes)) == len(changes) and set(changes) <= set(value['baselineFiles'])
                 and not {dataset['path'], evaluator['path']} & set(changes))
        metric = value['metric']
        _keys(metric, 'id unit direction minimumImprovement')
        _require(_identifier(metric['id']) and _identifier(metric['unit']) and metric['direction'] in {'minimize', 'maximize'})
        _require(_number(metric['minimumImprovement']) and metric['minimumImprovement'] >= 0)
        _require(_integer(value['seed'], 0, 2**31 - 1))
        authority = value['authority']
        _keys(authority, 'planFingerprint capabilities resourceLimits')
        _require(_hash(authority['planFingerprint']))
        capabilities = authority['capabilities']
        _require(type(capabilities) is list and len(capabilities) <= 30 and all(_identifier(item) for item in capabilities)
                 and len(set(capabilities)) == len(capabilities))
        limits = authority['resourceLimits']
        _keys(limits, 'cpu memoryMb wallSeconds outputBytes')
        for key, maximum in (('cpu', 64), ('memoryMb', 196608), ('wallSeconds', 3600), ('outputBytes', 10485760)):
            _require(_integer(limits[key], 1, maximum))
        refs: list[dict[str, Any]] = value['materialRefs']
        _require(type(refs) is list and 1 <= len(refs) <= 30)
        refs = cast(list[dict[str, Any]], refs)
        for ref in refs:
            _keys(ref, 'id version sha256')
            _require(_identifier(ref['id']) and _integer(ref['version'], 1, 2**31 - 1) and _hash(ref['sha256']))
        _require(len({(ref['id'], ref['version']) for ref in refs}) == len(refs))
        return deepcopy(value)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError(_ERROR) from None


def validate_candidate(contract, candidate):
    """Only reviewed existing file replacements; authority and data cannot change."""
    original = validate_contract(contract)
    try:
        _keys(candidate, 'schema contractSha256 authoritySha256 files')
        _require(type(candidate['schema']) is int and candidate['schema'] == 1)
        _require(candidate['contractSha256'] == fingerprint(original)
                 and candidate['authoritySha256'] == fingerprint(original['authority']))
        _files(candidate['files'])
        _require(set(candidate['files']) == set(original['baselineFiles']))
        changed = {name for name, digest in candidate['files'].items() if digest != original['baselineFiles'][name]}
        _require(changed <= set(original['allowedChanges']))
        return deepcopy(candidate)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError(_ERROR) from None


def _observation(contract, value, files):
    _keys(value, 'schema contractSha256 variantSha256 datasetSha256 evaluatorSha256 sampleSetSha256 sampleCount seed metricId unit status value resultSha256')
    _require(type(value['schema']) is int and value['schema'] == 1)
    expected = {'contractSha256': fingerprint(contract), 'variantSha256': fingerprint(files),
                'datasetSha256': contract['dataset']['sha256'], 'evaluatorSha256': contract['evaluator']['sha256'],
                'sampleSetSha256': contract['dataset']['sampleSetSha256'], 'seed': contract['seed'],
                'metricId': contract['metric']['id'], 'unit': contract['metric']['unit']}
    _require(all(type(value[key]) is type(item) and value[key] == item for key, item in expected.items()))
    _require(value['status'] in {'completed', 'failed', 'cancelled', 'unknown'} and _hash(value['resultSha256']))
    _require(_integer(value['sampleCount'], 0, contract['dataset']['sampleCount']))
    if value['status'] == 'completed':
        _require(value['sampleCount'] == contract['dataset']['sampleCount'] and _number(value['value']))
    else:
        _require(value['value'] is None)


def compare_observations(contract, candidate, baseline_result, candidate_result):
    """Descriptive one-metric comparison of supplied records, not execution proof."""
    original = validate_contract(contract)
    proposed = validate_candidate(original, candidate)
    try:
        _observation(original, baseline_result, original['baselineFiles'])
        _observation(original, candidate_result, proposed['files'])
        reasons = [side.upper() + '_' + result['status'].upper()
                   for side, result in (('baseline', baseline_result), ('candidate', candidate_result))
                   if result['status'] != 'completed']
        output = {'schema': 1, 'evidenceKind': 'offline_comparison_assessment',
                  'contractSha256': fingerprint(original), 'candidateSha256': fingerprint(proposed),
                  'status': 'inconclusive', 'improvement': None, 'metric': deepcopy(original['metric']),
                  'reasons': reasons, 'executionVerified': False, 'scientificConclusionVerified': False}
        if reasons:
            return output
        delta = candidate_result['value'] - baseline_result['value']
        if original['metric']['direction'] == 'minimize':
            delta = -delta
        threshold = original['metric']['minimumImprovement']
        return {**output, 'status': 'improved' if delta > threshold else 'regressed' if delta < -threshold else 'unchanged',
                'improvement': delta}
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError(_ERROR) from None

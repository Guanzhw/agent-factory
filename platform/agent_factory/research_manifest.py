"""Inert, versioned comparison identities for the pinned autoresearch protocol.

Hashes of externally supplied artifacts and baseline manifests are declarations,
not proofs of their bytes, upstream authenticity, installation or execution.
Only artifact_identity hashes supplied bytes; it is not a large-file verifier.
Candidate source and output checkpoints belong to run records, not this identity.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, cast

from .research_profile import SOURCE_SHA256, source_profile

_ERROR = 'RESEARCH_MANIFEST_INVALID'
MAX_INLINE_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 2**40
MAX_DATASET_BYTES = 2**44
EVALUATION_BUDGET_TOKENS = 40 * 524288
SEQUENCE_LENGTH = 2048


def _require(value: bool) -> None:
    if not value:
        raise ValueError(_ERROR)


def _keys(value: Any, keys: str) -> None:
    _require(type(value) is dict and all(type(key) is str for key in value) and set(value) == set(keys.split()))


def _integer(value: Any, minimum: int, maximum: int) -> None:
    _require(type(value) is int and minimum <= value <= maximum)


def _hash(value: Any) -> None:
    _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None)


def _token(value: Any) -> None:
    _require(type(value) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value) is not None)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                                     allow_nan=False).encode('ascii')).hexdigest()


def _artifact(value: Any) -> None:
    _keys(value, 'sha256 sizeBytes')
    _hash(value['sha256'])
    _integer(value['sizeBytes'], 0, MAX_ARTIFACT_BYTES)


def artifact_identity(raw: bytes) -> dict[str, Any]:
    """Hash at most 16 MiB of supplied bytes without reading paths or loading data."""
    _require(type(raw) is bytes and len(raw) <= MAX_INLINE_BYTES)
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}


def validate_manifest(value: Any) -> dict[str, Any]:
    """Validate exact inert fields; preserve shard order and return detached data."""
    _keys(value, 'schema evidenceKind sourceProfileSha256 baselineSourceManifestSha256 protocol dataset tokenizer environment device evaluator initialCheckpoint artifactLimits')
    _integer(value['schema'], 1, 1)
    _require(type(value['evidenceKind']) is str and value['evidenceKind'] == 'offline_research_experiment_manifest')
    _hash(value['sourceProfileSha256'])
    _require(value['sourceProfileSha256'] == _digest(source_profile()))
    _hash(value['baselineSourceManifestSha256'])
    protocol = value['protocol']
    _keys(protocol, 'revision trainingBudgetSeconds totalWallSeconds seed evaluationBudgetTokens sequenceLength')
    _token(protocol['revision'])
    _integer(protocol['trainingBudgetSeconds'], 300, 300)
    _integer(protocol['totalWallSeconds'], 301, 86400)
    _integer(protocol['seed'], 0, 2**31 - 1)
    _integer(protocol['evaluationBudgetTokens'], EVALUATION_BUDGET_TOKENS, EVALUATION_BUDGET_TOKENS)
    _integer(protocol['sequenceLength'], SEQUENCE_LENGTH, SEQUENCE_LENGTH)
    dataset = value['dataset']
    _keys(dataset, 'revision shards validationShardIds sampleSetSha256')
    _token(dataset['revision'])
    _hash(dataset['sampleSetSha256'])
    shards = dataset['shards']
    _require(type(shards) is list and 1 <= len(shards) <= 1024)
    ids: set[str] = set()
    total = 0
    for shard in cast(list[dict[str, Any]], shards):
        _keys(shard, 'id sha256 sizeBytes')
        _token(shard['id'])
        _require(shard['id'] not in ids)
        ids.add(shard['id'])
        _hash(shard['sha256'])
        _integer(shard['sizeBytes'], 1, MAX_ARTIFACT_BYTES)
        total += shard['sizeBytes']
        _require(total <= MAX_DATASET_BYTES)
    validation = dataset['validationShardIds']
    _require(type(validation) is list and 1 <= len(validation) <= len(shards))
    selected: set[str] = set()
    for identifier in validation:
        _token(identifier)
        _require(identifier in ids and identifier not in selected)
        selected.add(cast(str, identifier))
    tokenizer = value['tokenizer']
    _keys(tokenizer, 'tokenizer tokenBytes')
    for artifact in tokenizer.values():
        _artifact(artifact)
    environment = value['environment']
    _keys(environment, 'lockfileSha256 installedInventory runtimeKernel')
    _hash(environment['lockfileSha256'])
    _require(environment['lockfileSha256'] == SOURCE_SHA256['uv.lock'])
    _artifact(environment['installedInventory'])
    _artifact(environment['runtimeKernel'])
    device = value['device']
    _keys(device, 'identitySha256 deviceCount')
    _hash(device['identitySha256'])
    _integer(device['deviceCount'], 1, 1)
    evaluator = value['evaluator']
    _keys(evaluator, 'code configuration metric direction')
    _artifact(evaluator['code'])
    _artifact(evaluator['configuration'])
    _require(type(evaluator['metric']) is str and evaluator['metric'] == 'val_bpb'
             and type(evaluator['direction']) is str and evaluator['direction'] == 'minimize')
    if value['initialCheckpoint'] is not None:
        _artifact(value['initialCheckpoint'])
    limits = value['artifactLimits']
    _keys(limits, 'checkpointBytes logBytes resultBytes')
    for name, bound in (('checkpointBytes', MAX_ARTIFACT_BYTES), ('logBytes', 64 * 1024 * 1024), ('resultBytes', 1024 * 1024)):
        _integer(limits[name], 1, bound)
    if value['initialCheckpoint'] is not None:
        _require(value['initialCheckpoint']['sizeBytes'] <= limits['checkpointBytes'])
    return deepcopy(value)


def manifest_fingerprint(value: Any) -> str:
    """Hash the complete validated comparison identity, never a candidate source."""
    return _digest(validate_manifest(value))


def same_comparison_identity(left: Any, right: Any) -> bool:
    return manifest_fingerprint(left) == manifest_fingerprint(right)

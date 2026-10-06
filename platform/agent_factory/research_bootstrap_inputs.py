"""Read-only operator input capture; no training, source execution or task creation.

Paths and preparation bindings in the return value are private operator data.
Hashing bounds: 2 GiB/file, 16 GiB total, 1024 shards, 120 s cooperative deadline.
This captures bytes, not dataset semantics, GPU availability or environment admission.
The caller keeps approved inputs stable until the existing launch fences recheck.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from typing import cast

from .gpu_custody import GpuBinding
from .process_enforcement import ResearchProcessLimits
from .research_checkpoint import _flags, _root, _stamp, checkpoint_binding
from .research_local_driver import derive_local_identities
from .research_manifest import manifest_fingerprint, validate_manifest
from .research_profile import SOURCE_SHA256, source_profile, verify_upstream_source
from .research_staging import FilePin, InputPin
from .research_torch_runtime import decode_tokenizer_json

ERROR = 'RESEARCH_BOOTSTRAP_INPUT_INVALID'
MAX_FILE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 16 * 1024**3
MAX_TOKENIZER_BYTES = 1024**2
MAX_CAPTURE_SECONDS = 120


def _require(value):
    if not value:
        raise ValueError(ERROR)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()


def _artifact(row):
    return {key: row[key] for key in ('sha256', 'sizeBytes')}


def capture_bootstrap_inputs(*, input_root, tokenizer_basename, shards, validation_ids,
        upstream_files, environment_pins, gpu_binding, limits, token_bytes_pin,
        microbatch=1, dataset_revision='operator-local-v1'):
    """Return strict schema2 comparisonManifest and six-key LocalDriver inputs.

    token_bytes_pin must originate from ResearchPreparationStore.input_pin; its
    original nine-field binding is validated and retained in the runtime pin, never minted.
    This read-only function cannot authenticate who supplied that internal pin.
    """
    try:
        return _capture(input_root, tokenizer_basename, shards, validation_ids, upstream_files,
            environment_pins, gpu_binding, limits, token_bytes_pin, microbatch, dataset_revision)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def _capture(input_root, tokenizer_basename, shards, validation_ids, upstream_files,
             environment_pins, gpu_binding, limits, token_bytes_pin, microbatch, dataset_revision):
    _require(type(gpu_binding) is GpuBinding and type(limits) is ResearchProcessLimits)
    _require(type(microbatch) is int and 1 <= microbatch <= 128 and 128 % microbatch == 0)
    _require(type(shards) is tuple and 2 <= len(shards) <= 1024
             and all(type(row) is tuple and len(row) == 2 for row in shards))
    _require(type(validation_ids) is tuple and all(type(v) is str for v in validation_ids)
             and len(set(validation_ids)) == len(validation_ids))
    _require(type(limits.wall_seconds) in {int, float} and limits.wall_seconds == int(limits.wall_seconds)
             and 301 <= limits.wall_seconds <= 86400)
    verify_upstream_source(upstream_files)
    _require(type(environment_pins) is tuple and all(type(p) is InputPin and p.kind == 'environment' for p in environment_pins))
    environment_pins = cast(tuple[InputPin, ...], environment_pins)
    shards = cast(tuple[tuple[str, str], ...], shards)
    env = {p.label: p for p in environment_pins}
    _require(len(env) == len(environment_pins) == 3 and set(env) ==
             {'environment-inventory', 'environment-kernel', 'environment-lockfile'})
    _require(type(token_bytes_pin) is dict and set(token_bytes_pin) ==
             {'root', 'basename', 'rootIdentity', 'binding', 'sha256', 'sizeBytes'})
    binding = checkpoint_binding(token_bytes_pin['binding'])
    deadline, total = time.monotonic() + MAX_CAPTURE_SECONDS, 0
    observations = []

    def root(path, expected=None):
        _require(isinstance(path, (str, Path)))
        path = Path(path)
        _require(path.is_absolute() and '..' not in path.parts)
        initial = os.stat(path, follow_symlinks=False)
        identity = {'device': initial.st_dev, 'inode': initial.st_ino}
        _require(expected is None or (type(expected) is dict and set(expected) == {'device', 'inode'}
                 and all(type(v) is int for v in expected.values()) and expected == identity))
        fd = _root(path, identity)
        return str(path), identity, fd

    def read(path, basename, expected_root=None, expected=None, *, collect=False):
        nonlocal total
        _require(type(basename) is str)
        # Reuse the staging basename grammar and maximum; do not interpret paths.
        FilePin(basename, '0' * 64, 1)
        path, identity, fd = root(path, expected_root)
        handle = None
        try:
            nofollow, _, nonblock = _flags()
            root_stamp = _stamp(os.fstat(fd))
            handle = os.open(basename, os.O_RDONLY | nofollow | nonblock, dir_fd=fd)
            info = os.fstat(handle)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == getattr(os, 'getuid')()
                     and info.st_dev == os.fstat(fd).st_dev and
                     stat.S_IMODE(info.st_mode) == 0o600)
            _require(0 < info.st_size <= (MAX_TOKENIZER_BYTES if collect else MAX_FILE_BYTES))
            total += info.st_size
            _require(total <= MAX_TOTAL_BYTES)
            if expected is not None:
                _require(type(expected['sizeBytes']) is int and expected['sizeBytes'] == info.st_size)
            remaining, hasher, chunks = info.st_size, hashlib.sha256(), []
            while remaining:
                _require(time.monotonic() < deadline)
                chunk = os.read(handle, min(1024**2, remaining))
                _require(bool(chunk))
                remaining -= len(chunk)
                hasher.update(chunk)
                if collect:
                    chunks.append(chunk)
            _require(os.read(handle, 1) == b'' and _stamp(os.fstat(handle)) == _stamp(info)
                     and _stamp(os.stat(basename, dir_fd=fd, follow_symlinks=False)) == _stamp(info))
            row = {'basename': basename, 'sha256': hasher.hexdigest(), 'sizeBytes': info.st_size}
            _require(expected is None or _artifact(row) == expected)
            observations.append((path, identity, root_stamp, basename, _stamp(info)))
            return row, identity, b''.join(chunks)
        finally:
            if handle is not None:
                os.close(handle)
            os.close(fd)

    tokenizer, root_identity, raw = read(input_root, tokenizer_basename, collect=True)
    decode_tokenizer_json(raw)
    ids = [row[0] for row in shards]
    basenames = [row[1] for row in shards]
    _require(all(type(v) is str for v in ids + basenames) and len(set(ids)) == len(ids)
             and len(set(basenames)) == len(basenames) and tokenizer_basename not in basenames
             and 0 < len(validation_ids) < len(ids) and set(validation_ids) <= set(ids))
    rows = []
    for identifier, basename in shards:
        row, _, _ = read(input_root, basename, root_identity)
        rows.append({'id': identifier, **row})
    validation = set(validation_ids)
    _require(not {row['sha256'] for row in rows if row['id'] in validation} &
             {row['sha256'] for row in rows if row['id'] not in validation})
    token, token_root, _ = read(token_bytes_pin['root'], token_bytes_pin['basename'],
        token_bytes_pin['rootIdentity'], _artifact(token_bytes_pin))
    observed_env = {}
    for label, pin in env.items():
        row, _, _ = read(pin.root, pin.file.basename, asdict(pin.root_identity),
            {'sha256': pin.file.sha256, 'sizeBytes': pin.file.size_bytes})
        observed_env[label] = row
    derived = derive_local_identities(upstream_files, upstream_files, microbatch=microbatch)
    identities = derived['identities']
    manifest_shards = [{'id': row['id'], **_artifact(row)} for row in rows]
    sample = {'schema': 1, 'shards': manifest_shards, 'validationShardIds': list(validation_ids)}
    manifest = validate_manifest({'schema': 2, 'evidenceKind': 'offline_research_experiment_manifest',
        'sourceProfileSha256': _digest(source_profile()),
        'baselineSourceManifestSha256': identities['baseline']['sha256'],
        'protocol': {'revision': 'local-sdpa-baseline-v1', 'trainingBudgetSeconds': 300,
            'totalWallSeconds': int(limits.wall_seconds), 'seed': 42,
            'evaluationBudgetTokens': 20971520, 'sequenceLength': 2048},
        'dataset': {'revision': dataset_revision, 'shards': manifest_shards,
            'validationShardIds': list(validation_ids), 'sampleSetSha256': _digest(sample)},
        'tokenizer': {'tokenizer': _artifact(tokenizer), 'tokenBytes': _artifact(token)},
        'environment': {'lockfileSha256': observed_env['environment-lockfile']['sha256'],
            'upstreamLockfileSha256': SOURCE_SHA256['uv.lock'],
            'installedInventory': _artifact(observed_env['environment-inventory']),
            'runtimeKernel': _artifact(observed_env['environment-kernel'])},
        'device': {'identitySha256': gpu_binding.identity_key, 'deviceCount': 1},
        'evaluator': {'code': _artifact(identities['evaluatorCode']),
            'configuration': _artifact(identities['evaluatorConfiguration']), 'metric': 'val_bpb', 'direction': 'minimize'},
        'initialCheckpoint': None, 'artifactLimits': {'checkpointBytes': limits.file_size_bytes,
            'logBytes': limits.output_bytes, 'resultBytes': min(1024**2, limits.file_size_bytes)}})
    # Close the multi-file observation window after derivation, before return.
    for path, identity, directory_stamp, basename, file_stamp in observations:
        _require(time.monotonic() < deadline)
        fd = _root(path, identity)
        try:
            _require(_stamp(os.fstat(fd)) == directory_stamp and
                     _stamp(os.stat(basename, dir_fd=fd, follow_symlinks=False)) == file_stamp)
        finally:
            os.close(fd)
    return {'schema': 1, 'comparisonManifest': manifest, 'manifestSha256': manifest_fingerprint(manifest),
        'operatorInputs': {'inputRoot': str(Path(input_root)), 'inputRootIdentity': root_identity,
            'tokenizer': tokenizer, 'tokenBytes': {**token, 'root': token_bytes_pin['root'], 'rootIdentity': token_root, 'binding': deepcopy(binding)},
            'dataset': {'shards': rows, 'validationShardIds': list(validation_ids)}, 'outputCheckpoint': None},
        'tokenBytesPreparationBinding': binding, 'environmentPins': [asdict(pin) for pin in environment_pins],
        'adaptationReceipt': derived['adaptationReceipt'], 'executionVerified': False,
        'scientificConclusionVerified': False}

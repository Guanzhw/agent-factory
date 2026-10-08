"""Offline byte custody for a reviewed karpathy/autoresearch candidate.

This checks file changes, not Python semantics, training, upstream authenticity,
or whether train.py preserves the scientific evaluation protocol.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

REQUIRED_FILES = frozenset({'prepare.py', 'train.py', 'program.md', 'pyproject.toml', 'uv.lock'})
MAX_FILES = 256
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
_ERROR = 'RESEARCH_CANDIDATE_INVALID'
_COMPONENT = re.compile(r'[A-Za-z0-9_.-]{1,100}')
_RESERVED = frozenset({'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))})


def _require(value: bool) -> None:
    if not value:
        raise ValueError(_ERROR)


def _manifest(files: dict[str, bytes]) -> list[dict[str, Any]]:
    _require(type(files) is dict and len(REQUIRED_FILES) <= len(files) <= MAX_FILES)
    total = 0
    normalized: set[str] = set()
    for path, content in files.items():
        _require(type(path) is str and 0 < len(path) <= 240)
        parts = path.split('/')
        _require(all(_COMPONENT.fullmatch(part) is not None and part not in {'.', '..'}
                     and not part.endswith('.') and part.split('.')[0].casefold() not in _RESERVED for part in parts))
        folded = path.casefold()
        _require(folded not in normalized)
        normalized.add(folded)
        _require(type(content) is bytes and len(content) <= MAX_FILE_BYTES)
        total += len(content)
        _require(total <= MAX_TOTAL_BYTES)
    _require(REQUIRED_FILES <= files.keys())
    for path in normalized:
        parts = path.split('/')
        _require(not any('/'.join(parts[:index]) in normalized for index in range(1, len(parts))))
    return [{'path': path, 'sizeBytes': len(files[path]), 'sha256': hashlib.sha256(files[path]).hexdigest()}
            for path in sorted(files)]


def _fingerprint(manifest: list[dict[str, Any]]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    return hashlib.sha256(raw).hexdigest()


def validate_candidate_files(baseline: dict[str, bytes], candidate: dict[str, bytes]) -> dict[str, Any]:
    """Bind actual bounded bytes; reject every changed path except train.py.

    An unchanged candidate is valid. Additional baseline files are protected too.
    Callers must independently establish the trusted baseline and runtime checks.
    """
    baseline_manifest = _manifest(baseline)
    candidate_manifest = _manifest(candidate)
    _require(baseline.keys() == candidate.keys())
    changed = sorted(path for path in baseline if baseline[path] != candidate[path])
    _require(set(changed) <= {'train.py'})
    return {'schema': 1, 'evidenceKind': 'offline_candidate_validation',
            'allowedChanges': ['train.py'], 'changedFiles': changed,
            'baselineManifest': baseline_manifest, 'candidateManifest': candidate_manifest,
            'baselineManifestSha256': _fingerprint(baseline_manifest),
            'candidateManifestSha256': _fingerprint(candidate_manifest),
            'executionVerified': False, 'scientificConclusionVerified': False}

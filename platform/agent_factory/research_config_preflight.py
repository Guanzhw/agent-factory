"""Pure accumulated configuration diagnostics. Never emit the private config.

Only ``checks`` is a public report. ``config`` and ``validFields`` are internal
inputs for independently gated read-only probes, never execution authorization.
"""
import json
import math
from pathlib import PurePosixPath
import re
from typing import Any

KEYS = frozenset('schema ackLocalDevelopment ackTraining databaseUrlFile workspace requestId inputRoot '
    'tokenizerBasename shards validationIds upstreamRoot projectRoot venvRoot interpreterTarget '
    'interpreterSha256 approvedInterpreterRoots deviceUuid receiverNamespaceSha256 nvidiaSmi limits microbatch'.split())
PATHS = ('databaseUrlFile', 'workspace', 'inputRoot', 'upstreamRoot', 'projectRoot', 'venvRoot', 'interpreterTarget')
LIMITS = {'cpu_seconds': (1, 86400), 'address_space_mb': (32, 1048576),
    'file_size_bytes': (1024, 2 * 1024**3), 'wall_seconds': (301, 86400),
    'disk_bytes': (1, 8 * 1024**4), 'output_bytes': (1024, 64 * 1024**2)}
FIELDS = ('raw', 'json', 'config.fields', 'schema', 'ackLocalDevelopment', 'ackTraining', *PATHS,
    'requestId', 'tokenizerBasename', 'interpreterSha256', 'receiverNamespaceSha256', 'deviceUuid',
    'approvedInterpreterRoots', 'nvidiaSmi', 'nvidiaSmi.executable', 'nvidiaSmi.sha256',
    'limits', *(f'limits.{name}' for name in LIMITS), 'limits.outputBound', 'limits.diskReservation',
    'microbatch', 'shards', 'shards.rows', 'shards.ids', 'shards.basenames', 'validationIds',
    'validationIds.membership', 'tokenizerBasename.distinct')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON_DUPLICATE')
        result[key] = value
    return result


def _constant(_value):
    raise ValueError('JSON_NONFINITE')


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('JSON_NONFINITE')
    return result


def _path(value):
    return (type(value) is str and value.startswith('/')
        and str(PurePosixPath(value)) == value and '..' not in PurePosixPath(value).parts)


def _match(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _name(value):
    return _match(value, '[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}') and value not in {'.', '..'}


def config_preflight(raw):
    checks: dict[str, dict[str, Any]] = {field: {'field': field, 'code': 'DEPENDENCY_NOT_VALID', 'status': 'NOT_CHECKED'} for field in FIELDS}
    valid = set()

    def check(field, condition, code='FIELD_INVALID'):
        checks[field] = {'field': field, 'code': 'OK' if condition else code,
                         'status': 'PASS' if condition else 'BLOCKED'}
        if condition:
            valid.add(field)
        else:
            valid.discard(field)
        return bool(condition)

    def result(config):
        return {'checks': list(checks.values()), 'config': config, 'validFields': valid if config is not None else set()}

    if not check('raw', type(raw) is bytes and 0 < len(raw) <= 2 * 1024**2, 'RAW_INVALID'):
        return result(None)
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant, parse_float=_float)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        check('json', False, 'JSON_INVALID')
        return result(None)
    if not check('json', type(value) is dict, 'JSON_OBJECT_REQUIRED'):
        return result(None)
    check('config.fields', set(value) == KEYS, 'FIELD_SET_INVALID')

    def field(name, predicate):
        return check(name, name in value and predicate(value[name]), 'FIELD_MISSING' if name not in value else 'FIELD_INVALID')

    field('schema', lambda v: type(v) is int and v == 1)
    for name in ('ackLocalDevelopment', 'ackTraining'):
        field(name, lambda v: v is True)
    for name in PATHS:
        field(name, _path)
    field('requestId', lambda v: _match(v, '[A-Za-z0-9_.:-]{8,40}'))
    field('tokenizerBasename', _name)
    for name in ('interpreterSha256', 'receiverNamespaceSha256'):
        field(name, lambda v: _match(v, '[a-f0-9]{64}'))
    field('deviceUuid', lambda v: _match(v, 'GPU-[a-fA-F0-9-]{8,80}'))
    field('approvedInterpreterRoots', lambda v: type(v) is list and 1 <= len(v) <= 8 and all(_path(p) for p in v))
    if field('nvidiaSmi', lambda v: type(v) is dict):
        nvidia = value['nvidiaSmi']
        shape = check('nvidiaSmi', set(nvidia) == {'executable', 'sha256'}, 'FIELD_SET_INVALID')
        path_ok = check('nvidiaSmi.executable', type(nvidia.get('executable')) is str and PurePosixPath(nvidia['executable']).is_absolute())
        sha_ok = check('nvidiaSmi.sha256', _match(nvidia.get('sha256'), '[a-f0-9]{64}'))
        if not (shape and path_ok and sha_ok):
            valid.discard('nvidiaSmi')
    if field('limits', lambda v: type(v) is dict):
        limits = value['limits']
        shape = check('limits', set(limits) == set(LIMITS), 'FIELD_SET_INVALID')
        for name, (low, high) in LIMITS.items():
            number = limits.get(name)
            check('limits.' + name, type(number) is int and low <= number <= high, 'LIMIT_OUT_OF_RANGE')
            checks['limits.' + name].update(minimum=low, maximum=high)
        if {'limits.file_size_bytes', 'limits.output_bytes'} <= valid:
            check('limits.outputBound', limits['output_bytes'] <= limits['file_size_bytes'], 'OUTPUT_EXCEEDS_FILE_LIMIT')
        if {'limits.disk_bytes', 'limits.file_size_bytes', 'limits.output_bytes'} <= valid:
            check('limits.diskReservation', limits['disk_bytes'] >= 2 * limits['file_size_bytes'] + limits['output_bytes'], 'DISK_RESERVATION_TOO_SMALL')
        if not shape or not {field for field in FIELDS if field.startswith('limits.')} <= valid:
            valid.discard('limits')
    field('microbatch', lambda v: type(v) is int and 1 <= v <= 128 and 128 % v == 0)
    if field('shards', lambda v: type(v) is list and 2 <= len(v) <= 1024):
        rows = value['shards']
        if check('shards.rows', all(type(row) is dict and set(row) == {'id', 'basename'} for row in rows), 'SHARD_ROWS_INVALID'):
            ids = [row['id'] for row in rows]
            names = [row['basename'] for row in rows]
            check('shards.ids', all(_name(v) for v in ids) and len(set(ids)) == len(ids), 'SHARD_IDS_INVALID')
            check('shards.basenames', all(_name(v) for v in names) and len(set(names)) == len(names), 'SHARD_NAMES_INVALID')
        if not {'shards.rows', 'shards.ids', 'shards.basenames'} <= valid:
            valid.discard('shards')
    # Existing capture_bootstrap_inputs/_capture requires unique validation IDs,
    # unique shard basenames and a tokenizer basename distinct from all shards.
    field('validationIds', lambda v: type(v) is list and 1 <= len(v) <= 1024
          and all(_name(n) for n in v) and len(set(v)) == len(v))
    if {'validationIds', 'shards.ids'} <= valid:
        check('validationIds.membership', 0 < len(value['validationIds']) < len(value['shards'])
              and set(value['validationIds']) <= set(row['id'] for row in value['shards']), 'VALIDATION_SUBSET_INVALID')
        if 'validationIds.membership' not in valid:
            valid.discard('validationIds')
    if {'tokenizerBasename', 'shards.basenames'} <= valid:
        check('tokenizerBasename.distinct', value['tokenizerBasename'] not in [row['basename'] for row in value['shards']], 'INPUT_NAMES_OVERLAP')
    return result(value)

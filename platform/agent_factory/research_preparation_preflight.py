"""Pure bounded tokenizer diagnostics; never opens files or admits execution."""
import base64
import json
from typing import Any

from .research_preparation_harness import MAX_VOCAB, tokenizer_payload
from .research_torch_runtime import decode_tokenizer_json

MAX_INPUT_BYTES = 1024**2
MAX_CONFIG_BYTES = 2 * 1024**2
CONFIG_RESERVE_BYTES = 65536
_FIELDS = (
    'input_bytes', 'utf8', 'json', 'object_keys', 'schema', 'pattern',
    'ranks_type', 'ranks_count', 'rank_rows', 'rank_ids', 'token_encoding',
    'token_lengths', 'token_uniqueness', 'byte_coverage', 'specials_type',
    'specials_count', 'special_names', 'special_ids', 'reserved_token',
    'vocabulary_size', 'serialized_config_bound', 'decoder_authority', 'payload_authority',
)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _nonfinite(_):
    raise ValueError


def tokenizer_preflight(raw: object) -> dict[str, Any]:
    """Report all independent failures without returning any caller-controlled value.

    NOT_CHECKED means the prerequisite was unavailable, not that the field passed.
    Authority checks reuse the execution validators, including their output bounds.
    The config bound reserves the driver's fixed overhead; final reservation bytes
    and all filesystem/database/runtime checks remain outside this pure function.
    """
    checks = {field: {'field': field, 'status': 'NOT_CHECKED', 'code': 'DEPENDENCY_UNAVAILABLE'}
              for field in _FIELDS}

    def result(field, good):
        checks[field] = {'field': field, 'status': 'PASS' if good else 'BLOCKED',
                         'code': 'VALID' if good else field.upper() + '_INVALID'}

    def report():
        return {'schema': 1, 'kind': 'research-preparation-tokenizer-preflight',
                'status': 'PASS' if all(row['status'] == 'PASS' for row in checks.values()) else 'BLOCKED',
                'checks': list(checks.values()),
                'limits': {'inputBytes': MAX_INPUT_BYTES, 'configBytes': MAX_CONFIG_BYTES,
                           'configReserveBytes': CONFIG_RESERVE_BYTES, 'vocabularySize': MAX_VOCAB},
                'executionVerified': False}

    result('input_bytes', type(raw) is bytes and 0 < len(raw) <= MAX_INPUT_BYTES)
    if checks['input_bytes']['status'] != 'PASS':
        return report()
    assert type(raw) is bytes
    try:
        decoded = raw.decode('utf-8')
    except UnicodeError:
        result('utf8', False)
        return report()
    result('utf8', True)
    # Same ensure_ascii encoding as Store.canonical used by PreparationDriver.
    result('serialized_config_bound', len(json.dumps(decoded, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()) + CONFIG_RESERVE_BYTES <= MAX_CONFIG_BYTES)
    try:
        value = json.loads(decoded, object_pairs_hook=_unique, parse_constant=_nonfinite)
    except (ValueError, TypeError, RecursionError):
        result('json', False)
        return report()
    result('json', True)
    result('object_keys', type(value) is dict and set(value) == {
        'schema', 'pat_str', 'mergeable_ranks', 'special_tokens'})
    if type(value) is dict:
        result('schema', type(value.get('schema')) is int and value['schema'] == 1)
        pattern = value.get('pat_str')
        result('pattern', type(pattern) is str and 0 < len(pattern) <= 16384)
        rows, specials = value.get('mergeable_ranks'), value.get('special_tokens')
        result('ranks_type', type(rows) is list)
        result('specials_type', type(specials) is dict)
        tokens = []
        if type(rows) is list:
            result('ranks_count', 1 <= len(rows) <= 131072)
            shaped = all(type(row) is list and len(row) == 2 for row in rows)
            result('rank_rows', shaped)
            if shaped:
                result('rank_ids', all(type(row[1]) is int and row[1] == index for index, row in enumerate(rows)))
                encoding_ok = True
                for row in rows:
                    if type(row[0]) is not str:
                        encoding_ok = False
                        continue
                    try:
                        token = base64.b64decode(row[0], validate=True)
                    except (ValueError, TypeError):
                        encoding_ok = False
                        continue
                    if base64.b64encode(token).decode('ascii') != row[0]:
                        encoding_ok = False
                    tokens.append(token)
                result('token_encoding', encoding_ok)
                if encoding_ok:
                    result('token_lengths', all(0 < len(token) <= 65536 for token in tokens))
                    result('token_uniqueness', len(set(tokens)) == len(tokens))
                    result('byte_coverage', set(bytes([byte]) for byte in range(256)) <= set(tokens))
        if type(specials) is dict:
            result('specials_count', 1 <= len(specials) <= 256)
            result('special_names', all(type(name) is str and 0 < len(name) <= 256 for name in specials))
            result('reserved_token', '<|reserved_0|>' in specials)
            if type(rows) is list:
                result('special_ids', all(type(number) is int for number in specials.values())
                       and set(specials.values()) == set(range(len(rows), len(rows) + len(specials))))
        if type(rows) is list and type(specials) is dict:
            result('vocabulary_size', len(rows) + len(specials) <= MAX_VOCAB)
    try:
        decode_tokenizer_json(raw)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        result('decoder_authority', False)
    else:
        result('decoder_authority', True)
        try:
            tokenizer_payload(raw)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
            result('payload_authority', False)
        else:
            result('payload_authority', True)
    return report()

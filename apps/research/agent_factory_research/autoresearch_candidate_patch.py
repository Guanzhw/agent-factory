"""Bounded eleven-parameter edits; parse bytes only, never execute research code."""
import ast
import math

from .research_training_adapter import ALLOWED_PARAMETERS, _source, _assignments, _validate_values

ERROR = 'AUTORESEARCH_CANDIDATE_CHANGES_INVALID'


def require(value):
    if not value:
        raise ValueError(ERROR)


def _parsed(raw, microbatch):
    require(type(raw) is bytes and 0 < len(raw) <= 4 * 1024**2)
    require(type(microbatch) is int and 1 <= microbatch <= 128 and 128 % microbatch == 0)
    source, tree = _source(raw)
    values, _ = _assignments(source, tree)
    _validate_values(values, microbatch)
    return tree, values


def _numeric(value):
    require(type(value) in {int, float})
    try:
        require(math.isfinite(value))
    except OverflowError:
        raise ValueError(ERROR) from None
    return value


def build_candidate(raw: bytes, changes: dict, *, microbatch=1) -> str:
    """Replace only explicitly supplied original top-level literal expression bytes.

    AST columns are UTF-8 byte offsets, so slicing bytes preserves Unicode, CRLF,
    comments and every byte outside the chosen expressions. JSON beta arrays
    become Python tuples. Remaining protocol/range checks use the existing adapter.
    """
    tree, values = _parsed(raw, microbatch)
    require(type(changes) is dict and 1 <= len(changes) <= len(ALLOWED_PARAMETERS)
        and all(type(key) is str and key in ALLOWED_PARAMETERS for key in changes))
    original_values = dict(values)
    replacements = {}
    for name, proposed in changes.items():
        if name == 'ADAM_BETAS':
            require(type(proposed) is list and len(proposed) == 2)
            value = tuple(_numeric(item) for item in proposed)
        else:
            value = _numeric(proposed)
        values[name] = value
        replacements[name] = repr(value).encode('ascii')
    _validate_values(values, microbatch)
    require(any(name != 'DEVICE_BATCH_SIZE' and values[name] != original_values[name] for name in changes))
    starts = [0]
    for line in raw.splitlines(keepends=True): starts.append(starts[-1] + len(line))
    edits = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in replacements:
                expression = node.value
                require(expression.end_lineno is not None and expression.end_col_offset is not None)
                assert expression.end_lineno is not None and expression.end_col_offset is not None
                begin = starts[expression.lineno - 1] + expression.col_offset
                end = starts[expression.end_lineno - 1] + expression.end_col_offset
                edits.append((begin, end, replacements[name]))
    require(len(edits) == len(changes))
    result = raw
    for begin, end, replacement in sorted(edits, reverse=True):
        result = result[:begin] + replacement + result[end:]
    require(len(result) <= 4 * 1024**2)
    _parsed(result, microbatch)
    return result.decode('utf-8')


def parameter_context(raw: bytes, *, microbatch=1) -> dict:
    _, values = _parsed(raw, microbatch)
    current = {key: list(value) if type(value) is tuple else value for key, value in sorted(values.items())}
    return {'allowedParameters': sorted(ALLOWED_PARAMETERS), 'currentParameters': current,
        'candidateFormat': {'hypothesis': 'brief scientific reason', 'changes': 'nonempty subset of allowedParameters'},
        'instructions': ('Call research_candidate with hypothesis and changes, not full train.py. '
            'Use JSON numbers, never expressions or booleans. ADAM_BETAS uses a two-number JSON array. '
            'Only literal parameter spans are changed; architecture, loop and evaluation remain fixed.'),
        'approvedMicrobatch': microbatch}

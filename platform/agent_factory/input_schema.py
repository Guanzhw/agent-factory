"""Small deterministic application input schemas. No references or executable hooks."""
from copy import deepcopy
import json
import math
from typing import Any

ERROR = 'APPLICATION_INPUT_INVALID'


def require(value):
    if not value:
        raise ValueError(ERROR)


def bounded_json(value, *, maximum=65536):
    count = 0
    def walk(item, depth):
        nonlocal count
        count += 1
        require(depth <= 12 and count <= 4096)
        if type(item) is dict:
            require(len(item) <= 64 and all(type(k) is str and len(k) <= 100 for k in item))
            for child in item.values(): walk(child, depth + 1)
        elif type(item) is list:
            require(len(item) <= 256)
            for child in item: walk(child, depth + 1)
        elif type(item) is str:
            require(len(item) <= 16000)
        elif type(item) in (int, float):
            require(math.isfinite(item))
        else:
            require(item is None or type(item) is bool)
    try:
        walk(value, 0)
        require(len(json.dumps(value, allow_nan=False, ensure_ascii=True).encode()) <= maximum)
        return deepcopy(value)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def _matches(schema, value):
    kind = schema['type']
    if kind == 'object':
        require(type(value) is dict and not set(value) - set(schema['properties'])
                and set(schema.get('required', [])) <= set(value))
        for key, child in value.items(): _matches(schema['properties'][key], child)
    elif kind == 'array':
        require(type(value) is list and schema.get('minItems', 0) <= len(value) <= schema['maxItems'])
        for child in value: _matches(schema['items'], child)
    elif kind == 'string':
        require(type(value) is str and schema.get('minLength', 0) <= len(value) <= schema['maxLength'])
    elif kind in ('number', 'integer'):
        require(type(value) in ((int,) if kind == 'integer' else (int, float)) and math.isfinite(value))
        require(('minimum' not in schema or value >= schema['minimum']) and ('maximum' not in schema or value <= schema['maximum']))
    else:
        require((kind == 'boolean' and type(value) is bool) or (kind == 'null' and value is None))
    if 'enum' in schema:
        require(any(type(value) is type(item) and value == item for item in schema['enum']))


def validate_input_schema(schema):
    value = bounded_json(schema, maximum=32768)
    count = 0
    def node(item: dict[str, Any], depth: int):
        nonlocal count
        count += 1
        require(type(item) is dict and depth <= 6 and count <= 256)
        kind = item.get('type')
        allowed = {'object': {'properties', 'required', 'additionalProperties'},
            'array': {'items', 'minItems', 'maxItems'}, 'string': {'minLength', 'maxLength', 'enum'},
            'integer': {'minimum', 'maximum', 'enum'}, 'number': {'minimum', 'maximum', 'enum'},
            'boolean': {'enum'}, 'null': {'enum'}}
        require(type(kind) is str and kind in allowed and set(item) <= allowed[kind] | {'type', 'title', 'description'})
        for key, limit in (('title', 120), ('description', 2000)):
            if key in item: require(type(item[key]) is str and len(item[key]) <= limit)
        if kind == 'object':
            require(type(item.get('properties')) is dict and item.get('additionalProperties') is False)
            keys = item.get('required', [])
            require(type(keys) is list and all(type(k) is str for k in keys)
                    and len(keys) == len(set(keys)) and set(keys) <= set(item['properties']))
            for child in item['properties'].values(): node(child, depth + 1)
        elif kind in ('array', 'string'):
            lower, upper, ceiling = ('minItems', 'maxItems', 256) if kind == 'array' else ('minLength', 'maxLength', 16000)
            require(type(item.get(upper)) is int and 0 <= item[upper] <= ceiling
                    and type(item.get(lower, 0)) is int and 0 <= item.get(lower, 0) <= item[upper])
            if kind == 'array': node(item['items'], depth + 1)
        elif kind in ('number', 'integer'):
            for key in ('minimum', 'maximum'):
                if key in item: require(type(item[key]) in (int, float) and math.isfinite(item[key]))
            if 'minimum' in item and 'maximum' in item: require(item['minimum'] <= item['maximum'])
        if 'enum' in item:
            require(type(item['enum']) is list and 1 <= len(item['enum']) <= 32)
            base = {key: val for key, val in item.items() if key != 'enum'}
            for entry in item['enum']: _matches(base, entry)
            require(len({json.dumps(v, sort_keys=True) for v in item['enum']}) == len(item['enum']))
    try:
        node(value, 0)
        require(value['type'] == 'object')
        return value
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def validate_input_values(schema, values):
    checked = validate_input_schema(schema)
    value = bounded_json(values)
    try:
        _matches(checked, value)
        return value
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None

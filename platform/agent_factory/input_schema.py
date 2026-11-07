"""Small deterministic application input schemas. No references or executable hooks."""
from copy import deepcopy
import json
import math
from typing import Annotated, Any, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, TypeAdapter, create_model, model_validator

ERROR = 'APPLICATION_INPUT_INVALID'


def require(value):
    if not value:
        raise ValueError(ERROR)


def bounded_json(value, *, maximum=None, ensure_ascii=True):
    def walk(item, depth):
        if type(item) is dict:
            require(all(type(k) is str for k in item))
            for child in item.values(): walk(child, depth + 1)
        elif type(item) is list:
            for child in item: walk(child, depth + 1)
        elif type(item) is str:
            pass
        elif type(item) is float:
            require(math.isfinite(item))
        else:
            require(item is None or type(item) in (bool, int))
    try:
        walk(value, 0)
        require(maximum is None or len(json.dumps(value, allow_nan=False, ensure_ascii=ensure_ascii).encode()) <= maximum)
        return deepcopy(value)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


class _BoundedInputs(BaseModel):
    @model_validator(mode='before')
    @classmethod
    def bounded_values(cls, value: Any) -> Any:
        return bounded_json(value)


def _annotation(schema, *, root=False) -> Any:
    """Map the admitted declaration to Pydantic's strict validation primitives."""
    kind = schema['type']
    metadata = {key: schema[key] for key in ('title', 'description') if key in schema}
    if kind == 'object':
        required = set(schema.get('required', []))
        fields = {}
        for index, (name, child) in enumerate(sorted(schema['properties'].items())):
            # Aliases preserve arbitrary JSON property names without colliding
            # with BaseModel methods or protected/internal field names.
            fields['field_' + str(index)] = (_annotation(child), Field(
                default=... if name in required else None, alias=name,
                **{key: child[key] for key in ('title', 'description') if key in child}))
        return create_model(schema.get('title', 'ApplicationInputs'), __base__=_BoundedInputs if root else BaseModel, __config__=ConfigDict(strict=True, extra='forbid',
            populate_by_name=False, validate_default=False), **fields)
    if kind == 'array':
        annotation = list[_annotation(schema['items'])]
        metadata.update(min_length=schema.get('minItems', 0), max_length=schema.get('maxItems'))
    elif kind == 'string':
        annotation = StrictStr
        metadata.update(min_length=schema.get('minLength', 0), max_length=schema.get('maxLength'))
    elif kind in ('number', 'integer'):
        annotation = StrictInt if kind == 'integer' else Union[StrictInt, StrictFloat]
        metadata.update({target: schema[source] for source, target in (('minimum', 'ge'), ('maximum', 'le')) if source in schema})
        if kind == 'number': metadata['allow_inf_nan'] = False
    else:
        annotation = StrictBool if kind == 'boolean' else type(None)
    if 'enum' in schema:
        metadata['json_schema_extra'] = {'enum': deepcopy(schema['enum'])}
    result = Annotated[annotation, Field(**metadata)]
    if 'enum' in schema:
        choices = deepcopy(schema['enum'])
        def typed_enum(value):
            # Pydantic Literal follows equality (e.g. 1 == True == 1.0).
            # Existing immutable schemas distinguish their exact JSON types.
            require(any(type(value) is type(item) and value == item for item in choices))
            return value
        result = Annotated[result, AfterValidator(typed_enum)]
    return result


def validate_input_schema(schema):
    value = bounded_json(schema)
    def node(item: dict[str, Any], depth: int):
        require(type(item) is dict)
        kind = item.get('type')
        allowed = {'object': {'properties', 'required', 'additionalProperties'},
            'array': {'items', 'minItems', 'maxItems'}, 'string': {'minLength', 'maxLength', 'enum'},
            'integer': {'minimum', 'maximum', 'enum'}, 'number': {'minimum', 'maximum', 'enum'},
            'boolean': {'enum'}, 'null': {'enum'}}
        require(type(kind) is str and kind in allowed and set(item) <= allowed[kind] | {'type', 'title', 'description'})
        for key in ('title', 'description'):
            if key in item: require(type(item[key]) is str)
        if kind == 'object':
            require(type(item.get('properties')) is dict and item.get('additionalProperties') is False)
            keys = item.get('required', [])
            require(type(keys) is list and all(type(k) is str for k in keys)
                    and len(keys) == len(set(keys)) and set(keys) <= set(item['properties']))
            for child in item['properties'].values(): node(child, depth + 1)
        elif kind in ('array', 'string'):
            lower, upper = ('minItems', 'maxItems') if kind == 'array' else ('minLength', 'maxLength')
            require(type(item.get(lower, 0)) is int and item.get(lower, 0) >= 0)
            if upper in item:
                require(type(item[upper]) is int and item[upper] >= item.get(lower, 0))
            if kind == 'array': node(item['items'], depth + 1)
        elif kind in ('number', 'integer'):
            for key in ('minimum', 'maximum'):
                if key in item: require(type(item[key]) is int or type(item[key]) is float and math.isfinite(item[key]))
            if 'minimum' in item and 'maximum' in item: require(item['minimum'] <= item['maximum'])
        if 'enum' in item:
            require(type(item['enum']) is list and len(item['enum']) >= 1)
            base = {key: val for key, val in item.items() if key != 'enum'}
            for entry in item['enum']: TypeAdapter(_annotation(base)).validate_python(entry, strict=True)
            require(len({json.dumps(v, sort_keys=True) for v in item['enum']}) == len(item['enum']))
    try:
        node(value, 0)
        require(value['type'] == 'object')
        return value
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def input_model(schema) -> type[BaseModel]:
    """Return an Agno-compatible Pydantic model for the bounded declaration.

    Serialize with model_dump(by_alias=True, exclude_unset=True): optional
    omitted fields must never become explicit defaults in immutable inputs.
    """
    return _annotation(validate_input_schema(schema), root=True)


def validate_input_values(schema, values):
    model = input_model(schema)
    value = bounded_json(values)
    try:
        model.model_validate(value, strict=True)
        # Preserve the exact reviewed input representation rather than injecting
        # omitted fields or serializing Pydantic's numeric normalization.
        return value
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None

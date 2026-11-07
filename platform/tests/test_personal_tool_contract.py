"""Bounded standard tool schemas keep MCP semantics without network retrieval."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from agent_factory.personal_tool_contract import validate_tool_arguments, validate_tool_schema


class PersonalToolContractTests(unittest.TestCase):
    def test_standard_schema_annotations_local_refs_and_typed_values(self):
        schema = {'type': 'object', '$comment': 'Synthetic SDK declaration',
            '$defs': {'query': {'type': 'string'}},
            'properties': {'query': {'$ref': '#/$defs/query'},
                'choice': {'const': {'title': True}}, 'mode': {'enum': [False, 'safe']}},
            'required': ['query', 'choice', 'mode'], 'additionalProperties': False}
        frozen = validate_tool_schema(schema)
        values = {'query': 'synthetic', 'choice': {'title': True}, 'mode': False}
        self.assertEqual(validate_tool_arguments(frozen, values), values)
        for changed in ({'choice': {'title': 1}}, {'mode': 0}, {'query': 5}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, '^PERSONAL_TOOL_INPUT_INVALID$'):
                validate_tool_arguments(frozen, {**values, **changed})
        schema['properties']['query']['$ref'] = '#/missing'
        self.assertEqual(frozen['properties']['query']['$ref'], '#/$defs/query')

    def test_external_schema_reference_cannot_open_a_network_connection(self):
        schema = validate_tool_schema({'type': 'object',
            'properties': {'value': {'$ref': 'https://schema.invalid/private.json'}}})
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')) as connect:
            with self.assertRaisesRegex(ValueError, '^PERSONAL_TOOL_INPUT_INVALID$'):
                validate_tool_arguments(schema, {'value': 'synthetic'})
        connect.assert_not_called()

    def test_open_schema_still_bounds_arguments_and_reserved_native_fields(self):
        schema = validate_tool_schema({'type': 'object'})
        nested = {}
        for _ in range(14):
            nested = {'next': nested}
        for values in ({'query': 'x' * 200000}, {'rows': list(range(257))}, nested):
            self.assertEqual(validate_tool_arguments(schema, values), values)
        cycle = []
        cycle.append(cycle)
        for values in ({'value': float('nan')}, {'value': b'bytes'},
                {'value': cycle}, {'value': {1: 'key'}},
                {'fc': 'forged'}, {'run_context': {}}, {'_agno_run_context': {}}):
            with self.subTest(values=list(values)), self.assertRaisesRegex(ValueError, '^PERSONAL_TOOL_INPUT_INVALID$'):
                validate_tool_arguments(schema, values)

    def test_arguments_enforce_serialized_byte_budget_and_detach_values(self):
        schema = validate_tool_schema({'type': 'object'})
        values = {'text': '"' * 32762}
        self.assertEqual(len(json.dumps(values).encode()), 65536)
        result = validate_tool_arguments(schema, values)
        self.assertEqual(result, values)
        values['text'] += '"'
        self.assertEqual(validate_tool_arguments(schema, values), values)
        self.assertEqual(result, {'text': '"' * 32762})

    def test_schema_declaration_obeys_exact_serialized_budget(self):
        schema = {'type': 'object', '$comment': ''}
        overhead = len(json.dumps(schema).encode())
        schema['$comment'] = '"' * ((32768 - overhead) // 2) + 'x' * ((32768 - overhead) % 2)
        self.assertEqual(len(json.dumps(schema).encode()), 32768)
        frozen = validate_tool_schema(schema)
        self.assertEqual(frozen, schema)
        schema['$comment'] += 'x'
        self.assertEqual(validate_tool_schema(schema), schema)
        self.assertEqual(len(json.dumps(frozen).encode()), 32768)

    def test_invalid_or_oversized_declarations_do_not_enter_registry(self):
        original = {'type': 'object', 'properties': {'value': {'type': 'string'}}}
        for schema in ({'type': 'array'}, {'type': 'object', 'properties': {'fc': {}}},
                {'type': 'object', 'required': True},
                {**copy.deepcopy(original), 'default': float('nan')}):
            with self.subTest(schema_keys=list(schema)), self.assertRaisesRegex(ValueError, '^PERSONAL_TOOL_DESCRIPTOR_INVALID$'):
                validate_tool_schema(schema)

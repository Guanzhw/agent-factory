"""Public recipe contracts only: no process dispatch, network or credentials."""
from copy import deepcopy
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_factory.tool_operations import (
    instantiate_operation_adapter, normalize_operation, operation_hash,
)


class ToolOperationsTests(unittest.TestCase):
    def cli(self):
        return {'transport': 'cli', 'toolName': 'member_echo', 'executable': sys.executable}

    def mcp(self):
        return {'transport': 'mcp', 'toolName': 'member_echo',
                'url': 'http://localhost:8123/mcp', 'remoteToolName': 'echo'}

    def test_canonical_roundtrip_defaults_and_input_not_mutated(self):
        original = self.cli() | {'argumentOptions': {'z': '--last', 'a': '--first'},
                                 'arguments': ['second', 'first']}
        before = deepcopy(original)
        normalized = normalize_operation(original)
        self.assertEqual(original, before)
        self.assertEqual(normalize_operation(normalized), normalized)
        reordered = dict(reversed(list(original.items())))
        reordered['argumentOptions'] = {'a': '--first', 'z': '--last'}
        self.assertEqual(json.dumps(normalized), json.dumps(normalize_operation(reordered)))
        self.assertEqual(list(normalized['argumentOptions']), ['a', 'z'])
        self.assertEqual(normalized['arguments'], ['second', 'first'])
        self.assertEqual(normalized['credentialDestination'], sys.executable)
        self.assertEqual(normalized['permission'], 'tool:invoke')

    def test_each_dispatch_semantic_changes_hash(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        changes = {'toolName': 'another', 'description': 'Public operation',
            'inputSchema': {'type': 'object', 'properties': {'n': {'type': 'number'}}},
            'readOnly': True, 'timeoutSeconds': 20, 'maxOutputBytes': 2048,
            'executable': str(root / 'another-executable'), 'arguments': ['--fixed'],
            'workingDirectory': str(root), 'environment': {'PUBLIC_OPTION': 'value'},
            'argumentOptions': {'n': '--number'}, 'stdinJson': False,
            'credentialEnvironmentVariable': 'MEMBER_TOKEN', 'outputFormat': 'text'}
        baseline = operation_hash(self.cli())
        for key, value in changes.items():
            with self.subTest(key=key):
                self.assertNotEqual(baseline, operation_hash(self.cli() | {key: value}))
        self.assertNotEqual(operation_hash(self.cli() | {'arguments': ['a', 'b']}),
                            operation_hash(self.cli() | {'arguments': ['b', 'a']}))
        for change in ({'url': 'http://localhost:8124/mcp'}, {'remoteToolName': 'other'}):
            self.assertNotEqual(operation_hash(self.mcp()), operation_hash(self.mcp() | change))

    def test_generated_adapter_identity_is_not_recipe_identity(self):
        recipe = normalize_operation(self.cli())
        first = instantiate_operation_adapter(recipe, 'operation-a', '1')
        second = instantiate_operation_adapter(recipe, 'operation-b', '2')
        self.assertNotEqual(first.descriptor.adapter_id, second.descriptor.adapter_id)
        self.assertEqual(first.configuration, second.configuration)
        self.assertEqual(operation_hash(first.configuration), operation_hash(second.configuration))
        self.assertNotIn('adapterId', recipe)
        self.assertNotIn('revision', recipe)

    def test_mcp_restore_only_constructs_same_fixed_target(self):
        recipe = normalize_operation(self.mcp())
        adapter = instantiate_operation_adapter(recipe, 'public-mcp', '1')
        self.assertEqual(str(adapter._endpoint), recipe['url'])
        self.assertEqual(adapter._remote_tool_name, 'echo')
        self.assertEqual(adapter.descriptor.credential_destination, recipe['url'])

    def test_private_unknown_and_privilege_fields_rejected_without_echo(self):
        values = {'credentialRef': 'SYNTHETIC_PRIVATE', 'credentialRevision': 'SYNTHETIC_PRIVATE',
            'requestId': 'SYNTHETIC_PRIVATE', 'adapterId': 'SYNTHETIC_PRIVATE',
            'unexpected': 'SYNTHETIC_PRIVATE', 'permission': 'admin',
            'capabilities': ['tool:invoke', 'admin'], 'credentialProviderId': 'other',
            'credentialDestination': '/other'}
        for key, value in values.items():
            with self.subTest(key=key):
                with self.assertRaises(ValueError) as caught:
                    normalize_operation(self.cli() | {key: value})
                self.assertEqual(str(caught.exception), 'TOOL_OPERATION_CONFIGURATION_INVALID')
        for key in ('credentialRef', 'credentialRevision', 'requestId'):
            with self.assertRaises(ValueError):
                normalize_operation(self.cli() | {key: None})

    def test_url_credentials_query_and_fragment_rejected(self):
        for url in ('http://user:SYNTHETIC_PRIVATE@localhost/mcp',
                    'http://localhost/mcp?token=SYNTHETIC_PRIVATE', 'http://localhost/mcp#private'):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, '^TOOL_OPERATION_CONFIGURATION_INVALID$'):
                normalize_operation(self.mcp() | {'url': url})

    def test_path_and_invalid_schema_rejected(self):
        for change in ({'executable': 'relative'}, {'workingDirectory': 'relative'},
                       {'inputSchema': {'type': 'bad-type'}}, {'timeoutSeconds': float('nan')}):
            with self.assertRaisesRegex(ValueError, '^TOOL_OPERATION_CONFIGURATION_INVALID$'):
                normalize_operation(self.cli() | change)

    def test_public_environment_is_not_claimed_to_be_secret_detected(self):
        recipe = normalize_operation(self.cli() | {'environment': {'PUBLIC_SETTING': 'arbitrary'}})
        self.assertEqual(recipe['environment'], {'PUBLIC_SETTING': 'arbitrary'})

    def test_unavailable_executable_has_redacted_restore_error(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        missing = Path(directory.name).resolve() / 'synthetic-command'
        self.assertFalse(missing.exists())
        with self.assertRaisesRegex(ValueError, '^TOOL_OPERATION_ADAPTER_UNAVAILABLE$'):
            instantiate_operation_adapter(self.cli() | {'executable': str(missing)},
                                          'public-cli', '1')

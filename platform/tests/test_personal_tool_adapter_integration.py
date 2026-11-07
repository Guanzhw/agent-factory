"""Real local adapters through native Function calls; synthetic credentials only."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from agno.run import RunContext
from agno.tools.function import FunctionCall

from agent_factory.execution_bindings import BindingContext
from agent_factory.personal_cli import CliCredentialDelivery, PersonalCliAdapter, MemberCliAdapter
from agent_factory.personal_mcp import MCPToolAdapter
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.personal_tool_contract import ToolDescriptor
from agent_factory.personal_tool_execution import personal_tool_registration
from mcp_protocol_fixture import ALICE_TOKEN, MCPProtocolServer
from test_personal_cli import FIXTURE
from test_personal_tool_execution import Handle, Store


def native_call(adapter, lease, arguments):
    store = Store(adapter)
    context = RunContext(user_id='alice', session_id='task-alice', run_id='run-alice', session_state={})
    plan = {'id': 'plan-alice', 'ownerId': 'alice'}
    store.contexts[context.run_id] = (context.user_id, context.session_id, plan['id'])
    store.plans[context.run_id] = plan
    handle = Handle('alice', adapter, store.personal_tools)
    handle.lease = lease
    spec = {'connection': {'ref': 'connection-alice', 'revision': 'connection-v1'}}
    binding = BindingContext(None, store, plan, context, spec, handle)
    function = personal_tool_registration(adapter).factory(binding)
    function._run_context = context
    return FunctionCall(function=function, call_id='original-native-call', arguments=arguments), store, handle


class PersonalToolAdapterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # This test owns its loop; CLI pipe payloads must not enter debug tracing.
        asyncio.get_running_loop().set_debug(False)

    def assert_done(self, store, output, lease):
        self.assertEqual(len(store.effects), 1)
        effect = store.effects['run-alice', 'personal-tool:original-native-call']
        self.assertEqual(effect['status'], 'DONE')
        self.assertEqual(effect['task_id'], 'task-alice')
        self.assertEqual(effect['result']['outcome'], 'completed')
        self.assertEqual(effect['result']['output'], output)
        self.assertNotIn(lease.password, json.dumps(effect))

    @unittest.skipUnless(os.name == 'posix', 'CLI process groups require POSIX')
    async def test_cli_native_call_completes_once_and_replays_private_receipt(self):
        schema = {'type': 'object', 'additionalProperties': False, 'required': ['value'],
            'properties': {'value': {'type': 'string', 'maxLength': 100}, 'writeEffect': {'type': 'boolean'}}}
        descriptor = ToolDescriptor('integration-cli', 'v1', 'fixture_query', 'Synthetic CLI lookup',
            schema, 'cli', 'synthetic-cli', 'synthetic-service', ('tool:query',), permission='fixture:query')
        with TemporaryDirectory(prefix='personal-tool-integration-') as temporary:
            root = Path(temporary)
            private = root / 'private'
            private.mkdir()
            marker = root / 'business-effects.jsonl'
            adapter = PersonalCliAdapter(descriptor=descriptor, executable=sys.executable,
                fixed_arguments=('-I', str(FIXTURE.resolve()), '--credential-source', 'stdin',
                                 '--effect-file', str(marker)),
                probe_arguments=('--probe',), business_options={'value': '--value', 'writeEffect': '--write-effect'},
                credential=CliCredentialDelivery(mode='stdin'),
                verify_identity=lambda output, lease: (
                    output.get('account') == lease.username.removeprefix('synthetic-')
                    and output.get('credentialSource') == 'stdin'),
                unauthenticated_exit_codes=frozenset({77}), temporary_root=private)
            lease = SecretLease('synthetic-alice', 'synthetic-token-alice')
            call, store, handle = native_call(adapter, lease, {'value': 'native-cli', 'writeEffect': True})
            self.assertEqual((await call.aexecute()).status, 'success')
            expected = {'account': 'alice', 'credentialSource': 'stdin', 'value': 'native-cli'}
            self.assertEqual(call.result, expected)
            self.assert_done(store, expected, lease)
            self.assertEqual(handle.resolutions, 1)
            original_marker = marker.read_text()
            self.assertEqual([json.loads(line) for line in original_marker.splitlines()],
                             [{'account': 'alice', 'value': 'native-cli'}])
            replay = FunctionCall(function=call.function, call_id=call.call_id, arguments=dict(call.arguments))
            self.assertEqual((await replay.aexecute()).status, 'success')
            self.assertEqual(replay.result, expected)
            self.assertEqual(handle.resolutions, 1)
            self.assertEqual(marker.read_text(), original_marker)
            self.assertEqual(list(private.iterdir()), [])
            self.assert_done(store, expected, lease)

    @unittest.skipUnless(os.name == 'posix', 'CLI process groups require POSIX')
    async def test_member_cli_large_report_completes_and_replays_without_process(self):
        schema = {'type': 'object', 'properties': {}, 'additionalProperties': False}
        descriptor = ToolDescriptor('report-cli', 'v1', 'fixture_query', 'Synthetic report',
            schema, 'cli', 'synthetic-cli', 'synthetic-service', ('tool:query',),
            permission='fixture:query')
        expected = {'text': 'x' * 16001, 'rows': list(range(257)),
            'columns': {str(i): i for i in range(65)}}
        with TemporaryDirectory(prefix='personal-report-') as temporary:
            marker = Path(temporary) / 'dispatches'
            program = ("import json; from pathlib import Path; "
                f"p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
                "print(json.dumps({'text':'x'*16001,'rows':list(range(257)),"
                "'columns':{str(i):i for i in range(65)}}))")
            adapter = MemberCliAdapter(descriptor, {'executable': sys.executable,
                'arguments': ['-I', '-c', program]})
            call, store, _ = native_call(adapter, None, {})
            self.assertEqual((await call.aexecute()).status, 'success')
            self.assertEqual(call.result, expected)
            self.assertEqual(next(iter(store.effects.values()))['status'], 'DONE')
            replay = FunctionCall(function=call.function, call_id=call.call_id, arguments={})
            self.assertEqual((await replay.aexecute()).status, 'success')
            self.assertEqual(replay.result, expected)
            self.assertEqual(marker.read_text(), 'x')

    @unittest.skipUnless(os.name == 'posix', 'CLI process groups require POSIX')
    async def test_member_cli_accepts_declared_large_input_once_and_rejects_schema_violation(self):
        schema = {'type': 'object', 'additionalProperties': False, 'required': ['text', 'rows'],
            'properties': {'text': {'type': 'string', 'maxLength': 25000},
                'rows': {'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 300}}}
        descriptor = ToolDescriptor('input-cli', 'v1', 'fixture_query', 'Synthetic input report',
            schema, 'cli', 'synthetic-cli', 'synthetic-service', ('tool:query',),
            permission='fixture:query')
        with TemporaryDirectory(prefix='personal-input-') as temporary:
            marker = Path(temporary) / 'dispatches'
            program = ("import json,sys; from pathlib import Path; data=json.load(sys.stdin); "
                f"p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
                "print(json.dumps({'characters':len(data['text']),'rows':len(data['rows'])}))")
            adapter = MemberCliAdapter(descriptor, {'executable': sys.executable,
                'arguments': ['-I', '-c', program]})
            arguments = {'text': 'x' * 20000, 'rows': list(range(257))}
            call, store, _ = native_call(adapter, None, arguments)
            self.assertEqual((await call.aexecute()).status, 'success')
            self.assertEqual(call.result, {'characters': 20000, 'rows': 257})
            replay = FunctionCall(function=call.function, call_id=call.call_id, arguments=arguments)
            self.assertEqual((await replay.aexecute()).status, 'success')
            for invalid in ({**arguments, 'text': 'x' * 25001},
                    {**arguments, 'rows': list(range(301))}, {**arguments, 'rows': ['wrong type']}):
                rejected = FunctionCall(function=call.function, call_id='rejected', arguments=invalid)
                self.assertEqual((await rejected.aexecute()).error, 'PERSONAL_TOOL_INPUT_INVALID')
            self.assertEqual(marker.read_text(), 'x')
            self.assertEqual(len(store.effects), 1)
            self.assertEqual(next(iter(store.effects.values()))['status'], 'DONE')

    async def test_mcp_standard_schema_native_call_completes_once_and_replays_private_receipt(self):
        # Ordinary MCP schema has neither maxLength nor additionalProperties.
        schema = {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']}
        descriptor = ToolDescriptor('integration-mcp', 'v1', 'fixture_query', 'Synthetic MCP echo',
            schema, 'mcp', 'synthetic-vault', 'synthetic-mcp-server', ('tool:query',),
            permission='fixture:query', timeout_seconds=5)
        async with MCPProtocolServer() as server:
            adapter = MCPToolAdapter(descriptor, url=server.url, remote_tool_name='echo')
            lease = SecretLease('synthetic-mcp', ALICE_TOKEN)
            value = 'x' * 20000
            call, store, handle = native_call(adapter, lease, {'value': value})
            self.assertEqual(call.function.parameters, schema)
            self.assertEqual((await call.aexecute()).status, 'success')
            receipt = next(iter(store.effects.values()))['result']
            full = receipt['output']
            self.assertEqual(full['structuredContent'], {'owner': 'alice', 'value': value})
            self.assertGreater(len(full['content'][0]['text']), 16000)
            self.assertTrue(call.result['truncated'])
            self.assertEqual(call.result['fullOutput'], receipt['outputArtifact'])
            self.assertEqual(json.loads(store.artifacts[0]['content']), full)
            original = call.result
            self.assert_done(store, full, lease)
            self.assertEqual(server.calls, [('echo', 'alice')])
            requests, resolutions = len(server.requests), handle.resolutions
            self.assertGreater(requests, 0)
            self.assertGreater(resolutions, 0)
            replay = FunctionCall(function=call.function, call_id=call.call_id, arguments=dict(call.arguments))
            self.assertEqual((await replay.aexecute()).status, 'success')
            self.assertEqual(replay.result, original)
            self.assertEqual(server.calls, [('echo', 'alice')])
            self.assertEqual(len(server.requests), requests)
            self.assertEqual(handle.resolutions, resolutions)
            self.assert_done(store, full, lease)
        self.assertTrue(server.closed)

    async def test_mcp_initialize_401_is_stopped_failure_and_replays_without_network(self):
        schema = {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']}
        descriptor = ToolDescriptor('integration-mcp', 'v1', 'fixture_query', 'Synthetic MCP echo',
            schema, 'mcp', 'synthetic-vault', 'synthetic-mcp-server', ('tool:query',),
            permission='fixture:query', timeout_seconds=5)
        async with MCPProtocolServer() as server:
            adapter = MCPToolAdapter(descriptor, url=server.url, remote_tool_name='echo')
            lease = SecretLease('synthetic-mcp', 'synthetic-rejected-mcp-token')
            call, store, handle = native_call(adapter, lease, {'value': 'must-not-dispatch'})
            try:
                result = await call.aexecute()
            finally:
                self.assertEqual(server.calls, [])
                self.assertGreater(len(server.requests), 0)
                self.assertTrue(all(request.owner is None for request in server.requests))
                effect = store.effects['run-alice', 'personal-tool:original-native-call']
                self.assertEqual(effect['status'], 'DONE')
                self.assertEqual(effect['result'], {'outcome': 'failed', 'stopped': True})
                self.assertNotIn(lease.password, json.dumps(effect))
            self.assertEqual((result.status, result.error), ('failure', 'PERSONAL_TOOL_FAILED'))
            requests, resolutions = len(server.requests), handle.resolutions
            self.assertGreater(resolutions, 0)
            replay = FunctionCall(function=call.function, call_id=call.call_id, arguments=dict(call.arguments))
            result = await replay.aexecute()
            self.assertEqual((result.status, result.error), ('failure', 'PERSONAL_TOOL_FAILED'))
            self.assertEqual(server.calls, [])
            self.assertEqual(len(server.requests), requests)
            self.assertEqual(handle.resolutions, resolutions)
            self.assertEqual(effect['result'], {'outcome': 'failed', 'stopped': True})
        self.assertTrue(server.closed)

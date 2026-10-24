"""Member-defined resources use native Functions and real local transports."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from agno.run import RunContext
from agno.exceptions import StopAgentRun
from agno.tools.function import FunctionCall
from fastapi import HTTPException

from agent_factory.execution_bindings import BindingContext, ExecutionBindings
from agent_factory.personal_mcp import discover_mcp_tools, mcp_url
from agent_factory.personal_tools import ConfigureResourceRequest, DiscoverToolsRequest, PersonalTools
from agent_factory.personal_tool_execution import personal_tool_registration
from agent_factory.store import digest
from sqlalchemy import create_engine, select
from mcp_protocol_fixture import ALICE_TOKEN, MCPProtocolServer
import test_personal_tools as fixtures
from test_personal_tool_execution import Store


class MemberToolResources(unittest.TestCase):
    setUp = fixtures.PersonalToolTests.setUp
    create_credential = fixtures.PersonalToolTests.create_credential

    def config(self, **changes):
        return ConfigureResourceRequest(transport='cli', toolName='member_lookup', executable=sys.executable,
            arguments=['-c', 'import json; print(json.dumps({"ok": True}))'], requestId='member-resource', **changes)

    def test_member_configuration_survives_restart_and_is_native_registry_metadata(self):
        resource = self.service.configure_resource('alice', self.config(environment={'CONFIG_MODE': 'personal'}))
        self.assertIsNone(resource['credentialRef'])
        self.assertEqual(resource['status'], 'configured')
        self.assertNotIn('environment', json.dumps(resource))
        self.assertEqual(self.service.configure_resource('alice', self.config(environment={'CONFIG_MODE': 'personal'})), resource)
        reopened = PersonalTools(self.connections, self.vault, ())
        bindings = ExecutionBindings(type('Settings', (), {'demo': False})(), self.store, self.connections)
        reopened.register(bindings)
        declaration = resource['runtimeBinding'] | {'toolName': resource['toolName']}
        self.assertEqual(bindings._entry('tool', declaration).tool_name, 'member_lookup')
        self.assertEqual(reopened.inspect('alice', resource['registrationRef']), resource)
        self.assertIn('member_lookup', reopened.catalog_tools())
        self.assertEqual(reopened.describe('bob'), [])
        with self.assertRaises(HTTPException):
            reopened.inspect('bob', resource['registrationRef'])
        self.service.revoke('alice', resource['registrationRef'], 'revoke-member')
        self.assertFalse(reopened.inspect('alice', resource['registrationRef'])['available'])

    def native_call(self, resource, adapter, *, values=None, actor='alice'):
        store = Store(adapter)
        store.personal_tools = self.service
        store.authorize_tool = lambda context, name: None
        context = RunContext(user_id=actor, session_id='task-' + actor, run_id='member-run', session_state={})
        plan = {'id': 'member-plan', 'ownerId': actor}
        store.contexts[context.run_id] = (actor, context.session_id, plan['id'])
        with self.connections._read() as conn:
            handle = self.service.binding(conn, actor, resource['registrationRef']).opaque_handle
        binding = BindingContext(None, store, plan, context,
            {'connection': {'ref': resource['registrationRef'], 'revision': resource['revision']}}, handle)
        function = personal_tool_registration(adapter).factory(binding)
        function._run_context = context
        call = FunctionCall(function=function, arguments=values or {}, call_id='original-member-call')
        return call, context

    @unittest.skipUnless(os.name == 'posix', 'CLI process groups require the selected Linux deployment')
    def test_arbitrary_cli_workdir_configuration_and_native_retry_dispatch_once(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'dispatches'
            code = ('import json,os,sys,pathlib; '
                'p=pathlib.Path("dispatches"); p.write_text(p.read_text()+"x" if p.exists() else "x"); '
                'print(json.dumps({"input":json.load(sys.stdin),"mode":os.environ["CONFIG_MODE"],"cwd":os.getcwd()}))')
            request = self.config(workingDirectory=directory, environment={'CONFIG_MODE': 'personal'})
            request = request.model_copy(update={'arguments': ['-c', code],
                'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}})
            resource = self.service.configure_resource('alice', request)
            call, context = self.native_call(resource, self.service.adapters[resource['adapterId']], values={'query': 'local'})
            async def invoke_twice():
                first = await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
                second = await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
                self.assertEqual(first, second)
                return first
            output = asyncio.run(invoke_twice())
            self.assertEqual(output, {'input': {'query': 'local'}, 'mode': 'personal', 'cwd': directory})
            self.assertEqual(marker.read_text(), 'x')

    @unittest.skipUnless(os.name == 'posix', 'CLI process groups require the selected Linux deployment')
    def test_member_cli_option_mapping_and_text_output_follow_declared_contract(self):
        request = self.config().model_copy(update={'arguments': ['-c', 'import sys; print(sys.argv[1])'],
            'argumentOptions': {'query': '--query'}, 'stdinJson': False, 'outputFormat': 'text',
            'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}}})
        resource = self.service.configure_resource('alice', request)
        call, context = self.native_call(resource, self.service.adapters[resource['adapterId']], values={'query': 'one two'})
        output = asyncio.run(call.function.entrypoint(run_context=context, fc=call, **call.arguments))
        self.assertEqual(output, {'text': '--query=one two\n'})

    @unittest.skipUnless(os.name == 'posix', 'CLI process groups require the selected Linux deployment')
    def test_member_cli_failed_business_remains_unknown_and_native_retry_does_not_reexecute(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('import pathlib,sys; p=pathlib.Path("dispatches"); '
                'p.write_text(p.read_text()+"x" if p.exists() else "x"); sys.exit(3)')
            request = self.config(workingDirectory=directory).model_copy(update={'arguments': ['-c', code]})
            resource = self.service.configure_resource('alice', request)
            call, context = self.native_call(resource, self.service.adapters[resource['adapterId']])
            async def invoke_twice():
                for _ in range(2):
                    with self.assertRaisesRegex(StopAgentRun, 'PERSONAL_TOOL_OUTCOME_UNKNOWN'):
                        await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
            asyncio.run(invoke_twice())
            self.assertEqual((Path(directory) / 'dispatches').read_text(), 'x')

    @unittest.skipUnless(os.name == 'posix', 'CLI process groups require the selected Linux deployment')
    def test_member_cli_cleanup_failure_is_fixed_unknown_and_does_not_redispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('import pathlib; p=pathlib.Path("dispatches"); '
                'p.write_text(p.read_text()+"x" if p.exists() else "x"); print("{}")')
            resource = self.service.configure_resource('alice', self.config(workingDirectory=directory)
                .model_copy(update={'arguments': ['-c', code]}))
            call, context = self.native_call(resource, self.service.adapters[resource['adapterId']])
            cleanup = shutil.rmtree
            def fail_cleanup(path):
                self.addCleanup(cleanup, path)
                raise OSError('synthetic-private-credential-directory')
            async def invoke_twice():
                with patch('agent_factory.personal_cli.shutil.rmtree', side_effect=fail_cleanup):
                    for _ in range(2):
                        with self.assertRaisesRegex(StopAgentRun, '^PERSONAL_TOOL_OUTCOME_UNKNOWN$'):
                            await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
            asyncio.run(invoke_twice())
            self.assertEqual((Path(directory) / 'dispatches').read_text(), 'x')

    def test_http_member_configuration_rejects_invalid_command_without_exposing_input(self):
        response = self.client.post('/api/factory/personal-tools/resources', headers=self.headers,
            json={'transport': 'cli', 'toolName': 'member_lookup', 'executable': '/synthetic/missing',
                'requestId': 'missing-command'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('/synthetic/missing', response.text)

    def test_http_mcp_url_shapes_preserve_private_paths(self):
        for endpoint in ('http://localhost:9123/custom/mcp', 'http://10.0.0.2:8999/mcp', 'https://[::1]:9443/mcp'):
            self.assertEqual(mcp_url(endpoint), endpoint)

    def test_invalid_persisted_descriptor_fails_explicitly_when_loading_another_worker(self):
        resource = self.service.configure_resource('alice', self.config())
        with self.connections._write() as conn:
            body = conn.execute(select(self.service.tools.c.body)).scalar_one()
            body['descriptor']['inputSchema'] = {'type': 'string'}
            conn.execute(self.service.tools.update().values(body=body, fingerprint=digest(body)))
        reopened = PersonalTools(self.connections, self.vault, ())
        with self.assertRaises(HTTPException) as invalid:
            reopened.ensure_registered(resource['adapterId'])
        self.assertEqual((invalid.exception.status_code, invalid.exception.detail), (409, 'PERSONAL_TOOL_CONFIGURATION_INVALID'))

    @unittest.skipUnless(os.name == 'posix', 'Executable fixture requires POSIX')
    def test_removed_command_is_unavailable_but_remains_manageable_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'member-command'
            executable.write_text('#!/bin/sh\nprintf "{}"\n')
            executable.chmod(0o700)
            resource = self.service.configure_resource('alice', self.config().model_copy(update={'executable': str(executable)}))
            executable.unlink()
            reopened = PersonalTools(self.connections, self.vault, ())
            bindings = ExecutionBindings(type('Settings', (), {'demo': False})(), self.store, self.connections)
            reopened.register(bindings)
            self.assertEqual(reopened.list('alice')[0]['status'], 'unavailable')
            self.assertEqual(reopened.describe('alice')[0]['toolName'], 'member_lookup')
            self.assertEqual(reopened.revoke('alice', resource['registrationRef'], 'revoke-missing-command')['status'], 'revoked')


class MemberMCPResources(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix='member-mcp-'))
        # The monitor and invocation authorize concurrently. Give each checkout
        # its own connection instead of sharing StaticPool's one DBAPI handle.
        database = Path(directory) / 'tools.sqlite'
        fixtures.PersonalToolTests.setUp(self, engine=create_engine(
            'sqlite:///' + database.as_posix(), connect_args={'check_same_thread': False}))

    create_credential = fixtures.PersonalToolTests.create_credential
    native_call = MemberToolResources.native_call
    def test_team_member_invokes_real_mcp_with_owner_credential_and_withdrawal_stops_retained_function(self):
        async def run():
            async with MCPProtocolServer() as server:
                self.vault._policies['member-mcp'] = MCPPolicy()
                saved = self.vault.create(owner='alice', provider_id='member-mcp', destination=server.url,
                    username='bearer', password=ALICE_TOKEN)
                resource = self.service.configure_resource('alice', ConfigureResourceRequest(transport='mcp',
                    toolName='team_echo', remoteToolName='echo', url=server.url,
                    inputSchema={'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']},
                    credentialRef=saved['credentialRef'], credentialRevision=saved['credentialRevision'], requestId='team-mcp-resource'))
                ref = resource['registrationRef']
                self.assertEqual(self.service.list('bob'), [])
                self.service.share('alice', ref, 'team', 'share-mcp-resource')
                public = self.service.list('bob')[0]
                self.assertEqual(public['ownerId'], 'alice')
                self.assertFalse(public['isOwner'])
                self.assertEqual(public['allowedActions'], ['inspect', 'bind'])
                self.assertNotIn('credentialRef', public)
                self.assertNotIn('credentialRevision', public)
                self.assertIn(resource['adapterId'], [item['adapterId'] for item in self.service.describe('bob')])
                with self.assertRaises(HTTPException): self.service.revoke('bob', ref, 'foreign-mcp-revoke')
                with self.assertRaises(HTTPException): self.service.share('bob', ref, 'personal', 'foreign-mcp-share')
                call, context = self.native_call(resource, self.service.adapters[resource['adapterId']], values={'value': 'team'}, actor='bob')
                output = await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
                self.assertEqual(output['structuredContent'], {'owner': 'alice', 'value': 'team'})
                self.assertEqual(server.calls, [('echo', 'alice')])
                self.service.share('alice', ref, 'personal', 'withdraw-mcp-resource')
                self.assertEqual(self.service.list('bob'), [])
                call.call_id = 'after-withdrawal'
                with self.assertRaises(PermissionError):
                    await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
                self.assertEqual(server.calls, [('echo', 'alice')])
        asyncio.run(run())

    def test_real_discovery_configuration_native_invocation_and_credential_isolation(self):
        async def run():
            async with MCPProtocolServer() as server:
                self.vault._policies['member-mcp'] = MCPPolicy()
                saved = self.vault.create(owner='alice', provider_id='member-mcp', destination=server.url,
                    username='bearer', password=ALICE_TOKEN)
                discovered = await self.service.discover('alice', DiscoverToolsRequest(url=server.url,
                    credentialRef=saved['credentialRef'], credentialRevision=saved['credentialRevision']))
                self.assertEqual(server.calls, [])
                echo = next(tool for tool in discovered['tools'] if tool['name'] == 'echo')
                resource = self.service.configure_resource('alice', ConfigureResourceRequest(transport='mcp',
                    toolName='member_echo', remoteToolName='echo', url=server.url, inputSchema=echo['inputSchema'],
                    credentialRef=saved['credentialRef'], credentialRevision=saved['credentialRevision'], requestId='mcp-resource'))
                call, context = self.native_call(resource, self.service.adapters[resource['adapterId']], values={'value': 'local'})
                output = await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
                self.assertEqual(output['structuredContent'], {'owner': 'alice', 'value': 'local'})
                repeated = await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
                self.assertEqual(output, repeated)
                self.assertEqual(server.calls, [('echo', 'alice')])
                self.assertNotIn(ALICE_TOKEN, json.dumps(self.service.list('alice')))
                self.assertEqual(self.service.list('bob'), [])
                with self.assertRaises(HTTPException):
                    self.service.configure_resource('bob', ConfigureResourceRequest(transport='mcp',
                        toolName='member_echo', remoteToolName='echo', url=server.url,
                        credentialRef=saved['credentialRef'], credentialRevision=saved['credentialRevision'], requestId='foreign'))
        asyncio.run(run())

    def test_public_mcp_discovery_and_invocation_need_no_credential(self):
        from mcp.server import MCPServer
        public = MCPServer('public-local-member-test', log_level='ERROR')
        @public.tool(structured_output=True)
        async def public_echo(value: str) -> dict[str, str]:
            return {'value': value}
        class PublicServer(MCPProtocolServer):
            async def _authenticated(self, scope, receive, send):
                await self._app(scope, receive, send)
        async def run():
            server = PublicServer()
            server._app = public.streamable_http_app(stateless_http=True)
            async with server:
                discovered = await discover_mcp_tools(server.url)
                echo = next(tool for tool in discovered if tool['name'] == 'public_echo')
                resource = self.service.configure_resource('alice', ConfigureResourceRequest(transport='mcp',
                    toolName='public_echo', remoteToolName='public_echo', url=server.url,
                    inputSchema=echo['inputSchema'], requestId='public-resource'))
                call, context = self.native_call(resource, self.service.adapters[resource['adapterId']], values={'value': 'public'})
                output = await call.function.entrypoint(run_context=context, fc=call, **call.arguments)
                self.assertEqual(output['structuredContent'], {'value': 'public'})
        asyncio.run(run())


class MCPPolicy:
    normalize_destination = staticmethod(mcp_url)
    def __call__(self, value):
        return mcp_url(value)

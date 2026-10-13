"""Personal MCP calls over real loopback HTTP with synthetic owner credentials."""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
import io
import json
import logging
import threading
import unittest
from unittest.mock import patch

import httpx2
from mcp.shared import _otel
from opentelemetry import trace

from agent_factory.personal_mcp import MCPToolAdapter
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocation, ToolInvocationError
from mcp_protocol_fixture import ALICE_ROTATED_TOKEN, ALICE_TOKEN, BOB_TOKEN, MCPProtocolServer


EMPTY_SCHEMA = {'type': 'object', 'properties': {}}
ECHO_SCHEMA = {
    'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value'],
}


def descriptor(tool='whoami', **changes):
    return replace(ToolDescriptor(
        adapter_id='synthetic-mcp', revision='adapter-v1', tool_name=tool,
        description='Synthetic local protocol tool',
        input_schema=ECHO_SCHEMA if tool == 'echo' else EMPTY_SCHEMA,
        transport='mcp', credential_provider_id='synthetic-vault',
        credential_destination='synthetic-mcp-server', capabilities=('tool:invoke',),
        timeout_seconds=3,
    ), **changes)


class Authority:
    """Small trusted callback fixture enforcing the whole owner/ref/revision tuple."""

    def __init__(self, owner='alice', token=ALICE_TOKEN):
        self.owner, self.token = owner, token
        self.reference, self.revision = f'connection-{owner}', 'connection-v1'
        self.revoked, self.available = False, True
        self.checks, self.resolutions = 0, 0

    def invocation(self, arguments=None, *, owner=None, reference=None, revision=None):
        owner = self.owner if owner is None else owner
        reference = self.reference if reference is None else reference
        revision = self.revision if revision is None else revision

        def check():
            self.checks += 1
            if self.revoked or (owner, reference, revision) != (self.owner, self.reference, self.revision):
                raise ValueError(f'Synthetic authorization rejected {self.token}')

        def resolve():
            self.resolutions += 1
            check()
            if not self.available:
                raise ValueError(f'Synthetic credential unavailable {self.token}')
            return SecretLease('synthetic-mcp', self.token)

        return ToolInvocation(
            owner_id=owner, connection_ref=reference, connection_revision=revision,
            call_id=f'synthetic-call-{owner}-{revision}', arguments=arguments or {},
            run_context=None, check_authorized=check, resolve_credential=resolve,
        )


class PersonalMCPTests(unittest.IsolatedAsyncioTestCase):
    def assert_error(self, error, code, *, outcome='unknown', stopped=False):
        self.assertIsInstance(error, ToolInvocationError)
        self.assertEqual((error.code, str(error), error.outcome, error.stopped),
                         (code, code, outcome, stopped))
        self.assertNotIn(ALICE_TOKEN, repr(error))
        self.assertNotIn(BOB_TOKEN, repr(error))

    def test_https_is_default_and_plain_http_requires_explicit_numeric_loopback(self):
        for endpoint in ('http://127.0.0.1:8123/mcp', 'http://[::1]:8123/mcp',
                         'http://synthetic-public.invalid/mcp'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                MCPToolAdapter(descriptor(), url=endpoint)
        for endpoint in ('http://synthetic-public.invalid/mcp', 'http://192.0.2.10/mcp',
                         'http://localhost/mcp', 'http://127.0.0.1.example.invalid/mcp'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                MCPToolAdapter(descriptor(), url=endpoint, allow_loopback_http=True)
        MCPToolAdapter(descriptor(), url='https://synthetic-public.invalid/mcp')
        for endpoint in ('http://127.0.0.1:8123/mcp', 'http://[::1]:8123/mcp'):
            with self.subTest(endpoint=endpoint):
                MCPToolAdapter(descriptor(), url=endpoint, allow_loopback_http=True)

    async def test_two_owners_share_schema_but_keep_stateless_auth_and_results_separate(self):
        async with MCPProtocolServer() as server:
            adapter = MCPToolAdapter(descriptor('echo'), url=server.url, allow_loopback_http=True)
            alice, bob = Authority(), Authority('bob', BOB_TOKEN)
            outputs = await asyncio.gather(
                adapter.invoke(alice.invocation({'value': 'alice-input'})),
                adapter.invoke(bob.invocation({'value': 'bob-input'})),
            )
            self.assertEqual([output['structuredContent'] for output in outputs], [
                {'owner': 'alice', 'value': 'alice-input'},
                {'owner': 'bob', 'value': 'bob-input'},
            ])
            self.assertCountEqual(server.calls, [('echo', 'alice'), ('echo', 'bob')])
            for request in server.requests:
                expected = ALICE_TOKEN if request.owner == 'alice' else BOB_TOKEN
                self.assertEqual(request.headers['authorization'], f'Bearer {expected}')
                self.assertIsNone(request.session_id)
            for authority in (alice, bob):
                requests = sum(request.owner == authority.owner for request in server.requests)
                self.assertGreaterEqual(authority.resolutions, requests)
                self.assertGreaterEqual(authority.checks, authority.resolutions)
        self.assertTrue(server.closed)

    async def test_stateful_calls_get_distinct_owner_sessions_and_authenticated_delete(self):
        async with MCPProtocolServer(stateless=False) as server:
            adapter = MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True)
            outputs = await asyncio.gather(
                adapter.invoke(Authority().invocation()),
                adapter.invoke(Authority('bob', BOB_TOKEN).invocation()),
            )
            self.assertEqual([item['structuredContent']['owner'] for item in outputs], ['alice', 'bob'])
            sessions = {
                owner: {request.session_id for request in server.requests
                        if request.owner == owner and request.session_id is not None}
                for owner in ('alice', 'bob')
            }
            self.assertEqual(len(sessions['alice']), 1)
            self.assertEqual(len(sessions['bob']), 1)
            self.assertTrue(sessions['alice'].isdisjoint(sessions['bob']))
            deletes = [request for request in server.requests if request.method == 'DELETE']
            self.assertCountEqual([request.owner for request in deletes], ['alice', 'bob'])
            for request in deletes:
                self.assertIn(request.session_id, sessions[request.owner])
                token = ALICE_TOKEN if request.owner == 'alice' else BOB_TOKEN
                self.assertEqual(request.headers['authorization'], f'Bearer {token}')

    async def test_missing_revoked_foreign_and_stale_credentials_fail_before_http(self):
        async with MCPProtocolServer() as server:
            adapter = MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True)
            for case in ('missing', 'revoked', 'foreign-owner', 'foreign-ref', 'stale-revision'):
                with self.subTest(case=case):
                    authority = Authority()
                    authority.available = case != 'missing'
                    authority.revoked = case == 'revoked'
                    invocation = authority.invocation(
                        owner='bob' if case == 'foreign-owner' else None,
                        reference='foreign' if case == 'foreign-ref' else None,
                        revision='stale' if case == 'stale-revision' else None,
                    )
                    with self.assertRaises(ToolInvocationError) as failure:
                        await adapter.invoke(invocation)
                    self.assert_error(failure.exception, 'MCP_AUTHORIZATION_REJECTED', outcome='failed', stopped=True)
            self.assertEqual(server.requests, [])
            self.assertEqual(server.calls, [])

    async def test_revoke_during_dispatched_call_returns_unknown_and_no_new_calls(self):
        async with MCPProtocolServer(stateless=False) as server:
            authority = Authority()
            adapter = MCPToolAdapter(descriptor('wait'), url=server.url, allow_loopback_http=True, authorization_interval=0.01)
            pending = asyncio.create_task(adapter.invoke(authority.invocation()))
            await asyncio.wait_for(server.wait_started['alice'].wait(), 2)
            authority.revoked = True
            with self.assertRaises(ToolInvocationError) as failure:
                await asyncio.wait_for(pending, 2)
            self.assert_error(failure.exception, 'MCP_AUTHORIZATION_REJECTED')
            self.assertEqual(server.calls, [('wait', 'alice')])
            previous_requests = len(server.requests)
            with self.assertRaises(ToolInvocationError) as later:
                await adapter.invoke(authority.invocation())
            self.assert_error(later.exception, 'MCP_AUTHORIZATION_REJECTED', outcome='failed', stopped=True)
            self.assertEqual(len(server.requests), previous_requests)

    async def test_rotation_invalidates_inflight_revision_and_next_call_uses_new_token(self):
        async with MCPProtocolServer(stateless=False) as server:
            authority = Authority()
            adapter = MCPToolAdapter(descriptor('wait'), url=server.url, allow_loopback_http=True, authorization_interval=0.01)
            pending = asyncio.create_task(adapter.invoke(authority.invocation()))
            await asyncio.wait_for(server.wait_started['alice'].wait(), 2)
            authority.revision, authority.token = 'connection-v2', ALICE_ROTATED_TOKEN
            del server.tokens[ALICE_TOKEN]
            server.tokens[ALICE_ROTATED_TOKEN] = 'alice'
            with self.assertRaises(ToolInvocationError) as failure:
                await asyncio.wait_for(pending, 2)
            self.assert_error(failure.exception, 'MCP_AUTHORIZATION_REJECTED')
            split = len(server.requests)
            output = await MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True).invoke(authority.invocation())
            self.assertEqual(output['structuredContent'], {'owner': 'alice'})
            self.assertTrue(server.requests[split:])
            self.assertTrue(all(request.headers['authorization'] == f'Bearer {ALICE_ROTATED_TOKEN}'
                                for request in server.requests[split:]))
            self.assertCountEqual(server.calls, [('wait', 'alice'), ('whoami', 'alice')])

    async def test_caller_cancellation_preserves_unknown_despite_transport_close(self):
        async with MCPProtocolServer(stateless=False) as server:
            adapter = MCPToolAdapter(descriptor('wait'), url=server.url, allow_loopback_http=True)
            pending = asyncio.create_task(adapter.invoke(Authority().invocation()))
            await asyncio.wait_for(server.wait_started['alice'].wait(), 2)
            pending.cancel()
            with self.assertRaises(ToolInvocationError) as failure:
                await asyncio.wait_for(pending, 2)
            self.assert_error(failure.exception, 'MCP_CANCELLED')
            self.assertEqual(server.calls, [('wait', 'alice')])
            self.assertTrue(any(request.method == 'DELETE' for request in server.requests))
            async with asyncio.timeout(2):
                while 'alice' not in server.wait_cancelled:
                    await asyncio.sleep(0.005)

    async def test_timeout_of_dispatched_call_is_unknown_without_replay(self):
        async with MCPProtocolServer(stateless=False) as server:
            adapter = MCPToolAdapter(descriptor('wait', timeout_seconds=1), url=server.url, allow_loopback_http=True)
            with self.assertRaises(ToolInvocationError) as failure:
                await adapter.invoke(Authority().invocation())
            self.assert_error(failure.exception, 'MCP_TIMEOUT')
            self.assertEqual(server.calls, [('wait', 'alice')])

    async def test_remote_error_and_credential_echo_have_fixed_redacted_diagnostics(self):
        async with MCPProtocolServer() as server:
            for tool, code, outcome in (
                ('error', 'MCP_REMOTE_ERROR', 'failed'),
                ('secret_echo', 'MCP_CREDENTIAL_ECHO_REJECTED', 'unknown'),
            ):
                with self.subTest(tool=tool):
                    with self.assertRaises(ToolInvocationError) as failure:
                        await MCPToolAdapter(descriptor(tool), url=server.url, allow_loopback_http=True).invoke(Authority().invocation())
                    self.assert_error(failure.exception, code, outcome=outcome)
            self.assertEqual(server.calls, [('error', 'alice'), ('secret_echo', 'alice')])

    async def test_adapter_wire_debug_logs_do_not_contain_credentials_or_remote_error_content(self):
        async with MCPProtocolServer() as server:
            captured = io.StringIO()
            handler = logging.StreamHandler(captured)
            loggers = [logging.getLogger(name) for name in (
                'mcp.client.streamable_http', 'client', 'mcp.shared.jsonrpc_dispatcher',
                'mcp.shared.dispatcher', 'mcp.shared.tool_name_validation',
                'httpx2', 'httpcore2.connection', 'httpcore2.http11', 'httpcore2.http2',
            )]
            levels = [logger.level for logger in loggers]
            try:
                for logger in loggers:
                    logger.setLevel(logging.DEBUG)
                    logger.addHandler(handler)
                for tool in ('error', 'secret_echo'):
                    with self.assertRaises(ToolInvocationError):
                        await MCPToolAdapter(descriptor(tool), url=server.url, allow_loopback_http=True).invoke(Authority().invocation())
                logging.getLogger('mcp.client.streamable_http').debug('unrelated-mcp-client-still-visible')
            finally:
                for logger, level in zip(loggers, levels, strict=True):
                    logger.removeHandler(handler)
                    logger.setLevel(level)
            output = captured.getvalue()
            self.assertIn('unrelated-mcp-client-still-visible', output)
            self.assertNotIn(ALICE_TOKEN, output)
            self.assertNotIn('synthetic upstream failure', output)

    async def test_output_limit_rejects_large_success_without_replaying_tool(self):
        async with MCPProtocolServer() as server:
            adapter = MCPToolAdapter(descriptor('echo', max_output_bytes=128), url=server.url, allow_loopback_http=True)
            with self.assertRaises(ToolInvocationError) as failure:
                await adapter.invoke(Authority().invocation({'value': 'x' * 2048}))
            self.assert_error(failure.exception, 'MCP_OUTPUT_LIMIT')
            self.assertEqual(server.calls, [('echo', 'alice')])

    async def test_invalid_arguments_fail_before_credentials_or_http(self):
        async with MCPProtocolServer() as server:
            authority = Authority()
            adapter = MCPToolAdapter(descriptor('echo'), url=server.url, allow_loopback_http=True)
            for arguments in ({}, {'value': 12}):
                with self.subTest(arguments=arguments), self.assertRaises(ToolInvocationError) as failure:
                    await adapter.invoke(authority.invocation(arguments))
                self.assert_error(failure.exception, 'MCP_ARGUMENTS_INVALID', outcome='failed', stopped=True)
            self.assertEqual(authority.resolutions, 0)
            self.assertEqual(server.requests, [])

    async def test_schema_drift_and_missing_tool_fail_without_remote_dispatch(self):
        async with MCPProtocolServer() as server:
            changed_schema = {'type': 'object', 'properties': {'undeclared': {'type': 'string'}}}
            for tool, schema, code in (
                ('whoami', changed_schema, 'MCP_SCHEMA_CHANGED'),
                ('missing-tool', EMPTY_SCHEMA, 'MCP_TOOL_NOT_FOUND'),
            ):
                with self.subTest(tool=tool):
                    with self.assertRaises(ToolInvocationError) as failure:
                        await MCPToolAdapter(descriptor(tool, input_schema=schema), url=server.url, allow_loopback_http=True).invoke(
                            Authority().invocation())
                    self.assert_error(failure.exception, code, outcome='failed', stopped=True)
            self.assertEqual(server.calls, [])

    async def test_schema_annotations_and_caller_mutation_do_not_change_frozen_contract(self):
        async with MCPProtocolServer() as server:
            declared = json.loads(json.dumps(ECHO_SCHEMA))
            declared['description'] = 'Local documentation'
            declared['properties']['value']['$comment'] = 'Human explanation'
            adapter = MCPToolAdapter(descriptor('echo', input_schema=declared), url=server.url, allow_loopback_http=True)
            declared['properties']['value']['type'] = 'integer'
            output = await adapter.invoke(Authority().invocation({'value': 'still-a-string'}))
            self.assertEqual(output['structuredContent'], {'owner': 'alice', 'value': 'still-a-string'})

    async def test_each_invocation_owns_and_closes_its_http_transport_even_on_tool_failure(self):
        transports = []

        class ObservedTransport(httpx2.AsyncBaseTransport):
            def __init__(self):
                self.wire = httpx2.AsyncHTTPTransport()
                self.closed = False
                transports.append(self)

            async def handle_async_request(self, request):
                return await self.wire.handle_async_request(request)

            async def aclose(self):
                self.closed = True
                await self.wire.aclose()

        async with MCPProtocolServer(stateless=False) as server:
            authority = Authority()
            successful_adapter = MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True,
                                                http_transport_factory=ObservedTransport)
            for call_number, tool in enumerate(('whoami', 'whoami', 'error')):
                invocation = replace(authority.invocation(), call_id=f'synthetic-original-call-{call_number}')
                if tool == 'error':
                    adapter = MCPToolAdapter(descriptor(tool), url=server.url, allow_loopback_http=True,
                                             http_transport_factory=ObservedTransport)
                    with self.assertRaises(ToolInvocationError):
                        await adapter.invoke(invocation)
                else:
                    await successful_adapter.invoke(invocation)
                self.assertTrue(transports[-1].closed)
            self.assertEqual(len(transports), 3)
            sessions = {request.session_id for request in server.requests if request.session_id}
            self.assertEqual(len(sessions), 3)
            self.assertEqual(sum(request.method == 'DELETE' for request in server.requests), 3)

    async def test_server_rejects_wrong_bearer_without_tool_dispatch(self):
        async with MCPProtocolServer() as server:
            authority = Authority(token='synthetic-wrong-token')
            with self.assertRaises(ToolInvocationError) as failure:
                await MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True).invoke(authority.invocation())
            self.assert_error(failure.exception, 'MCP_TRANSPORT_ERROR', outcome='failed', stopped=True)
            self.assertEqual(len(server.requests), 1)
            self.assertIsNone(server.requests[0].owner)
            self.assertEqual(server.calls, [])

    async def test_incomplete_authentication_refusal_does_not_prove_stop(self):
        closed = asyncio.Event()

        class BrokenRefusal(httpx2.AsyncByteStream):
            async def __aiter__(self):
                yield b'incomplete refusal'
                raise httpx2.ReadError('synthetic response acknowledgement lost')

        class Transport(httpx2.MockTransport):
            async def aclose(self):
                await super().aclose()
                closed.set()

        adapter = MCPToolAdapter(descriptor(), url='https://synthetic-mcp.invalid/mcp',
            http_transport_factory=lambda: Transport(lambda request: httpx2.Response(
                401, request=request, stream=BrokenRefusal())))
        with self.assertRaises(ToolInvocationError) as failure:
            await adapter.invoke(Authority().invocation())
        self.assert_error(failure.exception, 'MCP_TRANSPORT_ERROR')
        self.assertTrue(closed.is_set(), 'Socket close alone does not prove a complete initialization refusal')

    async def test_cancelled_predispatch_credential_thread_does_not_prove_stop(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        invocation = Authority().invocation()

        def credential():
            entered.set()
            try:
                if not release.wait(5):
                    raise ValueError('Synthetic callback release timeout')
                return SecretLease('synthetic-mcp', ALICE_TOKEN)
            finally:
                finished.set()

        async with MCPProtocolServer() as server:
            adapter = MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True,
                                     teardown_timeout_seconds=0.05)
            pending = asyncio.create_task(adapter.invoke(replace(invocation, resolve_credential=credential)))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                pending.cancel()
                done, _ = await asyncio.wait({pending}, timeout=2)
                self.assertIn(pending, done)
                with self.assertRaises(ToolInvocationError) as failure:
                    await pending
                self.assert_error(failure.exception, 'MCP_CANCELLED', outcome='failed')
                self.assertFalse(finished.is_set())
                self.assertEqual(server.requests, [])
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, 2))
                await asyncio.gather(pending, return_exceptions=True)

    async def test_transport_close_failure_keeps_predispatch_schema_failure_unsettled(self):
        class CloseFailure(httpx2.AsyncHTTPTransport):
            async def aclose(self):
                await super().aclose()
                raise RuntimeError('Synthetic transport close acknowledgement lost')

        async with MCPProtocolServer(stateless=False) as server:
            schema = {'type': 'object', 'properties': {'undeclared': {'type': 'string'}}}
            adapter = MCPToolAdapter(descriptor(input_schema=schema), url=server.url, allow_loopback_http=True,
                                     http_transport_factory=CloseFailure)
            with self.assertRaises(ToolInvocationError) as failure:
                await adapter.invoke(Authority().invocation())
            self.assert_error(failure.exception, 'MCP_TRANSPORT_ERROR')
            self.assertEqual(server.calls, [])
            self.assertTrue(any(request.method == 'DELETE' for request in server.requests))

    async def test_pending_or_refused_delete_is_not_predispatch_stop_proof(self):
        async with MCPProtocolServer(stateless=False) as server:
            schema = {'type': 'object', 'properties': {'undeclared': {'type': 'string'}}}
            adapter = MCPToolAdapter(descriptor(input_schema=schema), url=server.url, allow_loopback_http=True)
            for status in (202, 405):
                with self.subTest(delete_status=status):
                    server.delete_status = status
                    with self.assertRaises(ToolInvocationError) as failure:
                        await adapter.invoke(Authority().invocation())
                    self.assert_error(failure.exception, 'MCP_SCHEMA_CHANGED', outcome='failed')
            self.assertEqual(server.calls, [])
            self.assertEqual(sum(request.method == 'DELETE' for request in server.requests), 2)

    async def test_schema_property_names_and_literal_const_values_are_not_annotations(self):
        async with MCPProtocolServer() as server:
            for declared, remote in (
                ({'type': 'object', 'properties': {}},
                 {'type': 'object', 'properties': {'title': {'type': 'string'}}}),
                ({'type': 'object', 'properties': {}},
                 {'type': 'object', 'properties': {'description': {'type': 'integer'}}}),
                ({'type': 'object', 'properties': {'payload': {'const': {'title': 'local'}}}},
                 {'type': 'object', 'properties': {'payload': {'const': {'title': 'remote'}}}}),
                ({'type': 'object', 'properties': {'payload': {'enum': [{'description': 'local'}]}}},
                 {'type': 'object', 'properties': {'payload': {'enum': [{'description': 'remote'}]}}}),
            ):
                with self.subTest(declared=declared, remote=remote):
                    server.tool_schemas['whoami'] = remote
                    with self.assertRaises(ToolInvocationError) as failure:
                        await MCPToolAdapter(descriptor(input_schema=declared), url=server.url, allow_loopback_http=True).invoke(
                            Authority().invocation())
                    self.assert_error(failure.exception, 'MCP_SCHEMA_CHANGED', outcome='failed', stopped=True)
            self.assertEqual(server.calls, [])

    async def test_schema_boolean_and_numeric_literals_remain_distinct(self):
        nested_bools = {'values': [True, {'enabled': False}]}
        nested_numbers = {'values': [1, {'enabled': 0}]}
        literal_pairs = (
            (True, 1), (1, True), (False, 0), (0, False),
            (nested_bools, nested_numbers), (nested_numbers, nested_bools),
        )
        async with MCPProtocolServer() as server:
            for keyword in ('const', 'enum'):
                for local_literal, remote_literal in literal_pairs:
                    with self.subTest(keyword=keyword, local=local_literal, remote=remote_literal):
                        local_value = [local_literal] if keyword == 'enum' else local_literal
                        remote_value = [remote_literal] if keyword == 'enum' else remote_literal
                        declared = {'type': 'object', 'properties': {'payload': {keyword: local_value}}}
                        server.tool_schemas['whoami'] = {
                            'type': 'object', 'properties': {'payload': {keyword: remote_value}},
                        }
                        # The optional payload is absent, so argument validation
                        # succeeds and the live discovery contract is compared.
                        with self.assertRaises(ToolInvocationError) as failure:
                            await MCPToolAdapter(descriptor(input_schema=declared), url=server.url, allow_loopback_http=True).invoke(
                                Authority().invocation())
                        self.assert_error(failure.exception, 'MCP_SCHEMA_CHANGED', outcome='failed', stopped=True)
                        self.assertEqual(server.calls, [])

    async def test_stateful_delete_credential_rejection_cannot_return_success(self):
        async with MCPProtocolServer(stateless=False) as server:
            authority = Authority()
            invocation = authority.invocation()
            initial_resolve = invocation.resolve_credential

            def reject_after_tool():
                if server.calls:
                    raise ValueError(f'Synthetic credential revoked: {ALICE_TOKEN}')
                return initial_resolve()

            invocation = replace(invocation, resolve_credential=reject_after_tool)
            with self.assertRaises(ToolInvocationError) as failure:
                await MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True).invoke(invocation)
            self.assert_error(failure.exception, 'MCP_AUTHORIZATION_REJECTED')
            self.assertEqual(server.calls, [('whoami', 'alice')])
            self.assertFalse(any(request.method == 'DELETE' for request in server.requests))

    async def test_broken_upstream_does_not_echo_error_or_retry(self):
        calls = []

        def broken(request):
            calls.append(request)
            raise httpx2.ReadError(f'Synthetic network error containing {ALICE_TOKEN}', request=request)

        adapter = MCPToolAdapter(descriptor(), url='http://127.0.0.1:1/mcp', allow_loopback_http=True,
                                 http_transport_factory=lambda: httpx2.MockTransport(broken))
        with self.assertRaises(ToolInvocationError) as failure:
            await adapter.invoke(Authority().invocation())
        self.assert_error(failure.exception, 'MCP_TRANSPORT_ERROR')
        self.assertEqual(len(calls), 1)

    async def test_response_headers_and_reason_phrase_cannot_leak_into_debug_logs(self):
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        loggers = [logging.getLogger(name) for name in ('httpx2', 'httpcore2.http11')]
        levels = [logger.level for logger in loggers]

        def secret_reason(request):
            return httpx2.Response(401, request=request, headers={'x-synthetic-secret': ALICE_TOKEN},
                                   extensions={'reason_phrase': ALICE_TOKEN.encode()})

        try:
            for logger in loggers:
                logger.setLevel(logging.DEBUG)
                logger.addHandler(handler)
            async with MCPProtocolServer() as server:
                server.response_headers['x-synthetic-secret'] = ALICE_TOKEN
                output = await MCPToolAdapter(descriptor(), url=server.url, allow_loopback_http=True).invoke(Authority().invocation())
                self.assertEqual(output['structuredContent']['owner'], 'alice')
            adapter = MCPToolAdapter(descriptor(), url='http://127.0.0.1:1/mcp', allow_loopback_http=True,
                                     http_transport_factory=lambda: httpx2.MockTransport(secret_reason))
            with self.assertRaises(ToolInvocationError):
                await adapter.invoke(Authority().invocation())
            loggers[0].debug('unrelated-http-client-still-visible')
        finally:
            for logger, level in zip(loggers, levels, strict=True):
                logger.removeHandler(handler)
                logger.setLevel(level)
        self.assertNotIn(ALICE_TOKEN, captured.getvalue())
        self.assertIn('unrelated-http-client-still-visible', captured.getvalue())

    async def test_encoding_and_oversize_json_are_rejected_before_json_parsing(self):
        class HugeJSON(httpx2.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"unbounded":"'
                yield b'x' * 1048577
                yield b'"}'

        for case, code in (('encoding', 'MCP_ENCODING_REJECTED'), ('oversize', 'MCP_RESPONSE_LIMIT')):
            with self.subTest(case=case):
                calls = []

                def response(request):
                    calls.append(request)
                    self.assertEqual(request.headers['accept-encoding'], 'identity')
                    if case == 'encoding':
                        return httpx2.Response(200, request=request, stream=HugeJSON(),
                                               headers={'content-type': 'application/json',
                                                        'content-encoding': 'gzip'})
                    return httpx2.Response(200, request=request, stream=HugeJSON(),
                                           headers={'content-type': 'application/json'})

                adapter = MCPToolAdapter(descriptor(), url='http://127.0.0.1:1/mcp', allow_loopback_http=True,
                                         http_transport_factory=lambda: httpx2.MockTransport(response))
                with self.assertRaises(ToolInvocationError) as failure:
                    await adapter.invoke(Authority().invocation())
                self.assert_error(failure.exception, code, outcome='failed')
                self.assertEqual(len(calls), 1)

    async def test_repeated_cancellation_during_delete_still_closes_and_restores_log_context(self):
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        logger = logging.getLogger('mcp.client.streamable_http')
        previous_level = logger.level
        closed = asyncio.Event()

        class ObservedTransport(httpx2.AsyncHTTPTransport):
            async def aclose(self):
                try:
                    await super().aclose()
                finally:
                    closed.set()

        try:
            logger.setLevel(logging.DEBUG)
            logger.addHandler(handler)
            async with MCPProtocolServer(stateless=False) as server:
                server.delete_release.clear()
                adapter = MCPToolAdapter(descriptor('wait'), url=server.url, allow_loopback_http=True,
                                         http_transport_factory=ObservedTransport)

                async def invocation_task():
                    try:
                        return await adapter.invoke(Authority().invocation())
                    finally:
                        logger.debug('same-task-context-restored-after-cancel')

                pending = asyncio.create_task(invocation_task())
                await asyncio.wait_for(server.wait_started['alice'].wait(), 2)
                pending.cancel()
                await asyncio.wait_for(server.delete_started.wait(), 2)
                pending.cancel()
                server.delete_release.set()
                with self.assertRaises(ToolInvocationError) as failure:
                    await asyncio.wait_for(pending, 2)
                self.assert_error(failure.exception, 'MCP_CANCELLED')
                self.assertTrue(closed.is_set())
                self.assertEqual(server.calls, [('wait', 'alice')])
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
        self.assertIn('same-task-context-restored-after-cancel', captured.getvalue())

    async def test_upstream_protocol_error_credentials_never_enter_telemetry(self):
        records, requests = [], []
        provider_before = trace.get_tracer_provider()

        class RecordedSpan(trace.NonRecordingSpan):
            def is_recording(self):
                return True

            def set_status(self, status, description=None):
                records.append(('status', getattr(status, 'description', None) or description))

            def set_attributes(self, attributes):
                records.append(('attributes', dict(attributes)))

            def record_exception(self, exception, *args, **kwargs):
                records.append(('exception', str(exception)))

        class RecordingTracer(trace.NoOpTracer):
            @contextmanager
            def start_as_current_span(self, name, **kwargs):
                records.append(('span', name, kwargs.get('attributes')))
                span = RecordedSpan(trace.INVALID_SPAN_CONTEXT)
                with trace.use_span(
                    span, record_exception=kwargs.get('record_exception', True),
                    set_status_on_exception=kwargs.get('set_status_on_exception', True),
                ):
                    yield span

        def upstream_error(request):
            requests.append(request)
            return httpx2.Response(400, request=request, json={
                'jsonrpc': '2.0', 'id': None,
                'error': {'code': -32603, 'message': f'upstream echoed {ALICE_TOKEN}',
                          'data': {'synthetic-private': ALICE_TOKEN}},
            })

        adapter = MCPToolAdapter(descriptor(), url='http://127.0.0.1:1/mcp', allow_loopback_http=True,
                                 http_transport_factory=lambda: httpx2.MockTransport(upstream_error))
        with patch.object(_otel, '_tracer', RecordingTracer()):
            with self.assertRaises(ToolInvocationError) as failure:
                await adapter.invoke(Authority().invocation())
        self.assert_error(failure.exception, 'MCP_TRANSPORT_ERROR')
        self.assertEqual(len(requests), 1)
        self.assertTrue(any(record[0] == 'status' for record in records))
        self.assertIn('MCP_REMOTE_PROTOCOL_ERROR', str(records))
        self.assertNotIn(ALICE_TOKEN, str(records))
        self.assertNotIn('synthetic-private', str(records))
        self.assertIs(trace.get_tracer_provider(), provider_before)

    async def test_cross_origin_redirect_is_not_followed_or_retried(self):
        requests = []

        def redirect(request):
            requests.append(request)
            return httpx2.Response(307, request=request,
                                   headers={'location': 'http://synthetic-untrusted.invalid/mcp'})

        endpoint = 'http://127.0.0.1:1/mcp'
        adapter = MCPToolAdapter(descriptor(), url=endpoint, allow_loopback_http=True,
                                 http_transport_factory=lambda: httpx2.MockTransport(redirect))
        with self.assertRaises(ToolInvocationError) as failure:
            await adapter.invoke(Authority().invocation())
        self.assert_error(failure.exception, 'MCP_TRANSPORT_ERROR')
        self.assertEqual([str(request.url) for request in requests], [endpoint])

    async def test_slow_delete_cannot_extend_cancellation_teardown_indefinitely(self):
        closed = asyncio.Event()

        class ObservedTransport(httpx2.AsyncHTTPTransport):
            async def aclose(self):
                try:
                    await super().aclose()
                finally:
                    closed.set()

        async with MCPProtocolServer(stateless=False) as server:
            server.delete_release.clear()
            server.delete_drip_interval = 0.01
            adapter = MCPToolAdapter(
                descriptor('wait'), url=server.url, allow_loopback_http=True,
                teardown_timeout_seconds=0.1, http_transport_factory=ObservedTransport,
            )
            pending = asyncio.create_task(adapter.invoke(Authority().invocation()))
            await asyncio.wait_for(server.wait_started['alice'].wait(), 2)
            started = asyncio.get_running_loop().time()
            pending.cancel()
            try:
                await asyncio.wait_for(server.delete_started.wait(), 2)
                pending.cancel()
                # A wait with no cancellation side effect makes the deadline
                # assertion independent from the adapter's own cancellation.
                done, _ = await asyncio.wait({pending}, timeout=2)
                self.assertIn(pending, done)
                with self.assertRaises(ToolInvocationError) as failure:
                    await pending
                self.assert_error(failure.exception, 'MCP_CANCELLED')
                self.assertLess(asyncio.get_running_loop().time() - started, 2)
                self.assertTrue(server.delete_started.is_set())
                self.assertGreaterEqual(server.delete_chunks, 2)
                self.assertTrue(closed.is_set())
                self.assertEqual(server.calls, [('wait', 'alice')])
            finally:
                server.delete_release.set()
                if not pending.done():
                    await asyncio.gather(pending, return_exceptions=True)

    async def test_delete_credential_resolution_is_bounded_even_when_callback_blocks(self):
        blocked, release, finished = threading.Event(), threading.Event(), threading.Event()
        closed = asyncio.Event()

        class ObservedTransport(httpx2.AsyncHTTPTransport):
            async def aclose(self):
                try:
                    await super().aclose()
                finally:
                    closed.set()

        async with MCPProtocolServer(stateless=False) as server:
            invocation = Authority().invocation()
            resolve = invocation.resolve_credential

            def blocking_after_tool():
                # Before the result, normal initialize/discovery/tool requests
                # resolve immediately. The next credential lookup is teardown.
                if server.calls:
                    blocked.set()
                    try:
                        release.wait(5)
                    finally:
                        finished.set()
                return resolve()

            adapter = MCPToolAdapter(
                descriptor(), url=server.url, allow_loopback_http=True,
                teardown_timeout_seconds=0.1, http_transport_factory=ObservedTransport,
            )
            pending = asyncio.create_task(adapter.invoke(replace(
                invocation, resolve_credential=blocking_after_tool,
            )))
            try:
                async with asyncio.timeout(2):
                    while not blocked.is_set():
                        await asyncio.sleep(0.005)
                started = asyncio.get_running_loop().time()
                done, _ = await asyncio.wait({pending}, timeout=2)
                self.assertIn(pending, done)
                with self.assertRaises(ToolInvocationError) as failure:
                    await pending
                self.assert_error(failure.exception, 'MCP_AUTHORIZATION_REJECTED')
                self.assertLess(asyncio.get_running_loop().time() - started, 2)
                self.assertTrue(closed.is_set())
                self.assertFalse(finished.is_set())
                self.assertFalse(any(request.method == 'DELETE' for request in server.requests))
                self.assertEqual(server.calls, [('whoami', 'alice')])
            finally:
                release.set()
                if not pending.done():
                    await asyncio.gather(pending, return_exceptions=True)
                if blocked.is_set():
                    self.assertTrue(await asyncio.to_thread(finished.wait, 2))


    async def test_monitor_failure_cannot_mask_sdk_cleanup_failure_before_dispatch(self):
        from mcp import ClientSession

        reject_next_check = threading.Event()
        monitor_rejected = threading.Event()
        sdk_close_failed = asyncio.Event()
        transport_closed = asyncio.Event()
        invocation = Authority().invocation()

        def check():
            invocation.check_authorized()
            if reject_next_check.is_set():
                reject_next_check.clear()
                monitor_rejected.set()
                raise ValueError('Synthetic transient authorization rejection')

        class PausedDiscovery(MCPToolAdapter):
            async def _verify_tool(self, session, state):
                await super()._verify_tool(session, state)
                # With discovery complete, only the authorization monitor can
                # consume this rejection before cancelling the operation.
                reject_next_check.set()
                await asyncio.Event().wait()

        class ObservedTransport(httpx2.AsyncHTTPTransport):
            async def aclose(self):
                await super().aclose()
                transport_closed.set()

        original_exit = ClientSession.__aexit__

        async def unconfirmed_exit(session, *arguments):
            try:
                await original_exit(session, *arguments)
            finally:
                sdk_close_failed.set()
                raise RuntimeError('Synthetic SDK cleanup acknowledgement lost')

        async with MCPProtocolServer(stateless=False) as server:
            adapter = PausedDiscovery(
                descriptor(), url=server.url, allow_loopback_http=True,
                authorization_interval=0.02, http_transport_factory=ObservedTransport,
            )
            with patch.object(ClientSession, '__aexit__', unconfirmed_exit):
                with self.assertRaises(ToolInvocationError) as failure:
                    await adapter.invoke(replace(invocation, check_authorized=check))
            self.assertTrue(monitor_rejected.is_set())
            self.assertTrue(sdk_close_failed.is_set())
            self.assertTrue(transport_closed.is_set())
            self.assertEqual(sum(request.method == 'DELETE' for request in server.requests), 1)
            self.assertEqual(server.calls, [])
            # Successful DELETE and socket close cannot hide the failed SDK
            # cleanup acknowledgement behind the monitor's earlier failure.
            self.assert_error(failure.exception, 'MCP_AUTHORIZATION_REJECTED', outcome='failed')


if __name__ == '__main__':
    unittest.main()

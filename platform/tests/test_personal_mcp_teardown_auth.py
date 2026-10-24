"""Late DELETE credential outcomes cannot turn uncertain custody into success."""
import asyncio
from dataclasses import replace
import threading
import unittest

import httpx2

from agent_factory.personal_mcp import MCPToolAdapter
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.personal_tool_contract import ToolInvocationError
from mcp_protocol_fixture import ALICE_ROTATED_TOKEN, MCPProtocolServer
from test_personal_mcp import Authority, descriptor


class LateTeardownCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def check_late_resolution(self, outcome):
        loop = asyncio.get_running_loop()
        entered, finished, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        release = threading.Event()
        late_calls = []
        completed = []

        class ObservedTransport(httpx2.AsyncHTTPTransport):
            async def aclose(self):
                try:
                    await super().aclose()
                finally:
                    closed.set()

        async with MCPProtocolServer(stateless=False) as server:
            authority = Authority()
            invocation = authority.invocation()
            original_resolve = invocation.resolve_credential

            def resolve():
                if not server.calls:
                    return original_resolve()
                late_calls.append(True)
                loop.call_soon_threadsafe(entered.set)
                try:
                    if not release.wait(3):
                        raise TimeoutError('SYNTHETIC_LATE_CALLBACK_GATE_NOT_RELEASED')
                    if outcome == 'rejected':
                        completed.append('rejected')
                        raise ValueError('SYNTHETIC_LATE_CREDENTIAL_REJECTED')
                    if outcome == 'changed':
                        completed.append('changed')
                        return SecretLease('synthetic-mcp', ALICE_ROTATED_TOKEN)
                    value = original_resolve()
                    completed.append('unchanged')
                    return value
                finally:
                    loop.call_soon_threadsafe(finished.set)

            adapter = MCPToolAdapter(descriptor(), url=server.url,
                teardown_timeout_seconds=0.1, http_transport_factory=ObservedTransport)
            pending = asyncio.create_task(adapter.invoke(replace(invocation, resolve_credential=resolve)))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                # The callback remains gated until actual transport closure:
                # only the original DELETE deadline can advance teardown here.
                await asyncio.wait_for(closed.wait(), 2)
                self.assertFalse(finished.is_set())
                self.assertEqual(len(late_calls), 1)
                release.set()
                await asyncio.wait_for(finished.wait(), 2)
                with self.assertRaises(ToolInvocationError) as raised:
                    await asyncio.wait_for(pending, 2)
                self.assertEqual((raised.exception.code, raised.exception.outcome, raised.exception.stopped),
                                 ('MCP_AUTHORIZATION_REJECTED', 'unknown', False))
                self.assertEqual(completed, [outcome])
                self.assertEqual(len(late_calls), 1, 'The original resolver must not be retried')
                self.assertEqual(server.calls, [('whoami', 'alice')])
                self.assertFalse(any(request.method == 'DELETE' for request in server.requests))
                self.assertFalse(authority.revoked)
            finally:
                release.set()
                if entered.is_set():
                    await asyncio.wait_for(finished.wait(), 2)
                if not pending.done():
                    pending.cancel()
                await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 2)

    async def test_late_same_credential_cannot_clear_unknown_or_retry(self):
        await self.check_late_resolution('unchanged')

    async def test_late_changed_credential_cannot_clear_unknown_or_retry(self):
        await self.check_late_resolution('changed')

    async def test_late_credential_exception_cannot_clear_unknown_or_retry(self):
        await self.check_late_resolution('rejected')


if __name__ == '__main__':
    unittest.main()

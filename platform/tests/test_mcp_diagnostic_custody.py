"""Fixture diagnostics retain late completion evidence without the application graph."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from agent_factory.personal_mcp import MCPToolAdapter
from agent_factory.personal_tool_contract import ToolInvocationError
from test_personal_mcp import descriptor
from test_personal_mcp_capacity_postgres import ObservedMCPAdapter


class Marker:
    pass


class MCPDiagnosticCustodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_callback_updates_diagnostics_without_retaining_graph_or_clearing_unknown(self):
        adapter = ObservedMCPAdapter(descriptor(), url='http://127.0.0.1:1/mcp')
        event = threading.Event()
        marker = Marker()
        graph = weakref.ref(marker)
        invocation = SimpleNamespace(run_context=SimpleNamespace(run_id='original'), call_id='original-call', graph=marker)

        async def completed_sdk(_adapter, value):
            state = SimpleNamespace(invocation=value, dispatched=True, authorization_rejected=True,
                                    sdk_closed=True, transport_closed=True, callbacks_finished=[event])
            adapter.observation(value)['state'] = state
            raise ToolInvocationError('MCP_AUTHORIZATION_REJECTED', outcome='unknown')

        with patch.object(MCPToolAdapter, 'invoke', new=completed_sdk):
            with self.assertRaises(ToolInvocationError) as raised:
                await adapter.invoke(invocation)
        self.assertEqual(raised.exception.outcome, 'unknown')
        self.assertNotIn('state', adapter.observation(invocation))
        del invocation, marker
        self.assertIsNone(graph(), 'Diagnostics must not retain the completed invocation graph')
        before = adapter.diagnostics()[0]
        self.assertEqual((before['callbacksTotal'], before['callbacksDone']), (1, 0))
        event.set()
        after = adapter.diagnostics()[0]
        self.assertEqual((after['callbacksTotal'], after['callbacksDone']), (1, 1))
        self.assertEqual(after['outcome'], 'unknown')
        self.assertFalse(after['stopped'])
        self.assertEqual(after['runId'], 'original')
        self.assertEqual(after['callId'], 'original-call')

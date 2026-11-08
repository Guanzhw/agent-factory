"""Personal MCP tools using Agno discovery and the official MCP session lifecycle."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agno.tools.mcp import MCPTools
from agno.exceptions import RunCancelledException
from agno.run.cancel import araise_if_cancelled
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp import types

from .personal_remote_provider import origin
from .personal_tool_contract import ToolDescriptor, ToolInvocation, ToolInvocationError


def mcp_url(value: str) -> str:
    parsed = urlsplit(value)
    destination = origin(urlunsplit((parsed.scheme, parsed.netloc, '', '', '')))
    return destination + (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')


class MCPRunConnections:
    """Connections owned by one native execution, closed by Agno's run finally."""
    def __init__(self):
        self._stack = AsyncExitStack()
        self._sessions = {}
        self._locks = {}
        self._closed = False

    @asynccontextmanager
    async def tools(self, key, url, credential, *, timeout_seconds=None, names=None):
        async with self._locks.setdefault(key, asyncio.Lock()):
            if self._closed:
                raise RuntimeError('MCP_RUN_ENDED')
            if key not in self._sessions:
                manager = _tools(url, credential, timeout_seconds=timeout_seconds, names=names)
                connection = await manager.__aenter__()
                if self._closed:
                    await manager.__aexit__(None, None, None)
                    raise RuntimeError('MCP_RUN_ENDED')
                self._stack.push_async_exit(manager)
                self._sessions[key] = connection
            connection = self._sessions[key]
        yield connection

    async def close(self):
        self._closed = True
        try:
            await self._stack.aclose()
        finally:
            self._sessions.clear()
            self._locks.clear()


@asynccontextmanager
async def _tools(url, credential, *, timeout_seconds: float | None = None, names=None):
    headers = {'Authorization': 'Bearer ' + credential.password} if credential is not None else {}
    transport = StreamableHttpTransport(url, headers=headers, max_sse_event_size=None)
    # FastMCP owns the underlying AnyIO session in its own task, so parallel tool
    # tasks can enter and the native run's finally can close it safely.
    async with Client(transport, timeout=timeout_seconds, init_timeout=0, mode='legacy') as client:
        session = client.session
        tools = MCPTools(session=session, include_tools=names)
        await tools.build_tools()
        yield tools, session


async def discover_mcp_tools(url: str, *, resolve_credential=lambda: None,
                             check_authorized=lambda: None, timeout_seconds: float | None = None) -> list[dict]:
    await asyncio.to_thread(check_authorized)
    credential = await asyncio.to_thread(resolve_credential)
    async with _tools(mcp_url(url), credential, timeout_seconds=timeout_seconds) as (tools, _):
        return [{'name': name, 'description': function.description or name,
                 'inputSchema': function.parameters, 'readOnly': False}
                for name, function in tools.functions.items()]


class MCPToolAdapter:
    def __init__(self, descriptor: ToolDescriptor, *, url: str,
                 remote_tool_name: str | None = None):
        self.descriptor = descriptor
        self._url = mcp_url(url)
        self._remote_tool_name = remote_tool_name or descriptor.tool_name
        self._timeout = descriptor.timeout_seconds

    async def invoke(self, invocation: ToolInvocation) -> dict[str, Any]:
        credential = await asyncio.to_thread(invocation.resolve_credential)
        dispatched = False
        result: Any = None
        async def call():
            nonlocal dispatched, result
            connections = invocation.mcp_connections
            connection = (_tools(self._url, credential, timeout_seconds=self._timeout,
                    names=[self._remote_tool_name]) if connections is None else
                connections.tools((invocation.owner_id, invocation.connection_ref, invocation.connection_revision,
                    self.descriptor.adapter_id, self.descriptor.revision), self._url, credential,
                    timeout_seconds=self._timeout, names=[self._remote_tool_name]))
            async with connection as (_, session):
                await asyncio.to_thread(invocation.check_authorized)
                dispatched = True
                # Use the official session result rather than Agno's text-only
                # error projection: callers need actual is_error and structured
                # output. Input-required must not automatically resend the call.
                result = await session.call_tool(self._remote_tool_name, dict(invocation.arguments),
                    read_timeout_seconds=self._timeout, allow_input_required=True)
        task = asyncio.create_task(call())
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=.1)
                await araise_if_cancelled(invocation.run_context.run_id)
            await task
        except (asyncio.CancelledError, RunCancelledException):
            raise
        except Exception as error:
            if result is None:
                raise ToolInvocationError('MCP_' + type(error).__name__.upper(),
                    outcome='unknown' if dispatched else 'failed', stopped=not dispatched) from error
            # A received business result remains valid if session cleanup fails.
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if not isinstance(result, types.CallToolResult):
            raise ToolInvocationError('MCP_INPUT_REQUIRED')
        output = {'content': [item.model_dump(mode='json', by_alias=True, exclude_none=True)
                              for item in result.content]}
        if result.structured_content is not None:
            output['structuredContent'] = result.structured_content
        if result.is_error:
            raise ToolInvocationError('MCP_REMOTE_ERROR', outcome='failed', stopped=True, output=output)
        return output

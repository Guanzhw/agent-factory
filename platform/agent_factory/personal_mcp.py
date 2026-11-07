"""Personal MCP tools using Agno discovery and the official MCP session lifecycle."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agno.tools.mcp import MCPTools
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from .personal_remote_provider import origin
from .personal_tool_contract import ToolDescriptor, ToolInvocation, ToolInvocationError


def mcp_url(value: str) -> str:
    parsed = urlsplit(value)
    destination = origin(urlunsplit((parsed.scheme, parsed.netloc, '', '', '')))
    return destination + (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')


@asynccontextmanager
async def _tools(url, credential, *, timeout_seconds: float | None = None, names=None):
    headers = {'Authorization': 'Bearer ' + credential.password} if credential is not None else {}
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(url, http_client=http, max_sse_event_size=None) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timeout_seconds) as session:
                tools = MCPTools(session=session, include_tools=names)
                # Agno initialize()/connect() swallow handshake errors. Use the
                # SDK handshake and Agno's public discovery method so a failed
                # connection is reported before any business call is attempted.
                await session.initialize()
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
        await asyncio.to_thread(invocation.check_authorized)
        credential = await asyncio.to_thread(invocation.resolve_credential)
        dispatched = False
        result = None
        try:
            async with _tools(self._url, credential, timeout_seconds=self._timeout,
                    names=[self._remote_tool_name]) as (_, session):
                dispatched = True
                # Use the official session result rather than Agno's text-only
                # error projection: callers need actual is_error and structured
                # output. Input-required must not automatically resend the call.
                result = await session.call_tool(self._remote_tool_name, dict(invocation.arguments),
                    read_timeout_seconds=self._timeout, allow_input_required=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if result is None:
                raise ToolInvocationError('MCP_' + type(error).__name__.upper(),
                    outcome='unknown' if dispatched else 'failed', stopped=not dispatched) from error
            # A received business result remains valid if session cleanup fails.
        if not isinstance(result, types.CallToolResult):
            raise ToolInvocationError('MCP_INPUT_REQUIRED')
        output = {'content': [item.model_dump(mode='json', by_alias=True, exclude_none=True)
                              for item in result.content]}
        if result.structured_content is not None:
            output['structuredContent'] = result.structured_content
        if result.is_error:
            raise ToolInvocationError('MCP_REMOTE_ERROR', outcome='failed', stopped=True, output=output)
        return output

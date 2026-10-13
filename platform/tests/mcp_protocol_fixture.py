"""Real loopback MCP protocol fixture; every credential below is synthetic."""

from __future__ import annotations

import asyncio
import contextlib
import socket
from dataclasses import dataclass
from copy import deepcopy

import uvicorn
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

ALICE_TOKEN = 'synthetic-mcp-alice-v1'
ALICE_ROTATED_TOKEN = 'synthetic-mcp-alice-v2'
BOB_TOKEN = 'synthetic-mcp-bob-v1'


@dataclass(frozen=True)
class HTTPRequest:
    method: str
    headers: dict[str, str]
    owner: str | None
    session_id: str | None


class MCPProtocolServer:
    """Use ``async with``; mutate ``tokens`` to simulate server-side rotation.

    ``requests`` records accepted and rejected HTTP requests. ``calls`` records
    actual tool execution. Blocking calls are controlled by owner-specific
    ``wait_started``/``wait_release`` events; cancellation records the owner in
    ``wait_cancelled``. Clear ``delete_release`` to pause session teardown until
    the test sets it again; set ``delete_drip_interval`` to stream response bytes
    while paused. ``tool_schemas`` and ``response_headers`` can inject
    synthetic peer responses. This fixture never contacts an external service.
    """

    def __init__(self, *, stateless: bool = True) -> None:
        self.tokens = {ALICE_TOKEN: 'alice', BOB_TOKEN: 'bob'}
        self.requests: list[HTTPRequest] = []
        self.calls: list[tuple[str, str]] = []
        self.wait_started = {owner: asyncio.Event() for owner in ('alice', 'bob')}
        self.wait_release = {owner: asyncio.Event() for owner in ('alice', 'bob')}
        self.wait_cancelled: set[str] = set()
        self.delete_started = asyncio.Event()
        self.delete_release = asyncio.Event()
        self.delete_release.set()
        self.delete_drip_interval: float | None = None
        self.delete_chunks = 0
        self.tool_schemas: dict[str, dict] = {}
        self.response_headers: dict[str, str] = {}
        self.url = ''
        self.closed = False
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        async def declared_schema(ctx, call_next):
            result = await call_next(ctx)
            if ctx.method == 'tools/list':
                for tool in result['tools']:
                    if tool['name'] in self.tool_schemas:
                        tool['inputSchema'] = deepcopy(self.tool_schemas[tool['name']])
            return result

        server = MCPServer('synthetic-owner-tools', log_level='ERROR', middleware=[declared_schema])

        def identity(ctx: Context) -> tuple[str, str]:
            request: Request = ctx.request_context.request
            return request.state.fixture_owner, request.headers['authorization']

        @server.tool(structured_output=True)
        async def whoami(ctx: Context) -> dict[str, str]:
            """Return the authenticated synthetic owner."""
            owner, _ = identity(ctx)
            self.calls.append(('whoami', owner))
            return {'owner': owner}

        @server.tool(structured_output=True)
        async def echo(value: str, ctx: Context) -> dict[str, str]:
            """Echo a value alongside the authenticated owner."""
            owner, _ = identity(ctx)
            self.calls.append(('echo', owner))
            return {'owner': owner, 'value': value}

        @server.tool(structured_output=True)
        async def wait(ctx: Context) -> dict[str, str]:
            """Wait until the test releases this owner's tool call."""
            owner, _ = identity(ctx)
            self.calls.append(('wait', owner))
            self.wait_started[owner].set()
            try:
                await self.wait_release[owner].wait()
            except asyncio.CancelledError:
                self.wait_cancelled.add(owner)
                raise
            return {'owner': owner, 'status': 'released'}

        @server.tool(structured_output=False)
        async def error(ctx: Context) -> CallToolResult:
            """Return an error containing only a synthetic credential."""
            owner, authorization = identity(ctx)
            self.calls.append(('error', owner))
            return CallToolResult(is_error=True, content=[TextContent(
                type='text', text=f'synthetic upstream failure: {authorization}',
            )])

        @server.tool(structured_output=True)
        async def secret_echo(ctx: Context) -> dict[str, str]:
            """Return synthetic auth so adapter redaction can be tested."""
            owner, authorization = identity(ctx)
            self.calls.append(('secret_echo', owner))
            return {'owner': owner, 'authorization': authorization}

        self._app = server.streamable_http_app(
            stateless_http=stateless,
            json_response=False,
            session_idle_timeout=5,
        )

    async def _authenticated(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] == 'http':
            headers = {
                key.decode('latin-1').lower(): value.decode('latin-1')
                for key, value in scope['headers']
            }
            authorization = headers.get('authorization', '')
            token = authorization.removeprefix('Bearer ')
            owner = self.tokens.get(token) if authorization.startswith('Bearer ') else None
            self.requests.append(HTTPRequest(
                method=scope['method'], headers=headers, owner=owner,
                session_id=headers.get('mcp-session-id'),
            ))
            if owner is None:
                await send({'type': 'http.response.start', 'status': 401, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'Synthetic authentication required'})
                return
            scope.setdefault('state', {})['fixture_owner'] = owner
            if scope['method'] == 'DELETE':
                self.delete_started.set()
                if self.delete_drip_interval is not None:
                    await send({'type': 'http.response.start', 'status': 200,
                                'headers': [(b'content-type', b'application/json')]})
                    while not self.delete_release.is_set():
                        await send({'type': 'http.response.body', 'body': b' ', 'more_body': True})
                        self.delete_chunks += 1
                        try:
                            await asyncio.wait_for(self.delete_release.wait(), self.delete_drip_interval)
                        except TimeoutError:
                            pass
                    await send({'type': 'http.response.body', 'body': b'{}', 'more_body': False})
                    return
                await self.delete_release.wait()

        async def response(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': [
                    *message.get('headers', []),
                    *((name.encode('latin-1'), value.encode('latin-1'))
                      for name, value in self.response_headers.items()),
                ]}
            await send(message)

        await self._app(scope, receive, response)

    async def __aenter__(self) -> MCPProtocolServer:
        if self._task is not None or self.closed:
            raise RuntimeError('Use a new MCPProtocolServer for each context')
        self._socket = socket.socket()
        self._socket.bind(('127.0.0.1', 0))
        self._socket.listen()
        self._socket.setblocking(False)
        port = self._socket.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}/mcp'
        self._server = uvicorn.Server(uvicorn.Config(
            self._authenticated, host='127.0.0.1', port=port,
            interface='asgi3', log_level='error', access_log=False,
            timeout_graceful_shutdown=1,
        ))
        self._task = asyncio.create_task(self._server.serve(sockets=[self._socket]))
        try:
            async with asyncio.timeout(5):
                while not self._server.started:
                    if self._task.done():
                        await self._task
                        raise RuntimeError('Synthetic MCP server exited before startup')
                    await asyncio.sleep(0.005)
        except BaseException:
            await self.aclose()
            raise
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        for event in self.wait_release.values():
            event.set()
        self.delete_release.set()
        if self._server is not None:
            self._server.should_exit = True
        try:
            if self._task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), timeout=3)
                except TimeoutError:
                    self._task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.wait_for(self._task, timeout=1)
        finally:
            if self._socket is not None:
                self._socket.close()

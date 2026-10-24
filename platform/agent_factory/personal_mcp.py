"""Owner-authenticated HTTP MCP adapter over the official SDK.

Each invocation owns one client/session; only the declared tool/schema is shared.
Use the SDK's session API deliberately: the higher-level Client can automatically
redispatch tools/call for input requests or a changed schema. Receipts/recovery
belong to core, and closing this transport never proves remote work stopped.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
import json
import logging
import math
import threading
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx2
from anyio.abc import ObjectReceiveStream
from jsonschema import Draft202012Validator
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage
from referencing import Registry

from .personal_remote_provider import SecretLease, origin, reject_credential_echo
from .personal_tool_contract import ToolDescriptor, ToolInvocation, ToolInvocationError


_private_wire: ContextVar[bool] = ContextVar('personal_mcp_private_wire', default=False)
_CLOSE_DEADLINE = 'agent_factory_mcp_close_deadline'


def mcp_url(value: str) -> str:
    """Normalize member-selected HTTP(S) endpoints, preserving the MCP path."""
    try:
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment or any(ord(char) < 33 for char in value):
            raise ValueError()
        destination = origin(urlunsplit((parsed.scheme, parsed.netloc, '', '', '')))
        return destination + (parsed.path or '/')
    except Exception:
        raise ValueError('MCP_CONFIGURATION_INVALID') from None


async def discover_mcp_tools(url: str, *, resolve_credential=lambda: None,
                             check_authorized=lambda: None, timeout_seconds: float = 30) -> list[dict]:
    """Read tools/list through the official SDK; never dispatch a business tool."""
    endpoint = httpx2.URL(mcp_url(url))
    invocation = ToolInvocation('', '', '', '', {}, None, check_authorized, resolve_credential)
    state = _InvocationState(invocation)
    marker = _private_wire.set(True)
    try:
        async with asyncio.timeout(timeout_seconds):
            transport = _BoundedTransport(httpx2.AsyncHTTPTransport(retries=0, trust_env=False), 1048576, state)
            async with httpx2.AsyncClient(auth=_OwnerAuth(state, endpoint, 2), transport=transport,
                    timeout=timeout_seconds, trust_env=False, follow_redirects=False) as http:
                async with streamable_http_client(str(endpoint), http_client=http, terminate_on_close=True) as (reader, writer):
                    async with ClientSession(_PrivateErrors(reader), writer, read_timeout_seconds=timeout_seconds) as session:
                        await session.initialize()
                        cursor = None
                        seen = set()
                        tools = []
                        for _ in range(32):
                            await state.check()
                            page = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
                            for tool in page.tools:
                                value = {'name': tool.name, 'description': tool.description or tool.name,
                                    'inputSchema': tool.input_schema,
                                    'readOnly': bool(tool.annotations and tool.annotations.read_only_hint)}
                                reject_credential_echo(value, state.lease)
                                tools.append(value)
                            cursor = page.next_cursor
                            if not cursor:
                                return tools
                            if cursor in seen:
                                break
                            seen.add(cursor)
                        raise ValueError('MCP_DISCOVERY_LIMIT')
    except Exception:
        raise ValueError('MCP_DISCOVERY_FAILED') from None
    finally:
        state.lease = None
        _private_wire.reset(marker)


class _PrivateWireFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # SDK debug records include whole messages; even exception records can
        # contain upstream payloads. Keep other MCP users' logging unchanged.
        return not _private_wire.get()


for _logger_name in (
    'mcp.client.streamable_http', 'client', 'mcp.shared.jsonrpc_dispatcher',
    'mcp.shared.dispatcher', 'mcp.shared.tool_name_validation',
    'httpx2', 'httpcore2.connection', 'httpcore2.http11', 'httpcore2.http2',
    'httpcore2.proxy', 'httpcore2.socks',
):
    logging.getLogger(_logger_name).addFilter(_PrivateWireFilter())


def _schema_contract(value: Any) -> Any:
    """Ignore human-readable annotations, preserving all validation keywords."""
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {'title', 'description', '$comment'}:
            continue
        if key in {'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'}:
            item = {name: _schema_contract(schema) for name, schema in item.items()}
        elif key in {'allOf', 'anyOf', 'oneOf', 'prefixItems'}:
            item = [_schema_contract(schema) for schema in item]
        elif key in {'additionalProperties', 'unevaluatedProperties', 'propertyNames', 'items',
                     'unevaluatedItems', 'contains', 'not', 'if', 'then', 'else'}:
            item = _schema_contract(item)
        # Object property names and literal enum/const values are data, even
        # when they happen to be named title or description.
        result[key] = item
    return result


def _known_error(error: Exception) -> ToolInvocationError | None:
    # AnyIO wraps exceptions raised inside session/transport contexts. Recover
    # our fixed diagnostic only when all leaves agree; never stringify an
    # upstream exception or accidentally label a mixed failure as definitive.
    pending: list[BaseException] = [error]
    errors: list[ToolInvocationError] = []
    while pending:
        item = pending.pop()
        if isinstance(item, BaseExceptionGroup):
            pending.extend(item.exceptions)
        elif isinstance(item, ToolInvocationError):
            errors.append(item)
        else:
            return None
    if errors and all((item.code, item.outcome, item.stopped) ==
                      (errors[0].code, errors[0].outcome, errors[0].stopped) for item in errors):
        return errors[0]
    return None


@dataclass
class _InvocationState:
    invocation: ToolInvocation = field(repr=False)
    lease: SecretLease | None = field(default=None, repr=False)
    dispatched: bool = False
    authorization_rejected: bool = False
    transport_started: bool = False
    transport_closed: bool = False
    sdk_closed: bool = False
    initialized: bool = False
    initialization_refused: bool = False
    callbacks_finished: list[threading.Event] = field(default_factory=list, repr=False)

    def error(self, code: str) -> ToolInvocationError:
        return ToolInvocationError(code, outcome='unknown' if self.dispatched else 'failed')

    async def checked_callback(self, callback):
        finished = threading.Event()
        self.callbacks_finished.append(finished)

        def call():
            try:
                return callback()
            finally:
                finished.set()

        # Cancelling to_thread's await does not stop the synchronous callback.
        return await asyncio.to_thread(call)

    def stopped_before_dispatch(self) -> bool:
        # Called only after the invocation's operation and monitor have joined.
        # Remote idle-session DELETE is best effort (405 is valid MCP). Before
        # tools/call, only the invocation's local work must be confirmed stopped.
        return (not self.dispatched and all(event.is_set() for event in self.callbacks_finished)
                and (not self.transport_started or (self.transport_closed and self.sdk_closed)))

    async def check(self) -> None:
        try:
            await self.checked_callback(self.invocation.check_authorized)
        except Exception:
            self.authorization_rejected = True
            raise self.error('MCP_AUTHORIZATION_REJECTED') from None

    async def credential(self) -> SecretLease | None:
        await self.check()
        try:
            lease = await self.checked_callback(self.invocation.resolve_credential)
            if (lease is not None and not isinstance(lease, SecretLease)) or (self.lease is not None and lease != self.lease):
                raise ValueError()
        except Exception:
            self.authorization_rejected = True
            raise self.error('MCP_AUTHORIZATION_REJECTED') from None
        await self.check()
        self.lease = lease
        return lease


class _OwnerAuth(httpx2.Auth):
    def __init__(self, state: _InvocationState, endpoint: httpx2.URL, teardown_timeout_seconds: float):
        self._state, self._endpoint = state, endpoint
        self._teardown_timeout_seconds = teardown_timeout_seconds

    async def async_auth_flow(self, request: httpx2.Request):
        if request.url != self._endpoint:
            raise self._state.error('MCP_DESTINATION_REJECTED')
        deadline = None
        if request.method == 'DELETE':
            # One total bound spans fresh authorization, response headers and
            # every body chunk. An inactivity timeout cannot bound drip feeds.
            deadline = asyncio.get_running_loop().time() + self._teardown_timeout_seconds
            request.extensions[_CLOSE_DEADLINE] = deadline
        try:
            async with asyncio.timeout_at(deadline):
                lease = await self._state.credential()
                if lease is not None:
                    request.headers['authorization'] = 'Bearer ' + lease.password
        except TimeoutError:
            # The SDK swallows DELETE failures. Preserve an incomplete auth
            # check so the completed operation cannot bypass the final guard.
            self._state.authorization_rejected = True
            raise self._state.error('MCP_AUTHORIZATION_REJECTED') from None
        yield request


class _BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream, limit: int, state: _InvocationState,
                 deadline: float | None = None, on_eof: Callable[[], None] | None = None):
        self._stream, self._limit, self._state = stream, limit, state
        self._deadline = deadline
        self._on_eof = on_eof

    async def __aiter__(self):
        size = 0
        iterator = self._stream.__aiter__()
        while True:
            try:
                async with asyncio.timeout_at(self._deadline):
                    chunk = await anext(iterator)
            except StopAsyncIteration:
                if self._on_eof is not None:
                    self._on_eof()
                return
            size += len(chunk)
            if size > self._limit:
                raise self._state.error('MCP_RESPONSE_LIMIT')
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class _BoundedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, transport: httpx2.AsyncBaseTransport, limit: int, state: _InvocationState):
        self._transport, self._limit, self._state = transport, limit, state
        state.transport_started = True

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        request.headers['accept-encoding'] = 'identity'
        deadline = request.extensions.pop(_CLOSE_DEADLINE, None)
        async with asyncio.timeout_at(deadline):
            response = await self._transport.handle_async_request(request)

        def received():
            if response.status_code in {401, 403} and not self._state.initialized:
                self._state.initialization_refused = True

        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
            await response.aclose()
            raise self._state.error('MCP_ENCODING_REJECTED')
        if not isinstance(response.stream, httpx2.AsyncByteStream):
            raise self._state.error('MCP_TRANSPORT_ERROR')
        if response.is_stream_consumed:
            received()
        response.stream = _BoundedStream(response.stream, self._limit, self._state, deadline, received)
        if response.status_code in {401, 403} and not self._state.initialized:
            # The SDK skips non-JSON error bodies. Drain this bounded refusal
            # to distinguish a complete preflight rejection from a lost reply.
            try:
                await response.aread()
            finally:
                await response.aclose()
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()
        self._state.transport_closed = True


class _PrivateErrors(ObjectReceiveStream[SessionMessage | Exception]):
    """Keep remote error prose out of the SDK's OpenTelemetry span status.

    This connection-local stream preserves correlation and protocol codes;
    tracing remains enabled and no global tracer configuration is changed.
    """

    def __init__(self, stream: Any):
        self._stream = stream

    @property
    def last_context(self):
        return getattr(self._stream, 'last_context', None)

    async def receive(self) -> SessionMessage | Exception:
        item = await self._stream.receive()
        if isinstance(item, SessionMessage) and isinstance(item.message, types.JSONRPCError):
            message = item.message.model_copy(update={'error': types.ErrorData(
                code=item.message.error.code, message='MCP_REMOTE_PROTOCOL_ERROR',
            )})
            return replace(item, message=message)
        if isinstance(item, Exception) and not isinstance(item, ToolInvocationError):
            return ToolInvocationError('MCP_TRANSPORT_ERROR')
        return item

    async def aclose(self) -> None:
        await self._stream.aclose()


class MCPToolAdapter:
    """Member or installed HTTP endpoint and one declared native tool.

    ``http_transport_factory`` is a trusted test/deployment injection, created
    separately for every invocation. Credentials never live on this adapter.
    Stateful and stateless servers use the same per-invocation lifecycle, so
    there are no idle sessions or authentication pools to share across owners.
    HTTP and HTTPS support local, private and public endpoints on custom ports.
    ``teardown_timeout_seconds`` bounds the whole session DELETE,
    including authorization and a continuously streaming response.
    """

    def __init__(self, descriptor: ToolDescriptor, *, url: str,
                 remote_tool_name: str | None = None, authorization_interval: float = 0.05,
                 teardown_timeout_seconds: float = 2.0,
                 http_transport_factory: Callable[[], httpx2.AsyncBaseTransport] | None = None):
        url = mcp_url(url)
        if (descriptor.transport != 'mcp'
                or not math.isfinite(descriptor.timeout_seconds) or descriptor.timeout_seconds <= 0
                or descriptor.max_output_bytes < 1
                or not math.isfinite(authorization_interval) or authorization_interval <= 0
                or not math.isfinite(teardown_timeout_seconds) or teardown_timeout_seconds <= 0):
            raise ValueError('MCP_CONFIGURATION_INVALID')
        self.descriptor = descriptor
        self._endpoint = httpx2.URL(url)
        self._remote_tool_name = remote_tool_name or descriptor.tool_name
        self._schema = json.loads(json.dumps(dict(descriptor.input_schema), allow_nan=False))
        Draft202012Validator.check_schema(self._schema)
        # Match the SDK's JSON schema comparison: Python equality conflates
        # True/1 and False/0, including nested const and enum values.
        self._schema_json = json.dumps(_schema_contract(self._schema), sort_keys=True, allow_nan=False)
        # No implicit network retrieval for an external schema reference.
        self._validator = Draft202012Validator(self._schema, registry=Registry())
        self._authorization_interval = authorization_interval
        self._teardown_timeout_seconds = teardown_timeout_seconds
        self._http_transport_factory = http_transport_factory

    async def invoke(self, invocation: ToolInvocation) -> dict[str, Any]:
        state = _InvocationState(invocation)
        marker = _private_wire.set(True)
        operation: asyncio.Task | None = None
        monitor: asyncio.Task | None = None
        failure: ToolInvocationError | None = None
        try:
            # Copy caller-owned data once; neither discovery nor schema checking
            # grants the server permission to add arguments to this invocation.
            try:
                arguments = json.loads(json.dumps(dict(invocation.arguments), allow_nan=False))
                self._validator.validate(arguments)
            except Exception:
                raise state.error('MCP_ARGUMENTS_INVALID') from None
            await state.credential()
            operation = asyncio.create_task(self._run(state, arguments))
            monitor = asyncio.create_task(self._watch_authorization(state))
            done, _ = await asyncio.wait(
                {operation, monitor}, timeout=self.descriptor.timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if monitor in done:
                await monitor
            if operation not in done:
                raise state.error('MCP_TIMEOUT')
            output = await operation
            await state.check()
            # Session termination is best effort in the SDK. It can swallow a
            # rejected DELETE credential after the tool result was received.
            if state.authorization_rejected:
                raise state.error('MCP_AUTHORIZATION_REJECTED')
            return output
        except asyncio.CancelledError:
            failure = state.error('MCP_CANCELLED')
            raise failure from None
        except ToolInvocationError as error:
            failure = error
            raise
        except Exception as error:
            known = _known_error(error)
            if known is not None:
                failure = known
            elif state.authorization_rejected:
                failure = state.error('MCP_AUTHORIZATION_REJECTED')
            elif state.initialization_refused:
                failure = state.error('MCP_TRANSPORT_ERROR')
            else:
                failure = ToolInvocationError('MCP_TRANSPORT_ERROR', outcome='unknown')
            raise failure from None
        finally:
            # The operation enters AND exits the SDK's AnyIO contexts in its
            # own task. Waiting for it closes HTTP/session resources on all exits.
            cancelled_during_close = False
            try:
                for task in (operation, monitor):
                    if task is not None and not task.done():
                        task.cancel()

                async def settle():
                    await asyncio.gather(
                        *(task for task in (operation, monitor) if task is not None), return_exceptions=True,
                    )
                    if not state.dispatched and failure is not None and failure.outcome == 'failed':
                        # A cancelled monitor can leave an ordinary short DB
                        # check finishing in its worker thread. Allow bounded
                        # settlement; an actually blocked callback still holds.
                        deadline = asyncio.get_running_loop().time() + self._teardown_timeout_seconds
                        while not all(event.is_set() for event in state.callbacks_finished):
                            remaining = deadline - asyncio.get_running_loop().time()
                            if remaining <= 0:
                                break
                            await asyncio.sleep(min(0.01, remaining))

                cleanup = asyncio.create_task(settle())
                # A second caller cancellation must not interrupt the SDK's
                # in-task __aexit__ while its session DELETE is in progress.
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        cancelled_during_close = True
            finally:
                state.lease = None
                _private_wire.reset(marker)
            if cancelled_during_close:
                failure = state.error('MCP_CANCELLED')
            if failure is not None and failure.outcome == 'failed':
                failure.stopped = state.stopped_before_dispatch()
            if cancelled_during_close and failure is not None:
                raise failure from None

    async def _watch_authorization(self, state: _InvocationState) -> None:
        while True:
            await asyncio.sleep(self._authorization_interval)
            await state.check()

    async def _run(self, state: _InvocationState, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_transport = self._http_transport_factory() if self._http_transport_factory else httpx2.AsyncHTTPTransport(
            retries=0, trust_env=False,
        )
        transport = _BoundedTransport(raw_transport, max(1048576, self.descriptor.max_output_bytes * 2), state)
        body_error: BaseException | None = None
        output: dict[str, Any] = {}
        async with httpx2.AsyncClient(
            auth=_OwnerAuth(state, self._endpoint, self._teardown_timeout_seconds), transport=transport,
            timeout=self.descriptor.timeout_seconds, trust_env=False,
            follow_redirects=False, max_redirects=0,
        ) as http:
            async with streamable_http_client(
                str(self._endpoint), http_client=http, terminate_on_close=True,
                max_sse_event_size=max(65536, self.descriptor.max_output_bytes * 2),
            ) as (read_stream, write_stream):
                async with ClientSession(
                    _PrivateErrors(read_stream), write_stream, read_timeout_seconds=self.descriptor.timeout_seconds,
                ) as session:
                    try:
                        output = await self._call(session, state, arguments)
                    except BaseException as error:
                        # Preserve the body failure separately: transport close
                        # alone cannot prove the SDK's contexts exited cleanly.
                        body_error = error
        state.sdk_closed = True
        if body_error is not None:
            raise body_error
        return output

    async def _call(self, session: ClientSession, state: _InvocationState,
                    arguments: dict[str, Any]) -> dict[str, Any]:
        await session.initialize()
        state.initialized = True
        await self._verify_tool(session, state)
        await state.credential()
        state.dispatched = True
        result = await session.call_tool(
            self._remote_tool_name, arguments,
            read_timeout_seconds=self.descriptor.timeout_seconds,
            allow_input_required=True,
        )
        await state.check()
        if not isinstance(result, types.CallToolResult):
            raise state.error('MCP_INPUT_REQUIRED')
        if result.is_error:
            raise ToolInvocationError('MCP_REMOTE_ERROR', outcome='failed')
        output = {'content': [item.model_dump(mode='json', by_alias=True, exclude_none=True)
                              for item in result.content]}
        if result.structured_content is not None:
            output['structuredContent'] = result.structured_content
        try:
            reject_credential_echo(output, state.lease)
        except Exception:
            raise state.error('MCP_CREDENTIAL_ECHO_REJECTED') from None
        if len(json.dumps(output, ensure_ascii=False, allow_nan=False).encode()) > self.descriptor.max_output_bytes:
            raise state.error('MCP_OUTPUT_LIMIT')
        return output

    async def _verify_tool(self, session: ClientSession, state: _InvocationState) -> None:
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(32):
            page = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
            for tool in page.tools:
                if tool.name == self._remote_tool_name:
                    remote_schema_json = json.dumps(_schema_contract(tool.input_schema), sort_keys=True, allow_nan=False)
                    if remote_schema_json != self._schema_json:
                        raise state.error('MCP_SCHEMA_CHANGED')
                    return
            cursor = page.next_cursor
            if not cursor:
                raise state.error('MCP_TOOL_NOT_FOUND')
            if cursor in seen:
                break
            seen.add(cursor)
        raise state.error('MCP_DISCOVERY_LIMIT')

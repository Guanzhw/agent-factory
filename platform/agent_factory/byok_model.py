"""Native Agno execution for the shared text/function-tool protocols.

No SDK environment key lookup, redirects, proxies, retry, discovery or billing.
Each invocation resolves the exact owner/vault revision and pins public DNS.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse


# Re-export the established names for callers while keeping endpoint policy,
# transport and protocol conversion independent of the Agno execution adapter.
from .model_endpoint_policy import (
    CLIENT_USER_AGENT as CLIENT_USER_AGENT, GO_BASE as GO_BASE,
    GO_CURRENT_BASE as GO_CURRENT_BASE, base_url as base_url,
    chat_headers as chat_headers, continuation_scope,
    generation_options as generation_options, model_id as model_id,
    model_origin as model_origin, max_output_tokens,
)
from .model_protocol import (
    assistant_message_matches, decode_response, encode_request, function_call as function_call,
    protocol_name, protocol_path,
)
from .model_transport import MAX_BYTES as MAX_BYTES, PinnedChatTransport as PinnedChatTransport
from .model_stream import read_model_stream
from .personal_remote_provider import PinnedHTTPSProbe as PinnedHTTPSProbe

PROVIDER_ID = 'byok-chat-v1'
ADAPTER_ID = 'owner-chat-completions-v1'
CAPABILITY = 'model:invoke'


def rejected(code='PERSONAL_MODEL_RESPONSE_REJECTED'):
    return ModelProviderError(message=code, status_code=400, model_name='Owner Model')


class OwnerChatModel(Model):
    def __init__(self, configuration, credential: Callable, *, transport_factory=None, recheck=None, session_id=None,
            trusted_proxy=None, timeout_seconds=300, on_text=None):
        super().__init__(id=model_id(configuration['model']), provider=configuration['provider'],
            name='Owner Model', retries=0)
        self._base = base_url(configuration['baseURL'])
        self._protocol = protocol_name(configuration)
        self._max_output_tokens = max_output_tokens(configuration)
        self._scope = continuation_scope(configuration)
        generation_options(configuration)
        self._thinking_mode = configuration.get('thinkingMode')
        self._credential = credential
        self._timeout_seconds = timeout_seconds
        self._on_text = on_text
        self.context_window = configuration.get("contextWindow")
        self.auto_compact_token_limit = configuration.get("autoCompactTokenLimit")
        self.factory_wire_stream = True
        self._transport_factory = transport_factory
        if transport_factory is not None and trusted_proxy is not None:
            raise ValueError('TRUSTED_MODEL_PROXY_CONFIGURATION_INVALID')
        if trusted_proxy is not None:
            from .trusted_model_proxy import TrustedModelProxy
            if (not isinstance(trusted_proxy, TrustedModelProxy)
                    or trusted_proxy.select(configuration.get('ownerId'), configuration,
                        trusted_proxy.environment_id) is not trusted_proxy):
                raise ValueError('TRUSTED_MODEL_PROXY_SCOPE_CHANGED')
        self._trusted_proxy = trusted_proxy
        self._recheck = recheck
        self._session_id = session_id or 'af-agent-' + uuid4().hex

    def __repr__(self):
        return 'OwnerChatModel(credentials=<redacted>)'

    def _body(self, messages, *, tools=None, tool_choice=None, response_format=None, **kwargs):
        if response_format is not None:
            raise rejected('PERSONAL_MODEL_UNSUPPORTED_FORMAT')
        encoded, continuation = [], []
        for index, message in enumerate(messages):
            if (message.role not in {'system', 'user', 'assistant', 'tool'}
                    or message.content is not None and type(message.content) is not str
                    or any(getattr(message, field, None) for field in ('images', 'videos', 'audio', 'files'))):
                raise rejected('PERSONAL_MODEL_TEXT_ONLY')
            item = {'role': message.role, 'content': message.content}
            if message.role == 'tool': item['tool_call_id'] = message.tool_call_id
            if message.tool_calls: item['tool_calls'] = [function_call(call) for call in message.tool_calls]
            if message.role == 'assistant':
                private = message.provider_data or {}
                data = private.get('owner_model_continuation', private.get('owner_responses'))
                required = bool(message.tool_calls) or self._protocol == 'chat-completions' and bool(tools)
                if data is not None:
                    if (type(data) is not dict or data.get('scope') != self._scope
                            or data.get('session') != self._session_id):
                        raise rejected('PERSONAL_MODEL_CONTINUATION_REQUIRED')
                    record = data.get('continuation')
                    expected = data.get('message', record.get('message') if type(record) is dict else None)
                    if not assistant_message_matches(expected, item):
                        raise rejected('PERSONAL_MODEL_CONTINUATION_REQUIRED')
                    if record is not None:
                        continuation.append({**record, 'message_index': index})
                elif required:
                    raise rejected('PERSONAL_MODEL_CONTINUATION_REQUIRED')
            encoded.append(item)
        chat = {'model': self.id, 'messages': encoded, 'max_tokens': self._max_output_tokens, 'stream': True}
        if tools:
            provider_tools = []
            for tool in tools:
                function = tool.get('function') if type(tool) is dict else None
                if type(function) is dict and type(function.get('external_execution')) is bool:
                    function = {key: value for key, value in function.items() if key != 'external_execution'}
                    tool = {**tool, 'function': function}
                provider_tools.append(tool)
            chat.update(tools=provider_tools)
        if tool_choice is not None:
            chat['tool_choice'] = tool_choice
        body = encode_request(self._protocol, chat, continuation=continuation)
        # Existing provider extensions are a configuration concern, never codec
        # logic and never an untrusted native request override.
        if self._protocol == 'chat-completions':
            body.update(generation_options({'baseURL': self._base, 'model': self.id,
                'thinkingMode': self._thinking_mode}))
        return body

    async def _request(self, messages, *, on_text=None, **kwargs):
        response_id = uuid4().hex
        async def progress(text):
            if self._on_text is not None:
                await self._on_text(text, response_id)
            if on_text is not None:
                await on_text(text)
        try:
            body = self._body(messages, **kwargs)
            if self._trusted_proxy is not None and self.id != self._trusted_proxy.model_id:
                raise ValueError('TRUSTED_MODEL_PROXY_SCOPE_CHANGED')
            # Resolve on every call. Rotation/revocation never leaves a cached key.
            lease = await asyncio.to_thread(self._credential)
            transport = self._transport_factory() if self._transport_factory else PinnedChatTransport(
                model_origin(self._base), base_path=urlsplit(self._base).path, before_send=self._recheck,
                trusted_proxy=self._trusted_proxy, protocol=self._protocol)
            if self._recheck is not None:
                await asyncio.to_thread(self._recheck)
            async with httpx.AsyncClient(transport=transport, trust_env=False,
                    follow_redirects=False, timeout=self._timeout_seconds, auth=None) as client:
                request = client.build_request('POST', self._base + protocol_path(self._protocol), json=body,
                    headers=chat_headers(self._base, lease, self._session_id))
                async with asyncio.timeout(self._timeout_seconds):
                    response = await client.send(request, stream=True)
                try:
                    if response.status_code != 200:
                        raise rejected('PERSONAL_MODEL_HTTP_' + str(response.status_code))
                    value = await read_model_stream(response, lease, self._protocol, progress,
                        idle_seconds=self._timeout_seconds)
                finally:
                    await response.aclose()
            if self._recheck is not None:
                await asyncio.to_thread(self._recheck)
        except asyncio.CancelledError:
            raise
        except ModelProviderError:
            raise
        except Exception as error:
            # Remote bodies, authentication values, URLs and transport errors do
            # not enter native persisted error events or product logs.
            code = str(error)
            known = {'REMOTE_DNS_FAILED', 'REMOTE_CREDENTIAL_ECHO_REJECTED', 'REMOTE_RESPONSE_REJECTED',
                'REMOTE_CREDENTIAL_UNAVAILABLE', 'REMOTE_ORIGIN_DENIED', 'REMOTE_PATH_DENIED', 'REMOTE_DEADLINE',
                'TRUSTED_MODEL_PROXY_REQUEST_DENIED', 'PERSONAL_MODEL_STREAM_INCOMPLETE'}
            raise rejected(code if code in known else
                'PERSONAL_MODEL_REQUEST_FAILED_' + type(error).__name__.upper()) from None
        result = self._parse_provider_response(value)
        declared_tools = {tool['function']['name'] if self._protocol == 'chat-completions' else tool['name']
            for tool in body.get('tools', [])}
        if any(call['function']['name'] not in declared_tools for call in result.tool_calls or []):
            raise rejected('PERSONAL_MODEL_TOOL_NOT_DECLARED')
        return result

    def invoke(self, messages, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            return self._parse_provider_response(executor.submit(lambda: asyncio.run(self._request(messages, **kwargs))).result())

    async def ainvoke(self, messages, **kwargs):
        return self._parse_provider_response(await self._request(messages, **kwargs))

    def invoke_stream(self, messages, **kwargs):
        values = Queue()
        loop = asyncio.new_event_loop()
        async def forward():
            try:
                async for value in self.ainvoke_stream(messages, **kwargs):
                    values.put(value)
            except BaseException as error:
                values.put(error)
            finally:
                values.put(None)
        task = loop.create_task(forward())
        def run():
            try:
                loop.run_until_complete(task)
            finally:
                loop.close()
        thread = Thread(target=run, daemon=True)
        thread.start()
        try:
            while True:
                value = values.get()
                if value is None:
                    break
                if isinstance(value, BaseException):
                    raise value
                yield value
        finally:
            if not loop.is_closed():
                loop.call_soon_threadsafe(task.cancel)
            thread.join()

    async def ainvoke_stream(self, messages, **kwargs):
        chunks = asyncio.Queue()
        async def text(value):
            await chunks.put(ModelResponse(role='assistant', content=value))
        async def request():
            try:
                result = await self._request(messages, on_text=text, **kwargs)
                await chunks.put(result)
            except BaseException as error:
                await chunks.put(error)
            finally:
                await chunks.put(None)
        task = asyncio.create_task(request())
        streamed = False
        try:
            while True:
                value = await chunks.get()
                if value is None:
                    break
                if isinstance(value, BaseException):
                    raise value
                if value.provider_data:
                    if streamed:
                        value.content = None
                else:
                    streamed = True
                yield value
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _parse_provider_response(self, response, **kwargs):
        if isinstance(response, ModelResponse): return response
        try:
            response, continuation = decode_response(self._protocol, response)
            message = response['choices'][0]['message']
            result = ModelResponse(role='assistant', content=message.get('content'),
                tool_calls=message.get('tool_calls', []))
            result.provider_data = {'owner_model_continuation': {'scope': self._scope,
                'session': self._session_id, 'message': message, 'continuation': continuation}}
            usage = response.get('usage')
            if usage is not None:
                result.response_usage = MessageMetrics(input_tokens=usage['prompt_tokens'],
                    output_tokens=usage['completion_tokens'], total_tokens=usage['total_tokens'])
            return result
        except ValueError as error:
            code = {'MODEL_PROTOCOL_EMPTY_OUTPUT': 'PERSONAL_MODEL_EMPTY_OUTPUT',
                'MODEL_PROTOCOL_REFUSAL': 'PERSONAL_MODEL_REFUSAL'}.get(str(error))
            raise rejected(code or 'PERSONAL_MODEL_RESPONSE_REJECTED') from None
        except Exception:
            raise rejected() from None

    def _parse_provider_response_delta(self, response):
        return response

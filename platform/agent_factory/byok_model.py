"""Native Agno execution for the shared text/function-tool protocols.

Owner credentials are selected explicitly; HTTPX uses its normal environment configuration.
Each invocation resolves the selected owner credential; HTTPX owns DNS and TLS.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from typing import Callable
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
from .model_stream import read_model_stream

PROVIDER_ID = 'byok-chat-v1'
ADAPTER_ID = 'owner-chat-completions-v1'
CAPABILITY = 'model:invoke'


def rejected(code='PERSONAL_MODEL_RESPONSE_REJECTED'):
    return ModelProviderError(message=code, status_code=400, model_name='Owner Model')


class OwnerChatModel(Model):
    def __init__(self, configuration, credential: Callable, *, recheck=None, session_id=None,
            timeout_seconds=300, on_text=None, on_reasoning=None):
        super().__init__(id=model_id(configuration['model']), provider=configuration['provider'],
            name='Owner Model', retries=0)
        self._base = base_url(configuration['baseURL'])
        self._protocol = protocol_name(configuration)
        self._max_output_tokens = max_output_tokens(configuration)
        self._scope = continuation_scope(configuration)
        generation_options(configuration)
        self._thinking_mode = configuration.get('thinkingMode')
        self._reasoning_effort = configuration.get('reasoningEffort')
        self._credential = credential
        self._timeout_seconds = timeout_seconds
        self._on_text = on_text
        self._on_reasoning = on_reasoning
        self.context_window = configuration.get("contextWindow")
        self.auto_compact_token_limit = configuration.get("autoCompactTokenLimit")
        self.factory_wire_stream = True
        self._recheck = recheck
        self._session_id = session_id or 'af-agent-' + uuid4().hex

    def __repr__(self):
        return 'OwnerChatModel(credentials=<redacted>)'

    def _body(self, messages, *, tools=None, tool_choice=None, response_format=None,
              compress_tool_results=False, **kwargs):
        if response_format is not None:
            raise rejected('PERSONAL_MODEL_UNSUPPORTED_FORMAT')
        encoded, continuation = [], []
        for index, message in enumerate(messages):
            content = message.get_content(use_compressed_content=compress_tool_results)
            if (message.role not in {'system', 'user', 'assistant', 'tool'}
                    or content is not None and type(content) is not str
                    or any(getattr(message, field, None) for field in ('images', 'videos', 'audio', 'files'))):
                raise rejected('PERSONAL_MODEL_TEXT_ONLY')
            item = {'role': message.role, 'content': content}
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
        if self._reasoning_effort is not None:
            if self._protocol == 'responses':
                body['reasoning'] = {'effort': self._reasoning_effort, 'summary': 'auto'}
            else:
                body['reasoning_effort'] = self._reasoning_effort
        # Existing provider extensions are a configuration concern, never codec
        # logic and never an untrusted native request override.
        if self._protocol == 'chat-completions':
            body.update(generation_options({'baseURL': self._base, 'model': self.id,
                'thinkingMode': self._thinking_mode}))
        return body

    async def _request(self, messages, *, on_text=None, on_reasoning=None, **kwargs):
        response_id = uuid4().hex
        async def progress(text):
            if self._on_text is not None:
                await self._on_text(text, response_id)
            if on_text is not None:
                await on_text(text)
        async def reasoning(text):
            if self._on_reasoning is not None:
                await self._on_reasoning(text, response_id)
            if on_reasoning is not None:
                await on_reasoning(text)
        try:
            body = self._body(messages, **kwargs)
            # Resolve on every call. Rotation/revocation never leaves a cached key.
            lease = await asyncio.to_thread(self._credential)
            if self._recheck is not None:
                await asyncio.to_thread(self._recheck)
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                request = client.build_request('POST', self._base + protocol_path(self._protocol), json=body,
                    headers=chat_headers(self._base, lease, self._session_id))
                response = await client.send(request, stream=True)
                try:
                    if response.status_code != 200:
                        raise rejected('PERSONAL_MODEL_HTTP_' + str(response.status_code))
                    value = await read_model_stream(response, self._protocol, progress, reasoning)
                finally:
                    await response.aclose()
            if self._recheck is not None:
                await asyncio.to_thread(self._recheck)
            result = self._parse_provider_response(value)
            if 'text/event-stream' not in response.headers.get('content-type', ''):
                if self._protocol == 'responses':
                    continuation = result.provider_data['owner_model_continuation']['continuation']
                    for item in continuation['output']:
                        if item['type'] == 'reasoning':
                            thought = ''.join(part['text'] for part in item.get('summary', []) + item.get('content', []))
                            if thought:
                                await reasoning(thought)
                        elif item['type'] == 'message':
                            await progress(''.join(part['text'] for part in item['content']))
                else:
                    if result.reasoning_content:
                        await reasoning(result.reasoning_content)
                    if result.content:
                        await progress(result.content)
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
                'PERSONAL_MODEL_STREAM_INCOMPLETE'}
            raise rejected(code if code in known else
                'PERSONAL_MODEL_REQUEST_FAILED_' + type(error).__name__.upper()) from None
        return result

    def invoke(self, messages, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(self._request(messages, **kwargs))).result()

    async def ainvoke(self, messages, **kwargs):
        return await self._request(messages, **kwargs)

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
        async def reasoning(value):
            await chunks.put(ModelResponse(role='assistant', reasoning_content=value))
        async def request():
            try:
                result = await self._request(messages, on_text=text, on_reasoning=reasoning, **kwargs)
                await chunks.put(result)
            except BaseException as error:
                await chunks.put(error)
            finally:
                await chunks.put(None)
        task = asyncio.create_task(request())
        streamed, reasoning_streamed = False, False
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
                    if reasoning_streamed:
                        value.reasoning_content = None
                else:
                    streamed = streamed or value.content is not None
                    reasoning_streamed = reasoning_streamed or value.reasoning_content is not None
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
            if continuation is not None:
                result.reasoning_content = continuation.get('reasoning_content')
                if self._protocol == 'responses':
                    result.reasoning_content = ''.join(part['text'] for item in continuation['output']
                        if item['type'] == 'reasoning' for part in item.get('summary', []) + item.get('content', [])) or None
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

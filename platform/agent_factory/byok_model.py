"""Owner-bound native Chat Completions and Responses continuation compatibility.

Owner credentials are selected explicitly; HTTPX uses its normal environment configuration.
Each invocation resolves the selected owner credential; HTTPX owns DNS and TLS.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Thread
from typing import Any, Callable, cast
from uuid import uuid4

from agno.exceptions import ModelProviderError
from agno.models.openai.chat import OpenAIChat
from agno.models.deepseek import DeepSeek
from openai import AsyncOpenAI, APIStatusError, Omit
from openai._models import construct_type
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from openai.types.responses import Response
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
from .model_protocol import OwnerResponses, protocol_name
from .model_stream import read_model_stream

PROVIDER_ID = 'byok-chat-v1'
ADAPTER_ID = 'owner-chat-completions-v1'
CAPABILITY = 'model:invoke'


def rejected(code='PERSONAL_MODEL_RESPONSE_REJECTED'):
    return ModelProviderError(message=code, status_code=400, model_name='Owner Model')


class OwnerChatModel(OpenAIChat):
    def __init__(self, configuration, credential: Callable, *, recheck=None, session_id=None,
            timeout_seconds=300, on_text=None, on_reasoning=None):
        super().__init__(id=model_id(configuration['model']), provider=configuration['provider'],
            name='Owner Model', retries=0, max_retries=0,
            max_tokens=max_output_tokens(configuration), reasoning_effort=configuration.get('reasoningEffort'),
            role_map={**OpenAIChat.default_role_map, 'system': 'system', 'developer': 'developer'})
        self._base = base_url(configuration['baseURL'])
        self._protocol = protocol_name(configuration)
        self._scope = continuation_scope(configuration)
        self._extensions = generation_options(configuration)
        self._credential = credential
        self._timeout_seconds = timeout_seconds
        self._on_text = on_text
        self._on_reasoning = on_reasoning
        self.context_window = configuration.get("contextWindow")
        self.auto_compact_token_limit = configuration.get("autoCompactTokenLimit")
        self._recheck = recheck
        self._session_id = session_id or 'af-agent-' + uuid4().hex
        self._responses = OwnerResponses(configuration, self._scope, self._session_id) if self._protocol == 'responses' else None

    def __repr__(self):
        return 'OwnerChatModel(credentials=<redacted>)'

    def _body(self, messages, *, tools=None, tool_choice=None, response_format=None,
              compress_tool_results=False, **kwargs):
        if self._protocol == 'chat-completions':
            params = self.get_request_params(response_format=response_format,
                tools=tools, tool_choice=tool_choice, run_response=kwargs.get('run_response'))
            # Agno tool metadata describes execution, not provider function schemas.
            if tools:
                params['tools'] = [{**tool, 'function': {key: value for key, value in tool['function'].items()
                    if key not in {'external_execution', 'requires_confirmation', 'approval_type'}}}
                    if tool.get('type') == 'function' else tool for tool in tools]
            return {'model': self.id, 'messages': self._format_all_messages(messages, compress_tool_results),
                'stream': True, **params, **self._extensions}
        if isinstance(tool_choice, dict) and tool_choice.get('type') == 'function' and 'function' in tool_choice:
            tool_choice = {'type': 'function', 'name': tool_choice['function']['name']}
        native = self._responses
        assert native is not None
        params = native.get_request_params(messages=messages, response_format=response_format,
            tools=tools, tool_choice=tool_choice, run_response=kwargs.get('run_response'))
        return {'model': self.id, 'input': native._format_messages(messages, compress_tool_results, tools),
            'stream': True, **params}

    def _format_message(self, message, compress_tool_results=False):
        # Agno's generic OpenAI formatter omits DeepSeek-compatible reasoning replay.
        if message.reasoning_content is not None:
            return DeepSeek._format_message(cast(DeepSeek, self), message, compress_tool_results)
        return super()._format_message(message, compress_tool_results)

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
            headers: dict[str, Any] = chat_headers(self._base, lease, self._session_id)
            if lease is None:
                headers['Authorization'] = Omit()
            async with AsyncOpenAI(api_key=lease.password if lease else 'unused-local-model',
                    base_url=self._base, max_retries=0, timeout=self._timeout_seconds) as client:
                endpoint = client.responses if self._responses else client.chat.completions
                extensions = {} if self._responses else self._extensions
                options = {key: value for key, value in body.items() if key not in extensions}
                async with endpoint.with_streaming_response.create(
                        **options, extra_body=extensions, extra_headers=headers) as response:
                    http_response = response.http_response
                    value = await read_model_stream(http_response, self._protocol, progress, reasoning)
            if self._recheck is not None:
                await asyncio.to_thread(self._recheck)
            result = self._parse_provider_response(value)
            if 'text/event-stream' not in http_response.headers.get('content-type', ''):
                if self._protocol == 'responses':
                    assert result.provider_data is not None
                    continuation = result.provider_data['owner_model_continuation']['continuation']
                    for item in continuation['output']:
                        if item['type'] == 'reasoning':
                            thought = ''.join(part['text'] for part in item.get('summary', []) + item.get('content', []))
                            if thought:
                                await reasoning(thought)
                        elif item['type'] == 'message':
                            await progress(''.join(part['text'] for part in item['content'] if part.get('type') == 'output_text'))
                else:
                    if result.reasoning_content:
                        await reasoning(result.reasoning_content)
                    if result.content:
                        await progress(result.content)
        except asyncio.CancelledError:
            raise
        except APIStatusError as error:
            raise rejected('PERSONAL_MODEL_HTTP_' + str(error.status_code)) from None
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
                if result.tool_calls:
                    # The native streaming loop consumes deltas, unlike ainvoke.
                    result.tool_calls = [ChoiceDeltaToolCall(**{**call, "index": index})
                        for index, call in enumerate(result.tool_calls)]
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
                if value.provider_data is not None:
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
        if self._protocol == 'chat-completions':
            if isinstance(response, dict):
                response = cast(ChatCompletion, construct_type(type_=ChatCompletion, value=response))
            if not response.choices or response.choices[0].finish_reason not in {'stop', 'tool_calls'}:
                raise rejected('PERSONAL_MODEL_STREAM_INCOMPLETE')
            result = super()._parse_provider_response(response, **kwargs)
            if not result.content and not result.tool_calls and result.audio is None:
                refusal = getattr(response.choices[0].message, 'refusal', None)
                raise rejected('PERSONAL_MODEL_REFUSAL' if refusal else 'PERSONAL_MODEL_EMPTY_OUTPUT')
            return result
        if isinstance(response, dict):
            response = cast(Response, construct_type(type_=Response, value=response))
        assert self._responses is not None
        return self._responses._parse_provider_response(response, **kwargs)

    def _parse_provider_response_delta(self, response):
        return response

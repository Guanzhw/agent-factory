"""Native Agno text/function-tool adapter for the reviewed Chat Completions subset.

No SDK environment key lookup, redirects, proxies, retry, discovery or billing.
Each invocation resolves the exact owner/vault revision and pins public DNS.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import re
from typing import Callable, cast
from urllib.parse import urlsplit

import httpx
from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse

from .personal_remote_provider import PinnedHTTPSProbe, origin, reject_credential_echo

PROVIDER_ID = 'byok-chat-v1'
ADAPTER_ID = 'owner-chat-completions-v1'
CAPABILITY = 'model:invoke'
MAX_BYTES = 1_048_576


def base_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.path.rstrip('/') != '/v1':
            raise ValueError()
        destination = origin(value[:value.index('/v1')])
        if value not in {destination + '/v1', destination + '/v1/'}:
            raise ValueError()
        return destination + '/v1'
    except (ValueError, TypeError, AttributeError):
        raise ValueError('PERSONAL_MODEL_DESTINATION_DENIED') from None


def model_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}', value):
        raise ValueError('PERSONAL_MODEL_ID_INVALID')
    return value


class PinnedChatTransport(httpx.AsyncBaseTransport):
    def __init__(self, destination, *, before_send=None):
        self.destination = origin(destination)
        self.before_send = before_send
        self.probe = PinnedHTTPSProbe()
        self.transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        if request.method != 'POST' or str(request.url) != self.destination + '/v1/chat/completions':
            raise ValueError('PERSONAL_MODEL_DESTINATION_DENIED')
        addresses = await asyncio.to_thread(self.probe.addresses, self.destination)
        if self.before_send is not None:
            await asyncio.to_thread(self.before_send)
        # DNS is checked once per invocation, then the connection uses a literal
        # address. Host and TLS SNI retain the exact credential-bound hostname.
        forwarded = httpx.Request('POST', request.url.copy_with(host=addresses[0]),
            headers={**dict(request.headers), 'host': request.url.host}, content=await request.aread(),
            extensions={**request.extensions, 'sni_hostname': request.url.host})
        return await self.transport.handle_async_request(forwarded)

    async def aclose(self):
        await self.transport.aclose()


def rejected(code='PERSONAL_MODEL_RESPONSE_REJECTED'):
    return ModelProviderError(message=code, status_code=400, model_name='Owner Chat Completions')


def function_call(call):
    if (type(call) is not dict or type(call.get('id')) is not str or not 1 <= len(call['id']) <= 200
            or call.get('type') != 'function' or type(call.get('function')) is not dict):
        raise rejected()
    function = call['function']
    if (type(function.get('name')) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', function['name'])
            or type(function.get('arguments')) is not str or type(json.loads(function['arguments'])) is not dict):
        raise rejected()
    return {'id': call['id'], 'type': 'function', 'function': {
        'name': function['name'], 'arguments': function['arguments']}}


class OwnerChatModel(Model):
    def __init__(self, configuration, credential: Callable, *, transport_factory=None, recheck=None):
        super().__init__(id=model_id(configuration['model']), provider=configuration['provider'],
            name='Owner Chat Completions', retries=0)
        self._base = base_url(configuration['baseURL'])
        self._credential = credential
        self._transport_factory = transport_factory
        self._recheck = recheck

    def __repr__(self):
        return 'OwnerChatModel(credentials=<redacted>)'

    def _body(self, messages, *, tools=None, tool_choice=None, response_format=None, **kwargs):
        if response_format is not None:
            raise rejected('PERSONAL_MODEL_UNSUPPORTED_FORMAT')
        encoded = []
        for message in messages:
            if (message.role not in {'system', 'user', 'assistant', 'tool'}
                    or message.content is not None and type(message.content) is not str
                    or any(getattr(message, field, None) for field in ('images', 'videos', 'audio', 'files'))):
                raise rejected('PERSONAL_MODEL_TEXT_ONLY')
            item = {'role': message.role, 'content': message.content}
            if message.role == 'tool': item['tool_call_id'] = message.tool_call_id
            if message.tool_calls: item['tool_calls'] = [function_call(call) for call in message.tool_calls]
            encoded.append(item)
        body = {'model': self.id, 'messages': encoded, 'max_tokens': 4096, 'stream': False}
        if tools:
            if any(tool.get('type') != 'function' or type(tool.get('function')) is not dict for tool in tools):
                raise rejected('PERSONAL_MODEL_FUNCTION_TOOLS_ONLY')
            body.update(tools=tools, parallel_tool_calls=False)
        if tool_choice is not None:
            if tool_choice not in ('none', 'auto', 'required'): raise rejected('PERSONAL_MODEL_TOOL_CHOICE_DENIED')
            body['tool_choice'] = tool_choice
        if len(json.dumps(body).encode()) > MAX_BYTES: raise rejected('PERSONAL_MODEL_REQUEST_TOO_LARGE')
        return body

    async def _request(self, messages, **kwargs):
        try:
            body = self._body(messages, **kwargs)
            # Resolve on every call. Rotation/revocation never leaves a cached key.
            lease = await asyncio.to_thread(self._credential)
            transport = self._transport_factory() if self._transport_factory else PinnedChatTransport(self._base[:-3], before_send=self._recheck)
            if self._recheck is not None:
                await asyncio.to_thread(self._recheck)
            async with asyncio.timeout(30), httpx.AsyncClient(transport=transport, trust_env=False,
                    follow_redirects=False, timeout=10, auth=None) as client:
                async with client.stream('POST', self._base + '/chat/completions', json=body,
                        headers={'Authorization': 'Bearer ' + lease.password, 'Accept-Encoding': 'identity'}) as response:
                    if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
                        raise rejected('PERSONAL_MODEL_REQUEST_FAILED')
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES: raise rejected()
                        chunks.append(chunk)
                    value = json.loads(b''.join(chunks))
                    reject_credential_echo(value, lease)
                    return value
        except asyncio.CancelledError:
            raise
        except Exception:
            # Remote bodies, authentication values, URLs and transport errors do
            # not enter native persisted error events or product logs.
            raise rejected('PERSONAL_MODEL_REQUEST_FAILED') from None

    def invoke(self, messages, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            return self._parse_provider_response(executor.submit(lambda: asyncio.run(self._request(messages, **kwargs))).result())

    async def ainvoke(self, messages, **kwargs):
        return self._parse_provider_response(await self._request(messages, **kwargs))

    def invoke_stream(self, messages, **kwargs):
        yield self.invoke(messages, **kwargs)

    async def ainvoke_stream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        if isinstance(response, ModelResponse): return response
        try:
            if type(response.get('choices')) is not list or len(response['choices']) != 1: raise rejected()
            choice = response['choices'][0]
            message = choice['message']
            if (choice.get('finish_reason') not in {'stop', 'tool_calls'} or message.get('role') != 'assistant'
                    or message.get('content') is not None and type(message['content']) is not str):
                raise rejected()
            calls = [function_call(call) for call in message.get('tool_calls', [])]
            if len(calls) > 16 or len({call['id'] for call in calls}) != len(calls): raise rejected()
            result = ModelResponse(role='assistant', content=message.get('content'), tool_calls=calls)
            usage = response.get('usage')
            if type(usage) is dict:
                incoming, outgoing, total = (usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                if all(type(n) is int and n >= 0 for n in (incoming, outgoing, total)) and cast(int, total) == cast(int, incoming) + cast(int, outgoing):
                    result.response_usage = MessageMetrics(input_tokens=cast(int, incoming), output_tokens=cast(int, outgoing), total_tokens=cast(int, total))
            return result
        except Exception:
            raise rejected() from None

    def _parse_provider_response_delta(self, response):
        return response

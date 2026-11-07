"""Official OpenAI stream decoding/aggregation at the owner transport boundary."""
import base64
from typing import Any, cast

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.lib.streaming.chat import ChatCompletionStreamState

from .model_transport import read_response_json, with_idle_timeout
from .personal_remote_provider import reject_credential_echo


async def read_model_stream(response, lease, protocol, on_text=None, idle_seconds=300):
    if 'text/event-stream' not in response.headers.get('content-type', ''):
        return await read_response_json(response, lease, idle_seconds)
    if response.status_code != 200:
        raise ValueError('PERSONAL_MODEL_REQUEST_FAILED')
    # The SDK owns SSE framing and chat tool-delta aggregation. The existing
    # codec still owns saved Responses reasoning/continuation compatibility.
    client = AsyncOpenAI(api_key='unused-stream-decoder', max_retries=0)
    state = ChatCompletionStreamState()
    result, completed = None, False
    reasoning = ''
    role_seen = False
    pending_text = ''
    secrets = []
    if lease is not None:
        encoded = base64.b64encode((lease.username + ':' + lease.password).encode()).decode()
        secrets = [lease.password, encoded, 'Basic ' + encoded, 'Bearer ' + lease.password]

    async def publish(text, *, final=False):
        nonlocal pending_text
        pending_text += text
        reject_credential_echo(pending_text, lease)
        # Retain only a suffix that could still become the configured credential
        # in the next chunk. Never publish a secret and then try to retract it.
        held = max((length for secret in secrets for length in range(1, len(secret))
            if pending_text.endswith(secret[:length])), default=0) if not final else 0
        ready = pending_text[:-held] if held else pending_text
        pending_text = pending_text[-held:] if held else ''
        if ready and on_text is not None:
            await on_text(ready)
    try:
        stream = AsyncStream(cast_to=dict[str, Any], response=response, client=client)
        async for value in with_idle_timeout(stream, idle_seconds):
            reject_credential_echo(value, lease)
            if value.get('error') or value.get('type') in {'error', 'response.failed', 'response.incomplete'}:
                raise ValueError('PERSONAL_MODEL_STREAM_FAILED')
            text = ''
            if protocol == 'responses':
                if value.get('type') == 'response.output_text.delta':
                    text = value.get('delta', '')
                elif value.get('type') == 'response.completed':
                    result, completed = value['response'], True
            else:
                # Compatible endpoints may repeat the unchanged role in every
                # delta; the SDK generic string merger would concatenate it.
                for choice in value.get('choices', []):
                    delta = choice.get('delta', {})
                    if 'role' in delta:
                        if delta['role'] != 'assistant':
                            raise ValueError('PERSONAL_MODEL_STREAM_ROLE')
                        if role_seen:
                            delta.pop('role')
                        role_seen = True
                # construct_type is the SDK's permissive compatible-provider
                # parser, including optional provider extension fields.
                from openai._models import construct_type
                chunk = construct_type(type_=ChatCompletionChunk, value=value)
                state.handle_chunk(cast(ChatCompletionChunk, chunk))
                for choice in value.get('choices', []):
                    if choice.get('index', 0) == 0:
                        delta = choice.get('delta', {})
                        text += delta.get('content') or ''
                        reasoning += delta.get('reasoning_content') or ''
                        completed = completed or bool(choice.get('finish_reason'))
            if text:
                await publish(text)
        if not completed:
            raise ValueError('PERSONAL_MODEL_STREAM_INCOMPLETE')
        if protocol == 'chat-completions':
            result = state.get_final_completion().model_dump(exclude_none=True)
            if reasoning:
                result['choices'][0]['message']['reasoning_content'] = reasoning
        reject_credential_echo(result, lease)
        await publish('', final=True)
        return result
    finally:
        await client.close()

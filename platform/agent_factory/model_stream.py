"""Official OpenAI stream decoding/aggregation at the owner transport boundary."""
import asyncio
from typing import Any, cast
from time import monotonic

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.lib.streaming.chat import ChatCompletionStreamState



async def read_model_stream(response, protocol, on_text=None, on_reasoning=None):
    if 'text/event-stream' not in response.headers.get('content-type', ''):
        await response.aread()
        return response.json()
    if response.status_code != 200:
        raise ValueError('PERSONAL_MODEL_REQUEST_FAILED')
    # The SDK owns SSE framing and chat tool-delta aggregation. The existing
    # codec still owns saved Responses reasoning/continuation compatibility.
    client = AsyncOpenAI(api_key='unused-stream-decoder', max_retries=0)
    state = ChatCompletionStreamState()
    result, completed = None, False
    reasoning = ''
    role_seen = False
    pending, pending_kind, last_emit = '', '', 0.0
    async def flush():
        nonlocal pending, last_emit
        callback = on_reasoning if pending_kind == 'reasoning' else on_text
        text = pending
        pending, last_emit = '', monotonic()
        if text and callback is not None:
            await callback(text)
    async def progress(kind, text):
        nonlocal pending, pending_kind
        if not text:
            return
        if pending_kind != kind:
            await flush()
            pending_kind = kind
        pending += text
        if monotonic() - last_emit >= 0.2:
            await flush()
    stream = AsyncStream(cast_to=dict[str, Any], response=response, client=client).__aiter__()
    next_value = asyncio.ensure_future(anext(stream))
    try:
        while True:
            ready, _ = await asyncio.wait({next_value},
                timeout=max(0.2 - (monotonic() - last_emit), 0) if pending else None)
            if not ready:
                await flush()
                continue
            try:
                value = next_value.result()
            except StopAsyncIteration:
                break
            next_value = asyncio.ensure_future(anext(stream))
            if value.get('error') or value.get('type') in {'error', 'response.failed', 'response.incomplete'}:
                raise ValueError('PERSONAL_MODEL_STREAM_FAILED')
            text = ''
            if protocol == 'responses':
                if value.get('type') == 'response.output_text.delta':
                    text = value.get('delta', '')
                elif value.get('type') in {'response.reasoning_summary_text.delta', 'response.reasoning_text.delta'}:
                    await progress('reasoning', value.get('delta', ''))
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
                        thought = delta.get('reasoning_content') or delta.get('reasoning') or ''
                        reasoning += thought
                        await progress('reasoning', thought)
                        completed = completed or bool(choice.get('finish_reason'))
            await progress('content', text)
        await flush()
        if not completed:
            raise ValueError('PERSONAL_MODEL_STREAM_INCOMPLETE')
        if protocol == 'chat-completions':
            result = state.get_final_completion().model_dump(exclude_none=True)
            if reasoning:
                result['choices'][0]['message']['reasoning_content'] = reasoning
        return result
    finally:
        next_value.cancel()
        await asyncio.gather(next_value, return_exceptions=True)
        try:
            await flush()
        finally:
            await client.close()

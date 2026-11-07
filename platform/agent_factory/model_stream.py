"""Official OpenAI stream decoding/aggregation at the owner transport boundary."""
from typing import Any, cast

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.lib.streaming.chat import ChatCompletionStreamState



async def read_model_stream(response, protocol, on_text=None):
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
    try:
        stream = AsyncStream(cast_to=dict[str, Any], response=response, client=client)
        async for value in stream:
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
            if text and on_text is not None:
                await on_text(text)
        if not completed:
            raise ValueError('PERSONAL_MODEL_STREAM_INCOMPLETE')
        if protocol == 'chat-completions':
            result = state.get_final_completion().model_dump(exclude_none=True)
            if reasoning:
                result['choices'][0]['message']['reasoning_content'] = reasoning
        return result
    finally:
        await client.close()

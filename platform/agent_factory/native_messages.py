"""Preserve missing tool results as observations, never as instructions to replay."""
from agno.models.message import Message


def pair_tool_results(messages):
    results = {item.tool_call_id for item in messages if item.role == 'tool' and not item.from_history}
    paired = []
    for message in messages:
        paired.append(message)
        if message.from_history:
            continue
        for call in message.tool_calls or []:
            if call.get('id') and call['id'] not in results:
                paired.append(Message(role='tool', tool_call_id=call['id'], tool_call_error=True,
                    content='No result was recorded before this execution ended. The operation outcome is unknown; '
                            'do not assume success or automatically repeat it. Continue independent work when possible.'))
    return paired

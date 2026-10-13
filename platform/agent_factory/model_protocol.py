"""Pure text/function-tool codecs; execution, credentials and accounting stay outside.

Continuations are private replay data for a tool turn, not public request
extensions. Callers keep them in their existing scoped history.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from typing import Any, NoReturn, cast

MAX_BYTES = 1_048_576
_PATHS = {'chat-completions': '/chat/completions', 'responses': '/responses'}
_REQUEST_FIELDS = {'model', 'messages', 'max_tokens', 'stream', 'tools', 'parallel_tool_calls', 'tool_choice'}


def _fail(code='INVALID') -> NoReturn:
    raise ValueError('MODEL_PROTOCOL_' + code)


def _bounded(value):
    """Accept only bounded JSON, including when called directly without a parser."""
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 100_000 or depth > 32:
            _fail('SIZE')
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                _fail()
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in {str, int, float, bool}:
            _fail()
        elif type(item) is float and not math.isfinite(item):
            _fail()
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail()
    if size > MAX_BYTES:
        _fail('SIZE')


def protocol_name(configuration):
    if type(configuration) is not dict:
        _fail('CONFIGURATION')
    value = configuration.get('protocol', 'chat-completions')
    protocol_path(value)
    return value


def protocol_path(protocol):
    if type(protocol) is not str or protocol not in _PATHS:
        _fail('UNSUPPORTED')
    return _PATHS[protocol]


def _identifier(value):
    if type(value) is not str or not 1 <= len(value) <= 200 or any(ord(c) < 32 for c in value):
        _fail('TOOL')
    return value


def _name(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', value):
        _fail('TOOL')
    return value


def function_call(call):
    if (type(call) is not dict or call.get('type') != 'function'
            or type(call.get('function')) is not dict):
        _fail('TOOL')
    identifier, function = _identifier(call.get('id')), call['function']
    name, arguments = _name(function.get('name')), function.get('arguments')
    if type(arguments) is not str:
        _fail('TOOL')
    try:
        parsed = json.loads(arguments)
    except (ValueError, RecursionError):
        _fail('TOOL')
    if type(parsed) is not dict:
        _fail('TOOL')
    _bounded(parsed)
    _bounded(arguments)
    return {'id': identifier, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


def _calls(value):
    if type(value) is not list or len(value) > 16:
        _fail('TOOL')
    calls = [function_call(call) for call in value]
    if len({call['id'] for call in calls}) != len(calls):
        _fail('TOOL')
    return calls


def _message(value):
    if (type(value) is not dict or set(value) - {'role', 'content', 'tool_calls', 'tool_call_id'}
            or type(value.get('role')) is not str or value['role'] not in {'system', 'user', 'assistant', 'tool'}):
        _fail('MESSAGE')
    role, content = value['role'], value.get('content')
    if content is not None and type(content) is not str:
        _fail('MESSAGE')
    result = {'role': role, 'content': content}
    if role == 'tool':
        result['tool_call_id'] = _identifier(value.get('tool_call_id'))
    elif 'tool_call_id' in value:
        _fail('MESSAGE')
    if 'tool_calls' in value:
        calls = _calls(value['tool_calls'])
        if calls and role != 'assistant':
            _fail('MESSAGE')
        if calls:
            result['tool_calls'] = calls
    return result


def _tools(value, responses):
    if type(value) is not list or len(value) > 64:
        _fail('TOOL')
    tools, names = [], set()
    for tool in value:
        if (type(tool) is not dict or set(tool) != {'type', 'function'}
                or tool.get('type') != 'function' or type(tool.get('function')) is not dict):
            _fail('TOOL')
        source = tool['function']
        if set(source) - {'name', 'description', 'parameters', 'strict'}:
            _fail('TOOL')
        name = _name(source.get('name'))
        if name in names:
            _fail('TOOL')
        names.add(name)
        function: dict[str, Any] = {'name': name}
        if 'description' in source:
            if type(source['description']) is not str:
                _fail('TOOL')
            function['description'] = source['description']
        if 'parameters' in source:
            if type(source['parameters']) is not dict:
                _fail('TOOL')
            function['parameters'] = json.loads(json.dumps(source['parameters']))
        if 'strict' in source:
            if type(source['strict']) is not bool:
                _fail('TOOL')
            function['strict'] = source['strict']
        elif responses:
            # Preserve the non-strict default of the canonical CC request.
            function['strict'] = False
        tools.append({'type': 'function', **function} if responses else {'type': 'function', 'function': function})
    return tools


def _choice(value, responses):
    if type(value) is str and value in {'auto', 'none', 'required'}:
        return value
    if (type(value) is dict and set(value) == {'type', 'function'} and value['type'] == 'function'
            and type(value['function']) is dict and set(value['function']) == {'name'}):
        name = _name(value['function']['name'])
        return {'type': 'function', 'name': name} if responses else {'type': 'function', 'function': {'name': name}}
    _fail('TOOL_CHOICE')


def _usage(value, responses):
    if type(value) is not dict:
        return None
    incoming = value.get('input_tokens' if responses else 'prompt_tokens')
    outgoing = value.get('output_tokens' if responses else 'completion_tokens')
    total = value.get('total_tokens')
    if (not all(type(n) is int and 0 <= n < 2**63 for n in (incoming, outgoing, total))
            or total != cast(int, incoming) + cast(int, outgoing)):
        return None
    return {'prompt_tokens': incoming, 'completion_tokens': outgoing, 'total_tokens': total}


def _response_items(output):
    if type(output) is not list or len(output) > 200:
        _fail('RESPONSE')
    content, calls, replay = [], [], []
    for source in output:
        if type(source) is not dict:
            _fail('RESPONSE')
        if source.get('status', 'completed') != 'completed':
            _fail('INCOMPLETE')
        kind = source.get('type')
        if kind == 'message':
            if source.get('role') != 'assistant' or type(source.get('content')) is not list:
                _fail('RESPONSE')
            parts = []
            for part in source['content']:
                if type(part) is not dict:
                    _fail('RESPONSE')
                if part.get('type') == 'refusal':
                    _fail('REFUSAL')
                if part.get('type') != 'output_text' or type(part.get('text')) is not str:
                    _fail('UNSUPPORTED_OUTPUT')
                content.append(part['text'])
                parts.append({'type': 'output_text', 'text': part['text'], 'annotations': []})
            item = {'type': 'message', 'role': 'assistant', 'content': parts, 'status': 'completed'}
            if source.get('phase') is not None:
                if type(source['phase']) is not str or source['phase'] not in {'commentary', 'final_answer'}:
                    _fail('UNSUPPORTED_OUTPUT')
                item['phase'] = source['phase']
        elif kind == 'function_call':
            call = function_call({'id': source.get('call_id'), 'type': 'function', 'function': {
                'name': source.get('name'), 'arguments': source.get('arguments')}})
            calls.append(call)
            item = {'type': 'function_call', 'call_id': call['id'], **call['function'], 'status': 'completed'}
        elif kind == 'reasoning':
            if 'id' not in source:
                _fail('RESPONSE')
            summary = source.get('summary', [])
            if type(summary) is not list:
                _fail('RESPONSE')
            summaries = []
            for part in summary:
                if type(part) is not dict or part.get('type') != 'summary_text' or type(part.get('text')) is not str:
                    _fail('RESPONSE')
                summaries.append({'type': 'summary_text', 'text': part['text']})
            item = {'type': 'reasoning', 'summary': summaries}
            if 'encrypted_content' in source and source['encrypted_content'] is not None:
                if type(source['encrypted_content']) is not str:
                    _fail('RESPONSE')
                item['encrypted_content'] = source['encrypted_content']
            # Other reasoning content is outside this deliberately small subset.
            if 'content' in source and source['content'] not in (None, []):
                _fail('UNSUPPORTED_OUTPUT')
        elif kind == 'refusal':
            _fail('REFUSAL')
        else:
            _fail('UNSUPPORTED_OUTPUT')
        if 'id' in source:
            item['id'] = _identifier(source['id'])
        replay.append(item)
    calls = _calls(calls)
    if not calls and not ''.join(content).strip():
        _fail('EMPTY_OUTPUT')
    message = {'role': 'assistant', 'content': ''.join(content) if content else None}
    if calls:
        message['tool_calls'] = calls
    return message, replay


def _json_equal(left, right):
    """Compare JSON types, not Python's interchangeable bool/int values."""
    if type(left) in {int, Decimal} and type(right) in {int, Decimal}:
        return left == right  # JSON has one number type; 1 and 1.0 are equivalent.
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def assistant_message_matches(expected, actual) -> bool:
    """Validate and compare a canonical assistant message without rewriting it.

    SDKs normalize empty assistant text and parse/stringify tool arguments.
    Compare that meaning while leaving the original replay payload untouched.
    Decimal avoids treating a changed JSON decimal as equal through rounding.
    """
    _bounded([expected, actual])
    expected, actual = _message(expected), _message(actual)
    if expected['role'] != 'assistant' or actual['role'] != 'assistant':
        return False
    left, right = expected.get('tool_calls', []), actual.get('tool_calls', [])
    if not left and not right:
        return expected['content'] == actual['content']
    if (not left or len(left) != len(right)
            or (expected['content'] or '') != (actual['content'] or '')):
        return False
    for a, b in zip(left, right):
        if a['id'] != b['id'] or a['function']['name'] != b['function']['name']:
            return False
        if not _json_equal(json.loads(a['function']['arguments'], parse_float=Decimal),
                json.loads(b['function']['arguments'], parse_float=Decimal)):
            return False
    return True


def _continuations(protocol, value):
    if value is None:
        return {}
    _bounded(value)
    if type(value) is not list:
        _fail('CONTINUATION')
    records, identifiers = {}, set()
    for record in value:
        field = 'output' if protocol == 'responses' else 'reasoning_content'
        if (type(record) is not dict or set(record) not in (
                {'message', field}, {'message', field, 'message_index'})):
            _fail('CONTINUATION')
        message = _message(record['message'])
        calls = message.get('tool_calls', [])
        if message['role'] != 'assistant' or not calls and (protocol == 'responses' or 'message_index' not in record):
            _fail('CONTINUATION')
        if protocol == 'responses':
            decoded, replay = _response_items(record['output'])
            if message != decoded:
                _fail('CONTINUATION')
        else:
            if type(record['reasoning_content']) is not str:
                _fail('CONTINUATION')
            replay = {**message, 'reasoning_content': record['reasoning_content']}
        call_ids = tuple(call['id'] for call in calls)
        if 'message_index' in record:
            position = record['message_index']
            if type(position) is not int or not 0 <= position < 200:
                _fail('CONTINUATION')
            key = ('index', position)
        else:
            key = ('calls', call_ids)
        if key in records or identifiers.intersection(call_ids):
            _fail('CONTINUATION')
        identifiers.update(call_ids)
        records[key] = (message, replay)
    return records


def encode_request(protocol, chat_body, continuation=None):
    """Encode a canonical CC request; continuation is a list of decode records.

    A replay record must match exactly one assistant message by ordered call
    IDs or an explicit message_index, and canonical message semantics. Text-only
    CC reasoning requires an index so identical answers cannot select a turn.
    """
    protocol_path(protocol)
    _bounded(chat_body)
    if type(chat_body) is not dict or set(chat_body) - _REQUEST_FIELDS:
        _fail('REQUEST')
    model, messages, limit = (chat_body.get(field) for field in ('model', 'messages', 'max_tokens'))
    if (type(model) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}', model)
            or type(messages) is not list or not 1 <= len(messages) <= 200
            or type(limit) is not int or limit <= 0 or chat_body.get('stream', False) is not False):
        _fail('REQUEST')
    responses = protocol == 'responses'
    records = _continuations(protocol, continuation)
    canonical = [_message(message) for message in messages]
    encoded, used = [], set()
    for index, message in enumerate(canonical):
        calls = message.get('tool_calls', [])
        indexed = ('index', index)
        key = indexed if indexed in records else ('calls', tuple(call['id'] for call in calls))
        if key in records:
            expected, replay = records[key]
            if key in used or not assistant_message_matches(expected, message):
                _fail('CONTINUATION')
            if responses:
                encoded.extend(replay)
            else:
                encoded.append(replay)
            used.add(key)
        elif not responses:
            encoded.append(message)
        elif message['role'] == 'tool':
            encoded.append({'type': 'function_call_output', 'call_id': message['tool_call_id'],
                'output': message['content'] or ''})
        else:
            if message['content'] is not None:
                encoded.append({'role': message['role'], 'content': message['content']})
            encoded.extend({'type': 'function_call', 'call_id': call['id'], **call['function']} for call in calls)
    if used != set(records):
        _fail('CONTINUATION')
    body = {'model': model, 'stream': False, 'input' if responses else 'messages': encoded,
        'max_output_tokens' if responses else 'max_tokens': limit}
    if responses:
        body['store'] = False
        body['include'] = ['reasoning.encrypted_content']
    if 'tools' in chat_body:
        body['tools'] = _tools(chat_body['tools'], responses)
    if 'parallel_tool_calls' in chat_body:
        if type(chat_body['parallel_tool_calls']) is not bool:
            _fail('TOOL_CHOICE')
        body['parallel_tool_calls'] = chat_body['parallel_tool_calls']
    if 'tool_choice' in chat_body:
        body['tool_choice'] = _choice(chat_body['tool_choice'], responses)
    _bounded(body)
    return body


def decode_response(protocol, raw):
    """Return (safe CC envelope, private replay record or None).

    Missing or invalid usage is omitted, never a zero count or an execution
    failure. This codec makes no inference about billing or dispatch outcomes.
    """
    protocol_path(protocol)
    _bounded(raw)
    if type(raw) is not dict or raw.get('error') is not None:
        _fail('RESPONSE')
    responses, continuation = protocol == 'responses', None
    if responses:
        if raw.get('status') != 'completed':
            _fail('INCOMPLETE')
        message, replay = _response_items(raw.get('output'))
        reason = 'tool_calls' if message.get('tool_calls') else 'stop'
        if message.get('tool_calls'):
            continuation = {'message': json.loads(json.dumps(message)), 'output': replay}
    else:
        choices = raw.get('choices')
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            _fail('RESPONSE')
        reason, source = choices[0].get('finish_reason'), choices[0].get('message')
        if type(reason) is not str or reason not in {'stop', 'tool_calls'}:
            _fail('INCOMPLETE')
        if type(source) is not dict or source.get('role') != 'assistant':
            _fail('RESPONSE')
        if source.get('refusal') is not None:
            _fail('REFUSAL')
        message = _message({key: source[key] for key in ('role', 'content', 'tool_calls') if key in source})
        if (reason == 'tool_calls') != bool(message.get('tool_calls')):
            _fail('RESPONSE')
        reasoning = source.get('reasoning_content')
        if reasoning is not None and type(reasoning) is not str:
            _fail('RESPONSE')
        if not message.get('tool_calls') and not (message['content'] or '').strip():
            _fail('EMPTY_OUTPUT')
        if reasoning is not None:
            continuation = {'message': json.loads(json.dumps(message)), 'reasoning_content': reasoning}
    value = {'id': 'chatcmpl-owner', 'object': 'chat.completion', 'created': 0, 'model': 'owner-model',
        'choices': [{'index': 0, 'message': message, 'finish_reason': reason}]}
    usage = _usage(raw.get('usage'), responses)
    if usage is not None:
        value['usage'] = usage
    _bounded([value, continuation])
    return value, continuation

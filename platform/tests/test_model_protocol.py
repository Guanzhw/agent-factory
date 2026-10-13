"""Offline wire contracts: no SDK, credentials, network or campaign required."""
from copy import deepcopy
import json
import unittest

from agent_factory.model_protocol import (
    MAX_BYTES, decode_response, encode_request, function_call, protocol_name, protocol_path,
)


def call(identifier='call-1', name='inspect', arguments='{}'):
    return {'id': identifier, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


def request(messages=None, **options):
    return {'model': 'fixture-model', 'messages': messages or [{'role': 'user', 'content': 'Inspect fixture'}],
        'max_tokens': 4096, 'stream': False, **options}


def response_item(identifier='call-1', **options):
    return {'type': 'function_call', 'id': 'fc_' + identifier, 'call_id': identifier,
        'name': 'inspect', 'arguments': '{}', 'status': 'completed', **options}


def text_item(text='Synthetic answer', **options):
    return {'type': 'message', 'id': 'msg_fixture', 'role': 'assistant', 'status': 'completed',
        'content': [{'type': 'output_text', 'text': text, 'annotations': []}], **options}


def responses(output=None, **options):
    return {'status': 'completed', 'output': [text_item()] if output is None else output, **options}


class ModelProtocolTests(unittest.TestCase):
    def test_protocol_default_and_explicit_null_are_distinct(self):
        self.assertEqual(protocol_name({}), 'chat-completions')
        for protocol, path in [('chat-completions', '/chat/completions'), ('responses', '/responses')]:
            self.assertEqual(protocol_name({'protocol': protocol}), protocol)
            self.assertEqual(protocol_path(protocol), path)
        for value in (None, '', 'auto', [], {}, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_UNSUPPORTED$'):
                protocol_name({'protocol': value})

    def test_cc_request_is_bounded_white_list_and_does_not_mutate_source(self):
        body = request([{'role': 'system', 'content': 'Follow fixture rules'},
            {'role': 'user', 'content': 'Inspect'},
            {'role': 'assistant', 'content': None, 'tool_calls': [call()]},
            {'role': 'tool', 'content': 'found', 'tool_call_id': 'call-1'}],
            tools=[{'type': 'function', 'function': {'name': 'inspect', 'description': 'Inspect fixture',
                'parameters': {'type': 'object', 'properties': {'optional': {'type': 'string'}}}}}],
            tool_choice='auto', parallel_tool_calls=False)
        original = deepcopy(body)
        encoded = encode_request('chat-completions', body)
        self.assertEqual(encoded, original)
        encoded['tools'][0]['function']['parameters']['properties'].clear()
        self.assertEqual(body, original)

    def test_responses_text_tools_and_choice_preserve_existing_schema_semantics(self):
        function = {'name': 'inspect', 'parameters': {'type': 'object',
            'properties': {'optional': {'type': 'string'}}}}
        body = request(tools=[{'type': 'function', 'function': function}],
            tool_choice={'type': 'function', 'function': {'name': 'inspect'}}, parallel_tool_calls=False)
        encoded = encode_request('responses', body)
        self.assertEqual(encoded['input'], body['messages'])
        self.assertEqual(encoded['max_output_tokens'], 4096)
        self.assertFalse(encoded['store'])
        self.assertEqual(encoded['include'], ['reasoning.encrypted_content'])
        self.assertFalse(encoded['stream'])
        self.assertNotIn('max_tokens', encoded)
        self.assertEqual(encoded['tools'], [{'type': 'function', **function, 'strict': False}])
        self.assertEqual(encoded['tool_choice'], {'type': 'function', 'name': 'inspect'})
        self.assertNotIn('required', encoded['tools'][0]['parameters'])
        body['tools'][0]['function']['strict'] = True
        self.assertTrue(encode_request('responses', body)['tools'][0]['strict'])

    def test_multiple_reasoning_tool_rounds_replay_once_in_original_order(self):
        reasoning = {'type': 'reasoning', 'id': 'rs_fixture', 'summary': [],
            'encrypted_content': 'opaque-synthetic-ciphertext'}
        first, first_context = decode_response('responses', responses([
            reasoning, text_item('Checking both', phase='commentary'),
            response_item('call-a'), response_item('call-b')]))
        second, second_context = decode_response('responses', responses([
            {**reasoning, 'id': 'rs_second'}, response_item('call-c')]))
        history = [
            {'role': 'user', 'content': 'Inspect both fixtures'}, first['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call-a', 'content': 'A'},
            {'role': 'tool', 'tool_call_id': 'call-b', 'content': 'B'}, second['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call-c', 'content': 'C'},
        ]
        before = deepcopy([history, first_context, second_context])
        encoded = encode_request('responses', request(history), [first_context, second_context])
        self.assertEqual(encoded['input'], [history[0], *first_context['output'],
            {'type': 'function_call_output', 'call_id': 'call-a', 'output': 'A'},
            {'type': 'function_call_output', 'call_id': 'call-b', 'output': 'B'},
            *second_context['output'], {'type': 'function_call_output', 'call_id': 'call-c', 'output': 'C'}])
        self.assertEqual([item['call_id'] for item in encoded['input'] if item.get('type') == 'function_call'],
            ['call-a', 'call-b', 'call-c'])
        self.assertEqual(sum(item.get('type') == 'message' for item in encoded['input']), 1)
        self.assertEqual([history, first_context, second_context], before)
        final, final_context = decode_response('responses', responses([reasoning, text_item('Done')]))
        self.assertEqual(final['choices'][0]['message']['content'], 'Done')
        self.assertIsNone(final_context)  # No promise of cross-user-turn reasoning memory.

    def test_continuations_cannot_be_attached_to_changed_or_missing_tool_turn(self):
        answer, context = decode_response('responses', responses([response_item()]))
        message = answer['choices'][0]['message']
        changed = deepcopy(message)
        changed['tool_calls'][0]['function']['arguments'] = '{"changed":true}'
        for history, contexts in [
            ([{'role': 'user', 'content': 'Unrelated'}], [context]),
            ([changed], [context]), ([message, message], [context]), ([message], [context, context]),
        ]:
            with self.subTest(history=history), self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_CONTINUATION$'):
                encode_request('responses', request(history), contexts)
        altered = deepcopy(context)
        altered['output'][0]['arguments'] = '{"changed":true}'
        with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_CONTINUATION$'):
            encode_request('responses', request([message]), [altered])
        with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_CONTINUATION$'):
            encode_request('chat-completions', request([message]), [context])

    def test_plain_canonical_tool_history_can_be_encoded_without_private_context(self):
        body = request([{'role': 'assistant', 'content': 'Checking', 'tool_calls': [call()]},
            {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'result'}])
        self.assertEqual(encode_request('responses', body)['input'], [
            {'role': 'assistant', 'content': 'Checking'},
            {'type': 'function_call', 'call_id': 'call-1', 'name': 'inspect', 'arguments': '{}'},
            {'type': 'function_call_output', 'call_id': 'call-1', 'output': 'result'}])

    def test_usage_is_optional_validated_and_mapped_without_execution_policy(self):
        for protocol in ('chat-completions', 'responses'):
            base = responses() if protocol == 'responses' else {'choices': [{'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'Synthetic answer'}}]}
            incoming = 'input_tokens' if protocol == 'responses' else 'prompt_tokens'
            outgoing = 'output_tokens' if protocol == 'responses' else 'completion_tokens'
            valid = {incoming: 2, outgoing: 3, 'total_tokens': 5}
            for usage in (None, {}, {**valid, incoming: True}, {**valid, outgoing: -1},
                    {**valid, 'total_tokens': 99}, {**valid, incoming: '2'},
                    {**valid, incoming: 2**70, 'total_tokens': 2**70 + 3}):
                result, _ = decode_response(protocol, {**base, 'usage': usage})
                self.assertNotIn('usage', result)
                self.assertEqual(result['choices'][0]['message']['content'], 'Synthetic answer')
            result, _ = decode_response(protocol, {**base, 'usage': valid})
            self.assertEqual(result['usage'], {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5})

    def test_remote_extra_fields_do_not_escape_into_completion_or_continuation(self):
        raw = responses([response_item(private='server-extension'), text_item(phase=None)],
            model='remote-arbitrary-model', id='remote-id', secret='untrusted-extra')
        result, context = decode_response('responses', raw)
        self.assertEqual(result['model'], 'owner-model')
        self.assertEqual(result['id'], 'chatcmpl-owner')
        self.assertNotIn('private', json.dumps(context))
        self.assertNotIn('remote-', json.dumps(result))
        self.assertNotIn('secret', result)
        cc, continuation = decode_response('chat-completions', {'private': 'ignored', 'choices': [{
            'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                'private': 'ignored', 'tool_calls': [{**call(), 'private': 'ignored'}]}}]})
        self.assertEqual(cc['choices'][0]['message']['tool_calls'], [call()])
        self.assertIsNone(continuation)

    def test_refusal_incomplete_and_unsupported_outputs_are_explicit(self):
        cases = [
            (responses(status='incomplete'), 'INCOMPLETE'),
            (responses([response_item(status='in_progress')]), 'INCOMPLETE'),
            (responses([text_item(content=[{'type': 'refusal', 'refusal': 'private'}])]), 'REFUSAL'),
            (responses([{'type': 'refusal'}]), 'REFUSAL'),
            (responses([{'type': 'web_search_call'}]), 'UNSUPPORTED_OUTPUT'),
            (responses([text_item(content=[{'type': 'image', 'data': 'unknown'}])]), 'UNSUPPORTED_OUTPUT'),
            (responses([{'type': 'reasoning', 'summary': []}]), 'RESPONSE'),
            (responses([{'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque'}, response_item()]), 'RESPONSE'),
            (responses([]), 'RESPONSE'),
            (responses([text_item(role='user')]), 'RESPONSE'),
        ]
        for payload, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_' + code + '$'):
                decode_response('responses', payload)
        with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_REFUSAL$'):
            decode_response('chat-completions', {'choices': [{'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': None, 'refusal': 'private'}}]})

    def test_tool_arguments_names_duplicate_ids_and_count_are_validated(self):
        for value in ([], {}, call(name='bad name'), call(identifier=''), call(arguments='[]'),
                call(arguments='{'), call(arguments='{"x":NaN}')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                function_call(value)
        for items in ([response_item(), response_item()], [response_item(str(i)) for i in range(17)]):
            with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_TOOL$'):
                decode_response('responses', responses(items))

    def test_unknown_options_and_noncanonical_input_fail_before_transport(self):
        for changes in ({'thinking': {'type': 'disabled'}}, {'temperature': .2}, {'stream': True},
                {'max_tokens': True}, {'tools': [{}]}, {'tool_choice': []}, {'parallel_tool_calls': 'false'},
                {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'x'}]}]},
                {'messages': [{'role': 'user', 'content': 'x', 'provider_data': {}}]},
                {'messages': [{'role': [], 'content': 'x'}]},
                {'messages': [{'role': 'tool', 'content': 'x'}]}):
            for protocol in ('chat-completions', 'responses'):
                with self.subTest(changes=changes, protocol=protocol), self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
                    encode_request(protocol, {**request(), **changes})

    def test_json_size_depth_and_non_json_shapes_are_bounded(self):
        deep = {}
        for _ in range(33):
            deep = {'nested': deep}
        for body in (request([{'role': 'user', 'content': 'x' * MAX_BYTES}]), request(extra=deep),
                request(extra=float('nan')), request(extra=object())):
            with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
                encode_request('responses', body)
        for raw in (None, [], {'choices': []}, {'choices': [{'finish_reason': [], 'message': {}}]},
                responses([text_item(phase=[])]), responses([{'type': 'reasoning', 'summary': {}}])):
            with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
                decode_response('responses' if type(raw) is dict and 'output' in raw else 'chat-completions', raw)


if __name__ == '__main__':
    unittest.main()

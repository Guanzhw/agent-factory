"""Offline wire contracts: no SDK, credentials, network or campaign required."""
from copy import deepcopy
import json
import unittest

from agent_factory.model_protocol import (
    MAX_BYTES, assistant_message_matches, decode_response, encode_request, function_call, protocol_name, protocol_path,
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

    def test_native_tool_turn_normalization_preserves_original_responses_replay(self):
        original_args = '{ "label": "\\u6d4b\\u8bd5", "nested": {"b":2, "a":[1.0,true,null]} }'
        native_args = '{"nested":{"a":[1,true,null],"b":2},"label":"测试"}'
        for original_content in (None, ''):
            output = ([] if original_content is None else [text_item('')]) + [
                response_item(arguments=original_args)]
            answer, context = decode_response('responses', responses(output))
            native_message = deepcopy(answer['choices'][0]['message'])
            native_message['content'] = '' if original_content is None else None
            native_message['tool_calls'][0]['function']['arguments'] = native_args
            before = deepcopy(context)
            encoded = encode_request('responses', request([native_message,
                {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'result'}]), [context])
            self.assertEqual(encoded['input'][:-1], context['output'])
            self.assertEqual(next(item for item in encoded['input'] if item.get('type') == 'function_call')['arguments'],
                original_args)
            self.assertEqual(context, before)

    def test_tool_turn_semantics_reject_real_changes_and_boolean_number_coercion(self):
        arguments = '{"nested":{"number":1,"flag":true,"list":[1,2]}}'
        answer, context = decode_response('responses', responses([response_item(arguments=arguments)]))
        original = answer['choices'][0]['message']
        for changed_args in (
            '{"nested":{"number":true,"flag":true,"list":[1,2]}}',
            '{"nested":{"number":1,"flag":1,"list":[1,2]}}',
            '{"nested":{"number":1,"flag":true,"list":[2,1]}}',
            '{"nested":{"number":1.0000000000000001,"flag":true,"list":[1,2]}}',
            '{"nested":{"number":NaN,"flag":true,"list":[1,2]}}',
            '[]',
        ):
            changed = deepcopy(original)
            changed['content'] = ''
            changed['tool_calls'][0]['function']['arguments'] = changed_args
            with self.subTest(arguments=changed_args), self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
                encode_request('responses', request([changed]), [context])
        changed_messages = []
        for field, value in (('name', 'different'), ('arguments', '{"different":true}')):
            changed = deepcopy(original)
            changed['tool_calls'][0]['function'][field] = value
            changed_messages.append(changed)
        changed_messages.extend([{**original, 'content': ' '}, {**original, 'content': 'different'},
            {**original, 'tool_calls': [call('other-call')]},
            {**original, 'tool_calls': original['tool_calls'] * 2}])
        multi, multi_context = decode_response('responses', responses([response_item('call-1'), response_item('call-2')]))
        reversed_turn = deepcopy(multi['choices'][0]['message'])
        reversed_turn['tool_calls'].reverse()
        for changed, record in [(message, context) for message in changed_messages] + [(reversed_turn, multi_context)]:
            with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
                encode_request('responses', request([changed]), [record])

    def test_cc_reasoning_is_private_and_restored_for_normalized_tool_turn(self):
        arguments = '{ "number": 1.0, "flag": true }'
        source = {'role': 'assistant', 'content': None, 'tool_calls': [call(arguments=arguments)],
            'reasoning_content': 'synthetic private reasoning'}
        answer, context = decode_response('chat-completions', {'choices': [
            {'finish_reason': 'tool_calls', 'message': source}]})
        self.assertNotIn('reasoning_content', answer['choices'][0]['message'])
        self.assertEqual(context, {'message': answer['choices'][0]['message'],
            'reasoning_content': source['reasoning_content']})
        native_message = deepcopy(answer['choices'][0]['message'])
        native_message['content'] = ''
        native_message['tool_calls'][0]['function']['arguments'] = '{"flag":true,"number":1}'
        before = deepcopy(context)
        encoded = encode_request('chat-completions', request([native_message,
            {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'result'}]), [context])
        self.assertEqual(encoded['messages'][0], {**source})
        self.assertEqual(context, before)
        with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_MESSAGE$'):
            encode_request('chat-completions', request([source]))  # Untrusted public input cannot supply private reasoning.

    def test_cc_reasoning_shape_and_context_are_checked_without_requiring_usage(self):
        for reasoning in (None, ''):
            source = {'role': 'assistant', 'content': None, 'tool_calls': [call()], 'reasoning_content': reasoning}
            answer, record = decode_response('chat-completions', {'choices': [
                {'finish_reason': 'tool_calls', 'message': source}]})
            self.assertNotIn('usage', answer)
            if reasoning is None:
                self.assertIsNone(record)
            else:
                self.assertEqual(record['reasoning_content'], '')
        for reasoning in (True, 1, [], {}, 'x' * MAX_BYTES):
            with self.subTest(reasoning_type=type(reasoning)), self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
                decode_response('chat-completions', {'choices': [{'finish_reason': 'tool_calls', 'message': {
                    'role': 'assistant', 'content': None, 'tool_calls': [call()], 'reasoning_content': reasoning}}]})
        message = {'role': 'assistant', 'content': None, 'tool_calls': [call()]}
        for reasoning in (True, 1, [], {}, None):
            with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
                encode_request('chat-completions', request([message]), [{'message': message, 'reasoning_content': reasoning}])

    def test_cc_final_reasoning_replays_at_explicit_positions_even_with_identical_answers(self):
        answer = {'role': 'assistant', 'content': 'Same synthetic answer'}
        records = []
        for reasoning in ('first synthetic reasoning', 'second synthetic reasoning'):
            envelope, record = decode_response('chat-completions', {'choices': [{'finish_reason': 'stop',
                'message': {**answer, 'reasoning_content': reasoning}}]})
            self.assertEqual(envelope['choices'][0]['message'], answer)
            self.assertEqual(record, {'message': answer, 'reasoning_content': reasoning})
            records.append(record)
        history = [{'role': 'user', 'content': 'First'}, answer, {'role': 'user', 'content': 'Second'}, answer,
            {'role': 'user', 'content': 'Now inspect with tools'}]
        encoded = encode_request('chat-completions', request(history,
            tools=[{'type': 'function', 'function': {'name': 'inspect', 'parameters': {'type': 'object'}}}]),
            [{**records[0], 'message_index': 1}, {**records[1], 'message_index': 3}])
        self.assertEqual(encoded['messages'][1]['reasoning_content'], 'first synthetic reasoning')
        self.assertEqual(encoded['messages'][3]['reasoning_content'], 'second synthetic reasoning')
        self.assertNotIn('reasoning_content', history[1])
        for record in (records[0], {**records[0], 'message_index': 0},
                {**records[0], 'message_index': 20}, {**records[0], 'message_index': True}):
            with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_CONTINUATION$'):
                encode_request('chat-completions', request(history), [record])
        with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_CONTINUATION$'):
            encode_request('chat-completions', request(history), [{**records[0], 'message_index': 1}] * 2)

    def test_public_assistant_comparison_validates_shape_and_keeps_text_turns_exact(self):
        self.assertTrue(assistant_message_matches({'role': 'assistant', 'content': 'same'},
            {'role': 'assistant', 'content': 'same'}))
        self.assertFalse(assistant_message_matches({'role': 'assistant', 'content': None},
            {'role': 'assistant', 'content': ''}))
        self.assertFalse(assistant_message_matches({'role': 'assistant', 'content': 'same'},
            {'role': 'assistant', 'content': 'same '}))
        self.assertTrue(assistant_message_matches({'role': 'assistant', 'content': None,
            'tool_calls': [call(arguments='{ "number": 1.0 }')]}, {'role': 'assistant', 'content': '',
            'tool_calls': [call(arguments='{"number":1}')]}))
        self.assertFalse(assistant_message_matches({'role': 'assistant', 'content': None,
            'tool_calls': [call(arguments='{"number":1}')]}, {'role': 'assistant', 'content': '',
            'tool_calls': [call(arguments='{"number":true}')]}))
        with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_'):
            assistant_message_matches({'role': 'assistant', 'content': 'same'},
                {'role': 'assistant', 'content': 'same', 'reasoning_content': 'untrusted'})

    def test_completed_empty_outputs_are_rejected_but_tool_only_turns_remain_valid(self):
        for content in (None, '', ' \n\t', '\u3000'):
            message = {'role': 'assistant', 'content': content}
            with self.subTest(protocol='chat-completions', content=content), self.assertRaisesRegex(
                    ValueError, '^MODEL_PROTOCOL_EMPTY_OUTPUT$'):
                decode_response('chat-completions', {'choices': [{'finish_reason': 'stop', 'message': message}]})
            result, _ = decode_response('chat-completions', {'choices': [{'finish_reason': 'tool_calls',
                'message': {**message, 'tool_calls': [call()]}}]})
            self.assertEqual(result['choices'][0]['message']['tool_calls'], [call()])
        reasoning = {'type': 'reasoning', 'id': 'rs_fixture', 'summary': [], 'encrypted_content': 'opaque'}
        for output in ([], [reasoning], [text_item(content=[])], [text_item('')], [text_item(' \n\t')],
                [reasoning, text_item('\u3000')]):
            with self.subTest(protocol='responses', output=output), self.assertRaisesRegex(
                    ValueError, '^MODEL_PROTOCOL_EMPTY_OUTPUT$'):
                decode_response('responses', responses(output))
            result, _ = decode_response('responses', responses([*output, response_item()]))
            self.assertEqual(result['choices'][0]['message']['tool_calls'], [call()])
        with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_EMPTY_OUTPUT$'):
            decode_response('chat-completions', {'choices': [{'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': None, 'reasoning_content': 'synthetic reasoning without answer'}}]})

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
            (responses([]), 'EMPTY_OUTPUT'),
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

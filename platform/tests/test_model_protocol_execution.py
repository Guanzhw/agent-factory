"""Offline owner model protocol execution; synthetic responses and credentials only."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.exceptions import ModelProviderError
from agno.models.message import Message
import httpx

from agent_factory.byok_model import OwnerChatModel, PinnedChatTransport
from agent_factory.owner_runtime_broker import OwnerModelCallError, OwnerRuntimeBroker
from agent_factory.personal_remote_provider import SecretLease


def response_output(*, tool=False):
    output = [{'type': 'reasoning', 'id': 'rs_synthetic', 'summary': [],
        'encrypted_content': 'synthetic-encrypted-reasoning'}]
    if tool:
        output.append({'type': 'function_call', 'id': 'fc_synthetic', 'call_id': 'call_synthetic',
            'name': 'checksum_fixture', 'arguments': '{}', 'status': 'completed'})
    else:
        output.append({'type': 'message', 'id': 'msg_synthetic_output', 'role': 'assistant',
            'status': 'completed', 'content': [{'type': 'output_text', 'text': 'synthetic completion', 'annotations': []}]})
    return {'id': 'resp_synthetic', 'object': 'response', 'status': 'completed', 'output': output}


class OwnerProtocolExecutionTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.calls = []
        self.config = {'ownerId': 'synthetic-owner', 'reference': 'synthetic-model-ref', 'revision': 'model-r1',
            'credentialRef': 'synthetic-credential-ref', 'credentialRevision': 'credential-r1',
            'provider': 'openai-compatible', 'model': 'gpt-6-luna', 'protocol': 'responses',
            'baseURL': 'https://opencode.ai/inference/go/v1'}
        self.revoked = False
        self.answer = response_output()
        self.checksum_tools = [{'type': 'function', 'function': {
            'name': 'checksum_fixture', 'parameters': {'type': 'object'}}}]

    def wire(self, request):
        self.calls.append(request)
        return httpx.Response(200, json=self.answer)

    def check(self):
        if self.revoked: raise ValueError('SYNTHETIC_REVOKED')

    def model(self):
        return OwnerChatModel(self.config, lambda: SecretLease('api-key', 'synthetic-private-key'),
            transport_factory=lambda: httpx.MockTransport(self.wire), recheck=self.check,
            session_id='af-plan-syntheticprotocol')

    def broker(self, **kwargs):
        handle = SimpleNamespace(owner='synthetic-owner', body=dict(self.config), check=self.check,
            credential=lambda: SecretLease('api-key', 'synthetic-private-key'),
            service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(self.wire)))
        return OwnerRuntimeBroker(Path(self.folder.name) / 'model.sock', handle, **kwargs)

    def test_agno_responses_runs_native_function_loop_with_reasoning_and_optional_usage(self):
        self.answer = response_output(tool=True)
        original = self.wire
        def wire(request):
            result = original(request)
            self.answer = response_output()
            return result
        self.wire = wire
        def checksum_fixture(): return 'synthetic-checksum'
        result = asyncio.run(Agent(model=self.model(), tools=[checksum_fixture], markdown=False).arun('synthetic task'))
        self.assertEqual(result.content, 'synthetic completion')
        self.assertEqual(len(self.calls), 2)
        first, second = [json.loads(request.content) for request in self.calls]
        self.assertEqual(str(self.calls[0].url), 'https://opencode.ai/inference/go/v1/responses')
        self.assertEqual(first['model'], 'gpt-6-luna')
        self.assertFalse(first['store']); self.assertFalse(first['stream'])
        self.assertEqual(first['max_output_tokens'], 4096)
        self.assertIn('reasoning.encrypted_content', first['include'])
        self.assertEqual(first['tools'][0]['type'], 'function')
        self.assertEqual(first['tools'][0]['name'], 'checksum_fixture')
        types = [item.get('type') for item in second['input']]
        self.assertLess(types.index('reasoning'), types.index('function_call'))
        self.assertLess(types.index('function_call'), types.index('function_call_output'))
        self.assertEqual(next(item for item in second['input'] if item.get('type') == 'reasoning')['encrypted_content'],
            'synthetic-encrypted-reasoning')
        self.assertEqual(next(item for item in second['input'] if item.get('type') == 'function_call_output')['output'],
            'synthetic-checksum')
        self.assertEqual(self.calls[0].headers['x-opencode-session'], self.calls[1].headers['x-opencode-session'])

    def test_broker_responses_returns_cc_and_replays_only_same_session_tool_continuation(self):
        broker = self.broker(); self.answer = response_output(tool=True)
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}],
            'tools': [{'type': 'function', 'function': {'name': 'checksum_fixture', 'parameters': {'type': 'object'}}}],
            'tool_choice': {'type': 'function', 'function': {'name': 'checksum_fixture'}}}
        first = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
        self.assertEqual(first['choices'][0]['finish_reason'], 'tool_calls')
        self.assertNotIn('synthetic-encrypted-reasoning', json.dumps(first))
        outgoing = json.loads(self.calls[0].content)
        self.assertEqual(outgoing['tool_choice'], {'type': 'function', 'name': 'checksum_fixture'})
        next_body = {**body, 'messages': [*body['messages'], first['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call_synthetic', 'content': 'synthetic-checksum'}]}
        self.answer = response_output()
        answer = broker.native_completion(next_body, 'ses_synthetic0001', 'msg_synthetic0001')
        self.assertEqual(answer['choices'][0]['message']['content'], 'synthetic completion')
        self.assertIn('reasoning', [item.get('type') for item in json.loads(self.calls[1].content)['input']])
        self.assertEqual(broker.native_completion(next_body, 'ses_synthetic0001', 'msg_synthetic0001'), answer)
        with self.assertRaises(OwnerModelCallError) as caught:
            broker.native_completion(next_body, 'ses_synthetic0002', 'msg_synthetic0001')
        self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        self.assertEqual(len(self.calls), 2)

    def test_agno_continuation_survives_reconstruction_but_not_credential_revision_change(self):
        self.answer = response_output(tool=True)
        first = asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic task')],
            tools=self.checksum_tools))
        assistant = Message(role='assistant', content=first.content, tool_calls=first.tool_calls,
            provider_data=first.provider_data)
        messages = [Message(role='user', content='synthetic task'), assistant,
            Message(role='tool', tool_call_id='call_synthetic', content='synthetic-checksum')]
        self.answer = response_output()
        self.assertEqual(asyncio.run(self.model().ainvoke(messages)).content, 'synthetic completion')
        self.config['credentialRevision'] = 'credential-r2'
        with self.assertRaises(ModelProviderError): asyncio.run(self.model().ainvoke(messages))
        self.assertEqual(len(self.calls), 2)

    def test_broker_responses_unknown_is_not_redispatched(self):
        def wire(request):
            self.calls.append(request)
            raise httpx.ReadTimeout('synthetic timeout')
        self.wire = wire
        broker = self.broker()
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
        diagnostics = []
        for _ in range(2):
            with self.assertRaises(OwnerModelCallError) as caught:
                broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
            self.assertEqual(caught.exception.code, 'OWNER_MODEL_CALL_UNCONFIRMED')
            diagnostics.append(caught.exception.diagnostic_id)
        self.assertEqual(diagnostics[0], diagnostics[1]); self.assertEqual(len(self.calls), 1)

    def test_two_function_rounds_work_in_both_protocols_and_execution_paths(self):
        for protocol in ('chat-completions', 'responses'):
            for execution in ('agno', 'broker'):
                with self.subTest(protocol=protocol, execution=execution):
                    self.calls = []
                    self.config.update(protocol=protocol,
                        model='gpt-6-luna' if protocol == 'responses' else 'deepseek-flash')
                    def wire(request):
                        self.calls.append(request)
                        turn = len(self.calls)
                        if protocol == 'responses':
                            payload = response_output(tool=turn < 3)
                            if turn < 3:
                                payload['output'][0]['id'] = f'rs_synthetic{turn}'
                                payload['output'][1].update(id=f'fc_synthetic{turn}', call_id=f'call_synthetic{turn}')
                        else:
                            message = {'role': 'assistant', 'content': 'synthetic completion'}
                            if turn < 3:
                                message.update(content=None, reasoning_content=f'synthetic-private-reasoning-{turn}',
                                    tool_calls=[{'type': 'function', 'id': f'call_synthetic{turn}',
                                    'function': {'name': 'checksum_fixture', 'arguments': '{}'}}])
                            payload = {'choices': [{'message': message, 'finish_reason': 'tool_calls' if turn < 3 else 'stop'}]}
                        return httpx.Response(200, json=payload)
                    self.wire = wire
                    if execution == 'agno':
                        def checksum_fixture(): return 'synthetic-checksum'
                        answer = asyncio.run(Agent(model=self.model(), tools=[checksum_fixture], markdown=False).arun('synthetic task'))
                        self.assertEqual(answer.content, 'synthetic completion')
                    else:
                        broker = self.broker()
                        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}],
                            'tools': [{'type': 'function', 'function': {'name': 'checksum_fixture', 'parameters': {'type': 'object'}}}]}
                        for turn in range(1, 4):
                            answer = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
                            if turn < 3:
                                body['messages'].extend([answer['choices'][0]['message'],
                                    {'role': 'tool', 'tool_call_id': f'call_synthetic{turn}', 'content': 'synthetic-checksum'}])
                        self.assertEqual(answer['choices'][0]['message']['content'], 'synthetic completion')
                    self.assertEqual(len(self.calls), 3)
                    self.assertTrue(all(json.loads(request.content)['parallel_tool_calls'] is False for request in self.calls))
                    if protocol == 'responses':
                        final_input = json.loads(self.calls[2].content)['input']
                        self.assertEqual([item['id'] for item in final_input if item.get('type') == 'reasoning'],
                            ['rs_synthetic1', 'rs_synthetic2'])
                    else:
                        final_messages = json.loads(self.calls[2].content)['messages']
                        self.assertEqual([message['reasoning_content'] for message in final_messages if message['role'] == 'assistant'],
                            ['synthetic-private-reasoning-1', 'synthetic-private-reasoning-2'])

    def test_agno_preserves_cc_final_reasoning_across_persisted_user_turns(self):
        self.config.update(protocol='chat-completions', model='deepseek-flash')
        def wire(request):
            self.calls.append(request)
            turn = len(self.calls)
            message = {'role': 'assistant', 'content': 'synthetic first answer' if turn == 1 else 'synthetic completion',
                'reasoning_content': f'synthetic-private-reasoning-{turn}'}
            if turn == 2:
                message.update(content=None, tool_calls=[{'id': 'call_synthetic', 'type': 'function',
                    'function': {'name': 'checksum_fixture', 'arguments': '{}'}}])
            return httpx.Response(200, json={'choices': [{'message': message,
                'finish_reason': 'tool_calls' if turn == 2 else 'stop'}]})
        self.wire = wire
        def checksum_fixture(): return 'synthetic-checksum'
        agent = Agent(model=self.model(), tools=[checksum_fixture], db=InMemoryDb(), add_history_to_context=True,
            session_id='synthetic-persisted-session', markdown=False)
        self.assertEqual(asyncio.run(agent.arun('synthetic first user')).content, 'synthetic first answer')
        self.assertEqual(asyncio.run(agent.arun('synthetic second user')).content, 'synthetic completion')
        self.assertEqual(len(self.calls), 3)
        final = json.loads(self.calls[2].content)
        self.assertEqual([message['reasoning_content'] for message in final['messages'] if message['role'] == 'assistant'],
            ['synthetic-private-reasoning-1', 'synthetic-private-reasoning-2'])

    def test_empty_or_refusal_is_terminal_in_both_protocols_and_execution_paths(self):
        cc_messages = [{'role': 'assistant', 'content': value} for value in (None, '', ' \n ')] + [
            {'role': 'assistant', 'content': None, 'reasoning_content': 'synthetic thinking only'},
            {'role': 'assistant', 'content': None, 'refusal': 'synthetic refusal'}]
        responses_outputs = [
            [{'type': 'message', 'role': 'assistant', 'content': []}],
            [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': ''}]}],
            [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': ' \n '}]}],
            [{'type': 'reasoning', 'id': 'rs_synthetic_empty', 'summary': [], 'encrypted_content': 'synthetic thinking only'}],
            [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal', 'refusal': 'synthetic refusal'}]}],
        ]
        for protocol, payloads in (
                ('chat-completions', [{'choices': [{'finish_reason': 'stop', 'message': message}]} for message in cc_messages]),
                ('responses', [{'status': 'completed', 'output': output} for output in responses_outputs])):
            for index, payload in enumerate(payloads):
                for execution in ('agno', 'broker'):
                    with self.subTest(protocol=protocol, payload=index, execution=execution):
                        self.config.update(protocol=protocol, model='gpt-6-luna' if protocol == 'responses' else 'deepseek-flash')
                        self.calls = []; self.answer = payload
                        if execution == 'agno':
                            with self.assertRaises(ModelProviderError) as caught:
                                asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic task')]))
                            self.assertIn('PERSONAL_MODEL_REFUSAL' if index == 4 else 'PERSONAL_MODEL_EMPTY_OUTPUT', str(caught.exception))
                        else:
                            broker = self.broker()
                            body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
                            diagnostics = []
                            for _ in range(2):
                                with self.assertRaises(OwnerModelCallError) as caught:
                                    broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
                                self.assertEqual(caught.exception.code, 'OWNER_MODEL_CALL_UNCONFIRMED')
                                expected_reason = 'MODEL_REFUSAL' if index == 4 else 'MODEL_EMPTY_OUTPUT'
                                self.assertEqual(caught.exception.response()['error']['terminalReason'], expected_reason)
                                diagnostics.append(caught.exception.diagnostic_id)
                            self.assertEqual(diagnostics[0], diagnostics[1]); self.assertEqual(broker.continuations, {})
                        self.assertEqual(len(self.calls), 1)

    def test_unmarked_tool_history_is_not_silently_resumed_after_restart(self):
        assistant = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_synthetic', 'type': 'function',
            'function': {'name': 'checksum_fixture', 'arguments': '{}'}}]}
        tool = {'role': 'tool', 'tool_call_id': 'call_synthetic', 'content': 'synthetic result'}
        for protocol in ('chat-completions', 'responses'):
            with self.subTest(protocol=protocol):
                self.config['protocol'] = protocol
                messages = [{'role': 'user', 'content': 'synthetic task'}, assistant, tool]
                with self.assertRaises(ModelProviderError):
                    asyncio.run(self.model().ainvoke([Message(**message) for message in messages]))
                with self.assertRaises(OwnerModelCallError) as caught:
                    self.broker().native_completion({'model': 'owner-model', 'messages': messages},
                        'ses_synthetic0001', 'msg_synthetic0001')
                self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        self.assertEqual(self.calls, [])

    def test_user_only_summary_branch_does_not_replay_or_replace_original_receipt(self):
        for protocol in ('chat-completions', 'responses'):
            with self.subTest(protocol=protocol):
                self.config['protocol'] = protocol
                self.answer = response_output() if protocol == 'responses' else {
                    'choices': [{'message': {'role': 'assistant', 'content': 'synthetic first answer'}, 'finish_reason': 'stop'}]}
                self.calls = []
                broker = self.broker()
                body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
                first = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
                self.assertEqual(broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001'), first)
                summary = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0002')
                self.assertEqual(broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0002'), summary)
                self.assertEqual(broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001'), first)
                self.assertEqual(len(self.calls), 2)
                # A third unseen request cannot overwrite an unconsumed summary.
                with self.assertRaises(OwnerModelCallError) as caught:
                    broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0003')
                self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
                self.assertEqual(len(self.calls), 2)

    def test_cc_private_markers_cannot_fall_back_after_scope_changes(self):
        self.config.update(protocol='chat-completions', model='deepseek-flash')
        self.answer = {'choices': [{'message': {'role': 'assistant', 'content': None,
            'reasoning_content': 'synthetic-private-reasoning', 'tool_calls': [{'id': 'call_synthetic', 'type': 'function',
                'function': {'name': 'checksum_fixture', 'arguments': '{}'}}]}, 'finish_reason': 'tool_calls'}]}
        original = dict(self.config)
        model = self.model()
        first = asyncio.run(model.ainvoke([Message(role='user', content='synthetic task')],
            tools=self.checksum_tools))
        messages = [Message(role='user', content='synthetic task'), Message(role='assistant', content=first.content,
            tool_calls=first.tool_calls, provider_data=first.provider_data),
            Message(role='tool', tool_call_id='call_synthetic', content='synthetic result')]
        for field, value in (('ownerId', 'another-owner'), ('revision', 'model-r2'),
                ('credentialRevision', 'credential-r2'), ('model', 'different-model'),
                ('baseURL', 'https://models.example.com/v1'), ('protocol', 'responses')):
            with self.subTest(path='agno', field=field):
                self.config = {**original, field: value}
                with self.assertRaises(ModelProviderError): asyncio.run(self.model().ainvoke(messages))
        self.config = original
        model = self.model(); model._session_id = 'another-synthetic-session'
        with self.assertRaises(ModelProviderError): asyncio.run(model.ainvoke(messages))
        self.assertEqual(len(self.calls), 1)

        broker = self.broker()
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
        result = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
        body['messages'].extend([result['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call_synthetic', 'content': 'synthetic result'}])
        for number, (field, value) in enumerate((('revision', 'model-r2'), ('credentialRevision', 'credential-r2'),
                ('model', 'different-model'), ('baseURL', 'https://models.example.com/v1'), ('protocol', 'responses'))):
            with self.subTest(path='broker', field=field):
                broker.handle.body = {**original, field: value}
                with self.assertRaises(OwnerModelCallError) as caught:
                    broker.native_completion(body, 'ses_synthetic0001', f'msg_syntheticchange{number}')
                self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        broker.handle.body = original
        for session, owner in (('ses_synthetic0002', 'synthetic-owner'), ('ses_synthetic0001', 'another-owner')):
            broker.handle.owner = owner
            with self.assertRaises(OwnerModelCallError) as caught:
                broker.native_completion(body, session, 'msg_syntheticfinalchange')
            self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        self.assertEqual(len(self.calls), 2)

    def test_legacy_agno_responses_private_record_can_still_be_read(self):
        self.answer = response_output(tool=True)
        model = self.model()
        first = asyncio.run(model.ainvoke([Message(role='user', content='synthetic task')],
            tools=self.checksum_tools))
        private = first.provider_data['owner_model_continuation']
        legacy = {'owner_responses': {field: private[field] for field in ('scope', 'session', 'continuation')}}
        self.answer = response_output()
        result = asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic task'),
            Message(role='assistant', content=first.content, tool_calls=first.tool_calls, provider_data=legacy),
            Message(role='tool', tool_call_id='call_synthetic', content='synthetic result')]))
        self.assertEqual(result.content, 'synthetic completion')

    def test_agno_retained_private_markers_follow_the_current_message_positions(self):
        original = dict(self.config)
        for protocol, legacy in (('chat-completions', False), ('responses', False), ('responses', True)):
            with self.subTest(protocol=protocol, legacy=legacy):
                self.config = {**original, 'protocol': protocol}
                self.calls = []
                self.answer = response_output(tool=True) if protocol == 'responses' else {'choices': [{
                    'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                        'reasoning_content': 'synthetic-private-reasoning', 'tool_calls': [{'id': 'call_synthetic',
                            'type': 'function', 'function': {'name': 'checksum_fixture', 'arguments': '{}'}}]}}]}
                first = asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic original task')],
                    tools=self.checksum_tools))
                marker = deepcopy(first.provider_data)
                if legacy:
                    private = marker['owner_model_continuation']
                    marker = {'owner_responses': {field: private[field] for field in ('scope', 'session', 'continuation')}}
                self.answer = response_output() if protocol == 'responses' else {'choices': [{
                    'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'synthetic completion'}}]}
                # Agno owns the messages: dropping earlier complete turns and
                # prepending a summary must not depend on the broker's ordinal.
                result = asyncio.run(self.model().ainvoke([
                    Message(role='system', content='Synthetic summary of earlier complete turns.'),
                    Message(role='user', content='synthetic current task'),
                    Message(role='assistant', content=first.content, tool_calls=first.tool_calls, provider_data=marker),
                    Message(role='tool', tool_call_id='call_synthetic', content='synthetic result')]))
                self.assertEqual(result.content, 'synthetic completion')
                self.assertEqual(len(self.calls), 2)
                sent = json.loads(self.calls[1].content)
                if protocol == 'responses':
                    self.assertEqual([item['encrypted_content'] for item in sent['input'] if item.get('type') == 'reasoning'],
                        ['synthetic-encrypted-reasoning'])
                else:
                    self.assertEqual(sent['messages'][2]['reasoning_content'], 'synthetic-private-reasoning')

    def test_agno_current_and_legacy_markers_reject_foreign_bindings_before_credentials(self):
        original = dict(self.config)
        for protocol, legacy in (('chat-completions', False), ('responses', False), ('responses', True)):
            with self.subTest(protocol=protocol, legacy=legacy):
                bound = {**original, 'protocol': protocol}
                self.config = bound
                self.answer = response_output(tool=True) if protocol == 'responses' else {'choices': [{
                    'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                        'reasoning_content': 'synthetic-private-reasoning', 'tool_calls': [{'id': 'call_synthetic',
                            'type': 'function', 'function': {'name': 'checksum_fixture', 'arguments': '{}'}}]}}]}
                first = asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic original task')],
                    tools=self.checksum_tools))
                marker = deepcopy(first.provider_data)
                if legacy:
                    private = marker['owner_model_continuation']
                    marker = {'owner_responses': {field: private[field] for field in ('scope', 'session', 'continuation')}}
                messages = [Message(role='system', content='Synthetic compacted prior context.'),
                    Message(role='assistant', content=first.content, tool_calls=first.tool_calls, provider_data=marker),
                    Message(role='tool', tool_call_id='call_synthetic', content='synthetic result')]
                resolutions = []
                def credential():
                    resolutions.append('resolved')
                    return SecretLease('api-key', 'synthetic-private-key')
                calls_before = len(self.calls)
                for field, value in (('ownerId', 'another-synthetic-owner'), ('reference', 'another-model-reference'),
                        ('revision', 'model-r2'), ('credentialRef', 'another-credential-reference'),
                        ('credentialRevision', 'credential-r2'), ('model', 'another-model'),
                        ('baseURL', 'https://models.example.com/v1'),
                        ('protocol', 'responses' if protocol == 'chat-completions' else 'chat-completions')):
                    with self.subTest(field=field):
                        self.config = {**bound, field: value}
                        model = self.model(); model._credential = credential
                        with self.assertRaises(ModelProviderError): asyncio.run(model.ainvoke(messages))
                self.config = bound
                model = self.model(); model._credential = credential
                model._session_id = 'another-synthetic-session'
                with self.assertRaises(ModelProviderError): asyncio.run(model.ainvoke(messages))

                # Invalid existing metadata cannot be treated as absent, even
                # with a valid legacy record alongside the current marker.
                model = self.model(); model._credential = credential
                marker_name = 'owner_responses' if legacy else 'owner_model_continuation'
                changed = deepcopy(marker)
                changed[marker_name]['scope'] = 'foreign-owner-scope'
                if not legacy and protocol == 'responses':
                    changed['owner_responses'] = deepcopy(marker[marker_name])
                invalid = Message(role='assistant', content=first.content, tool_calls=first.tool_calls, provider_data=changed)
                with self.assertRaises(ModelProviderError):
                    asyncio.run(model.ainvoke([messages[0], invalid, messages[2]]))
                changed = deepcopy(marker)
                changed[marker_name]['session'] = 'foreign-session'
                invalid = Message(role='assistant', content=first.content, tool_calls=first.tool_calls, provider_data=changed)
                with self.assertRaises(ModelProviderError):
                    asyncio.run(model.ainvoke([messages[0], invalid, messages[2]]))
                self.assertEqual(resolutions, [])
                self.assertEqual(len(self.calls), calls_before)

    def test_broker_continuation_cannot_cross_credential_revision_or_owner(self):
        broker = self.broker(); self.answer = response_output(tool=True)
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
        answer = broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
        body['messages'].extend([answer['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call_synthetic', 'content': 'synthetic-checksum'}])
        broker.handle.body['credentialRevision'] = 'credential-r2'
        with self.assertRaises(OwnerModelCallError) as caught:
            broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0002')
        self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        broker.handle.body['credentialRevision'] = 'credential-r1'
        broker.handle.owner = 'another-synthetic-owner'
        with self.assertRaises(OwnerModelCallError) as caught:
            broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0003')
        self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        self.assertEqual(len(self.calls), 1)

    def test_both_paths_reject_secret_echo_in_encrypted_reasoning(self):
        self.answer = response_output(tool=True)
        self.answer['output'][0]['encrypted_content'] = 'synthetic-private-key'
        with self.assertRaises(ModelProviderError):
            asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic task')]))
        broker = self.broker()
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic task'}]}
        for _ in range(2):
            with self.assertRaises(OwnerModelCallError) as caught:
                broker.native_completion(body, 'ses_synthetic0001', 'msg_synthetic0001')
            self.assertEqual(caught.exception.code, 'OWNER_MODEL_CALL_UNCONFIRMED')
        self.assertEqual(broker.continuations, {})
        self.assertEqual(len(self.calls), 2)

    def test_both_paths_preserve_chat_completions_tool_choice_for_current_go(self):
        self.config.update(model='deepseek-flash', protocol='chat-completions')
        self.answer = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'synthetic'}}]}
        tools = [{'type': 'function', 'function': {'name': 'checksum_fixture', 'parameters': {'type': 'object'}}}]
        choice = {'type': 'function', 'function': {'name': 'checksum_fixture'}}
        asyncio.run(self.model().ainvoke([Message(role='user', content='synthetic')], tools=tools, tool_choice=choice))
        asyncio.run(self.broker().completion({'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic'}],
            'tools': tools, 'tool_choice': choice}, 'ses_synthetic0001'))
        for request in self.calls:
            self.assertEqual(str(request.url), 'https://opencode.ai/inference/go/v1/chat/completions')
            self.assertEqual(json.loads(request.content)['tool_choice'], choice)
            self.assertEqual(json.loads(request.content)['model'], 'deepseek-flash')
            self.assertIn('x-opencode-session', request.headers)

    def test_responses_pin_target_hostname_and_reject_wrong_protocol_route(self):
        calls = []
        async def run():
            transport = PinnedChatTransport('https://opencode.ai', base_path='/inference/go/v1', protocol='responses')
            await transport.transport.aclose()
            transport.transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json={}))
            transport.probe.addresses = lambda destination: ['93.184.216.34']
            async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                await client.post('https://opencode.ai/inference/go/v1/responses', json={})
                with self.assertRaises(ValueError):
                    await client.post('https://opencode.ai/inference/go/v1/chat/completions', json={})
        asyncio.run(run())
        self.assertEqual(str(calls[0].url), 'https://93.184.216.34/inference/go/v1/responses')
        self.assertEqual(calls[0].headers['host'], 'opencode.ai')
        self.assertEqual(calls[0].extensions['sni_hostname'], 'opencode.ai')

"""Synthetic model transport; no native research engine or network here."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
import socket
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import httpx

from agent_factory.owner_runtime_broker import OwnerRuntimeBroker
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.platform_openresearch import _UnixHTTP


class OwnerRuntimeBrokerTests(unittest.TestCase):
    def test_compaction_retained_suffix_distinguishes_identical_final_text_and_keeps_unknown_receipt(self):
        from agent_factory.owner_runtime_broker import OwnerModelCallError
        session = 'ses_syntheticcompaction123'
        tools = [{'type': 'function', 'function': {'name': 'synthetic_tool',
            'parameters': {'type': 'object', 'properties': {}}}}]
        def final(reasoning, text='Identical synthetic final'):
            self.answer = {'choices': [{'message': {'role': 'assistant', 'content': text,
                'reasoning_content': reasoning}, 'finish_reason': 'stop'}]}
        def call(messages, number, enabled=True):
            return self.broker.native_completion({'model': 'owner-model', 'messages': messages,
                'tools': tools if enabled else []}, session, f'msg_syntheticcompact{number}')
        first_user = {'role': 'user', 'content': 'First old user turn'}
        second_user = {'role': 'user', 'content': 'Retained user turn'}
        final('private-first')
        first = call([first_user], 1)['choices'][0]['message']
        final('private-second')
        second = call([first_user, first, second_user], 2)['choices'][0]['message']
        self.assertEqual(first, second)
        preserved = deepcopy(self.broker.histories)
        with self.assertRaises(OwnerModelCallError):
            call([{'role': 'user', 'content': 'Changed original prefix'}, second], 998, False)
        with self.assertRaises(OwnerModelCallError):
            call([first_user, first, second_user, second,
                {'role': 'assistant', 'content': 'Invented extra final'}, {'role': 'user', 'content': 'Continue'}], 997, False)
        self.assertEqual(self.broker.histories, preserved)
        self.assertEqual(len(self.calls), 2)
        uncertain = [first_user, first, second_user, second, {'role': 'user', 'content': 'Uncertain old turn'}]
        transport = self.handle.service.transport_factory
        def old_unknown(request):
            self.calls.append(request)
            raise httpx.ReadError('synthetic old disconnect')
        self.handle.service.transport_factory = lambda: httpx.MockTransport(old_unknown)
        with self.assertRaises(OwnerModelCallError) as old_error:
            call(uncertain, 999)
        self.assertEqual(self.broker.histories, preserved)
        self.handle.service.transport_factory = transport
        final('private-summary', 'Synthetic summary')
        summary_input = [{'role': 'user', 'content': 'Summarize the old conversation'}]
        summary = call(summary_input, 3, False)['choices'][0]['message']
        original_count = len(self.calls)
        self.assertEqual(call(summary_input, 3, False)['choices'][0]['message'], summary)
        self.assertEqual(len(self.calls), original_count)
        compacted = [{'role': 'user', 'content': 'What did we do so far?'}, summary,
            second_user, second, {'role': 'user', 'content': 'Use a tool after compaction'}]
        # Changing the retained slice or transplanting a reference across owner
        # cannot select reasoning by identical text or resolve a credential.
        state = next(iter(self.broker.histories.values()))
        original = deepcopy(state)
        credential = self.handle.credential
        resolved = []
        def observe_credential():
            resolved.append(True)
            return credential()
        self.handle.credential = observe_credential
        key = state['summary_parent'][-1]['record']
        state['summary_parent'][-1]['record'] = (key[0], 'foreign-owner-scope', key[2])
        with self.assertRaises(OwnerModelCallError) as caught:
            call(compacted, 4)
        self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
        state.clear(); state.update(original)
        altered = deepcopy(compacted); altered[2]['content'] = 'Altered retained user'
        with self.assertRaises(OwnerModelCallError): call(altered, 5)
        self.assertEqual(len(self.calls), original_count)
        self.assertEqual(resolved, [])
        self.handle.credential = credential
        self.answer = {'choices': [{'message': {'role': 'assistant', 'content': None,
            'reasoning_content': 'private-tool', 'tool_calls': [{'id': 'call_aftercompaction', 'type': 'function',
                'function': {'name': 'synthetic_tool', 'arguments': '{ "n": 1.0 }'}}]}, 'finish_reason': 'tool_calls'}]}
        assistant = call(compacted, 6)['choices'][0]['message']
        sent = json.loads(self.calls[-1].content)
        self.assertEqual([m['reasoning_content'] for m in sent['messages'] if m['role'] == 'assistant'],
            ['private-summary', 'private-second'])
        assistant['content'] = ''
        assistant['tool_calls'][0]['function']['arguments'] = '{"n":1}'
        following = compacted + [assistant,
            {'role': 'tool', 'tool_call_id': 'call_aftercompaction', 'content': 'Synthetic tool result'}]
        def unknown(request):
            self.calls.append(request)
            raise httpx.ReadError('synthetic disconnect')
        self.handle.service.transport_factory = lambda: httpx.MockTransport(unknown)
        diagnostics = []
        count = len(self.calls)
        preserved = deepcopy(self.broker.histories)
        for _ in range(2):
            with self.assertRaises(OwnerModelCallError) as caught:
                call(following, 6)
            diagnostics.append(caught.exception.diagnostic_id)
        self.assertEqual(diagnostics[0], diagnostics[1]); self.assertEqual(len(self.calls), count + 1)
        self.assertEqual(self.broker.histories, preserved)
        self.assertEqual([m['reasoning_content'] for m in json.loads(self.calls[-1].content)['messages']
            if m['role'] == 'assistant'], ['private-summary', 'private-second', 'private-tool'])
        self.assertEqual(call(summary_input, 3, False)['choices'][0]['message'], summary)
        self.assertEqual(len(self.calls), count + 1)
        with self.assertRaises(OwnerModelCallError) as replayed:
            call(uncertain, 999)
        self.assertEqual(replayed.exception.diagnostic_id, old_error.exception.diagnostic_id)
        self.assertEqual(len(self.calls), count + 1)

    def test_compaction_allows_empty_tail_and_tail_starting_with_assistant(self):
        for keep in (False, True):
            with self.subTest(keep=keep):
                broker = OwnerRuntimeBroker(Path(self.folder.name) / 'unused.sock', self.handle)
                session = 'ses_synthetictail123'
                def call(messages, request, tools=False):
                    return broker.native_completion({'model': 'owner-model', 'messages': messages,
                        **({'tools': [{'type': 'function', 'function': {'name': 'synthetic_tool'}}]} if tools else {})},
                        session, request)['choices'][0]['message']
                first = call([{'role': 'user', 'content': 'Original turn'}], 'msg_synthetictail0001')
                self.answer = {'choices': [{'message': {'role': 'assistant', 'content': 'Synthetic summary'}, 'finish_reason': 'stop'}]}
                summary = call([{'role': 'user', 'content': 'Summarize'}], 'msg_synthetictail0002')
                self.answer = {'choices': [{'message': {'role': 'assistant', 'content': 'Synthetic continued'}, 'finish_reason': 'stop'}]}
                call([{'role': 'user', 'content': 'Native summary marker'}, summary,
                    *([first] if keep else []), {'role': 'user', 'content': 'Continue'}], 'msg_synthetictail0003', True)
                self.assertEqual(len(broker.native_calls), 3)

    def test_concurrent_summary_cannot_overwrite_a_newer_inflight_transcript(self):
        from agent_factory.owner_runtime_broker import OwnerModelCallError
        admitted, release = threading.Event(), threading.Event()
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'Original task'}]}
        first = self.broker.native_completion(body, 'ses_syntheticbranch123', 'msg_syntheticbranch0001')
        continued = {**body, 'messages': [*body['messages'], first['choices'][0]['message'],
            {'role': 'user', 'content': 'Next task'}]}
        def wire(request):
            self.calls.append(request); admitted.set()
            self.assertTrue(release.wait(timeout=3))
            return httpx.Response(200, json=self.answer)
        self.handle.service.transport_factory = lambda: httpx.MockTransport(wire)
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(self.broker.native_completion, continued, 'ses_syntheticbranch123', 'msg_syntheticbranch0002')
            self.assertTrue(admitted.wait(timeout=3))
            with self.assertRaises(OwnerModelCallError) as caught:
                self.broker.native_completion(body, 'ses_syntheticbranch123', 'msg_syntheticbranch0003')
            self.assertEqual(caught.exception.code, 'OWNER_MODEL_REQUEST_REJECTED')
            release.set(); active.result(timeout=3)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.broker.history_inflight)

    def test_native_go_thinking_option_comes_only_from_the_bound_owner_configuration(self):
        self.handle.body.update(baseURL='https://opencode.ai/zen/go/v1',
            model='longcat-2.5-preview-free', thinkingMode='disabled')
        body = {'model':'owner-model','messages':[{'role':'user','content':'synthetic'}],
            'thinking':{'type':'enabled'}, 'max_tokens':99999}
        asyncio.run(self.broker.completion(body,'ses_syntheticnative123'))
        sent=json.loads(self.calls[-1].content)
        self.assertEqual(sent['thinking'],{'type':'disabled'})
        self.assertEqual(sent['max_tokens'],4096)
        self.assertEqual(self.broker.remaining,64)
        self.handle.body.pop('thinkingMode')
        asyncio.run(self.broker.completion(body,'ses_syntheticnative123'))
        self.assertNotIn('thinking',json.loads(self.calls[-1].content))

    def test_native_accounting_reuses_a_lost_result_but_distinguishes_identical_legal_turns(self):
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'identical synthetic goal'}]}
        first = self.broker.native_completion(body, 'ses_syntheticnative123', 'msg_syntheticturn0001')
        self.assertEqual(self.broker.native_completion(body, 'ses_syntheticnative123', 'msg_syntheticturn0001'), first)
        self.assertEqual(len(self.calls), 1)
        second_body = {**body, 'messages': [*body['messages'], first['choices'][0]['message'], *body['messages']]}
        self.answer = {'choices': [{'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'call_synthetic', 'type': 'function',
                'function': {'name': 'synthetic_tool', 'arguments': '{}'}}]}, 'finish_reason': 'tool_calls'}]}
        second = self.broker.native_completion(second_body, 'ses_syntheticnative123', 'msg_syntheticturn0002')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.broker.remaining, 62)
        # A changed tool-loop input is a separate call within the same user turn.
        next_body = {**body, 'messages': second_body['messages'] + [
            second['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': 'call_synthetic', 'content': 'actual synthetic tool output'}]}
        self.answer = {'choices': [{'message': {'role': 'assistant', 'content': 'Synthetic final'}, 'finish_reason': 'stop'}]}
        self.broker.native_completion(next_body, 'ses_syntheticnative123', 'msg_syntheticturn0002')
        self.assertEqual(len(self.calls), 3)
        self.revoked = True
        with self.assertRaises(ValueError):
            self.broker.native_completion(body, 'ses_syntheticnative123', 'msg_syntheticturn0001')
        self.assertEqual(len(self.calls), 3)

    def test_native_accounting_preserves_unknown_outcome_and_rejects_missing_turn_identity(self):
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic goal'}]}
        def wire(request):
            self.calls.append(request)
            raise httpx.ReadError('synthetic upstream disconnect')
        self.handle.service.transport_factory = lambda: httpx.MockTransport(wire)
        diagnostics = []
        for _ in range(2):
            with self.assertRaises(ValueError) as caught:
                self.broker.native_completion(body, 'ses_syntheticnative123', 'msg_syntheticturn0001')
            diagnostics.append(caught.exception.diagnostic_id)
        self.assertEqual(diagnostics[0], diagnostics[1]); self.assertEqual(len(self.calls), 1)
        self.assertTrue(all(type(record.error) is tuple for record in self.broker.native_calls.values()))
        with self.assertRaises(ValueError): self.broker.native_completion(body, 'ses_syntheticnative123', None)
        self.assertEqual(len(self.calls), 1); self.assertEqual(self.broker.remaining, 63)

    def test_concurrent_native_retries_share_the_original_inflight_call(self):
        admitted, release = threading.Event(), threading.Event()
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic goal'}]}
        def wire(request):
            self.calls.append(request); admitted.set()
            self.assertTrue(release.wait(timeout=3))
            return httpx.Response(200, json=self.answer)
        self.handle.service.transport_factory = lambda: httpx.MockTransport(wire)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.broker.native_completion, body, 'ses_syntheticnative123', 'msg_syntheticturn0001')
            self.assertTrue(admitted.wait(timeout=3))
            second = pool.submit(self.broker.native_completion, body, 'ses_syntheticnative123', 'msg_syntheticturn0001')
            release.set()
            self.assertEqual(first.result(timeout=3), second.result(timeout=3))
        self.assertEqual(len(self.calls), 1); self.assertEqual(self.broker.remaining, 63)

    def test_go_preserves_native_conversation_header_and_requires_it_before_dispatch(self):
        self.handle.body['baseURL'] = 'https://opencode.ai/zen/go/v1'
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'synthetic coding task'}]}
        for session in (None, 'invalid header', self.broker.capability, 'synthetic-private-key'):
            with self.assertRaises(ValueError): asyncio.run(self.broker.completion(body, session))
        self.assertEqual(self.calls, [])
        for _ in range(2):
            answer = asyncio.run(self.broker.completion(body, 'ses_syntheticnative123'))
            body['messages'].extend([answer['choices'][0]['message'], {'role': 'user', 'content': 'synthetic coding task'}])
        self.assertEqual(len(self.calls), 2)
        for request in self.calls:
            self.assertEqual(str(request.url), 'https://opencode.ai/zen/go/v1/chat/completions')
            self.assertEqual(request.headers['x-opencode-session'], 'ses_syntheticnative123')
            self.assertTrue(request.headers['user-agent'].startswith('agent-factory/'))
            self.assertEqual(json.loads(request.content)['model'], 'owner-selected-model')

    @unittest.skipUnless(sys.platform == 'linux', 'Native broker requires AF_UNIX')
    def test_go_header_survives_the_actual_private_http_boundary(self):
        self.handle.body['baseURL'] = 'https://opencode.ai/zen/go/v1'
        self.broker.start(); self.addCleanup(self.broker.close)
        client = _UnixHTTP(self.broker.path)
        try:
            client.request('POST', '/v1/chat/completions', body=json.dumps({'model': 'owner-model',
                'messages': [{'role': 'user', 'content': 'synthetic fixture'}]}), headers={
                'Authorization': 'Bearer ' + self.broker.capability,
                'x-opencode-session-id': 'ses_syntheticnative123', 'x-opencode-request': 'msg_syntheticturn123', 'Content-Type': 'application/json'})
            response = client.getresponse()
            self.assertEqual(response.status, 200); response.read()
        finally: client.close()
        self.assertEqual(self.calls[0].headers['x-opencode-session'], 'ses_syntheticnative123')

    @unittest.skipUnless(sys.platform == 'linux', 'Native broker requires AF_UNIX')
    def test_go_conflicting_native_conversation_headers_reject_before_dispatch(self):
        self.handle.body['baseURL'] = 'https://opencode.ai/zen/go/v1'
        self.broker.start(); self.addCleanup(self.broker.close)
        client = _UnixHTTP(self.broker.path)
        try:
            client.request('POST', '/v1/chat/completions', body=json.dumps({'model': 'owner-model',
                'messages': [{'role': 'user', 'content': 'synthetic fixture'}]}), headers={
                'Authorization': 'Bearer ' + self.broker.capability,
                'x-opencode-session-id': 'ses_syntheticnative123', 'x-opencode-request': 'msg_syntheticturn123',
                'x-opencode-session': 'ses_differentfixture123', 'Content-Type': 'application/json'})
            response = client.getresponse(); self.assertEqual(response.status, 400); response.read()
        finally: client.close()
        self.assertEqual(self.calls, [])

    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.revoked, self.calls = False, []
        self.answer = {'choices': [{'message': {'role': 'assistant', 'content': 'Synthetic native response'}, 'finish_reason': 'stop'}]}
        def wire(request):
            self.calls.append(request)
            return httpx.Response(200, json=self.answer)
        def check():
            if self.revoked: raise ValueError('synthetic-private-key')
        self.handle = SimpleNamespace(body={'baseURL': 'https://models.example.com/v1', 'model': 'owner-selected-model'},
            service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(wire)), check=check,
            credential=lambda: SecretLease('api-key', 'synthetic-private-key'))
        self.broker = OwnerRuntimeBroker(Path(self.folder.name) / 'broker.sock', self.handle)

    def test_original_harness_wire_is_pinned_to_owner_model_without_key_in_local_body(self):
        body = {'model': 'owner-model', 'stream': True,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Synthetic native input'}]}]}
        value = asyncio.run(self.broker.completion(body))
        self.assertEqual(value['choices'][0]['message']['content'], 'Synthetic native response')
        outgoing = json.loads(self.calls[0].content)
        self.assertEqual(outgoing['model'], 'owner-selected-model')
        self.assertFalse(outgoing['stream'])
        self.assertEqual(outgoing['messages'][0]['content'], 'Synthetic native input')
        self.assertEqual(self.calls[0].headers['Authorization'], 'Bearer synthetic-private-key')
        self.assertNotIn('synthetic-private-key', json.dumps(body))
        self.assertNotIn('synthetic-private-key', repr(self.broker))

    def test_rotation_revocation_echo_and_multimodal_fail_closed(self):
        body = {'model': 'owner-model', 'messages': [{'role': 'user', 'content': 'Synthetic input'}]}
        self.revoked = True
        with self.assertRaises(ValueError): asyncio.run(self.broker.completion(body))
        self.assertEqual(self.calls, [])
        self.revoked = False; self.answer['secret'] = 'synthetic-private-key'
        with self.assertRaises(ValueError): asyncio.run(self.broker.completion(body))
        calls = len(self.calls)
        body['messages'][0]['content'] = [{'type': 'image_url', 'image_url': 'https://example.com/private.png'}]
        with self.assertRaises(ValueError): asyncio.run(self.broker.completion(body))
        self.assertEqual(len(self.calls), calls)
        self.assertFalse(self.broker.authorized('foreign-capability'))
        self.broker.deadline = 0
        self.assertFalse(self.broker.authorized(self.broker.capability))

    @unittest.skipUnless(sys.platform == 'linux', 'Pinned platform package uses Linux private sockets')
    def test_long_private_workspace_socket_stream_and_sanitized_revocation(self):
        directory = Path(self.folder.name) / ('workspace-' + 'a' * 80) / ('owner-' + 'b' * 40)
        directory.mkdir(mode=0o700, parents=True)
        broker = OwnerRuntimeBroker(directory / 'broker.sock', self.handle)
        broker.start(); self.addCleanup(broker.close)
        self.assertGreater(len(str(broker.path)), 108)
        def call(token, text='Synthetic local wire'):
            client = _UnixHTTP(broker.path)
            try:
                client.request('POST', '/v1/chat/completions', body=json.dumps({'model': 'owner-model', 'stream': True,
                    'messages': [{'role': 'user', 'content': text}]}),
                    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                        'x-opencode-session-id': 'ses_fixtureconversation123', 'x-opencode-request': 'msg_fixtureturn123'})
                response = client.getresponse()
                return response.status, response.read().decode()
            finally: client.close()
        self.assertEqual(call('foreign-capability')[0], 401)
        self.assertEqual(call('foreign-capability', 'Synthetic unauthorized body ' * 4096)[0], 401)
        self.assertEqual(self.calls, [])
        status, value = call(broker.capability)
        self.assertEqual(status, 200)
        self.assertIn('Synthetic native response', value); self.assertIn('[DONE]', value)
        self.assertNotIn('synthetic-private-key', value)
        self.revoked = True
        status, value = call(broker.capability)
        self.assertEqual(status, 400); self.assertNotIn('synthetic-private-key', value)
        self.assertIn('OWNER_MODEL_REQUEST_REJECTED', value)

    @unittest.skipUnless(sys.platform == 'linux', 'Native broker requires AF_UNIX')
    def test_dispatched_disconnect_and_provider_502_are_terminal_not_native_retry_errors(self):
        from agent_factory.owner_runtime_broker import OwnerModelCallError
        for outcome in ('disconnect', 'provider_502'):
            with self.subTest(outcome=outcome):
                def wire(request):
                    self.calls.append(request)
                    if outcome == 'disconnect': raise httpx.ReadError('private-provider-secret socket hang up')
                    return httpx.Response(502, json={'error': 'private-provider-secret'})
                self.handle.service.transport_factory = lambda: httpx.MockTransport(wire)
                with self.assertRaises(OwnerModelCallError) as caught:
                    asyncio.run(self.broker.completion({'model': 'owner-model',
                        'messages': [{'role': 'user', 'content': 'synthetic input'}]}))
                error = caught.exception
                self.assertEqual(error.code, 'OWNER_MODEL_CALL_UNCONFIRMED')
                self.assertRegex(error.diagnostic_id, r'^diag_[a-p]{32}$')
                self.assertNotIn('private-provider-secret', json.dumps(error.response()))
        self.assertEqual(len(self.calls), 2)

    @unittest.skipUnless(sys.platform == 'linux', 'Native broker requires AF_UNIX')
    def test_unknown_dispatch_http_response_has_safe_diagnostic_and_no_retry_status(self):
        def wire(request):
            self.calls.append(request)
            raise httpx.ReadTimeout('private secret response timeout')
        self.handle.service.transport_factory = lambda: httpx.MockTransport(wire)
        self.broker.start(); self.addCleanup(self.broker.close)
        client = _UnixHTTP(self.broker.path)
        try:
            client.request('POST', '/v1/chat/completions', body=json.dumps({'model': 'owner-model',
                'messages': [{'role': 'user', 'content': 'synthetic fixture'}]}), headers={
                'Authorization': 'Bearer ' + self.broker.capability, 'Content-Type': 'application/json',
                'x-opencode-session-id': 'ses_fixtureconversation123', 'x-opencode-request': 'msg_fixtureturn123'})
            response = client.getresponse(); value = json.loads(response.read())
            self.assertEqual(response.status, 422)
            self.assertEqual(value['error']['code'], 'OWNER_MODEL_CALL_UNCONFIRMED')
            self.assertIn(value['diagnosticId'], value['error']['message'])
            self.assertNotIn('private secret', json.dumps(value))
        finally: client.close()
        self.assertEqual(len(self.calls), 1)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux directory-relative socket custody')
    def test_close_parent_replacement_cannot_delete_another_owner_socket(self):
        root = Path(self.folder.name)
        for owner in ('alice', 'bob'): (root / owner / 'sockets').mkdir(parents=True, mode=0o700)
        alice = OwnerRuntimeBroker(root / 'alice/sockets/broker.sock', self.handle)
        bob = OwnerRuntimeBroker(root / 'bob/sockets/broker.sock', self.handle)
        alice.start(); bob.start(); self.addCleanup(bob.close); self.addCleanup(alice.close)
        identity = bob.path.stat().st_ino
        original = root / 'alice/original-sockets'
        alice.path.parent.rename(original)
        alice.path.parent.symlink_to(bob.path.parent, target_is_directory=True)
        alice.close(); alice.close()
        self.assertEqual(bob.path.stat().st_ino, identity)
        self.assertFalse((original / 'broker.sock').exists())
        client = _UnixHTTP(bob.path)
        try:
            client.request('POST', '/v1/chat/completions', body=json.dumps({'model': 'owner-model',
                'messages': [{'role': 'user', 'content': 'Synthetic surviving owner'}]}),
                headers={'Authorization': 'Bearer ' + bob.capability,
                    'x-opencode-session-id': 'ses_syntheticnative123', 'x-opencode-request': 'msg_syntheticturn123'})
            self.assertEqual(client.getresponse().status, 200)
        finally: client.close()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux directory-relative socket custody')
    def test_close_does_not_unlink_replaced_socket_inode(self):
        broker = self.broker; broker.start(); self.addCleanup(broker.close)
        original = broker.path.with_name('original.sock'); broker.path.rename(original)
        replacement = socket.socket(getattr(socket, 'AF_UNIX'), socket.SOCK_STREAM)
        self.addCleanup(replacement.close); replacement.bind(str(broker.path))
        identity = os.lstat(broker.path).st_ino
        broker.close()
        self.assertEqual(os.lstat(broker.path).st_ino, identity)

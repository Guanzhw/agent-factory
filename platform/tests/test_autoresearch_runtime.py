"""Offline controller/HTTP contract tests; no container, provider or research run."""
import asyncio
from copy import deepcopy
import json
import time
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from agent_factory.autoresearch_runtime import AutoResearchRuntime, PROTOCOL
from agent_factory.autoresearch_profile import TOOL_NAMES
from agent_factory.usage_ledger import UsageEvidence


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.body = {'goal': 'Synthetic research goal', 'session': None, 'deadline': time.time() + 5}
        self.intents = {}
        self.ledger = SimpleNamespace(begin_attempt=Mock(return_value='original-attempt'), finish_attempt=Mock())
        self.ctx = SimpleNamespace(run_context=SimpleNamespace(user_id='alice', session_id='task_original', run_id='run_original'),
            plan={'id': 'plan_original'}, store=SimpleNamespace(usage_ledger=self.ledger))
        self.service = SimpleNamespace(current=Mock(return_value=SimpleNamespace(instructions='Only read research_context, then stop; no experiments authorized.', limits={'totalSeconds': 5, 'modelRequests': 3, 'modelOutputTokens': 512})),
            record=Mock(), change=self.change, row=lambda *args: {'body': self.body},
            commit_intent=self.commit, tool=AsyncMock(return_value={'original': True}))
        self.launcher = SimpleNamespace(config=SimpleNamespace(cpus=1, memory_mb=1024, pids=64, max_output_tokens=512), start=Mock(return_value={'containerId': 'a' * 64, 'orxSocket': '/unused.sock', 'projectId': 'project_original'}),
            stop=Mock(return_value={'containerId': 'a' * 64, 'stopped': True, 'status': 'STOPPED', 'proofKind': 'docker-state-exited'}))
        self.launcher.reclaim = Mock(return_value={'reclaimed': True, 'containerId': 'a' * 64})
        self.model_patch = patch('agent_factory.autoresearch_runtime.ORXResearchModel', return_value=Mock())
        self.model_patch.start(); self.addCleanup(self.model_patch.stop)
        self.credential = Mock(return_value='synthetic-not-a-secret')

    def change(self, owner, task, function):
        self.assertEqual((owner, task), ('alice', 'task_original'))
        return function(self.body)

    def commit(self, ctx, *, intent):
        self.service.current(ctx)
        if intent['key'] in self.intents:
            raise ValueError('ORIGINAL_UNKNOWN')
        self.intents[intent['key']] = dict(intent)

    def runtime(self, **kw):
        value = AutoResearchRuntime(self.ctx, self.service, launcher=self.launcher,
            project_id='project_original', credential=self.credential, billing_authorized=lambda: True, **kw)
        value._start_host = AsyncMock()
        return value

    async def rpc(self, runtime, value, *, capability=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime), base_url='http://127.0.0.1') as client:
            return await client.post('/mcp', json=value,
                headers={'Authorization': 'Bearer ' + (capability or runtime.capability)})

    async def test_scientific_mcp_advertises_compact_parameters_without_full_source(self):
        self.service.current.return_value.candidate_builder = lambda changes: 'not invoked by listing'
        runtime = self.runtime()
        response = await self.rpc(runtime, {'jsonrpc': '2.0', 'id': 'list', 'method': 'tools/list'})
        schema = next(tool['inputSchema'] for tool in response.json()['result']['tools']
                      if tool['name'] == 'research_candidate')
        self.assertEqual(set(schema['required']), {'hypothesis', 'changes'})
        self.assertNotIn('trainPy', schema['properties'])
        changes = schema['properties']['changes']
        self.assertEqual(len(changes['properties']), 11)
        self.assertFalse(changes['additionalProperties'])
        self.assertEqual(changes['properties']['DEVICE_BATCH_SIZE']['type'], 'integer')
        self.assertEqual(changes['properties']['ADAM_BETAS']['maxItems'], 2)
        self.service.tool.assert_not_awaited()

    async def test_mcp_real_tool_dispatch_identity_no_permissions_or_builtins_added(self):
        runtime = self.runtime()
        initialized = await self.rpc(runtime, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': PROTOCOL}})
        self.assertEqual(initialized.json()['result']['protocolVersion'], PROTOCOL)
        listing = await self.rpc(runtime, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        self.assertEqual([v['name'] for v in listing.json()['result']['tools']], list(TOOL_NAMES))
        call = {'jsonrpc': '2.0', 'id': 'original-call', 'method': 'tools/call',
                'params': {'name': 'research_context', 'arguments': {}}}
        for _ in range(2):
            self.assertEqual((await self.rpc(runtime, call)).status_code, 200)
        calls = self.service.tool.call_args_list
        self.assertEqual(calls[0].args[2]['_factoryCallId'], calls[1].args[2]['_factoryCallId'])
        self.assertEqual(calls[0].args[1], 'research_context')
        self.credential.assert_not_called()
        self.ledger.begin_attempt.assert_not_called()

    async def test_observed_opencode_initialize_negotiates_implemented_version_then_tools(self):
        runtime = self.runtime()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime), base_url='http://127.0.0.1',
                headers={'Authorization': 'Bearer ' + runtime.capability}) as client:
            response = await client.post('/mcp', json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                           'clientInfo': {'name': 'opencode', 'version': 'synthetic'}}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['result']['protocolVersion'], PROTOCOL)
            client.headers['mcp-protocol-version'] = PROTOCOL
            notified = await client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            self.assertEqual(notified.status_code, 202)
            listing = await client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
            self.assertEqual(listing.status_code, 200)
            self.assertEqual([row['name'] for row in listing.json()['result']['tools']], list(TOOL_NAMES))
            client.headers['mcp-protocol-version'] = '2025-11-25'
            self.assertEqual((await client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2,
                'method': 'tools/list'})).status_code, 403)
            del client.headers['mcp-protocol-version']
            for invalid in ('2099-01-01', None, True, ['2025-11-25']):
                response = await client.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'initialize',
                    'params': {'protocolVersion': invalid}})
                self.assertEqual(response.status_code, 403)
        self.service.tool.assert_not_called()
        self.credential.assert_not_called()

    async def test_mcp_denies_wrong_capability_builtin_and_forged_call_id(self):
        runtime = self.runtime()
        for name, args, cap in [('bash', {}, None), ('research_context', {'_factoryCallId': 'forged'}, None),
                                ('research_context', {}, 'wrong')]:
            response = await self.rpc(runtime, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': name, 'arguments': args}}, capability=cap)
            self.assertEqual(response.status_code, 403)
        self.service.tool.assert_not_called()
        self.credential.assert_not_called()

    async def test_revocation_before_tool_and_after_result_hides_result(self):
        runtime = self.runtime()
        self.service.current.side_effect = ValueError('private authority detail')
        response = await self.rpc(runtime, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'research_context', 'arguments': {}}})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('private', response.text)
        self.service.tool.assert_not_called()
        self.service.current.side_effect = [True, True, ValueError('private')]
        response = await self.rpc(runtime, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
            'params': {'name': 'research_context', 'arguments': {}}})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('original', response.text)

    async def test_native_ledger_attempt_and_unknown_are_original_and_no_credential_pre_admission(self):
        runtime = self.runtime()
        body = {'model': 'deepseek-flash', 'stream': True, 'messages': [], 'max_tokens': 8}
        ticket = await runtime._reserve(1, 512, 8, body)
        self.assertEqual(ticket, 'original-attempt')
        self.ledger.begin_attempt.assert_called_once_with(self.ctx.run_context, self.ctx.plan,
            runtime._model, streaming=True, arguments=(body,))
        self.credential.assert_not_called()
        await runtime._hold(ticket, 'UNKNOWN')
        self.ledger.finish_attempt.assert_called_once_with('original-attempt', None)
        usage = UsageEvidence(2, 3, 'synthetic')
        await runtime._settle(ticket, usage)
        self.ledger.finish_attempt.assert_called_with(ticket, usage)

    async def test_fixture_settlement_never_claims_model_execution_and_billing_denial_prevents_secret(self):
        runtime = self.runtime(broker_transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        await runtime._settle('synthetic-attempt', UsageEvidence(1, 1, 'fixture'))
        self.assertIsNone(self.service.record.call_args.kwargs['accepted'])
        runtime._billing_authorized = lambda: False
        with self.assertRaises(ValueError):
            await runtime._broker_authority()
        self.credential.assert_not_called()
        self.ledger.begin_attempt.assert_not_called()

    async def test_operator_caps_cannot_exceed_persisted_preset_and_expired_deadline_never_launches(self):
        for kwargs in ({'max_requests': 4}, {'max_output_tokens': 513}):
            with self.assertRaises(ValueError):
                self.runtime(**kwargs)
        runtime = self.runtime()
        self.body['deadline'] = time.time() - 1
        with self.assertRaises(ValueError):
            await runtime.run()
        self.launcher.start.assert_not_called()
        cast(AsyncMock, runtime._start_host).assert_not_called()

    async def test_launcher_resources_and_actual_output_cap_must_fit_reviewed_profile(self):
        for attribute, value in (('cpus', 2), ('cpus', True), ('memory_mb', 1025),
                                 ('pids', 65), ('pids', False), ('max_output_tokens', 4096),
                                 ('max_output_tokens', True)):
            previous = getattr(self.launcher.config, attribute)
            setattr(self.launcher.config, attribute, value)
            with self.subTest(attribute=attribute, value=value), self.assertRaises(ValueError):
                self.runtime()
            setattr(self.launcher.config, attribute, previous)
        for seconds in (3601, True, 0):
            self.service.current.return_value.limits['totalSeconds'] = seconds
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                self.runtime()
        self.launcher.start.assert_not_called()
        self.credential.assert_not_called()

    async def test_real_wire_create_title_message_poll_and_exact_stop_proof(self):
        calls = []
        row = {'id': 'chat_original', 'projectId': 'project_original', 'harness': 'opencode',
               'model': 'factory/deepseek-flash', 'busy': False, 'archived': False}
        def wire(request):
            calls.append((request.method, request.url.path))
            if request.method == 'PATCH':
                self.assertIn('orx-title', self.intents)
                return httpx.Response(200, json={'session': row | {'title': 'Factory bounded research'}})
            if request.method == 'POST':
                if request.url.path.endswith('/message'):
                    self.assertIn('orx-message', self.intents)
                    self.assertIn('Goal: Synthetic research goal', json.loads(request.content)['text'])
                    self.assertIn(self.service.current.return_value.instructions, json.loads(request.content)['text'])
                    self.assertIn('not mandatory actions', json.loads(request.content)['text'])
                    return httpx.Response(200, json={'ok': True, 'turn': {'turnId': 'turn_original', 'existing': False, 'queued': False}})
                self.assertIn('orx-create', self.intents)
                return httpx.Response(200, json={'session': row})
            if request.url.path.endswith('/messages'):
                return httpx.Response(200, json={'messages': [{'id': 'message_final', 'role': 'assistant', 'createdAt': 1,
                    'completedAt': 2, 'parts': [{'type': 'text', 'text': 'Synthetic terminal agent text'}]}],
                    'activeLeafId': 'message_final', 'queued': []})
            return httpx.Response(200, json={'sessions': [row]})
        runtime = self.runtime(session_transport=httpx.MockTransport(wire))
        result = await runtime.run()
        self.assertEqual(result['turnId'], 'turn_original')
        self.assertEqual(result['finalText'], 'Synthetic terminal agent text')
        self.assertFalse(result['scientificConclusionVerified'])
        self.assertEqual(self.body['session']['id'], 'chat_original')
        self.assertEqual(self.body['turn']['turnId'], 'turn_original')
        self.assertEqual([method for method, _ in calls if method != 'GET'], ['POST', 'PATCH', 'POST'])
        self.assertTrue(await runtime.stop())
        self.credential.assert_not_called()

    async def test_lost_create_not_retried_and_stop_mismatched_container_stays_unknown(self):
        posts = []
        def wire(request):
            if request.method == 'POST':
                posts.append(request)
                raise httpx.ReadError('private wire')
            return httpx.Response(200, json={'sessions': []})
        runtime = self.runtime(session_transport=httpx.MockTransport(wire))
        with self.assertRaises(ValueError):
            await runtime.run()
        self.assertEqual(len(posts), 1)
        self.assertIsNone(self.body['session'])
        self.launcher.stop.return_value['containerId'] = 'b' * 64
        self.assertFalse(await runtime.stop())

    async def test_cancel_kills_container_without_requiring_revoked_authority(self):
        runtime = self.runtime()
        runtime._container_id = 'a' * 64
        self.service.current.side_effect = ValueError('revoked')
        self.assertTrue(await runtime.cancel())
        self.launcher.stop.assert_called_once()
        self.assertEqual(self.service.current.call_count, 1)
        self.credential.assert_not_called()
        self.assertTrue(await runtime.stop())
        self.launcher.stop.assert_called_once()

    async def test_original_poll_protocol_failure_survives_secondary_authority_denial(self):
        from agent_factory.orx_research_session import OrxSessionError, _diagnostic
        runtime = self.runtime()
        original = OrxSessionError()
        original.session_diagnostic = _diagnostic('messages', 'request', httpx.ReadTimeout('private'))
        async def failed_poll():
            runtime.session = {'id': 'original-session'}
            runtime.turn = {'turnId': 'original-turn'}
            runtime._run_phase = 'poll-messages'
            raise original
        runtime._run = failed_poll
        with self.assertRaises(OrxSessionError) as caught:
            await runtime.run()
        self.assertIs(caught.exception, original)
        saved = deepcopy(self.body['runtimeFailure'])
        self.assertEqual(saved['phase'], 'poll-messages')
        self.assertEqual(saved['code'], 'ORX_PROTOCOL')
        self.assertEqual(saved['sessionDiagnostic']['errorType'], 'ReadTimeout')
        self.assertEqual(saved['sessionDiagnostic']['route'], 'messages')
        self.assertTrue(saved['sessionKnown'] and saved['turnKnown'])
        runtime._cancelled = True
        with self.assertRaises(ValueError):
            await runtime._broker_authority()
        self.assertEqual(self.body['runtimeFailure'], saved)
        self.assertNotIn('original-session', json.dumps(saved))

    async def test_runtime_diagnostic_never_echoes_exception_text_and_preserves_original(self):
        runtime = self.runtime()
        original = ValueError('synthetic-sensitive-body')
        async def fail():
            raise original
        runtime._run = fail
        self.service.change = Mock(side_effect=RuntimeError('persistence unavailable'))
        with self.assertRaises(ValueError) as caught:
            await runtime.run()
        self.assertIs(caught.exception, original)
        self.assertNotIn('synthetic-sensitive-body', json.dumps(runtime.runtime_failure))
        self.assertEqual(cast(dict, runtime.runtime_failure)['phase'], 'admission')

    async def test_get_timeout_recovers_original_session_without_mutation_or_broker_retry(self):
        from agent_factory.orx_research_session import OrxSessionError, _diagnostic
        runtime = self.runtime(poll_seconds=0.01)
        timeout = OrxSessionError()
        timeout.session_diagnostic = _diagnostic('sessions', 'request', TimeoutError())
        client = SimpleNamespace(read_messages=AsyncMock(side_effect=[timeout, {'original': True}]),
            read_session=AsyncMock(return_value={'busy': False}))
        runtime._http = cast(Any, client)
        transcript, current = await runtime._poll_original('chat_original')
        self.assertTrue(transcript['original'])
        self.assertFalse(current['busy'])
        self.assertEqual(client.read_messages.call_args_list[0].args, ('chat_original',))
        self.assertEqual(client.read_messages.call_args_list[1].args, ('chat_original',))
        self.assertFalse(self.intents)
        self.credential.assert_not_called()
        self.ledger.begin_attempt.assert_not_called()
        for phase, error in (('shape', timeout), ('headers', timeout)):
            error.session_diagnostic = _diagnostic('sessions', phase, TimeoutError())
            client.read_messages = AsyncMock(side_effect=error)
            with self.assertRaises(OrxSessionError):
                await runtime._poll_original('chat_original')
            client.read_messages.assert_awaited_once()

    async def test_get_timeout_retries_never_extend_run_deadline_or_resend_message(self):
        from agent_factory.orx_research_session import OrxSessionError, _diagnostic
        runtime = self.runtime(poll_seconds=0.01)
        timeout = OrxSessionError()
        timeout.session_diagnostic = _diagnostic('sessions', 'request', TimeoutError())
        client = SimpleNamespace(_request=AsyncMock(return_value={'sessions': []}),
            create_session=AsyncMock(return_value={'id': 'chat_original'}), rename_session=AsyncMock(),
            send_message=AsyncMock(return_value={'turnId': 'turn_original'}),
            read_messages=AsyncMock(side_effect=timeout), read_session=AsyncMock())
        clock = [100.0]
        self.body['deadline'] = 102.0
        real_timeout, real_sleep = asyncio.timeout, asyncio.sleep
        contexts, requested_delays = [], []

        def controlled_timeout(delay):
            requested_delays.append(delay)
            # Exercise the real timeout cancellation/conversion without a race
            # against OS scheduling. Only the original context is expired below.
            context = real_timeout(None)
            contexts.append(context)
            return context

        async def advance_retry_clock(delay):
            self.assertEqual(delay, 0.01)
            clock[0] += 1
            if clock[0] == self.body['deadline']:
                contexts[0].reschedule(asyncio.get_running_loop().time())
            await real_sleep(0)

        with patch('agent_factory.autoresearch_runtime.OpenResearchSessionHTTP', return_value=client), \
             patch('agent_factory.autoresearch_runtime.time.time', side_effect=lambda: clock[0]), \
             patch('agent_factory.autoresearch_runtime.asyncio.timeout', side_effect=controlled_timeout), \
             patch('agent_factory.autoresearch_runtime.asyncio.sleep', side_effect=advance_retry_clock):
            with self.assertRaises(TimeoutError):
                await runtime.run()
        self.assertEqual(requested_delays, [2.0, 30])  # original deadline, then read-only readiness
        self.assertTrue(contexts[0].expired())
        self.assertFalse(contexts[1].expired())
        self.assertEqual(self.body['deadline'], 102.0)
        client.create_session.assert_awaited_once()
        client.rename_session.assert_awaited_once()
        client.send_message.assert_awaited_once()
        self.assertEqual(client.read_messages.await_count, 2)
        self.credential.assert_not_called()
        self.assertTrue(await runtime.stop())

    async def test_stop_proof_persisted_before_reclaim_and_failed_reclaim_only_retried(self):
        runtime = self.runtime()
        runtime._container_id = 'a' * 64
        def reclaim():
            self.assertEqual(self.body['runtimeStop']['containerId'], 'a' * 64)
            self.assertEqual(self.body['runtimeStop']['proofKind'], 'docker-state-exited')
            return {'reclaimed': False, 'containerId': 'a' * 64}
        self.launcher.reclaim.side_effect = reclaim
        self.assertFalse(await runtime.stop())
        self.assertFalse(self.body['runtimeReclaim']['reclaimed'])
        self.launcher.reclaim.side_effect = None
        self.assertTrue(await runtime.stop())
        self.assertTrue(self.body['runtimeReclaim']['reclaimed'])
        self.launcher.stop.assert_called_once()
        self.assertEqual(self.launcher.reclaim.call_count, 2)

    async def test_failed_stop_persistence_never_removes_container_and_missing_reclaim_not_skipped(self):
        runtime = self.runtime()
        runtime._container_id = 'a' * 64
        self.service.change = Mock(side_effect=ValueError('persistence unavailable'))
        with self.assertRaises(ValueError):
            await runtime.stop()
        self.launcher.reclaim.assert_not_called()
        self.service.change = self.change
        del self.launcher.reclaim
        with self.assertRaises(AttributeError):
            await runtime.stop()
        self.assertFalse(runtime._stop_proof)
        self.assertIn('runtimeStop', self.body)
        self.launcher.stop.assert_called_once()

    async def test_double_cancel_and_concurrent_stop_wait_for_one_original_launch(self):
        runtime = self.runtime()
        started, release = asyncio.Event(), asyncio.Event()
        async def fake_thread(fn, *args):
            if fn == self.launcher.start:
                started.set()
                await release.wait()
                return deepcopy(self.launcher.start.return_value)
            return fn(*args)
        with patch('agent_factory.autoresearch_runtime.asyncio.to_thread', side_effect=fake_thread):
            task = asyncio.create_task(runtime.run())
            await asyncio.wait_for(started.wait(), 2)
            task.cancel(); await asyncio.sleep(0)
            task.cancel(); await asyncio.sleep(0)
            stop = asyncio.create_task(runtime.stop())
            await asyncio.sleep(0)
            self.launcher.stop.assert_not_called()
            self.assertFalse(cast(asyncio.Task, runtime._launch_task).done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(await stop)
            self.assertFalse(cast(asyncio.Task, runtime._launch_task).cancelled())
            self.assertEqual(runtime._container_id, 'a' * 64)
            self.launcher.stop.assert_called_once()

    async def test_launch_timeout_retains_original_handle_until_later_cleanup(self):
        runtime = self.runtime()
        release = asyncio.Event()
        async def original_launch():
            await release.wait()
            return deepcopy(self.launcher.start.return_value)
        runtime._launch_task = asyncio.create_task(original_launch())
        original = runtime._launch_task
        runtime._launch_deadline = asyncio.get_running_loop().time() - 1
        self.assertFalse(await runtime.stop())
        self.assertIs(runtime._launch_task, original)
        self.assertFalse(original.cancelled())
        self.launcher.stop.assert_not_called()
        release.set(); await original
        self.assertTrue(await runtime.stop())
        self.launcher.start.assert_not_called()
        self.launcher.stop.assert_called_once()

    async def test_cancellation_during_launch_retains_original_receipt_for_cleanup(self):
        runtime = self.runtime()
        started = asyncio.Event()
        async def fake_thread(fn, *args):
            if fn == self.launcher.start:
                started.set()
                await asyncio.sleep(0.02)
                return deepcopy(self.launcher.start.return_value)
            return fn(*args)
        with patch('agent_factory.autoresearch_runtime.asyncio.to_thread', side_effect=fake_thread):
            task = asyncio.create_task(runtime.run())
            await asyncio.wait_for(started.wait(), 2); task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(runtime._container_id, 'a' * 64)
            self.assertTrue(await runtime.stop())

"""Real isolated PG, native summary parsing, scripted responses and run receipts.

Synthetic terminal records exercise the contract; this is not crash or live-model QA.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agno.exceptions import RunCancelledException, StopAgentRun
from agno.models.message import Message
from agno.models.response import ModelResponse
from fastapi import HTTPException

from agent_factory.application_content import ContentPublication
from research import session_context
from research.session_routes import MAX_USER_INPUT_TEXT_CHARS, CreateSession, SessionCommand, SessionText
import test_research_sessions as fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchContextContracts(unittest.TestCase):
    setUp = fixture.ResearchSessionContracts.setUp
    reserved = fixture.ResearchSessionContracts.reserved
    read = fixture.ResearchSessionContracts.read
    observed_detail = fixture.ResearchSessionContracts.observed_detail

    def rows(self):
        with self.service.db.read() as conn:
            return self.service._row(conn, 'alice', self.identifier), self.service._turns(conn, self.identifier)

    def finish(self, task, result=None, status='completed'):
        self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
        with self.service.db.write() as conn:
            turn = self.service._turns(conn, self.identifier)[-1]
            self.service._save_turn(conn, turn, {**turn['body'], 'terminal': True, 'status': status,
                'taskId': task['id'], 'runId': task['run_id'], 'result': result, 'completedAt': 'synthetic-final'})

    def known_window(self):
        original = self.service.setup.models.list
        catalog = patch.object(self.service.setup.models, 'list', side_effect=lambda owner: [
            {**item, 'contextWindow': 1000} for item in original(owner)])
        catalog.start()
        self.addCleanup(catalog.stop)

    def long_turn(self, result=None):
        self.known_window()
        _, prior = self.reserved()
        self.finish(prior, result or 'Confirmed synthetic observation. ' * 500)
        # Known model window triggers the native summary path, not a character cap.
        with self.service.db.write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            body = deepcopy(row['body'])
            body['configuration']['model']['contextWindow'] = 1000
            self.service._save_session(conn, row, body)
        _, task = self.reserved('continue-original', 'Keep the original contract and continue')
        return prior, task

    def model(self, content=None, action=None):
        response = Mock(side_effect=action, return_value=ModelResponse(role='assistant', content=content or json.dumps(
            {'summary': 'Synthetic condensed observations; the experiment is still uncertain.', 'topics': ['test']})))
        factory = Mock(return_value=SimpleNamespace(response=response))
        return factory, response

    def before(self, factory, messages=None, ticket=None):
        messages = messages if messages is not None else [Message(role='user', content='Original bounded admission')]
        with patch.object(self.service.runs.factory.bridge.native_db, 'get_job', return_value=ticket or self.ticket):
            self.service.before_model(self.context, messages, factory)
        return messages

    def test_old_long_history_reserves_bounded_input_and_native_summary_is_reused(self):
        prior, task = self.long_turn()
        row, turns = self.rows()
        original = turns[0]['body']['result']
        self.assertGreater(len(session_context.project(row, turns, raw=True)), 12000)
        self.assertLessEqual(len(turns[1]['body']['context']), 12000)
        self.assertNotIn(original, turns[1]['body']['context'])
        factory, response = self.model()
        messages = self.before(factory)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(set(response.call_args.kwargs), {'messages'})
        summary_input = '\n'.join(str(message.content) for message in response.call_args.kwargs['messages'])
        self.assertIn(original, summary_input)
        self.assertNotIn('Keep the original contract', summary_input)
        projected = json.loads(messages[-1].content.split('\n', 1)[1])
        self.assertEqual(projected['goal'], self.create.goal)
        self.assertEqual(projected['boundaries'], self.create.boundaries)
        self.assertEqual([item['turnId'] for item in projected['turns']], [turns[-1]['id']])
        self.assertNotIn(prior['id'], str(projected['turns']))
        self.assertLessEqual(len(session_context.canonical(projected)), 12000)
        row, turns = self.rows()
        self.assertEqual(turns[0]['body']['result'], original)
        self.assertEqual(row['body']['contextCheckpoint']['throughSequence'], 1)
        self.assertEqual(turns[-1]['body']['compaction']['status'], 'ready')
        self.before(factory, messages, {**self.ticket, 'attempt': 2})
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(sum(message.id == 'research-context:' + turns[-1]['id'] for message in messages), 1)
        self.assertNotEqual(prior['id'], task['id'])

    def test_history_above_old_summary_limit_can_be_reserved_without_changing_original(self):
        _, prior = self.reserved()
        self.finish(prior, 'x' * 48000)
        self.reserved('long-history', 'Continue')
        self.assertEqual(len(self.rows()[1]), 2)
        self.assertEqual(self.rows()[1][0]['body']['result'], 'x' * 48000)

    def test_correction_commits_while_summary_is_outside_transaction_and_is_in_main_only(self):
        self.long_turn()
        entered, release = Event(), Event()
        def delayed(**kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return ModelResponse(role='assistant', content='{"summary":"Synthetic result","topics":[]}')
        factory, response = self.model(action=delayed)
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.before, factory)
            try:
                self.assertTrue(entered.wait(5))
                self.service.correct('alice', self.identifier, SessionText(requestId='during-summary', text='Never change the public API'))
                self.assertEqual(self.rows()[1][-1]['body']['messages'][-1]['state'], 'pending')
            finally:
                release.set()
            messages = pending.result(5)
        self.assertIn('Never change the public API', messages[-1].content)
        self.assertEqual(self.rows()[1][-1]['body']['messages'][-1]['state'], 'included')
        self.assertNotIn('Never change the public API', str(response.call_args))

    def test_current_corrections_keep_each_constraint_during_summary(self):
        self.long_turn()
        def response(**kwargs):
            for index, text in enumerate(('Do not use GPU', 'Report before editing')):
                self.service.correct('alice', self.identifier,
                    SessionText(requestId=f'late-correction-{index}', text=text))
            return ModelResponse(role='assistant', content='{"summary":"Historical notes","topics":[]}')
        factory, provider = self.model(action=response)
        messages = self.before(factory)
        row, turns = self.rows()
        self.assertEqual(turns[-1]['body']['compaction']['status'], 'ready')
        self.assertLessEqual(len(self.service._context(row, turns)), 12000)
        self.assertIn('Do not use GPU', messages[-1].content)
        self.assertIn('Report before editing', messages[-1].content)
        self.assertEqual(len(turns[-1]['body']['messages']), 3)
        self.assertEqual(turns[-1]['body']['messages'][-2]['state'], 'included')
        self.assertEqual(turns[-1]['body']['messages'][-1]['state'], 'included')
        self.assertEqual(provider.call_count, 1)

    def test_large_current_goal_survives_native_summary(self):
        self.long_turn()
        def response(**kwargs):
            with self.service.db.write() as conn:
                row = self.service._row(conn, 'alice', self.identifier)
                self.service._save_session(conn, row, {**row['body'], 'goal': 'x' * 12000})
            return ModelResponse(role='assistant', content='{"summary":"Historical notes","topics":[]}')
        factory, _ = self.model(action=response)
        messages = self.before(factory)
        self.assertEqual(self.rows()[1][-1]['body']['compaction']['status'], 'ready')
        self.assertIn('x' * 12000, messages[-1].content)

    def test_invalid_summary_preserves_pending_messages_and_explicit_retry_requires_safe_task(self):
        _, task = self.long_turn()
        factory, response = self.model(content='not JSON')
        with self.assertRaises(StopAgentRun):
            self.before(factory)
        row, turns = self.rows()
        self.assertNotIn('contextCheckpoint', row['body'])
        self.assertEqual(turns[-1]['body']['compaction']['status'], 'failed')
        self.assertTrue(all(item['state'] == 'pending' for item in turns[-1]['body']['messages']))
        with self.assertRaises(StopAgentRun):
            self.before(factory)
        self.assertEqual(response.call_count, 1)
        with self.assertRaises(HTTPException):
            self.service._reserve('alice', self.identifier, SessionText(requestId='unsafe-retry', text='Continue'))
        self.finish(task, status='failed')
        self.reserved('explicit-summary-retry', 'Retry the read-only summary')
        self.assertEqual(self.rows()[1][-1]['body']['compaction']['status'], 'pending')
        self.assertEqual(len(self.rows()[1]), 3)

    def test_unknown_summary_no_auto_retry_but_safe_explicit_retry_uses_new_task(self):
        _, task = self.long_turn()
        factory, response = self.model(action=TimeoutError('Synthetic unknown response'))
        with self.assertRaises(TimeoutError):
            self.before(factory)
        self.assertEqual(self.rows()[1][-1]['body']['compaction']['status'], 'unknown')
        with self.assertRaises(StopAgentRun):
            self.before(factory, ticket={**self.ticket, 'attempt': 2})
        self.assertEqual(response.call_count, 1)
        self.finish(task, status='failed')
        _, next_task = self.reserved('explicit-unknown-retry', 'Explicitly try read-only summarization again')
        self.assertNotEqual(next_task['id'], task['id'])
        self.assertEqual(self.rows()[1][-1]['body']['compaction']['status'], 'pending')

    def test_started_record_on_restarted_attempt_is_unknown_without_request(self):
        self.long_turn()
        with self.service.db.write() as conn:
            turn = self.service._turns(conn, self.identifier)[-1]
            body = deepcopy(turn['body'])
            body['compaction'].update(status='started', attempt=1, runId=self.context.run_id)
            self.service._save_turn(conn, turn, body)
        factory, _ = self.model()
        with self.assertRaises(StopAgentRun):
            self.before(factory, ticket={**self.ticket, 'attempt': 2})
        factory.assert_not_called()
        self.assertEqual(self.rows()[1][-1]['body']['compaction']['status'], 'unknown')

    def test_stop_during_summary_does_not_apply_late_reply_or_mark_correction(self):
        self.long_turn()
        entered, release = Event(), Event()
        def delayed(**kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return ModelResponse(role='assistant', content='{"summary":"Late reply","topics":[]}')
        factory, _ = self.model(action=delayed)
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.before, factory)
            try:
                self.assertTrue(entered.wait(5))
                asyncio.run(self.service.stop('alice', self.identifier, SessionCommand(requestId='stop-summary')))
            finally:
                release.set()
            with self.assertRaises(RunCancelledException):
                pending.result(5)
        row, turns = self.rows()
        self.assertTrue(row['body']['stopped'])
        self.assertNotIn('contextCheckpoint', row['body'])
        self.assertEqual(turns[-1]['body']['compaction']['status'], 'unknown')
        self.assertTrue(all(message['state'] == 'pending' for message in turns[-1]['body']['messages']))

    def test_shared_source_revoked_during_summary_does_not_apply_reply(self):
        self.known_window()
        _, prior = self.reserved()
        source = self.service.content.publish('bob', ContentPublication(
            source={'application': 'research', 'record': 'synthetic-context', 'revision': '1'},
            content={'result': 'synthetic'}, visibility='team'), 'share-context')
        self.service.record_source(self.context, source['id'])
        self.finish(prior, 'Evidence remains uncertain. ' * 600)
        with self.service.db.write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            body = deepcopy(row['body'])
            body['configuration']['model']['contextWindow'] = 1000
            self.service._save_session(conn, row, body)
        self.reserved('shared-summary', 'Continue with the shared source')
        def revoke(**kwargs):
            self.service.content.set_visibility('bob', source['id'], 'personal', 'revoke-context')
            return ModelResponse(role='assistant', content='{"summary":"Do not accept this reply","topics":[]}')
        factory, _ = self.model(action=revoke)
        with self.assertRaises(HTTPException) as caught:
            self.before(factory)
        self.assertEqual(caught.exception.detail['code'], 'RESEARCH_SOURCE_UNAVAILABLE')
        self.assertNotIn('contextCheckpoint', self.rows()[0]['body'])

    def test_business_effect_unknown_still_blocks_auxiliary_and_new_turn(self):
        _, task = self.long_turn()
        self.store.effect_reserve(self.context.run_id, 'research-session-tool:unknown', {'synthetic': True})
        factory, _ = self.model()
        with self.assertRaises(StopAgentRun):
            self.before(factory)
        factory.assert_not_called()
        self.assertEqual(self.rows()[1][-1]['body']['blockReason'], 'RESEARCH_EFFECT_UNCONFIRMED')
        self.finish(task, status='failed')
        with self.assertRaises(HTTPException):
            self.service._reserve('alice', self.identifier, SessionText(requestId='unsafe-new-turn', text='Continue'))

    def test_prefix_change_and_other_owner_do_not_call_summary(self):
        self.long_turn()
        factory, _ = self.model()
        with self.service.db.write() as conn:
            original = self.service._turns(conn, self.identifier)[0]
            self.service._save_turn(conn, original, {**original['body'], 'result': 'Changed immutable source'})
        with self.assertRaises(HTTPException):
            self.before(factory)
        self.context.user_id = 'bob'
        with self.assertRaises((PermissionError, HTTPException)):
            self.before(factory)
        factory.assert_not_called()

    def test_ready_checkpoint_after_interruption_is_reused_before_main(self):
        self.long_turn()
        factory, response = self.model()
        original = self.service._model_boundary
        calls = 0
        def boundary(*args):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise SystemExit('Synthetic interruption after checkpoint commit')
            return original(*args)
        with patch.object(self.service, '_model_boundary', side_effect=boundary):
            with self.assertRaises(SystemExit):
                self.before(factory)
        row, turns = self.rows()
        self.assertEqual(turns[-1]['body']['compaction']['status'], 'ready')
        self.assertTrue(all(message['state'] == 'pending' for message in turns[-1]['body']['messages']))
        saved = deepcopy(row['body']['contextCheckpoint'])
        self.before(factory, ticket={**self.ticket, 'attempt': 2})
        self.assertEqual(response.call_count, 1)
        self.assertEqual(self.rows()[0]['body']['contextCheckpoint'], saved)

    def test_refresh_rechecks_compaction_after_summary_finishes_during_detail(self):
        _, task = self.long_turn()
        entered, release = Event(), Event()
        def delayed(**kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return ModelResponse(role='assistant', content='{"summary":"Synthetic ready notes","topics":[]}')
        factory, _ = self.model(action=delayed)
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.before, factory)
            try:
                self.assertTrue(entered.wait(5))
                async def detail(_):
                    release.set()
                    await asyncio.to_thread(pending.result, 5)
                    self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
                    return self.observed_detail(task, 'completed')
                with patch.object(self.service.runs.factory, 'detail', side_effect=detail):
                    asyncio.run(self.service._refresh('alice', self.identifier))
            finally:
                release.set()
        turn = self.rows()[1][-1]
        self.assertEqual(turn['body']['compaction']['status'], 'ready')
        self.assertEqual(turn['body']['status'], 'completed')
        self.assertEqual(turn['body']['result'], 'Observed final reply')

    def test_late_old_reply_cannot_replace_new_checkpoint_or_clear_stop(self):
        _, task = self.long_turn()
        entered, release = Event(), Event()
        old_context, old_ticket = self.context, self.ticket
        def delayed(**kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return ModelResponse(role='assistant', content='{"summary":"Stale old answer","topics":[]}')
        factory, _ = self.model(action=delayed)
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.before, factory)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(StopAgentRun):
                    self.before(Mock(), ticket={**old_ticket, 'attempt': 2})
                self.finish(task, status='failed')
                self.reserved('new-after-unknown', 'Explicit new read-only summary')
                new_factory, _ = self.model(content='{"summary":"New checkpoint","topics":[]}')
                self.before(new_factory)
                saved = deepcopy(self.rows()[0]['body']['contextCheckpoint'])
            finally:
                self.context = old_context
                release.set()
            with self.assertRaises(RunCancelledException):
                pending.result(5)
        self.assertEqual(self.rows()[0]['body']['contextCheckpoint'], saved)
        self.assertEqual(saved['summary']['summary'], 'New checkpoint')

    def test_large_summary_and_manual_continuation_preserve_history(self):
        _, task = self.long_turn()
        factory, _ = self.model()
        self.before(factory)
        saved = deepcopy(self.rows()[0]['body']['contextCheckpoint'])
        self.finish(task, 'New confirmed synthetic result. ' * 500)
        _, later = self.reserved('third-turn', 'Continue again')
        too_large, _ = self.model(content=json.dumps({'summary': 'x' * 3001, 'topics': []}))
        self.before(too_large)
        row, turns = self.rows()
        self.assertNotEqual(row['body']['contextCheckpoint'], saved)
        self.assertEqual(turns[-1]['body']['compaction']['status'], 'ready')
        self.finish(later, status='failed')
        _, final_task = self.reserved('fourth-turn', 'Explicit retry')
        self.finish(final_task, status='failed')
        row, turns = self.rows()
        saved_limits = deepcopy(row['body']['limits'])
        self.reserved('manual-after-cap', 'Explicitly authorize one more task')
        self.assertEqual(self.rows()[0]['body']['limits'], saved_limits)
        self.assertEqual(len(self.rows()[1]), 5)


class NativeSummaryContract(unittest.TestCase):
    def test_unconfigured_model_has_no_invented_window_or_default_turn_budget(self):
        request = CreateSession(requestId='large-goal', title='Long request', goal='需' * 3000,
            boundaries='Stop when finished', modelConnectionRef='model')
        self.assertEqual(request.limits.model_dump(),
            {'maxTurns': None, 'toolCallsPerTurn': None, 'operationSeconds': None})
        self.assertEqual(SessionText(requestId='long-input', text='长' * 20000).text, '长' * 20000)
        self.assertIsNone(session_context.compact_token_limit({}))
        short = CreateSession(requestId='one-char', title='标题' * 100, goal='嗨', modelConnectionRef='model')
        self.assertEqual(short.boundaries, '')

    def test_user_input_limit_matches_codex_combined_character_scope(self):
        text = '文' * (MAX_USER_INPUT_TEXT_CHARS - 1)
        CreateSession(requestId='limit-edge', title='Title', goal=text, boundaries='界', modelConnectionRef='model')
        with self.assertRaisesRegex(ValueError, '1048576'):
            CreateSession(requestId='over-edge', title='Title', goal=text, boundaries='边界', modelConnectionRef='model')
        SessionText(requestId='text-edge', text=text + '界')
        with self.assertRaises(ValueError):
            SessionText(requestId='text-over', text=text + '边界')

    def test_compaction_uses_codex_model_token_window_policy(self):
        self.assertEqual(session_context.compact_token_limit({'contextWindow': 10000}), 9000)
        self.assertEqual(session_context.compact_token_limit(
            {'contextWindow': 10000, 'autoCompactTokenLimit': 12000}), 9000)
        self.assertEqual(session_context.compact_token_limit(
            {'contextWindow': 10000, 'autoCompactTokenLimit': 8000}), 8000)
        self.assertEqual(session_context.compact_token_limit({'autoCompactTokenLimit': 8000}), 8000)

    def test_ended_diagnostics_are_summary_background_but_current_unknown_identity_remains(self):
        turns = [{'id': 'old-' + status, 'sequence': index + 1, 'body': {
            'messages': [], 'status': status, 'terminal': True, 'result': status + ' original diagnostic'}}
            for index, status in enumerate(('completed', 'failed', 'canceled'))]
        row = {'body': {'goal': 'Keep facts', 'boundaries': 'Do not repeat', 'sharedSourceIds': []}}
        source, identity = session_context.summary_source(row, turns)
        self.assertEqual([item['sequence'] for item in source['confirmedReplies']], [1])
        row['body']['contextCheckpoint'] = {**identity, 'summary': {'summary': 'Non-authoritative', 'topics': []}}
        self.assertIn('failed original diagnostic', str(source['historicalMessages']))
        turns.append({'id': 'current-unknown', 'sequence': 4, 'body': {'messages': [],
            'status': 'unknown', 'terminal': False, 'toolResults': [{'effectKey': 'original-effect', 'status': 'UNKNOWN'}]}})
        for protected in (False, True):
            projected = json.loads(session_context.project(row, turns, protected=protected))
            self.assertEqual(len(projected['turns']), 1)
            self.assertEqual(projected['turns'][0]['effects'], [{'effectKey': 'original-effect', 'status': 'UNKNOWN'}])
        self.assertIn('failed original diagnostic', session_context.project(row, turns, raw=True))

    def test_long_history_and_source_catalog_do_not_fill_current_protected_context(self):
        row = {'body': {'goal': 'Current goal', 'boundaries': 'No network',
                        'sharedSourceIds': ['old-source-' + str(index) for index in range(1000)]}}
        turns = [{'id': str(index), 'sequence': index + 1, 'body': {'messages': [
            {'id': 'message-' + str(index), 'kind': 'instruction', 'text': 'historical ' * 200},
            {'id': 'correction-' + str(index), 'kind': 'correction', 'text': 'Prior constraint ' + str(index)}],
            'terminal': True, 'status': 'completed', 'result': 'old observed result'}} for index in range(30)]
        current = {'id': 'current', 'sequence': 31, 'body': {'messages': [
            {'id': 'new-instruction', 'kind': 'instruction', 'text': 'Continue the authorized work'},
            {'id': 'latest', 'kind': 'correction', 'text': 'Preserve the public API'}],
            'sharedSourceIds': ['current-source'], 'status': 'reserved', 'terminal': False}}
        packet, pending = session_context.prepare(row, turns, prospective=current)
        self.assertGreater(len(packet), 12000)
        self.assertEqual(json.loads(packet)['latestCorrection']['text'], 'Preserve the public API')
        self.assertEqual(json.loads(packet)['sharedSourceIds'], ['current-source'])
        self.assertIsNone(pending)
        source, identity = session_context.summary_source(row, turns)
        self.assertGreater(len(session_context.canonical(source)), 48000)
        self.assertEqual(len(source['historicalMessages']), 30)
        row['body']['contextCheckpoint'] = {**identity, 'summary': {'summary': 'Background only', 'topics': []}}
        projected = json.loads(session_context.project(row, [*turns, current]))
        self.assertEqual([item['turnId'] for item in projected['turns']], ['current'])
        self.assertTrue(projected['summary']['nonAuthoritative'])
        self.assertEqual(len(turns), 30)

    def test_active_constraints_and_legacy_source_ids_are_kept_exact(self):
        row = {'body': {'goal': 'Current goal', 'boundaries': 'Owner boundary', 'sharedSourceIds': ['legacy-source']}}
        turns = [{'id': 'active', 'sequence': 1, 'body': {'messages': [
            {'id': 'first', 'kind': 'correction', 'text': 'Never use GPU'},
            {'id': 'second', 'kind': 'correction', 'text': 'Report first'}], 'terminal': False, 'status': 'running'}}]
        for protected in (False, True):
            packet = json.loads(session_context.project(row, turns, protected=protected))
            self.assertEqual(packet['sharedSourceIds'], ['legacy-source'])
            self.assertEqual(packet['turns'][0]['messages'][0]['text'], 'Never use GPU')
            self.assertEqual(packet['latestCorrection']['text'], 'Report first')
        turns[0]['body'].update(terminal=True, status='completed', result='Reported A')
        turns.append({'id': 'new-user-turn', 'sequence': 2, 'body': {'messages': [
            {'id': 'new-instruction', 'kind': 'instruction', 'text': 'Now report B'}],
            'sharedSourceIds': [], 'terminal': False, 'status': 'reserved'}})
        packet = json.loads(session_context.project(row, turns, protected=True))
        self.assertEqual(packet['latestCorrection']['turnId'], 'active')
        self.assertEqual(packet['latestCorrection']['sequence'], 1)
        self.assertEqual(packet['turns'][0]['sequence'], 2)
        self.assertEqual(packet['turns'][0]['messages'][0]['text'], 'Now report B')

    def test_legacy_pending_summary_keeps_original_source_fingerprint(self):
        row = {'body': {'goal': 'Current', 'boundaries': 'Stop safely', 'sharedSourceIds': []}}
        turns = [{'id': 'old', 'sequence': 1, 'body': {'messages': [
            {'id': 'instruction', 'kind': 'instruction', 'text': 'Original request'}],
            'terminal': True, 'status': 'completed', 'result': 'Original reply'}}]
        source, identity = session_context.summary_source(row, turns, version=1)
        self.assertEqual(source, {'previousSummary': None, 'confirmedReplies': [{'sequence': 1, 'text': 'Original reply'}]})
        self.assertNotIn('projectionVersion', identity)
        self.assertEqual(identity['sourceDigest'], session_context.digest(source))
        row['body']['contextCheckpoint'] = {**identity, 'summary': {'summary': 'Legacy replies only', 'topics': []}}
        upgraded, updated_identity = session_context.summary_source(row, turns)
        self.assertEqual(upgraded['historicalMessages'][0]['messages'][0]['text'], 'Original request')
        self.assertEqual(updated_identity['projectionVersion'], 2)

    def test_native_wrapper_consumes_only_exact_json_object_and_rejects_tool_arguments(self):
        provider = Mock()
        factory = Mock(return_value=provider)
        model = session_context.SummaryModel(factory)
        messages = [Message(role='user', content='Synthetic summary input')]
        model.response(messages=messages, response_format={'type': 'json_object'})
        provider.response.assert_called_once_with(messages=messages)
        for kwargs in ({'messages': messages}, {'messages': messages, 'response_format': {'type': 'json_schema'}},
                       {'messages': messages, 'response_format': {'type': 'json_object'}, 'tools': []}):
            with self.assertRaises(ValueError):
                model.response(**kwargs)
        self.assertEqual(factory.call_count, 1)


if __name__ == '__main__':
    unittest.main()

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
from research.session_routes import SessionCommand, SessionText
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

    def long_turn(self, result=None):
        _, prior = self.reserved()
        self.finish(prior, result or 'Confirmed synthetic observation. ' * 500)
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
        self.assertEqual(projected['turns'][0]['taskId'], prior['id'])
        self.assertEqual(projected['turns'][0]['status'], 'completed')
        self.assertLessEqual(len(session_context.canonical(projected)), 12000)
        row, turns = self.rows()
        self.assertEqual(turns[0]['body']['result'], original)
        self.assertEqual(row['body']['contextCheckpoint']['throughSequence'], 1)
        self.assertEqual(turns[-1]['body']['compaction']['status'], 'ready')
        self.before(factory, messages, {**self.ticket, 'attempt': 2})
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(sum(message.id == 'research-context:' + turns[-1]['id'] for message in messages), 1)
        self.assertNotEqual(prior['id'], task['id'])

    def test_oversized_summary_input_is_rejected_before_reservation(self):
        _, prior = self.reserved()
        self.finish(prior, 'x' * 48000)
        with self.assertRaises(HTTPException) as caught:
            self.service._reserve('alice', self.identifier, SessionText(requestId='too-long', text='Continue'))
        self.assertEqual(caught.exception.detail['code'], 'RESEARCH_SUMMARY_INPUT_LIMIT')
        self.assertEqual(len(self.rows()[1]), 1)

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
        _, prior = self.reserved()
        source = self.service.content.publish('bob', ContentPublication(
            source={'application': 'research', 'record': 'synthetic-context', 'revision': '1'},
            content={'result': 'synthetic'}, visibility='team'), 'share-context')
        self.service.record_source(self.context, source['id'])
        self.finish(prior, 'Evidence remains uncertain. ' * 600)
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

    def test_too_large_summary_does_not_overwrite_prior_checkpoint_and_failed_turn_counts(self):
        _, task = self.long_turn()
        factory, _ = self.model()
        self.before(factory)
        saved = deepcopy(self.rows()[0]['body']['contextCheckpoint'])
        self.finish(task, 'New confirmed synthetic result. ' * 500)
        _, later = self.reserved('third-turn', 'Continue again')
        too_large, _ = self.model(content=json.dumps({'summary': 'x' * 3001, 'topics': []}))
        with self.assertRaises(StopAgentRun):
            self.before(too_large)
        row, turns = self.rows()
        self.assertEqual(row['body']['contextCheckpoint'], saved)
        self.assertEqual(turns[-1]['body']['compaction']['code'], 'RESEARCH_SUMMARY_TOO_LARGE')
        self.finish(later, status='failed')
        _, final_task = self.reserved('fourth-turn', 'Explicit retry')
        self.finish(final_task, status='failed')
        with self.assertRaises(HTTPException) as caught:
            self.service._reserve('alice', self.identifier, SessionText(requestId='over-max-turns', text='Continue'))
        self.assertEqual(caught.exception.detail['code'], 'RESEARCH_TURN_LIMIT')


class NativeSummaryContract(unittest.TestCase):
    def test_failed_and_canceled_result_are_never_removed_from_protected_projection(self):
        turns = [{'id': 'old-' + status, 'sequence': index + 1, 'body': {
            'messages': [], 'status': status, 'terminal': True, 'result': status + ' original diagnostic'}}
            for index, status in enumerate(('completed', 'failed', 'canceled'))]
        row = {'body': {'goal': 'Keep facts', 'boundaries': 'Do not repeat', 'sharedSourceIds': []}}
        source, identity = session_context.summary_source(row, turns)
        self.assertEqual([item['sequence'] for item in source['confirmedReplies']], [1])
        row['body']['contextCheckpoint'] = {**identity, 'summary': {'summary': 'Non-authoritative', 'topics': []}}
        for protected in (False, True):
            projected = json.loads(session_context.project(row, turns, protected=protected))
            self.assertNotIn('result', projected['turns'][0])
            self.assertEqual(projected['turns'][1]['result'], 'failed original diagnostic')
            self.assertEqual(projected['turns'][2]['result'], 'canceled original diagnostic')

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

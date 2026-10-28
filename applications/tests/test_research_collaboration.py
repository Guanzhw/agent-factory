"""Real PostgreSQL identities/transactions with scripted native state, no model IO."""
import asyncio
from copy import deepcopy
import os
import unittest
from unittest.mock import AsyncMock, patch

from agno.models.message import Message
from fastapi import HTTPException
from sqlalchemy import event, func, select

from agent_factory.application_runs import ApplicationRuns
from agent_factory.store import now
from research.session_collaboration import ResearchCollaboration
from research.session_routes import SessionCommand, SessionTurn
import test_research_conversations as conversation_fixture
import test_research_sessions as session_fixture
import test_research_session_replies as reply_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchCollaborationContracts(unittest.TestCase):
    reserved = session_fixture.ResearchSessionContracts.reserved
    before = session_fixture.ResearchSessionContracts.before
    read = session_fixture.ResearchSessionContracts.read
    finish = reply_fixture.ResearchSessionReplyContracts.finish

    def setUp(self):
        conversation_fixture.ResearchConversationContracts.setUp(self)
        self.collaboration = self.service.collaboration
        self.events = self.state['assistant_events']
        self.turn_id, self.task = self.reserved()

    def ask(self, call_id='ask-one', text='What evidence supports the measurement?', *, complete=True):
        arguments = {'assistant_id': self.assistant_id, 'text': text}
        request = {'ownerId': 'alice', 'taskId': self.context.session_id, 'sessionId': self.identifier,
            'turnId': self.turn_id, 'toolName': 'research_ask_assistant', 'callId': call_id, 'arguments': arguments}
        self.store.effect_reserve(self.context.run_id, 'research-session-tool:' + call_id, request)
        ack = self.collaboration.ask(self.context, call_id, arguments)
        if complete:
            self.store.effect_complete(self.context.run_id, 'research-session-tool:' + call_id,
                {'outcome': 'completed', 'output': ack})
        return ack['questionId'], arguments

    def intent(self, question_id):
        with self.service.db.read() as conn:
            return conn.execute(select(self.collaboration.intents).where(
                self.collaboration.intents.c.question_id == question_id)).mappings().one()

    def reply(self, question_id, text='Synthetic reply, not a real experiment.'):
        self.admission.receipts[('bob', 'assistant-message:' + question_id)] = {
            'state': 'accepted', 'taskId': 'synthetic-b-task-' + question_id, 'runId': 'synthetic-b-run'}
        with self.store.transaction() as conn:
            conn.execute(self.messages.messages.update().where(self.messages.messages.c.id == question_id).values(
                reply={'taskId': 'synthetic-b-task-' + question_id, 'text': text, 'contentIds': [], 'createdAt': now()}))

    def deliver(self, question_id):
        intent = self.intent(question_id)
        return asyncio.run(self.service.deliver_collaboration(self.store, self.store.task(self.task['id']),
            intent['body']['eventId'], question_id))

    def counts(self):
        with self.store.engine.connect() as conn:
            return tuple(conn.execute(select(func.count()).select_from(table)).scalar_one() for table in
                (self.messages.messages, self.store.local_budget_scopes.allocations,
                 self.conversations.origins, self.collaboration.intents, self.events.events))

    def test_ask_transaction_dedupes_message_origin_budget_intent_and_event(self):
        identifier, arguments = self.ask()
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))
        repeated = self.collaboration.ask(self.context, 'ask-one', arguments)
        self.assertEqual(repeated, {'questionId': identifier, 'state': 'saved'})
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))
        original = self.conversations.listing('alice', self.identifier)['items'][0]
        self.assertEqual(original['origin'], 'agent')
        self.assertEqual(original['collaboration'], {'originTurnId': self.turn_id, 'state': 'waiting'})
        inbox = self.conversations.inbox('bob')['items'][0]
        self.assertNotIn('origin', inbox)
        self.assertNotIn('collaboration', inbox)
        self.assertNotIn(self.create.goal, str(inbox))
        with self.assertRaises(HTTPException):
            self.conversations.listing('bob', self.identifier)

    def test_intent_write_failure_rolls_back_message_origin_event_and_budget(self):
        def fail(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.startswith('INSERT INTO research_collaboration_intents'):
                raise RuntimeError('synthetic exit before intent commit')
        event.listen(self.store.engine, 'before_cursor_execute', fail)
        try:
            with self.assertRaisesRegex(RuntimeError, 'before intent commit'):
                self.ask()
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', fail)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
        self.assertIsNone(self.collaboration.reconcile(self.context, 'ask-one', {
            'assistant_id': self.assistant_id, 'text': 'What evidence supports the measurement?'}))
        self.assertEqual(self.store.effects(self.task['id'])[0]['status'], 'UNKNOWN')

    def test_restart_reconciles_only_exact_saved_question_not_b_unknown(self):
        question_id, arguments = self.ask(complete=False)
        rebuilt = ResearchCollaboration(self.service, self.conversations, self.events)
        with patch.object(self.messages, 'recover', side_effect=AssertionError('No tool/manual fallback')):
            self.assertEqual(rebuilt.reconcile(self.context, 'ask-one', arguments)['questionId'], question_id)
            with self.assertRaises(PermissionError):
                rebuilt.reconcile(self.context, 'ask-one', {**arguments, 'text': 'changed'})
        self.admission.receipts[('bob', 'assistant-message:' + question_id)] = {
            'state': 'unknown', 'taskId': 'synthetic-b-unknown', 'runId': None}
        self.assertFalse(self.deliver(question_id))
        self.assertEqual(self.store.effects(self.task['id'])[0]['status'], 'DONE')
        self.assertEqual(self.messages.read('alice', question_id)['delivery']['state'], 'unknown')
        self.assertEqual(self.intent(question_id)['body']['state'], 'waiting')

    def test_multiple_replies_are_ordered_once_at_model_safety_point(self):
        first, _ = self.ask()
        second, _ = self.ask('ask-two', 'Is the result independently reproducible?')
        self.reply(second)
        self.reply(first)
        self.assertFalse(self.deliver(first))
        self.assertEqual(self.intent(first)['body']['state'], 'pending')
        messages = [Message(role='user', content='original')]
        self.before(messages)
        self.before(messages)
        with self.service.db.read() as conn:
            turn = self.service._turns(conn, self.identifier)[-1]
        self.assertEqual([item['questionId'] for item in turn['body']['assistantReplies']], [first, second])
        self.assertEqual(len([item for item in messages if item.id == 'research-context:' + self.turn_id]), 1)
        self.assertIn(first, str(messages))
        for question_id in (first, second):
            self.assertEqual(self.intent(question_id)['body']['includedTurnId'], self.turn_id)
            self.assertTrue(self.deliver(question_id))
        self.assertEqual(len(self.read()['turns']), 1)

    def test_idle_reserves_one_batch_and_repeated_event_reconciles_same_request(self):
        first, _ = self.ask()
        second, _ = self.ask('ask-two', 'Is there another comparison?')
        self.reply(first)
        self.reply(second)
        self.finish(self.task, 'Synthetic completed A round')
        calls = []
        async def reserve(owner, body, **options):
            calls.append((owner, body.requestId, options))
            plan, key = ApplicationRuns._prepare(self.service.runs, owner, body)
            self.store.reserve_task(plan, key, private_event_id=options['private_event_id'])
            raise HTTPException(503, 'synthetic acknowledgement lost after reservation')
        with patch.object(self.service.runs, 'start', side_effect=reserve):
            self.assertFalse(self.deliver(first))
            self.assertFalse(self.deliver(first))
            self.assertFalse(self.deliver(second))
        self.assertEqual(len(calls), 1)
        with self.service.db.read() as conn:
            turns = self.service._turns(conn, self.identifier)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[-1]['body']['continuation']['questionIds'], [first, second])
        self.assertTrue(turns[-1]['body']['dispatchStarted'])
        self.assertEqual(self.intent(first)['body']['continuedTurnId'], turns[-1]['id'])
        self.assertEqual(self.intent(first)['body']['state'], 'pending')
        self.assertNotIn('includedTurnId', self.intent(first)['body'])

    def test_stopped_waiting_intent_never_reactivates_after_manual_continue(self):
        question_id, _ = self.ask()
        self.finish(self.task, 'Synthetic completed A round')
        self.assertIn('stop', self.read()['allowedActions'])
        asyncio.run(self.service.stop('alice', self.identifier, SessionCommand(requestId='stop-idle-waiting')))
        self.reply(question_id)
        with patch.object(self.service.runs, 'start', AsyncMock()) as start:
            self.assertTrue(self.deliver(question_id))
            self.service._reserve('alice', self.identifier, SessionTurn(requestId='manual-after-stop', text='Continue manually'))
            self.assertTrue(self.deliver(question_id))
        start.assert_not_called()
        self.assertEqual(self.intent(question_id)['body']['state'], 'stopped')

    def test_b_terminal_failure_without_reply_blocks_a_without_restarting_b(self):
        question_id, _ = self.ask()
        # Script only the recipient task lookup; the intent and message are real PostgreSQL records.
        self.admission.receipts[('bob', 'assistant-message:' + question_id)] = {
            'state': 'accepted', 'taskId': 'scripted-b-failed', 'runId': 'scripted-b-run'}
        lookup = self.store.task
        def task(identifier, owner=None):
            if identifier == 'scripted-b-failed' and owner == 'bob':
                return {'id': identifier, 'terminal': True}
            return lookup(identifier, owner)
        with patch.object(self.store, 'task', side_effect=task), patch.object(self.service.runs, 'start', AsyncMock()) as start:
            self.assertTrue(self.deliver(question_id))
        self.assertEqual(self.intent(question_id)['body']['state'], 'blocked')
        start.assert_not_called()
        self.assertEqual(self.messages.read('alice', question_id)['delivery']['state'], 'accepted')

    def test_original_b_rejected_admission_has_explicit_terminal_feedback(self):
        question_id, _ = self.ask()
        self.admission.receipts[('bob', 'assistant-message:' + question_id)] = {
            'state': 'rejected', 'taskId': None, 'runId': None}
        self.assertTrue(self.deliver(question_id))
        self.assertEqual(self.intent(question_id)['body']['state'], 'blocked')
        self.assertEqual(self.intent(question_id)['body']['code'], 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')

    def test_stop_after_automatic_reservation_prevents_actual_native_admission(self):
        question_id, _ = self.ask()
        self.reply(question_id)
        self.finish(self.task, 'Synthetic completed A round')
        held = []
        async def stop_before_reserve(owner, body, **options):
            held.append(body)
            asyncio_stop = self.service.stop(owner, self.identifier, SessionCommand(requestId='stop-auto-race'))
            await asyncio_stop
            plan, key = ApplicationRuns._prepare(self.service.runs, owner, body)
            with self.assertRaises(HTTPException) as error:
                self.store.reserve_task(plan, key, private_event_id=options['private_event_id'])
            self.assertEqual(error.exception.detail['code'], 'RESEARCH_SESSION_STOP_REQUESTED')
        with patch.object(self.service.runs, 'start', side_effect=stop_before_reserve):
            self.assertFalse(self.deliver(question_id))
        self.assertEqual(len(held), 1)
        self.assertEqual(len(self.store.tasks('alice')), 1)
        receipt = asyncio.run(self.service.request('alice', held[0].requestId))
        self.assertEqual(receipt['action'], 'collaboration')
        self.assertEqual(receipt['session']['state'], 'stopped')
        self.assertEqual(self.intent(question_id)['body']['state'], 'stopped')

    def test_auto_turn_fails_before_model_inclusion_without_another_continuation(self):
        question_id, _ = self.ask()
        self.reply(question_id)
        self.finish(self.task, 'Synthetic completed A round')
        calls = []
        async def fail_before_model(owner, body, **options):
            calls.append(body.requestId)
            plan, key = ApplicationRuns._prepare(self.service.runs, owner, body)
            task, _ = self.store.reserve_task(plan, key, private_event_id=options['private_event_id'])
            self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
            with self.service._write() as conn:
                turn = self.service._turns(conn, self.identifier)[-1]
                self.service._save_turn(conn, turn, {**turn['body'], 'terminal': True, 'status': 'failed'})
        with patch.object(self.service.runs, 'start', side_effect=fail_before_model):
            self.assertFalse(self.deliver(question_id))
            self.assertTrue(self.deliver(question_id))
            self.assertTrue(self.deliver(question_id))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.intent(question_id)['body']['state'], 'blocked')
        self.assertEqual(self.intent(question_id)['body']['code'], 'RESEARCH_COLLABORATION_CONTINUATION_NOT_INCLUDED')
        self.assertNotIn('includedTurnId', self.intent(question_id)['body'])

    def test_auto_admission_error_reports_unknown_original_request_and_pending_reason(self):
        question_id, _ = self.ask()
        self.reply(question_id)
        self.finish(self.task, 'Synthetic completed A round')
        with patch.object(self.service.runs, 'start', side_effect=HTTPException(503, 'MODEL_CONNECTION_UNAVAILABLE')):
            self.assertFalse(self.deliver(question_id))
        intent = self.intent(question_id)
        self.assertEqual(intent['body']['state'], 'pending')
        self.assertEqual(intent['body']['code'], 'MODEL_CONNECTION_UNAVAILABLE')
        detail = self.read()
        self.assertEqual(detail['turns'][-1]['status'], 'unknown')
        receipt = asyncio.run(self.service.request('alice', detail['turns'][-1]['requestId']))
        self.assertEqual(receipt['turnId'], detail['turns'][-1]['id'])
        self.assertEqual(len(self.store.tasks('alice')), 1)

    def test_manual_selection_does_not_duplicate_automatic_reply(self):
        question_id, _ = self.ask()
        self.reply(question_id)
        self.finish(self.task, 'Synthetic completed A round')
        self.service._reserve('alice', self.identifier, SessionTurn(requestId='manual-reply-first',
            text='Use this reply', assistantQuestionId=question_id))
        self.assertFalse(self.deliver(question_id))
        with self.service._write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            turn = self.service._turns(conn, self.identifier)[-1]
            returned = self.collaboration.receive(conn, row, turn)
        self.assertNotIn('assistantReplies', returned['body'])

    def test_reply_source_revocation_blocks_all_existing_context_guards(self):
        question_id, _ = self.ask()
        self.reply(question_id)
        self.before([Message(role='user', content='original')])
        original = self.conversations.validate_reply
        def reject(owner, session_id, snapshot):
            if snapshot['questionId'] == question_id:
                raise HTTPException(409, 'synthetic revoked source')
            return original(owner, session_id, snapshot)
        with patch.object(self.conversations, 'validate_reply', side_effect=reject):
            with self.assertRaises(HTTPException):
                self.before([Message(role='user', content='original')])
            with self.assertRaises(HTTPException):
                self.service.authorize_tool(self.context, 'research_read_file')
            projected = self.read()['turns'][0]['assistantReplies'][0]
            self.assertEqual(projected['state'], 'unavailable')
            self.assertNotIn('reply', projected)

    def test_capacity_failure_preserves_reply_without_truncation_or_new_turn(self):
        question_id, _ = self.ask()
        self.reply(question_id)
        with patch.object(self.service, '_capacity', side_effect=HTTPException(409, {'code': 'RESEARCH_CONTEXT_LIMIT'})):
            self.before([Message(role='user', content='original')])
        self.assertEqual(self.intent(question_id)['body']['state'], 'blocked')
        self.assertEqual(self.intent(question_id)['body']['code'], 'RESEARCH_CONTEXT_LIMIT')
        self.assertIsNotNone(self.messages.read('alice', question_id)['reply'])
        with self.service.db.read() as conn:
            self.assertNotIn('assistantReplies', self.service._turns(conn, self.identifier)[0]['body'])

    def test_new_and_historical_session_capability_comes_from_fixed_configuration(self):
        self.assertTrue(self.read()['collaboration']['enabled'])
        with self.service._write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            body = deepcopy(row['body'])
            del body['configuration']['autonomousCollaboration']
            self.service._save_session(conn, row, body)
        self.assertFalse(self.read()['collaboration']['enabled'])

    def block_question_turn(self):
        with self.service._write() as conn:
            turn = self.service._turns(conn, self.identifier)[0]
            self.service._save_turn(conn, turn, {**turn['body'],
                'blockReason': 'RESEARCH_RESTART_REQUIRES_RECONCILIATION', 'status': 'unknown'})

    def release(self, question_id, *, native_status='completed', persisted='completed'):
        # Only native-observation inputs are scripted here. OS-exit acceptance is separate.
        observation = {'parent': {'taskId': self.task['id'], 'nativeStatus': native_status,
            'persistedRunStatus': persisted, 'unknown': True}, 'children': [], 'allStopped': False, 'unknown': True}
        ticket = {**self.ticket, 'status': native_status}
        with patch.object(self.store.lifecycle_observer, 'inspect_subtree', AsyncMock(return_value=observation)), \
                patch.object(self.service.runs.factory.bridge.native_db, 'get_job', return_value=ticket):
            return asyncio.run(self.collaboration._release_question_block(
                self.store.task(self.task['id']), self.intent(question_id)))

    def test_exact_question_receipt_only_releases_own_block_without_settling_or_starting(self):
        question_id, _ = self.ask()
        self.block_question_turn()
        original = self.store.task(self.task['id'])
        with patch.object(self.service.runs, 'start', AsyncMock()) as start:
            self.assertTrue(self.release(question_id))
        self.assertEqual(self.store.task(self.task['id']), original)
        with self.service.db.read() as conn:
            body = self.service._turns(conn, self.identifier)[0]['body']
        self.assertIsNone(body['blockReason'])
        self.assertEqual(body['status'], 'unknown')
        self.assertFalse(body['terminal'])
        start.assert_not_called()

    def test_any_other_done_file_effect_blocks_question_only_reconciliation(self):
        question_id, _ = self.ask()
        self.block_question_turn()
        self.store.effect_reserve(self.context.run_id, 'research-session-tool:synthetic-file', {'fixture': 'file-write'})
        self.store.effect_complete(self.context.run_id, 'research-session-tool:synthetic-file',
            {'outcome': 'completed', 'output': {'path': 'synthetic.py'}})
        self.assertFalse(self.release(question_id))
        with self.service.db.read() as conn:
            self.assertEqual(self.service._turns(conn, self.identifier)[0]['body']['blockReason'],
                'RESEARCH_RESTART_REQUIRES_RECONCILIATION')

    def test_nonterminal_run_or_pending_child_custody_never_releases_question_block(self):
        question_id, _ = self.ask()
        self.block_question_turn()
        self.assertFalse(self.release(question_id, persisted='running'))
        with patch.object(self.store.delegation, 'has_pending_children', return_value=True):
            self.assertFalse(self.release(question_id))
        with patch.object(self.store.application_runtime, 'effect_held', return_value=True):
            self.assertFalse(self.release(question_id))
        with self.service.db.read() as conn:
            self.assertEqual(self.service._turns(conn, self.identifier)[0]['body']['blockReason'],
                'RESEARCH_RESTART_REQUIRES_RECONCILIATION')

    def test_wrong_saved_receipt_is_not_proof_and_stopped_intent_does_not_reactivate(self):
        question_id, _ = self.ask()
        self.block_question_turn()
        self.store.effect_complete(self.context.run_id, 'research-session-tool:ask-one',
            {'outcome': 'completed', 'output': {'questionId': question_id, 'state': 'b-succeeded'}})
        self.assertFalse(self.release(question_id))
        with self.service._write() as conn:
            self.collaboration.stop(conn, 'alice', self.identifier)
        self.assertFalse(self.release(question_id))

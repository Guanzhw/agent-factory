"""Real PG session contracts with a scripted reply-authority boundary; no model IO.

Conversation/message integration is tested separately. These tests isolate adoption,
protected context, request identity and authority rechecks at execution boundaries.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from threading import Event, current_thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from agent_factory.application_runs import ApplicationRuns
from research import session_context
from research.session_routes import SessionText, SessionTurn
import test_research_sessions as fixture


class ReplySchemaTests(unittest.TestCase):
    def test_question_selection_belongs_only_to_turns(self):
        value = {'requestId': 'question-selection', 'text': 'Use this evidence', 'assistantQuestionId': str(uuid4())}
        self.assertEqual(SessionTurn(**value).assistantQuestionId, value['assistantQuestionId'])
        with self.assertRaises(ValidationError):
            SessionText(**value)
        with self.assertRaises(ValidationError):
            SessionTurn(**{**value, 'assistantQuestionId': 'not-a-message-id'})


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchSessionReplyContracts(unittest.TestCase):
    read = fixture.ResearchSessionContracts.read

    def setUp(self):
        fixture.ResearchSessionContracts.setUp(self)
        self.question_id = str(uuid4())
        self.snapshot = {'questionId': self.question_id, 'senderId': 'alice', 'recipientId': 'bob',
            'endpointId': str(uuid4()), 'questionText': 'What does the shared experiment show?',
            'reply': {'state': 'available', 'text': 'Synthetic evidence: the result remains uncertain.',
                      'contentIds': [], 'createdAt': 'synthetic-reply'},
            'delivery': {'state': 'accepted', 'taskId': str(uuid4()), 'runId': str(uuid4())}}
        self.revoked = False
        self.adoptions = Mock(side_effect=self.adopt)
        self.validation = Mock(side_effect=self.validate_reply)
        self.service.conversations = SimpleNamespace(adopt=self.adoptions, validate_reply=self.validation)

    def adopt(self, owner, session_id, question_id):
        if (owner, session_id, question_id) != ('alice', self.identifier, self.question_id):
            raise HTTPException(404, 'RESEARCH_QUESTION_NOT_FOUND')
        self.validate_reply(owner, session_id, self.snapshot)
        return deepcopy(self.snapshot)

    def validate_reply(self, owner, session_id, snapshot):
        if self.revoked or owner != 'alice' or session_id != self.identifier or snapshot != self.snapshot:
            raise HTTPException(409, 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')

    def rows(self):
        with self.service.db.read() as conn:
            return self.service._row(conn, 'alice', self.identifier), self.service._turns(conn, self.identifier)

    def request(self, key='adopt-original', **values):
        return SessionTurn(requestId=key, text='Continue using this evidence',
                           assistantQuestionId=self.question_id, **values)

    def activate(self, request=None):
        turn_id, fresh = self.service._reserve('alice', self.identifier, request or self.request())
        self.assertTrue(fresh)
        row, turns = self.rows()
        turn = turns[-1]
        start = self.service._start(row, turn)
        plan, key = ApplicationRuns._prepare(self.service.runs, 'alice', start)
        task, _ = self.store.reserve_task(plan, key)
        run_id = str(uuid4())
        self.store.accept(task['id'], run_id)
        with self.service.db.write() as conn:
            self.service._save_turn(conn, turn, {**turn['body'], 'dispatchStarted': True})
        self.context = RunContext(run_id=run_id, session_id=task['id'], user_id='alice', session_state={})
        self.ticket = {'id': run_id, 'session_id': task['id'], 'user_id': 'alice', 'attempt': 1, 'status': 'running'}
        return turn_id, task

    def finish(self, task, result):
        self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
        with self.service.db.write() as conn:
            turn = self.service._turns(conn, self.identifier)[-1]
            self.service._save_turn(conn, turn, {**turn['body'], 'terminal': True, 'status': 'completed',
                'taskId': task['id'], 'runId': task['run_id'], 'result': result, 'completedAt': 'synthetic-final'})

    def before(self, factory=None):
        factory = factory or Mock(side_effect=AssertionError('Unexpected auxiliary model'))
        messages = [Message(role='user', content=self.rows()[1][-1]['body']['context'])]
        with patch.object(self.service.runs.factory.bridge.native_db, 'get_job', return_value=self.ticket):
            self.service.before_model(self.context, messages, factory)
        return messages

    def test_selection_is_protected_and_duplicate_does_not_readopt(self):
        original, _ = self.activate()
        row, turns = self.rows()
        packet = json.loads(session_context.project(row, turns, protected=True))
        self.assertEqual(packet['turns'][0]['assistantReply']['reply'], self.snapshot['reply'])
        self.assertTrue(packet['turns'][0]['assistantReply']['nonAuthoritative'])
        self.assertEqual(packet['goal'], self.create.goal)
        self.revoked = True
        duplicate, fresh = self.service._reserve('alice', self.identifier, self.request())
        self.assertEqual(duplicate, original)
        self.assertFalse(fresh)
        self.assertEqual(self.adoptions.call_count, 1)
        with self.assertRaises(HTTPException) as error:
            self.service._reserve('alice', self.identifier, self.request().model_copy(
                update={'assistantQuestionId': str(uuid4())}))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(self.rows()[1]), 1)

    def test_no_selection_keeps_old_request_identity(self):
        request = SessionText(requestId='old-compatible-turn', text='Continue without a reply')
        original, _ = self.service._reserve('alice', self.identifier, request)
        duplicate, fresh = self.service._reserve('alice', self.identifier,
            SessionTurn(**request.model_dump(), assistantQuestionId=None))
        self.assertEqual(duplicate, original)
        self.assertFalse(fresh)
        self.assertNotIn('assistantReply', self.rows()[1][0]['body'])
        self.adoptions.assert_not_called()

    def test_missing_or_unavailable_reply_and_capacity_leave_no_turn(self):
        with self.assertRaises(HTTPException):
            self.service._reserve('alice', self.identifier, self.request().model_copy(
                update={'assistantQuestionId': str(uuid4())}))
        self.revoked = True
        with self.assertRaises(HTTPException):
            self.service._reserve('alice', self.identifier, self.request())
        self.revoked = False
        with self.service.db.write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            self.service._save_session(conn, row, {**row['body'], 'boundaries': 'b' * 11300})
        with self.assertRaises(HTTPException) as error:
            self.service._reserve('alice', self.identifier, self.request())
        self.assertEqual(error.exception.detail['code'], 'RESEARCH_CONTEXT_LIMIT')
        self.assertEqual(self.rows()[1], [])

    def test_revocation_hides_session_copy_and_blocks_model_tool_and_next_turn(self):
        _, task = self.activate()
        self.before()
        self.revoked = True
        for call in (self.before, lambda: self.service.authorize_tool(self.context, 'research_read_file')):
            with self.assertRaises(HTTPException) as error:
                call()
            self.assertEqual(error.exception.detail['code'], 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')
        self.finish(task, 'Previously observed result')
        for detail in (self.read(), asyncio.run(self.service.request('alice', 'adopt-original'))['session']):
            self.assertEqual(detail['blockReason'], 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')
            self.assertNotIn('start', detail['allowedActions'])
            self.assertEqual(detail['turns'][0]['assistantReply'], {
                'state': 'unavailable', 'questionId': self.question_id, 'code': 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE'})
        with self.assertRaises(HTTPException):
            self.service._reserve('alice', self.identifier, SessionTurn(requestId='next-after-withdrawal', text='Continue'))
        self.assertEqual(self.rows()[1][0]['body']['assistantReply'], self.snapshot)

    def test_summary_preserves_quote_and_rechecks_authority_before_and_after(self):
        _, task = self.activate()
        self.finish(task, 'Confirmed synthetic history. ' * 600)
        self.activate(SessionTurn(requestId='after-long-history', text='Continue with preserved constraints'))
        self.revoked = True
        factory = Mock()
        with self.assertRaises(HTTPException):
            self.before(factory)
        factory.assert_not_called()
        self.revoked = False
        def response(**kwargs):
            self.revoked = True
            return ModelResponse(role='assistant', content='{"summary":"Synthetic notes","topics":[]}')
        model = SimpleNamespace(response=Mock(side_effect=response))
        factory = Mock(return_value=model)
        with self.assertRaises(HTTPException):
            self.before(factory)
        self.assertEqual(factory.call_count, 1)
        row, turns = self.rows()
        self.assertNotIn('contextCheckpoint', row['body'])
        self.assertEqual(turns[-1]['body']['messages'][0]['state'], 'pending')
        self.assertEqual(turns[0]['body']['assistantReply'], self.snapshot)

    def test_successful_summary_keeps_reply_outside_summary_and_checks_checkpoint_reuse(self):
        _, task = self.activate()
        self.finish(task, 'Confirmed synthetic history. ' * 600)
        self.activate(SessionTurn(requestId='continue-with-summary', text='Continue'))
        model = SimpleNamespace(response=Mock(return_value=ModelResponse(
            role='assistant', content='{"summary":"Synthetic notes","topics":[]}')))
        factory = Mock(return_value=model)
        messages = self.before(factory)
        packet = json.loads(messages[-1].content.split('\n', 1)[1])
        self.assertEqual(packet['turns'][0]['assistantReply']['reply']['text'], self.snapshot['reply']['text'])
        self.assertNotIn(self.snapshot['reply']['text'], str(model.response.call_args))
        self.revoked = True
        with self.assertRaises(HTTPException):
            self.before(factory)
        self.assertEqual(factory.call_count, 1)

    def test_reply_admission_and_protocol_cancel_share_lock_order(self):
        _, prior = self.activate()
        self.finish(prior, 'Confirmed prior result')
        protocol_context = self.context
        budget_held, writer_attempted = Event(), Event()
        original_lock = self.store.local_budget_scopes.admission_lock
        writer_name = None
        def lock(conn):
            if current_thread().name == writer_name:
                writer_attempted.set()
            return original_lock(conn)
        def reject():
            with self.store.transaction() as conn:
                original_lock(conn)
                budget_held.set()
                self.assertTrue(writer_attempted.wait(5))
                free = conn.execute(text(
                    "SELECT pg_try_advisory_xact_lock(hashtext('research_sessions_v1'))")).scalar_one()
                self.assertTrue(free, 'Reply admission must take af_admission before the session write lock')
                self.store.reject_model_protocol(protocol_context)
        def reserve():
            nonlocal writer_name
            writer_name = current_thread().name
            self.assertTrue(budget_held.wait(5))
            return self.service._reserve('alice', self.identifier, self.request('after-protocol-stop'))
        with patch.object(self.store.local_budget_scopes, 'admission_lock', side_effect=lock):
            with ThreadPoolExecutor(max_workers=2) as workers:
                rejected = workers.submit(reject)
                admitted = workers.submit(reserve)
                rejected.result(10)
                _, fresh = admitted.result(10)
        self.assertTrue(fresh)
        self.assertTrue(self.store.task(prior['id'], 'alice')['cancel_requested'])


if __name__ == '__main__':
    unittest.main()

"""Real PostgreSQL collaboration admission; replies are synthetic, not model QA."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agno.run import RunContext
from sqlalchemy import select

from agent_factory.application_runs import StartNotSubmitted
from agent_factory.store import now
from research.assistants import ConfigureAssistant
import test_chat_journey as journey


class CollaborationAdmission(unittest.TestCase):
    setUpClass = classmethod(journey.ChatJourney.setUpClass.__func__)
    post, session, wait_for, send = journey.ChatJourney.post, journey.ChatJourney.session, journey.ChatJourney.wait_for, journey.ChatJourney.send

    def setUp(self):
        journey.ChatJourney.setUp(self)
        self.send('切换模型后继续')
        snapshot = self.wait_for(lambda value: value['turns'][-1]['completedAt'] is not None)
        self.sessions = self.state['research_sessions']
        self.collaboration = self.sessions.collaboration
        self.store = self.sessions.store
        self.identifier = snapshot['id']
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown)
        # This test drives delivery itself, so the background event scanner must not race its barriers.
        scanner = patch.object(self.collaboration.events, '_deliver_collaboration', new=AsyncMock())
        scanner.start()
        self.addCleanup(scanner.stop)
        with self.sessions.db.read() as conn:
            row = self.sessions._row(conn, self.owner, self.identifier)
            turn = self.sessions._turns(conn, self.identifier)[-1]
        self.origin_task = self.sessions._task(self.owner, turn)
        assistant = self.sessions.assistants.me(self.owner)['assistant']
        self.sessions.assistants.configure(self.owner, ConfigureAssistant(requestId=str(uuid4()),
            expectedRevision=assistant['configurationRevision'], connectionRefs=row['body']['configuration']['connectionRefs']))
        context = RunContext(run_id=self.origin_task['run_id'], session_id=self.origin_task['id'], user_id=self.owner)
        call_id = str(uuid4())
        arguments = {'assistant_id': assistant['id'], 'text': 'Synthetic reply for admission regression'}
        self.store.effect_reserve(context.run_id, 'research-session-tool:' + call_id,
            {'ownerId': self.owner, 'taskId': self.origin_task['id'], 'sessionId': row['id'], 'turnId': turn['id'],
             'toolName': 'research_ask_assistant', 'callId': call_id, 'arguments': arguments})
        # Seed a genuine question/event on the completed fixture turn without running another model.
        with patch.object(self.sessions, '_execution', return_value=(row, turn, self.origin_task)), \
                patch.object(self.sessions, 'authorize_tool'):
            self.question = self.collaboration.ask(context, call_id, arguments)['questionId']
        messages = self.collaboration.conversations.messages
        with messages.db.write() as conn:
            conn.execute(messages.messages.update().where(messages.messages.c.id == self.question).values(
                reply={'taskId': self.origin_task['id'], 'text': 'Fixture answer', 'contentIds': [], 'createdAt': now()}))
        self.event = self.intent()['body']['eventId']
        self.addCleanup(self.collaboration.events._finish_collaboration, self.event, True, None)

    def intent(self):
        with self.sessions.db.read() as conn:
            return conn.execute(select(self.collaboration.intents).where(
                self.collaboration.intents.c.question_id == self.question)).mappings().one()

    def latest(self):
        with self.sessions.db.read() as conn:
            return self.sessions._turns(conn, self.identifier)[-1]

    def deliver(self):
        return self.pool.submit(asyncio.run,
            self.sessions.deliver_collaboration(self.store, self.origin_task, self.event, self.question))

    def test_prequeue_failure_is_terminal_and_manual_chat_continues(self):
        with patch.object(self.sessions.runs, '_prepare', side_effect=RuntimeError('fixture unavailable')) as prepare:
            self.assertTrue(self.deliver().result(15))
            self.assertTrue(self.deliver().result(15))
            self.assertEqual(prepare.call_count, 1)
        turn = self.latest()
        self.assertEqual(turn['body']['status'], 'failed')
        self.assertTrue(turn['body']['neverDispatched'])
        self.assertIsNone(self.sessions._task(self.owner, turn))
        self.assertEqual(self.intent()['body']['state'], 'blocked')
        self.post('/research/sessions/' + self.identifier + '/turns', {'text': '切换模型后继续'})
        completed = self.wait_for(lambda value: value['turns'][-1]['completedAt'] is not None)
        self.assertEqual(completed['turns'][-1]['status'], 'completed')

    def test_duplicate_delivery_cannot_admit_between_absence_check_and_failure(self):
        checked, release = threading.Event(), threading.Event()
        original = self.sessions._not_submitted
        first = True
        async def start(owner, body, **kwargs):
            nonlocal first
            if first:
                first = False
                raise StartNotSubmitted(RuntimeError('first preflight failed'))
            return await original_start(owner, body, **kwargs)
        def absence(owner, turn, error):
            result = original(owner, turn, error)
            checked.set()
            if not release.wait(10):
                raise AssertionError('Admission barrier timed out')
            return result
        original_start = self.sessions.runs.start
        original_transaction = self.store.transaction
        second_thread = None
        @contextmanager
        def transaction(**kwargs):
            with original_transaction(**kwargs) as conn:
                if threading.get_ident() == second_thread:
                    conn.exec_driver_sql("SET LOCAL application_name='collaboration-second-delivery'")
                yield conn
        def duplicate():
            nonlocal second_thread
            second_thread = threading.get_ident()
            return asyncio.run(self.sessions.deliver_collaboration(
                self.store, self.origin_task, self.event, self.question))
        with patch.object(self.sessions.runs, 'start', side_effect=start), \
                patch.object(self.sessions, '_not_submitted', side_effect=absence), \
                patch.object(self.store, 'transaction', side_effect=transaction):
            a = self.deliver()
            try:
                self.assertTrue(checked.wait(10))
                b = self.pool.submit(duplicate)
                waiting = []
                deadline = time.monotonic() + 10
                while not b.done() and time.monotonic() < deadline:
                    waiting = self.store.sql("SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                                             "AND wait_event='advisory' AND application_name='collaboration-second-delivery'")
                    if waiting:
                        break
                    time.sleep(.02)
                self.assertTrue(b.done() or waiting, 'Second delivery did not reach admission')
            finally:
                release.set()
            a.result(15)
            b.result(15)
        turn = self.latest()
        task = self.sessions._task(self.owner, turn)
        self.assertFalse(task is not None and turn['body'].get('neverDispatched'),
                         'A concurrent admitted task must not be declared never dispatched')
        self.assertEqual(turn['body']['status'], 'failed')
        self.assertIsNone(task)
        self.assertEqual(self.intent()['body']['state'], 'blocked')

    def test_stop_survives_prequeue_failure(self):
        entered, release = threading.Event(), threading.Event()
        def prepare(*args):
            entered.set()
            if not release.wait(10):
                raise AssertionError('Stop barrier timed out')
            raise RuntimeError('fixture unavailable')
        with patch.object(self.sessions.runs, '_prepare', side_effect=prepare):
            delivery = self.deliver()
            try:
                self.assertTrue(entered.wait(10))
                request = str(uuid4())
                self.post('/research/sessions/' + self.identifier + '/stop', {'requestId': request})
            finally:
                release.set()
            delivery.result(15)
        self.assertEqual(self.latest()['body']['stopRequestId'], request)
        self.assertEqual(self.intent()['body']['state'], 'stopped')
        self.assertIsNone(self.sessions._task(self.owner, self.latest()))
        with patch.object(self.sessions.runs, 'start', new=AsyncMock()) as start:
            self.assertTrue(self.deliver().result(15))
            start.assert_not_called()

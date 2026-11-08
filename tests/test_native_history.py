"""Conversation history through native PostgreSQL runs and a local HTTP model."""
from http.server import ThreadingHTTPServer
import json
from threading import Event, Thread
import unittest
from typing import Any
from unittest.mock import patch

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

from research import session_context
import test_chat_journey as journey
from test_native_model import Endpoint, reply


class NativeHistory(journey.ChatJourney):
    def setUp(self):
        super().setUp()
        self.provider: Any = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        self.provider.requests, self.provider.hold, self.provider.started = [], None, Event()
        self.provider.answer = lambda body: (200, reply('answer:' + body['messages'][-1]['content']))
        thread = Thread(target=self.provider.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.provider.server_close)
        self.addCleanup(self.provider.shutdown)
        model = self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'history-fixture',
            'baseURL': f'http://127.0.0.1:{self.provider.server_port}/v1'})
        self.reference = model['connectionRef']
        value = self.post('/research/sessions', {'title': 'History', 'goal': 'Preserve conversation facts',
            'modelConnectionRef': self.reference})
        self.path = '/research/sessions/' + value['id']
        self.page.goto(self.origin + '/?researchSession=' + value['id'])
        self.addCleanup(lambda: self.post(self.path + '/stop', {}))

    def turn(self, text, count):
        self.post(self.path + '/turns', {'text': text})
        return self.wait_for(lambda value: len(value['turns']) == count and value['turns'][-1]['completedAt'] is not None)

    def test_old_session_then_six_turns_fail_continue_and_owner_isolation(self):
        service = self.state['research_sessions']
        # Produce an authentic old per-task native session, then remove the compatibility fixture.
        with patch.object(service, 'native_session_for_plan', return_value=None):
            first = self.turn('legacy-earliest-marker', 1)
        self.assertEqual(first['turns'][0]['status'], 'completed')
        first_task = service.store.task(first['turns'][0]['taskId'], self.owner)
        self.assertEqual(service.store.native_session_id(first_task), first_task['id'])
        for index in range(2, 7):
            value = self.turn(f'new-turn-{index}', index)
            self.assertEqual(value['turns'][-1]['status'], 'completed')
        request = self.provider.requests[-1][0]
        wire = json.dumps(request)
        self.assertIn('legacy-earliest-marker', wire)
        for index in range(2, 7):
            self.assertIn(f'new-turn-{index}', wire)
        self.assertNotIn('sessionContext', wire)
        self.assertEqual(sum(item['content'] == 'legacy-earliest-marker' for item in request['messages']), 1)
        task = service.store.task(value['turns'][-1]['taskId'], self.owner)
        self.assertEqual(service.store.native_session_id(task), value['id'])
        self.provider.answer = lambda _: (400, {'error': {'message': 'actual-history-provider-failure', 'type': 'invalid_request_error'}})
        failed = self.turn('failed-user-instruction', 7)
        self.assertEqual(failed['turns'][-1]['status'], 'failed')
        self.assertIn('HTTP 400', failed['turns'][-1]['failure'])
        db = service.runs.factory.bridge.native_db
        self.assertEqual(db.get_job(failed['turns'][-1]['runId'])['status'], 'completed')
        self.assertEqual(db.get_run(failed['turns'][-1]['runId']).status, RunStatus.error)
        with service._write() as conn:
            row = service._row(conn, self.owner, failed['id'])
            service._save_session(conn, row, {**row['body'], 'contextCheckpoint': {
                'throughSequence': 7, 'summary': {'summary': 'v1-successful-answers-only'}}})
        self.provider.answer = lambda _: (200, reply('recovered'))
        recovered = self.turn('recover-with-new-instruction', 8)
        self.assertEqual(recovered['turns'][-1]['status'], 'completed')
        wire = json.dumps(self.provider.requests[-1][0])
        self.assertIn('failed-user-instruction', wire)
        self.assertIn('legacy-earliest-marker', wire)
        self.assertNotIn('v1-successful-answers-only', wire)
        self.assertIn('failed', wire)
        db = service.runs.factory.bridge.native_db
        stored = db.get_session(value['id'], user_id=self.owner)
        self.assertEqual(len({run.run_id for run in stored.runs}), 7)
        self.assertIsNone(db.get_session(value['id'], user_id='different-owner'))
        self.page.reload()
        self.assertEqual(len(self.session()['turns']), 8)
        entered, release = Event(), Event()
        def held_answer(_):
            entered.set()
            release.wait(20)
            return 200, reply('late response')
        self.provider.answer = held_answer
        self.addCleanup(release.set)
        self.post(self.path + '/turns', {'text': 'stopped-user-instruction'})
        try:
            self.assertTrue(entered.wait(20))
            self.post(self.path + '/stop', {})
        finally:
            release.set()
        stopped = self.wait_for(lambda row: len(row['turns']) == 9 and row['turns'][-1]['completedAt'] is not None)
        self.assertEqual(stopped['turns'][-1]['status'], 'canceled')
        self.provider.answer = lambda _: (200, reply('continued after Stop'))
        continued = self.turn('continue-after-stop', 10)
        self.assertEqual(continued['turns'][-1]['status'], 'completed')
        wire = json.dumps(self.provider.requests[-1][0])
        self.assertIn('stopped-user-instruction', wire)
        self.assertIn('canceled', wire)

    def test_summary_and_correction_keep_original_native_runs(self):
        self.provider.answer = lambda body: (200, reply(json.dumps({'summary': 'summarized-old-marker', 'topics': []})
            if body['messages'][-1]['content'] == 'Provide the summary of the conversation.' else 'initial-answer'))
        first = self.turn('initial-original-marker', 1)
        self.post(self.path + '/corrections', {'text': 'latest-correction-marker'})
        service = self.state['research_sessions']
        with service._write() as conn:
            row = service._row(conn, self.owner, first['id'])
            service._save_session(conn, row, {**row['body'], 'contextCheckpoint': {
                'throughSequence': 1, 'projectionVersion': 1, 'summary': {'summary': 'v1-answer-only'}}})
        compact_model = self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'history-compact',
            'baseURL': f'http://127.0.0.1:{self.provider.server_port}/v1', 'autoCompactTokenLimit': 1})
        self.post(self.path + '/turns', {'text': 'newer-instruction-marker', 'modelConnectionRef': compact_model['connectionRef']})
        value = self.wait_for(lambda row: len(row['turns']) == 2 and row['turns'][-1]['completedAt'] is not None)
        self.assertEqual(value['turns'][-1]['status'], 'completed')
        self.assertEqual(value['context']['compaction']['status'], 'ready')
        summary_request = next(request for request, _ in self.provider.requests
            if request['messages'][-1]['content'] == 'Provide the summary of the conversation.')
        self.assertIn('initial-original-marker', json.dumps(summary_request))
        self.assertIn('latest-correction-marker', json.dumps(summary_request))
        self.assertNotIn('v1-answer-only', json.dumps(summary_request))
        primary = [request for request, _ in self.provider.requests if request.get('tools')][-1]
        wire = json.dumps(primary)
        self.assertIn('summarized-old-marker', wire)
        self.assertIn('latest-correction-marker', wire)
        self.assertIn('newer-instruction-marker', wire)
        self.assertLess(wire.index('latest-correction-marker'), wire.index('newer-instruction-marker'))
        db = self.state['research_sessions'].runs.factory.bridge.native_db
        original = db.get_run(first['turns'][0]['runId'])
        self.assertIn('initial-original-marker', str(original.messages))
        self.assertEqual(original.status, RunStatus.completed)
        third = self.turn('third-after-summary', 3)
        self.assertEqual(third['turns'][-1]['status'], 'completed')
        primary = [request for request, _ in self.provider.requests if request.get('tools')][-1]
        self.assertNotIn('initial-original-marker', json.dumps(primary))
        self.assertIn('latest-correction-marker', json.dumps(primary))


class InterruptedHistory(unittest.TestCase):
    def test_cancelled_tool_fact_is_usable_without_changing_stored_status_or_index(self):
        native = RunOutput(run_id='cancelled', status=RunStatus.cancelled, messages=[
            Message(role='user', content='real instruction'), Message(role='assistant', tool_calls=[
                {'id': 'unfinished', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{}'}}])])
        session = AgentSession(session_id='conversation', runs=[native])
        turn = {'id': 'turn', 'body': {'status': 'canceled', 'messages': [], 'failure': 'User stopped execution'}}
        view = session_context.history_run(turn, native)
        session_context.history_view(session, [view], None)
        history = session.get_messages()
        self.assertIn('outcome is unknown', str(history))
        self.assertIn('User stopped execution', str(history))
        self.assertEqual([message.tool_call_id for message in history if message.role == 'tool'], ['unfinished'])
        self.assertIs((session.runs or [])[0], native)
        self.assertEqual(len(native.messages or []), 2)
        self.assertEqual(native.status, RunStatus.cancelled)


def load_tests(loader, tests, pattern):
    # Reuse journey startup, without rerunning its unrelated inherited scenarios.
    return unittest.TestSuite([loader.loadTestsFromName(name, NativeHistory)
        for name in NativeHistory.__dict__ if name.startswith('test_')] + [loader.loadTestsFromTestCase(InterruptedHistory)])

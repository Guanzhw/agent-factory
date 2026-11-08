"""A finished conversation can continue without replaying an unknown operation."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from agent_factory.application_runs import StartNotSubmitted

from sqlalchemy import Column, JSON, MetaData, String, Table

from research.sessions import ResearchSessions


class SessionUnknown(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = object.__new__(ResearchSessions)
        self.turn = {'id': 'turn', 'sequence': 1, 'body': {'terminal': False, 'status': 'running',
            'blockReason': 'RESEARCH_EFFECT_UNCONFIRMED', 'children': []}}
        self.task = {'id': 'task', 'run_id': 'run', 'terminal': False, 'researchChild': False,
                     'admission': 'accepted', 'body': {}}
        self.ticket = {'id': 'run', 'session_id': 'task', 'user_id': 'owner', 'status': 'completed', 'attempt': 1}
        self.effect = {'effect_key': 'run:command', 'status': 'UNKNOWN', 'result': None}
        self.session.store = SimpleNamespace(task=Mock(return_value=self.task),
            native_session_id=lambda task: task["id"], task_for_context=lambda _: self.task,
            effects=Mock(return_value=[self.effect]), sql=Mock(return_value=[]), event=Mock())
        self.conn = Mock()
        self.conn.execute.return_value.mappings.return_value.one.return_value = self.turn
        self.session.db = SimpleNamespace(read=lambda: nullcontext(self.conn))
        self.session._write = lambda: nullcontext(self.conn)
        self.session.turns = Table('turns', MetaData(), Column('id', String), Column('body', JSON))
        self.session._row = Mock(return_value={'id': 'session', 'body': {'sharedSourceIds': []}})
        self.session._turns = Mock(return_value=[self.turn])
        self.session._task = Mock(return_value=self.task)
        self.session.memory = SimpleNamespace(observe=Mock())
        self.session.subagents = SimpleNamespace(children=AsyncMock(return_value=[]),
            permits_continuation=Mock(return_value=False))
        self.session.research = self.session.collaboration = None
        self.session._sources = self.session._replies = Mock()
        def save(_conn, _turn, body):
            self.turn['body'] = body
        self.session._save_turn = save
        run = {'run_id': 'run', 'session_id': 'task', 'user_id': 'owner',
            'status': 'completed', 'content': 'Finished; command outcome remains unknown.',
            'messages': [{'role': 'assistant', 'content': 'Finished; command outcome remains unknown.'}]}
        self.session.runs = SimpleNamespace(factory=SimpleNamespace(
            bridge=SimpleNamespace(native_db=SimpleNamespace(get_job=Mock(return_value=self.ticket))),
            detail=AsyncMock(return_value={'job': {'status': 'finalizing'}, 'events': [],
                'snapshot': {'queue': self.ticket, 'run': run, 'effects': [self.effect]}})))

    def test_submission_classification_preserves_public_http_error(self):
        original = HTTPException(403, {'code': 'RESOURCE_UNAVAILABLE', 'message': 'Unavailable'},
                                 {'X-Request-Id': 'original'})
        classified = StartNotSubmitted(original)
        self.assertEqual((classified.status_code, classified.detail, classified.headers),
                         (original.status_code, original.detail, original.headers))
        self.assertNotIn('private diagnostic', StartNotSubmitted(RuntimeError('private diagnostic')).detail)

    def test_absence_alone_never_proves_a_start_was_not_submitted(self):
        self.session._task.return_value = None
        self.assertFalse(self.session._not_submitted('owner', self.turn, RuntimeError()))
        rejected = StartNotSubmitted(RuntimeError())
        self.assertTrue(self.session._not_submitted('owner', self.turn, rejected))
        self.session._task.return_value = self.task
        self.assertFalse(self.session._not_submitted('owner', self.turn, rejected))
        self.session._task.side_effect = HTTPException(503, 'Unavailable')
        self.assertFalse(self.session._not_submitted('owner', self.turn, rejected))

    async def test_native_end_allows_independent_turn_but_retains_unknown_and_stop(self):
        await self.session._refresh('owner', 'session')
        self.assertEqual(self.turn['body']['status'], 'completed')
        self.assertIn('outcome remains unknown', self.turn['body']['result'])
        self.assertTrue(self.session._safe('owner', self.turn))
        self.assertFalse(self.task['terminal'])
        self.assertEqual(self.effect['status'], 'UNKNOWN')
        self.assertEqual(self.turn['body']['toolResults'][0]['status'], 'UNKNOWN')
        self.ticket['status'] = 'running'
        self.assertFalse(self.session._safe('owner', self.turn))
        self.ticket['status'] = 'completed'
        self.turn['body']['children'] = [{'status': 'running'}]
        self.assertFalse(self.session._safe('owner', self.turn))
        self.turn['body']['children'] = []
        self.turn['body']['stopRequestId'] = 'stop'
        self.assertFalse(self.session._safe('owner', self.turn))

    async def test_unknown_does_not_block_model_but_queue_retry_still_does(self):
        row = self.session._row()
        self.session._execution = Mock(return_value=(row, self.turn, self.task))
        context = SimpleNamespace(run_id='run', user_id='owner')
        self.assertIsNone(self.session._model_boundary(self.conn, context)[-1])
        self.assertIsNone(self.turn['body']['blockReason'])
        self.ticket['attempt'] = 2
        self.assertEqual(self.session._model_boundary(self.conn, context)[-1],
            'RESEARCH_RESTART_REQUIRES_RECONCILIATION')
        self.assertEqual(self.effect['status'], 'UNKNOWN')

    async def test_stop_recorded_during_observation_prevents_terminal_upgrade(self):
        current = {'id': 'turn', 'body': {**self.turn['body'], 'stopRequestId': 'stop'}}
        self.conn.execute.return_value.mappings.return_value.one.return_value = current
        await self.session._refresh('owner', 'session')
        self.assertFalse(self.turn['body']['terminal'])
        self.assertEqual(self.turn['body']['status'], 'finalizing')
        self.assertEqual(self.turn['body']['stopRequestId'], 'stop')
        self.assertFalse(self.session._safe('owner', self.turn))

    async def test_retry_failure_allows_new_turn_only_after_native_end(self):
        self.turn['body']['blockReason'] = 'RESEARCH_RESTART_REQUIRES_RECONCILIATION'
        self.ticket['attempt'] = 2
        self.ticket['status'] = 'running'
        await self.session._refresh('owner', 'session')
        self.assertFalse(self.session._safe('owner', self.turn))
        self.ticket['status'] = 'completed'
        await self.session._refresh('owner', 'session')
        self.assertEqual(self.turn['body']['status'], 'failed')
        self.assertIsNone(self.turn['body']['result'])
        self.assertIn('自动重试已停止', self.turn['body']['failure'])
        self.assertIsNone(self.turn['body']['blockReason'])
        self.assertTrue(self.session._safe('owner', self.turn))
        self.assertEqual(self.effect['status'], 'UNKNOWN')

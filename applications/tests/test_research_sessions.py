"""Real PG conversation/admission contracts; synthetic run identities, no model IO.

These tests do not claim native queue crash recovery or live model integration.
The separate runtime/browser acceptance exercises those boundaries.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
import unittest

from agno.exceptions import RunCancelledException, StopAgentRun
from agno.models.message import Message
from agno.run import RunContext
from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.application_content import ContentPublication
from agent_factory.application_interface import ApplicationStart
from agent_factory.application_runs import ApplicationRuns
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.session_routes import CreateSession, SessionCommand, SessionLimits, SessionText
from research.session_tools import ResearchSessionTools


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchSessionContracts(unittest.TestCase):
    def setUp(self):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        directory = self.enterContext(TemporaryDirectory())
        (Path(directory) / 'coding').mkdir()
        self.tools = ResearchSessionTools(workspace_root=Path(directory) / 'coding', host_commands=True)
        app = create_app(Settings(db_url=isolated.url, workspace=Path(directory) / 'factory'), session_tools=self.tools)
        state = factory_state(app)
        self.store, self.service = state['store'], state['research_sessions']
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.dispose_root_locks)
        initialize_members(state['auth'])
        model = self.store.personal_models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic-session'}, 'configure-session-model')
        self.create = CreateSession(requestId='create-session-original', title='Synthetic contract research',
            goal='Preserve the real original goal', boundaries='Never install dependencies',
            modelConnectionRef=model['connectionRef'], limits={'maxTurns': 4, 'toolCallsPerTurn': 4, 'operationSeconds': 5})
        self.identifier = self.service.create('alice', self.create)

    def read(self):
        return asyncio.run(self.service.read('alice', self.identifier))

    def reserved(self, request='turn-original', text='Read then test', alter_start=None):
        turn_id, fresh = self.service._reserve('alice', self.identifier, SessionText(requestId=request, text=text))
        self.assertTrue(fresh)
        with self.service.db.read() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            turn = conn.execute(select(self.service.turns).where(self.service.turns.c.id == turn_id)).mappings().one()
        conf = row['body']['configuration']
        start = ApplicationStart(requestId=turn['application_request_id'], application=conf['applicationRef']['id'],
            applicationRef=conf['applicationRef'], mode='autonomous', goal=row['body']['goal'],
            connectionRefs=conf['connectionRefs'], inputValues={'sessionId': self.identifier, 'turnId': turn_id,
                                                             'sessionContext': turn['body']['context']})
        if alter_start is not None:
            start = alter_start(start)
        plan, key = ApplicationRuns._prepare(self.service.runs, 'alice', start)
        task, _ = self.store.reserve_task(plan, key)
        run_id = str(uuid4())
        self.store.accept(task['id'], run_id)
        self.context = RunContext(run_id=run_id, session_id=task['id'], user_id='alice', session_state={})
        self.ticket = {'id': run_id, 'session_id': task['id'], 'user_id': 'alice', 'attempt': 1, 'status': 'running'}
        return turn_id, task

    def before(self, messages, ticket=None):
        with patch.object(self.service.runs.factory.bridge.native_db, 'get_job', return_value=ticket or self.ticket):
            self.service.before_model(self.context, messages)

    def test_owner_identity_configuration_reuse_and_request_conflict(self):
        self.assertEqual(self.service.create('alice', self.create), self.identifier)
        with self.assertRaises(HTTPException) as error:
            self.service.create('alice', self.create.model_copy(update={'goal': 'changed payload'}))
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException) as error:
            asyncio.run(self.service.read('bob', self.identifier))
        self.assertEqual(error.exception.status_code, 404)
        second = self.service.create('alice', self.create.model_copy(update={'requestId': 'create-second-session'}))
        first, other = self.read(), asyncio.run(self.service.read('alice', second))
        self.assertEqual(first['assistantId'], other['assistantId'])
        with self.service.db.read() as conn:
            rows = list(conn.execute(select(self.service.setup.configurations)).mappings())
        self.assertEqual(len(rows), 1)
        self.assertEqual(first['turns'], [])
        changed_model = self.store.personal_models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic-second'}, 'configure-second-session-model')
        third = self.service.create('alice', self.create.model_copy(update={'requestId': 'create-third-session',
            'modelConnectionRef': changed_model['connectionRef'],
            'limits': SessionLimits(maxTurns=10, toolCallsPerTurn=4, operationSeconds=5)}))
        with self.service.db.read() as conn:
            rows = list(conn.execute(select(self.service.setup.configurations)).mappings())
            first_config = self.service._row(conn, 'alice', self.identifier)['body']['configuration']
            third_config = self.service._row(conn, 'alice', third)['body']['configuration']
        self.assertEqual(len(rows), 1, 'Connection selection and total turns must not republish structural materials')
        self.assertEqual(first_config['applicationRef'], third_config['applicationRef'])
        self.assertNotEqual(first_config['connectionRefs'], third_config['connectionRefs'])

    def test_concurrent_reservations_have_one_active_turn_and_duplicate_is_read_only(self):
        barrier = Barrier(2)
        def reserve(index):
            barrier.wait(timeout=5)
            try:
                return self.service._reserve('alice', self.identifier,
                    SessionText(requestId=f'concurrent-turn-{index}', text='Original instruction'))
            except HTTPException as error:
                return error
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (1, 2)))
        self.assertEqual(sum(isinstance(item, tuple) for item in results), 1)
        failure = next(item for item in results if isinstance(item, HTTPException))
        self.assertEqual(failure.detail['code'], 'RESEARCH_TURN_ACTIVE_OR_UNCONFIRMED')
        detail = self.read()
        turn = detail['turns'][0]
        repeated, fresh = self.service._reserve('alice', self.identifier,
            SessionText(requestId=turn['requestId'], text='Original instruction'))
        self.assertFalse(fresh)
        self.assertEqual(repeated, turn['id'])
        self.assertIsNone(turn['taskId'])

    def test_stopped_reservation_prevents_model_and_tool_before_dispatch(self):
        _, task = self.reserved()
        with self.service.db.write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            self.service._save_session(conn, row, {**row['body'], 'stopped': True})
        with self.assertRaises(RunCancelledException):
            self.before([Message(role='user', content='original')])
        with self.assertRaises(RunCancelledException):
            self.service.authorize_tool(self.context, 'research_run')
        self.assertEqual(self.store.effects(task['id']), [])

    def test_same_reserved_request_cannot_admit_changed_context_or_model_connection(self):
        other = self.store.personal_models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic-other'}, 'configure-conflicting-model')
        alterations = (
            lambda start: start.model_copy(update={'inputValues': {**start.inputValues, 'sessionContext': 'Different research boundary'}}),
            lambda start: start.model_copy(update={'connectionRefs': {'model': other['connectionRef']}}))
        for index, alteration in enumerate(alterations):
            if index:
                self.identifier = self.service.create('alice', self.create.model_copy(update={'requestId': 'payload-second-session'}))
            self.reserved(request=f'payload-reservation-{index}', alter_start=alteration)
            with self.assertRaisesRegex(PermissionError, 'RESEARCH_SESSION_ADMISSION_PAYLOAD_MISMATCH'):
                self.before([Message(role='user', content='unchanged turn ID')])
            with self.assertRaisesRegex(PermissionError, 'RESEARCH_SESSION_ADMISSION_PAYLOAD_MISMATCH'):
                self.service.authorize_tool(self.context, 'research_run')

    def test_stop_of_reserved_not_dispatched_turn_is_safe_and_never_submitted_by_read(self):
        request = SessionText(requestId='reserved-before-stop', text='Original instruction')
        turn_id, _ = self.service._reserve('alice', self.identifier, request)
        stopped = asyncio.run(self.service.stop('alice', self.identifier,
            SessionCommand(requestId='stop-before-dispatch')))
        self.assertEqual(stopped['state'], 'stopped')
        self.assertEqual(stopped['turns'][0]['status'], 'canceled')
        self.assertIsNone(stopped['turns'][0]['taskId'])
        with patch.object(self.service.runs, 'start', side_effect=AssertionError('No original request replay')):
            repeated = asyncio.run(self.service.turn('alice', self.identifier, request))
            original = asyncio.run(self.service.request('alice', request.requestId))
        self.assertEqual(repeated['turns'][0]['id'], turn_id)
        self.assertEqual(original['turnId'], turn_id)
        self.assertIn('start', stopped['allowedActions'])

    def test_correction_is_persisted_once_included_at_request_and_carries_to_next_turn(self):
        turn_id, task = self.reserved()
        messages = [Message(role='user', content='original')]
        self.before(messages)
        correction = SessionText(requestId='correct-original', text='Do not change the public signature')
        self.service.correct('alice', self.identifier, correction)
        self.service.correct('alice', self.identifier, correction)
        with self.service.db.read() as conn:
            original = self.service._turns(conn, self.identifier)[0]
        self.assertEqual(original['body']['messages'][-1]['state'], 'pending')
        # Simulate a positively ended original run while retaining the correction
        # received after its final provider request; no fake model is called.
        with self.store.transaction():
            self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
        with self.service.db.write() as conn:
            body = deepcopy(original['body'])
            body.update(terminal=True, status='completed', result='Observed first result', completedAt='synthetic-final')
            self.service._save_turn(conn, original, body)
        _, second_task = self.reserved('turn-second', 'Continue with the result')
        with self.service.db.read() as conn:
            second = self.service._turns(conn, self.identifier)[1]
        self.assertIn(correction.text, second['body']['context'])
        self.assertIn('Observed first result', second['body']['context'])
        self.before([Message(role='user', content=second['body']['context'])])
        with self.service.db.read() as conn:
            original = self.service._turns(conn, self.identifier)[0]
        self.assertEqual(original['id'], turn_id)
        self.assertEqual(original['body']['messages'][-1]['state'], 'included')
        self.assertNotEqual(task['id'], second_task['id'])

    def test_unknown_and_done_with_new_queue_attempt_both_freeze_before_model(self):
        _, task = self.reserved()
        self.store.effect_reserve(self.context.run_id, 'research-session-tool:write-once', {'synthetic': True})
        with self.assertRaises(StopAgentRun):
            self.before([Message(role='user', content='original')])
        with self.service.db.write() as conn:
            turn = self.service._turns(conn, self.identifier)[0]
            self.service._save_turn(conn, turn, {**turn['body'], 'blockReason': None})
        self.store.effect_complete(self.context.run_id, 'research-session-tool:write-once',
            {'outcome': 'completed', 'output': {'synthetic': True}})
        with self.assertRaises(StopAgentRun):
            self.before([Message(role='user', content='original')], {**self.ticket, 'attempt': 2})
        with self.service.db.read() as conn:
            turn = self.service._turns(conn, self.identifier)[0]
        self.assertEqual(turn['body']['blockReason'], 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')
        self.assertEqual(self.store.effects(task['id'])[0]['status'], 'DONE')
        with self.assertRaises(HTTPException):
            self.service._reserve('alice', self.identifier, SessionText(requestId='blocked-new-turn', text='Continue'))

    def test_shared_source_is_available_then_revocation_blocks_existing_context(self):
        self.reserved()
        source = self.service.content.publish('bob', ContentPublication(
            source={'application': 'research', 'record': 'synthetic-publication', 'revision': '1'},
            content={'finding': 'synthetic observation'}, visibility='team'), 'publish-shared-source')
        self.service.record_source(self.context, source['id'])
        self.before([Message(role='user', content='original')])
        self.service.content.set_visibility('bob', source['id'], 'personal', 'withdraw-shared-source')
        with self.assertRaises(HTTPException) as error:
            self.before([Message(role='user', content='original')])
        self.assertEqual(error.exception.detail['code'], 'RESEARCH_SOURCE_UNAVAILABLE')

    def test_context_capacity_rejects_without_new_task_or_silent_truncation(self):
        with self.service.db.write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            self.service._save_session(conn, row, {**row['body'], 'boundaries': 'b' * 12000})
        with self.assertRaises(HTTPException) as error:
            self.service._reserve('alice', self.identifier, SessionText(requestId='oversized-context', text='Continue'))
        self.assertEqual(error.exception.detail['code'], 'RESEARCH_CONTEXT_LIMIT')
        with self.service.db.read() as conn:
            self.assertEqual(self.service._turns(conn, self.identifier), [])
            self.assertEqual(self.service._row(conn, 'alice', self.identifier)['body']['boundaries'], 'b' * 12000)


if __name__ == '__main__':
    unittest.main()

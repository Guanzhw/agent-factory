"""Real PG conversation/admission contracts; synthetic run identities, no model IO.

These tests do not claim native queue crash recovery or live model integration.
The separate runtime/browser acceptance exercises those boundaries.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from unittest.mock import AsyncMock, patch
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
        self.tools = ResearchSessionTools(workspace_root=Path(directory) / 'coding', host_commands=True,
            command_path=str(Path(sys.executable).parent))
        app = create_app(Settings(db_url=isolated.url, workspace=Path(directory) / 'factory'), session_tools=self.tools)
        state = factory_state(app)
        self.state = state
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
        with self.service.db.write() as conn:
            self.service._save_turn(conn, turn, {**turn['body'], 'dispatchStarted': True})
        self.context = RunContext(run_id=run_id, session_id=task['id'], user_id='alice', session_state={})
        self.ticket = {'id': run_id, 'session_id': task['id'], 'user_id': 'alice', 'attempt': 1, 'status': 'running'}
        return turn_id, task

    def before(self, messages, ticket=None):
        with patch.object(self.service.runs.factory.bridge.native_db, 'get_job', return_value=ticket or self.ticket):
            self.service.before_model(self.context, messages, lambda: self.fail('Unexpected auxiliary model request'))

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

    def test_new_session_uses_configured_timeout_without_rewriting_old_session(self):
        self.store.settings.experiment_timeout_seconds = 60
        option = self.service.options('alice')['limits']['operationSeconds']
        self.assertEqual(option, {'min': 1, 'max': 60, 'default': 60})
        longer = self.service.create('alice', self.create.model_copy(update={
            'requestId': 'create-longer-session',
            'limits': SessionLimits(maxTurns=4, toolCallsPerTurn=4, operationSeconds=option['default'])}))
        self.assertEqual(asyncio.run(self.service.read('alice', longer))['limits']['operationSeconds'], 60)
        self.assertEqual(self.read()['limits']['operationSeconds'], 5)
        with self.service.db.read() as conn:
            configuration = self.service._row(conn, 'alice', longer)['body']['configuration']
        self.assertEqual(configuration['budget']['operationSeconds'], 60)

    def test_new_tool_default_preserves_existing_plan_and_explicit_lower_budget(self):
        _, original_task = self.reserved()
        original_plan = deepcopy(self.store.plan(original_task['plan_id'], 'alice'))
        self.store.settings.max_tool_calls = 32
        option = self.service.options('alice')['limits']['toolCallsPerTurn']
        self.assertEqual(option, {'min': 1, 'max': 32, 'default': 32})
        wider = self.service.create('alice', self.create.model_copy(update={
            'requestId': 'create-wider-tool-session',
            'limits': SessionLimits(maxTurns=4, toolCallsPerTurn=option['default'], operationSeconds=5)}))
        explicit = self.service.create('alice', self.create.model_copy(update={'requestId': 'create-explicit-tool-session'}))
        self.assertEqual(asyncio.run(self.service.read('alice', wider))['limits']['toolCallsPerTurn'], 32)
        self.assertEqual(asyncio.run(self.service.read('alice', explicit))['limits']['toolCallsPerTurn'], 4)
        self.assertEqual(self.read()['limits']['toolCallsPerTurn'], 4)
        with self.service.db.read() as conn:
            old_config = self.service._row(conn, 'alice', self.identifier)['body']['configuration']
            explicit_config = self.service._row(conn, 'alice', explicit)['body']['configuration']
            wider_config = self.service._row(conn, 'alice', wider)['body']['configuration']
        self.assertEqual(old_config, explicit_config)
        self.assertEqual(wider_config['budget']['toolCalls'], 32)
        self.assertEqual(self.store.plan(original_task['plan_id'], 'alice'), original_plan)
        self.identifier = wider
        _, wider_task = self.reserved('turn-wider-tool-budget')
        self.assertEqual(self.store.plan(wider_task['plan_id'], 'alice')['budget']['toolCalls'], 32)

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

    def finish_original(self, task, turn_id):
        self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
        with self.service.db.write() as conn:
            turn = conn.execute(select(self.service.turns).where(self.service.turns.c.id == turn_id)).mappings().one()
            self.service._save_turn(conn, turn, {**turn['body'], 'terminal': True, 'status': 'completed',
                'result': 'Original completed result', 'completedAt': 'synthetic-final'})

    def test_delayed_stop_keeps_original_turn_binding_after_explicit_new_turn(self):
        old_turn, old_task = self.reserved()
        self.finish_original(old_task, old_turn)
        original_cancel = self.service._cancel_original

        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            async def delayed(*args):
                entered.set()
                await release.wait()
                await original_cancel(*args)
            with patch.object(self.service, '_cancel_original', side_effect=delayed), \
                    patch.object(self.service.runs.factory.commands, 'submit', new_callable=AsyncMock) as submit:
                pending = asyncio.create_task(self.service.stop('alice', self.identifier,
                    SessionCommand(requestId='old-stop-delayed')))
                await asyncio.wait_for(entered.wait(), 5)
                new_turn, new_task = self.reserved('new-turn-after-old-stop', 'Explicitly continue')
                release.set()
                await asyncio.wait_for(pending, 5)
                self.assertEqual(submit.await_count, 0, 'Old completed stop must never cancel the new task')
                self.assertFalse(self.store.task(new_task['id'])['cancel_requested'])
                with self.service.db.read() as conn:
                    command = conn.execute(select(self.service.commands.c.result).where(
                        self.service.commands.c.request_id == 'old-stop-delayed')).scalar_one()
                    row = self.service._row(conn, 'alice', self.identifier)
                self.assertEqual(command['turnId'], old_turn)
                self.assertNotEqual(command['turnId'], new_turn)
                self.assertFalse(row['body']['stopped'])
                # Re-reading or repeating the old command cannot retarget it.
                await self.service.stop('alice', self.identifier, SessionCommand(requestId='old-stop-delayed'))
                self.assertFalse(self.store.task(new_task['id'])['cancel_requested'])
        asyncio.run(scenario())

    def test_late_old_task_cancel_does_not_stop_new_turn_but_current_cancel_does(self):
        old_turn, old_task = self.reserved()
        self.finish_original(old_task, old_turn)
        _, new_task = self.reserved('new-turn-before-late-hook', 'Continue after completed result')
        self.store.request_cancel(old_task['id'])
        with self.service.db.read() as conn:
            self.assertFalse(self.service._row(conn, 'alice', self.identifier)['body']['stopped'])
        self.assertFalse(self.store.task(new_task['id'])['cancel_requested'])
        self.before([Message(role='user', content='Current turn remains usable')])
        self.store.request_cancel(new_task['id'])
        with self.service.db.read() as conn:
            self.assertTrue(self.service._row(conn, 'alice', self.identifier)['body']['stopped'])
        with self.assertRaises(RunCancelledException):
            self.before([Message(role='user', content='Current turn must stop')])
        with self.assertRaises(RunCancelledException):
            self.service.authorize_tool(self.context, 'research_run')

    def test_old_creator_cannot_dispatch_after_stop_and_new_reservation(self):
        reserved, release = Event(), Event()
        reserve_original = self.service._reserve
        def delayed_reserve(*args):
            value = reserve_original(*args)
            reserved.set()
            if not release.wait(5):
                raise AssertionError('The synthetic delayed creator was not released')
            return value

        async def scenario():
            with patch.object(self.service, '_reserve', side_effect=delayed_reserve), \
                    patch.object(self.service.runs, 'start', new_callable=AsyncMock) as start:
                pending = asyncio.create_task(self.service.turn('alice', self.identifier,
                    SessionText(requestId='old-delayed-creator', text='Old instruction')))
                try:
                    self.assertTrue(await asyncio.to_thread(reserved.wait, 5))
                    await self.service.stop('alice', self.identifier, SessionCommand(requestId='stop-old-reservation'))
                    new_id, fresh = reserve_original('alice', self.identifier,
                        SessionText(requestId='new-explicit-reservation', text='New instruction'))
                    self.assertTrue(fresh)
                finally:
                    release.set()
                await asyncio.wait_for(pending, 5)
                self.assertEqual(start.await_count, 0)
                with self.service.db.read() as conn:
                    turns = self.service._turns(conn, self.identifier)
                    row = self.service._row(conn, 'alice', self.identifier)
                self.assertTrue(turns[0]['body']['neverDispatched'])
                self.assertEqual(turns[-1]['id'], new_id)
                self.assertEqual(turns[-1]['body']['status'], 'reserved')
                self.assertFalse(row['body']['stopped'])
        asyncio.run(scenario())

    def observed_detail(self, task, status):
        return {'job': {'status': status}, 'events': [], 'snapshot': {
            'run_id': self.context.run_id, 'session_id': task['id'], 'user_id': 'alice', 'effects': [],
            'status': status.upper(),
            'messages': [{'role': 'assistant', 'content': 'Observed final reply'}], 'content': 'Observed final reply'}}

    def test_stale_running_observation_cannot_cache_terminal_or_admit_without_result(self):
        _, task = self.reserved()
        self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
        with patch.object(self.service.runs.factory, 'detail', new_callable=AsyncMock,
                side_effect=[self.observed_detail(task, 'running'), self.observed_detail(task, 'completed')]) as detail:
            asyncio.run(self.service._refresh('alice', self.identifier))
            with self.service.db.read() as conn:
                turn = self.service._turns(conn, self.identifier)[0]
            self.assertFalse(turn['body']['terminal'])
            self.assertFalse(self.service._safe('alice', turn))
            self.assertIsNone(turn['body']['result'])
            asyncio.run(self.service._refresh('alice', self.identifier))
            self.assertEqual(detail.await_count, 2)
        with self.service.db.read() as conn:
            turn = self.service._turns(conn, self.identifier)[0]
        self.assertTrue(turn['body']['terminal'])
        self.assertEqual(turn['body']['result'], 'Observed final reply')
        self.assertTrue(self.service._safe('alice', turn))

    def test_concurrent_stale_refresh_cannot_overwrite_confirmed_final_result(self):
        _, task = self.reserved()
        self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            calls = 0
            async def detail(_):
                nonlocal calls
                calls += 1
                if calls == 1:
                    entered.set()
                    await release.wait()
                    return self.observed_detail(task, 'running')
                return self.observed_detail(task, 'completed')
            with patch.object(self.service.runs.factory, 'detail', side_effect=detail):
                old = asyncio.create_task(self.service._refresh('alice', self.identifier))
                await asyncio.wait_for(entered.wait(), 5)
                await self.service._refresh('alice', self.identifier)
                release.set()
                await asyncio.wait_for(old, 5)
            self.assertEqual(calls, 2)
        asyncio.run(scenario())
        with self.service.db.read() as conn:
            turn = self.service._turns(conn, self.identifier)[0]
        self.assertEqual(turn['body']['status'], 'completed')
        self.assertTrue(turn['body']['terminal'])
        self.assertEqual(turn['body']['result'], 'Observed final reply')

    def test_confirmed_failure_or_cancel_can_continue_without_fabricated_answer(self):
        for index, status in enumerate(('failed', 'canceled')):
            if index:
                self.identifier = self.service.create('alice', self.create.model_copy(update={'requestId': 'canceled-session'}))
            _, task = self.reserved(request=f'ended-turn-{index}')
            self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
            observation = self.observed_detail(task, status)
            observation['snapshot']['content'] = 'This is an error, not an assistant answer'
            with patch.object(self.service.runs.factory, 'detail', new_callable=AsyncMock, return_value=observation):
                asyncio.run(self.service._refresh('alice', self.identifier))
            with self.service.db.read() as conn:
                turn = self.service._turns(conn, self.identifier)[0]
            self.assertTrue(turn['body']['terminal'])
            self.assertIsNone(turn['body']['result'])
            self.assertTrue(self.service._safe('alice', turn))
            _, fresh = self.service._reserve('alice', self.identifier,
                SessionText(requestId=f'explicit-after-{status}', text='Explicitly continue'))
            self.assertTrue(fresh)

    def test_lost_late_start_ack_cannot_overwrite_already_observed_final_reply(self):
        async def accepted_then_lost(owner, start):
            plan, key = ApplicationRuns._prepare(self.service.runs, owner, start)
            task, _ = self.store.reserve_task(plan, key)
            run_id = str(uuid4())
            self.store.accept(task['id'], run_id)
            self.context = RunContext(run_id=run_id, session_id=task['id'], user_id=owner, session_state={})
            self.store.sql('UPDATE af_tasks SET terminal=TRUE WHERE id=:id', id=task['id'])
            with patch.object(self.service.runs.factory, 'detail', new_callable=AsyncMock,
                    return_value=self.observed_detail(task, 'completed')):
                await self.service._refresh(owner, self.identifier)
            raise RuntimeError('Synthetic late loss of the original submission acknowledgement')
        with patch.object(self.service.runs, 'start', side_effect=accepted_then_lost) as start:
            detail = asyncio.run(self.service.turn('alice', self.identifier,
                SessionText(requestId='late-submission-ack', text='Original instruction')))
        self.assertEqual(start.await_count, 1)
        self.assertEqual(detail['state'], 'idle')
        self.assertEqual(detail['turns'][0]['status'], 'completed')
        self.assertEqual(detail['turns'][0]['result'], 'Observed final reply')
        self.assertIsNone(detail['turns'][0]['failure'])

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

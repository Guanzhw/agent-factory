"""Real isolated PG memory/effect contracts; scripted native lifecycle, no model IO.

The separate service-exit acceptance proves worker restart, rather than these
synthetic terminal observations.
"""
import asyncio
from copy import deepcopy
import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.db.schemas import UserMemory
from agno.exceptions import RunCancelledException, StopAgentRun
from agno.models.message import Message
from agno.tools.function import FunctionCall

from agent_factory.execution_bindings import BindingContext
from research.session_memory import ResearchSessionMemory
from research.session_tools import EFFECT_PREFIX
import test_research_sessions as fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class PersonalMemoryPostgresTests(unittest.TestCase):
    read = fixture.ResearchSessionContracts.read
    before = fixture.ResearchSessionContracts.before
    finish_original = fixture.ResearchSessionContracts.finish_original

    def setUp(self):
        fixture.ResearchSessionContracts.setUp(self)
        self.sequence = 0

    def reserved(self, *args, **kwargs):
        turn_id, task = fixture.ResearchSessionContracts.reserved(self, *args, **kwargs)
        return turn_id, self.store.task(task['id'])

    def call(self, name, arguments, call_id=None):
        self.sequence += 1
        task = self.store.task(self.context.session_id, self.context.user_id)
        plan = self.store.plan(task['plan_id'], self.context.user_id)
        binding = BindingContext(None, self.store, plan, self.context, {})
        registration = next(item for item in self.tools.tool_registrations if item.tool_name == name)
        function = registration.factory(binding)
        function._run_context = self.context
        return FunctionCall(function=function, arguments=arguments, call_id=call_id or f'pg-call-{self.sequence}')

    def invoke(self, name, arguments, call_id=None):
        call = self.call(name, arguments, call_id)
        result = asyncio.run(call.aexecute())
        self.assertEqual(result.status, 'success', result.error)
        return call.result

    def turn(self):
        with self.service.db.read() as conn:
            return self.service._turns(conn, self.identifier)[-1]

    def observation(self, task, *, native='error', queue='failed', view='finalizing'):
        return {'job': {'status': view}, 'events': self.store.events(task['id']), 'snapshot': {
            'run_id': task['run_id'], 'session_id': task['id'], 'user_id': 'alice', 'status': native,
            'queue': {'id': task['run_id'], 'session_id': task['id'], 'user_id': 'alice', 'status': queue},
            'effects': self.store.effects(task['id'])}}

    def refresh(self, task, **values):
        with patch.object(self.service.runs.factory, 'detail', new_callable=AsyncMock,
                side_effect=lambda _: self.observation(task, **values)):
            return self.read()

    def lose_receipt(self, *, call_id='lost-receipt'):
        with patch.object(self.store, 'effect_complete', side_effect=ConnectionError('synthetic lost receipt')):
            with self.assertRaises(StopAgentRun):
                self.invoke('research_remember', {'memory': 'Use unittest before reporting results.'}, call_id)
        return self.store.native_db.get_user_memories(user_id='alice')[0]

    def restart_guard(self):
        with self.assertRaises(StopAgentRun):
            self.before([Message(role='user', content='Synthetic original retry')],
                ticket={**self.ticket, 'attempt': 2})
        self.assertEqual(self.turn()['body']['blockReason'], 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')

    def test_native_preferences_reopen_and_new_session_update_forget(self):
        self.assertTrue(self.read()['capabilities']['memory'])
        turn_id, task = self.reserved()
        command = self.invoke('research_remember', {'memory': 'Run python -m unittest discover.'})['memory']
        self.invoke('research_remember', {'memory': 'State reproducible experiments first.'})
        self.finish_original(task, turn_id)
        reopened = PostgresDb(db_url=self.store.native_db.db_engine.url.render_as_string(hide_password=False))
        self.addCleanup(reopened.db_engine.dispose)
        self.service.memory = ResearchSessionMemory(self.service)
        self.service.memory.db = reopened
        self.identifier = self.service.create('alice', self.create.model_copy(update={'requestId': 'new-memory-session'}))
        self.reserved(request='new-memory-turn')
        found = self.invoke('research_find_memories', {'query': 'unittest'})
        self.assertEqual(found['memories'][0]['id'], command['id'])
        changed = self.invoke('research_update_memory', {'memory_id': command['id'], 'memory': 'Run python -m pytest -q.'})
        self.assertEqual(changed['previousText'], command['text'])
        self.assertEqual(changed['memory']['id'], command['id'])
        removed = self.invoke('research_forget_memory', {'memory_id': command['id']})
        self.assertEqual(removed['memory']['text'], 'Run python -m pytest -q.')
        self.assertEqual(self.invoke('research_find_memories', {'query': 'pytest'})['total'], 0)
        self.assertEqual(self.invoke('research_find_memories', {})['total'], 1)

    def test_foreign_id_and_disabled_owner_cannot_mutate_memory(self):
        self.reserved()
        identifier = str(uuid4())
        self.store.native_db.upsert_user_memory(UserMemory(memory_id=identifier, user_id='bob', memory='Bob private preference.'))
        self.assertEqual(self.invoke('research_find_memories', {})['total'], 0)
        for name, arguments in [('research_update_memory', {'memory_id': identifier, 'memory': 'Wrong owner.'}),
                ('research_forget_memory', {'memory_id': identifier})]:
            self.assertEqual(self.invoke(name, arguments)['code'], 'RESEARCH_MEMORY_NOT_FOUND')
        self.assertEqual(self.store.effects(self.context.session_id), [])
        self.assertEqual(self.store.native_db.get_user_memory(identifier, user_id='bob').memory, 'Bob private preference.')
        self.state['auth'].directory.set_disabled('alice', True)
        with patch.object(self.store.native_db, 'upsert_user_memory') as write:
            result = asyncio.run(self.call('research_remember', {'memory': 'No write.'}).aexecute())
            self.assertEqual(result.status, 'failure')
        write.assert_not_called()

    def test_same_call_and_changed_payload_never_create_replacement_memory(self):
        self.reserved()
        with patch.object(self.store.native_db, 'upsert_user_memory', wraps=self.store.native_db.upsert_user_memory) as write:
            first = self.invoke('research_remember', {'memory': 'One preference.'}, 'original')
            self.assertEqual(self.invoke('research_remember', {'memory': 'One preference.'}, 'original'), first)
            rejected = self.invoke('research_remember', {'memory': 'Changed payload.'}, 'original')
        self.assertEqual(write.call_count, 1)
        self.assertEqual(rejected['code'], 'RESEARCH_MEMORY_REQUEST_CONFLICT')
        self.assertEqual(len(self.store.native_db.get_user_memories(user_id='alice')), 1)

    def test_write_before_receipt_only_observes_original_id_then_native_lifecycle_releases(self):
        _, task = self.reserved()
        memory = self.lose_receipt()
        self.restart_guard()
        with patch.object(self.store.native_db, 'upsert_user_memory', side_effect=AssertionError('No replay')):
            view = self.refresh(task)
        self.assertEqual(self.store.native_db.get_user_memory(memory.memory_id, user_id='alice').memory, memory.memory)
        self.assertEqual(self.store.effects(task['id'])[0]['status'], 'DONE')
        self.assertIsNone(self.turn()['body']['blockReason'])
        self.assertFalse(self.store.task(task['id'])['terminal'], 'Memory observation must not mark the native task terminal')
        self.assertNotIn('start', view['allowedActions'])
        self.store.observed(task, 'failed', True)
        self.assertTrue(self.store.task(task['id'])['terminal'])
        view = self.refresh(task, view='failed')
        self.assertIn('start', view['allowedActions'])

    def test_later_change_is_not_replayed_and_unknown_command_stays_blocking(self):
        _, task = self.reserved()
        memory = self.lose_receipt()
        self.store.native_db.upsert_user_memory(UserMemory(memory_id=memory.memory_id, user_id='alice',
            memory='A later preference.', input='synthetic later authorized operation'))
        self.restart_guard()
        self.refresh(task)
        self.assertEqual(self.store.effects(task['id'])[0]['status'], 'UNKNOWN')
        self.assertIsNotNone(self.turn()['body']['blockReason'])
        self.assertEqual(self.store.native_db.get_user_memory(memory.memory_id, user_id='alice').memory, 'A later preference.')

    def test_confirmed_memory_does_not_clear_other_unknown_or_live_native_custody(self):
        _, task = self.reserved()
        self.lose_receipt()
        self.store.effect_reserve(task['run_id'], EFFECT_PREFIX + 'unknown-command', {'syntheticCommand': True})
        self.restart_guard()
        self.refresh(task)
        effects = self.store.effects(task['id'])
        self.assertCountEqual([item['status'] for item in effects], ['DONE', 'UNKNOWN'])
        self.assertIsNotNone(self.turn()['body']['blockReason'])
        self.store.effect_complete(task['run_id'], EFFECT_PREFIX + 'unknown-command', {'outcome': 'completed', 'output': {}})
        self.refresh(task, native='running', queue='running')
        self.assertIsNotNone(self.turn()['body']['blockReason'])

    def test_ordinary_retry_has_no_memory_reconciliation_proof(self):
        _, task = self.reserved()
        self.store.effect_reserve(task['run_id'], EFFECT_PREFIX + 'completed-command', {'syntheticCommand': True})
        self.store.effect_complete(task['run_id'], EFFECT_PREFIX + 'completed-command', {'outcome': 'completed', 'output': {}})
        self.restart_guard()
        self.refresh(task)
        self.assertEqual(self.turn()['body']['blockReason'], 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')

    def test_completed_memory_before_final_reply_can_be_verified_without_reexecution(self):
        _, task = self.reserved()
        memory = self.invoke('research_remember', {'memory': 'Confirmed before the final reply.'})['memory']
        self.restart_guard()
        with patch.object(self.store.native_db, 'upsert_user_memory', side_effect=AssertionError('No replay')):
            self.refresh(task)
        self.assertEqual(self.store.native_db.get_user_memory(memory['id'], user_id='alice').memory, memory['text'])
        self.assertIsNone(self.turn()['body']['blockReason'])

    def test_completed_memory_does_not_release_mixed_command_restart(self):
        _, task = self.reserved()
        self.invoke('research_remember', {'memory': 'Confirmed preference.'})
        self.store.effect_reserve(task['run_id'], EFFECT_PREFIX + 'original-command', {'syntheticCommand': True})
        self.store.effect_complete(task['run_id'], EFFECT_PREFIX + 'original-command', {'outcome': 'completed', 'output': {}})
        self.restart_guard()
        self.refresh(task)
        self.assertEqual(self.turn()['body']['blockReason'], 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')

    def test_memory_intent_cannot_complete_unknown_command_with_same_call_id(self):
        _, task = self.reserved()
        memory = self.invoke('research_remember', {'memory': 'Only this memory.'})['memory']
        self.store.effect_reserve(task['run_id'], EFFECT_PREFIX + 'collision', {
            'ownerId': 'alice', 'taskId': task['id'], 'sessionId': self.identifier,
            'turnId': self.turn()['id'], 'toolName': 'research_run', 'callId': 'collision',
            'arguments': {'argv': ['unknown-command']}})
        with self.assertRaises(StopAgentRun):
            self.invoke('research_forget_memory', {'memory_id': memory['id']}, 'collision')
        self.store.native_db.delete_user_memory(memory['id'], user_id='alice')
        self.refresh(task)
        original = next(item for item in self.store.effects(task['id']) if item['effect_key'].endswith(':collision'))
        self.assertEqual(original['status'], 'UNKNOWN')
        self.assertIsNone(original['result'])

    def test_unproven_memory_intent_does_not_hide_completed_command_from_restart_guard(self):
        _, task = self.reserved()
        memory = self.invoke('research_remember', {'memory': 'Keep this preference.'})['memory']
        self.store.effect_reserve(task['run_id'], EFFECT_PREFIX + 'collision', {
            'ownerId': 'alice', 'taskId': task['id'], 'sessionId': self.identifier,
            'turnId': self.turn()['id'], 'toolName': 'research_run', 'callId': 'collision',
            'arguments': {'argv': ['confirmed-command']}})
        self.store.effect_complete(task['run_id'], EFFECT_PREFIX + 'collision', {'outcome': 'completed', 'output': {}})
        with self.assertRaises(StopAgentRun):
            self.invoke('research_forget_memory', {'memory_id': memory['id']}, 'collision')
        self.restart_guard()
        self.refresh(task)
        self.assertEqual(self.turn()['body']['blockReason'], 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')
        original = next(item for item in self.store.effects(task['id']) if item['effect_key'].endswith(':collision'))
        self.assertNotIn('reconciled', original['result'])

    def test_wrong_native_owner_does_not_release_verified_memory_hold(self):
        _, task = self.reserved()
        self.lose_receipt()
        self.restart_guard()
        def wrong_owner(_):
            value = self.observation(task)
            value['snapshot']['queue']['user_id'] = 'bob'
            return value
        with patch.object(self.service.runs.factory, 'detail', new_callable=AsyncMock, side_effect=wrong_owner):
            self.read()
        self.assertEqual(self.store.effects(task['id'])[0]['status'], 'DONE')
        self.assertEqual(self.turn()['body']['blockReason'], 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')

    def test_pg_error_and_stop_do_not_report_saved(self):
        _, task = self.reserved()
        with patch.object(self.store.native_db, 'upsert_user_memory', side_effect=ConnectionError('synthetic DB failed')):
            with self.assertRaises(StopAgentRun):
                self.invoke('research_remember', {'memory': 'Not saved.'})
        self.refresh(task)
        self.assertEqual(self.store.effects(task['id'])[0]['status'], 'UNKNOWN')
        self.assertEqual(self.store.native_db.get_user_memories(user_id='alice'), [])
        self.store.request_cancel(task['id'])
        with patch.object(self.store.native_db, 'upsert_user_memory') as write:
            with self.assertRaises(RunCancelledException):
                self.invoke('research_remember', {'memory': 'After stop.'})
        write.assert_not_called()

    def test_old_binding_capability_is_not_silently_upgraded(self):
        with self.service._write() as conn:
            row = self.service._row(conn, 'alice', self.identifier)
            body = deepcopy(row['body'])
            body['configuration'].pop('personalMemory')
            self.service._save_session(conn, row, body)
        self.assertFalse(self.read()['capabilities']['memory'])

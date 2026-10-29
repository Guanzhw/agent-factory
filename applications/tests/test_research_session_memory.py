"""Native SQLite memory CRUD and Agno tools; scripted authority, no model or PG claims."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agno.db.sqlite import SqliteDb
from agno.exceptions import RunCancelledException, StopAgentRun
from agno.run import RunContext
from agno.tools.function import FunctionCall

from agent_factory.execution_bindings import BindingContext
from research.session_memory import ResearchSessionMemory
from research.session_tools import EFFECT_PREFIX, ResearchSessionTools
import test_research_session_tools as fixture


class Sessions(fixture.Sessions):
    def __init__(self, store, turns=None):
        super().__init__()
        self.store, self.turns = store, turns if turns is not None else {}
        self.memory = ResearchSessionMemory(self)

    def _write(self):
        return nullcontext(None)

    def _execution(self, conn, context):
        self.authorize_tool(context, 'research_remember')
        return None, {'id': context.run_id, 'body': deepcopy(self.turns.setdefault(context.run_id, {}))}, None

    def _save_turn(self, conn, turn, body):
        self.turns[turn['id']] = deepcopy(body)


class Store(fixture.Store):
    def sql(self, query, **values):
        effect = self.receipts.get(values['key'])
        return [{'fingerprint': effect['fingerprint']}] if effect and effect['taskId'] == values['task'] else []


class PersonalMemoryToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.db_file = str(Path(self.directory) / 'memory.db')
        self.store = Store()
        self.store.native_db = SqliteDb(db_file=self.db_file)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.sessions = Sessions(self.store)
        self.tools = ResearchSessionTools()
        self.tools.bind(self.sessions, None)
        self.sequence = 0

    def call(self, name, values, *, owner='alice', run_id=None, call_id=None):
        self.sequence += 1
        task_id = 'task-' + owner + ('-second' if run_id and run_id.endswith('-second') else '')
        ctx = RunContext(user_id=owner, session_id=task_id,
            run_id=run_id or 'run-' + owner, session_state={})
        binding = BindingContext(None, self.store, {'budget': {'outputBytes': 65536}}, ctx, {})
        registration = next(item for item in self.tools.tool_registrations if item.tool_name == name)
        function = registration.factory(binding)
        function._run_context = ctx
        return FunctionCall(function=function, arguments=values, call_id=call_id or 'call-' + str(self.sequence))

    async def invoke(self, name, values, **kwargs):
        call = self.call(name, values, **kwargs)
        result = await call.aexecute()
        self.assertEqual(result.status, 'success', result.error)
        return call.result

    def observe_original(self):
        self.sessions.memory.observe('alice', {'id': 'turn-alice', 'session_id': 'session-alice',
            'body': self.sessions.turns['run-alice']}, {'id': 'task-alice', 'run_id': 'run-alice'}, EFFECT_PREFIX)

    async def test_owner_preferences_survive_reopen_and_new_session_correct_and_forget(self):
        command = await self.invoke('research_remember', {'memory': 'Run python -m unittest discover.'})
        await self.invoke('research_remember', {'memory': 'Put reproducible experiments first.'})
        self.store.native_db.db_engine.dispose()
        self.store.native_db = SqliteDb(db_file=self.db_file)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.sessions.memory = ResearchSessionMemory(self.sessions)
        found = await self.invoke('research_find_memories', {'query': 'unittest'}, run_id='run-alice-second')
        self.assertEqual(found['memories'][0]['id'], command['memory']['id'])
        changed = await self.invoke('research_update_memory', {'memory_id': command['memory']['id'],
            'memory': 'Run python -m pytest -q.'}, run_id='run-alice-second')
        self.assertEqual(changed['memory']['id'], command['memory']['id'])
        self.assertEqual(changed['previousText'], 'Run python -m unittest discover.')
        self.assertEqual((await self.invoke('research_find_memories', {'query': 'unittest'}))['total'], 0)
        removed = await self.invoke('research_forget_memory', {'memory_id': command['memory']['id']})
        self.assertEqual(removed['memory']['text'], 'Run python -m pytest -q.')
        self.assertIn('旧会话', removed['notice'])
        found = await self.invoke('research_find_memories', {}, run_id='run-alice-second')
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['memories'][0]['text'], 'Put reproducible experiments first.')

    async def test_known_other_owner_id_cannot_read_update_or_forget_and_bad_arguments_are_recoverable(self):
        memory = (await self.invoke('research_remember', {'memory': 'Alice preference.'}))['memory']
        self.assertEqual((await self.invoke('research_find_memories', {}, owner='bob'))['memories'], [])
        for tool, values in [('research_update_memory', {'memory_id': memory['id'], 'memory': 'Stolen'}),
                             ('research_forget_memory', {'memory_id': memory['id']})]:
            result = await self.invoke(tool, values, owner='bob')
            self.assertEqual(result['code'], 'RESEARCH_MEMORY_NOT_FOUND')
        rejected = await self.invoke('research_remember', {'memory': 'No owner override', 'owner': 'alice'}, owner='bob')
        self.assertEqual(rejected['code'], 'PERSONAL_TOOL_INPUT_INVALID')
        self.assertEqual(self.store.effects('task-bob'), [])
        own = await self.invoke('research_remember', {'memory': 'Bob preference.'}, owner='bob')
        self.assertNotEqual(own['memory']['id'], memory['id'])
        self.assertEqual(self.store.native_db.get_user_memory(memory['id'], user_id='alice').memory, 'Alice preference.')

    async def test_find_paginates_without_cross_owner_entries(self):
        for number in range(11):
            await self.invoke('research_remember', {'memory': f'Preference {number}.'})
        await self.invoke('research_remember', {'memory': 'Bob only.'}, owner='bob')
        first = await self.invoke('research_find_memories', {})
        second = await self.invoke('research_find_memories', {'page': first['nextPage']})
        self.assertEqual((first['total'], second['total']), (11, 11))
        self.assertEqual((len(first['memories']), len(second['memories']), second['nextPage']), (10, 1, None))
        self.assertEqual(len({item['id'] for item in first['memories'] + second['memories']}), 11)

    async def test_same_call_returns_original_receipt_without_another_write(self):
        with patch.object(self.store.native_db, 'upsert_user_memory', wraps=self.store.native_db.upsert_user_memory) as write:
            first = await self.invoke('research_remember', {'memory': 'Use unittest.'}, call_id='original')
            repeated = await self.invoke('research_remember', {'memory': 'Use unittest.'}, call_id='original')
        self.assertEqual(first, repeated)
        self.assertEqual(write.call_count, 1)

    async def test_parent_and_child_same_call_id_keep_distinct_original_memories(self):
        def shared_turn(conn, context):
            self.sessions.authorize_tool(context, 'research_remember')
            return None, {'id': 'shared-turn', 'body': deepcopy(
                self.sessions.turns.setdefault('shared-turn', {}))}, None
        self.sessions._execution = shared_turn
        with patch.object(self.store.native_db, 'upsert_user_memory', wraps=self.store.native_db.upsert_user_memory) as write:
            parent = await self.invoke('research_remember', {'memory': 'Parent preference.'}, call_id='same-call')
            child = await self.invoke('research_remember', {'memory': 'Child preference.'},
                run_id='run-alice-second', call_id='same-call')
            self.assertIn('memory', child)
            self.assertNotEqual(parent['memory']['id'], child['memory']['id'])
            repeated = await self.invoke('research_remember', {'memory': 'Child preference.'},
                run_id='run-alice-second', call_id='same-call')
        self.assertEqual(child, repeated)
        self.assertEqual(write.call_count, 2)

    async def test_child_lost_receipt_observes_only_its_own_original_effect(self):
        def shared_turn(conn, context):
            self.sessions.authorize_tool(context, 'research_remember')
            return None, {'id': 'turn-alice', 'body': deepcopy(
                self.sessions.turns.setdefault('turn-alice', {}))}, None
        self.sessions._execution = shared_turn
        parent = await self.invoke('research_remember', {'memory': 'Parent original.'}, call_id='same-call')
        with patch.object(self.store, 'effect_complete', side_effect=ConnectionError('synthetic child receipt loss')):
            with self.assertRaises(StopAgentRun):
                await self.invoke('research_remember', {'memory': 'Child original.'},
                    run_id='run-alice-second', call_id='same-call')
        body = self.sessions.turns['turn-alice']
        body.update(result='Root result is not a child result.', blockReason='RESEARCH_RESTART_REQUIRES_RECONCILIATION')
        with patch.object(self.store.native_db, 'upsert_user_memory', side_effect=AssertionError('No child replay')):
            self.sessions.memory.observe('alice', {'id': 'turn-alice', 'session_id': 'session-alice', 'body': body},
                {'id': 'task-alice-second', 'run_id': 'run-alice-second'}, EFFECT_PREFIX)
        child_effect = self.store.effects('task-alice-second')[0]
        self.assertEqual(child_effect['status'], 'DONE')
        self.assertTrue(child_effect['result']['reconciled'])
        self.assertNotEqual(child_effect['result']['output']['memory']['id'], parent['memory']['id'])
        self.assertNotIn('reconciled', self.store.effects('task-alice')[0]['result'])
        self.assertEqual(body['result'], 'Root result is not a child result.')
        self.assertEqual(body['blockReason'], 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')

    async def test_lost_receipt_reconciles_original_id_without_rewriting(self):
        with patch.object(self.store, 'effect_complete', side_effect=ConnectionError('synthetic lost receipt')):
            with self.assertRaises(StopAgentRun):
                await self.invoke('research_remember', {'memory': 'Keep this preference.'}, call_id='original')
        original = self.store.native_db.get_user_memories(user_id='alice')[0]
        with patch.object(self.store.native_db, 'upsert_user_memory', side_effect=AssertionError('must not replay')):
            self.observe_original()
            repeated = await self.invoke('research_remember', {'memory': 'Keep this preference.'}, call_id='original')
        self.assertEqual(repeated['memory']['id'], original.memory_id)
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'DONE')
        self.assertTrue(self.store.effects('task-alice')[0]['result']['reconciled'])

    async def test_later_correction_never_gets_overwritten_by_unknown_original_write(self):
        with patch.object(self.store, 'effect_complete', side_effect=ConnectionError('synthetic lost receipt')):
            with self.assertRaises(StopAgentRun):
                await self.invoke('research_remember', {'memory': 'Old preference.'}, call_id='original')
        identifier = self.store.native_db.get_user_memories(user_id='alice')[0].memory_id
        await self.invoke('research_update_memory', {'memory_id': identifier, 'memory': 'New preference.'},
            run_id='run-alice-second')
        with patch.object(self.store.native_db, 'upsert_user_memory', side_effect=AssertionError('must not replay')):
            self.observe_original()
            with self.assertRaises(StopAgentRun):
                await self.invoke('research_remember', {'memory': 'Old preference.'}, call_id='original')
        self.assertEqual(self.store.native_db.get_user_memory(identifier, user_id='alice').memory, 'New preference.')
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'UNKNOWN')

    async def test_delete_with_no_boolean_return_is_confirmed_by_owner_readback(self):
        memory = (await self.invoke('research_remember', {'memory': 'Forget this.'}))['memory']
        with patch.object(self.store, 'effect_complete', side_effect=ConnectionError('synthetic lost receipt')):
            with self.assertRaises(StopAgentRun):
                await self.invoke('research_forget_memory', {'memory_id': memory['id']}, call_id='forget-original')
        with patch.object(self.store.native_db, 'delete_user_memory', side_effect=AssertionError('must not delete twice')):
            self.observe_original()
        receipt = self.store.effects('task-alice')[-1]['result']
        self.assertEqual(receipt['output']['operation'], 'forget')
        self.assertEqual(receipt['output']['memory'], memory)

    async def test_write_error_stays_unknown_and_reads_before_writing_fail_without_claiming_success(self):
        with patch.object(self.store.native_db, 'get_user_memories', side_effect=OSError('synthetic offline')):
            result = await self.invoke('research_find_memories', {})
        self.assertEqual(result['code'], 'RESEARCH_MEMORY_UNAVAILABLE')
        with patch.object(self.store.native_db, 'upsert_user_memory', side_effect=OSError('synthetic write offline')):
            with self.assertRaises(StopAgentRun):
                await self.invoke('research_remember', {'memory': 'Never stored.'}, call_id='write-error')
        self.observe_original()
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'UNKNOWN')
        self.assertEqual(self.store.native_db.get_user_memories(user_id='alice'), [])

    async def test_stop_before_mutation_keeps_native_memory_unchanged(self):
        self.sessions.cancelled = True
        with patch.object(self.store.native_db, 'upsert_user_memory') as write:
            with self.assertRaises(RunCancelledException):
                await self.invoke('research_remember', {'memory': 'Do not save.'})
        write.assert_not_called()
        self.assertEqual(self.store.effects('task-alice'), [])

    async def test_stop_after_reservation_before_write_is_confirmed_cancelled(self):
        prepare = self.sessions.memory.prepare
        def stopped_after_prepare(*args):
            operation = prepare(*args)
            self.sessions.cancelled = True
            return operation
        with patch.object(self.sessions.memory, 'prepare', side_effect=stopped_after_prepare), \
                patch.object(self.store.native_db, 'upsert_user_memory') as write:
            with self.assertRaises(RunCancelledException):
                await self.invoke('research_remember', {'memory': 'Do not save after stop.'})
        write.assert_not_called()
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'CANCELLED')

    async def test_memory_intent_cannot_reconcile_colliding_unknown_command(self):
        memory = (await self.invoke('research_remember', {'memory': 'Forget only this preference.'}))['memory']
        self.store.effect_reserve('run-alice', EFFECT_PREFIX + 'colliding-call', {
            'ownerId': 'alice', 'taskId': 'task-alice', 'sessionId': 'session-alice', 'turnId': 'turn-alice',
            'toolName': 'research_run', 'callId': 'colliding-call', 'arguments': {'argv': ['unknown-command']}})
        with self.assertRaises(StopAgentRun):
            await self.invoke('research_forget_memory', {'memory_id': memory['id']}, call_id='colliding-call')
        self.store.native_db.delete_user_memory(memory['id'], user_id='alice')
        self.observe_original()
        self.assertEqual(self.store.effects('task-alice')[-1]['status'], 'UNKNOWN')
        self.assertIsNone(self.store.effects('task-alice')[-1]['result'])

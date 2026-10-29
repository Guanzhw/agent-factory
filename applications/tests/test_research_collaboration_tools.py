"""Native Function/effect contracts with explicit synthetic collaboration services.

The PostgreSQL case verifies immutable application configuration, not a live model.
"""
import asyncio
from copy import deepcopy
import os
import unittest
from unittest.mock import Mock, patch

from agno.exceptions import StopAgentRun
from agno.run import RunContext
from agno.tools.function import FunctionCall

from agent_factory.execution_bindings import BindingContext
from agent_factory.personal_tool_contract import ToolInvocationError
from research.session_tools import COLLABORATION_TOOLS, EFFECT_PREFIX, ResearchSessionTools
import test_research_session_tools as tool_fixture
import test_research_sessions as session_fixture


ASSISTANT_ID = 'abcdefab-1111-2222-3333-abcdefabcdef'
QUESTION = {'assistant_id': ASSISTANT_ID, 'text': 'What does the shared synthetic result establish?'}
ACK = {'questionId': 'synthetic-question', 'state': 'saved'}


class Collaboration:
    def __init__(self):
        self.saved = {}
        self.calls = []
        self.reconciliations = []
        self.directory_calls = []

    def directory(self, context):
        self.directory_calls.append(context.user_id)
        return {'items': [{'id': ASSISTANT_ID, 'name': 'Synthetic colleague'}]}

    def ask(self, context, call_id, arguments):
        key = (context.user_id, context.run_id, call_id)
        self.calls.append((key, deepcopy(arguments)))
        self.saved[key] = deepcopy(arguments)
        return deepcopy(ACK)

    def reconcile(self, context, call_id, arguments):
        key = (context.user_id, context.run_id, call_id)
        self.reconciliations.append((key, deepcopy(arguments)))
        return deepcopy(ACK) if self.saved.get(key) == arguments else None


class ResearchCollaborationToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.store = tool_fixture.Store()
        self.sessions = tool_fixture.Sessions()
        self.collaboration = Collaboration()
        self.sessions.collaboration = self.collaboration
        self.tools = ResearchSessionTools()
        self.tools.bind(self.sessions, tool_fixture.Content())

    def call(self, name='research_ask_assistant', arguments=None, call_id='original-call'):
        context = RunContext(user_id='alice', session_id='task-alice', run_id='run-alice', session_state={})
        binding = BindingContext(None, self.store, {'budget': {'outputBytes': 65536}}, context, {})
        registration = next(item for item in self.tools.tool_registrations if item.tool_name == name)
        function = registration.factory(binding)
        function._run_context = context
        return FunctionCall(function=function, arguments=QUESTION if arguments is None else arguments, call_id=call_id)

    async def invoke(self, call):
        result = await call.aexecute()
        self.assertEqual(result.status, 'success', result.error)
        return call.result

    def unknown(self):
        request = {'ownerId': 'alice', 'taskId': 'task-alice', 'sessionId': 'session-alice',
            'turnId': 'turn-alice', 'toolName': 'research_ask_assistant', 'callId': 'original-call',
            'arguments': QUESTION}
        self.store.effect_reserve('run-alice', EFFECT_PREFIX + 'original-call', request)

    async def test_directory_and_question_need_no_workspace_and_send_only_explicit_arguments(self):
        self.assertTrue(COLLABORATION_TOOLS <= set(self.tools.available_tools))
        self.assertNotIn('research_run', self.tools.available_tools)
        directory = await self.invoke(self.call('research_assistant_directory', {}))
        self.assertEqual(directory['items'][0]['id'], ASSISTANT_ID)
        self.assertEqual(self.store.effects('task-alice'), [])
        self.assertEqual(await self.invoke(self.call()), ACK)
        self.assertEqual(self.collaboration.calls, [(('alice', 'run-alice', 'original-call'), QUESTION)])
        self.assertEqual(self.store.effects('task-alice')[0]['result'], {'outcome': 'completed', 'output': ACK})

    async def test_saved_question_receipt_replay_never_sends_or_recovers_again(self):
        self.assertEqual(await self.invoke(self.call()), ACK)
        self.assertEqual(await self.invoke(self.call()), ACK)
        self.assertEqual(len(self.collaboration.calls), 1)
        self.assertEqual(self.collaboration.reconciliations, [])

    async def test_native_tool_limit_prevents_second_question_in_the_same_batch(self):
        native = tool_fixture.RepairModel('', '')
        results = []
        async for _ in native.arun_function_calls(
                [self.call(call_id='first'), self.call(call_id='second')], results, function_call_limit=1):
            pass
        self.assertEqual(len(self.collaboration.calls), 1)
        self.assertEqual(len(self.store.receipts), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(bool(result.tool_call_error) for result in results), 1)
        self.assertEqual(native.calls, 0, 'Native executor test must not invoke even a scripted model')

    async def test_confirmed_precommit_rejection_is_terminal_and_never_retried(self):
        with patch.object(self.collaboration, 'ask', side_effect=ToolInvocationError(
                'ASSISTANT_ENDPOINT_DISABLED', outcome='failed', stopped=True)) as ask:
            self.assertEqual((await self.call().aexecute()).status, 'failure')
            self.assertEqual((await self.call().aexecute()).status, 'failure')
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'DONE')
        self.assertEqual(self.collaboration.reconciliations, [])

    async def test_lost_receipt_reconciles_original_saved_message_without_resending(self):
        with patch.object(self.store, 'effect_complete', side_effect=ConnectionError('synthetic lost ack')):
            with self.assertRaises(StopAgentRun):
                await self.call().aexecute()
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'UNKNOWN')
        self.assertEqual(await self.invoke(self.call()), ACK)
        self.assertEqual(len(self.collaboration.calls), 1)
        self.assertEqual(len(self.collaboration.reconciliations), 1)
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'DONE')

    async def test_missing_original_or_read_failure_keeps_unknown_and_does_not_send(self):
        self.unknown()
        with self.assertRaises(StopAgentRun):
            await self.call().aexecute()
        with patch.object(self.collaboration, 'reconcile', side_effect=ConnectionError('synthetic unavailable DB')):
            with self.assertRaises(StopAgentRun):
                await self.call().aexecute()
        self.assertEqual(self.collaboration.calls, [])
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'UNKNOWN')

    async def test_changed_original_arguments_cannot_reconcile_or_send(self):
        self.unknown()
        self.collaboration.saved[('alice', 'run-alice', 'original-call')] = deepcopy(QUESTION)
        with self.assertRaises(StopAgentRun):
            await self.call(arguments={**QUESTION, 'text': 'Different question'}).aexecute()
        self.assertEqual(self.collaboration.calls, [])
        self.assertEqual(self.collaboration.reconciliations, [])
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'UNKNOWN')

    async def test_other_unknown_effect_still_blocks_even_a_saved_question(self):
        self.unknown()
        self.collaboration.saved[('alice', 'run-alice', 'original-call')] = deepcopy(QUESTION)
        self.store.effect_reserve('run-alice', EFFECT_PREFIX + 'other', {'taskId': 'task-alice'})
        with self.assertRaises(StopAgentRun):
            await self.call().aexecute()
        self.assertEqual(self.collaboration.reconciliations, [])
        self.assertEqual(self.collaboration.calls, [])

    async def test_untrusted_owner_fields_and_changed_native_identity_are_rejected(self):
        for arguments in ({**QUESTION, 'owner_id': 'bob'}, {**QUESTION, 'text': 'x'},
                {**QUESTION, 'text': 'x' * 2001}):
            with self.subTest(arguments=list(arguments)):
                self.assertEqual((await self.call(arguments=arguments).aexecute()).status, 'failure')
        stale = self.call()
        stale.function._run_context.user_id = 'bob'
        self.assertEqual((await stale.aexecute()).status, 'failure')
        self.assertEqual(self.collaboration.calls, [])
        self.assertEqual(self.store.receipts, {})

    async def test_unbound_collaboration_is_not_advertised_or_called(self):
        self.sessions.collaboration = None
        self.assertTrue(COLLABORATION_TOOLS.isdisjoint(self.tools.available_tools))
        self.assertEqual((await self.call().aexecute()).status, 'failure')
        self.assertEqual(self.store.receipts, {})


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchCollaborationConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = session_fixture.ResearchSessionContracts()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_new_tools_create_new_pin_without_enabling_the_fixed_older_session(self):
        service, tools = self.fixture.service, self.fixture.tools
        self.assertTrue(service.setup.options('alice')['collaboration']['available'])
        current = tools.tool_registrations
        with patch.object(tools, 'tool_registrations', tuple(
                item for item in current if item.tool_name not in COLLABORATION_TOOLS)):
            old_id = service.create('alice', self.fixture.create.model_copy(update={'requestId': 'legacy-tool-session'}))
            self.assertFalse(service.setup.options('alice')['collaboration']['available'])
        new_id = service.create('alice', self.fixture.create.model_copy(update={'requestId': 'new-tool-session'}))
        with service.db.read() as conn:
            older = service._row(conn, 'alice', old_id)['body']['configuration']
            newer = service._row(conn, 'alice', new_id)['body']['configuration']
        self.assertFalse(older['autonomousCollaboration'])
        self.assertTrue(newer['autonomousCollaboration'])
        self.assertNotEqual(older['applicationRef'], newer['applicationRef'])
        with patch.object(service.runs, 'start', new=Mock(side_effect=AssertionError('Read must not execute'))):
            asyncio.run(service.read('alice', old_id))
        with service.db.read() as conn:
            self.assertEqual(older, service._row(conn, 'alice', old_id)['body']['configuration'])

"""Autonomous domain choices with SQLite records and synthetic native task ports.

These tests do not establish live model compatibility or PostgreSQL concurrency.
"""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from agno.run import RunContext
from agno.exceptions import StopAgentRun
from fastapi import HTTPException
from sqlalchemy import create_engine, select

from agent_factory.applications import GovernedStorage
from agent_factory.personal_tool_contract import ToolInvocationError
from agent_factory.store import digest
from research.session_research import ResearchSessionResearch


class Publications:
    def __init__(self):
        self.items = {}
        self.sources = {}

    def read(self, owner, identifier):
        return deepcopy(self.sources[identifier])

    def publish(self, owner, publication, request_id):
        value = publication.model_dump()
        previous = self.items.get(request_id)
        if previous is not None:
            if previous['ownerId'] != owner or previous['publication'] != value:
                raise HTTPException(409, 'synthetic publication conflict')
            return deepcopy(previous)
        item = {'id': str(uuid4()), 'ownerId': owner, 'publication': value}
        self.items[request_id] = item
        return deepcopy(item)


class ResearchSessionResearchTests(unittest.TestCase):
    def make_engine(self):
        directory = self.enterContext(TemporaryDirectory())
        return create_engine('sqlite:///' + str(Path(directory) / 'research.db'))

    def setUp(self):
        engine = self.make_engine()
        self.addCleanup(engine.dispose)
        self.receipts = []
        self.task = {'id': str(uuid4()), 'owner_id': 'alice', 'run_id': str(uuid4()),
                     'plan_id': str(uuid4()), 'terminal': False, 'cancel_requested': False}
        self.context = RunContext(user_id='alice', session_id=self.task['id'],
                                  run_id=self.task['run_id'], session_state={})
        self.store = SimpleNamespace(engine=engine,
            _connection=ContextVar('autonomous_research_test_connection', default=None),
            effects=lambda task: deepcopy(self.receipts) if task == self.task['id'] else [],
            task=Mock(side_effect=lambda identifier, owner: {**self.task, 'id': identifier, 'owner_id': owner}),
            sql=Mock(return_value=[]), effect_complete=Mock(side_effect=self.complete_effect))
        self.group = {'allStopped': False, 'unknown': False, 'status': 'running'}
        self.store.lifecycle_observer = SimpleNamespace(
            inspect_subtree=AsyncMock(side_effect=lambda *_: deepcopy(self.group)))
        self.row = {'id': str(uuid4()), 'owner_id': 'alice', 'body': {
            'goal': 'Compare synthetic candidate behavior', 'boundaries': 'Use synthetic data only',
            'sharedSourceIds': [], 'projectId': None}}
        self.turn = {'id': str(uuid4()), 'body': {}}
        self.content = Publications()
        self.sessions = SimpleNamespace(store=self.store,
            db=GovernedStorage(self.store, 'synthetic_sessions'),
            authorize_tool=self.authorize, _execution=self.execution,
            subagents=SimpleNamespace(start=AsyncMock(), children=AsyncMock(return_value=[])),
            content=self.content)
        self.sessions._write = self.sessions.db.write
        self.sessions.subagents._projection = lambda child, group: {
            'status': 'unknown' if group['unknown'] else group['status'],
            'childTaskId': child['id']}
        self.sessions.subagents.start.side_effect = self.start_child
        self.projects = SimpleNamespace(read=Mock())
        self.records = SimpleNamespace(content=self.content)
        self.service = ResearchSessionResearch(self.sessions, self.projects, self.records)

    def authorize(self, context, name):
        if context.user_id != 'alice' or context.session_id != self.task['id']:
            raise PermissionError('synthetic original session required')
        return {'id': self.row['id'], 'ownerId': 'alice', 'turnId': self.turn['id']}

    def execution(self, conn, context):
        self.authorize(context, '')
        return deepcopy(self.row), deepcopy(self.turn), deepcopy(self.task)

    def invoke(self, name, values=None, call_id=None, context=None):
        return asyncio.run(self.service.invoke(context or self.context,
            call_id or str(uuid4()), name, values or {}))

    async def start_child(self, context, call_id, goal):
        return {'childTaskId': str(uuid4()), 'status': 'running'}

    def receipt(self, suffix='command', exit_code=0, status='DONE', stopped=True):
        key = self.context.run_id + ':research-session-tool:' + suffix
        self.receipts.append({'effect_key': key, 'status': status, 'result': {
            'outcome': 'completed', 'output': {'exitCode': exit_code, 'stopped': stopped,
                                             'stdout': 'PRIVATE_SYNTHETIC_OUTPUT'}}})
        return key

    def complete_effect(self, run_id, key, receipt):
        effect = next(item for item in self.receipts if item['effect_key'] == run_id + ':' + key)
        effect.update(status='DONE', result=deepcopy(receipt))

    def direct(self, key=None, call_id=None):
        return self.invoke('research_record_experiment', {
            'hypothesis': 'Candidate preserves the expected value', 'conditions': 'Synthetic fixture',
            'effectKeys': [key or self.receipt()]}, call_id=call_id)

    def delegate(self, call_id=None):
        return self.invoke('research_experiment', {'hypothesis': 'Candidate passes',
            'conditions': 'Synthetic fixture', 'goal': 'Inspect the synthetic candidate'}, call_id=call_id)

    def rows(self):
        with self.sessions.db.read() as conn:
            return list(conn.execute(select(self.service.experiments)).mappings())

    def test_context_lookup_needs_zero_experiments_and_no_project(self):
        result = self.invoke('research_project')
        self.assertIsNone(result['project'])
        self.assertEqual(result['sessionGoal'], self.row['body']['goal'])
        self.assertEqual(self.rows(), [])
        self.sessions.subagents.start.assert_not_called()
        self.assertEqual(self.content.items, {})

    def test_direct_command_recording_needs_no_delegation_and_keeps_output_private(self):
        key = self.receipt()
        result = self.direct(key)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['evidenceIds'], [key])
        self.assertEqual(result['observations'], [{'evidenceId': key, 'exitCode': 0, 'stopped': True}])
        self.assertTrue(result['startRecordId'])
        self.assertTrue(result['terminalRecordId'])
        self.sessions.subagents.start.assert_not_called()
        self.assertEqual(len(self.content.items), 2)
        self.assertNotIn('PRIVATE_SYNTHETIC_OUTPUT', str(self.content.items))
        for item in self.content.items.values():
            self.assertEqual(item['publication']['visibility'], 'team')
            self.assertEqual(item['publication']['content']['verificationStatus'], 'unverified')
            self.assertNotIn('sessionGoal', item['publication']['content'])

    def test_lost_child_response_recovers_original_link_without_dispatch(self):
        child_id = str(uuid4())
        self.sessions.subagents.start.side_effect = RuntimeError('synthetic lost child response')
        with self.assertRaises(RuntimeError):
            self.delegate('lost-original-child')
        self.store.sql.return_value = [{'child_id': child_id}]
        self.service = ResearchSessionResearch(self.sessions, self.projects, self.records)
        recovered = self.delegate('lost-original-child')
        self.assertEqual(recovered['childTaskId'], child_id)
        self.assertEqual(recovered['status'], 'unknown')
        self.assertEqual(recovered['evidenceIds'], [child_id])
        self.assertNotIn('terminalRecordId', recovered)
        self.sessions.subagents.start.assert_awaited_once()
        self.assertEqual(self.store.sql.call_args.kwargs, {'owner': 'alice', 'parent': self.task['id'],
            'request': 'research-child:' + digest({'run': self.context.run_id, 'call': 'lost-original-child'})})

    def test_observer_leaves_pending_task_without_run_identity_untouched(self):
        self.direct()
        before = self.rows()
        self.store.effects = Mock(side_effect=AssertionError('A pending task has no run effects'))
        for task in ({**self.task, 'run_id': None}, {**self.task, 'run_id': ''},
                     {key: value for key, value in self.task.items() if key != 'run_id'}):
            asyncio.run(self.service.observe(task))
        self.store.effects.assert_not_called()
        self.store.effect_complete.assert_not_called()
        self.store.lifecycle_observer.inspect_subtree.assert_not_called()
        self.assertEqual(self.rows(), before)

    def test_observer_recovers_lost_child_response_and_exact_unknown_effect(self):
        child_id = str(uuid4())
        call_id = 'observer-original-child'
        self.sessions.subagents.start.side_effect = RuntimeError('synthetic lost child response')
        with self.assertRaises(RuntimeError):
            self.delegate(call_id)
        key = self.context.run_id + ':research-session-tool:' + call_id
        self.receipts.append({'effect_key': key, 'status': 'UNKNOWN', 'result': None})
        self.receipts.append({'effect_key': self.context.run_id + ':research-session-tool:unrelated',
                              'status': 'UNKNOWN', 'result': None})
        self.store.sql.return_value = [{'child_id': child_id}]
        self.group.update(allStopped=True, unknown=False, status='completed')
        asyncio.run(self.service.observe(self.task))
        self.sessions.subagents.start.assert_awaited_once()
        self.store.effect_complete.assert_called_once()
        run_id, recovered_key, receipt = self.store.effect_complete.call_args.args
        self.assertEqual((run_id, recovered_key),
                         (self.context.run_id, 'research-session-tool:' + call_id))
        self.assertEqual(receipt['outcome'], 'completed')
        self.assertEqual(receipt['output']['childTaskId'], child_id)
        self.assertEqual(self.receipts[0]['status'], 'DONE')
        self.assertEqual(self.receipts[1]['status'], 'UNKNOWN')
        self.assertEqual(self.rows()[0]['body']['status'], 'completed')
        self.assertTrue(self.rows()[0]['body']['terminalRecordId'])
        asyncio.run(self.service.observe(self.task))
        self.store.effect_complete.assert_called_once()

    def test_completed_parent_with_running_descendant_is_not_terminal(self):
        experiment = self.delegate()
        self.group.update(allStopped=False, status='completed',
            parent={'nativeStatus': 'completed', 'failed': False},
            children=[{'nativeStatus': 'running', 'failed': False}])
        result = self.invoke('research_experiment_result', {'experimentId': experiment['experimentId']})
        self.assertEqual(result['status'], 'running')
        self.assertNotIn('terminalRecordId', result)
        with self.assertRaises(ToolInvocationError):
            self.invoke('research_assess', {'experimentId': experiment['experimentId'],
                                          'assessment': 'The parent alone completed.'})
        self.assertEqual(len(self.content.items), 1)

    def test_failed_descendant_makes_stopped_group_failed(self):
        experiment = self.delegate()
        self.group.update(allStopped=True, status='completed',
            parent={'nativeStatus': 'completed', 'failed': False},
            children=[{'nativeStatus': 'failed', 'failed': True}])
        result = self.invoke('research_experiment_result', {'experimentId': experiment['experimentId']})
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['terminalRecordId'])
        self.assertEqual(result['observations'], [{'evidenceId': experiment['childTaskId'],
            'nativeStatus': 'failed', 'stopped': True}])

    def test_shared_source_dependencies_follow_start_terminal_and_assessment(self):
        first, second = str(uuid4()), str(uuid4())
        self.row['body']['sharedSourceIds'] = [first]
        self.content.sources[first] = {'sourceContentIds': [second]}
        result = self.direct()
        self.invoke('research_assess', {'experimentId': result['experimentId'], 'assessment': 'Conditional finding.'})
        self.assertEqual(len(self.content.items), 3)
        for publication in self.content.items.values():
            self.assertEqual(publication['publication']['sourceContentIds'], sorted([first, second]))

    def test_assessment_publication_lost_ack_recovers_without_duplicate(self):
        result = self.direct()
        publish = self.content.publish
        def lost_ack(owner, publication, request_id):
            receipt = publish(owner, publication, request_id)
            if 'assessment-' in request_id:
                raise RuntimeError('synthetic lost publication response')
            return receipt
        self.content.publish = lost_ack
        values = {'experimentId': result['experimentId'], 'assessment': 'Only an agent assessment.'}
        with self.assertRaises(RuntimeError):
            self.invoke('research_assess', values, call_id='lost-assessment')
        self.content.publish = publish
        recovered = self.service.reconcile(self.context, 'lost-assessment', 'research_assess', values)
        self.assertTrue(recovered['recordId'])
        self.assertEqual(recovered['verificationStatus'], 'agent_analysis')
        self.assertEqual(len(self.content.items), 3)
        self.assertNotIn('PRIVATE_SYNTHETIC_OUTPUT', str(self.content.items))

    def test_direct_start_publication_lost_ack_recovers_original_evidence(self):
        key = self.receipt('original-direct-command')
        publish = self.content.publish
        def lost_ack(owner, publication, request_id):
            receipt = publish(owner, publication, request_id)
            if request_id.endswith(':start'):
                raise RuntimeError('synthetic lost start publication response')
            return receipt
        self.content.publish = lost_ack
        with self.assertRaises(RuntimeError):
            self.direct(key, call_id='lost-direct-start')
        self.content.publish = publish
        recovered = self.direct(key, call_id='lost-direct-start')
        self.assertEqual(recovered['status'], 'completed')
        self.assertEqual(recovered['evidenceIds'], [key])
        self.assertTrue(recovered['terminalRecordId'])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.content.items), 2)
        self.sessions.subagents.start.assert_not_called()

    def test_multiple_experiments_allow_different_action_orders(self):
        first = self.direct(self.receipt('first'))
        self.invoke('research_project')
        second = self.delegate()
        third = self.direct(self.receipt('third', exit_code=1))
        self.assertEqual(len({first['experimentId'], second['experimentId'], third['experimentId']}), 3)
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(third['status'], 'failed')
        assessment = self.invoke('research_assess', {'experimentId': third['experimentId'],
            'assessment': 'Negative observation: candidate did not satisfy the measured condition.'})
        self.assertEqual(assessment['verificationStatus'], 'agent_analysis')
        self.sessions.subagents.start.assert_awaited_once()

    def test_original_delegate_request_survives_service_restart_without_new_child(self):
        first = self.delegate('original-delegation')
        self.service = ResearchSessionResearch(self.sessions, self.projects, self.records)
        again = self.delegate('original-delegation')
        self.assertEqual(again, first)
        self.sessions.subagents.start.assert_awaited_once()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.content.items), 1)
        with self.assertRaises(ToolInvocationError):
            self.invoke('research_experiment', {'hypothesis': 'Different hypothesis',
                'conditions': 'Synthetic fixture', 'goal': 'Inspect the synthetic candidate'},
                call_id='original-delegation')

    def test_unknown_dispatch_is_not_replayed(self):
        self.sessions.subagents.start.side_effect = RuntimeError('synthetic lost acknowledgement')
        with self.assertRaises(RuntimeError):
            self.delegate('unknown-delegation')
        with self.assertRaises(StopAgentRun):
            self.delegate('unknown-delegation')
        self.sessions.subagents.start.assert_awaited_once()
        self.assertEqual(len(self.rows()), 1)
        self.assertIsNone(self.service.reconcile(self.context, 'unknown-delegation',
            'research_experiment', {'hypothesis': 'Candidate passes',
                'conditions': 'Synthetic fixture', 'goal': 'Inspect the synthetic candidate'}))

    def test_unknown_child_never_publishes_terminal_or_accepts_assessment(self):
        experiment = self.delegate()
        self.group.update(allStopped=True, unknown=True, status='completed')
        result = self.invoke('research_experiment_result', {'experimentId': experiment['experimentId']})
        self.assertEqual(result['status'], 'unknown')
        self.assertNotIn('terminalRecordId', result)
        self.assertEqual(len(self.content.items), 1)
        with self.assertRaises(ToolInvocationError):
            self.invoke('research_assess', {'experimentId': experiment['experimentId'],
                                          'assessment': 'Must not claim completed.'})

    def test_observer_records_original_completion_once_without_scientific_verification(self):
        experiment = self.delegate()
        self.group.update(allStopped=True, unknown=False, status='completed')
        asyncio.run(self.service.observe(self.task))
        asyncio.run(self.service.observe(self.task))
        result = self.invoke('research_experiment_result', {'experimentId': experiment['experimentId']})
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['terminalRecordId'])
        self.assertEqual(len(self.content.items), 2)
        assessment = self.invoke('research_assess', {'experimentId': experiment['experimentId'],
            'assessment': 'This is scientific proof!'}, call_id='assessment-original')
        self.assertEqual(assessment['verificationStatus'], 'agent_analysis')
        self.assertEqual(self.service.reconcile(self.context, 'assessment-original', 'research_assess',
            {'experimentId': experiment['experimentId'], 'assessment': 'This is scientific proof!'}), assessment)
        self.assertEqual(len(self.content.items), 3)
        self.assertTrue(assessment['recordId'])
        repeated = self.invoke('research_assess', {'experimentId': experiment['experimentId'],
            'assessment': 'This is scientific proof!'}, call_id='assessment-original')
        self.assertEqual(repeated, assessment)
        self.assertEqual(len(self.content.items), 3)

    def test_direct_evidence_requires_original_confirmed_stopped_receipts(self):
        for status, stopped in [('UNKNOWN', True), ('DONE', False)]:
            with self.subTest(status=status, stopped=stopped):
                key = self.receipt(str(uuid4()), status=status, stopped=stopped)
                with self.assertRaises(ToolInvocationError):
                    self.direct(key)
        with self.assertRaises(ToolInvocationError):
            self.direct('foreign-task:research-session-tool:command')
        unrelated = self.receipt('unrelated')
        self.receipts[-1]['effect_key'] = unrelated.replace('research-session-tool:', 'another-adapter:')
        with self.assertRaises(ToolInvocationError):
            self.direct(self.receipts[-1]['effect_key'])
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.content.items, {})

    def test_other_owner_and_other_session_cannot_read_experiment(self):
        experiment = self.direct()
        foreign = RunContext(user_id='bob', session_id=self.task['id'],
                             run_id=self.task['run_id'], session_state={})
        with self.assertRaises(PermissionError):
            self.invoke('research_experiment_result', {'experimentId': experiment['experimentId']}, context=foreign)
        self.row['id'] = str(uuid4())
        with self.assertRaises(ToolInvocationError):
            self.invoke('research_experiment_result', {'experimentId': experiment['experimentId']})

    def test_project_context_hides_resource_bindings_and_stale_goal_blocks_new_experiment(self):
        self.row['body'].update(projectId='synthetic-project', projectGoalVersion=1)
        self.projects.read.return_value = {'id': 'synthetic-project', 'state': 'ready',
            'currentGoalVersion': 2, 'goals': [{'version': 2, 'agreement': {
                'objective': 'Revised goal', 'execution': {'connectionRefs': {'model': 'private'}},
                'resourceRefs': {'model': 'private'}}}]}
        result = self.invoke('research_project')
        self.assertNotIn('execution', result['project']['goals'][0]['agreement'])
        self.assertNotIn('resourceRefs', result['project']['goals'][0]['agreement'])
        with self.assertRaises(ToolInvocationError):
            self.delegate()
        self.assertEqual(self.rows(), [])
        self.sessions.subagents.start.assert_not_called()

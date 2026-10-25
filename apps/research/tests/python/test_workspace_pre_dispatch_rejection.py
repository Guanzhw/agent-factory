"""Offline regression for workspace rejection versus uncertain dispatch.

Workspace metadata uses the existing SQLite fixture pattern. AutoResearch.start,
recover and projection are real; only its PostgreSQL persistence and Factory
dependencies are in-memory seams, as in test_autoresearch_service. No native
queue, authorization policy implementation, model or remote runtime is exercised.
"""
from contextvars import ContextVar
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from sqlalchemy import create_engine

from agent_factory_research.autoresearch import AutoResearchService, ResearchPreset
from agent_factory_research.services import ResearchServices
from agent_factory_research.openresearch_workspace import (
    OpenResearchWorkspace, WorkspaceProjectCreate, WorkspaceSessionCreate,
)


class MemoryResearchService(AutoResearchService):
    """Replace PostgreSQL row storage only, retaining the real admission path."""

    def row(self, owner, task_id):
        self.store.task(task_id, owner)
        row = self.store.research_rows.get(task_id)
        if row is None or row['body']['ownerId'] != owner:
            raise HTTPException(404, 'RESEARCH_RUN_NOT_FOUND')
        return deepcopy(row)

    def change(self, owner, task_id, fn):
        row = self.row(owner, task_id)
        result = fn(row['body'])
        self.store.research_rows[task_id] = row
        return result


class WorkspacePreDispatchRejectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task = {'id': 'synthetic-task', 'owner_id': 'alice', 'run_id': 'synthetic-native-run'}
        self.plan = {'id': 'synthetic-plan', 'status': 'ready'}
        self.store = SimpleNamespace(
            engine=create_engine('sqlite://'),
            _connection=ContextVar('workspace-rejection-connection', default=None),
            connections=Mock(), settings=SimpleNamespace(demo=False), research_rows={},
            composition=SimpleNamespace(
                propose=Mock(return_value={'id': 'synthetic-proposal'}),
                accept=Mock(return_value=self.plan)),
            plan_policy=SimpleNamespace(status=Mock(return_value={'executionAllowed': False})),
            require_plan_execution=Mock(),
            reserve_task=Mock(return_value=(self.task, True)),
            accept=Mock(), admission_unknown=Mock(), task=Mock(return_value=self.task),
            effects=Mock(return_value=[]),
        )
        self.addCleanup(self.store.engine.dispose)
        self.store.sql = Mock(side_effect=self._research_sql)
        self.auth = Mock()
        self.bridge = SimpleNamespace(submit=AsyncMock(return_value={'run_id': self.task['run_id']}))
        self.runtime = Mock(side_effect=AssertionError('This admission fixture must not execute research'))
        self.preset = ResearchPreset(
            id='controlled', name='Synthetic admission fixture', default_goal='A bounded question',
            owner_id='alice', instructions='Synthetic fixture only', manifest={},
            limits={'totalSeconds': 60}, application_ref={'id': 'synthetic-application'},
            runtime_factory=self.runtime, context_reader=self.runtime,
            candidate_validator=self.runtime, experiment=self.runtime,
        )
        self.graph = ResearchServices(self.store, installed=True)
        self.research = MemoryResearchService(self.store, self.auth, self.bridge,
            {'controlled': self.preset}, research=self.graph)
        self.graph.autoresearch = self.research
        # Spies execute the actual implementations; neither injects the rejection.
        self.research.start = AsyncMock(wraps=self.research.start)
        self.research.recover = Mock(wraps=self.research.recover)
        self.workspace = OpenResearchWorkspace(self.store, self.auth, self.research)
        self.project = self.workspace.create_project('alice', WorkspaceProjectCreate(
            requestId='project-request', name='Synthetic workspace'))
        self.body = WorkspaceSessionCreate(
            requestId='session-request', workloadPresetId=self.preset.id, goal='A bounded question')

    def _research_sql(self, statement, **parameters):
        """Only the constructor, original-request lookup and insertion use SQL."""
        sql = ' '.join(statement.split())
        if sql.startswith('CREATE TABLE IF NOT EXISTS af_autoresearch_runs '):
            return []
        if sql == 'SELECT task_id FROM af_autoresearch_runs WHERE owner_id=:owner AND request_id=:request':
            return [{'task_id': task_id} for task_id, row in self.store.research_rows.items()
                if row['body']['ownerId'] == parameters['owner']
                and row['body']['requestId'] == parameters['request']]
        if sql.startswith('INSERT INTO af_autoresearch_runs VALUES('):
            task_id = parameters['task']
            if task_id in self.store.research_rows:
                return []
            self.store.research_rows[task_id] = {
                'fingerprint': parameters['fp'], 'body': json.loads(parameters['body'])}
            return [{'task_id': task_id}]
        raise AssertionError('Unexpected SQL in the admission-only fixture: ' + sql)

    async def test_member_submits_directly_without_consulting_historical_review_policy(self):
        result = await self.workspace.create_session('alice', self.project['id'], self.body)
        self.assertEqual(result['taskId'], self.task['id'])
        self.store.require_plan_execution.assert_called_once_with('alice', self.plan)
        self.store.plan_policy.status.assert_not_called()
        self.store.reserve_task.assert_called_once()
        self.bridge.submit.assert_awaited_once()
        self.runtime.assert_not_called()

    async def test_same_member_request_reuses_original_native_task(self):
        original = await self.workspace.create_session('alice', self.project['id'], self.body)
        result = await self.workspace.create_session('alice', self.project['id'], self.body)
        self.assertEqual(result['id'], original['id'])
        self.assertEqual(result['taskId'], self.task['id'])
        self.store.reserve_task.assert_called_once()
        self.research.start.assert_awaited_once()
        self.bridge.submit.assert_awaited_once()
        self.assertEqual(self.bridge.submit.await_args.args[2], original['nativeRequestId'])
        self.runtime.assert_not_called()

    async def test_timeout_after_real_start_attempt_keeps_unknown_and_never_redispatches(self):
        self.bridge.submit.side_effect = TimeoutError('Synthetic lost native admission acknowledgement')
        with self.assertRaises(TimeoutError):
            await self.workspace.create_session('alice', self.project['id'], self.body)
        self.store.reserve_task.assert_called_once()
        self.store.admission_unknown.assert_called_once_with(self.task['id'])
        self.bridge.submit.assert_awaited_once()
        original_rows = deepcopy(self.store.research_rows)
        self.assertEqual(original_rows[self.task['id']]['body']['status'], 'unknown')
        restarted = OpenResearchWorkspace(self.store, self.auth, self.research)
        recovered = await restarted.create_session('alice', self.project['id'], self.body)
        self.assertEqual(recovered['state'], 'unknown')
        self.assertEqual(recovered['taskId'], self.task['id'])
        self.assertEqual(recovered['nativeRequestId'], original_rows[self.task['id']]['body']['requestId'])
        self.research.start.assert_awaited_once()
        self.bridge.submit.assert_awaited_once()
        self.store.reserve_task.assert_called_once()
        self.assertEqual(self.store.research_rows, original_rows)
        self.runtime.assert_not_called()

    async def test_dispatch_http_error_keeps_original_unknown_and_does_not_authorize_replay(self):
        self.bridge.submit.side_effect = HTTPException(409, 'synthetic dispatch error')
        with self.assertRaises(HTTPException):
            await self.workspace.create_session('alice', self.project['id'], self.body)
        recovered = await self.workspace.create_session('alice', self.project['id'], self.body)
        self.assertEqual(recovered['state'], 'unknown')
        self.store.reserve_task.assert_called_once()
        self.store.admission_unknown.assert_called_once_with(self.task['id'])
        self.bridge.submit.assert_awaited_once()

"""Portable managed admission boundaries; fixtures never call native ORX/model."""
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine

from agent_factory.managed_orx_attachment import ManagedORXSessionProvider
from agent_factory.openresearch_workspace import OpenResearchWorkspace, WorkspaceManagedPrepare
from agent_factory.store import digest
from agent_factory.managed_orx_profile import exact_input_schema


class ManagedWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = SimpleNamespace(engine=create_engine('sqlite://'),
            _connection=ContextVar('managed-workspace-transaction', default=None),
            composition=Mock(), applications=Mock(), plan_policy=Mock(),
            require_plan_execution=Mock(), plan=Mock(), task=Mock(), task_for_request=Mock())
        self.addCleanup(self.store.engine.dispose)
        self.auth, self.research, self.factory = Mock(), Mock(), Mock()
        self.factory.instantiate = AsyncMock(return_value={'id': 'task-1'})
        self.pin = {'kind': 'orx', 'revision': '1', 'version': 1, 'fingerprint': 'b' * 64}
        self.project = {'id': 'project-1', 'kind': 'native-openresearch', 'upstreamProjectId': 'native-1',
            'connectionRefs': {'workspace': 'original-connection'}, 'connectionPins': {'workspace': self.pin},
            'nativeProject': {'projectIdentityHash': 'c' * 64}}
        self.contract = {'ownerId': 'alice', 'connectionRef': 'original-connection',
            'connectionFingerprint': self.pin['fingerprint'], 'connectionRevision': '1', 'connectionVersion': 1,
            'projectId': 'native-1', 'projectIdentityHash': 'c' * 64, 'sessionId': 'original-session',
            'profile': {'harness': 'opencode', 'model': 'factory/deepseek-flash'}}
        self.profile = {'ownerId': 'alice', 'targetRef': 'original-target', 'connectionPin': self.pin,
            'nativeProfileId': 'text-probe', 'sessionId': 'original-session',
            'contractSha256': digest(self.contract), 'applicationRef': {'id': 'probe-app', 'version': 1, 'sha256': 'd' * 64},
            'mode': 'probe'}
        provider = object.__new__(ManagedORXSessionProvider)
        provider._contract = self.contract
        self.store.process_runtime = SimpleNamespace(resources=SimpleNamespace(targets={
            'original-target': SimpleNamespace(provider=provider, owners={'alice'}, axis='compute')}))
        self.service = OpenResearchWorkspace(self.store, self.auth, self.research,
            factory=self.factory, managed_profiles={'probe': self.profile})
        with self.service.db.write() as conn:
            conn.execute(self.service.projects.insert().values(id='project-1', owner_id='alice',
                body=self.project, created_at='2026-01-01'))
        self.service.refresh_native_project = AsyncMock(return_value=self.project)
        self.adapter = Mock()
        self.adapter.describe.return_value = {'sessionProfiles': [{'id': 'text-probe', **self.contract['profile']}]}
        self.service._native_adapter = Mock(return_value=(self.adapter, self.pin))
        self.plan = {'status': 'ready', 'id': 'immutable-plan', 'ownerId': 'alice', 'applicationRef': self.profile['applicationRef'],
            'inputValues': {'managedAttachment': self.contract}, 'tools': ['bounded_process_run'],
            'executionBindings': {'model': {'adapterId': 'managed-orx-pause-model-v1', 'config': {'targetRef': 'original-target'}},
                'environment': {'config': {'targetRef': 'original-target'}},
                'tools': [{'config': {'targetRef': 'original-target'}}]}}
        self.store.applications.require_current.return_value = {'modes': {'probe': {'inputSchema': exact_input_schema(self.contract)}}}
        self.store.composition.propose.return_value = {'id': 'proposal'}
        self.store.composition.accept.return_value = self.plan
        self.store.composition._candidate.return_value = self.plan
        self.store.plan.return_value = self.plan
        self.store.plan_policy.status.return_value = {'executionAllowed': False}
        self.body = WorkspaceManagedPrepare(requestId='prepare-request', profileId='probe', goal='Verify original attachment')
        self.store.task_for_request.side_effect = HTTPException(404, 'not found')

    async def test_prepare_is_nonexecuting_and_immutable_composition_input(self):
        result = await self.service.prepare_managed('alice', 'project-1', self.body)
        self.assertEqual(result['state'], 'prepared')
        self.assertEqual(result['plan'], self.plan)
        self.assertFalse(result['authorization']['executionAllowed'])
        self.assertEqual(self.store.composition.propose.call_args.kwargs['input_values'], {'managedAttachment': self.contract})
        self.factory.instantiate.assert_not_awaited()
        self.store.plan_policy.request_review.assert_not_called()
        again = await self.service.prepare_managed('alice', 'project-1', self.body)
        self.assertEqual(again['id'], result['id'])
        self.store.composition.propose.assert_called_once()
        with self.assertRaises(HTTPException):
            self.service.session('bob', 'project-1', result['id'])
        with self.assertRaises(ValidationError):
            WorkspaceManagedPrepare(**{**self.body.model_dump(), 'managedAttachment': self.contract})

    async def test_profiles_filter_foreign_revoked_and_changed_original(self):
        self.assertEqual(len(await self.service.list_managed_profiles('alice', 'project-1')), 1)
        self.assertEqual(await self.service.list_managed_profiles('bob', 'project-1'), [])
        self.service.managed_profiles['probe']['sessionId'] = 'replacement-session'
        self.assertEqual(await self.service.list_managed_profiles('alice', 'project-1'), [])
        with self.assertRaises(HTTPException):
            await self.service.prepare_managed('alice', 'project-1', self.body)
        self.store.composition.propose.assert_not_called()

    async def test_start_rechecks_approval_and_unknown_never_resubmits(self):
        result = await self.service.prepare_managed('alice', 'project-1', self.body)
        self.store.require_plan_execution.side_effect = HTTPException(403, 'review required')
        with self.assertRaises(HTTPException):
            await self.service.start_managed('alice', 'project-1', result['id'], 'start-request')
        self.factory.instantiate.assert_not_awaited()
        self.store.require_plan_execution.side_effect = None
        self.factory.instantiate.side_effect = TimeoutError('unknown native acknowledgment')
        with self.assertRaises(TimeoutError):
            await self.service.start_managed('alice', 'project-1', result['id'], 'start-request')
        again = await self.service.start_managed('alice', 'project-1', result['id'], 'retry-request')
        self.assertEqual(again['state'], 'unknown')
        self.factory.instantiate.assert_awaited_once()
        task = {'id': 'task-1', 'plan_id': self.plan['id'], 'request_id': result['nativeRequestId'],
            'admission': 'unknown', 'body': {'lastStatus': 'unknown'}}
        self.store.task_for_request.side_effect = None
        self.store.task_for_request.return_value = task
        self.store.task.return_value = task
        recovered = self.service.reconcile('alice', 'project-1', result['id'])
        self.assertEqual(recovered['taskId'], 'task-1')
        self.assertNotIn('research', recovered)
        self.research.projection.assert_not_called()
        self.factory.instantiate.assert_awaited_once()

    async def test_plan_target_replacement_rolls_back_session(self):
        self.plan['executionBindings']['environment']['config']['targetRef'] = 'replacement-target'
        with self.assertRaises(HTTPException):
            await self.service.prepare_managed('alice', 'project-1', self.body)
        self.assertEqual(self.service.list_sessions('alice', 'project-1'), [])

    async def test_revoked_execution_does_not_hide_readable_original_session(self):
        value = await self.service.prepare_managed('alice', 'project-1', self.body)
        self.store.plan_policy.status.side_effect = HTTPException(403, 'run revoked')
        self.store.plan_policy.current.return_value = {'name': 'admin-review'}
        current = self.service.session('alice', 'project-1', value['id'])
        self.assertFalse(current['authorization']['executionAllowed'])
        self.assertFalse(current['authorization']['reviewRequestSupported'])
        self.assertEqual(current['authorization']['code'], 'EXECUTION_PERMISSION_REVOKED')
        self.assertEqual(current['upstreamSessionId'], 'original-session')
        self.factory.instantiate.assert_not_awaited()

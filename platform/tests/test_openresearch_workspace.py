"""Portable workspace metadata tests, not live ORX or queue acceptance."""
import unittest
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine

from agent_factory.openresearch_workspace import (
    OpenResearchWorkspace, WorkspaceProjectCreate, WorkspaceSessionCreate,
)


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = SimpleNamespace(engine=create_engine('sqlite://'),
            _connection=ContextVar('workspace-test-connection', default=None), connections=Mock())
        self.addCleanup(self.store.engine.dispose)
        self.auth = Mock()
        self.research = Mock()
        self.preset = SimpleNamespace(id='controlled', fingerprint='pinned-workload', connection_refs={})
        self.research.preset.return_value = self.preset
        self.research.unavailable.return_value = []
        self.research.list_presets.return_value = []
        self.research.start = AsyncMock(return_value={'id': 'task-1'})
        def run_row(owner, task_id):
            with self.store.engine.connect() as conn:
                row = conn.execute(self.service.sessions.select()).mappings().first()
            intent = row['body']
            return {'body': {'id': task_id, 'ownerId': owner, 'presetId': intent['workloadPresetId'],
                'presetFingerprint': intent['workloadFingerprint'], 'requestId': intent['nativeRequestId'],
                'goal': intent['goal']}}
        self.research.row.side_effect = run_row
        self.research.cancel = AsyncMock()
        self.research.projection.return_value = {'id': 'task-1', 'status': 'running', 'acceptance': {}}
        self.research.recover.return_value = None
        self.service = OpenResearchWorkspace(self.store, self.auth, self.research)
        self.project = self.service.create_project('alice', WorkspaceProjectCreate(requestId='project-request', name='A project'))
        self.body = WorkspaceSessionCreate(requestId='session-request', workloadPresetId='controlled', goal='Research a bounded question')

    def test_project_idempotency_and_isolation(self):
        again = self.service.create_project('alice', WorkspaceProjectCreate(requestId='project-request', name='A project'))
        self.assertEqual(again, self.project)
        self.assertEqual(self.service.list_projects('bob'), [])
        with self.assertRaises(HTTPException) as caught:
            self.service.project('bob', self.project['id'])
        self.assertEqual(caught.exception.status_code, 404)
        with self.assertRaises(HTTPException) as caught:
            self.service.create_project('alice', WorkspaceProjectCreate(requestId='project-request', name='Changed'))
        self.assertEqual(caught.exception.status_code, 409)

    async def test_exact_task_link_and_no_redispatch(self):
        value = await self.service.create_session('alice', self.project['id'], self.body)
        self.assertEqual(value['taskId'], 'task-1')
        self.assertEqual(value['contextSource'], 'approved-workload-preset')
        self.assertEqual(value['verificationStatus'], 'not-live-verified')
        again = await self.service.create_session('alice', self.project['id'], self.body)
        self.assertEqual(again['id'], value['id'])
        self.research.start.assert_awaited_once()
        self.assertTrue(self.research.start.await_args.args[-1].startswith('or-session:'))
        await self.service.cancel('alice', self.project['id'], value['id'], 'cancel-request')
        self.research.cancel.assert_awaited_once_with('alice', 'task-1', 'cancel-request')
        with self.assertRaises(HTTPException):
            await self.service.cancel('bob', self.project['id'], value['id'], 'cancel-request')

    async def test_unknown_ack_never_replays_even_after_restart(self):
        self.research.start.side_effect = TimeoutError('unknown upstream acknowledgment')
        with self.assertRaises(TimeoutError):
            await self.service.create_session('alice', self.project['id'], self.body)
        restarted = OpenResearchWorkspace(self.store, self.auth, self.research)
        value = await restarted.create_session('alice', self.project['id'], self.body)
        self.assertIsNone(value['taskId'])
        self.assertEqual(value['state'], 'unknown')
        self.research.start.assert_awaited_once()
        with self.assertRaises(HTTPException) as caught:
            await restarted.cancel('alice', self.project['id'], value['id'], 'cancel-request')
        self.assertEqual(caught.exception.status_code, 409)
        self.research.recover.return_value = {'id': 'task-1'}
        recovered = restarted.reconcile('alice', self.project['id'], value['id'])
        self.assertEqual(recovered['taskId'], 'task-1')
        self.research.start.assert_awaited_once()

    async def test_changed_request_and_cross_project_are_not_aliases(self):
        value = await self.service.create_session('alice', self.project['id'], self.body)
        other = self.service.create_project('alice', WorkspaceProjectCreate(requestId='another-project', name='Other'))
        with self.assertRaises(HTTPException):
            self.service.session('alice', other['id'], value['id'])
        changed = self.body.model_copy(update={'goal': 'A changed goal'})
        with self.assertRaises(HTTPException) as caught:
            await self.service.create_session('alice', self.project['id'], changed)
        self.assertEqual(caught.exception.status_code, 409)
        self.research.start.assert_awaited_once()

    async def test_selected_resource_cannot_be_ignored_by_preset(self):
        self.store.connections.inspect.return_value = {'kind': 'environment'}
        self.store.connections.preflight.return_value = {'kind': 'environment', 'revision': 'v1', 'fingerprint': 'fp', 'version': 1}
        project = self.service.create_project('alice', WorkspaceProjectCreate(requestId='remote-project', name='Remote',
            connectionRefs={'runtime': 'personal-connection'}))
        with self.assertRaises(HTTPException) as caught:
            await self.service.create_session('alice', project['id'], self.body)
        self.assertEqual(caught.exception.detail, 'OPENRESEARCH_WORKLOAD_CONNECTION_MISMATCH')
        self.research.start.assert_not_awaited()

    async def test_current_permission_checked_and_capabilities_honest(self):
        capabilities = self.service.capabilities('alice')
        for name in ('upstreamProjectCreation', 'arbitraryModelSelection', 'arbitraryHarnessSelection', 'upstreamWorktrees', 'liveEndToEndVerified'):
            self.assertFalse(capabilities[name])
        self.auth.require.side_effect = HTTPException(403, 'permission revoked')
        with self.assertRaises(HTTPException):
            await self.service.create_session('alice', self.project['id'], self.body)
        self.research.start.assert_not_awaited()

    def test_no_secret_or_arbitrary_model_contract(self):
        with self.assertRaises(ValidationError):
            WorkspaceProjectCreate.model_validate({'requestId': 'bad-request', 'name': 'A', 'password': 'secret'})
        with self.assertRaises(ValidationError):
            WorkspaceSessionCreate.model_validate({**self.body.model_dump(), 'model': 'unapproved'})

    async def test_recovery_must_match_pinned_workload_goal_and_original_request(self):
        self.research.start.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await self.service.create_session('alice', self.project['id'], self.body)
        self.research.recover.return_value = {'id': 'task-1'}
        original = self.research.row.side_effect
        for field, replacement in [('presetFingerprint', 'changed'), ('requestId', 'other'),
                ('goal', 'another goal'), ('ownerId', 'bob'), ('presetId', 'other')]:
            def changed(owner, task, field=field, replacement=replacement):
                row = original(owner, task)
                row['body'][field] = replacement
                return row
            self.research.row.side_effect = changed
            with self.assertRaises(HTTPException) as caught:
                await self.service.create_session('alice', self.project['id'], self.body)
            self.assertEqual(caught.exception.detail, 'OPENRESEARCH_SESSION_IDENTITY_CHANGED')
        self.research.start.assert_awaited_once()

    async def test_native_attach_keeps_real_project_identity_and_blocks_unrelated_preset(self):
        import httpx
        from agent_factory.orx_research_session import UPSTREAM_COMMIT
        from agent_factory.orx_workspace_adapter import OpenResearchWorkspaceAdapter
        from agent_factory.openresearch_workspace import WorkspaceNativeAttach
        calls = []
        def handler(request):
            calls.append((request.method, request.url.path))
            project = {'id': 'native-project', 'name': 'Real native metadata fixture',
                'slug': 'native-project', 'repoPath': '/owned/project', 'path': '/owned/project'}
            return httpx.Response(200, json={'projects': [project]} if request.url.path == '/api/projects' else {'project': project})
        adapter = OpenResearchWorkspaceAdapter(owner_id='alice', port=3101,
            project_paths={'native-project': '/owned/project'}, session_profiles={},
            authorize=lambda owner, operation: owner == 'alice', upstream_revision=UPSTREAM_COMMIT,
            owner_exclusive=True, transport=httpx.MockTransport(handler))
        self.store.connections.resolve.return_value = adapter
        self.store.connections.preflight.return_value = {'kind': 'orx', 'revision': 'v1', 'fingerprint': 'fp', 'version': 1}
        preview = await self.service.native_projects('alice', 'native-connection')
        native = preview['projects'][0]
        attached = await self.service.attach_native_project('alice', WorkspaceNativeAttach(
            requestId='attach-request', connectionRef='native-connection', nativeProjectId=native['id'],
            projectIdentityHash=native['projectIdentityHash']))
        self.assertEqual(attached['upstreamProjectId'], 'native-project')
        self.assertEqual(attached['kind'], 'native-openresearch')
        self.assertFalse(attached['sessionExecutionAvailable'])
        refreshed = await self.service.refresh_native_project('alice', attached['id'])
        self.assertEqual(refreshed['nativeProject']['projectIdentityHash'], native['projectIdentityHash'])
        with self.assertRaises(HTTPException) as caught:
            await self.service.create_session('alice', attached['id'], self.body)
        self.assertEqual(caught.exception.detail, 'NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED')
        self.research.start.assert_not_awaited()
        self.assertTrue(all(method == 'GET' for method, _ in calls))
        with self.assertRaises(HTTPException):
            await self.service.refresh_native_project('bob', attached['id'])
        with self.assertRaises(HTTPException) as caught:
            await self.service.attach_native_project('alice', WorkspaceNativeAttach(
                requestId='changed-attach', connectionRef='native-connection', nativeProjectId=native['id'],
                projectIdentityHash='a' * 64))
        self.assertEqual(caught.exception.detail, 'OPENRESEARCH_NATIVE_PROJECT_CHANGED')

    def test_goals_are_canonical_before_durable_intent(self):
        self.assertEqual(WorkspaceSessionCreate(requestId='space-request', workloadPresetId='controlled',
            goal='  A valid goal  ').goal, 'A valid goal')
        with self.assertRaises(ValidationError):
            WorkspaceSessionCreate(requestId='space-request', workloadPresetId='controlled', goal='    ')

    async def test_request_recovery_is_read_only_owner_scoped_and_covers_unknown_intent(self):
        recovered = self.service.request_result('alice', 'project-request')
        self.assertEqual(recovered['project']['id'], self.project['id'])
        with self.assertRaises(HTTPException) as caught:
            self.service.request_result('bob', 'project-request')
        self.assertEqual(caught.exception.status_code, 404)
        self.research.start.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await self.service.create_session('alice', self.project['id'], self.body)
        recovered = self.service.request_result('alice', 'session-request')
        self.assertEqual(recovered['session']['state'], 'unknown')
        self.assertIsNone(recovered['session']['taskId'])
        self.research.recover.assert_not_called()
        self.research.start.assert_awaited_once()

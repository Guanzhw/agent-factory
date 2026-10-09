"""Owner-scoped OpenResearch workspace over governed Factory workload runs.

These records group genuine task-backed sessions; they never create an upstream
project, silently change a preset's repository/model, or grant harness access.
Unknown dispatch is reconciled by the original request, never submitted again.
"""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from .applications import GovernedStorage
from .store import digest, now

ID = r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$'


class WorkspaceProjectCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    # Configuration metadata only. No filesystem path, URL, secret or shell input.
    connectionRefs: dict[str, str] = Field(default_factory=dict, max_length=12)


class WorkspaceNativeAttach(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=ID)
    connectionRef: str = Field(min_length=1, max_length=200)
    nativeProjectId: str = Field(min_length=1, max_length=100, pattern=ID)
    projectIdentityHash: str = Field(pattern=r'^[a-f0-9]{64}$')


class WorkspaceSessionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=ID)
    workloadPresetId: str = Field(min_length=1, max_length=100, pattern=ID)
    goal: str = Field(min_length=2, max_length=2000)
    executionContract: Literal['controlled-workload-v1'] = 'controlled-workload-v1'

    @field_validator('goal')
    @classmethod
    def normalized_goal(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('A non-empty research goal is required')
        return value


class WorkspaceManagedPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=8, max_length=100, pattern=ID)
    profileId: str = Field(min_length=1, max_length=100, pattern=ID)
    goal: str = Field(min_length=2, max_length=2000)


class WorkspaceCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=ID)


class OpenResearchWorkspace:
    def __init__(self, store, auth, research, *, factory=None, managed_profiles=None):
        self.store, self.auth, self.research = store, auth, research
        import copy
        self.factory, self.managed_profiles = factory, copy.deepcopy(managed_profiles or {})
        self.db = GovernedStorage(store, 'af_openresearch_workspace_v1')
        metadata = MetaData()
        self.projects = Table('af_openresearch_workspace_projects', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('body', JSON, nullable=False), Column('created_at', String, nullable=False))
        self.sessions = Table('af_openresearch_workspace_sessions', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('project_id', String, nullable=False), Column('body', JSON, nullable=False),
            Column('state', String, nullable=False), Column('task_id', String),
            Column('created_at', String, nullable=False))
        self.commands = self.db.command_table('af_openresearch_workspace_commands', metadata)
        metadata.create_all(store.engine)

    def capabilities(self, owner):
        self.auth.require(owner, 'read')
        return {'contractVersion': 1, 'projectKind': 'factory-workspace',
            'sessionExecution': ['controlled-workload-v1'],
            'nativeProjectAttachment': True, 'nativeAttachmentRequiresTrustedConnection': True,
            'upstreamProjectCreation': False, 'arbitraryModelSelection': False,
            'arbitraryHarnessSelection': False, 'upstreamWorktrees': False,
            'liveEndToEndVerified': False,
            'workloads': [{**p, 'kind': 'controlled-workload'} for p in self.research.list_presets(owner)]}

    def request_result(self, owner, request_id):
        """Read-only recovery of an acknowledged or in-flight owner command."""
        self.auth.require(owner, 'read')
        from .material_governance import MaterialGovernance
        MaterialGovernance._key(request_id)
        with self.db.read() as conn:
            command = conn.execute(select(self.commands).where(self.commands.c.actor_id == owner,
                self.commands.c.request_id == request_id)).mappings().first()
            if command is None:
                raise HTTPException(404, 'OPENRESEARCH_REQUEST_NOT_FOUND')
            identifier = command['result']['id']
            action = command['action']
            if action in {'project-create', 'native-project-attach'}:
                return {'requestId': request_id, 'action': action,
                    'project': dict(self._project(conn, owner, identifier)['body'])}
            row = conn.execute(select(self.sessions).where(self.sessions.c.id == identifier,
                self.sessions.c.owner_id == owner)).mappings().first()
            if row is None:
                raise HTTPException(409, 'OPENRESEARCH_REQUEST_INTEGRITY')
            session = dict(row)
        return {'requestId': request_id, 'action': action, 'session': self._projection(owner, session)}

    def _native_adapter(self, owner, reference, pin=None):
        from .orx_workspace_adapter import ADAPTER_ID, OpenResearchWorkspaceAdapter
        expected = {} if pin is None else {'expected_revision': pin['revision'],
            'expected_fingerprint': pin['fingerprint'], 'expected_version': pin['version']}
        current = self.store.connections.preflight(owner, reference, 'orx',
            expected_adapter_ref=ADAPTER_ID, required_capabilities=['project:read'], **expected)
        handle = self.store.connections.resolve(owner, reference, 'orx', expected_adapter_ref=ADAPTER_ID,
            required_capabilities=['project:read'], expected_revision=current['revision'],
            expected_fingerprint=current['fingerprint'], expected_version=current['version'])
        if type(handle) is not OpenResearchWorkspaceAdapter:
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_ADAPTER_UNAVAILABLE')
        return handle, current

    async def native_projects(self, owner, reference):
        self.auth.require(owner, 'read')
        from .orx_research_session import OrxSessionError
        adapter, pin = self._native_adapter(owner, reference)
        try:
            projects = await adapter.list_projects(owner)
            self._native_adapter(owner, reference, pin)
            return {'connectionRef': reference, 'connectionPin': pin,
                'adapter': adapter.describe(owner), 'projects': projects}
        except OrxSessionError:
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_PROJECT_OBSERVATION_FAILED') from None

    async def attach_native_project(self, owner, body: WorkspaceNativeAttach):
        self.auth.require(owner, 'run')
        from .orx_research_session import OrxSessionError
        fp = digest({'action': 'native-project-attach', 'payload': body.model_dump(exclude={'requestId'})})
        with self.db.read() as conn:
            old = self.db.old(conn, self.commands, owner, body.requestId, fp)
            if old:
                return dict(self._project(conn, owner, old['id'])['body'])
        adapter, pin = self._native_adapter(owner, body.connectionRef)
        try:
            native = await adapter.inspect_project(owner, body.nativeProjectId)
        except OrxSessionError:
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_PROJECT_OBSERVATION_FAILED') from None
        if native['projectIdentityHash'] != body.projectIdentityHash:
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_PROJECT_CHANGED')
        self._native_adapter(owner, body.connectionRef, pin)
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, body.requestId, fp)
            if old:
                return dict(self._project(conn, owner, old['id'])['body'])
            identifier = 'orp-' + uuid4().hex
            project = {'id': identifier, 'name': native['name'], 'description': '',
                'kind': 'native-openresearch', 'connectionRefs': {'workspace': body.connectionRef},
                'connectionPins': {'workspace': pin}, 'upstreamProjectId': native['id'],
                'nativeProject': native, 'createdAt': now(),
                'sessionExecutionAvailable': False,
                'sessionBlocker': 'NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED'}
            conn.execute(self.projects.insert().values(id=identifier, owner_id=owner,
                body=project, created_at=project['createdAt']))
            self.db.record(conn, self.commands, owner, body.requestId, fp, 'native-project-attach', {'id': identifier})
            return project

    async def refresh_native_project(self, owner, project_id):
        self.auth.require(owner, 'read')
        project = self.project(owner, project_id)
        if project['kind'] != 'native-openresearch':
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_PROJECT_REQUIRED')
        from .orx_research_session import OrxSessionError
        ref, pin = project['connectionRefs']['workspace'], project['connectionPins']['workspace']
        adapter, _ = self._native_adapter(owner, ref, pin)
        try:
            native = await adapter.inspect_project(owner, project['upstreamProjectId'])
        except OrxSessionError:
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_PROJECT_OBSERVATION_FAILED') from None
        self._native_adapter(owner, ref, pin)
        if native['projectIdentityHash'] != project['nativeProject']['projectIdentityHash']:
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_PROJECT_CHANGED')
        return {**project, 'nativeProject': native}

    def _managed_profile(self, owner, project, profile_id):
        """Resolve only operator-installed original custody; never accept JSON proof."""
        from .managed_orx_attachment import ManagedORXSessionProvider
        self.auth.require(owner, 'run')
        if project['kind'] != 'native-openresearch':
            raise HTTPException(409, 'OPENRESEARCH_NATIVE_PROJECT_REQUIRED')
        value = self.managed_profiles.get(profile_id)
        if not value or value.get('ownerId') != owner:
            raise HTTPException(404, 'OPENRESEARCH_MANAGED_PROFILE_NOT_FOUND')
        if not self.store.settings.fee_management_enabled or not self.store.settings.platform_paid_models_enabled:
            raise HTTPException(409, 'MANAGED_BUDGET_PROFILE_DISABLED: platform-paid hard-budget profiles are unavailable')
        ref, pin = project['connectionRefs']['workspace'], project['connectionPins']['workspace']
        adapter, current = self._native_adapter(owner, ref, pin)
        target = self.store.process_runtime.resources.targets.get(value['targetRef'])
        provider = getattr(target, 'provider', None)
        if type(provider) is not ManagedORXSessionProvider or owner not in target.owners or target.axis != 'compute':
            raise HTTPException(409, 'OPENRESEARCH_MANAGED_PROVIDER_UNAVAILABLE')
        contract = provider.contract
        expected = {'ownerId': owner, 'connectionRef': ref, 'connectionFingerprint': current['fingerprint'],
            'connectionRevision': current['revision'], 'connectionVersion': current['version'],
            'projectId': project['upstreamProjectId'], 'projectIdentityHash': project['nativeProject']['projectIdentityHash']}
        profiles = adapter.describe(owner)['sessionProfiles']
        native_profile = next((p for p in profiles if p['id'] == value['nativeProfileId']), None)
        if (any(contract.get(k) != v for k, v in expected.items())
                or value['connectionPin'] != pin or value['contractSha256'] != digest(contract)
                or value['sessionId'] != contract['sessionId']
                or native_profile is None or {k: v for k, v in native_profile.items() if k != 'id'} != contract['profile']):
            raise HTTPException(409, 'OPENRESEARCH_MANAGED_ATTACHMENT_CHANGED')
        application = self.store.applications.require_current(value['applicationRef'])
        from .managed_orx_profile import exact_input_schema
        mode = application.get('modes', {}).get(value['mode'], {})
        if mode.get('inputSchema') != exact_input_schema(contract):
            raise HTTPException(409, 'OPENRESEARCH_MANAGED_APPLICATION_SCHEMA_CHANGED')
        # Pure composition preflight: list only currently executable installed
        # bindings with a real usage commitment. It does not persist a proposal.
        inputs = self.store.composition._input('Verify original managed attachment', value['mode'], None,
            value['applicationRef'], None, value.get('connectionRefs', {}), input_values={'managedAttachment': contract})
        candidate = self.store.composition._candidate(owner, inputs, application)
        if candidate.get('status') != 'ready':
            raise HTTPException(409, 'OPENRESEARCH_MANAGED_PROFILE_UNAVAILABLE')
        self._validate_managed_plan(candidate, value, contract)
        return value, contract

    @staticmethod
    def _validate_managed_plan(plan, profile, contract):
        bindings = plan.get('executionBindings') or {}
        model = bindings.get('model', {})
        if (plan.get('inputValues', {}).get('managedAttachment') != contract
                or plan.get('applicationRef') != profile['applicationRef']
                or model.get('adapterId') != 'managed-orx-pause-model-v1'
                or model.get('config', {}).get('targetRef') != profile['targetRef']
                or plan.get('tools') != ['bounded_process_run']
                or any(spec.get('config', {}).get('targetRef') != profile['targetRef']
                    for spec in [bindings.get('environment', {}), *bindings.get('tools', [])])):
            raise HTTPException(409, 'OPENRESEARCH_MANAGED_PLAN_BINDING_INVALID')

    async def list_managed_profiles(self, owner, project_id):
        self.auth.require(owner, 'read')
        project = await self.refresh_native_project(owner, project_id)
        result = []
        for identifier in self.managed_profiles:
            try:
                profile, contract = self._managed_profile(owner, project, identifier)
            except (HTTPException, ValueError):
                continue
            result.append({'id': identifier, 'name': profile.get('name', identifier),
                'applicationRef': profile['applicationRef'], 'nativeProfileId': profile['nativeProfileId'],
                'upstreamSessionId': contract['sessionId'], 'profile': contract['profile'],
                'executionContract': 'managed-native-attachment-v1', 'liveEndToEndVerified': False,
                'kind': 'managed-connection-probe', 'modelRequests': 1, 'nativeTools': 'disabled',
                'nativeResearchAvailable': False})
        return result

    async def prepare_managed(self, owner, project_id, body):
        self.auth.require(owner, 'run')
        fp = digest({'action': 'managed-prepare', 'projectId': project_id, 'payload': body.model_dump(exclude={'requestId'})})
        with self.db.read() as conn:
            old = self.db.old(conn, self.commands, owner, body.requestId, fp)
        if old:
            return self.session(owner, project_id, old['id'])
        project = await self.refresh_native_project(owner, project_id)
        profile, contract = self._managed_profile(owner, project, body.profileId)
        # One transaction joins composition intent, immutable plan and session.
        # No plan review decision, native admission, allocation or provider call.
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, body.requestId, fp)
            if old:
                return self.session(owner, project_id, old['id'])
            key = digest({'owner': owner, 'request': body.requestId})
            proposal = self.store.composition.propose(owner, body.goal, mode=profile['mode'],
                application_ref=profile['applicationRef'], connection_refs=profile.get('connectionRefs', {}),
                request_id='or-propose:' + key, input_values={'managedAttachment': contract})
            plan = self.store.composition.accept(owner, proposal['id'], 'or-accept:' + key)
            self._validate_managed_plan(plan, profile, contract)
            identifier = 'ors-' + uuid4().hex
            value = {'id': identifier, 'projectId': project_id, 'goal': body.goal,
                'managedProfileId': body.profileId, 'nativeProfileId': profile['nativeProfileId'],
                'managedProfileSha256': digest(profile),
                'managedContractSha256': digest(contract), 'planId': plan['id'],
                'executionContract': 'managed-native-attachment-v1',
                'nativeRequestId': 'or-session:' + digest({'owner': owner, 'session': identifier}),
                'contextSource': 'original-native-project-session', 'upstreamSessionId': contract['sessionId'],
                'createdAt': now()}
            conn.execute(self.sessions.insert().values(id=identifier, owner_id=owner, project_id=project_id,
                body=value, state='prepared', task_id=None, created_at=value['createdAt']))
            self.db.record(conn, self.commands, owner, body.requestId, fp, 'managed-prepare', {'id': identifier})
        return self.session(owner, project_id, identifier)

    async def start_managed(self, owner, project_id, session_id, request_id):
        from .factory_api import InstanceRequest
        if self.factory is None:
            raise HTTPException(503, 'OPENRESEARCH_MANAGED_ADMISSION_UNAVAILABLE')
        self.auth.require(owner, 'run')
        with self.db.read() as conn:
            row = dict(self._session(conn, owner, project_id, session_id))
        if row['body'].get('executionContract') != 'managed-native-attachment-v1':
            raise HTTPException(409, 'OPENRESEARCH_MANAGED_SESSION_REQUIRED')
        project = await self.refresh_native_project(owner, project_id)
        profile, contract = self._managed_profile(owner, project, row['body']['managedProfileId'])
        if digest(profile) != row['body']['managedProfileSha256'] or digest(contract) != row['body']['managedContractSha256']:
            raise HTTPException(409, 'OPENRESEARCH_MANAGED_ATTACHMENT_CHANGED')
        plan = self.store.plan(row['body']['planId'], owner)
        self.store.require_plan_execution(owner, plan)
        fp = digest({'action': 'managed-start', 'projectId': project_id, 'sessionId': session_id})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fp)
            current = self._session(conn, owner, project_id, session_id)
            fresh = old is None and current['state'] == 'prepared'
            if old is None:
                self.db.record(conn, self.commands, owner, request_id, fp, 'managed-start', {'id': session_id})
            if fresh:
                conn.execute(self.sessions.update().where(self.sessions.c.id == session_id,
                    self.sessions.c.owner_id == owner).values(state='dispatch-intent'))
        if fresh:
            try:
                result = await self.factory.instantiate(owner, InstanceRequest(planId=plan['id'], requestId=row['body']['nativeRequestId']))
                self._link_managed(owner, session_id, result['id'])
            except BaseException:
                with self.db.write() as conn:
                    conn.execute(self.sessions.update().where(self.sessions.c.id == session_id,
                        self.sessions.c.owner_id == owner).values(state='unknown'))
                raise
        return self.reconcile(owner, project_id, session_id)

    def _link_managed(self, owner, session_id, task_id):
        task = self.store.task(task_id, owner)
        with self.db.write() as conn:
            row = conn.execute(select(self.sessions).where(self.sessions.c.id == session_id,
                self.sessions.c.owner_id == owner)).mappings().first()
            if row is None:
                raise HTTPException(404, 'OPENRESEARCH_SESSION_NOT_FOUND')
            if (task['plan_id'] != row['body']['planId'] or task['request_id'] != row['body']['nativeRequestId']
                    or row['task_id'] not in (None, task_id)):
                raise HTTPException(409, 'OPENRESEARCH_SESSION_IDENTITY_CHANGED')
            conn.execute(self.sessions.update().where(self.sessions.c.id == session_id,
                self.sessions.c.owner_id == owner).values(task_id=task_id, state='task-linked'))

    def _project(self, conn, owner, project_id):
        row = conn.execute(select(self.projects).where(self.projects.c.id == project_id,
            self.projects.c.owner_id == owner)).mappings().first()
        if row is None:
            raise HTTPException(404, 'OPENRESEARCH_PROJECT_NOT_FOUND')
        return row

    def _session(self, conn, owner, project_id, session_id):
        self._project(conn, owner, project_id)
        row = conn.execute(select(self.sessions).where(self.sessions.c.id == session_id,
            self.sessions.c.owner_id == owner, self.sessions.c.project_id == project_id)).mappings().first()
        if row is None:
            raise HTTPException(404, 'OPENRESEARCH_SESSION_NOT_FOUND')
        return row

    def create_project(self, owner, body: WorkspaceProjectCreate):
        self.auth.require(owner, 'run')
        payload = body.model_dump(exclude={'requestId'})
        if not body.name.strip():
            raise HTTPException(422, 'OPENRESEARCH_PROJECT_NAME_INVALID')
        pins = {}
        for name, reference in body.connectionRefs.items():
            self.store.connections._key(name)
            value = self.store.connections.inspect(owner, reference)
            pins[name] = self.store.connections.preflight(owner, reference, value['kind'])
        fp = digest({'action': 'project-create', 'payload': payload})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, body.requestId, fp)
            if old:
                return dict(self._project(conn, owner, old['id'])['body'])
            identifier = 'orp-' + uuid4().hex
            project = {'id': identifier, 'name': body.name.strip(), 'description': body.description,
                'kind': 'factory-workspace', 'connectionRefs': body.connectionRefs,
                'connectionPins': pins, 'upstreamProjectId': None, 'createdAt': now()}
            conn.execute(self.projects.insert().values(id=identifier, owner_id=owner,
                body=project, created_at=project['createdAt']))
            self.db.record(conn, self.commands, owner, body.requestId, fp, 'project-create', {'id': identifier})
            return project

    def list_projects(self, owner):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            return [dict(row['body']) for row in conn.execute(select(self.projects).where(
                self.projects.c.owner_id == owner).order_by(self.projects.c.created_at, self.projects.c.id)).mappings()]

    def project(self, owner, project_id):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            return dict(self._project(conn, owner, project_id)['body'])

    def list_sessions(self, owner, project_id):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            self._project(conn, owner, project_id)
            rows = list(conn.execute(select(self.sessions).where(self.sessions.c.owner_id == owner,
                self.sessions.c.project_id == project_id).order_by(self.sessions.c.created_at, self.sessions.c.id)).mappings())
        return [self._projection(owner, row) for row in rows]

    def _projection(self, owner, row):
        result = {**row['body'], 'state': row['state'], 'taskId': row['task_id'],
            'verificationStatus': 'not-live-verified', 'upstreamSessionId': None}
        if row['body'].get('executionContract') == 'managed-native-attachment-v1':
            plan = self.store.plan(row['body']['planId'], owner)
            try:
                authorization = self.store.plan_policy.status(owner, plan)
            except HTTPException as error:
                if error.status_code != 403:
                    raise
                # Read permission remains sufficient to inspect the original
                # mapping after execution authority is revoked. Never grant a
                # replacement execution/review capability from this projection.
                authorization = {'executionAllowed': False, 'reviewRequired': False,
                    'reviewRequestSupported': False, 'nativeToolConfirmationRequired': True,
                    'policy': self.store.plan_policy.current(), 'reason': 'Current execution permission is unavailable',
                    'code': 'EXECUTION_PERMISSION_REVOKED', 'approval': None}
            result.update(upstreamSessionId=row['body']['upstreamSessionId'], plan=plan,
                authorization=authorization, taskUrl=None)
            if row['task_id']:
                task = self.store.task(row['task_id'], owner)
                result.update(state=task['body'].get('lastStatus', task['admission']),
                    admission=task['admission'], outcomeSource='persisted_factory_observation',
                    taskUrl='/jobs/' + task['id'])
            return result
        if row['task_id']:
            run = self.research.projection(owner, row['task_id'])
            result.update(state=run['status'], research=run)
        return result

    def session(self, owner, project_id, session_id):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            row = dict(self._session(conn, owner, project_id, session_id))
        return self._projection(owner, row)

    def _selection(self, owner, project, preset):
        # Selection is not cosmetic: reject any chosen connection that the
        # executable workload will not actually use. Never mutate trusted presets.
        if project['kind'] == 'native-openresearch':
            raise HTTPException(409, 'NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED')
        refs = project['connectionRefs']
        if refs and refs != preset.connection_refs:
            raise HTTPException(409, 'OPENRESEARCH_WORKLOAD_CONNECTION_MISMATCH')
        for name, pin in project['connectionPins'].items():
            self.store.connections.preflight(owner, refs[name], pin['kind'],
                expected_revision=pin['revision'], expected_fingerprint=pin['fingerprint'],
                expected_version=pin['version'])
        if self.research.unavailable(preset):
            raise HTTPException(409, 'OPENRESEARCH_WORKLOAD_UNAVAILABLE')

    async def create_session(self, owner, project_id, body: WorkspaceSessionCreate):
        self.auth.require(owner, 'run')
        fp = digest({'action': 'session-create', 'projectId': project_id, 'payload': body.model_dump(exclude={'requestId'})})
        with self.db.write() as conn:
            project = dict(self._project(conn, owner, project_id)['body'])
            old = self.db.old(conn, self.commands, owner, body.requestId, fp)
            if old:
                row = dict(self._session(conn, owner, project_id, old['id']))
            else:
                preset = self.research.preset(owner, body.workloadPresetId)
                self._selection(owner, project, preset)
                identifier = 'ors-' + uuid4().hex
                native_request = 'or-session:' + digest({'owner': owner, 'session': identifier})
                value = {'id': identifier, 'projectId': project_id, 'goal': body.goal,
                    'workloadPresetId': preset.id, 'workloadFingerprint': preset.fingerprint,
                    'executionContract': body.executionContract, 'nativeRequestId': native_request,
                    'contextSource': 'approved-workload-preset', 'createdAt': now()}
                conn.execute(self.sessions.insert().values(id=identifier, owner_id=owner, project_id=project_id,
                    body=value, state='dispatch-intent', task_id=None, created_at=value['createdAt']))
                self.db.record(conn, self.commands, owner, body.requestId, fp, 'session-create', {'id': identifier})
                row = None
        if row is not None:
            # An earlier invocation may have crossed admission. Observe only;
            # even a missing receipt never authorizes a second submit.
            return self.reconcile(owner, project_id, row['id'])
        try:
            run = await self.research.start(owner, body.workloadPresetId, body.goal, native_request,
                expected_preset_fingerprint=value['workloadFingerprint'])
        except BaseException:
            with self.db.write() as conn:
                conn.execute(self.sessions.update().where(self.sessions.c.id == identifier,
                    self.sessions.c.owner_id == owner).values(state='unknown'))
            raise
        self._link(owner, identifier, run['id'])
        return self.session(owner, project_id, identifier)

    def _link(self, owner, session_id, task_id):
        # Projection performs original owner/task validation before any link.
        self.research.projection(owner, task_id)
        run = self.research.row(owner, task_id)['body']
        with self.db.write() as conn:
            row = conn.execute(select(self.sessions).where(self.sessions.c.id == session_id,
                self.sessions.c.owner_id == owner)).mappings().first()
            if row is None:
                raise HTTPException(404, 'OPENRESEARCH_SESSION_NOT_FOUND')
            intent = row['body']
            expected = {'id': task_id, 'ownerId': owner, 'presetId': intent['workloadPresetId'],
                'presetFingerprint': intent['workloadFingerprint'], 'requestId': intent['nativeRequestId'],
                'goal': intent['goal']}
            if any(run.get(key) != value for key, value in expected.items()):
                raise HTTPException(409, 'OPENRESEARCH_SESSION_IDENTITY_CHANGED')
            if row['task_id'] is not None and row['task_id'] != task_id:
                raise HTTPException(409, 'OPENRESEARCH_SESSION_IDENTITY_CHANGED')
            conn.execute(self.sessions.update().where(self.sessions.c.id == session_id,
                self.sessions.c.owner_id == owner).values(task_id=task_id, state='task-linked'))

    def reconcile(self, owner, project_id, session_id):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            row = dict(self._session(conn, owner, project_id, session_id))
        if row['body'].get('executionContract') == 'managed-native-attachment-v1':
            if row['task_id'] is None and row['state'] != 'prepared':
                try:
                    task = self.store.task_for_request(row['body']['nativeRequestId'], owner)
                except HTTPException as error:
                    if error.status_code != 404:
                        raise
                else:
                    self._link_managed(owner, session_id, task['id'])
            return self.session(owner, project_id, session_id)
        if row['task_id'] is None:
            run = self.research.recover(owner, row['body']['nativeRequestId'])
            if run is not None:
                self._link(owner, session_id, run['id'])
        return self.session(owner, project_id, session_id)

    async def cancel(self, owner, project_id, session_id, request_id):
        self.auth.require(owner, 'run')
        value = self.reconcile(owner, project_id, session_id)
        if value['taskId'] is None:
            raise HTTPException(409, 'OPENRESEARCH_DISPATCH_RECONCILIATION_REQUIRED')
        if value.get('executionContract') == 'managed-native-attachment-v1':
            from .control_commands import ControlCommand
            if self.factory is None:
                raise HTTPException(503, 'OPENRESEARCH_MANAGED_ADMISSION_UNAVAILABLE')
            await self.factory.commands.submit(owner, value['taskId'], ControlCommand(commandId=request_id, action='cancel'))
        else:
            await self.research.cancel(owner, value['taskId'], request_id)
        return self.session(owner, project_id, session_id)


def openresearch_workspace_router(auth, service):
    router = APIRouter(prefix='/api/factory/openresearch', tags=['openresearch-workspace'])

    @router.get('/capabilities')
    def capabilities(request: Request):
        return service.capabilities(auth.user(request)['id'])

    @router.get('/requests/{request_id}')
    def request_result(request_id: str, request: Request):
        return service.request_result(auth.user(request)['id'], request_id)

    @router.get('/projects')
    def projects(request: Request):
        return service.list_projects(auth.user(request)['id'])

    @router.post('/projects', status_code=201)
    def create_project(body: WorkspaceProjectCreate, request: Request):
        return service.create_project(auth.user(request)['id'], body)

    @router.get('/native-projects')
    async def native_projects(connectionRef: str, request: Request):
        return await service.native_projects(auth.user(request)['id'], connectionRef)

    @router.post('/projects/attach', status_code=201)
    async def attach_native_project(body: WorkspaceNativeAttach, request: Request):
        return await service.attach_native_project(auth.user(request)['id'], body)

    @router.post('/projects/{project_id}/refresh')
    async def refresh_native_project(project_id: str, request: Request):
        return await service.refresh_native_project(auth.user(request)['id'], project_id)

    @router.get('/projects/{project_id}')
    def project(project_id: str, request: Request):
        return service.project(auth.user(request)['id'], project_id)

    @router.get('/projects/{project_id}/managed-profiles')
    async def managed_profiles(project_id: str, request: Request):
        return await service.list_managed_profiles(auth.user(request)['id'], project_id)

    @router.post('/projects/{project_id}/sessions/prepare-managed', status_code=201)
    async def prepare_managed(project_id: str, body: WorkspaceManagedPrepare, request: Request):
        return await service.prepare_managed(auth.user(request)['id'], project_id, body)

    @router.post('/projects/{project_id}/sessions/{session_id}/start', status_code=202)
    async def start_managed(project_id: str, session_id: str, body: WorkspaceCommand, request: Request):
        return await service.start_managed(auth.user(request)['id'], project_id, session_id, body.requestId)

    @router.get('/projects/{project_id}/sessions')
    def sessions(project_id: str, request: Request):
        return service.list_sessions(auth.user(request)['id'], project_id)

    @router.post('/projects/{project_id}/sessions', status_code=202)
    async def create_session(project_id: str, body: WorkspaceSessionCreate, request: Request):
        return await service.create_session(auth.user(request)['id'], project_id, body)

    @router.get('/projects/{project_id}/sessions/{session_id}')
    def session(project_id: str, session_id: str, request: Request):
        return service.session(auth.user(request)['id'], project_id, session_id)

    @router.post('/projects/{project_id}/sessions/{session_id}/reconcile')
    def reconcile(project_id: str, session_id: str, request: Request):
        return service.reconcile(auth.user(request)['id'], project_id, session_id)

    @router.post('/projects/{project_id}/sessions/{session_id}/cancel')
    async def cancel(project_id: str, session_id: str, body: WorkspaceCommand, request: Request):
        return await service.cancel(auth.user(request)['id'], project_id, session_id, body.requestId)

    return router

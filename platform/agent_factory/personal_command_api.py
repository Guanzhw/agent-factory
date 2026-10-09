"""Preparation/read ingress only; mutations run through shared Factory admission."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .factory_api import InstanceRequest
from .personal_command_profile import APPLICATION_ID, PROJECT_APPLICATION_ID, CONTRACT, command_from_plan, reconcile_command
from .store import canonical


class PrepareCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_.:-]+$')
    action: Literal['create', 'prompt', 'interrupt']
    connectionRef: str | None = Field(default=None, max_length=200)
    nativeProjectId: str | None = Field(default=None, max_length=200)
    sessionId: str | None = Field(default=None, max_length=200)
    title: str = Field(default='Factory personal session', min_length=1, max_length=120)
    text: str = Field(default='', max_length=16000)
    agent: str | None = Field(default=None, max_length=200)

    @model_validator(mode='after')
    def scope(self):
        if self.action == 'create':
            if not self.connectionRef or not self.nativeProjectId or self.sessionId or self.text or self.agent:
                raise ValueError('Create requires connection/project only')
        elif not self.sessionId or self.connectionRef or self.nativeProjectId:
            raise ValueError('Prompt/interrupt require an existing personal session')
        if self.action == 'prompt' and not self.text.strip(): raise ValueError('Prompt text required')
        if self.action == 'interrupt' and (self.text or self.agent): raise ValueError('Interrupt takes no prompt')
        return self


class AttachSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_.:-]+$')
    connectionRef: str = Field(min_length=1, max_length=200)
    nativeProjectId: str = Field(min_length=1, max_length=200)
    nativeSessionId: str = Field(min_length=1, max_length=200)


class RebindSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_.:-]+$')
    connectionRef: str = Field(min_length=1, max_length=200)
    expectedOldFingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    expectedNewFingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class StartCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    planId: str = Field(min_length=1, max_length=100)


def deny_direct_admission(owner, intent):
    raise HTTPException(403, 'PERSONAL_NATIVE_COMMAND_REQUIRED')


class PersonalCommandAPI:
    def __init__(self, store, auth, factory):
        from .personal_agent_sessions import PersonalAgentSessions
        self.store, self.auth, self.factory = store, auth, factory
        self.sessions = PersonalAgentSessions(store.connections, admission=deny_direct_admission,
            observed=lambda owner, request_id: reconcile_command(store, self.sessions, owner, request_id))
        from .personal_orx_projects import PersonalOrxProjects
        self.projects = PersonalOrxProjects(store.connections, admission=deny_direct_admission)
        self.router = APIRouter(prefix='/api/factory/personal-agent')
        self.routes()

    def prepare(self, owner, body):
        self.auth.require(owner, 'run')
        if body.action == 'create':
            project = self.sessions.project(owner, body.connectionRef)
            if project['nativeProjectId'] != body.nativeProjectId:
                raise HTTPException(409, 'PERSONAL_PROJECT_MISMATCH')
            pin, project_id, native_session = project['connectionPin'], body.nativeProjectId, ''
        else:
            session = self.sessions.inspect(owner, body.sessionId)
            pin, project_id, native_session = session['connectionPin'], session['nativeProjectId'], session['nativeSessionId']
            if not native_session: raise HTTPException(409, 'PERSONAL_SESSION_ACK_UNKNOWN')
            # Current owner/pin/capability is rechecked now and again by the native tool.
            self.sessions._handle(owner, pin, capability='session:' + body.action)
        values = {'executionContract': CONTRACT, 'action': body.action, 'requestId': body.requestId,
            'connectionPin': canonical(pin), 'nativeProjectId': project_id, 'nativeSessionId': native_session,
            'factorySessionId': body.sessionId or '', 'title': body.title, 'text': body.text, 'agent': body.agent or ''}
        plan = self.store.admit_plan(owner, body.requestId, {'personalCommand': body.model_dump()},
            lambda: self.store.composition.create_plan(owner, 'Personal remote agent ' + body.action,
                'personal-command', APPLICATION_ID, request_id=body.requestId, input_values=values))
        return {'executionContract': CONTRACT, 'plan': plan,
            'authorization': self.store.plan_policy.status(owner, plan),
            'commandSuccessMeans': 'remote-command-acceptance-only', 'remoteStopVerified': False,
            'remoteBudgetEnforcement': 'advisory'}

    async def prepared_request(self, owner, request_id):
        self.auth.require(owner, 'read')
        rows = self.store.sql('SELECT plan_id FROM af_plan_requests WHERE owner_id=:owner AND request_id=:request',
            owner=owner, request=request_id)
        if not rows: raise HTTPException(404, 'PERSONAL_PREPARATION_NOT_FOUND')
        plan = self.store.plan(rows[0]['plan_id'], owner)
        if plan.get('application') not in {APPLICATION_ID, PROJECT_APPLICATION_ID}: raise HTTPException(404, 'PERSONAL_PREPARATION_NOT_FOUND')
        service = self.projects if plan['application'] == PROJECT_APPLICATION_ID else self.sessions
        result = {'requestId': request_id, 'plan': plan, 'authorization': self.store.plan_policy.status(owner, plan),
            'job': None, 'receipt': None, 'nativeRunId': None}
        try:
            result['receipt'] = service.request_result(owner, request_id)
        except HTTPException as error:
            if error.status_code != 404: raise
        else:
            reconcile_command(self.store, service, owner, request_id)
        try:
            task = self.store.task_for_request('personal:' + plan['id'], owner)
        except HTTPException as error:
            if error.status_code != 404: raise
        else:
            result['nativeRunId'] = task['run_id']
            result['job'] = (await self.factory.detail(task))['job']
        return result

    async def start(self, owner, plan_id):
        plan = self.store.plan(plan_id, owner)
        if plan.get('application') not in {APPLICATION_ID, PROJECT_APPLICATION_ID} or plan.get('mode') != 'personal-command':
            raise HTTPException(409, 'PERSONAL_COMMAND_PLAN_REQUIRED')
        if plan['application'] == PROJECT_APPLICATION_ID:
            command = command_from_plan(plan)
            self.projects.require_approval(owner, command['requestId'], plan_id, command['projectBundle'])
        return await self.factory.instantiate(owner, InstanceRequest(planId=plan_id, requestId='personal:' + plan_id))

    def routes(self):
        from .personal_orx_projects import PrepareProject, ProjectDecision, ConnectProject, prepare_project
        def owner(request): return self.auth.user(request)['id']
        @self.router.get('/capabilities')
        def capabilities(request: Request):
            self.auth.require(owner(request), 'read')
            return {'executionContract': CONTRACT, 'applicationId': APPLICATION_ID, 'nativeQueue': True,
                'remoteBudgetEnforcement': 'advisory', 'remoteStopVerified': False, 'liveEndToEndVerified': False,
                'planPolicy': self.store.plan_policy.current(), 'planReviewDeterminedAtPreparation': True}
        @self.router.get('/projects')
        def projects(request: Request, connectionRef: str):
            self.auth.require(owner(request), 'read')
            return self.sessions.project(owner(request), connectionRef)
        @self.router.get('/native-sessions')
        def native_sessions(request: Request, connectionRef: str):
            return self.sessions.native_sessions(owner(request), connectionRef)
        @self.router.post('/sessions/attach')
        def attach(body: AttachSession, request: Request):
            return self.sessions.attach(owner(request), body.connectionRef, body.nativeProjectId,
                body.nativeSessionId, body.requestId)
        @self.router.get('/sessions')
        def sessions(request: Request, connectionRef: str | None = None):
            return self.sessions.list(owner(request), connection_ref=connectionRef)
        @self.router.get('/sessions/{session_id}/rebind-preview')
        def preview_rebind(session_id: str, request: Request,
                connectionRef: str = Query(min_length=1, max_length=200),
                expectedOldFingerprint: str = Query(pattern=r'^[a-f0-9]{64}$')):
            actor = owner(request)
            self.auth.require(actor, 'read')
            return self.sessions.preview_rebind(actor, session_id, connectionRef, expectedOldFingerprint)
        @self.router.post('/sessions/{session_id}/rebind')
        def rebind(session_id: str, body: RebindSession, request: Request):
            actor = owner(request)
            self.auth.require(actor, 'run')
            return self.sessions.rebind(actor, session_id, body.connectionRef, body.requestId,
                expected_old_fingerprint=body.expectedOldFingerprint,
                expected_new_fingerprint=body.expectedNewFingerprint)
        @self.router.get('/sessions/{session_id}')
        def session(session_id: str, request: Request, refresh: bool = False):
            return self.sessions.inspect(owner(request), session_id, refresh=refresh)
        @self.router.get('/requests/{request_id}')
        def recover(request_id: str, request: Request):
            result = self.sessions.request_result(owner(request), request_id)
            reconcile_command(self.store, self.sessions, owner(request), request_id)
            return result
        @self.router.get('/commands/requests/{request_id}')
        async def prepared_request(request_id: str, request: Request):
            return await self.prepared_request(owner(request), request_id)
        @self.router.post('/commands/prepare')
        def prepare(body: PrepareCommand, request: Request): return self.prepare(owner(request), body)
        @self.router.post('/commands/start')
        async def start(body: StartCommand, request: Request): return await self.start(owner(request), body.planId)
        @self.router.post('/project-commands/prepare')
        def prepare_creation(body: PrepareProject, request: Request):
            return prepare_project(self, owner(request), body)
        @self.router.post('/project-commands/{request_id}/decision')
        def decide_creation(request_id: str, body: ProjectDecision, request: Request):
            self.projects.decide(owner(request), request_id, body.previewHash, body.approved)
            return self.projects.request_result(owner(request), request_id)
        @self.router.get('/project-commands/{request_id}')
        def recover_creation(request_id: str, request: Request, refresh: bool = False):
            result = self.projects.request_result(owner(request), request_id, refresh=refresh)
            reconcile_command(self.store, self.projects, owner(request), request_id)
            return result
        @self.router.post('/project-commands/{request_id}/connect')
        def connect_creation(request_id: str, body: ConnectProject, request: Request):
            return self.projects.connect(owner(request), request_id, harness=body.harness, model=body.model)

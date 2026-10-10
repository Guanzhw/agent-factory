"""Owner-approved native ORX project creation on the existing Factory command path.

Not a queue, research loop or upstream idempotency emulation. An unknown POST
remains unknown; recovery reads the original reservation and lists candidates.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from .personal_agent_sessions import PersonalAgentSessions
from .personal_command_profile import CONTRACT, PROJECT_APPLICATION_ID
from .store import canonical, digest, now

DISCLOSURE_VERSION = 'native-orx-create-consent-v2'


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=512)
    source: str = Field(pattern=r'^(empty|existing|clone|paper)$')
    cloneUrl: str | None = Field(default=None, max_length=512)
    paperId: str | None = Field(default=None, max_length=80)

    @model_validator(mode='after')
    def validate_source(self):
        if self.name != self.name.strip() or self.path != self.path.strip() or any(ord(c) < 32 for c in self.name + self.path):
            raise ValueError('Use an exact nonempty name and remote path')
        if not (self.path.startswith('/') or re.match(r'^[A-Za-z]:[\\/]', self.path)):
            raise ValueError('Absolute remote path required')
        if self.source == 'clone':
            if not self.cloneUrl or not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', self.cloneUrl) or self.paperId:
                raise ValueError('Public HTTPS GitHub repository required')
        elif self.cloneUrl:
            raise ValueError('Clone URL is only valid for clone source')
        if self.source == 'paper':
            if not self.paperId or not re.fullmatch(r'[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?', self.paperId):
                raise ValueError('Explicit arXiv paper ID required')
        elif self.paperId:
            raise ValueError('Paper ID is only valid for paper source')
        return self


def native_request(value):
    body = ProjectInput.model_validate(value)
    return {'name': body.name, 'path': body.path, 'createFolder': body.source != 'existing',
        'requireNewFolder': body.source != 'existing', 'initializeGit': body.source in {'empty', 'paper'},
        'cloneUrl': body.cloneUrl, 'paperId': body.paperId, 'locale': 'zh',
        # Rust member versus serde(rename_all="camelCase") wire spelling.
        # Keep the explicit internal false and the actual recognized wire false.
        'github_sync_enabled': False, 'githubSyncEnabled': False}


def valid_native_request(value):
    if type(value) is not dict: return False
    try:
        source = 'clone' if value.get('cloneUrl') else 'paper' if value.get('paperId') else 'empty' if value.get('createFolder') else 'existing'
        expected = native_request({'name': value.get('name'), 'path': value.get('path'), 'source': source,
            'cloneUrl': value.get('cloneUrl'), 'paperId': value.get('paperId')})
        # bool/int equality must not weaken the exact disabled-sync contract.
        return canonical(value) == canonical(expected)
    except (ValueError, TypeError):
        return False


def disclosure(request):
    clone = bool(request['cloneUrl'])
    return {'version': DISCLOSURE_VERSION, 'remotePath': request['path'], 'repository': request['cloneUrl'],
        'paperId': request['paperId'], 'remoteWrites': 'clone-into-new-or-existing-empty-folder-and-project' if clone
            else 'register-existing-folder' if not request['createFolder'] else 'create-new-folder-and-project',
        'clone': clone, 'paperDownload': bool(request['paperId']),
        'gitInitialization': request['initializeGit'], 'githubSyncEnabled': False,
        'pathResolution': 'upstream-clone-target-symlinks-followed-no-new-folder-guarantee' if clone
            else 'upstream-canonical-path-and-enclosing-git-root',
        'starterSuggestions': 'may-request-four-project-chat-suggestions',
        'modelInput': ['README', 'selected-code', 'file-list', 'paper-summary'],
        'modelSelection': 'remote-preferred-or-ready-harness', 'billing': 'owner-remote-account-possible-cost',
        'hardBudgetEnforced': False, 'automaticExperiment': False,
        'emptyCacheHitOrNoHarness': 'may-skip-model-request', 'unknownResponse': 'read-only-reconcile-never-resend'}


def project_review_summary(plan):
    """Read the exact admitted disclosure; never resolve or project credentials."""
    if plan.get('application') != PROJECT_APPLICATION_ID: return None
    from .personal_command_profile import command_from_plan
    command = command_from_plan(plan)
    bundle = command['projectBundle']; request = bundle['request']
    source = 'clone' if request['cloneUrl'] else 'paper' if request['paperId'] else 'empty' if request['createFolder'] else 'existing'
    return {'schema': 'native-orx-project-review-v1', 'requestId': command['requestId'],
        'previewHash': bundle['previewHash'],
        'project': {'name': request['name'], 'path': request['path'], 'source': source,
            'cloneUrl': request['cloneUrl'], 'paperId': request['paperId']},
        'effects': deepcopy(bundle['disclosure']),
        'billing': {'controllerLedgerScope': 'local-controller-only',
            'remoteUsageStatus': 'unknown', 'remoteCostStatus': 'unknown',
            'remoteBilling': bundle['disclosure']['billing'],
            'remoteCostIncludedInUsageBudget': False, 'hardRemoteBudgetEnforced': False},
        'ownerConsentSeparate': True}


class PersonalOrxProjects:
    def __init__(self, connections, *, admission):
        self.connections, self.store, self.auth = connections, connections.store, connections.auth
        self.sessions = PersonalAgentSessions(connections, admission=admission)
        self.commands = self.sessions.commands
        metadata = MetaData()
        self.consents = Table('af_personal_orx_project_consents', metadata,
            Column('owner_id', String, primary_key=True), Column('request_id', String, primary_key=True),
            Column('plan_id', String, nullable=False), Column('bundle', JSON, nullable=False),
            Column('fingerprint', String, nullable=False), Column('state', String, nullable=False),
            Column('updated_at', String, nullable=False))
        self.selections = Table('af_personal_orx_project_selections', metadata,
            Column('owner_id', String, primary_key=True), Column('request_id', String, primary_key=True),
            Column('fingerprint', String, nullable=False), Column('state', String, nullable=False),
            Column('failure_status', JSON), Column('created_at', String, nullable=False))
        metadata.create_all(self.store.engine)

    def _command(self, owner, request_id): return self.sessions._command(owner, request_id)

    def bundle(self, owner, reference, values):
        self.auth.require(owner, 'run')
        handle, pin = self.sessions._handle(owner, reference=reference, capability='project:create')
        if handle.namespace != 'native-openresearch' or not handle.configuration.get('projectCreation'):
            raise HTTPException(409, 'PERSONAL_ORX_CREATION_CONNECTION_REQUIRED')
        request = native_request(values)
        result = {'request': request, 'disclosure': disclosure(request), 'connectionPin': pin}
        return {**result, 'previewHash': digest(result)}

    @staticmethod
    def validate_bundle(bundle):
        if (type(bundle) is not dict or set(bundle) != {'request', 'disclosure', 'connectionPin', 'previewHash'}
                or not valid_native_request(bundle['request']) or bundle['disclosure'] != disclosure(bundle['request'])
                or bundle['previewHash'] != digest({k: v for k, v in bundle.items() if k != 'previewHash'})):
            raise HTTPException(409, 'PERSONAL_PROJECT_PREVIEW_CHANGED')
        return bundle

    def record(self, owner, request_id, plan, bundle):
        self.validate_bundle(bundle)
        with self.store.engine.begin() as conn:
            self.connections._lock(conn, 'personal-orx-project:' + owner)
            old = conn.execute(select(self.consents).where(self.consents.c.owner_id == owner,
                self.consents.c.request_id == request_id)).mappings().first()
            if old:
                if old['plan_id'] != plan['id'] or old['fingerprint'] != digest(bundle):
                    raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            else:
                conn.execute(self.consents.insert().values(owner_id=owner, request_id=request_id,
                    plan_id=plan['id'], bundle=bundle, fingerprint=digest(bundle), state='awaiting', updated_at=now()))
        return self.consent(owner, request_id)

    def consent(self, owner, request_id):
        self.auth.require(owner, 'read'); self.connections._key(request_id)
        with self.store.engine.connect() as conn:
            row = conn.execute(select(self.consents).where(self.consents.c.owner_id == owner,
                self.consents.c.request_id == request_id)).mappings().first()
        if row is None:
            # A crash can occur after immutable plan admission but before the
            # consent row commits. Recover its preview without a GET mutation;
            # only a new explicit decision can materialize awaiting consent.
            if not callable(getattr(self.store, 'sql', None)):
                raise HTTPException(404, 'PERSONAL_PROJECT_REQUEST_NOT_FOUND')
            plans = self.store.sql('SELECT plan_id FROM af_plan_requests WHERE owner_id=:owner AND request_id=:request',
                owner=owner, request=request_id)
            if not plans: raise HTTPException(404, 'PERSONAL_PROJECT_REQUEST_NOT_FOUND')
            plan = self.store.plan(plans[0]['plan_id'], owner)
            if plan.get('application') != PROJECT_APPLICATION_ID:
                raise HTTPException(404, 'PERSONAL_PROJECT_REQUEST_NOT_FOUND')
            bundle = self.validate_bundle(json.loads(plan['inputValues']['text']))
            return {'owner_id': owner, 'request_id': request_id, 'plan_id': plan['id'],
                'bundle': bundle, 'fingerprint': digest(bundle), 'state': 'awaiting', '_unrecorded': True}
        if digest(row['bundle']) != row['fingerprint']: raise HTTPException(409, 'PERSONAL_PROJECT_INTEGRITY')
        self.validate_bundle(row['bundle'])
        return dict(row)

    def decide(self, owner, request_id, preview_hash, approved):
        self.auth.require(owner, 'run')
        row = self.consent(owner, request_id)
        if row['bundle']['previewHash'] != preview_hash: raise HTTPException(409, 'PERSONAL_PROJECT_PREVIEW_CHANGED')
        if row.get('_unrecorded'):
            row = self.record(owner, request_id, self.store.plan(row['plan_id'], owner), row['bundle'])
        target = 'approved' if approved else 'cancelled'
        with self.store.engine.begin() as conn:
            self.connections._lock(conn, 'personal-orx-project:' + owner)
            current = conn.execute(select(self.consents.c.state).where(self.consents.c.owner_id == owner,
                self.consents.c.request_id == request_id)).scalar_one()
            if current != target and current not in {'awaiting', 'approved'}:
                raise HTTPException(409, 'PERSONAL_PROJECT_DECISION_FROZEN')
            changed = conn.execute(self.consents.update().where(self.consents.c.owner_id == owner,
                self.consents.c.request_id == request_id, self.consents.c.state == current).values(state=target, updated_at=now()))
            if changed.rowcount != 1: raise HTTPException(409, 'PERSONAL_PROJECT_DECISION_FROZEN')
        return self.consent(owner, request_id)

    def require_approval(self, owner, request_id, plan_id, bundle):
        self.auth.require(owner, 'run')
        row = self.consent(owner, request_id)
        if row['state'] not in {'approved', 'dispatch_started'} or row['plan_id'] != plan_id or row['bundle'] != bundle:
            raise HTTPException(409, 'PERSONAL_PROJECT_EXPLICIT_APPROVAL_REQUIRED')
        return row

    def create(self, owner, command):
        bundle = self.validate_bundle(command['projectBundle'])
        request_id = command['requestId']
        old = self._command(owner, request_id)
        if old:
            if old['intent'].get('projectBundle') != bundle: raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            return self.request_result(owner, request_id)
        handle, _ = self.sessions._handle(owner, bundle['connectionPin'], capability='project:create')
        baseline = handle.creation_projects()
        intent = {'executionContract': CONTRACT, 'action': 'project_create', 'requestId': request_id,
            'connectionPin': bundle['connectionPin'], 'projectBundle': bundle,
            'baselineProjectIds': [p['nativeProjectId'] for p in baseline]}
        identity = self.sessions._authorize(owner, intent)
        self.require_approval(owner, request_id, identity['planId'], bundle)
        with self.store.engine.begin() as conn:
            self.connections._lock(conn, 'personal-orx-project:' + owner)
            previous = conn.execute(select(self.commands.c.intent).where(self.commands.c.owner_id == owner,
                self.commands.c.request_id == request_id)).scalar_one_or_none()
            if previous is not None:
                if previous.get('action') != 'project_create' or previous.get('projectBundle') != bundle:
                    raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
                reserved = False
            else:
                conn.execute(self.commands.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=digest(intent), intent=intent, identity=identity, identity_hash=digest(identity),
                    state='ack_unknown', result=None, created_at=now()))
                reserved = True
        if reserved:
            try:
                def before_send():
                    self.sessions._authorize(owner, intent, identity)
                    self.require_approval(owner, request_id, identity['planId'], bundle)
                    with self.store.engine.begin() as conn:
                        claimed = conn.execute(self.consents.update().where(self.consents.c.owner_id == owner,
                            self.consents.c.request_id == request_id, self.consents.c.state == 'approved',
                            self.consents.c.fingerprint == digest(bundle)).values(state='dispatch_started', updated_at=now()))
                        if claimed.rowcount != 1: raise HTTPException(409, 'PERSONAL_PROJECT_DISPATCH_FROZEN')
                result = handle.create_project(bundle['request'], before_send=before_send)
                with self.store.engine.begin() as conn:
                    conn.execute(self.commands.update().where(self.commands.c.owner_id == owner,
                        self.commands.c.request_id == request_id, self.commands.c.state == 'ack_unknown').values(
                            state='acknowledged', result=result))
            except Exception:
                # Remote diagnostics can contain secrets; never persist or return them.
                pass
        return self.request_result(owner, request_id)

    def request_result(self, owner, request_id, *, refresh=False):
        row = self._command(owner, request_id)
        consent = self.consent(owner, request_id)
        if row is not None and row['intent'].get('action') != 'project_create':
            raise HTTPException(404, 'PERSONAL_PROJECT_REQUEST_NOT_FOUND')
        candidates = []
        if refresh and row is not None and row['state'] == 'ack_unknown':
            handle, _ = self.sessions._handle(owner, row['intent']['connectionPin'], capability='project:read')
            candidates = [p for p in handle.creation_projects() if p['nativeProjectId'] not in row['intent']['baselineProjectIds']]
        return {'requestId': request_id, 'action': 'project_create', 'state': row['state'] if row else consent['state'],
            'consentState': consent['state'], 'planId': consent['plan_id'], 'preview': consent['bundle'],
            'result': row['result'] if row else None, 'factoryIdentity': row['identity'] if row else None,
            'candidates': candidates, 'candidateCorrelation': 'unproven-does-not-settle-original-request',
            'liveEndToEndVerified': False}

    def connect(self, owner, request_id, *, harness, model):
        self.auth.require(owner, 'run')
        result = self.request_result(owner, request_id)
        if result['state'] != 'acknowledged': raise HTTPException(409, 'PERSONAL_PROJECT_ACK_UNKNOWN')
        row = self.consent(owner, request_id)
        handle, _ = self.sessions._handle(owner, row['bundle']['connectionPin'], capability='project:read')
        # Opaque credential references retain owner/provider/origin/revision binding.
        config = {k: v for k, v in handle.configuration.items() if k in {'origin', 'authMode', 'credentialRef', 'credentialRevision'}}
        config.update(projectId=result['result']['nativeProjectId'], sessionDefaults={'harness': harness, 'model': model})
        suffix = digest({'request': request_id, 'harness': harness, 'model': model})[:40]
        remote = self.connections.personal.configure(owner, handle.provider.provider_id, config, 'created-config:' + suffix)
        self.connections.personal.verify(owner, remote['registrationRef'], 'created-verify:' + suffix)
        return self.connections.bind(owner, remote['registrationRef'], 'created-bind:' + suffix)

    def existing_projects(self, owner, reference):
        self.auth.require(owner, 'read')
        handle, _ = self.sessions._handle(owner, reference=reference, capability='project:read')
        return handle.creation_projects()

    def select_existing(self, owner, reference, project_id, request_id):
        # A receipt before validation distinguishes terminal failures from a
        # lost response. Reserving the key never admits research/model IO.
        self.auth.require(owner, 'read')
        self.connections._key(request_id)
        fingerprint = digest({'connectionRef': reference, 'nativeProjectId': project_id})
        with self.connections._write() as conn:
            self.connections._lock(conn, owner)
            row = conn.execute(select(self.selections).where(self.selections.c.owner_id == owner,
                self.selections.c.request_id == request_id)).mappings().first()
            if row:
                if row['fingerprint'] != fingerprint: raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
                if row['state'] == 'failed': raise HTTPException(row['failure_status'], 'PERSONAL_PROJECT_SELECTION_FAILED')
                if row['state'] != 'complete': raise HTTPException(409, 'PERSONAL_PROJECT_SELECTION_PENDING')
            else:
                conn.execute(self.selections.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=fingerprint, state='pending', created_at=now()))
        if row: return self.selected_request(owner, request_id)
        try:
            result = self._select_existing(owner, reference, project_id, request_id)
        except HTTPException as error:
            self._selection_state(owner, request_id, 'failed', error.status_code)
            # Upstream diagnostics or secrets are never stored/projected.
            raise HTTPException(error.status_code, 'PERSONAL_PROJECT_SELECTION_FAILED') from None
        # Unexpected exceptions or process loss leave pending, never an absence
        # assertion. The original command receipts remain available read-only.
        self._selection_state(owner, request_id, 'complete')
        return result

    def _selection_state(self, owner, request_id, state, failure_status=None):
        with self.connections._write() as conn:
            self.connections._lock(conn, owner)
            conn.execute(self.selections.update().where(self.selections.c.owner_id == owner,
                self.selections.c.request_id == request_id).values(state=state, failure_status=failure_status))

    def selection_status(self, owner, request_id):
        self.auth.require(owner, 'read')
        self.connections._key(request_id)
        suffix = digest({'request': request_id})[:40]
        keys = ['research-' + stage + ':' + suffix for stage in
            ('config', 'verify', 'read', 'template', 'template-verify', 'bind')]
        with self.connections._read() as conn:
            row = conn.execute(select(self.selections).where(self.selections.c.owner_id == owner,
                self.selections.c.request_id == request_id)).mappings().first()
            commands = list(conn.execute(select(self.connections.commands.c.request_id).where(
                self.connections.commands.c.owner_id == owner,
                self.connections.commands.c.request_id.in_(keys))).scalars())
        # Legacy/final receipts can establish completion even after process loss
        # before the selection row was updated. Missing receipts cannot prove
        # nonexecution; this endpoint never retries any configuration command.
        connection = self.selected_request(owner, request_id) if keys[-1] in commands else None
        if row is None and not commands: raise HTTPException(404, 'PERSONAL_PROJECT_SELECTION_NOT_FOUND')
        return {'requestId': request_id, 'ownerId': owner,
            'state': 'complete' if connection else 'failed' if row and row['state'] == 'failed' else 'unknown',
            'localConfiguration': 'partial' if commands else 'none',
            'failureStatus': row['failure_status'] if row and row['state'] == 'failed' else None,
            'connection': connection}

    def _select_existing(self, owner, reference, project_id, request_id):
        """Explicitly bind an existing project; only upstream GETs, no research IO.

        Reuse a real, nonarchived native session's explicit remote model as the
        new-session template. No invented harness/model or Factory BYOK forwarding.
        All intermediate commands use the existing owner-scoped receipt stores.
        """
        self.auth.require(owner, 'run')
        self.connections._key(request_id)
        handle, source_pin = self.sessions._handle(owner, reference=reference, capability='project:read')
        # Shared/task grants keep their existing admission policy; they cannot
        # be converted into an owner-owned service with owner-submit approval.
        self.connections.personal.inspect(owner, source_pin['registrationRef'])
        if source_pin.get('taskId') is not None:
            raise HTTPException(409, 'PERSONAL_USER_CONNECTION_REQUIRED')
        if project_id not in {p['nativeProjectId'] for p in handle.creation_projects()}:
            raise HTTPException(404, 'PERSONAL_NATIVE_PROJECT_NOT_FOUND')
        suffix = digest({'request': request_id})[:40]
        config = {k: v for k, v in handle.configuration.items() if k in {'origin', 'authMode', 'credentialRef', 'credentialRevision'}}
        config['projectId'] = project_id
        remote = self.connections.personal.configure(owner, handle.provider.provider_id, config, 'research-config:' + suffix)
        self.sessions._handle(owner, source_pin, capability='project:read')
        self.connections.personal.verify(owner, remote['registrationRef'], 'research-verify:' + suffix)
        bound = self.connections.bind(owner, remote['registrationRef'], 'research-read:' + suffix)
        # A second explicit selection POST never dispatches a remote mutation.
        # The final bind receipt establishes setup completion after loss.
        scoped, _ = self.sessions._handle(owner, reference=bound['ref'], capability='session:read')
        templates = sorted((s for s in scoped.list_sessions() if s.get('model') and not s['archived']),
            key=lambda s: (s['busy'], s['nativeSessionId']))
        if templates:
            config['sessionTemplateId'] = templates[0]['nativeSessionId']
            remote = self.connections.personal.configure(owner, handle.provider.provider_id, config, 'research-template:' + suffix)
            self.sessions._handle(owner, source_pin, capability='project:read')
            self.connections.personal.verify(owner, remote['registrationRef'], 'research-template-verify:' + suffix)
        self.sessions._handle(owner, source_pin, capability='project:read')
        return self.connections.bind(owner, remote['registrationRef'], 'research-bind:' + suffix)

    def selected_request(self, owner, request_id):
        return self.connections.request_result(owner, 'research-bind:' + digest({'request': request_id})[:40])['connection']


class PrepareProject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_.:-]+$')
    connectionRef: str = Field(min_length=1, max_length=200)
    project: ProjectInput


class ProjectDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    previewHash: str = Field(pattern=r'^[a-f0-9]{64}$')
    approved: bool


class ConnectProject(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    harness: str = Field(pattern=r'^(codex|opencode|claude-code)$')
    model: str = Field(min_length=1, max_length=200)


class SelectExistingProject(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_.:-]+$')
    connectionRef: str = Field(min_length=1, max_length=200)
    nativeProjectId: str = Field(min_length=1, max_length=200)


def prepare_project(api, owner, body):
    service = api.projects
    bundle = service.bundle(owner, body.connectionRef, body.project.model_dump())
    values = {'executionContract': CONTRACT, 'action': 'project_create', 'requestId': body.requestId,
        'connectionPin': canonical(bundle['connectionPin']), 'nativeProjectId': '', 'nativeSessionId': '',
        'factorySessionId': '', 'title': body.project.name, 'text': canonical(bundle), 'agent': ''}
    plan = api.store.admit_plan(owner, body.requestId, {'personalProject': body.model_dump()},
        lambda: api.store.composition.create_plan(owner, 'Create native OpenResearch project',
            'personal-command', PROJECT_APPLICATION_ID, request_id=body.requestId, input_values=values))
    # Recover a lost response from the immutable plan, never from a fresh pin.
    persisted = json.loads(plan['inputValues']['text'])
    service.record(owner, body.requestId, plan, persisted)
    return {'plan': plan, 'authorization': api.store.plan_policy.status(owner, plan),
        'receipt': service.request_result(owner, body.requestId)}

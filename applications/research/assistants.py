"""Stable research identities backed by core endpoints and original messages."""
from copy import deepcopy
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, select

from agent_factory.applications import GovernedStorage
from agent_factory.assistant_endpoints import AutomaticBudget, EndpointConfiguration
from agent_factory.assistant_messages import SendAssistantMessage
from agent_factory.material_governance import PinnedRef
from agent_factory.store import digest
from .projects import Budget, Reference, RequestId


class CreateAssistant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId


class QuestionBudget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    caps: Budget
    perQuestionCaps: Budget
    deadline: float = Field(strict=True, allow_inf_nan=False)

    @model_validator(mode='after')
    def bounded(self):
        if self.perQuestionCaps.rounds != 1:
            raise ValueError('One question consumes one native root allocation')
        if self.caps.tokenLimit is not None or self.perQuestionCaps.tokenLimit is not None:
            raise ValueError('RESEARCH_QA_BYOK_METERING_UNSUPPORTED: token and monetary limits are not supported')
        if self.perQuestionCaps.toolCalls > self.caps.toolCalls:
            raise ValueError('Question caps exceed the total commitment')
        return self


class ConfigureAssistant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    expectedRevision: int = Field(strict=True, ge=0)
    applicationRef: PinnedRef
    connectionRefs: dict[Reference, Reference] = Field(max_length=12)
    budget: QuestionBudget


class ResearchAssistants:
    def __init__(self, store, auth, endpoints, messages, scopes, *, pin,
                 tool_registrations, environment_registration):
        self.store, self.auth, self.endpoints, self.messages, self.scopes = store, auth, endpoints, messages, scopes
        self.pin, self.tools, self.environment = pin, tuple(tool_registrations), environment_registration
        self.db = GovernedStorage(store, 'research_assistants_v1')
        metadata = MetaData()
        self.identities = Table('research_assistants', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, unique=True, nullable=False),
            Column('configuration_revision', Integer, nullable=False), Column('qa_endpoint_id', String))
        self.configurations = Table('research_assistant_configurations', metadata,
            Column('assistant_id', String, primary_key=True), Column('revision', Integer, primary_key=True),
            Column('endpoint_id', String, unique=True, nullable=False), Column('body', JSON, nullable=False))
        self.commands = self.db.command_table('research_assistant_commands', metadata)
        metadata.create_all(store.engine)

    def _identity(self, conn, identifier):
        row = conn.execute(select(self.identities).where(self.identities.c.id == identifier)).mappings().first()
        if row is None:
            raise HTTPException(404, 'RESEARCH_ASSISTANT_NOT_FOUND')
        return row

    def configuration_for_endpoint(self, owner, endpoint_id):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            return self._historical_configuration(conn, owner, endpoint_id)

    def _historical_configuration(self, conn, owner, endpoint_id):
        row = conn.execute(select(self.configurations).join(self.identities,
            self.identities.c.id == self.configurations.c.assistant_id).where(
                self.identities.c.owner_id == owner, self.configurations.c.endpoint_id == endpoint_id)).mappings().first()
        if row is None:
            raise HTTPException(404, 'RESEARCH_ASSISTANT_CONFIGURATION_NOT_FOUND')
        return {'id': row['assistant_id'], 'revision': row['revision'], 'endpointId': row['endpoint_id']}

    def _projection(self, conn, row):
        qa = {'state': 'unconfigured'}
        if row['qa_endpoint_id']:
            configuration = conn.execute(select(self.configurations.c.body).where(
                self.configurations.c.assistant_id == row['id'],
                self.configurations.c.revision == row['configuration_revision'])).scalar_one()
            qa = {'state': 'configured', 'endpointId': row['qa_endpoint_id'], **deepcopy(configuration),
                'accounting': {'mode': 'operational_limits_only', 'tokenMetered': False, 'costMetered': False,
                               'notice': '操作额度受限，token/费用未计量'},
                **self._availability(row)}
        return {'id': row['id'], 'ownerId': row['owner_id'],
            'configurationRevision': row['configuration_revision'], 'qa': qa}

    def me(self, owner):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            row = conn.execute(select(self.identities).where(self.identities.c.owner_id == owner)).mappings().first()
            return {'assistant': self._projection(conn, row) if row else None}

    def owned(self, owner, identifier):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            row = self._identity(conn, identifier)
            if row['owner_id'] != owner:
                raise HTTPException(404, 'RESEARCH_ASSISTANT_NOT_FOUND')
            return self._projection(conn, row)

    def create(self, owner, body: CreateAssistant):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'create'})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, body.requestId, fingerprint)
            if old is not None:
                return old
            row = conn.execute(select(self.identities).where(self.identities.c.owner_id == owner)).mappings().first()
            if row is None:
                identifier = str(uuid4())
                conn.execute(self.identities.insert().values(id=identifier, owner_id=owner,
                    configuration_revision=0, qa_endpoint_id=None))
                row = self._identity(conn, identifier)
            return self.db.record(conn, self.commands, owner, body.requestId, fingerprint, 'create', self._projection(conn, row))

    def _validate_execution(self, owner, application_ref, connection_refs):
        app = self.store.applications.require_current(application_ref)
        if set(app['modes']) != {'qa'}:
            raise HTTPException(422, 'RESEARCH_QA_ONLY_MODE_REQUIRED')
        mode = app['modes']['qa']
        if mode.get('nativeComponent') != self.pin or self.store.native_workflows.pin(self.pin['id']) != self.pin or mode['materialChoices']:
            raise HTTPException(409, 'RESEARCH_QA_COMPONENT_MISMATCH')
        materials = self.store.applications.closure(mode['materialRefs'])
        expected_tools = {(entry.adapter_id, entry.revision, entry.tool_name) for entry in self.tools}
        actual_tools = set()
        for material in materials:
            binding = material.get('runtimeBinding') or {}
            config = binding.get('config', {})
            identity = (binding.get('adapterId'), binding.get('revision'))
            if material['kind'] == 'model':
                valid = identity == ('owner-chat-completions-v1', '1') and config == {'connectionName': 'model'}
            elif material['kind'] == 'environment':
                valid = identity == (self.environment.adapter_id, self.environment.revision) and config == {}
            elif material['kind'] == 'tool':
                actual_tools.add((*identity, material['content']))
                valid = config == {}
            else:
                valid = False
            if not valid:
                raise HTTPException(422, 'RESEARCH_QA_MATERIAL_MISMATCH')
        if actual_tools != expected_tools or set(connection_refs) != {'model'}:
            raise HTTPException(422, 'RESEARCH_QA_MATERIAL_MISMATCH')
        pins = {'model': self.store.connections.preflight(owner, connection_refs['model'], 'model',
            required_capabilities=['model:invoke'])}
        self.store.execution_bindings.build(materials, owner, pins)
        if self.store.execution_bindings.preflight(materials, owner, pins):
            raise HTTPException(409, 'RESEARCH_QA_BINDING_UNAVAILABLE')

    def configure(self, owner, body: ConfigureAssistant):
        self.auth.require_member(owner)
        value = body.model_dump(exclude={'requestId', 'expectedRevision'})
        fingerprint = digest({'action': 'configure', 'expectedRevision': body.expectedRevision, **value})
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                self.scopes.admission_lock(conn)
            with self.db.write(), self.endpoints.db.write():
                old = self.db.old(conn, self.commands, owner, body.requestId, fingerprint)
                if old is not None:
                    return old
                row = conn.execute(select(self.identities).where(self.identities.c.owner_id == owner)).mappings().first()
                if row is None:
                    raise HTTPException(404, 'RESEARCH_ASSISTANT_NOT_FOUND')
                if row['configuration_revision'] != body.expectedRevision:
                    raise HTTPException(409, 'RESEARCH_ASSISTANT_REVISION_CONFLICT')
                self._validate_execution(owner, value['applicationRef'], value['connectionRefs'])
                scope_id = str(uuid4())
                budget = value['budget']
                self.scopes.create_scope(owner, scope_id, digest(value), budget['caps'], budget['deadline'])
                endpoint = self.endpoints.configure(owner, EndpointConfiguration(name='Research assistant QA',
                    applicationRef=body.applicationRef, mode='qa', connectionRefs=body.connectionRefs,
                    automaticBudget=AutomaticBudget(scopeId=scope_id, caps=budget['perQuestionCaps'], deadline=budget['deadline'])), str(uuid4()))
                if row['qa_endpoint_id']:
                    self.endpoints.set_enabled(owner, row['qa_endpoint_id'], False, str(uuid4()))
                revision = row['configuration_revision'] + 1
                conn.execute(self.configurations.insert().values(assistant_id=row['id'], revision=revision,
                    endpoint_id=endpoint['id'], body={**value, 'scopeId': scope_id}))
                conn.execute(self.identities.update().where(self.identities.c.id == row['id']).values(
                    configuration_revision=revision, qa_endpoint_id=endpoint['id']))
                result = self._projection(conn, self._identity(conn, row['id']))
                return self.db.record(conn, self.commands, owner, body.requestId, fingerprint, 'configure', result)

    def _availability(self, row):
        if row['qa_endpoint_id'] is None:
            return {'available': False, 'unavailableCode': 'RESEARCH_ASSISTANT_UNCONFIGURED'}
        try:
            endpoint = self.endpoints.resolve(row['qa_endpoint_id'])
            budget = endpoint['automaticBudget']
            with self.db.read() as conn:
                self.endpoints.require_budget(conn, row['owner_id'], budget)
            self._validate_execution(row['owner_id'], endpoint['applicationRef'], endpoint['defaults']['connectionRefs'])
            scope = self.scopes.inspect(row['owner_id'], budget['scopeId'])
            caps, per = scope['caps'], budget['caps']
            if scope['allocatedRounds'] + 1 > caps['rounds'] or scope['heldToolCalls'] + scope['settledToolCalls'] + per['toolCalls'] > caps['toolCalls']:
                return {'available': False, 'unavailableCode': 'LOCAL_BUDGET_EXHAUSTED'}
            return {'available': True}
        except HTTPException as error:
            if error.status_code not in {403, 404, 409, 422}:
                raise
            code = str(error.detail).split(':', 1)[0]
            if not code.replace('_', '').isalnum() or not code.isupper():
                code = 'RESEARCH_QA_UNAVAILABLE'
            return {'available': False, 'unavailableCode': code}

    def list(self, actor, *, after='', limit=50):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            rows = conn.execute(select(self.identities).where(self.identities.c.id > after)
                .order_by(self.identities.c.id).limit(limit + 1)).mappings().all()
            items = []
            for row in rows[:limit]:
                try:
                    self.auth.require_member(row['owner_id'])
                    identity = self.auth.identity(row['owner_id'])
                except HTTPException as error:
                    if error.status_code != 403:
                        raise
                    continue
                items.append({'id': row['id'], 'ownerId': row['owner_id'], 'displayName': identity['name'],
                    'qaAvailable': self._availability(row)['available']})
            return {'items': items, 'nextCursor': rows[limit - 1]['id'] if len(rows) > limit else None}

    async def question(self, sender, identifier, body: SendAssistantMessage):
        self.auth.require_member(sender)
        try:
            original = self.messages.request(sender, body.requestId)
        except HTTPException as error:
            if error.status_code != 404 or error.detail != 'ASSISTANT_MESSAGE_NOT_FOUND':
                raise
        else:
            with self.db.read() as conn:
                configuration = self._historical_configuration(conn, original['recipientId'], original['endpointId'])
            if original['text'] != body.text or configuration['id'] != identifier:
                raise HTTPException(409, 'RESEARCH_QUESTION_REQUEST_CONFLICT')
            return original
        with self.db.read() as conn:
            row = self._identity(conn, identifier)
            endpoint_id = row['qa_endpoint_id']
            if endpoint_id is None:
                raise HTTPException(409, 'RESEARCH_ASSISTANT_UNCONFIGURED')
        return await self.messages.send(sender, endpoint_id, body)


def assistants_router(auth, service):
    router = APIRouter(prefix='/api/factory/research')

    @router.get('/assistants/me')
    def me(request: Request):
        return service.me(auth.user(request)['id'])

    @router.post('/assistants')
    def create(request: Request, body: CreateAssistant):
        return service.create(auth.user(request)['id'], body)

    @router.get('/assistants')
    def directory(request: Request, after: str = Query(default='', max_length=200), limit: int = Query(default=50, ge=1, le=50)):
        return service.list(auth.user(request)['id'], after=after, limit=limit)

    @router.post('/assistants/me/configurations')
    def configure(request: Request, body: ConfigureAssistant):
        return service.configure(auth.user(request)['id'], body)

    @router.post('/assistants/{identifier}/questions', status_code=202)
    async def question(identifier: str, request: Request, body: SendAssistantMessage):
        return await service.question(auth.user(request)['id'], identifier, body)

    @router.get('/assistant-questions/{identifier}')
    def read_question(identifier: str, request: Request):
        return service.messages.read(auth.user(request)['id'], identifier)

    return router

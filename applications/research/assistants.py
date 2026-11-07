"""Stable research identities backed by core endpoints and original messages."""
from copy import deepcopy
from contextlib import nullcontext
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, select, text

from agent_factory.applications import GovernedStorage
from agent_factory.assistant_endpoints import EndpointConfiguration
from agent_factory.assistant_messages import SendAssistantMessage
from agent_factory.assistant_events import EventSubscription
from agent_factory.store import digest
from .projects import Reference, RequestId


class CreateAssistant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId


class AssociationConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    maxRecipients: int | None = Field(default=None, strict=True, ge=1)


class ConfigureAssistant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    expectedRevision: int = Field(strict=True, ge=0)
    connectionRefs: dict[Reference, Reference]
    associations: AssociationConfiguration | None = None


class ResearchAssistants:
    def __init__(self, store, auth, endpoints, messages, *, events=None):
        self.store, self.auth, self.endpoints, self.messages = store, auth, endpoints, messages
        self.events = events
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

    def _configuration_row(self, conn, owner, endpoint_id):
        row = conn.execute(select(self.configurations).join(self.identities,
            self.identities.c.id == self.configurations.c.assistant_id).where(
                self.identities.c.owner_id == owner, self.configurations.c.endpoint_id == endpoint_id)).mappings().first()
        if row is None:
            raise HTTPException(404, 'RESEARCH_ASSISTANT_CONFIGURATION_NOT_FOUND')
        return row

    def _historical_configuration(self, conn, owner, endpoint_id):
        row = self._configuration_row(conn, owner, endpoint_id)
        return {'id': row['assistant_id'], 'revision': row['revision'], 'endpointId': row['endpoint_id']}

    def _projection(self, conn, row):
        qa = {'state': 'unconfigured'}
        if row['qa_endpoint_id']:
            configuration = conn.execute(select(self.configurations.c.body).where(
                self.configurations.c.assistant_id == row['id'],
                self.configurations.c.revision == row['configuration_revision'])).scalar_one()
            qa = {'state': 'configured', 'endpointId': row['qa_endpoint_id'], **deepcopy(configuration),
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

    def configure(self, owner, body: ConfigureAssistant):
        self.auth.require_member(owner)
        value = body.model_dump(exclude={'requestId', 'expectedRevision'}, exclude_none=True)
        fingerprint = digest({'action': 'configure', 'expectedRevision': body.expectedRevision, **value})
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            with self.db.write(), (self.events.db.write() if self.events is not None else nullcontext()), self.endpoints.db.write():
                old = self.db.old(conn, self.commands, owner, body.requestId, fingerprint)
                if old is not None:
                    return old
                row = conn.execute(select(self.identities).where(self.identities.c.owner_id == owner)).mappings().first()
                if row is None:
                    raise HTTPException(404, 'RESEARCH_ASSISTANT_NOT_FOUND')
                if row['configuration_revision'] != body.expectedRevision:
                    raise HTTPException(409, 'RESEARCH_ASSISTANT_REVISION_CONFLICT')
                endpoint = self.endpoints.configure(owner, EndpointConfiguration(name='Research assistant QA',
                    mode='qa', connectionRefs=body.connectionRefs), str(uuid4()))
                if body.associations and body.associations.enabled:
                    if self.events is None:
                        raise HTTPException(409, 'RESEARCH_ASSOCIATIONS_NOT_INSTALLED')
                    self.events.configure(owner, EventSubscription(endpointId=endpoint['id'], namespace='research',
                        eventType='evidence.available'), 'research-associations:' + endpoint['id'])
                if row['qa_endpoint_id']:
                    self.endpoints.set_enabled(owner, row['qa_endpoint_id'], False, str(uuid4()))
                revision = row['configuration_revision'] + 1
                conn.execute(self.configurations.insert().values(assistant_id=row['id'], revision=revision,
                    endpoint_id=endpoint['id'], body=value))
                conn.execute(self.identities.update().where(self.identities.c.id == row['id']).values(
                    configuration_revision=revision, qa_endpoint_id=endpoint['id']))
                result = self._projection(conn, self._identity(conn, row['id']))
                return self.db.record(conn, self.commands, owner, body.requestId, fingerprint, 'configure', result)

    def association_configuration(self, owner):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            row = conn.execute(select(self.identities).where(self.identities.c.owner_id == owner)).mappings().first()
            if row is None or not row['qa_endpoint_id']:
                return None
            configuration = conn.execute(select(self.configurations.c.body).where(
                self.configurations.c.assistant_id == row['id'],
                self.configurations.c.revision == row['configuration_revision'])).scalar_one()
            if not (configuration.get('associations') or {}).get('enabled'):
                return None
            if not self._availability(row)['available']:
                return None
            result = {'assistantId': row['id'], 'endpointId': row['qa_endpoint_id'], **deepcopy(configuration)}
        return result

    def _availability(self, row):
        if row['qa_endpoint_id'] is None:
            return {'available': False, 'unavailableCode': 'RESEARCH_ASSISTANT_UNCONFIGURED'}
        try:
            self.endpoints.resolve(row['qa_endpoint_id'])
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

    def question_target(self, sender, identifier, body: SendAssistantMessage):
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
            return original['endpointId'], original
        with self.db.read() as conn:
            row = self._identity(conn, identifier)
            endpoint_id = row['qa_endpoint_id']
            if endpoint_id is None:
                raise HTTPException(409, 'RESEARCH_ASSISTANT_UNCONFIGURED')
        return endpoint_id, None

    async def question(self, sender, identifier, body: SendAssistantMessage):
        endpoint_id, original = self.question_target(sender, identifier, body)
        if original is not None:
            return original
        return await self.messages.send(sender, endpoint_id, body)

    def read_question(self, actor, identifier):
        message = self.messages.read(actor, identifier)
        with self.db.read() as conn:
            self._historical_configuration(conn, message['recipientId'], message['endpointId'])
        return {**message, **self.messages.recovery_actions(actor, identifier)}


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
        return service.read_question(auth.user(request)['id'], identifier)

    return router

"""Team-visible goals and selected contributions; execution stays with each member."""
from copy import deepcopy
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.applications import GovernedStorage
from agent_factory.store import digest, now
from agent_factory.personal_tool_contract import ToolInvocationError
from .conversations import SessionQuestion
from .projects import RequestId


class CreateWork(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    sessionId: str | None = None
    projectId: str | None = None


class Contribution(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    text: str = Field(min_length=1)
    evidenceIds: list[str] = Field(default_factory=list)
    sessionId: str | None = None


class ContributionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    assistantId: str
    text: str = Field(min_length=1)
    sessionId: str


class ResearchTeamWork:
    def __init__(self, sessions):
        self.sessions, self.auth = sessions, sessions.auth
        self.db = GovernedStorage(sessions.store, 'research_team_work_v1')
        metadata = MetaData()
        self.records = Table('research_team_work', metadata,
            Column('id', String, primary_key=True), Column('body', JSON, nullable=False))
        self.commands = self.db.command_table('research_team_work_commands', metadata)
        metadata.create_all(sessions.store.engine)

    async def invoke(self, context, call_id, name, values):
        try:
            result = await self._invoke(context, call_id, name, values)
        except HTTPException as error:
            # A committed contribution request may still be awaiting native admission.
            if self._receipt(context, call_id) is not None:
                raise
            detail = error.detail
            code = cast(dict, detail)['code'] if isinstance(detail, dict) else str(detail)
            raise ToolInvocationError(code, outcome='failed', stopped=True) from error
        return self._sources(context, result)

    def _sources(self, context, result):
        records = result.get('items', []) if 'items' in result else [result]
        for record in records:
            for entry in record.get('entries', []):
                reply = entry.get('reply')
                if reply is not None and reply['state'] == 'available':
                    for source in reply['contentIds']:
                        self.sessions.record_source(context, source)
        return result

    async def _invoke(self, context, call_id, name, values):
        execution = self.sessions.authorize_tool(context, name)
        owner = context.user_id
        request = 'team-work:' + digest({'run': context.run_id, 'call': call_id})
        if name == 'research_team_work':
            return self.read(owner, values['work_id']) if 'work_id' in values else self.listing(owner)
        if name == 'research_create_team_work':
            return self.create(owner, CreateWork(requestId=request, sessionId=execution['id'], **values))
        identifier = values['work_id']
        if name == 'research_request_contribution':
            return await self.request_native(context, call_id, values, execution, request)
        return self.contribute(owner, identifier, Contribution(requestId=request, sessionId=execution['id'],
            text=values['text'], evidenceIds=values.get('evidence_ids', [])),
            kind='synthesis' if name == 'research_synthesize_team_work' else 'contribution',
            origin={'sessionId': execution['id'], 'turnId': execution['turnId'],
                    'taskId': self.sessions.store.task_for_context(context)['id'], 'runId': context.run_id})

    def _receipt(self, context, call_id):
        request = 'team-work:' + digest({'run': context.run_id, 'call': call_id})
        with self.db.read() as conn:
            row = conn.execute(select(self.commands).where(
                self.commands.c.actor_id == context.user_id, self.commands.c.request_id == request)).mappings().one_or_none()
        return {**row['result'], 'action': row['action']} if row is not None else None

    async def reconcile(self, context, call_id):
        result = self._receipt(context, call_id)
        if result is not None and result['action'] in {'request', 'native_request'}:
            messages = self.sessions.conversations.messages
            original = messages.read(context.user_id, result['questionId'])
            await messages.recover(original['recipientId'], original['id'], private_event_id=result['eventId'])
        if result is not None and result['action'] == 'native_request':
            return {'questionId': result['questionId'], 'state': 'saved'}
        return self._sources(context, self.read(context.user_id, result['id'])) if result is not None else None

    def _row(self, conn, identifier):
        body = conn.execute(select(self.records.c.body).where(self.records.c.id == identifier)).scalar_one_or_none()
        if body is None:
            raise HTTPException(404, 'RESEARCH_TEAM_WORK_NOT_FOUND')
        return deepcopy(body)

    def _session(self, conn, owner, identifier):
        if identifier is not None:
            return self.sessions._row(conn, owner, identifier)
        return None

    def create(self, owner, body):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'create', **body.model_dump(exclude={'requestId'})})
        with self.sessions._write() as conn, self.db.write():
            old = self.db.old(conn, self.commands, owner, body.requestId, fingerprint)
            if old is not None:
                identifier = old['id']
            else:
                session = self._session(conn, owner, body.sessionId)
                project = body.projectId or (session['body'].get('projectId') if session is not None else None)
                if project is not None:
                    self.sessions.projects.read(owner, project)
                identifier, stamp = str(uuid4()), now()
                record = {'id': identifier, 'leadId': owner, 'title': body.title, 'goal': body.goal,
                    'createdAt': stamp, 'updatedAt': stamp, 'entries': [],
                    **{key: value for key, value in body.model_dump().items()
                       if key in {'sessionId', 'projectId'} and value is not None},
                    **({'projectId': project} if project is not None else {})}
                conn.execute(self.records.insert().values(id=identifier, body=record))
                self.db.record(conn, self.commands, owner, body.requestId, fingerprint, 'create', {'id': identifier})
        return self.read(owner, identifier)

    def read(self, owner, identifier):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            record = self._row(conn, identifier)
        for entry in record['entries']:
            if entry['kind'] == 'request':
                try:
                    message = self.sessions.conversations.messages.read(entry['memberId'], entry['questionId'])
                except HTTPException as error:
                    if error.status_code not in {403, 404}:
                        raise
                    entry['reply'] = {'state': 'source_unavailable'}
                    continue
                reply = message['reply']
                if reply is not None and reply['state'] == 'available':
                    try:
                        for source in reply['contentIds']:
                            if self.sessions.content.read(owner, source)['visibility'] != 'team':
                                raise HTTPException(403, 'RESEARCH_TEAM_SOURCE_REQUIRED')
                    except HTTPException as error:
                        if error.status_code not in {403, 404}:
                            raise
                        reply = {'state': 'source_unavailable'}
                entry.update(reply=reply, delivery=message['delivery'])
        return record

    def listing(self, owner):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            records = list(conn.execute(select(self.records.c.body)).scalars())
        return {'items': sorted(records, key=lambda item: (item['updatedAt'], item['id']), reverse=True)}

    def _append(self, conn, owner, identifier, body, kind, **extra):
        record = self._row(conn, identifier)
        if kind == 'synthesis' and record['leadId'] != owner:
            raise HTTPException(403, 'RESEARCH_TEAM_WORK_LEAD_REQUIRED')
        self._session(conn, owner, body.sessionId)
        origin = {'sessionId': body.sessionId} if body.sessionId is not None else {}
        entry = {'id': str(uuid4()), 'kind': kind, 'memberId': owner, 'text': body.text,
                 'evidenceIds': getattr(body, 'evidenceIds', []), 'createdAt': now(), 'origin': origin, **extra}
        record['entries'].append(entry)
        if kind == 'synthesis':
            record['synthesis'] = entry
        record['updatedAt'] = entry['createdAt']
        conn.execute(self.records.update().where(self.records.c.id == identifier).values(body=record))

    def contribute(self, owner, identifier, body, *, kind='contribution', origin=None):
        self.auth.require_member(owner)
        fingerprint = digest({'action': kind, 'id': identifier, **body.model_dump(exclude={'requestId'})})
        with self.db.write() as conn:
            if self.db.old(conn, self.commands, owner, body.requestId, fingerprint) is None:
                self._append(conn, owner, identifier, body, kind, **({'origin': origin} if origin is not None else {}))
                self.db.record(conn, self.commands, owner, body.requestId, fingerprint, kind, {'id': identifier})
        return self.read(owner, identifier)

    async def request_native(self, context, call_id, values, execution, request_id):
        owner, identifier = context.user_id, values['work_id']
        body = ContributionRequest(requestId=request_id, assistantId=values['assistant_id'],
            text=values['text'], sessionId=execution['id'])
        fingerprint = digest({'action': 'request', 'id': identifier, **body.model_dump(exclude={'requestId'})})
        collaboration = self.sessions.collaboration
        with self.sessions._write() as conn, self.db.write():
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is None:
                self._row(conn, identifier)
                ack = collaboration.ask(context, call_id, values, tool_name='research_request_contribution')
                question = self.sessions.conversations.messages.read(owner, ack['questionId'])
                intent = conn.execute(select(collaboration.intents).where(
                    collaboration.intents.c.question_id == question['id'])).mappings().one()
                self._append(conn, owner, identifier, body, 'request', questionId=question['id'],
                    recipientId=question['recipientId'], eventId=intent['body']['eventId'],
                    origin={'sessionId': execution['id'], 'turnId': execution['turnId'],
                            'taskId': self.sessions.store.task_for_context(context)['id'], 'runId': context.run_id})
                old = self.db.record(conn, self.commands, owner, request_id, fingerprint, 'native_request',
                    {'id': identifier, 'eventId': intent['body']['eventId'], 'questionId': question['id']})
        message = self.sessions.conversations.messages.read(owner, old['questionId'])
        await self.sessions.conversations.messages.recover(message['recipientId'], message['id'],
            private_event_id=old['eventId'])
        return {'questionId': message['id'], 'state': 'saved'}

    async def request(self, owner, identifier, body):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'request', 'id': identifier, **body.model_dump(exclude={'requestId'})})
        conversations = self.sessions.conversations
        question = SessionQuestion(requestId='team-work:' + digest({'owner': owner, 'request': body.requestId}),
            assistantId=body.assistantId, text=body.text)
        # Use the same admission lock ordering as ordinary private questions.
        with self.sessions._write() as conn:
            with self.db.write():
                old = self.db.old(conn, self.commands, owner, body.requestId, fingerprint)
                if old is None:
                    self._row(conn, identifier)
                    message, _ = conversations._reserve(owner, body.sessionId, question)
                    event = self.sessions.collaboration.events.emit_collaboration(conn, owner, message['id'])
                    self._append(conn, owner, identifier, body, 'request',
                        questionId=message['id'], recipientId=message['recipient_id'], eventId=event['id'])
                    old = self.db.record(conn, self.commands, owner, body.requestId, fingerprint, 'request',
                        {'id': identifier, 'eventId': event['id'], 'questionId': message['id']})
        message = conversations.messages.request(owner, question.requestId)
        await conversations.messages.recover(message['recipientId'], message['id'], private_event_id=old['eventId'])
        return self.read(owner, identifier)


def team_work_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/team-work')

    @router.get('')
    def listing(request: Request):
        return service.listing(auth.user(request)['id'])

    @router.post('')
    def create(request: Request, body: CreateWork):
        return service.create(auth.user(request)['id'], body)

    @router.get('/{identifier}')
    def read(identifier: str, request: Request):
        return service.read(auth.user(request)['id'], identifier)

    @router.post('/{identifier}/contributions')
    def contribute(identifier: str, request: Request, body: Contribution):
        return service.contribute(auth.user(request)['id'], identifier, body)

    @router.post('/{identifier}/synthesis')
    def synthesize(identifier: str, request: Request, body: Contribution):
        return service.contribute(auth.user(request)['id'], identifier, body, kind='synthesis')

    @router.post('/{identifier}/requests', status_code=202)
    async def ask(identifier: str, request: Request, body: ContributionRequest):
        return await service.request(auth.user(request)['id'], identifier, body)

    return router

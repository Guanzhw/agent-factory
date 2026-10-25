"""Member messages reference original application admissions; reads never dispatch."""
import asyncio
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, MetaData, String, Table, select

from .application_interface import ApplicationRequestId, ApplicationStart
from .applications import GovernedStorage
from .store import digest, now


class SendAssistantMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: ApplicationRequestId
    text: str = Field(min_length=2, max_length=2000)


class AssistantMessages:
    def __init__(self, store, auth, endpoints, runs):
        self.auth, self.endpoints, self.runs = auth, endpoints, runs
        self.db = GovernedStorage(store, 'af_assistant_messages_v1')
        metadata = MetaData()
        self.messages = Table('af_assistant_messages', metadata,
            Column('id', String, primary_key=True), Column('sender_id', String, nullable=False),
            Column('recipient_id', String, nullable=False), Column('endpoint_id', String, nullable=False),
            Column('text', String, nullable=False), Column('created_at', String, nullable=False))
        self.commands = self.db.command_table('af_assistant_message_commands', metadata)
        metadata.create_all(store.engine)

    def _row(self, conn, identifier):
        row = conn.execute(select(self.messages).where(self.messages.c.id == identifier)).mappings().first()
        if row is None:
            raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        return dict(row)

    def _reserve(self, sender, endpoint_id, body):
        self.auth.require_member(sender)
        fingerprint = digest({'endpointId': endpoint_id, 'text': body.text})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, sender, body.requestId, fingerprint)
            if old is not None:
                return self._row(conn, old['id']), False
            endpoint = self.endpoints.resolve(endpoint_id)
            identifier = str(uuid4())
            conn.execute(self.messages.insert().values(id=identifier, sender_id=sender,
                recipient_id=endpoint['ownerId'], endpoint_id=endpoint_id, text=body.text, created_at=now()))
            self.db.record(conn, self.commands, sender, body.requestId, fingerprint,
                           'assistant.message', {'id': identifier})
            return self._row(conn, identifier), True

    @staticmethod
    def _request_id(message):
        return 'assistant-message:' + message['id']

    async def send(self, sender, endpoint_id, body: SendAssistantMessage):
        message, fresh = await asyncio.to_thread(self._reserve, sender, endpoint_id, body)
        if fresh:
            self.auth.require_member(sender)
            endpoint = await asyncio.to_thread(self.endpoints.resolve, endpoint_id)
            values = {**endpoint['defaults'], 'requestId': self._request_id(message), 'goal': message['text']}
            if endpoint['textInput']:
                values['inputValues'] = {'goal': message['text']}
            await self.runs.start(message['recipient_id'], ApplicationStart.model_validate(values))
        return await asyncio.to_thread(self.read, sender, message['id'])

    def _projection(self, message):
        try:
            receipt = self.runs.request(message['recipient_id'], self._request_id(message))
        except HTTPException as error:
            if error.status_code != 404 or error.detail != 'APPLICATION_START_RECEIPT_NOT_FOUND':
                raise
            # A missing receipt cannot distinguish pre-admission failure from a
            # concurrent or interrupted start. It never permits another start.
            receipt = {'state': 'unconfirmed', 'taskId': None, 'runId': None}
        return {'id': message['id'], 'senderId': message['sender_id'],
            'recipientId': message['recipient_id'], 'endpointId': message['endpoint_id'],
            'text': message['text'], 'createdAt': message['created_at'],
            'delivery': {key: receipt[key] for key in ('state', 'taskId', 'runId')},
            'createsExecution': False, 'automaticReplay': False}

    def read(self, actor, identifier):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            message = self._row(conn, identifier)
        if actor not in {message['sender_id'], message['recipient_id']}:
            raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        return self._projection(message)

    def request(self, sender, request_id):
        self.auth.require_member(sender)
        with self.db.read() as conn:
            result = conn.execute(select(self.commands.c.result).where(
                self.commands.c.actor_id == sender, self.commands.c.request_id == request_id)).scalar()
            if result is None:
                raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
            message = self._row(conn, result['id'])
        return self._projection(message)


def assistant_messages_router(auth, service):
    router = APIRouter(prefix='/api/factory')

    @router.post('/assistants/{endpoint_id}/messages', status_code=202)
    async def send(endpoint_id: str, body: SendAssistantMessage, request: Request):
        return await service.send(auth.user(request)['id'], endpoint_id, body)

    @router.get('/assistant-messages/{message_id}')
    def read(message_id: str, request: Request):
        return service.read(auth.user(request)['id'], message_id)

    @router.get('/assistant-message-requests/{request_id}')
    def receipt(request_id: str, request: Request):
        return service.request(auth.user(request)['id'], request_id)

    return router

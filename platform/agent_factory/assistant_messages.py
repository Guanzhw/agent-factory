"""Member messages reference original application admissions; reads never dispatch."""
import asyncio
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text, Column, JSON, MetaData, String, Table, inspect, select

from .application_content import ObjectId
from .application_interface import ApplicationRequestId, ApplicationStart
from .application_runs import factory_request_id
from .applications import GovernedStorage
from .store import digest, now


class SendAssistantMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: ApplicationRequestId
    text: str = Field(min_length=1)


class AssistantReply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1)
    contentIds: list[ObjectId] = Field(default_factory=list)
    citedContentIds: list[ObjectId] | None = None


class AssistantMessages:
    def __init__(self, store, auth, endpoints, runs, content):
        self.auth, self.endpoints, self.runs, self.content = auth, endpoints, runs, content
        self.question_instructions: list[str] | None = None
        self.db = GovernedStorage(store, 'af_assistant_messages_v1')
        metadata = MetaData()
        self.messages = Table('af_assistant_messages', metadata,
            Column('id', String, primary_key=True), Column('sender_id', String, nullable=False),
            Column('recipient_id', String, nullable=False), Column('endpoint_id', String, nullable=False),
            Column('text', String, nullable=False), Column('created_at', String, nullable=False),
            Column('reply', JSON))
        self.commands = self.db.command_table('af_assistant_message_commands', metadata)
        metadata.create_all(store.engine)
        with store.engine.begin() as conn:
            if store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_assistant_messages_v1'))"))
            if 'reply' not in {column['name'] for column in inspect(conn).get_columns('af_assistant_messages')}:
                conn.execute(text('ALTER TABLE af_assistant_messages ADD COLUMN reply JSON'))

    def _row(self, conn, identifier):
        row = conn.execute(select(self.messages).where(self.messages.c.id == identifier)).mappings().first()
        if row is None:
            raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        return dict(row)

    def reserve(self, sender, endpoint_id, body):
        self.auth.require_member(sender)
        fingerprint = digest({'endpointId': endpoint_id, 'text': body.text})
        store = self.db.store
        with store.transaction() as conn:
            if store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            with self.db.write():
                old = self.db.old(conn, self.commands, sender, body.requestId, fingerprint)
                if old is not None:
                    return self._row(conn, old['id']), False
                endpoint = self.endpoints.resolve(endpoint_id)
                identifier = str(uuid4())
                conn.execute(self.messages.insert().values(id=identifier, sender_id=sender,
                    recipient_id=endpoint['ownerId'], endpoint_id=endpoint_id, text=body.text, created_at=now()))
                message = self._row(conn, identifier)
                self.db.record(conn, self.commands, sender, body.requestId, fingerprint,
                               'assistant.message', {'id': identifier})
                return message, True

    @staticmethod
    def _request_id(message):
        return 'assistant-message:' + message['id']

    def _start_body(self, message, endpoint):
        values = {**endpoint['defaults'], 'requestId': self._request_id(message), 'goal': message['text']}
        values['inputValues'] = {'goal': message['text']}
        if self.question_instructions is not None:
            values['instructions'] = self.question_instructions
        return ApplicationStart.model_validate(values)

    async def send(self, sender, endpoint_id, body: SendAssistantMessage):
        message, fresh = await asyncio.to_thread(self.reserve, sender, endpoint_id, body)
        if fresh:
            self.auth.require_member(sender)
            endpoint = await asyncio.to_thread(self.endpoints.resolve, endpoint_id)
            await self.runs.start(message['recipient_id'], self._start_body(message, endpoint))
        return await asyncio.to_thread(self.read, sender, message['id'])

    async def recover(self, recipient, identifier, *, delivery_id=None, private_event_id=None):
        """Trusted admission reentry; the original reservation owns the fresh gate."""
        if self.db.store._connection.get() is not None:
            raise RuntimeError('Assistant recovery requires a committed message transaction')
        self.auth.require_member(recipient)
        with self.db.read() as conn:
            message = self._row(conn, identifier)
        if message['recipient_id'] != recipient:
            raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        receipt = await asyncio.to_thread(self._receipt, message)
        if receipt['taskId'] is None:
            self.auth.require_member(message['sender_id'])
            endpoint = await asyncio.to_thread(self.endpoints.resolve, message['endpoint_id'])
            options = {}
            if delivery_id is not None:
                options['delivery_id'] = delivery_id
            if private_event_id is not None:
                options['private_event_id'] = private_event_id
            await self.runs.start(recipient, self._start_body(message, endpoint), **options)
        return await asyncio.to_thread(self.read, recipient, identifier)

    def _message_id(self, request_id, execution):
        if execution['application'] != self.runs.application:
            return None
        raw_id = (request_id.removeprefix('application-start:') if self.runs.application == 'research-chat'
                  else execution.get('requestId', ''))
        if not raw_id.startswith('assistant-message:'):
            return None
        if request_id != factory_request_id(raw_id, self.runs.application):
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ADMISSION_MISMATCH')
        return raw_id.removeprefix('assistant-message:')

    def validate_admission(self, conn, owner, request_id, execution):
        identifier = self._message_id(request_id, execution)
        if identifier is None:
            return
        message = self._row(conn, identifier)
        if message['recipient_id'] != owner:
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ADMISSION_MISMATCH')
        self.auth.require_member(message['sender_id'])
        endpoint = self.endpoints.resolve(message['endpoint_id'])
        expected = self._start_body(message, endpoint).model_dump(exclude={'interfaceVersion', 'requestId'})
        fingerprint = execution.get('requestFingerprint')
        if fingerprint is None:
            legacy = self.runs._legacy_request(owner, request_id)
            if legacy is not None and legacy['body']['id'] == execution['id']:
                fingerprint = legacy['request_fingerprint']
        if execution['ownerId'] != owner or fingerprint != digest(expected):
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ADMISSION_MISMATCH')
    def message_for_task(self, owner, task_id):
        self.auth.require_member(owner)
        task = self.db.store.task(task_id, owner)
        identifier = self._message_id(task['request_id'], self.db.store.execution(task))
        if identifier is None:
            return None
        with self.db.read() as conn:
            message = self._row(conn, identifier)
            if message['recipient_id'] != owner:
                raise HTTPException(409, 'ASSISTANT_MESSAGE_TASK_MISMATCH')
        return {'messageId': message['id'], 'senderId': message['sender_id'],
            'recipientId': message['recipient_id'], 'endpointId': message['endpoint_id'], 'text': message['text']}

    def _receipt(self, message):
        try:
            receipt = self.runs._request_receipt(message['recipient_id'], self._request_id(message))
        except HTTPException as error:
            if error.status_code != 404 or error.detail != 'APPLICATION_START_RECEIPT_NOT_FOUND':
                raise
            # Absence alone cannot establish that an earlier start did not run.
            receipt = {'state': 'unconfirmed', 'taskId': None, 'runId': None}
        return receipt

    def _require_reply_sources(self, message, content_ids):
        for owner in (message['sender_id'], message['recipient_id']):
            self.auth.require_member(owner)
            for identifier in content_ids:
                self.content.read(owner, identifier)

    def reply_for_task(self, receiver, task_id, text, content_ids=(), *, cited_content_ids=None):
        body = AssistantReply(text=text, contentIds=list(content_ids), citedContentIds=cited_content_ids)
        sources = sorted(set(body.contentIds))
        cited = sorted(set(body.citedContentIds)) if body.citedContentIds is not None else None
        store = self.db.store
        with store.transaction() as conn:
            if store.engine.dialect.name == 'postgresql':
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(hashtext('af_admission'))")
            with self.db.write() as conn:
                original = self.message_for_task(receiver, task_id)
                if original is None:
                    raise HTTPException(409, 'ASSISTANT_MESSAGE_TASK_MISMATCH')
                message = self._row(conn, original['messageId'])
                self._require_reply_sources(message, sources)
                reply = message['reply']
                if reply is not None:
                    if (reply['taskId'] != task_id or reply['text'] != body.text
                            or reply['contentIds'] != sources or reply.get('citedContentIds') != cited):
                        raise HTTPException(409, 'ASSISTANT_REPLY_CONFLICT')
                else:
                    conn.execute(self.messages.update().where(self.messages.c.id == message['id']).values(
                        reply={'taskId': task_id, 'text': body.text, 'contentIds': sources, 'createdAt': now(),
                               **({'citedContentIds': cited} if cited is not None else {})}))
        return self.read(receiver, message['id'])

    def _reply_snapshot(self, message):
        reply = message['reply']
        if reply is None:
            return None
        try:
            self._require_reply_sources(message, reply['contentIds'])
        except HTTPException as error:
            if error.status_code not in {403, 404}:
                raise
            return {'state': 'source_unavailable'}
        return {'state': 'available', **{key: reply[key] for key in ('text', 'contentIds', 'createdAt')},
                **({'citedContentIds': reply['citedContentIds']} if 'citedContentIds' in reply else {})}

    def _projection(self, message, reply):
        receipt = self._receipt(message)
        return {'id': message['id'], 'senderId': message['sender_id'],
            'recipientId': message['recipient_id'], 'endpointId': message['endpoint_id'],
            'text': message['text'], 'createdAt': message['created_at'],
            'delivery': {key: receipt[key] for key in ('state', 'taskId', 'runId')},
            'createsExecution': False, 'automaticReplay': False, 'reply': reply}

    def read(self, actor, identifier):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            message = self._row(conn, identifier)
        if actor not in {message['sender_id'], message['recipient_id']}:
            raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        reply = None
        if message['reply'] is not None:
            store = self.db.store
            with store.transaction() as conn:
                if store.engine.dialect.name == 'postgresql':
                    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
                self.auth.require_member(actor)
                message = self._row(conn, identifier)
                reply = self._reply_snapshot(message)
        return self._projection(message, reply)

    def request(self, sender, request_id):
        self.auth.require_member(sender)
        with self.db.read() as conn:
            result = conn.execute(select(self.commands.c.result).where(
                self.commands.c.actor_id == sender, self.commands.c.request_id == request_id)).scalar()
            if result is None:
                raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        return self.read(sender, result['id'])

    def received(self, recipient, *, endpoint_ids, after='', limit=50):
        self.auth.require_member(recipient)
        with self.db.read() as conn:
            identifiers = list(conn.execute(select(self.messages.c.id).where(
                self.messages.c.recipient_id == recipient,
                self.messages.c.endpoint_id.in_(endpoint_ids), self.messages.c.id > after)
                .order_by(self.messages.c.id).limit(limit + 1)).scalars())
        return {'items': [self.read(recipient, identifier) for identifier in identifiers[:limit]],
            'nextCursor': identifiers[limit - 1] if len(identifiers) > limit else None}

    def recovery_actions(self, actor, identifier):
        message = self.read(actor, identifier)
        if actor != message['recipientId']:
            return {'allowedActions': [], 'recoveryCode': 'ASSISTANT_RECIPIENT_REQUIRED'}
        if message['delivery']['taskId'] is not None:
            return {'allowedActions': [], 'recoveryCode': 'ASSISTANT_ORIGINAL_TASK_EXISTS'}
        events = self.db.store.assistant_events
        with self.db.read() as conn:
            delivery = conn.execute(select(events.deliveries.c.id).where(
                events.deliveries.c.owner_id == actor, events.deliveries.c.message_id == identifier)).first()
            if delivery is not None:
                return {'allowedActions': [], 'recoveryCode': 'ASSISTANT_EVENT_RECOVERY_MANAGED'}
        try:
            self.auth.require_member(message['senderId'])
            self.endpoints.resolve(message['endpointId'])
        except HTTPException as error:
            if error.status_code not in {403, 404, 409, 422}:
                raise
            code = str(error.detail).split(':', 1)[0]
            if not code.replace('_', '').isalnum() or not code.isupper():
                code = 'ASSISTANT_RECOVERY_UNAVAILABLE'
            return {'allowedActions': [], 'recoveryCode': code}
        return {'allowedActions': ['recover'], 'recoveryCode': None}


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

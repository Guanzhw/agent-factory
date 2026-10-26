"""Member messages reference original application admissions; reads never dispatch."""
import asyncio
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text, Column, JSON, MetaData, String, Table, inspect, select

from .application_content import ObjectId
from .application_interface import ApplicationRequestId, ApplicationStart
from .applications import GovernedStorage
from .store import digest, now


class SendAssistantMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: ApplicationRequestId
    text: str = Field(min_length=2, max_length=2000)


class AssistantReply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=2, max_length=2000)
    contentIds: list[ObjectId] = Field(default_factory=list, max_length=20)


class AssistantMessages:
    def __init__(self, store, auth, endpoints, runs, content):
        self.auth, self.endpoints, self.runs, self.content = auth, endpoints, runs, content
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

    def _reserve(self, sender, endpoint_id, body, *, allocation_id=None, delivery_id=None):
        self.auth.require_member(sender)
        fingerprint = digest({'endpointId': endpoint_id, 'text': body.text})
        store = self.db.store
        with store.transaction() as conn:
            if store.engine.dialect.name == 'postgresql':
                store.local_budget_scopes.admission_lock(conn)
            with self.db.write():
                old = self.db.old(conn, self.commands, sender, body.requestId, fingerprint)
                if old is not None:
                    return self._row(conn, old['id']), False
                endpoint = self.endpoints.resolve(endpoint_id)
                identifier = str(uuid4())
                conn.execute(self.messages.insert().values(id=identifier, sender_id=sender,
                    recipient_id=endpoint['ownerId'], endpoint_id=endpoint_id, text=body.text, created_at=now()))
                message = self._row(conn, identifier)
                budget = endpoint.get('automaticBudget')
                if budget:
                    self.endpoints.require_budget(conn, endpoint['ownerId'], budget)
                    if allocation_id is None:
                        allocation_id = str(uuid4())
                        store.local_budget_scopes.allocate(conn, endpoint['ownerId'], budget['scopeId'],
                            allocation_id, digest({'messageId': identifier}), budget['caps'])
                if allocation_id is not None:
                    store.local_budget_scopes.bind_request(conn, endpoint['ownerId'], allocation_id,
                        'application-start:' + self._request_id(message), delivery_id=delivery_id)
                if budget:
                    self._budget_allocation(conn, message, endpoint, allocation_id)
                self.db.record(conn, self.commands, sender, body.requestId, fingerprint,
                               'assistant.message', {'id': identifier})
                return message, True

    @staticmethod
    def _request_id(message):
        return 'assistant-message:' + message['id']

    def _start_body(self, message, endpoint):
        values = {**endpoint['defaults'], 'requestId': self._request_id(message), 'goal': message['text']}
        if endpoint['textInput']:
            values['inputValues'] = {'goal': message['text']}
        return ApplicationStart.model_validate(values)

    async def send(self, sender, endpoint_id, body: SendAssistantMessage):
        message, fresh = await asyncio.to_thread(self._reserve, sender, endpoint_id, body)
        if fresh:
            self.auth.require_member(sender)
            endpoint = await asyncio.to_thread(self.endpoints.resolve, endpoint_id)
            options = {}
            if endpoint.get('automaticBudget'):
                with self.db.read() as conn:
                    options['allocation_id'] = self._budget_allocation(conn, message, endpoint)['id']
            await self.runs.start(message['recipient_id'], self._start_body(message, endpoint), **options)
        return await asyncio.to_thread(self.read, sender, message['id'])

    async def recover(self, recipient, identifier, *, allocation_id=None, delivery_id=None):
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
            if endpoint.get('automaticBudget'):
                with self.db.read() as conn:
                    allocation_id = self._budget_allocation(conn, message, endpoint, allocation_id)['id']
            options = {'allocation_id': allocation_id} if allocation_id is not None else {}
            if delivery_id is not None:
                options['delivery_id'] = delivery_id
            await self.runs.start(recipient, self._start_body(message, endpoint), **options)
        return await asyncio.to_thread(self.read, recipient, identifier)

    def _budget_allocation(self, conn, message, endpoint, allocation_id=None):
        scopes = self.db.store.local_budget_scopes
        original = scopes.request_allocation(conn, message['recipient_id'],
            'application-start:' + self._request_id(message))
        if original is not None and allocation_id is not None and original != allocation_id:
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ALLOCATION_MISMATCH')
        identifier = original
        if identifier is None:
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ALLOCATION_MISSING')
        allocation = scopes._allocation(conn, message['recipient_id'], identifier)
        budget = endpoint['automaticBudget']
        if allocation['scope_id'] != budget['scopeId'] or allocation['body']['caps'] != budget['caps']:
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ALLOCATION_MISMATCH')
        return allocation

    def validate_admission(self, conn, owner, request_id, plan, allocation_id):
        prefix = 'application-start:assistant-message:'
        if not request_id.startswith(prefix):
            return
        message = self._row(conn, request_id[len(prefix):])
        if message['recipient_id'] != owner:
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ADMISSION_MISMATCH')
        self.auth.require_member(message['sender_id'])
        endpoint = self.endpoints.resolve(message['endpoint_id'])
        expected = self._start_body(message, endpoint).model_dump(exclude={'interfaceVersion', 'requestId'})
        prepared = conn.execute(text('SELECT plan_id,fingerprint FROM af_plan_requests '
            'WHERE owner_id=:owner AND request_id=:request'), {'owner': owner, 'request': request_id}).mappings().first()
        if (prepared is None or prepared['plan_id'] != plan['id'] or plan['ownerId'] != owner
                or prepared['fingerprint'] != digest(expected)):
            raise HTTPException(409, 'ASSISTANT_MESSAGE_ADMISSION_MISMATCH')
        if endpoint.get('automaticBudget'):
            self.endpoints.require_budget(conn, owner, endpoint['automaticBudget'])
            allocation = self._budget_allocation(conn, message, endpoint, allocation_id)
            if allocation['id'] != allocation_id:
                raise HTTPException(409, 'ASSISTANT_MESSAGE_ALLOCATION_MISMATCH')

    def message_for_task(self, owner, task_id):
        self.auth.require_member(owner)
        task = self.db.store.task(task_id, owner)
        prefix = 'application-start:assistant-message:'
        if not task['request_id'].startswith(prefix):
            return None
        with self.db.read() as conn:
            message = self._row(conn, task['request_id'][len(prefix):])
            if message['recipient_id'] != owner:
                raise HTTPException(409, 'ASSISTANT_MESSAGE_TASK_MISMATCH')
            endpoint = self.endpoints.owned(owner, message['endpoint_id'])
            if endpoint.get('automaticBudget'):
                allocation = self._budget_allocation(conn, message, endpoint)
                if allocation['task_id'] != task['id']:
                    raise HTTPException(409, 'ASSISTANT_MESSAGE_TASK_MISMATCH')
            scopes = self.db.store.local_budget_scopes
            delivery_id = scopes.request_delivery(conn, owner, task['request_id'])
            if delivery_id is not None:
                events = self.db.store.assistant_events
                delivery = events._row(conn, events.deliveries, delivery_id)
                if (delivery['owner_id'] != owner or delivery['message_id'] != message['id']
                        or scopes.request_allocation(conn, owner, task['request_id']) != delivery['allocation_id']):
                    raise HTTPException(409, 'ASSISTANT_MESSAGE_TASK_MISMATCH')
                allocation = scopes._allocation(conn, owner, delivery['allocation_id'])
                if allocation['task_id'] != task['id']:
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

    def reply_for_task(self, receiver, task_id, text, content_ids=()):
        body = AssistantReply(text=text, contentIds=list(content_ids))
        sources = sorted(set(body.contentIds))
        store = self.db.store
        with store.transaction() as conn:
            if store.engine.dialect.name == 'postgresql':
                store.local_budget_scopes.admission_lock(conn)
            with self.db.write() as conn:
                original = self.message_for_task(receiver, task_id)
                if original is None:
                    raise HTTPException(409, 'ASSISTANT_MESSAGE_TASK_MISMATCH')
                message = self._row(conn, original['messageId'])
                self._require_reply_sources(message, sources)
                reply = message['reply']
                if reply is not None:
                    if (reply['taskId'] != task_id or reply['text'] != body.text
                            or reply['contentIds'] != sources):
                        raise HTTPException(409, 'ASSISTANT_REPLY_CONFLICT')
                else:
                    conn.execute(self.messages.update().where(self.messages.c.id == message['id']).values(
                        reply={'taskId': task_id, 'text': body.text, 'contentIds': sources, 'createdAt': now()}))
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
        return {'state': 'available', **{key: reply[key] for key in ('text', 'contentIds', 'createdAt')}}

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
                    store.local_budget_scopes.admission_lock(conn)
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

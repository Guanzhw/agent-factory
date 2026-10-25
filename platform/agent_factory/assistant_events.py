"""Transactional content notifications; native admission remains the execution owner."""
import asyncio
import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Column, Float, Integer, JSON, MetaData, String, Table, UniqueConstraint, select, text

from .application_content import Label, ObjectId
from .assistant_messages import SendAssistantMessage
from .applications import GovernedStorage
from .local_budget_scopes import _caps
from .store import digest


DELIVERY_ERROR_CODES = frozenset({
    'LOCAL_BUDGET_EXHAUSTED', 'LOCAL_BUDGET_CLOSED_OR_EXPIRED',
    'LOCAL_BUDGET_SCOPE_NOT_FOUND',
    'LOCAL_BUDGET_BINDING_CONFLICT', 'LOCAL_BUDGET_REQUEST_CONFLICT',
    'ASSISTANT_ENDPOINT_DISABLED', 'APPLICATION_CONTENT_NOT_FOUND', 'RESOURCE_NOT_FOUND',
    'ASSISTANT_EVENT_EXPIRED', 'ASSISTANT_EVENT_PROPAGATION_LIMIT',
    'ASSISTANT_EVENT_SUBSCRIPTION_MISMATCH', 'ASSISTANT_EVENT_DELIVERY_MISMATCH',
    'ASSISTANT_EVENT_ADMISSION_MISMATCH', 'ASSISTANT_EVENT_ALLOCATION_MISMATCH',
    'ASSISTANT_DELIVERY_STOPPING',
})


def error_code(error):
    if isinstance(error, HTTPException):
        candidate = error.detail.get('code') if isinstance(error.detail, dict) else error.detail
        if isinstance(candidate, str) and candidate in DELIVERY_ERROR_CODES:
            return candidate
    return type(error).__name__


class EventSubscription(BaseModel):
    model_config = ConfigDict(extra='forbid')
    endpointId: ObjectId
    namespace: Label
    eventType: Label
    scopeId: str = Field(min_length=1, max_length=200)
    caps: dict
    deadline: float = Field(allow_inf_nan=False)
    maxDepth: int = Field(ge=0)
    maxCandidates: int = Field(ge=1, le=20)


class ContentEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    namespace: Label
    eventType: Label
    contentId: ObjectId
    candidates: list[ObjectId] = Field(max_length=20)
    deadline: float = Field(allow_inf_nan=False)


class AssistantEvents:
    def __init__(self, store, auth, endpoints, content, messages, scopes):
        self.admission_stopping: asyncio.Event | None = None
        self.store, self.auth, self.endpoints = store, auth, endpoints
        self.content, self.messages, self.scopes = content, messages, scopes
        self.db = GovernedStorage(store, 'af_assistant_events_v1')
        metadata = MetaData()
        self.subscriptions = Table('af_assistant_subscriptions', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('endpoint_id', String, nullable=False), Column('namespace', String, nullable=False),
            Column('event_type', String, nullable=False), Column('body', JSON, nullable=False),
            Column('enabled', Boolean, nullable=False))
        self.events = Table('af_assistant_events', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('body', JSON, nullable=False), Column('root_id', String, nullable=False),
            Column('depth', Integer, nullable=False), Column('deadline', Float, nullable=False),
            Column('scanned', Boolean, nullable=False), Column('attempted_at', Float, nullable=False),
            Column('error', String))
        self.deliveries = Table('af_assistant_event_deliveries', metadata,
            Column('id', String, primary_key=True), Column('event_id', String, nullable=False),
            Column('endpoint_id', String, nullable=False), Column('subscription_id', String),
            Column('owner_id', String), Column('message_id', String), Column('allocation_id', String),
            Column('state', String, nullable=False), Column('error', String),
            Column('attempted_at', Float, nullable=False),
            UniqueConstraint('event_id', 'endpoint_id'))
        self.commands = self.db.command_table('af_assistant_event_commands', metadata)
        metadata.create_all(store.engine)

    @staticmethod
    def _row(conn, table, identifier):
        row = conn.execute(select(table).where(table.c.id == identifier)).mappings().first()
        if row is None:
            raise HTTPException(404, 'ASSISTANT_EVENT_RECORD_NOT_FOUND')
        return dict(row)

    def configure(self, owner, configuration: EventSubscription, request_id):
        self.auth.require_member(owner)
        value = configuration.model_dump()
        value['caps'] = _caps(value['caps'])
        if value['caps']['rounds'] != 1:
            raise HTTPException(422, 'LOCAL_BUDGET_ONE_ROUND_REQUIRED')
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, digest(value))
            if old:
                return self._row(conn, self.subscriptions, old['id'])
            self.endpoints.owned(owner, value['endpointId'])
            scope = self.scopes._scope(conn, owner, value['scopeId'])
            if scope['state'] != 'ACTIVE' or not time.time() < value['deadline'] <= scope['body']['deadline']:
                raise HTTPException(409, 'ASSISTANT_SUBSCRIPTION_EXPIRED')
            existing = conn.execute(select(self.subscriptions.c.id).where(
                self.subscriptions.c.endpoint_id == value['endpointId'],
                self.subscriptions.c.namespace == value['namespace'],
                self.subscriptions.c.event_type == value['eventType'], self.subscriptions.c.enabled.is_(True))).first()
            if existing:
                raise HTTPException(409, 'ASSISTANT_SUBSCRIPTION_ALREADY_ENABLED')
            identifier = str(uuid4())
            conn.execute(self.subscriptions.insert().values(id=identifier, owner_id=owner,
                endpoint_id=value['endpointId'], namespace=value['namespace'], event_type=value['eventType'],
                body=value, enabled=True))
            self.db.record(conn, self.commands, owner, request_id, digest(value), 'subscription.configure', {'id': identifier})
            return self._row(conn, self.subscriptions, identifier)

    def set_enabled(self, owner, identifier, enabled, request_id):
        self.auth.require_member(owner)
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            with self.db.write():
                row = self._row(conn, self.subscriptions, identifier)
                if row['owner_id'] != owner:
                    raise HTTPException(404, 'ASSISTANT_EVENT_RECORD_NOT_FOUND')
                fingerprint = digest({'id': identifier, 'enabled': enabled})
                old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
                if not old:
                    if enabled:
                        conflict = conn.execute(select(self.subscriptions.c.id).where(
                            self.subscriptions.c.id != identifier, self.subscriptions.c.endpoint_id == row['endpoint_id'],
                            self.subscriptions.c.namespace == row['namespace'], self.subscriptions.c.event_type == row['event_type'],
                            self.subscriptions.c.enabled.is_(True))).first()
                        if conflict:
                            raise HTTPException(409, 'ASSISTANT_SUBSCRIPTION_ALREADY_ENABLED')
                    conn.execute(self.subscriptions.update().where(self.subscriptions.c.id == identifier).values(enabled=enabled))
                    self.db.record(conn, self.commands, owner, request_id, fingerprint, 'subscription.state', {'id': identifier})
                return self._row(conn, self.subscriptions, identifier)

    def emit(self, conn, owner, event: ContentEvent, request_id, *, parent_delivery_id=None, task_id=None):
        if conn is None or conn is not self.store._connection.get():
            raise RuntimeError('Event emit requires the current domain transaction')
        self.auth.require_member(owner)
        value = event.model_dump()
        fingerprint = digest({'event': value, 'parent': parent_delivery_id, 'task': task_id})
        with self.db.write():
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old:
                return self._row(conn, self.events, old['id'])
            publication = self.content.read(owner, value['contentId'])
            if publication['ownerId'] != owner:
                raise HTTPException(404, 'APPLICATION_CONTENT_NOT_FOUND')
            identifier = str(uuid4())
            root, depth, deadline = identifier, 0, value['deadline']
            if parent_delivery_id is not None:
                parent = self._row(conn, self.deliveries, parent_delivery_id)
                allocation = self.scopes._allocation(conn, owner, parent['allocation_id'])
                if parent['owner_id'] != owner or not task_id or allocation['task_id'] != task_id:
                    raise HTTPException(409, 'ASSISTANT_EVENT_PARENT_MISMATCH')
                origin = self._row(conn, self.events, parent['event_id'])
                root, depth, deadline = origin['root_id'], origin['depth'] + 1, min(deadline, origin['deadline'])
            elif task_id is not None:
                raise HTTPException(422, 'ASSISTANT_EVENT_PARENT_REQUIRED')
            if deadline <= time.time():
                raise HTTPException(409, 'ASSISTANT_EVENT_EXPIRED')
            conn.execute(self.events.insert().values(id=identifier, owner_id=owner, body=value,
                root_id=root, depth=depth, deadline=deadline, scanned=False, attempted_at=0))
            self.db.record(conn, self.commands, owner, request_id, fingerprint, 'event.emit', {'id': identifier})
            return self._row(conn, self.events, identifier)

    def _current(self, conn, event, subscription, endpoint_id):
        value, config = event['body'], subscription['body']
        self.auth.require_member(event['owner_id'])
        self.auth.require_member(subscription['owner_id'])
        if (not subscription['enabled'] or endpoint_id not in value['candidates']
                or subscription['endpoint_id'] != endpoint_id or config['namespace'] != value['namespace']
                or config['eventType'] != value['eventType']):
            raise HTTPException(409, 'ASSISTANT_EVENT_SUBSCRIPTION_MISMATCH')
        if time.time() >= min(event['deadline'], config['deadline']):
            raise HTTPException(409, 'ASSISTANT_EVENT_EXPIRED')
        if event['depth'] > config['maxDepth'] or len(value['candidates']) > config['maxCandidates']:
            raise HTTPException(409, 'ASSISTANT_EVENT_PROPAGATION_LIMIT')
        endpoint = self.endpoints.resolve(endpoint_id)
        if endpoint['ownerId'] != subscription['owner_id']:
            raise HTTPException(409, 'ASSISTANT_EVENT_OWNER_MISMATCH')
        self.content.read(subscription['owner_id'], value['contentId'])
        return endpoint

    def prepare(self, event_id, endpoint_id):
        with self.store.transaction() as conn:
            self.scopes.admission_lock(conn)
            with self.db.write():
                existing = conn.execute(select(self.deliveries).where(self.deliveries.c.event_id == event_id,
                    self.deliveries.c.endpoint_id == endpoint_id)).mappings().first()
                if existing:
                    return dict(existing)
                event = self._row(conn, self.events, event_id)
                value = event['body']
                if endpoint_id not in value['candidates']:
                    raise HTTPException(404, 'ASSISTANT_EVENT_CANDIDATE_NOT_FOUND')
                subscription = conn.execute(select(self.subscriptions).where(self.subscriptions.c.endpoint_id == endpoint_id,
                    self.subscriptions.c.namespace == value['namespace'], self.subscriptions.c.event_type == value['eventType'],
                    self.subscriptions.c.enabled.is_(True))).mappings().first()
                if subscription is None:
                    return None
                self._current(conn, event, subscription, endpoint_id)
                identifier, allocation_id = str(uuid4()), str(uuid4())
                config, owner = subscription['body'], subscription['owner_id']
                self.scopes.allocate(conn, owner, config['scopeId'], allocation_id,
                    digest({'event': event_id, 'endpoint': endpoint_id}), config['caps'])
                message, _ = self.messages._reserve(event['owner_id'], endpoint_id, SendAssistantMessage(
                    requestId='event:' + identifier, text='Shared content notification: ' + value['contentId']))
                conn.execute(self.deliveries.insert().values(id=identifier, event_id=event_id, endpoint_id=endpoint_id,
                    subscription_id=subscription['id'], owner_id=owner, message_id=message['id'],
                    allocation_id=allocation_id, state='pending', attempted_at=0))
                self.scopes.bind_request(conn, owner, allocation_id,
                    'application-start:' + self.messages._request_id(message), delivery_id=identifier)
                return self._row(conn, self.deliveries, identifier)

    def validate_admission(self, conn, owner, delivery_id, request_id, plan, allocation_id):
        if self.admission_stopping is not None and self.admission_stopping.is_set():
            raise HTTPException(409, 'ASSISTANT_DELIVERY_STOPPING')
        delivery = self._row(conn, self.deliveries, delivery_id)
        if (delivery['state'] != 'pending' or delivery['owner_id'] != owner
                or delivery['allocation_id'] != allocation_id):
            raise HTTPException(409, 'ASSISTANT_EVENT_DELIVERY_MISMATCH')
        event = self._row(conn, self.events, delivery['event_id'])
        subscription = self._row(conn, self.subscriptions, delivery['subscription_id'])
        endpoint = self._current(conn, event, subscription, delivery['endpoint_id'])
        message = self.messages._row(conn, delivery['message_id'])
        expected = self.messages._start_body(message, endpoint)
        if (request_id != 'application-start:' + expected.requestId or plan['ownerId'] != owner
                or plan['applicationRef'] != expected.applicationRef or plan['mode'] != expected.mode
                or plan['normalizedGoal'] != expected.goal):
            raise HTTPException(409, 'ASSISTANT_EVENT_ADMISSION_MISMATCH')
        allocation = self.scopes._allocation(conn, owner, allocation_id)
        if allocation['scope_id'] != subscription['body']['scopeId']:
            raise HTTPException(409, 'ASSISTANT_EVENT_ALLOCATION_MISMATCH')

    def subscriptions_for(self, owner):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            return [dict(row) for row in conn.execute(select(self.subscriptions).where(
                self.subscriptions.c.owner_id == owner).order_by(self.subscriptions.c.id)).mappings()]

    def delivery(self, owner, identifier):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            row = self._row(conn, self.deliveries, identifier)
            event = self._row(conn, self.events, row['event_id'])
            if owner not in {row['owner_id'], event['owner_id']}:
                raise HTTPException(404, 'ASSISTANT_EVENT_RECORD_NOT_FOUND')
            return row

    def delivery_for_task(self, owner, task_id):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            task = self.store.task(task_id, owner)
            delivery_id = self.scopes.request_delivery(conn, owner, task['request_id'])
            if delivery_id is None:
                return None
            try:
                delivery = self._row(conn, self.deliveries, delivery_id)
                allocation = self.scopes._allocation(conn, owner, delivery['allocation_id'])
                if (delivery['owner_id'] != owner or allocation['task_id'] != task['id']
                        or self.scopes.request_allocation(conn, owner, task['request_id']) != delivery['allocation_id']):
                    raise HTTPException(409, 'ASSISTANT_EVENT_TASK_BINDING_MISMATCH')
                event = self._row(conn, self.events, delivery['event_id'])
            except HTTPException as error:
                if error.status_code == 404:
                    raise HTTPException(409, 'ASSISTANT_EVENT_TASK_BINDING_MISMATCH') from error
                raise
            return {'contentId': event['body']['contentId'], 'eventId': event['id'],
                'deliveryId': delivery['id'], 'rootId': event['root_id'], 'depth': event['depth'],
                'scopeId': allocation['scope_id'], 'allocationId': delivery['allocation_id']}

    def _finish_attempt(self, delivery, error, settled=False):
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            current = self._row(conn, self.deliveries, delivery['id'])
            if current['state'] != 'pending':
                return
            state = 'settled' if settled else 'pending'
            if (isinstance(error, HTTPException) and error.status_code < 500
                    and error.detail != 'ASSISTANT_DELIVERY_STOPPING'):
                message = self.messages._row(conn, delivery['message_id'])
                task = conn.execute(text('SELECT id FROM af_tasks WHERE owner_id=:owner AND request_id=:request'),
                    {'owner': delivery['owner_id'],
                     'request': 'application-start:' + self.messages._request_id(message)}).first()
                if task is None:
                    state = 'rejected'
            with self.db.write():
                conn.execute(self.deliveries.update().where(self.deliveries.c.id == delivery['id']).values(
                    state=state, error=error_code(error) if error else None, attempted_at=time.time()))

    async def deliver_batch(self, limit=20, *, stopping=None):
        if not 1 <= limit <= 100:
            raise ValueError('Event batch must be between 1 and 100')
        with self.db.read() as conn:
            events = conn.execute(select(self.events).where(self.events.c.scanned.is_(False))
                .order_by(self.events.c.attempted_at, self.events.c.id).limit(limit)).mappings().all()
        completed_events, attempted_deliveries = 0, 0
        for event in events:
            if stopping is not None and stopping.is_set():
                return completed_events, attempted_deliveries
            retry, error_kind = False, None
            for endpoint_id in event['body']['candidates']:
                if stopping is not None and stopping.is_set():
                    return completed_events, attempted_deliveries
                try:
                    await asyncio.to_thread(self.prepare, event['id'], endpoint_id)
                except Exception as error:
                    error_kind = error_code(error)
                    if not isinstance(error, HTTPException) or error.status_code >= 500:
                        retry = True
                        continue
                    with self.db.write() as conn:
                        old = conn.execute(select(self.deliveries.c.id).where(self.deliveries.c.event_id == event['id'],
                            self.deliveries.c.endpoint_id == endpoint_id)).first()
                        if old is None:
                            conn.execute(self.deliveries.insert().values(id=str(uuid4()), event_id=event['id'],
                                endpoint_id=endpoint_id, state='rejected', error=error_kind, attempted_at=time.time()))
            with self.db.write() as conn:
                conn.execute(self.events.update().where(self.events.c.id == event['id']).values(
                    scanned=not retry, attempted_at=time.time(), error=error_kind))
            completed_events += 1
        with self.db.read() as conn:
            deliveries = conn.execute(select(self.deliveries).where(self.deliveries.c.state == 'pending')
                .order_by(self.deliveries.c.attempted_at, self.deliveries.c.id).limit(limit)).mappings().all()
        for delivery in deliveries:
            if stopping is not None and stopping.is_set():
                return completed_events, attempted_deliveries
            failure, settled = None, False
            try:
                await self.messages.recover(delivery['owner_id'], delivery['message_id'],
                    allocation_id=delivery['allocation_id'], delivery_id=delivery['id'])
            except Exception as error:
                failure = error
            try:
                result = await asyncio.to_thread(self.scopes.settle, delivery['owner_id'], delivery['allocation_id'])
                settled = result['state'] == 'SETTLED'
            except Exception as error:
                if failure is None:
                    failure = error
            await asyncio.to_thread(self._finish_attempt, delivery, failure, settled)
            attempted_deliveries += 1
        return completed_events, attempted_deliveries

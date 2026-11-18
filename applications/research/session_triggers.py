"""Standing chat instructions dispatch through the existing native turn admission."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import logging
import time
from typing import Literal
from uuid import uuid4

from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Boolean, Column, JSON, MetaData, String, Table, select

from agent_factory.store import digest, now
from .projects import RequestId


class CreateTrigger(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    title: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    source: Literal['external', 'cron', 'research']
    eventType: str | None = None
    cron: str | None = None
    timezone: str = 'UTC'
    keyword: str = ''

    @model_validator(mode='after')
    def source_configuration(self):
        if self.source == 'external' and not self.eventType:
            raise ValueError('External triggers require eventType')
        if self.source == 'cron':
            if not self.cron or not validate_cron_expr(self.cron):
                raise ValueError('Invalid cron expression')
            if not validate_timezone(self.timezone):
                raise ValueError('Invalid timezone')
        return self


class ExternalEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    eventType: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


class ResearchTriggers:
    def __init__(self, sessions):
        self.sessions, self.store, self.db = sessions, sessions.store, sessions.db
        metadata = MetaData()
        self.triggers = Table('research_session_triggers', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('session_id', String, nullable=False), Column('enabled', Boolean, nullable=False),
            Column('body', JSON, nullable=False))
        self.events = Table('research_trigger_events', metadata,
            Column('id', String, primary_key=True), Column('body', JSON, nullable=False))
        self.deliveries = Table('research_trigger_deliveries', metadata,
            Column('id', String, primary_key=True), Column('trigger_id', String, nullable=False),
            Column('session_id', String, nullable=False), Column('owner_id', String, nullable=False),
            Column('event_id', String, nullable=False), Column('body', JSON, nullable=False))
        self.commands = self.db.command_table('research_trigger_commands', metadata)
        metadata.create_all(self.store.engine)
        if self.store.engine.dialect.name == 'postgresql':
            with self.store.engine.begin() as conn:
                conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS research_trigger_due
                    ON research_session_triggers (((body->>'nextRunAt')::double precision))
                    WHERE enabled IS TRUE AND body->>'source' = 'cron'""")
                conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS research_delivery_state_created
                    ON research_trigger_deliveries ((body->>'state'), (body->>'createdAt'), id)""")


    @staticmethod
    def _view(row):
        body = deepcopy(row['body'])
        return {'id': row['id'], 'sessionId': row['session_id'], 'enabled': row['enabled'], **body}

    def create(self, owner, session_id, request):
        self.sessions.auth.require_member(owner)
        value = request.model_dump(exclude={'requestId'})
        fingerprint = digest({'sessionId': session_id, **value})
        with self.sessions._write() as conn:
            row = self.sessions._row(conn, owner, session_id)
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old:
                row = conn.execute(select(self.triggers).where(self.triggers.c.id == old['id'])).mappings().one()
                return self._view(row)
            identifier = str(uuid4())
            body = {**value, 'createdAt': now(),
                'nextRunAt': compute_next_run(request.cron, request.timezone) if request.source == 'cron' else None}
            conn.execute(self.triggers.insert().values(id=identifier, owner_id=owner,
                session_id=session_id, enabled=True, body=body))
            self.sessions._save_session(conn, row, {**row['body'], 'stopped': False, 'stopRequestId': None})
            self.db.record(conn, self.commands, owner, request.requestId, fingerprint, 'trigger.create', {'id': identifier})
            return self._view({'id': identifier, 'session_id': session_id, 'enabled': True, 'body': body})

    def listing(self, owner, session_id):
        self.sessions.auth.require_member(owner)
        with self.db.read() as conn:
            self.sessions._row(conn, owner, session_id)
            items = conn.execute(select(self.triggers).where(self.triggers.c.owner_id == owner,
                self.triggers.c.session_id == session_id)).mappings()
            deliveries = conn.execute(select(self.deliveries).where(self.deliveries.c.owner_id == owner,
                self.deliveries.c.session_id == session_id)).mappings()
            return {'items': [self._view(row) for row in items if not row['body'].get('discoveryDestination')], 'deliveries': [
                {'id': row['id'], 'triggerId': row['trigger_id'], 'eventId': row['event_id'], **row['body']}
                for row in sorted(deliveries, key=lambda item: item['body']['createdAt'], reverse=True)]}

    def delete(self, owner, session_id, identifier, request_id):
        self.sessions.auth.require_member(owner)
        with self.sessions._write() as conn:
            self.sessions._row(conn, owner, session_id)
            row = conn.execute(select(self.triggers).where(self.triggers.c.id == identifier,
                self.triggers.c.owner_id == owner, self.triggers.c.session_id == session_id)).mappings().first()
            if row is None:
                raise HTTPException(404, 'RESEARCH_TRIGGER_NOT_FOUND')
            fingerprint = digest({'delete': identifier})
            if not self.db.old(conn, self.commands, owner, request_id, fingerprint):
                conn.execute(self.triggers.update().where(self.triggers.c.id == identifier).values(enabled=False))
                self._stop_deliveries(conn, identifier)
                self.db.record(conn, self.commands, owner, request_id, fingerprint, 'trigger.delete', {'id': identifier})
        return {'id': identifier, 'enabled': False}

    def _stop_deliveries(self, conn, trigger_id):
        for row in conn.execute(select(self.deliveries).where(self.deliveries.c.trigger_id == trigger_id)).mappings():
            if row['body']['state'] == 'pending':
                self._save_delivery(conn, row, state='stopped')

    def stop(self, conn, owner, session_id):
        for row in conn.execute(select(self.triggers).where(self.triggers.c.owner_id == owner,
                self.triggers.c.session_id == session_id)).mappings():
            self._stop_deliveries(conn, row['id'])

    def published(self, conn, owner, publication):
        if publication['source']['application'] == 'research':
            self.emit(conn, owner, 'content:' + publication['id'], 'research', 'published',
                      {'contentId': publication['id']})

    def emit(self, conn, owner, event_id, source, event_type, payload, *, trigger_id=None):
        if conn is not self.store._connection.get():
            raise RuntimeError('Trigger events require the current domain transaction')
        with self.db.write():
            key = digest({'owner': owner, 'source': source, 'event': event_id, 'triggerId': trigger_id})
            value = {'eventId': event_id, 'source': source, 'eventType': event_type, 'payload': payload, 'ownerId': owner}
            old = conn.execute(select(self.events).where(self.events.c.id == key)).mappings().first()
            if old:
                if old['body'] != value:
                    raise HTTPException(409, 'RESEARCH_TRIGGER_EVENT_CONFLICT')
                return {'id': key, 'eventId': event_id}
            conn.execute(self.events.insert().values(id=key, body=value))
            candidates = select(self.triggers).where(self.triggers.c.enabled.is_(True),
                self.triggers.c.body['source'].as_string() == source)
            if trigger_id is not None:
                candidates = candidates.where(self.triggers.c.id == trigger_id)
            for row in conn.execute(candidates).mappings():
                body = row['body']
                if body['eventType'] and body['eventType'] != event_type:
                    continue
                discovery = getattr(self.sessions, 'discovery', None)
                kind = discovery.publication_kind(conn, row['owner_id'], row, owner) if discovery else None
                if kind == 'skip':
                    continue
                if source != 'research' and row['owner_id'] != owner:
                    continue
                if source == 'research':
                    try:
                        publication = self.sessions.content.read(row['owner_id'], payload['contentId'])
                        keyword = body['keyword'].casefold()
                        if keyword and keyword not in json.dumps(publication['content'], ensure_ascii=False).casefold():
                            continue
                    except HTTPException as error:
                        if error.status_code not in {403, 404}:
                            raise
                        continue
                identifier = digest({'event': key, 'trigger': row['id']})
                conn.execute(self.deliveries.insert().values(id=identifier, trigger_id=row['id'],
                    session_id=row['session_id'], owner_id=row['owner_id'], event_id=key,
                    body={**({'provenance': {'contentId': publication['id'], 'ownerId': publication['ownerId']}}
                        if source == 'research' else {}),
                        'kind': kind or 'task', 'state': 'stopped' if self.sessions._row(conn, row['owner_id'],
                        row['session_id'])['body']['stopped'] else 'pending',
                        'error': None, 'turnId': None, 'createdAt': now()}))
            return {'id': key, 'eventId': event_id}

    def ingest(self, owner, request):
        self.sessions.auth.require_member(owner)
        with self.sessions._write() as conn:
            return self.emit(conn, owner, request.requestId, 'external', request.eventType, request.payload)

    def _save_delivery(self, conn, row, **changes):
        conn.execute(self.deliveries.update().where(self.deliveries.c.id == row['id']).values(
            body={**row['body'], **changes}))

    def poll_sources(self):
        due = select(self.triggers).where(self.triggers.c.enabled.is_(True),
            self.triggers.c.body['source'].as_string() == 'cron',
            self.triggers.c.body['nextRunAt'].as_float() <= time.time())
        with self.db.read() as conn:
            if conn.execute(due.with_only_columns(self.triggers.c.id).limit(1)).first() is None:
                return
        # Recheck after admission so two workers cannot advance the same schedule twice.
        with self.sessions._write() as conn:
            for row in conn.execute(due).mappings():
                body = row['body']
                self.emit(conn, row['owner_id'], row['id'] + ':' + str(body['nextRunAt']),
                    'cron', 'tick', {'scheduledAt': body['nextRunAt']}, trigger_id=row['id'])
                conn.execute(self.triggers.update().where(self.triggers.c.id == row['id']).values(
                    body={**body, 'nextRunAt': compute_next_run(body['cron'], body['timezone'])}))

    async def deliver_batch(self):
        self.poll_sources()
        with self.db.read() as conn:
            rows = list(conn.execute(select(self.deliveries).where(
                self.deliveries.c.body['state'].as_string() == 'pending').order_by(
                    self.deliveries.c.body['createdAt'].as_string(), self.deliveries.c.id)).mappings())
        for delivery in rows:
            await self._deliver(delivery)

    async def _deliver(self, delivery):
        owner, session_id = delivery['owner_id'], delivery['session_id']
        try:
            self.sessions.auth.require_member(owner)
            await self.sessions._refresh(owner, session_id)
            with self.sessions._write() as conn:
                current = conn.execute(select(self.deliveries).where(self.deliveries.c.id == delivery['id'])).mappings().one()
                trigger = conn.execute(select(self.triggers).where(self.triggers.c.id == delivery['trigger_id'])).mappings().one()
                row = self.sessions._row(conn, owner, session_id)
                if current['body']['state'] != 'pending':
                    return
                if not trigger['enabled'] or row['body']['stopped']:
                    self._save_delivery(conn, current, state='stopped')
                    return
                event = conn.execute(select(self.events).where(self.events.c.id == delivery['event_id'])).mappings().one()['body']
                if current['body'].get('turnId'):
                    turn_id, fresh = current['body']['turnId'], False
                else:
                    turn_id, fresh = self._reserve_event(owner, session_id, current, trigger, event)
                self._save_delivery(conn, current, turnId=turn_id, error=None)
            await self.sessions._dispatch(owner, session_id, turn_id, fresh, recover=True)
            with self.sessions._write() as conn:
                current = conn.execute(select(self.deliveries).where(self.deliveries.c.id == delivery['id'])).mappings().one()
                turn = conn.execute(select(self.sessions.turns).where(
                    self.sessions.turns.c.id == turn_id)).mappings().one()
                body = turn['body']
                if current['body'].get('adoptedAt'):
                    return
                self._save_delivery(conn, current,
                    state='failed' if body['status'] == 'failed' else 'dispatched',
                    error=body.get('failure'))
        except HTTPException as error:
            code = error.detail.get('code') if isinstance(error.detail, dict) else str(error.detail)
            with self.sessions._write() as conn:
                current = conn.execute(select(self.deliveries).where(self.deliveries.c.id == delivery['id'])).mappings().one()
                if current['body']['state'] != 'pending':
                    return
                self._save_delivery(conn, current, error=None if code == 'RESEARCH_TURN_ACTIVE_OR_UNCONFIRMED' else code,
                    state='pending' if code == 'RESEARCH_TURN_ACTIVE_OR_UNCONFIRMED' else 'failed')
        except Exception as error:
            with self.sessions._write() as conn:
                current = conn.execute(select(self.deliveries).where(self.deliveries.c.id == delivery['id'])).mappings().one()
                if current['body']['state'] != 'pending':
                    return
                self._save_delivery(conn, current, error=str(error))

    def receipts(self, conn, owner, session_id):
        return [{'id': item['id'], 'eventId': item['event_id'], **item['body']}
            for item in conn.execute(select(self.deliveries).where(
                self.deliveries.c.owner_id == owner, self.deliveries.c.session_id == session_id)).mappings()
            if item['body'].get('kind') in {'evidence', 'task'}]

    def receive(self, conn, row, turn):
        body = deepcopy(turn['body'])
        source_ids = list(row['body']['sharedSourceIds'])
        for delivery in conn.execute(select(self.deliveries).where(
                self.deliveries.c.owner_id == row['owner_id'],
                self.deliveries.c.session_id == row['id'])).mappings():
            if delivery['body'].get('kind') != 'evidence' or delivery['body']['state'] != 'pending':
                continue
            # A reserved continuation owns its input even if its acknowledgement was lost.
            if delivery['body'].get('turnId'):
                continue
            trigger = conn.execute(select(self.triggers).where(
                self.triggers.c.id == delivery['trigger_id'])).mappings().one()
            if not trigger['enabled']:
                continue
            event = conn.execute(select(self.events).where(
                self.events.c.id == delivery['event_id'])).mappings().one()['body']
            try:
                text, origin, sources = self._event_input(row['owner_id'], delivery, trigger, event)
            except HTTPException as error:
                if error.status_code not in {403, 404}:
                    raise
                self._save_delivery(conn, delivery, state='failed', error='RESEARCH_SOURCE_UNAVAILABLE')
                continue
            message = self.sessions._message('evidence', text)
            message.update(id='research-evidence:' + delivery['id'], createdAt=delivery['body']['createdAt'], origin=origin)
            body['messages'].append(message)
            body['sharedSourceIds'] = list(dict.fromkeys([*body.get('sharedSourceIds', []), *sources]))
            source_ids = list(dict.fromkeys([*source_ids, *sources]))
            self._save_delivery(conn, delivery, state='adopted', turnId=turn['id'], adoptedAt=now(), error=None)
        if body != turn['body']:
            self.sessions._save_turn(conn, turn, body)
            self.sessions._save_session(conn, row, {**row['body'], 'sharedSourceIds': source_ids})
        return {**turn, 'body': body}

    def included(self, conn, turn):
        for delivery in conn.execute(select(self.deliveries).where(
                self.deliveries.c.session_id == turn['session_id'])).mappings():
            if (delivery['body'].get('kind') in {'evidence', 'task'}
                    and delivery['body'].get('turnId') == turn['id']
                    and not delivery['body'].get('adoptedAt')):
                self._save_delivery(conn, delivery, state='adopted', adoptedAt=now(), error=None)

    def _event_input(self, owner, delivery, trigger, event):
        payload = deepcopy(event['payload'])
        source_ids = []
        attribution = {}
        if event['source'] == 'research':
            publication = self.sessions.content.read(owner, payload['contentId'])
            source_ids = [payload['contentId']]
            attribution = {'contentId': publication['id'], 'ownerId': publication['ownerId']}
            payload.update(attribution, content=publication['content'])
        if delivery['body'].get('kind') == 'discovery':
            payload['routingContext'] = self.sessions.discovery.context(owner)
            source_ids = sorted(set(source_ids) | set(payload['routingContext'].pop('sourceIds')))
        origin = {'kind': 'trigger', 'triggerId': trigger['id'], 'triggerTitle': trigger['body']['title'],
            'eventId': event['eventId'], 'source': event['source'], 'eventType': event['eventType'],
            **attribution}
        text = delivery['body'].get('instruction', trigger['body']['instruction']) + '\n\nTrigger event:\n' + json.dumps(
            {'eventId': event['eventId'], 'source': event['source'], 'eventType': event['eventType'],
             'payload': payload}, ensure_ascii=False)
        if delivery['body'].get('kind') == 'evidence':
            text = '同事提供的新证据（参考资料）：\n' + text
        return text, origin, source_ids

    def _reserve_event(self, owner, session_id, delivery, trigger, event):
        from .session_routes import SessionTurn
        text, origin, source_ids = self._event_input(owner, delivery, trigger, event)
        request = SessionTurn(requestId='trigger:' + delivery['id'], text=text)
        turn_id, fresh = self.sessions._reserve(owner, session_id, request, origin=origin, source_ids=source_ids)
        return turn_id, fresh

@asynccontextmanager
async def trigger_lifespan(app):
    service = app.state.factory.get('research_triggers')
    stopping = asyncio.Event()
    async def run():
        while not stopping.is_set():
            try:
                await service.deliver_batch()
            except Exception:
                logging.getLogger(__name__).exception('Research trigger dispatch deferred')
            try:
                await asyncio.wait_for(stopping.wait(), timeout=1)
            except TimeoutError:
                pass
    task = asyncio.create_task(run(), name='research-session-triggers')
    try:
        yield
    finally:
        stopping.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def event_router(auth, service):
    router = APIRouter(prefix='/api/factory/research')
    @router.post('/events')
    async def event(request: Request, body: ExternalEvent):
        return await asyncio.to_thread(service.ingest, auth.user(request)['id'], body)
    return router

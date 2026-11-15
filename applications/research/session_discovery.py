"""Member-selected semantic discovery uses ordinary native research turns."""
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.store import digest, now
from .projects import Reference, RequestId


INSTRUCTION = (
    'Evaluate this new team publication against my project objectives and current work. '
    'Judge meaning, not overlapping words. Call research_route_discovery exactly once: '
    'ignore if no useful follow-up; attach to an existing ordinary session for the same problem; '
    'new for a useful independent question. Give the evidence-based reason and a concrete instruction '
    'for attach/new. Never select this discovery trace as a destination. Do not execute or publish '
    'the follow-up here; the selected destination will execute it using my resources.'
)


class DiscoveryConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    enabled: bool
    modelConnectionRef: Reference | None = None
    instruction: str = ''

    @model_validator(mode='after')
    def selected_model(self):
        if self.enabled and not self.modelConnectionRef:
            raise ValueError('Select a model to enable discovery')
        return self


class DiscoveryDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['ignore', 'attach', 'new']
    reason: str = Field(min_length=1)
    sessionId: Reference | None = None
    title: str | None = None
    instruction: str | None = None
    projectId: Reference | None = None


class ResearchDiscovery:
    def __init__(self, sessions):
        self.sessions, self.triggers, self.db = sessions, sessions.triggers, sessions.db
        metadata = MetaData()
        self.settings = Table('research_discovery_settings', metadata,
            Column('owner_id', String, primary_key=True), Column('body', JSON, nullable=False))
        self.decisions = Table('research_discovery_decisions', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('event_id', String, nullable=False), Column('body', JSON, nullable=False))
        metadata.create_all(sessions.store.engine)

    def listing(self, owner):
        self.sessions.auth.require_member(owner)
        with self.db.read() as conn:
            setting = conn.execute(select(self.settings.c.body).where(self.settings.c.owner_id == owner)).scalar()
            rows = conn.execute(select(self.decisions).where(self.decisions.c.owner_id == owner)).mappings()
            decisions = []
            for row in rows:
                body = deepcopy(row['body'])
                try:
                    self.sessions.content.read(owner, body['contentId'])
                except HTTPException as error:
                    if error.status_code not in {403, 404}:
                        raise
                    body = {**body, 'reason': '共享来源已不可用。', 'sourceUnavailable': True}
                delivery = conn.execute(select(self.triggers.deliveries.c.body).where(
                    self.triggers.deliveries.c.id == body.get('deliveryId'))).scalar()
                decisions.append({'id': row['id'], 'eventId': row['event_id'], **body,
                                  'delivery': delivery})
            if setting and setting.get('sessionId'):
                trace = self.sessions._row(conn, owner, setting['sessionId'])
                setting = {**setting, 'enabled': setting['enabled'] and not trace['body']['stopped']}
            return {**(setting or {'enabled': False, 'modelConnectionRef': None,
                                  'instruction': '', 'sessionId': None}),
                    'decisions': sorted(decisions, key=lambda item: item['createdAt'], reverse=True)}

    def configure(self, owner, request):
        from .session_routes import CreateSession
        from .session_triggers import CreateTrigger
        self.sessions.auth.require_member(owner)
        fingerprint = digest({'discovery': request.model_dump(exclude={'requestId'})})
        with self.sessions._write() as conn:
            old = self.db.old(conn, self.triggers.commands, owner, request.requestId, fingerprint)
            if old:
                return self.listing(owner)
            previous = conn.execute(select(self.settings.c.body).where(self.settings.c.owner_id == owner)).scalar()
            session_id = (previous or {}).get('sessionId')
            trigger_id = (previous or {}).get('triggerId')
            if request.enabled:
                configuration = self.sessions.setup.prepare(owner, request.modelConnectionRef)
                if not session_id:
                    session_id = self.sessions.create(owner, CreateSession(
                        requestId='discovery:' + digest(owner)[:32], title='团队材料主动发现',
                        goal=INSTRUCTION, modelConnectionRef=request.modelConnectionRef))
                row = self.sessions._row(conn, owner, session_id)
                self.sessions._save_session(conn, row, {**row['body'], 'configuration': configuration,
                    'stopped': False, 'stopRequestId': None})
                if not trigger_id:
                    trigger = self.triggers.create(owner, session_id, CreateTrigger(
                        requestId='discovery-trigger:' + digest(owner)[:32], source='research',
                        title='团队材料语义发现', instruction=INSTRUCTION))
                    trigger_id = trigger['id']
            if trigger_id:
                conn.execute(self.triggers.triggers.update().where(self.triggers.triggers.c.id == trigger_id)
                    .values(enabled=request.enabled))
                if not request.enabled:
                    self.triggers._stop_deliveries(conn, trigger_id)
            body = {**request.model_dump(exclude={'requestId'}), 'sessionId': session_id, 'triggerId': trigger_id}
            if previous is None:
                conn.execute(self.settings.insert().values(owner_id=owner, body=body))
            else:
                conn.execute(self.settings.update().where(self.settings.c.owner_id == owner).values(body=body))
            self.db.record(conn, self.triggers.commands, owner, request.requestId, fingerprint,
                           'discovery.configure', {'sessionId': session_id})
        return self.listing(owner)

    def publication_kind(self, conn, owner, trigger, publisher):
        setting = conn.execute(select(self.settings.c.body).where(self.settings.c.owner_id == owner)).scalar()
        if setting and setting.get('triggerId') == trigger['id']:
            return 'discovery' if setting['enabled'] and owner != publisher else 'skip'
        # Destination triggers represent one decision, never a standing subscription.
        if trigger['body'].get('discoveryDestination'):
            return 'skip'
        return None

    def context(self, owner):
        with self.db.read() as conn:
            setting = conn.execute(select(self.settings.c.body).where(self.settings.c.owner_id == owner)).scalar_one()
            discovery_ids = {
                body['sessionId'] for body in conn.execute(select(self.settings.c.body)).scalars()}
            projects = []
            source_ids = set()
            discovered_sources = {body['sessionId']: body['contentId'] for body in conn.execute(
                select(self.decisions.c.body).where(self.decisions.c.owner_id == owner)).scalars()
                if body['decision'] == 'new'}
            for row in conn.execute(select(self.sessions.projects.projects).where(
                    self.sessions.projects.projects.c.owner_id == owner)).mappings():
                if row['state'] != 'ended':
                    project = self.sessions.projects.read(owner, row['id'])
                    if not project.get('sourceUnavailable'):
                        projects.append(project)
                        if self.sessions.projects.peer_sources is not None:
                            source_ids.update(self.sessions.projects.peer_sources.project_dependencies(row['id']))
            work = []
            for row in conn.execute(select(self.sessions.sessions).where(
                    self.sessions.sessions.c.owner_id == owner)).mappings():
                if row['id'] in discovery_ids:
                    continue
                body = row['body']
                turns = self.sessions._turns(conn, row['id'])
                try:
                    if row['id'] in discovered_sources:
                        self.sessions._sources(owner, [discovered_sources[row['id']]])
                    self.sessions._context_sources(owner, row, turns)
                except HTTPException as error:
                    if not isinstance(error.detail, dict) or error.detail.get('code') not in {
                            'RESEARCH_SOURCE_UNAVAILABLE', 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE'}:
                        raise
                    continue
                source_ids.update(body['sharedSourceIds'])
                if row['id'] in discovered_sources:
                    source_ids.add(discovered_sources[row['id']])
                work.append({'sessionId': row['id'], 'title': body['title'], 'goal': body['goal'],
                    'projectId': body.get('projectId'), 'stopped': body['stopped'],
                    'status': turns[-1]['body']['status'] if turns else 'idle'})
            return {'projects': projects, 'work': work, 'memberInstruction': setting['instruction'],
                    'sourceIds': sorted(source_ids)}

    def decide(self, context, values):
        from .session_routes import CreateSession
        request = DiscoveryDecision.model_validate(values)
        owner = context.user_id
        with self.sessions._write() as conn:
            row, turn, task = self.sessions._execution(conn, context)
            if task['researchChild']:
                raise HTTPException(409, 'RESEARCH_DISCOVERY_ORIGINAL_TURN_REQUIRED')
            origin = turn['body'].get('origin') or {}
            delivery = conn.execute(select(self.triggers.deliveries).where(
                self.triggers.deliveries.c.owner_id == owner,
                self.triggers.deliveries.c.body['turnId'].as_string() == turn['id'])).mappings().first()
            if delivery is None or delivery['body'].get('kind') != 'discovery':
                raise HTTPException(409, 'RESEARCH_DISCOVERY_ORIGINAL_EVENT_REQUIRED')
            event_id = delivery['event_id']
            identifier = digest({'discoveryOwner': owner, 'event': event_id})
            old = conn.execute(select(self.decisions).where(self.decisions.c.id == identifier)).mappings().first()
            if old:
                return {'id': identifier, **old['body']}
            setting = conn.execute(select(self.settings.c.body).where(self.settings.c.owner_id == owner)).scalar_one()
            if not setting['enabled'] or setting['sessionId'] != row['id']:
                raise HTTPException(409, 'RESEARCH_DISCOVERY_DISABLED')
            self.sessions.content.read(owner, origin['contentId'])
            destination, delivery_id = None, None
            if request.decision != 'ignore':
                if not request.instruction:
                    raise ValueError('Attach/new requires an actionable instruction')
                if request.decision == 'attach':
                    if not request.sessionId:
                        raise ValueError('Attach requires sessionId')
                    destination = request.sessionId
                    if destination not in {item['sessionId'] for item in self.context(owner)['work']}:
                        raise ValueError('Choose an existing ordinary session')
                    target = self.sessions._row(conn, owner, destination)
                    if target['body']['stopped']:
                        raise ValueError('The destination was stopped by its owner')
                else:
                    if not request.title:
                        raise ValueError('New work requires title')
                    destination = self.sessions.create(owner, CreateSession(
                        requestId='discovery-work:' + identifier[:48], title=request.title,
                        # Source-derived instructions belong to the sourced first turn, which can be withdrawn.
                        goal='跟进团队材料提出的独立研究问题；具体问题与来源见首轮消息。', projectId=request.projectId,
                        modelConnectionRef=row['body']['configuration']['connectionRefs']['model']))
                trigger_id = 'discovery-route:' + identifier
                conn.execute(self.triggers.triggers.insert().values(id=trigger_id, owner_id=owner,
                    session_id=destination, enabled=True, body={'title': request.title or '团队新证据',
                    'instruction': request.instruction, 'discoveryDestination': True}))
                delivery_id = digest({'event': event_id, 'decision': identifier})
                conn.execute(self.triggers.deliveries.insert().values(id=delivery_id, trigger_id=trigger_id,
                    owner_id=owner, session_id=destination, event_id=event_id,
                    body={'state': 'pending', 'kind': 'evidence' if request.decision == 'attach' else 'task',
                        'instruction': request.instruction + '\n发现理由：' + request.reason,
                        'provenance': {'contentId': origin['contentId'], 'ownerId': origin['ownerId'],
                            'decisionId': identifier, 'discoverySessionId': row['id']},
                        'createdAt': now(), 'turnId': None, 'error': None}))
            body = {'decision': request.decision, 'reason': request.reason,
                'contentId': origin['contentId'], 'ownerId': origin['ownerId'],
                'sessionId': destination, 'discoverySessionId': row['id'],
                'deliveryId': delivery_id, 'createdAt': now()}
            conn.execute(self.decisions.insert().values(id=identifier, owner_id=owner, event_id=event_id, body=body))
            return {'id': identifier, **body}


def discovery_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/discovery')
    @router.get('')
    def listing(request: Request):
        return service.listing(auth.user(request)['id'])
    @router.post('')
    def configure(request: Request, body: DiscoveryConfiguration):
        return service.configure(auth.user(request)['id'], body)
    return router

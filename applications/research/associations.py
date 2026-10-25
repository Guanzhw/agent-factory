"""Selective research notifications over the existing endpoint event queue."""
from copy import deepcopy
import json
import re
import unicodedata
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.assistant_events import ContentEvent
from agent_factory.store import now


def terms(value):
    text = unicodedata.normalize('NFKC', str(value)).casefold()
    ignored = {'research', 'experiment', 'result', 'study', '研究', '实验', '结果', '数据', '模型'}
    words = set(re.findall(r'[a-z0-9]{3,}', text))
    for sequence in re.findall(r'[\u3400-\u9fff]+', text):
        words.update(sequence[i:i + 2] for i in range(len(sequence) - 1))
    return words - ignored


def research_terms(body):
    experiment = body.get('experiment') or {}
    values = [body.get('objective'), body.get('conditions'), body.get('hypothesis'),
              experiment.get('hypothesis'), experiment.get('conditions')]
    def strings(value):
        if isinstance(value, dict):
            return ' '.join(strings(item) for item in value.values())
        if isinstance(value, list):
            return ' '.join(strings(item) for item in value)
        return value if isinstance(value, str) else ''
    return terms(' '.join(strings(value) for value in values))


class ResearchAssociations:
    def __init__(self, sources, assistants, events):
        self.sources, self.assistants, self.events = sources, assistants, events
        self.content, self.db = sources.content, sources.db
        metadata = MetaData()
        self.intents = Table('research_association_intents', metadata,
            Column('content_id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('event_id', String, unique=True), Column('candidates', JSON, nullable=False))
        self.analyses = Table('research_associations', metadata,
            Column('id', String, primary_key=True), Column('task_id', String, unique=True, nullable=False),
            Column('run_id', String, nullable=False), Column('delivery_id', String, unique=True, nullable=False),
            Column('owner_id', String, nullable=False), Column('sender_id', String, nullable=False),
            Column('content_ids', JSON, nullable=False), Column('source_ids', JSON, nullable=False),
            Column('answer', JSON), Column('created_at', String, nullable=False))
        metadata.create_all(self.db.store.engine)

    def prepare(self, conn, owner, content_id):
        if conn.execute(select(self.intents).where(self.intents.c.content_id == content_id)).first():
            return
        trigger = self.content.read(owner, content_id)
        if trigger['content'].get('kind') not in {'research.experiment.start', 'research.round.terminal'}:
            return
        configuration = self.assistants.association_configuration(owner)
        if configuration is None:
            conn.execute(self.intents.insert().values(content_id=content_id, owner_id=owner, event_id=None, candidates=[]))
            return
        words = research_terms(trigger['content'])
        ranked = []
        for item in self.content.list(owner, limit=50)['items']:
            if item['ownerId'] == owner or item['visibility'] != 'team' or item['source']['application'] != 'research':
                continue
            try:
                candidate = self.content.read(owner, item['id'])
                recipient = self.assistants.association_configuration(item['ownerId'])
                if recipient is None:
                    continue
                self.content.read(item['ownerId'], content_id)
            except HTTPException as error:
                if error.status_code not in {403, 404}:
                    raise
                continue
            score = len(words & research_terms(candidate['content']))
            if score:
                ranked.append((-score, item['id'], item['ownerId'], recipient['endpointId']))
        selected, owners = [], set()
        for score, identifier, author, endpoint in sorted(ranked):
            if author in owners:
                continue
            selected.append({'contentId': identifier, 'ownerId': author, 'endpointId': endpoint,
                             'score': -score, 'rule': 'research-terms-v1'})
            owners.add(author)
            if len(selected) == configuration['associations']['maxRecipients']:
                break
        event_id = None
        if selected:
            event = self.events.emit(conn, owner, ContentEvent(namespace='research', eventType='evidence.available',
                contentId=content_id, candidates=[item['endpointId'] for item in selected],
                deadline=configuration['budget']['deadline']), 'research-associate:' + content_id)
            event_id = event['id']
        conn.execute(self.intents.insert().values(content_id=content_id, owner_id=owner,
            event_id=event_id, candidates=selected))

    def context(self, ctx, message, delivery):
        with self.sources.guard() as conn:
            intent = conn.execute(select(self.intents).where(self.intents.c.event_id == delivery['eventId'])).mappings().first()
            candidate = next((item for item in intent['candidates'] if item['endpointId'] == message['endpointId']), None) if intent else None
            if (intent is None or candidate is None or candidate['ownerId'] != ctx.user_id
                    or intent['owner_id'] != message['senderId'] or intent['content_id'] != delivery['contentId']):
                raise HTTPException(409, 'RESEARCH_ASSOCIATION_ORIGINAL_EVENT_REQUIRED')
            row = conn.execute(select(self.analyses).where(self.analyses.c.task_id == ctx.session_id)).mappings().first()
            ids = [intent['content_id'], candidate['contentId']]
            if row:
                self._original(row, ctx, delivery)
                ids = row['content_ids']
            selected = []
            for identifier in ids:
                source = self.content.read(ctx.user_id, identifier)
                self.content.read(message['senderId'], identifier)
                if source['visibility'] != 'team':
                    raise HTTPException(404, 'RESEARCH_SOURCE_UNAVAILABLE')
                selected.append({key: source[key] for key in ('id', 'source', 'content', 'verificationStatus')})
            if len(json.dumps(selected, ensure_ascii=False).encode()) > 16384:
                raise HTTPException(422, 'RESEARCH_ASSOCIATION_INPUT_TOO_LARGE')
            dependencies = sorted({identifier for source_id in ids
                                   for identifier in self.sources.source_dependencies(source_id, actor=ctx.user_id)})
            if row is None:
                conn.execute(self.analyses.insert().values(id=str(uuid4()), task_id=ctx.session_id, run_id=ctx.run_id,
                    delivery_id=delivery['deliveryId'], owner_id=ctx.user_id, sender_id=message['senderId'],
                    content_ids=ids, source_ids=dependencies, created_at=now()))
            elif row['source_ids'] != dependencies:
                raise HTTPException(409, 'RESEARCH_ASSOCIATION_ORIGINAL_INPUT_REQUIRED')
            return {'question': 'Compare these two research records. Explain related evidence, differing conditions, or no useful relation.',
                    'purpose': 'association', 'sources': selected,
                    'search': {'candidateLimit': 50, 'sourceLimit': 8, 'byteLimit': 16384, 'insufficientEvidence': False}}

    @staticmethod
    def _original(row, ctx, delivery):
        if row['owner_id'] != ctx.user_id or row['run_id'] != ctx.run_id or row['delivery_id'] != delivery['deliveryId']:
            raise HTTPException(409, 'RESEARCH_ASSOCIATION_ORIGINAL_INPUT_REQUIRED')

    def record(self, ctx, delivery, answer):
        with self.sources.guard() as conn:
            row = conn.execute(select(self.analyses).where(self.analyses.c.task_id == ctx.session_id)).mappings().first()
            if row is None:
                raise HTTPException(409, 'RESEARCH_ASSOCIATION_ORIGINAL_INPUT_REQUIRED')
            self._original(row, ctx, delivery)
            self.sources.require(ctx.user_id, row['source_ids'])
            self.sources.require(row['sender_id'], row['source_ids'])
            if answer.relation is None or set(answer.citations) != set(row['content_ids']):
                raise HTTPException(422, 'RESEARCH_ASSOCIATION_COMPLETE_CITATIONS_REQUIRED')
            value = answer.model_dump()
            if row['answer'] is not None and row['answer'] != value:
                raise HTTPException(409, 'RESEARCH_ASSOCIATION_ANSWER_CONFLICT')
            conn.execute(self.analyses.update().where(self.analyses.c.id == row['id']).values(answer=value))
            return {'associationId': row['id'], 'state': 'not_related' if answer.relation == 'not_related' else 'available'}

    def _projection(self, actor, row):
        self.assistants.auth.require_member(row['owner_id'])
        self.sources.require(actor, row['source_ids'])
        if row['answer'] is None or row['answer']['relation'] == 'not_related':
            raise HTTPException(404, 'RESEARCH_ASSOCIATION_NOT_FOUND')
        return {'id': row['id'], 'ownerId': row['owner_id'], 'sourceIds': list(row['source_ids']),
                'inputContentIds': list(row['content_ids']), 'analysis': deepcopy(row['answer']), 'createdAt': row['created_at']}

    def read(self, actor, identifier):
        self.assistants.auth.require_member(actor)
        with self.sources.guard() as conn:
            row = conn.execute(select(self.analyses).where(self.analyses.c.id == identifier)).mappings().first()
            if row is None:
                raise HTTPException(404, 'RESEARCH_ASSOCIATION_NOT_FOUND')
            return self._projection(actor, row)

    def for_round(self, owner, round_id, project_id, agreement):
        bound = self.sources.bound(round_id)
        if bound is None:
            words = terms(agreement.objective + ' ' + agreement.evaluation + ' ' + agreement.stopConditions)
            ranked = []
            for source in self.content.list(owner, limit=50)['items']:
                if source['ownerId'] == owner or source['visibility'] != 'team' or source['source']['application'] != 'research':
                    continue
                score = len(words & research_terms(source['content']))
                if score:
                    item = {'id': source['id'], 'kind': 'original_record', 'sources': [source],
                            'sourceIds': self.sources.source_dependencies(source['id'], actor=owner)}
                    ranked.append((-score, source['id'], item))
            for item in self.list(owner)['items']:
                original = [self.content.read(owner, identifier) for identifier in item['sourceIds']]
                score = len(words & set().union(*(research_terms(source['content']) for source in original)))
                if score:
                    ranked.append((-score, item['id'], {**item, 'kind': 'association', 'sources': original}))
            selected, size = [], 0
            for _, _, item in sorted(ranked):
                encoded = len(json.dumps(item, ensure_ascii=False).encode())
                displayed = {source['id'] for candidate in [*selected, item] for source in candidate['sources']}
                if size + encoded <= 16384 and len(displayed) <= 8:
                    selected.append(item)
                    size += encoded
            dependencies = set(self.sources.project_dependencies(project_id))
            dependencies.update(identifier for item in selected for identifier in item['sourceIds'])
            self.sources.bind(round_id, project_id, dependencies,
                [item['id'] for item in selected if item['kind'] == 'association'],
                [item['id'] for item in selected if item['kind'] == 'original_record'])
        return self.round_inputs(owner, round_id)

    def round_inputs(self, owner, round_id):
        bound = self.sources.bound(round_id)
        if bound is None:
            return []
        self.sources.require(owner, bound['source_ids'])
        result = []
        for identifier in bound['content_ids']:
            result.append({'id': identifier, 'kind': 'original_record', 'sources': [self.content.read(owner, identifier)],
                           'sourceIds': self.sources.source_dependencies(identifier, actor=owner)})
        for identifier in bound['association_ids']:
            item = self.read(owner, identifier)
            item['kind'] = 'association'
            item['sources'] = [self.content.read(owner, source_id) for source_id in item['sourceIds']]
            result.append(item)
        return result

    def list(self, actor, *, after='', limit=50):
        self.assistants.auth.require_member(actor)
        with self.sources.guard() as conn:
            rows = conn.execute(select(self.analyses).where(self.analyses.c.id > after)
                .order_by(self.analyses.c.id).limit(limit + 1)).mappings().all()
            items = []
            for row in rows[:limit]:
                try:
                    items.append(self._projection(actor, row))
                except HTTPException as error:
                    if error.status_code not in {403, 404}:
                        raise
            return {'items': items, 'nextCursor': rows[limit - 1]['id'] if len(rows) > limit else None}


def associations_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/associations')

    @router.get('')
    def listing(request: Request, after: str = Query(default='', max_length=200), limit: int = Query(default=50, ge=1, le=50)):
        return service.list(auth.user(request)['id'], after=after, limit=limit)

    @router.get('/{identifier}')
    def read(identifier: str, request: Request):
        return service.read(auth.user(request)['id'], identifier)

    return router

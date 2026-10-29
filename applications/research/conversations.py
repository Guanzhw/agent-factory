"""Research origins for existing private assistant messages and replies."""
import asyncio
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import Column, MetaData, String, Table, select

from agent_factory.application_content import ObjectId
from agent_factory.assistant_messages import SendAssistantMessage
from agent_factory.applications import GovernedStorage
from agent_factory.store import digest, now
from .session_setup import rejected


class SessionQuestion(SendAssistantMessage):
    assistantId: ObjectId


class ResearchConversations:
    def __init__(self, store, auth, assistants, sessions):
        self.store, self.auth, self.assistants, self.sessions = store, auth, assistants, sessions
        self.messages = assistants.messages
        self.db = GovernedStorage(store, 'research_conversations_v1')
        metadata = MetaData()
        self.origins = Table('research_question_origins', metadata,
            Column('owner_id', String, primary_key=True), Column('request_id', String, primary_key=True),
            Column('session_id', String, nullable=False), Column('assistant_id', String, nullable=False),
            Column('fingerprint', String, nullable=False), Column('created_at', String, nullable=False))
        metadata.create_all(store.engine)

    def _reserve(self, owner, session_id, body):
        self.auth.require_member(owner)
        fingerprint = digest({'sessionId': session_id, 'assistantId': body.assistantId, 'text': body.text})
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                self.store.local_budget_scopes.admission_lock(conn)
            self.sessions._row(conn, owner, session_id)
            old = conn.execute(select(self.origins).where(self.origins.c.owner_id == owner,
                self.origins.c.request_id == body.requestId)).mappings().first()
            if old is not None and old['fingerprint'] != fingerprint:
                raise rejected('RESEARCH_QUESTION_REQUEST_CONFLICT', '此请求已经关联其他问题，请核对原问题。')
            endpoint, _ = self.assistants.question_target(owner, body.assistantId, body)
            message, fresh = self.messages.reserve(owner, endpoint, body)
            if old is None:
                if not fresh:
                    raise rejected('RESEARCH_QUESTION_REQUEST_CONFLICT', '此请求已用于独立问答，不能改绑研究会话。')
                conn.execute(self.origins.insert().values(owner_id=owner, request_id=body.requestId,
                    session_id=session_id, assistant_id=body.assistantId, fingerprint=fingerprint, created_at=now()))
            return message, fresh

    def _item(self, owner, origin):
        message = self.messages.request(owner, origin['request_id'])
        collaboration = {'origin': 'manual'}
        if self.sessions.collaboration is not None:
            with self.db.read() as conn:
                collaboration = self.sessions.collaboration.projection(conn, owner, origin['request_id'])
        return {**self.assistants.read_question(owner, message['id']), 'sessionId': origin['session_id'],
            'requestId': origin['request_id'], 'assistantId': origin['assistant_id'], **collaboration}

    async def question(self, owner, session_id, body):
        try:
            message, fresh = await asyncio.to_thread(self._reserve, owner, session_id, body)
        except HTTPException as error:
            reasons = {
                'RESEARCH_ASSISTANT_UNCONFIGURED': '对方尚未配置助手问答，问题未发送，草稿已保留。',
                'LOCAL_BUDGET_EXHAUSTED': '对方助手的问答预算已用完，问题未发送，草稿已保留。',
                'LOCAL_BUDGET_CLOSED_OR_EXPIRED': '对方助手的问答预算已关闭或过期，问题未发送，草稿已保留。',
                'ASSISTANT_ENDPOINT_DISABLED': '对方助手的原问答配置已停用，问题未发送，草稿已保留。',
                'RESEARCH_QUESTION_REQUEST_CONFLICT': '此请求已绑定其他问题，请核对原问题。',
            }
            if isinstance(error.detail, str) and error.detail in reasons:
                raise rejected(error.detail, reasons[error.detail], error.status_code) from error
            raise
        try:
            if fresh:
                await self.messages.recover(message['recipient_id'], message['id'])
            return self.listing(owner, session_id, request_id=body.requestId)['items'][0]
        except HTTPException as error:
            raise rejected('RESEARCH_QUESTION_ADMISSION_UNCONFIRMED',
                '问题已保存，尚未确认接收方执行，请核对原问题。') from error

    def listing(self, owner, session_id, *, request_id=None, after='', limit=50):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            self.sessions._row(conn, owner, session_id)
            query = select(self.origins).where(self.origins.c.owner_id == owner,
                self.origins.c.session_id == session_id)
            if request_id is not None:
                query = query.where(self.origins.c.request_id == request_id)
            else:
                query = query.where(self.origins.c.request_id > after)
            rows = conn.execute(query.order_by(self.origins.c.request_id).limit(limit + 1)).mappings().all()
            if request_id is not None and not rows:
                raise rejected('RESEARCH_QUESTION_NOT_FOUND', '未找到本会话的原问题。', 404)
            return {'items': [self._item(owner, row) for row in rows[:limit]],
                'nextCursor': rows[limit - 1]['request_id'] if len(rows) > limit else None}

    def inbox(self, owner, *, after='', limit=50):
        self.auth.require_member(owner)
        assistants = self.assistants
        with self.db.read() as conn:
            endpoints = list(conn.execute(select(assistants.configurations.c.endpoint_id)
                .join(assistants.identities, assistants.identities.c.id == assistants.configurations.c.assistant_id)
                .where(assistants.identities.c.owner_id == owner)).scalars())
        page = self.messages.received(owner, endpoint_ids=endpoints, after=after, limit=limit)
        return {**page, 'items': [{**message, **self.messages.recovery_actions(owner, message['id'])}
                                for message in page['items']]}

    async def recover(self, owner, identifier):
        original = self.assistants.read_question(owner, identifier)
        if original['recipientId'] != owner:
            raise HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        if original['recoveryCode'] == 'ASSISTANT_EVENT_RECOVERY_MANAGED':
            raise rejected('ASSISTANT_EVENT_RECOVERY_MANAGED', '此消息由原通知投递处理，请核对原投递状态。')
        await self.messages.recover(owner, identifier)
        return self.assistants.read_question(owner, identifier)

    def adopt(self, owner, session_id, question_id):
        self.auth.require_member(owner)
        commands = self.messages.commands
        with self.db.read() as conn:
            self.sessions._row(conn, owner, session_id)
            origin = conn.execute(select(self.origins).join(commands,
                (commands.c.actor_id == self.origins.c.owner_id)
                & (commands.c.request_id == self.origins.c.request_id)).where(
                    self.origins.c.owner_id == owner, self.origins.c.session_id == session_id,
                    commands.c.result['id'].as_string() == question_id)).mappings().first()
            if origin is None:
                raise rejected('RESEARCH_QUESTION_NOT_FOUND', '只能采用本会话发出问题的回复。', 404)
            message = self.messages.read(owner, question_id)
            if message['reply'] is None or message['reply']['state'] != 'available':
                raise rejected('RESEARCH_ASSISTANT_REPLY_UNAVAILABLE', '此问题尚无可用回复，或来源已不可用。')
            return {'questionId': question_id, 'state': 'available', 'questionText': message['text'],
                **{key: deepcopy(message[key]) for key in
                   ('senderId', 'recipientId', 'endpointId', 'reply', 'delivery')}}

    def validate_reply(self, owner, session_id, snapshot):
        current = self.adopt(owner, session_id, snapshot['questionId'])
        if (any(current[key] != snapshot[key] for key in
                ('questionText', 'senderId', 'recipientId', 'endpointId', 'reply'))
                or current['delivery']['taskId'] != snapshot['delivery']['taskId']):
            raise rejected('RESEARCH_ASSISTANT_REPLY_UNAVAILABLE', '原回复绑定已不一致，请核对原问题。')


def conversations_router(auth, service):
    router = APIRouter(prefix='/api/factory/research')

    @router.post('/sessions/{identifier}/questions', status_code=202)
    async def question(identifier: str, request: Request, body: SessionQuestion):
        return await service.question(auth.user(request)['id'], identifier, body)

    @router.get('/sessions/{identifier}/questions')
    def listing(identifier: str, request: Request, requestId: str | None = Query(default=None, max_length=200),
                after: str = Query(default='', max_length=200), limit: int = Query(default=50, ge=1, le=50)):
        return service.listing(auth.user(request)['id'], identifier, request_id=requestId, after=after, limit=limit)

    @router.get('/assistant-inbox')
    def inbox(request: Request, after: str = Query(default='', max_length=200),
              limit: int = Query(default=50, ge=1, le=50)):
        return service.inbox(auth.user(request)['id'], after=after, limit=limit)

    @router.post('/assistant-questions/{identifier}/recover', status_code=202)
    async def recover(identifier: str, request: Request):
        return await service.recover(auth.user(request)['id'], identifier)

    return router

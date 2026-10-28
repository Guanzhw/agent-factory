"""Persist only original QA inputs; core owns replies and current source authority."""
import json
import re
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.applications import GovernedStorage


class ResearchQA:
    def __init__(self, store, assistants, messages, runs, content, *, associations=None):
        self.assistants, self.messages, self.runs, self.content = assistants, messages, runs, content
        self.associations = associations
        self.db = GovernedStorage(store, 'research_qa_v1')
        metadata = MetaData()
        self.inputs = Table('research_qa_inputs', metadata,
            Column('task_id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('run_id', String, nullable=False), Column('message_id', String, nullable=False),
            Column('configuration', JSON, nullable=False), Column('content_ids', JSON, nullable=False))
        metadata.create_all(store.engine)

    @contextmanager
    def _write(self):
        if self.associations is None:
            with self.db.write() as conn:
                yield conn
        else:
            with self.associations.sources.guard(), self.db.write() as conn:
                yield conn

    def _original(self, ctx):
        owner, task = ctx.user_id, ctx.session_id
        request = ctx.session_state['factory_envelope']['request_id']
        receipt = self.runs.request(owner, request.removeprefix('application-start:'))
        if receipt['taskId'] != task or receipt['runId'] != ctx.run_id:
            raise HTTPException(409, 'RESEARCH_QA_ORIGINAL_RUN_REQUIRED')
        message = self.messages.message_for_task(owner, task)
        if message is None:
            raise HTTPException(409, 'RESEARCH_QA_ORIGINAL_MESSAGE_REQUIRED')
        config = self.assistants.configuration_for_endpoint(owner, message['endpointId'])
        return message, config

    def _source(self, message, identifier):
        read = self.content.read
        source = read(message['senderId'], identifier)
        read(message['recipientId'], identifier)
        if source['visibility'] != 'team' or source['source']['application'] != 'research':
            raise HTTPException(403, 'RESEARCH_QA_TEAM_SOURCE_REQUIRED')
        return {key: source[key] for key in ('id', 'source', 'content', 'verificationStatus')}

    def _select(self, message):
        tokens = set(re.findall(r'[\w]+', message['text'].casefold()))
        ranked = []
        for item in self.content.list(message['recipientId'], limit=50)['items']:
            if item['visibility'] != 'team' or item['source']['application'] != 'research':
                continue
            try:
                source = self._source(message, item['id'])
            except HTTPException as error:
                if error.status_code not in {403, 404}:
                    raise
                continue
            text = json.dumps(source['content'], ensure_ascii=False).casefold()
            score = sum(token in text for token in tokens)
            if score:
                ranked.append((-score, source['id'], source))
        selected, size = [], 0
        for _, _, source in sorted(ranked):
            length = len(json.dumps(source, ensure_ascii=False).encode())
            if size + length > 16384:
                continue
            selected.append(source)
            size += length
            if len(selected) == 8:
                break
        return selected

    def context(self, ctx):
        with self._write() as conn:
            message, config = self._original(ctx)
            if self.associations is not None:
                delivery = self.associations.events.delivery_for_task(ctx.user_id, ctx.session_id)
                if delivery is not None:
                    return self.associations.context(ctx, message, delivery)
            saved = self.messages.read(ctx.user_id, message['messageId'])['reply']
            row = conn.execute(select(self.inputs).where(self.inputs.c.task_id == ctx.session_id)).mappings().first()
            if saved is not None:
                if row is None:
                    raise HTTPException(409, 'RESEARCH_QA_ORIGINAL_INPUT_REQUIRED')
                self._match(row, ctx, message, config)
                for identifier in row['content_ids']:
                    self._source(message, identifier)
                if saved['state'] != 'available':
                    raise HTTPException(403, 'RESEARCH_QA_REPLY_SOURCE_UNAVAILABLE')
                return {'savedReply': self.messages.reply_for_task(ctx.user_id, ctx.session_id,
                    saved['text'], content_ids=row['content_ids'])}
            if row is None:
                sources = self._select(message)
                conn.execute(self.inputs.insert().values(task_id=ctx.session_id, owner_id=ctx.user_id,
                    run_id=ctx.run_id, message_id=message['messageId'], configuration=config,
                    content_ids=[source['id'] for source in sources]))
            else:
                self._match(row, ctx, message, config)
                sources = [self._source(message, identifier) for identifier in row['content_ids']]
            return {'question': message['text'], 'sources': sources,
                'search': {'candidateLimit': 50, 'sourceLimit': 8, 'byteLimit': 16384,
                           'insufficientEvidence': not sources}}

    @staticmethod
    def _match(row, ctx, message, config):
        if (row['owner_id'] != ctx.user_id or row['run_id'] != ctx.run_id
                or row['message_id'] != message['messageId'] or row['configuration'] != config):
            raise HTTPException(409, 'RESEARCH_QA_ORIGINAL_INPUT_REQUIRED')

    def record(self, ctx, answer):
        with self._write() as conn:
            message, config = self._original(ctx)
            if self.associations is not None:
                delivery = self.associations.events.delivery_for_task(ctx.user_id, ctx.session_id)
                if delivery is not None:
                    return self.associations.record(ctx, delivery, answer)
            row = conn.execute(select(self.inputs).where(self.inputs.c.task_id == ctx.session_id)).mappings().first()
            if row is None:
                raise HTTPException(409, 'RESEARCH_QA_ORIGINAL_INPUT_REQUIRED')
            self._match(row, ctx, message, config)
            dependencies = list(row['content_ids'])
        if not set(answer.citations) <= set(dependencies):
            raise HTTPException(422, 'RESEARCH_QA_UNKNOWN_CITATION')
        return self.messages.reply_for_task(ctx.user_id, ctx.session_id, answer.answer, content_ids=dependencies)

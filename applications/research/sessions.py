"""Private research conversations over existing, independently bounded tasks."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

from agno.exceptions import ModelProviderError, RunCancelledException, StopAgentRun
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.utils.tokens import count_tokens
from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, UniqueConstraint, select

from agent_factory.application_interface import ApplicationStart
from agent_factory.application_runs import StartNotSubmitted, factory_request_id
from agent_factory.applications import GovernedStorage
from agent_factory.control_commands import ControlCommand
from agent_factory.runtime_hooks import effect_unresolved, runtime_custody_held
from agent_factory.store import digest, now
from agent_factory.task_status import native_status
from .assistants import CreateAssistant
from .session_setup import INSTRUCTIONS, MODE, ResearchSessionSetup, rejected
from .session_memory import ResearchSessionMemory
from .session_tools import EFFECT_PREFIX
from . import session_context
from .session_subagents import ResearchSubagents


class ResearchSessions:
    def __init__(self, store, auth, assistants, runs, *, connections, models, content, tools):
        self.store, self.auth, self.assistants, self.runs = store, auth, assistants, runs
        self.content, self.tools = content, tools
        self.conversations: Any = None
        self.collaboration: Any = None
        self.projects: Any = None
        self.research: Any = None
        self.memory = ResearchSessionMemory(self)
        self.subagents = ResearchSubagents(self)
        self.setup = ResearchSessionSetup(store, connections, models, tools)
        self.db = GovernedStorage(store, 'research_sessions_v1')
        metadata = MetaData()
        self.sessions = Table('research_sessions', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('assistant_id', String, nullable=False), Column('body', JSON, nullable=False))
        self.turns = Table('research_session_turns', metadata,
            Column('id', String, primary_key=True), Column('session_id', String, nullable=False),
            Column('owner_id', String, nullable=False), Column('sequence', Integer, nullable=False),
            Column('application_request_id', String, unique=True, nullable=False), Column('body', JSON, nullable=False),
            UniqueConstraint('session_id', 'sequence'))
        self.commands = self.db.command_table('research_session_commands', metadata)
        metadata.create_all(store.engine)
        store.research_instructions = [INSTRUCTIONS]
        store.research_sessions = self
        store.research_tools = tools

    @contextmanager
    def _write(self):
        with self.store.transaction() as conn:
            with self.db.write():
                yield conn

    def options(self, owner):
        self.auth.require_member(owner)
        return self.setup.options(owner)

    def _row(self, conn, owner, identifier):
        row = conn.execute(select(self.sessions).where(self.sessions.c.id == identifier,
            self.sessions.c.owner_id == owner)).mappings().first()
        if row is None:
            raise rejected('RESEARCH_SESSION_NOT_FOUND', '未找到研究会话。', 404)
        return row

    def _turns(self, conn, identifier):
        return list(conn.execute(select(self.turns).where(self.turns.c.session_id == identifier)
                                 .order_by(self.turns.c.sequence)).mappings())

    def _save_session(self, conn, row, body):
        body = {**body, 'updatedAt': now()}
        conn.execute(self.sessions.update().where(self.sessions.c.id == row['id']).values(body=body))

    def _save_turn(self, conn, row, body):
        conn.execute(self.turns.update().where(self.turns.c.id == row['id']).values(body=body))

    def _command(self, conn, owner, request_id, fingerprint, action, session_id, turn_id=None):
        return self.db.record(conn, self.commands, owner, request_id, fingerprint, action,
            {'sessionId': session_id, 'turnId': turn_id, 'action': action})

    @staticmethod
    def _message(kind, text):
        return {'id': str(uuid4()), 'kind': kind, 'text': text, 'state': 'pending',
                'createdAt': now(), 'includedAt': None}

    def native_session_for_plan(self, plan):
        inputs = plan.get('inputValues') or {}
        if plan.get('mode') != MODE or plan.get('delegation') or not inputs.get('turnId'):
            return None
        owner = plan['ownerId']
        with self.db.read() as conn:
            row = self._row(conn, owner, inputs.get('sessionId'))
            turn = conn.execute(select(self.turns).where(self.turns.c.id == inputs['turnId'],
                self.turns.c.session_id == row['id'], self.turns.c.owner_id == owner)).mappings().one()
            if turn['body']['startFingerprint'] != digest(self._start(row, turn).model_dump(
                    exclude={'interfaceVersion', 'requestId'})):
                raise PermissionError('RESEARCH_SESSION_ADMISSION_PAYLOAD_MISMATCH')
        return row['id']

    def prepare_history(self, context, session):
        with self.db.read() as conn:
            row, current, task = self._execution(conn, context)
            if task['researchChild']:
                return
            turns = session_context.active_turns(row, self._turns(conn, row['id']))
            saved = session_context.checkpoint(row)
            through = saved['throughSequence'] if saved else 0
        native_runs = {run.run_id: run for run in session.runs or []}
        history = []
        for turn in turns:
            if turn['sequence'] <= through or turn['sequence'] >= current['sequence']:
                continue
            run_id = turn['body'].get('runId')
            native = native_runs.get(run_id)
            if native is None and run_id:
                native = self.runs.factory.bridge.native_db.get_run(run_id)
                if native is not None:
                    prior_task = self._task(context.user_id, turn)
                    if (prior_task is None or native.user_id != context.user_id
                            or native.session_id != self.store.native_session_id(prior_task)):
                        raise PermissionError('RESEARCH_HISTORY_OWNER_MISMATCH')
            history.append(session_context.history_run(turn, native))
        session_context.history_view(session, history, saved)

    def _sources(self, owner, identifiers):
        for identifier in identifiers:
            try:
                self.content.read(owner, identifier)
            except HTTPException as error:
                if error.status_code not in {403, 404}:
                    raise
                raise rejected('RESEARCH_SOURCE_UNAVAILABLE', '本轮使用的共享来源已不可读，本轮已停止；可以发送新消息继续。') from None

    def _reply(self, owner, identifier, snapshot):
        try:
            self.conversations.validate_reply(owner, identifier, snapshot)
        except HTTPException as error:
            if error.status_code >= 500:
                raise
            raise rejected('RESEARCH_ASSISTANT_REPLY_UNAVAILABLE',
                '本轮使用的助手回答已不可用，本轮已停止；可以发送新消息继续。') from None

    def _replies(self, owner, identifier, turns):
        for turn in turns:
            if 'assistantReply' in turn['body']:
                self._reply(owner, identifier, turn['body']['assistantReply'])
            for snapshot in turn['body'].get('assistantReplies', []):
                self._reply(owner, identifier, snapshot)

    def _context_sources(self, owner, row, turns):
        self._sources(owner, row['body']['sharedSourceIds'])
        self._replies(owner, row['id'], session_context.active_turns(row, turns))

    def _continuation_context(self, row, turns):
        try:
            self._context_sources(row['owner_id'], row, turns)
        except HTTPException as error:
            if not isinstance(error.detail, dict) or error.detail.get('code') not in {
                    'RESEARCH_SOURCE_UNAVAILABLE', 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE'}:
                raise
            # Derived replies and summaries have no finer source attribution.
            body = {**row['body'], 'sharedSourceIds': [],
                    'contextAfterSequence': turns[-1]['sequence'] if turns else 0,
                    'contextNotice': '旧共享来源或助手回答已不可用。后续对话从新的上下文继续，原聊天记录仍保留。'}
            body.pop('contextCheckpoint', None)
            return {**row, 'body': body}
        return row

    def _reply_projection(self, owner, identifier, snapshot):
        try:
            self._reply(owner, identifier, snapshot)
        except HTTPException:
            return {'state': 'unavailable', 'questionId': snapshot['questionId'],
                    'code': 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE'}
        return {'state': 'available', **deepcopy(snapshot)}

    def create(self, owner, request):
        self.auth.require_member(owner)
        value = request.model_dump(exclude={'requestId'}, exclude_none=True)
        if value.get('projectId') is None:
            value.pop('projectId', None)
        fingerprint = digest({'action': 'create', **value})
        with self._write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old is not None:
                return old['sessionId']
            configuration = self.setup.prepare(owner, value['modelConnectionRef'], value.get('reasoningEffort'))
            assistant = self.assistants.create(owner, CreateAssistant(
                requestId='session-identity:' + digest({'owner': owner, 'request': request.requestId})[:32]))
            identifier, stamp = str(uuid4()), now()
            body = {key: value[key] for key in ('title', 'goal', 'boundaries')}
            if value.get('projectId') is not None:
                if self.projects is None:
                    raise rejected('RESEARCH_PROJECTS_UNAVAILABLE', 'Research projects are unavailable.')
                project = self.projects.read(owner, value['projectId'])
                if project['state'] == 'ended' or project.get('sourceUnavailable'):
                    raise rejected('RESEARCH_PROJECT_UNAVAILABLE', '所选项目已结束或来源不可用。')
                body.update(projectId=project['id'], projectGoalVersion=project['currentGoalVersion'])
            body.update(configuration=configuration, createdAt=stamp, updatedAt=stamp,
                        stopped=False, stopRequestId=None, sharedSourceIds=[])
            conn.execute(self.sessions.insert().values(id=identifier, owner_id=owner, assistant_id=assistant['id'], body=body))
            self._command(conn, owner, request.requestId, fingerprint, 'create', identifier)
            return identifier

    def _task(self, owner, turn):
        try:
            return self.store.task_for_request(factory_request_id(turn['application_request_id']), owner)
        except HTTPException as error:
            if error.status_code == 404:
                return None
            raise

    def _not_submitted(self, owner, turn, error):
        if not isinstance(error, StartNotSubmitted):
            return False
        try:
            return self._task(owner, turn) is None
        except Exception:
            return False  # An unreadable original request is not proof of absence.

    async def _refresh(self, owner, identifier):
        observations = {}
        with self.db.read() as conn:
            self._row(conn, owner, identifier)
            turns = self._turns(conn, identifier)
        for turn in turns:
            if turn['body'].get('terminal'):
                continue
            task = await asyncio.to_thread(self._task, owner, turn)
            if task is None:
                continue
            await asyncio.to_thread(self.memory.observe, owner, turn, task, EFFECT_PREFIX)
            try:
                detail = await self.runs.factory.detail(task)
            except HTTPException:
                # A failed observation is not a failed task or a dispatch grant.
                continue
            task = self.store.task(task['id'], owner)
            children = await self.subagents.children(task)
            if self.research is not None:
                await self.research.observe(task)
            status, snapshot = detail['job']['status'], detail['snapshot']
            observations[turn['id']] = {'events': detail['events'], 'toolResults': [
                {'effectKey': item['effect_key'], 'status': item['status'], 'result': item['result']}
                for item in snapshot.get('effects', [])]}
            run = snapshot.get('run', snapshot)
            result = None
            ticket = snapshot.get('queue') or {}
            native_ended = (ticket.get('id') == task['run_id'] and ticket.get('session_id') == self.store.native_session_id(task)
                and ticket.get('user_id') == owner and ticket.get('status') in {'completed', 'failed', 'cancelled'}
                and run.get('run_id') == task['run_id'] and run.get('session_id') == self.store.native_session_id(task)
                and run.get('user_id') == owner
                and str(run.get('status', '')).lower() in {'completed', 'error', 'cancelled'})
            with self._write() as conn:
                current = conn.execute(select(self.turns).where(self.turns.c.id == turn['id'])).mappings().one()
                if current['body'].get('terminal'):
                    continue  # A concurrent confirmed final result wins over this older observation.
                body = deepcopy(current['body'])
                observed_terminal = bool(task['terminal'] and status in {'completed', 'failed', 'canceled'})
                if native_ended and not body.get('stopRequestId') and all(
                        child['status'] in {'completed', 'failed', 'cancelled', 'canceled'} for child in children):
                    # Ending the native turn does not resolve or replay its unknown operations.
                    observed_terminal = True
                    status = {'error': 'failed', 'cancelled': 'canceled', 'canceled': 'canceled'}.get(
                        native_status(ticket['status'], run.get('status')), ticket['status'])
                # Ticket fallbacks may contain error text. Only exact persisted run
                # messages accompanying an actually completed task are an answer.
                if (status == 'completed' and observed_terminal and run.get('run_id') == task['run_id']
                        and run.get('session_id') == self.store.native_session_id(task) and run.get('user_id') == owner
                        and str(run.get('status', '')).lower() == 'completed'
                        and isinstance(run.get('messages'), list)):
                    # Agno run.content also contains intermediate messages before tool calls.
                    answer = next((item for item in reversed(run['messages'])
                        if isinstance(item, dict) and item.get('role') == 'assistant'), None)
                    if answer is not None and not answer.get('tool_calls') and isinstance(answer.get('content'), str):
                        result = answer['content']
                if native_ended and observed_terminal and not body.get('stopRequestId'):
                    if body.get('blockReason') == 'RESEARCH_RESTART_REQUIRES_RECONCILIATION':
                        status, result = 'failed', None
                        body['failure'] = '原任务自动重试已停止，以免重复执行结果未知的操作。可以开始独立的新一轮。'
                        body['blockReason'] = None
                    elif body.get('blockReason') == 'RESEARCH_EFFECT_UNCONFIRMED':
                        body['blockReason'] = None
                if observed_terminal and body.get('contextFailure') and not body.get('stopRequestId'):
                    status, result = 'failed', None
                compaction = body.get('compaction')
                if observed_terminal and compaction and compaction['status'] == 'started':
                    body['compaction'].update(status='unknown', code='RESEARCH_SUMMARY_UNKNOWN')
                if status == 'completed' and result is None:
                    # Terminal metadata cannot upgrade an unconfirmed native answer.
                    observed_terminal, status = False, 'finalizing'
                body.update(taskId=task['id'], runId=task.get('run_id'), status=status,
                            terminal=observed_terminal, children=children)
                if observed_terminal:
                    body.update(observations[turn['id']])
                    body['completedAt'] = body.get('completedAt') or now()
                    body['result'] = result
                    if status == 'completed':
                        body['failure'] = None
                    elif status == 'failed' and not body.get('contextFailure'):
                        native_error = None
                        if native_status(None, run.get('status')) == 'error':
                            native_error = next((event.get('error') for event in reversed(run.get('events') or [])
                                if event.get('event') == 'RunError'), None) or run.get('content')
                        error = (snapshot.get('queue') or {}).get('error') or snapshot.get('error') or native_error
                        if isinstance(error, str) and error.startswith('PERSONAL_MODEL_HTTP_'):
                            status_code = error.removeprefix('PERSONAL_MODEL_HTTP_')
                            body['failure'] = f'模型服务返回 HTTP {status_code}，本轮未完成。请检查模型服务或设置中的连接。'
                        else:
                            body['failure'] = str(error or body.get('failure') or '本轮执行失败，请查看工具记录。')
                if current['body'] != body:
                    self._save_turn(conn, current, body)

        return observations

    def _safe(self, owner, turn):
        body = turn['body']
        if body.get('blockReason') not in {None, 'RESEARCH_EFFECT_UNCONFIRMED'} or not body['terminal']:
            return False
        task = self._task(owner, turn)
        if task is None:
            return bool(body.get('neverDispatched') and body['terminal'])
        if task['admission'] == 'rejected' and not task.get('run_id') and task['body'].get('neverSubmitted'):
            return bool(task['terminal'])
        if body.get('stopRequestId'):
            return bool(task['terminal'] and not runtime_custody_held(self.store, task['id'])
                and not any(effect_unresolved(item, self.store) for item in self.store.effects(task['id'])))
        ticket = self.runs.factory.bridge.native_db.get_job(task['run_id'], strict=True)
        # Agno expires terminal queue tickets; the persisted terminal turn survives cleanup.
        return bool((ticket is None or (ticket.get('id') == task['run_id']
            and ticket.get('session_id') == self.store.native_session_id(task)
            and ticket.get('user_id') == owner and ticket.get('status') in {'completed', 'failed', 'cancelled'}))
            and all(child['status'] in {'completed', 'failed', 'cancelled', 'canceled'}
                    for child in body.get('children', [])))

    @staticmethod
    def _start(row, turn):
        configuration = turn['body'].get('configuration', row['body']['configuration'])
        messages = turn['body']['messages']
        return ApplicationStart(requestId=turn['application_request_id'],
            mode=MODE, goal=messages[0]['text'] if messages else row['body']['goal'],
            connectionRefs=configuration['connectionRefs'],
            inputValues={'sessionId': row['id'], 'turnId': turn['id'],
                **({'sessionContext': turn['body']['context']} if 'context' in turn['body'] else
                   {key: row['body'][key] for key in ('goal', 'boundaries', 'projectId', 'projectGoalVersion') if key in row['body']}),
                **({'reasoningEffort': configuration['model']['reasoningEffort']}
                   if 'reasoningEffort' in configuration['model'] else {})})

    def _prepare_turn_configuration(self, conn, owner, row, turns, request=None):
        previous = row['body']['configuration']
        model_ref = (request.modelConnectionRef if request is not None else None) or previous['connectionRefs']['model']
        effort = request.reasoningEffort if request is not None and 'reasoningEffort' in request.model_fields_set else (
            previous['model'].get('reasoningEffort') if model_ref == previous['connectionRefs']['model'] else None)
        configuration = self.setup.prepare(owner, model_ref, effort)
        # Pin each original turn before refreshing the session's selected tools.
        # Native plans and request identities remain unchanged for recovery.
        for prior in turns:
            if 'configuration' not in prior['body']:
                self._save_turn(conn, prior, {**prior['body'], 'configuration': deepcopy(previous)})
        row = {**row, 'body': {**row['body'], 'configuration': configuration}}
        return row

    def _reserve(self, owner, identifier, request):
        question_id = request.model_dump().get('assistantQuestionId')
        fingerprint = digest({'action': 'turn', 'sessionId': identifier, 'text': request.text,
            **({'assistantQuestionId': question_id} if question_id is not None else {}),
            **{key: getattr(request, key) for key in ('modelConnectionRef', 'reasoningEffort') if key in request.model_fields_set}})
        with self._write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old is not None:
                return old['turnId'], False
            row, turns = self._row(conn, owner, identifier), self._turns(conn, identifier)
            if turns and not self._safe(owner, turns[-1]):
                raise rejected('RESEARCH_TURN_ACTIVE_OR_UNCONFIRMED', '原轮次尚未安全结束，请先核对其状态。')
            row = self._continuation_context(row, turns)
            row = self._prepare_turn_configuration(conn, owner, row, turns, request)
            configuration = row['body']['configuration']
            turn_id, stamp = str(uuid4()), now()
            body = {'requestId': request.requestId, 'configuration': deepcopy(configuration),
                'taskId': None, 'runId': None, 'status': 'reserved',
                'createdAt': stamp, 'completedAt': None, 'result': None, 'failure': None, 'terminal': False,
                'blockReason': None, 'messages': [self._message('instruction', request.text)],
                'lastAttempt': 0, 'dispatchStarted': False, 'events': [], 'toolResults': [], 'sharedSourceIds': []}
            if question_id is not None:
                body['assistantReply'] = self.conversations.adopt(owner, identifier, question_id)
            start = self._start(row, {'id': turn_id, 'application_request_id': 'research-turn:' + turn_id, 'body': body})
            body['startFingerprint'] = digest(start.model_dump(exclude={'interfaceVersion', 'requestId'}))
            conn.execute(self.turns.insert().values(id=turn_id, session_id=identifier, owner_id=owner,
                sequence=len(turns) + 1, application_request_id='research-turn:' + turn_id, body=body))
            self._save_session(conn, row, {**row['body'], 'stopped': False, 'stopRequestId': None})
            self._command(conn, owner, request.requestId, fingerprint, 'turn', identifier, turn_id)
            return turn_id, True

    async def turn(self, owner, identifier, request):
        self.auth.require_member(owner)
        await self._refresh(owner, identifier)
        turn_id, fresh = await asyncio.to_thread(self._reserve, owner, identifier, request)
        if fresh:
            with self._write() as conn:
                row = self._row(conn, owner, identifier)
                turn = conn.execute(select(self.turns).where(self.turns.c.id == turn_id)).mappings().one()
                if (row['body']['stopped'] or turn['body'].get('stopRequestId')
                        or self._turns(conn, identifier)[-1]['id'] != turn_id):
                    self._save_turn(conn, turn, {**turn['body'], 'status': 'canceled', 'terminal': True,
                        'completedAt': now(), 'neverDispatched': True})
                    start = None
                else:
                    start = self._start(row, turn)
                    self._save_turn(conn, turn, {**turn['body'], 'dispatchStarted': True})
            if start is not None:
                try:
                    await self.runs.start(owner, start)
                except Exception as error:
                    never_submitted = self._not_submitted(owner, turn, error)
                    with self._write() as conn:
                        current = conn.execute(select(self.turns).where(self.turns.c.id == turn_id)).mappings().one()
                        if not current['body'].get('terminal'):
                            if never_submitted and isinstance(error, StartNotSubmitted):
                                self._save_turn(conn, current, {**current['body'], 'status': 'failed',
                                    'terminal': True, 'completedAt': now(), 'neverDispatched': True,
                                    'failure': error.message})
                            else:
                                self._save_turn(conn, current, {**current['body'], 'status': 'unknown',
                                    'failure': '尚未确认原提交结果；请读取原请求，勿重复启动。'})
                with self.db.read() as conn:
                    original = conn.execute(select(self.turns).where(self.turns.c.id == turn_id)).mappings().one()
                if original['body'].get('stopRequestId'):
                    await self._cancel_original(owner, identifier, original['body']['stopRequestId'])
        return await self.read(owner, identifier)

    def correct(self, owner, identifier, request):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'correct', 'sessionId': identifier, 'text': request.text})
        with self._write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old is not None:
                return
            row, turns = self._row(conn, owner, identifier), self._turns(conn, identifier)
            if not turns or row['body']['stopped'] or turns[-1]['body'].get('blockReason'):
                raise rejected('RESEARCH_CORRECTION_UNAVAILABLE', '当前没有可接收纠正的研究轮次。')
            turn = turns[-1]
            body = deepcopy(turn['body'])
            body['messages'].append(self._message('correction', request.text))
            self._save_turn(conn, turn, body)
            self._save_session(conn, row, row['body'])
            self._command(conn, owner, request.requestId, fingerprint, 'correct', identifier, turn['id'])

    async def stop(self, owner, identifier, request):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'stop', 'sessionId': identifier})
        with self._write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            row = self._row(conn, owner, identifier)
            if old is None:
                self._save_session(conn, row, {**row['body'], 'stopped': True, 'stopRequestId': request.requestId})
                if self.collaboration is not None:
                    self.collaboration.stop(conn, owner, identifier)
                turns = self._turns(conn, identifier)
                turn_id = turns[-1]['id'] if turns else None
                if turns:
                    turn = turns[-1]
                    body = {**turn['body'], 'stopRequestId': request.requestId}
                    if not body['dispatchStarted']:
                        body.update(status='canceled', terminal=True, completedAt=now(), neverDispatched=True)
                    self._save_turn(conn, turn, body)
                self._command(conn, owner, request.requestId, fingerprint, 'stop', identifier, turn_id)
        if old is None:
            await self._cancel_original(owner, identifier, request.requestId)
        return await self.read(owner, identifier)

    async def _cancel_original(self, owner, identifier, request_id):
        with self.db.read() as conn:
            command = conn.execute(select(self.commands).where(self.commands.c.actor_id == owner,
                self.commands.c.request_id == request_id, self.commands.c.action == 'stop')).mappings().first()
            if command is None or command['result']['sessionId'] != identifier or not command['result']['turnId']:
                return
            turn = conn.execute(select(self.turns).where(self.turns.c.id == command['result']['turnId'],
                self.turns.c.session_id == identifier, self.turns.c.owner_id == owner)).mappings().first()
        if turn is None:
            return
        # The immutable turn/request link resolves an admission that may have
        # completed after stop was received. Never select a later active turn.
        task = await asyncio.to_thread(self._task, owner, turn)
        if task is not None and not task['terminal']:
            await asyncio.to_thread(self.store.request_cancel, task['id'])
            try:
                await self.runs.factory.commands.submit(owner, task['id'], ControlCommand(
                    commandId='research-stop:' + digest({'session': identifier, 'request': request_id})[:32], action='cancel'))
            except HTTPException:
                pass  # Persisted cancellation remains pending; never claim stopped.

    def _execution(self, conn, context):
        task = self.store.task_for_context(context)
        if task['run_id'] != context.run_id:
            raise PermissionError('RESEARCH_SESSION_RUN_MISMATCH')
        plan = self.store.plan(task['plan_id'], context.user_id)
        original_task = self.subagents.root_task(context.user_id, task, plan)
        turn = conn.execute(select(self.turns).where(self.turns.c.owner_id == context.user_id,
            self.turns.c.application_request_id == original_task['request_id'].removeprefix('application-start:'))).mappings().first()
        if turn is None or original_task['request_id'] != factory_request_id(turn['application_request_id']):
            raise PermissionError('RESEARCH_SESSION_ORIGINAL_TURN_REQUIRED')
        row = self._row(conn, context.user_id, turn['session_id'])
        expected = turn['body'].get('configuration', row['body']['configuration'])
        if plan.get('connectionRefs', {}).get('model') != expected['connectionRefs']['model'] or plan.get('mode') != MODE:
            raise PermissionError('RESEARCH_SESSION_PLAN_MISMATCH')
        if ((plan.get('inputValues') or {}).get('turnId') != turn['id']
                or (plan.get('inputValues') or {}).get('sessionId') != row['id']):
            raise PermissionError('RESEARCH_SESSION_INPUT_MISMATCH')
        original = self.store.sql('SELECT fingerprint FROM af_plan_requests WHERE owner_id=:owner '
            'AND request_id=:request AND plan_id=:plan', owner=context.user_id,
            request=original_task['request_id'], plan=original_task['plan_id'])
        if len(original) != 1 or original[0]['fingerprint'] != turn['body']['startFingerprint']:
            raise PermissionError('RESEARCH_SESSION_ADMISSION_PAYLOAD_MISMATCH')
        latest = self._turns(conn, row['id'])[-1]
        if (latest['id'] != turn['id'] or row['body']['stopped']
                or task['cancel_requested'] or original_task['cancel_requested']):
            raise RunCancelledException('RESEARCH_SESSION_STOP_REQUESTED')
        if turn['body'].get('blockReason'):
            raise StopAgentRun(turn['body']['blockReason'])
        if task['id'] != original_task['id']:
            self.store.delegation.authorize_child(context)
        return row, turn, {**task, 'researchChild': task['id'] != original_task['id']}

    def authorize_tool(self, context, tool_name):
        self.auth.require_member(context.user_id)
        with self.db.read() as conn:
            row, turn, _ = self._execution(conn, context)
            self._context_sources(context.user_id, row, self._turns(conn, row['id']))
            self.store.authorize_tool(context, tool_name)
            return {'id': row['id'], 'ownerId': row['owner_id'], 'turnId': turn['id'],
                    'workspaceRef': row['id']}

    def record_source(self, context, identifier):
        with self._write() as conn:
            row, turn, _ = self._execution(conn, context)
            self._sources(context.user_id, [identifier])
            body = deepcopy(row['body'])
            if identifier not in body['sharedSourceIds']:
                body['sharedSourceIds'].append(identifier)
            turn_body = deepcopy(turn['body'])
            if identifier not in turn_body.setdefault('sharedSourceIds', deepcopy(row['body']['sharedSourceIds'])):
                turn_body['sharedSourceIds'].append(identifier)
            self._save_turn(conn, turn, turn_body)
            self._save_session(conn, row, body)

    def _model_boundary(self, conn, context):
        row, turn, task = self._execution(conn, context)
        body = deepcopy(turn['body'])
        ticket = self.runs.factory.bridge.native_db.get_job(context.run_id)
        blocked = None
        if not ticket or ticket.get('session_id') != self.store.native_session_id(task) or ticket.get('user_id') != context.user_id:
            blocked = 'RESEARCH_QUEUE_IDENTITY_UNCONFIRMED'
        elif type(ticket.get('attempt')) is not int or ticket['attempt'] < 1:
            blocked = 'RESEARCH_QUEUE_ATTEMPT_UNCONFIRMED'
        elif (ticket['attempt'] > 1 and (task['researchChild'] or body.get('lastAttempt') != ticket['attempt'])
                and (context.metadata or {}).get('factoryNativeRetryAttempt') != ticket['attempt']
                and (self.store.effects(task['id']) or self.store.sql(
                'SELECT 1 FROM af_delegation_links WHERE owner_id=:owner AND parent_id=:parent LIMIT 1',
                owner=context.user_id, parent=task['id']) or self.store.sql(
                "SELECT 1 FROM af_events started WHERE task_id=:id AND type='tool_started' "
                "AND data->>'toolName'='ssh_run' AND NOT EXISTS (SELECT 1 FROM af_events finished "
                "WHERE finished.task_id=started.task_id AND finished.type='tool_finished' "
                "AND finished.data->>'callId'=started.data->>'callId' "
                "AND finished.data->>'toolName'='ssh_run' AND finished.data->>'outcome'='failed' "
                "AND finished.data->'output'->>'stopped'='true') LIMIT 1", id=task['id']))
                and not self.subagents.permits_continuation(task, ticket)):
            blocked = 'RESEARCH_RESTART_REQUIRES_RECONCILIATION'
        if blocked:
            if task['researchChild']:
                raise StopAgentRun(blocked)
            body['blockReason'] = blocked
            self.store.event(task['id'], 'research_reconciliation_required', '原执行需要核对，已阻止新的模型调用。', {'code': blocked})
            self._save_turn(conn, turn, body)
        else:
            if body.get('blockReason') == 'RESEARCH_EFFECT_UNCONFIRMED':
                body['blockReason'] = None
                self._save_turn(conn, turn, body)
            try:
                self._context_sources(context.user_id, row, self._turns(conn, row['id']))
            except HTTPException as error:
                if isinstance(error.detail, dict) and error.detail.get('code') in {
                        'RESEARCH_SOURCE_UNAVAILABLE', 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE'}:
                    detail = cast(dict, error.detail)
                    self._save_turn(conn, turn, {**turn['body'], 'contextFailure': detail['code'],
                        'failure': detail['message']})
                    blocked = detail['message']
                else:
                    raise
            if not blocked and self.collaboration is not None and not task['researchChild']:
                turn = self.collaboration.receive(conn, row, turn)
        return row, turn, task, ticket, blocked

    def _summary_outcome(self, owner, turn_id, claim, status, code):
        with self._write() as conn:
            turn = conn.execute(select(self.turns).where(self.turns.c.id == turn_id,
                self.turns.c.owner_id == owner)).mappings().one()
            body = deepcopy(turn['body'])
            if body.get('compaction') == claim:
                body['compaction'].update(status=status, code=code)
                self._save_turn(conn, turn, body)

    def _compact(self, context, messages, auxiliary_model):
        history = [item.model_copy(update={'from_history': False}) for item in messages if item.from_history]
        if not history:
            return
        with self._write() as conn:
            row, turn, task, ticket, blocked = self._model_boundary(conn, context)
            if not blocked:
                active = session_context.active_turns(row, self._turns(conn, row['id']))
                correction = next((item['id'] for previous in reversed(active) for item in reversed(previous['body']['messages'])
                                   if item['kind'] == 'correction'), None)
                prior = [item for item in active
                         if item['sequence'] < turn['sequence'] and item['body'].get('terminal')]
                limit = session_context.compact_token_limit(turn['body'].get('configuration', row['body']['configuration'])['model'])
                if (not prior or limit is None or turn['body'].get('compaction', {}).get('status') not in {None, 'pending'}
                        or count_tokens(messages, model_id=row['body']['configuration']['model'].get('model', '')) < limit):
                    return
                claim = {'status': 'started', 'runId': context.run_id, 'attempt': ticket['attempt'],
                         'throughSequence': prior[-1]['sequence'], 'startedAt': now()}
                self._save_turn(conn, turn, {**turn['body'], 'compaction': claim})
                saved = session_context.checkpoint(row)
        if blocked:
            raise StopAgentRun(blocked)
        if saved:
            history.insert(0, Message(role='user', content='Previous conversation summary: ' + saved['summary']['summary']))
        source = AgentSession(session_id=context.session_id, user_id=context.user_id,
            runs=[RunOutput(run_id=context.run_id, status=RunStatus.completed, messages=history)])
        try:
            summary = session_context.summarize(source, auxiliary_model)
            with self._write() as conn:
                row, turn, task, ticket, blocked = self._model_boundary(conn, context)
                if not blocked:
                    if task['terminal'] or ticket['attempt'] != claim['attempt']:
                        raise StopAgentRun('RESEARCH_SUMMARY_RUN_INACTIVE')
                    self._save_session(conn, row, {**row['body'], 'contextCheckpoint': {
                        'throughSequence': claim['throughSequence'], 'projectionVersion': 3, 'summary': summary}})
                    self._save_turn(conn, turn, {**turn['body'], 'compaction': {**claim, 'status': 'ready'}})
            if blocked:
                raise StopAgentRun(blocked)
            messages[:] = [item for item in messages if not item.from_history or item.id == correction]
            messages.insert(1, Message(id='research-summary:' + context.run_id, role='user', from_history=False,
                content='Previous conversation summary: ' + summary['summary']))
        except (ValueError, ModelProviderError):
            self._summary_outcome(context.user_id, turn['id'], claim, 'failed', 'RESEARCH_SUMMARY_MODEL_FAILED')
        except BaseException:
            self._summary_outcome(context.user_id, turn['id'], claim, 'unknown', 'RESEARCH_SUMMARY_UNKNOWN')
            raise

    def authorize_model(self, context):
        with self._write() as conn:
            _, _, _, _, blocked = self._model_boundary(conn, context)
        if blocked:
            raise StopAgentRun(blocked)

    def before_model(self, context, messages, auxiliary_model):
        with self.db.read() as conn:
            _, _, task = self._execution(conn, context)
        if task['researchChild']:
            self.authorize_model(context)
            return
        self._compact(context, messages, auxiliary_model)
        with self._write() as conn:
            row, turn, task, ticket, blocked = self._model_boundary(conn, context)
            if not blocked:
                turns = session_context.active_turns(row, self._turns(conn, row['id']))
                known = {item.id for item in messages}
                # Keep the latest earlier correction before the newer user instruction.
                correction = next((item for previous in reversed(turns[:-1])
                                   for item in reversed(previous['body']['messages']) if item['kind'] == 'correction'), None)
                if correction and correction['id'] not in known:
                    index = next((index for index, item in enumerate(messages)
                                  if item.role != 'system' and not item.from_history), len(messages))
                    messages.insert(index, Message(id=correction['id'], role='user', content=correction['text'], from_history=True))
                    known.add(correction['id'])
                for item in session_context.additions(turn):
                    if item.id not in known:
                        messages.append(item)
                        known.add(item.id)
                for previous in turns:
                    body = deepcopy(previous['body'])
                    for item in body['messages']:
                        if item['kind'] == 'instruction' or item['id'] in known:
                            item['state'], item['includedAt'] = 'included', item['includedAt'] or now()
                    if previous['id'] == turn['id']:
                        body['lastAttempt'] = ticket['attempt']
                    if body != previous['body']:
                        self._save_turn(conn, previous, body)
                if self.collaboration is not None:
                    self.collaboration.included(conn, row, turn)
        if blocked:
            raise StopAgentRun(blocked)

    async def external_result(self, commands, task, requirement, requirements, decision):
        return await self.subagents.external_result(commands, task, requirement, requirements, decision)

    async def observe_waits(self, observer, task):
        root = self.subagents.root_task(task['owner_id'], task, self.store.plan(task['plan_id'], task['owner_id']))
        with self.db.read() as conn:
            turn = conn.execute(select(self.turns).where(self.turns.c.owner_id == task['owner_id'],
                self.turns.c.application_request_id == root['request_id'].removeprefix('application-start:'))).mappings().first()
        if turn is not None and root['request_id'] == factory_request_id(turn['application_request_id']):
            if turn['body'].get('stopRequestId') and not root['cancel_requested']:
                await asyncio.to_thread(self.store.request_cancel, root['id'])
            await asyncio.to_thread(self.memory.observe, task['owner_id'], turn, task, EFFECT_PREFIX)
        await self.subagents.observe_waits(observer, task)
        if self.research is not None:
            await self.research.observe(task)

    def mark_cancel(self, store, task_id, *, reason: str):
        task = store.task(task_id)
        with self._write() as conn:
            turn = conn.execute(select(self.turns).where(self.turns.c.owner_id == task['owner_id'],
                self.turns.c.application_request_id == task['request_id'].removeprefix('application-start:'))).mappings().first()
            if turn is not None:
                row = self._row(conn, task['owner_id'], turn['session_id'])
                if self._turns(conn, row['id'])[-1]['id'] == turn['id']:
                    if (reason == 'native-failure' and self.collaboration is not None
                            and self.collaboration.retain_after_native_failure(conn, row, turn, task)):
                        return
                    self._save_session(conn, row, {**row['body'], 'stopped': True})
                    if self.collaboration is not None:
                        self.collaboration.stop(conn, task['owner_id'], row['id'])

    async def deliver_collaboration(self, store, origin_task, event_id, message_id):
        if self.collaboration is None or store is not self.store:
            return False
        return await self.collaboration.deliver(origin_task, event_id, message_id)

    def validate_collaboration_admission(self, store, origin_task, event_id, request_id, plan):
        if self.collaboration is None or store is not self.store:
            raise PermissionError('RESEARCH_COLLABORATION_UNAVAILABLE')
        self.collaboration.validate_admission(origin_task, event_id, request_id, plan)

    def task_held(self, store, task):
        with self.db.read() as conn:
            turn = conn.execute(select(self.turns.c.body).where(self.turns.c.owner_id == task['owner_id'],
                self.turns.c.application_request_id == task['request_id'].removeprefix('application-start:'))).scalar_one_or_none()
            return bool(turn and turn.get('blockReason'))

    def workspace(self, owner, identifier):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            row = self._row(conn, owner, identifier)
            return self.tools._workspace({'ownerId': owner, 'id': row['id']})

    async def read(self, owner, identifier):
        self.auth.require_member(owner)
        observations = await self._refresh(owner, identifier)
        with self.db.read() as conn:
            row, turns = self._row(conn, owner, identifier), self._turns(conn, identifier)
            body = row['body']
            latest = turns[-1] if turns else None
            safe = not latest or self._safe(owner, latest)
            block = latest['body'].get('blockReason') if latest else None
            if block == 'RESEARCH_EFFECT_UNCONFIRMED':
                block = None
            if latest and latest['body']['status'] == 'unknown':
                block = block or 'RESEARCH_ORIGINAL_OUTCOME_UNCONFIRMED'
            raw_characters = sum(len(item['text']) for turn in turns for item in turn['body']['messages'])
            raw_characters += sum(len(str(turn['body'].get('result') or '')) for turn in turns)
            context_row = self._continuation_context(row, turns) if safe else row
            context_turns = session_context.active_turns(context_row, turns)
            compaction = context_turns[-1]['body'].get('compaction') if context_turns else None
            saved = session_context.checkpoint(context_row)
            through = saved['throughSequence'] if saved else 0
            characters = sum(len(item['text']) for turn in context_turns if turn['sequence'] > through
                             for item in turn['body']['messages'])
            characters += sum(len(str(turn['body'].get('result') or '')) for turn in context_turns if turn['sequence'] > through)
            if saved:
                characters += len(saved['summary']['summary'])
            compact_view: dict[str, Any] | None = None
            if compaction and compact_view is None:
                compact_view = {'status': {'pending': 'needed', 'started': 'preparing'}.get(
                    compaction['status'], compaction['status'])}
                if compaction.get('code'):
                    compact_view['code'] = compaction['code']
            elif saved and compact_view is None:
                compact_view = {'status': 'ready'}
            if compact_view:
                compact_view['throughSequence'] = saved['throughSequence'] if saved else 0
            state = ('blocked' if block else 'stopped' if body['stopped'] and safe else
                     'stopping' if body['stopped'] else 'idle' if safe else 'running')
            actions = []
            if safe and not block:
                actions.append('start')
            if latest and not body['stopped'] and not block:
                actions.append('correct')
            if not safe or not body['stopped']:
                actions.append('stop')
            return {'id': row['id'], 'assistantId': row['assistant_id'],
                'projectId': body.get('projectId'),
                **{key: deepcopy(body[key]) for key in ('title', 'goal', 'boundaries', 'createdAt', 'updatedAt', 'sharedSourceIds')},
                'model': deepcopy(body['configuration']['model']), 'state': state, 'allowedActions': actions,
                'capabilities': {'memory': body['configuration'].get('personalMemory') is True},
                'collaboration': {'enabled': body['configuration'].get('autonomousCollaboration') is True},
                'blockReason': block, 'context': {'characters': characters, 'maximumCharacters': None,
                    'rawCharacters': raw_characters, 'notice': context_row['body'].get('contextNotice'), **({'compaction': compact_view} if compact_view else {})},
                'turns': [{'id': item['id'], 'sequence': item['sequence'],
                    **({'assistantReply': self._reply_projection(owner, identifier, item['body']['assistantReply'])}
                       if 'assistantReply' in item['body'] else {}),
                    **({'assistantReplies': [self._reply_projection(owner, identifier, snapshot)
                        for snapshot in item['body']['assistantReplies']]} if 'assistantReplies' in item['body'] else {}),
                    **({'continuation': deepcopy(item['body']['continuation'])} if 'continuation' in item['body'] else {}),
                    **{key: deepcopy(item['body'].get(key))
                    for key in ('requestId', 'taskId', 'runId', 'status', 'createdAt', 'completedAt', 'result',
                                'messages', 'events', 'toolResults', 'children', 'failure')},
                    **((observations[item['id']] if item['id'] in observations else
                        {'events': self.store.events(item['body']['taskId']),
                        'toolResults': [{'effectKey': effect['effect_key'], 'status': effect['status'], 'result': effect['result']}
                            for effect in self.store.effects(item['body']['taskId'])]})
                       if item['body'].get('taskId') and not item['body'].get('terminal') else {})} for item in turns]}

    async def listing(self, owner, after=''):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            if after:
                self._row(conn, owner, after)
            query = select(self.sessions.c.id).where(self.sessions.c.owner_id == owner)
            if after:
                query = query.where(self.sessions.c.id < after)
            identifiers = list(conn.execute(query.order_by(self.sessions.c.id.desc()).limit(21)).scalars())
        items = []
        for identifier in identifiers[:20]:
            detail = await self.read(owner, identifier)
            items.append({key: value for key, value in detail.items() if key != 'turns'})
        return {'items': items, 'nextCursor': identifiers[19] if len(identifiers) > 20 else None}

    async def request(self, owner, request_id):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            command = conn.execute(select(self.commands).where(self.commands.c.actor_id == owner,
                self.commands.c.request_id == request_id)).mappings().first()
            if command is None:
                raise rejected('RESEARCH_SESSION_REQUEST_NOT_FOUND', '尚未找到原请求回执，请继续核对；不会自动重发。', 404)
            result = deepcopy(command['result'])
        return {'requestId': request_id, **result, 'session': await self.read(owner, result['sessionId']),
                'createsExecution': False, 'automaticReplay': False}

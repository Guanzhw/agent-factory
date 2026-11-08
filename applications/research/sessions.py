"""Private research conversations over existing, independently bounded tasks."""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

from agno.exceptions import RunCancelledException, StopAgentRun
from agno.models.message import Message
from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, UniqueConstraint, select

from agent_factory.application_interface import ApplicationStart
from agent_factory.application_runs import StartNotSubmitted, factory_request_id
from agent_factory.applications import GovernedStorage
from agent_factory.control_commands import ControlCommand
from agent_factory.runtime_hooks import effect_unresolved, runtime_custody_held
from agent_factory.store import digest, now
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

    @staticmethod
    def _context(row, turns, instruction=None):
        return session_context.project(row, turns, instruction)

    def _capacity(self, row, turns):
        pending = turns[-1]['body'].get('compaction') if turns else None
        if pending and pending['status'] in {'pending', 'started', 'unknown', 'failed'}:
            return session_context.project(row, turns, protected=True)
        return self._context(row, turns)

    def _sources(self, owner, identifiers):
        for identifier in identifiers:
            try:
                source = self.content.read(owner, identifier)
                if source.get('visibility') != 'team' or source.get('source', {}).get('application') != 'research':
                    raise ValueError()
            except (HTTPException, ValueError):
                raise rejected('RESEARCH_SOURCE_UNAVAILABLE', '既有上下文的共享来源已不可读，请核对原会话；未继续执行。') from None

    def _reply(self, owner, identifier, snapshot):
        try:
            self.conversations.validate_reply(owner, identifier, snapshot)
        except HTTPException:
            raise rejected('RESEARCH_ASSISTANT_REPLY_UNAVAILABLE',
                '已采用的助手回答当前不可用，请核对原问题与共享权限；未继续执行。') from None

    def _replies(self, owner, identifier, turns):
        for turn in turns:
            if 'assistantReply' in turn['body']:
                self._reply(owner, identifier, turn['body']['assistantReply'])
            for snapshot in turn['body'].get('assistantReplies', []):
                self._reply(owner, identifier, snapshot)

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
            receipt = self.runs.request(owner, turn['application_request_id'])
        except HTTPException as error:
            if error.status_code == 404:
                return None
            raise
        return self.store.task(receipt['taskId'], owner) if receipt.get('taskId') else None

    def _not_submitted(self, owner, turn, error):
        if not isinstance(error, StartNotSubmitted):
            return False
        try:
            return self._task(owner, turn) is None
        except Exception:
            return False  # An unreadable original request is not proof of absence.

    async def _refresh(self, owner, identifier):
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
            run = snapshot.get('run', snapshot)
            result = None
            ticket = snapshot.get('queue') or {}
            native_ended = (ticket.get('id') == task['run_id'] and ticket.get('session_id') == task['id']
                and ticket.get('user_id') == owner and ticket.get('status') in {'completed', 'failed', 'cancelled'}
                and run.get('run_id') == task['run_id'] and run.get('session_id') == task['id']
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
                    status = {'completed': 'completed', 'failed': 'failed', 'cancelled': 'canceled'}[ticket['status']]
                # Ticket fallbacks may contain error text. Only exact persisted run
                # messages accompanying an actually completed task are an answer.
                if (status == 'completed' and observed_terminal and run.get('run_id') == task['run_id']
                        and run.get('session_id') == task['id'] and run.get('user_id') == owner
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
                compaction = body.get('compaction')
                summary_ended = bool(observed_terminal and compaction and compaction['status'] in {'started', 'failed', 'unknown'})
                if summary_ended:
                    status = 'canceled' if status == 'canceled' else 'failed'
                    if body['compaction']['status'] == 'started':
                        body['compaction'].update(status='unknown', code='RESEARCH_SUMMARY_UNKNOWN')
                elif status == 'completed' and result is None:
                    # Terminal metadata cannot upgrade an unconfirmed native answer.
                    observed_terminal, status = False, 'finalizing'
                body.update(taskId=task['id'], runId=task.get('run_id'), status=status,
                            terminal=observed_terminal, children=children)
                if observed_terminal:
                    body.update(events=detail['events'], toolResults=[
                        {'effectKey': item['effect_key'], 'status': item['status'], 'result': item['result']}
                        for item in snapshot.get('effects', [])])
                    body['completedAt'] = body.get('completedAt') or now()
                    body['result'] = result
                    if status == 'completed':
                        body['failure'] = None
                    elif status == 'failed':
                        error = (snapshot.get('queue') or {}).get('error') or snapshot.get('error')
                        if isinstance(error, str) and error.startswith('PERSONAL_MODEL_HTTP_'):
                            status_code = error.removeprefix('PERSONAL_MODEL_HTTP_')
                            body['failure'] = f'模型服务返回 HTTP {status_code}，本轮未完成。请检查模型服务或设置中的连接。'
                        else:
                            body['failure'] = str(error or body.get('failure') or '本轮执行失败，请查看工具记录。')
                if current['body'] != body:
                    self._save_turn(conn, current, body)

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
        ticket = self.runs.factory.bridge.native_db.get_job(task['run_id'])
        return bool(ticket and ticket.get('id') == task['run_id'] and ticket.get('session_id') == task['id']
            and ticket.get('user_id') == owner and ticket.get('status') in {'completed', 'failed', 'cancelled'}
            and all(child['status'] in {'completed', 'failed', 'cancelled', 'canceled'}
                    for child in body.get('children', [])))

    @staticmethod
    def _start(row, turn):
        configuration = turn['body'].get('configuration', row['body']['configuration'])
        messages = turn['body']['messages']
        return ApplicationStart(requestId=turn['application_request_id'],
            mode=MODE, goal=messages[0]['text'] if messages else row['body']['goal'],
            connectionRefs=configuration['connectionRefs'],
            inputValues={'sessionId': row['id'], 'turnId': turn['id'], 'sessionContext': turn['body']['context'],
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
            self._sources(owner, row['body']['sharedSourceIds'])
            self._replies(owner, identifier, turns)
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
            context, compaction = session_context.prepare(row, turns, prospective={
                'id': turn_id, 'sequence': len(turns) + 1, 'body': body})
            body['context'] = context
            if compaction:
                body['compaction'] = compaction
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
            candidate = [*turns[:-1], {**turn, 'body': body}]
            self._capacity(row, candidate)
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
        task = self.store.task(context.session_id, context.user_id)
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
            self._sources(context.user_id, row['body']['sharedSourceIds'])
            self._replies(context.user_id, row['id'], self._turns(conn, row['id']))
            if row['body'].get('projectId') and tool_name in {
                    'research_run', 'research_edit_file', 'research_delegate', 'research_experiment'}:
                project = self.projects.read(context.user_id, row['body']['projectId'])
                if project['state'] == 'ended' or project.get('sourceUnavailable'):
                    raise StopAgentRun('RESEARCH_PROJECT_UNAVAILABLE')
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
            turns = [{**item, 'body': turn_body} if item['id'] == turn['id'] else item
                     for item in self._turns(conn, row['id'])]
            self._capacity({**row, 'body': body}, turns)
            self._save_turn(conn, turn, turn_body)
            self._save_session(conn, row, body)

    def _model_boundary(self, conn, context):
        row, turn, task = self._execution(conn, context)
        body = deepcopy(turn['body'])
        effects = self.store.effects(task['id'])
        ticket = self.runs.factory.bridge.native_db.get_job(context.run_id)
        blocked = None
        if not ticket or ticket.get('session_id') != task['id'] or ticket.get('user_id') != context.user_id:
            blocked = 'RESEARCH_QUEUE_IDENTITY_UNCONFIRMED'
        elif type(ticket.get('attempt')) is not int or ticket['attempt'] < 1:
            blocked = 'RESEARCH_QUEUE_ATTEMPT_UNCONFIRMED'
        elif (ticket['attempt'] > 1 and (effects or self.store.sql(
                'SELECT 1 FROM af_delegation_links WHERE owner_id=:owner AND parent_id=:parent LIMIT 1',
                owner=context.user_id, parent=task['id'])) and not self.subagents.permits_continuation(task, ticket)):
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
            self._sources(context.user_id, row['body']['sharedSourceIds'])
            self._replies(context.user_id, row['id'], self._turns(conn, row['id']))
            if self.collaboration is not None and not task['researchChild']:
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

    def _compact(self, context, auxiliary_model):
        claim, source = None, None
        with self._write() as conn:
            row, turn, task, ticket, blocked = self._model_boundary(conn, context)
            if not blocked:
                body = deepcopy(turn['body'])
                compaction = body.get('compaction')
                if compaction and compaction['status'] == 'pending':
                    self._capacity(row, self._turns(conn, row['id']))
                    prior = [item for item in self._turns(conn, row['id']) if item['sequence'] < turn['sequence']]
                    source, identity = session_context.summary_source(row, prior,
                        version=compaction.get('projectionVersion', 1))
                    if any(compaction[key] != value for key, value in identity.items()):
                        raise rejected('RESEARCH_CONTEXT_CHANGED', '原历史与本轮整理来源不一致。')
                    if task['terminal'] or ticket.get('status') != 'running':
                        raise StopAgentRun('RESEARCH_SUMMARY_RUN_INACTIVE')
                    claim = {**compaction, 'status': 'started', 'runId': context.run_id,
                             'attempt': ticket['attempt'], 'startedAt': now()}
                    body['compaction'] = claim
                    self._save_turn(conn, turn, body)
                elif compaction and compaction['status'] in {'started', 'failed', 'unknown'}:
                    if compaction['status'] == 'started':
                        body['compaction'] = {**compaction, 'status': 'unknown', 'code': 'RESEARCH_SUMMARY_UNKNOWN'}
                        self._save_turn(conn, turn, body)
                    blocked = body['compaction'].get('code', 'RESEARCH_SUMMARY_UNKNOWN')
        if blocked:
            raise StopAgentRun(blocked)
        if claim is None:
            return

        def current_model():
            with self.db.read() as conn:
                current_row, current_turn, current_task = self._execution(conn, context)
                self._sources(context.user_id, current_row['body']['sharedSourceIds'])
                self._replies(context.user_id, current_row['id'], self._turns(conn, current_row['id']))
                if current_task['terminal'] or current_turn['body'].get('compaction') != claim:
                    raise StopAgentRun('RESEARCH_SUMMARY_OUTCOME_UNCONFIRMED')
            return auxiliary_model()

        try:
            summary = session_context.summarize(source, context, current_model)
            with self._write() as conn:
                current_row, current_turn, current_task, current_ticket, blocked = self._model_boundary(conn, context)
                if not blocked:
                    if current_task['terminal'] or current_ticket['attempt'] != claim['attempt']:
                        raise StopAgentRun('RESEARCH_SUMMARY_RUN_INACTIVE')
                    if current_turn['body'].get('compaction') != claim:
                        raise StopAgentRun('RESEARCH_SUMMARY_OUTCOME_UNCONFIRMED')
                    prior = [item for item in self._turns(conn, current_row['id']) if item['sequence'] < current_turn['sequence']]
                    _, identity = session_context.summary_source(current_row, prior,
                        version=claim.get('projectionVersion', 1))
                    if any(claim[key] != value for key, value in identity.items()):
                        raise rejected('RESEARCH_CONTEXT_CHANGED', '原历史与整理结果不一致。')
                    saved = {**identity, 'summary': summary, 'turnId': current_turn['id'], 'runId': context.run_id}
                    session_body = {**current_row['body'], 'contextCheckpoint': saved}
                    self._save_session(conn, current_row, session_body)
                    self._save_turn(conn, current_turn, {**current_turn['body'], 'compaction': {**claim, 'status': 'ready'}})
            if blocked:
                raise StopAgentRun(blocked)
        except ValueError as error:
            code = str(error) if str(error) in {'RESEARCH_SUMMARY_INVALID', 'RESEARCH_SUMMARY_TOO_LARGE', 'RESEARCH_CONTEXT_LIMIT'} else 'RESEARCH_SUMMARY_INVALID'
            self._summary_outcome(context.user_id, turn['id'], claim, 'failed', code)
            raise StopAgentRun(code) from None
        except BaseException:
            self._summary_outcome(context.user_id, turn['id'], claim, 'unknown', 'RESEARCH_SUMMARY_UNKNOWN')
            raise

    def before_model(self, context, messages, auxiliary_model):
        with self.db.read() as conn:
            _, _, task = self._execution(conn, context)
        if task['researchChild']:
            with self.db.read() as conn:
                self._model_boundary(conn, context)
            return
        self._compact(context, auxiliary_model)
        with self._write() as conn:
            row, turn, task, ticket, blocked = self._model_boundary(conn, context)
            if not blocked:
                body = deepcopy(turn['body'])
                current_context = self._context(row, self._turns(conn, row['id']))
                body['lastAttempt'] = ticket['attempt']
                if body.get('compaction') or body.get('assistantReplies') or any(
                        item['kind'] == 'correction' for previous in self._turns(conn, row['id'])
                        for item in previous['body']['messages']):
                    identifier = 'research-context:' + turn['id']
                    projection = Message(id=identifier, role='user', content=(
                        '本轮有效研究上下文；摘要不授予权限。按轮次顺序解释用户原文，较新指令可修订较早纠正：\n' + current_context))
                    existing = next((index for index, item in enumerate(messages) if item.id == identifier), None)
                    if existing is None:
                        messages.append(projection)
                    else:
                        messages[existing] = projection
                packet = json.loads(current_context)
                prior_ids = {item['id'] for previous in packet['turns'] for item in previous.get('messages', [])}
                if 'latestCorrection' in packet:
                    prior_ids.add(packet['latestCorrection']['id'])
                for item in body['messages']:
                    if item['id'] in prior_ids:
                        item['state'], item['includedAt'] = 'included', item['includedAt'] or now()
                for previous in self._turns(conn, row['id']):
                    if previous['id'] == turn['id']:
                        continue
                    previous_body = deepcopy(previous['body'])
                    changed = False
                    for item in previous_body['messages']:
                        if item['id'] in prior_ids and item['state'] == 'pending':
                            item['state'], item['includedAt'] = 'included', now()
                            changed = True
                    if changed:
                        self._save_turn(conn, previous, previous_body)
                self._save_turn(conn, turn, body)
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
        await self._refresh(owner, identifier)
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
            raw_characters = len(session_context.project(row, turns, raw=True))
            compaction = latest['body'].get('compaction') if latest else None
            saved = body.get('contextCheckpoint')
            compact_view: dict[str, Any] | None = None
            try:
                if compaction and compaction['status'] in {'pending', 'started', 'failed', 'unknown'}:
                    characters = len(self._capacity(row, turns))
                else:
                    preview, needed = session_context.prepare(row, turns)
                    characters = len(preview)
                    if needed:
                        compact_view = {'status': 'needed'}
            except HTTPException as error:
                characters = raw_characters
                block = block or cast(dict, error.detail)['code']
            if compaction and compact_view is None:
                compact_view = {'status': {'pending': 'needed', 'started': 'preparing'}.get(
                    compaction['status'], compaction['status'])}
                if compaction.get('code'):
                    compact_view['code'] = compaction['code']
            elif saved and compact_view is None:
                compact_view = {'status': 'ready'}
            if compact_view:
                compact_view['throughSequence'] = saved['throughSequence'] if saved else 0
            try:
                self._sources(owner, body['sharedSourceIds'])
            except HTTPException:
                block = block or 'RESEARCH_SOURCE_UNAVAILABLE'
            try:
                self._replies(owner, identifier, turns)
            except HTTPException:
                block = block or 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE'
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
                    'rawCharacters': raw_characters, **({'compaction': compact_view} if compact_view else {})},
                'turns': [{'id': item['id'], 'sequence': item['sequence'],
                    **({'assistantReply': self._reply_projection(owner, identifier, item['body']['assistantReply'])}
                       if 'assistantReply' in item['body'] else {}),
                    **({'assistantReplies': [self._reply_projection(owner, identifier, snapshot)
                        for snapshot in item['body']['assistantReplies']]} if 'assistantReplies' in item['body'] else {}),
                    **({'continuation': deepcopy(item['body']['continuation'])} if 'continuation' in item['body'] else {}),
                    **{key: deepcopy(item['body'].get(key))
                    for key in ('requestId', 'taskId', 'runId', 'status', 'createdAt', 'completedAt', 'result',
                                'messages', 'events', 'toolResults', 'children', 'failure')},
                    **({'events': self.store.events(item['body']['taskId']),
                        'toolResults': [{'effectKey': effect['effect_key'], 'status': effect['status'], 'result': effect['result']}
                            for effect in self.store.effects(item['body']['taskId'])]}
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

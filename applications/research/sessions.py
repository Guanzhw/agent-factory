"""Private research conversations over existing, independently bounded tasks."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

from agno.exceptions import RunCancelledException, StopAgentRun
from agno.models.message import Message
from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, UniqueConstraint, select

from agent_factory.application_interface import ApplicationStart
from agent_factory.application_runs import factory_request_id
from agent_factory.applications import GovernedStorage
from agent_factory.control_commands import ControlCommand
from agent_factory.runtime_hooks import effect_unresolved, runtime_custody_held
from agent_factory.store import canonical, digest, now
from .assistants import CreateAssistant
from .session_setup import CONTEXT_CHARACTERS, MODE, ResearchSessionSetup, rejected


class ResearchSessions:
    def __init__(self, store, auth, assistants, runs, *, connections, models, content, tools):
        self.store, self.auth, self.assistants, self.runs = store, auth, assistants, runs
        self.content, self.tools = content, tools
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
        registrations = [('environment', tools.environment_registration),
                         *[('tool', entry) for entry in tools.tool_registrations]]
        store.application_runtime.register('research-session', self,
            bindings=tuple((kind, entry.adapter_id, entry.revision) for kind, entry in registrations))

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
        body = row['body']
        entries = [{'sequence': turn['sequence'], 'messages': [
            {'id': item['id'], 'kind': item['kind'], 'text': item['text']} for item in turn['body']['messages']],
            'result': turn['body'].get('result'), 'status': turn['body']['status'],
            'failure': turn['body'].get('failure')} for turn in turns]
        if instruction is not None:
            entries.append({'sequence': len(turns) + 1, 'instruction': instruction})
        # All completed results and pending corrections remain present; no slice,
        # surrogate summary, or copied tool trace is used to fit the boundary.
        return canonical({'goal': body['goal'], 'boundaries': body['boundaries'], 'turns': entries,
                          'sharedSourceIds': body['sharedSourceIds']})

    @staticmethod
    def _bounded(context):
        if len(context) > CONTEXT_CHARACTERS:
            raise rejected('RESEARCH_CONTEXT_LIMIT', '会话上下文超过当前容量；原历史已保留，未启动新执行。')
        return context

    def _sources(self, owner, identifiers):
        for identifier in identifiers:
            try:
                source = self.content.read(owner, identifier)
                if source.get('visibility') != 'team' or source.get('source', {}).get('application') != 'research':
                    raise ValueError()
            except (HTTPException, ValueError):
                raise rejected('RESEARCH_SOURCE_UNAVAILABLE', '既有上下文的共享来源已不可读，请核对原会话；未继续执行。') from None

    def create(self, owner, request):
        self.auth.require_member(owner)
        value = request.model_dump(exclude={'requestId'})
        fingerprint = digest({'action': 'create', **value})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old is not None:
                return old['sessionId']
            configuration = self.setup.prepare(owner, value['modelConnectionRef'], value['limits'])
            assistant = self.assistants.create(owner, CreateAssistant(
                requestId='session-identity:' + digest({'owner': owner, 'request': request.requestId})[:32]))
            identifier, stamp = str(uuid4()), now()
            body = {key: value[key] for key in ('title', 'goal', 'boundaries', 'limits')}
            body.update(configuration=configuration, createdAt=stamp, updatedAt=stamp,
                        stopped=False, stopRequestId=None, sharedSourceIds=[])
            self._bounded(self._context({'body': body}, []))
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
            try:
                detail = await self.runs.factory.detail(task)
            except HTTPException:
                # A failed observation is not a failed task or a dispatch grant.
                continue
            task = self.store.task(task['id'], owner)
            status, snapshot = detail['job']['status'], detail['snapshot']
            run = snapshot.get('run', snapshot)
            result = None
            observed_terminal = bool(task['terminal'] and status in {'completed', 'failed', 'canceled'})
            # Ticket fallbacks may contain error text. Only exact persisted run
            # messages accompanying an actually completed task are an answer.
            if (status == 'completed' and observed_terminal and run.get('run_id') == task['run_id']
                    and run.get('session_id') == task['id'] and run.get('user_id') == owner
                    and str(run.get('status', '')).lower() == 'completed'
                    and isinstance(run.get('messages'), list)
                    and any(item.get('role') == 'assistant' for item in run['messages'] if isinstance(item, dict))
                    and isinstance(run.get('content'), str)):
                result = run['content']
            if status == 'completed' and result is None:
                # A later task-row completion cannot upgrade a stale or missing
                # native observation. The next ordinary read can obtain it.
                observed_terminal, status = False, 'finalizing'
            with self.db.write() as conn:
                current = conn.execute(select(self.turns).where(self.turns.c.id == turn['id'])).mappings().one()
                if current['body'].get('terminal'):
                    continue  # A concurrent confirmed final result wins over this older observation.
                body = deepcopy(current['body'])
                body.update(taskId=task['id'], runId=task.get('run_id'), status=status,
                            terminal=observed_terminal, events=detail['events'],
                            toolResults=[{'effectKey': item['effect_key'], 'status': item['status'], 'result': item['result']}
                                         for item in snapshot.get('effects', [])])
                if observed_terminal:
                    body['completedAt'] = body.get('completedAt') or now()
                    body['result'] = result
                    if status == 'completed':
                        body['failure'] = None
                    elif status == 'failed':
                        body['failure'] = body.get('failure') or '本轮执行失败，请查看原任务与工具记录。'
                self._save_turn(conn, current, body)

    def _safe(self, owner, turn):
        body = turn['body']
        if body.get('blockReason') or not body['terminal']:
            return False
        task = self._task(owner, turn)
        if task is None:
            return bool(body.get('neverDispatched') and body['terminal'])
        return bool(task and task['terminal'] and not runtime_custody_held(self.store, task['id'])
                    and not any(effect_unresolved(item, self.store) for item in self.store.effects(task['id'])))

    @staticmethod
    def _start(row, turn):
        configuration = row['body']['configuration']
        return ApplicationStart(requestId=turn['application_request_id'],
            application=configuration['applicationRef']['id'], applicationRef=configuration['applicationRef'],
            mode=MODE, goal=row['body']['goal'], connectionRefs=configuration['connectionRefs'],
            inputValues={'sessionId': row['id'], 'turnId': turn['id'], 'sessionContext': turn['body']['context']})

    def _reserve(self, owner, identifier, request):
        fingerprint = digest({'action': 'turn', 'sessionId': identifier, 'text': request.text})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old is not None:
                return old['turnId'], False
            row, turns = self._row(conn, owner, identifier), self._turns(conn, identifier)
            if turns and not self._safe(owner, turns[-1]):
                raise rejected('RESEARCH_TURN_ACTIVE_OR_UNCONFIRMED', '原轮次尚未安全结束，请先核对其状态。')
            if len(turns) >= row['body']['limits']['maxTurns']:
                raise rejected('RESEARCH_TURN_LIMIT', '已达到本会话约定轮数，原历史已保留。')
            self._sources(owner, row['body']['sharedSourceIds'])
            context = self._bounded(self._context(row, turns, request.text))
            turn_id, stamp = str(uuid4()), now()
            body = {'requestId': request.requestId, 'taskId': None, 'runId': None, 'status': 'reserved',
                'createdAt': stamp, 'completedAt': None, 'result': None, 'failure': None, 'terminal': False,
                'blockReason': None, 'messages': [self._message('instruction', request.text)],
                'context': context, 'lastAttempt': 0, 'dispatchStarted': False, 'events': [], 'toolResults': []}
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
            with self.db.write() as conn:
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
                except Exception:
                    with self.db.write() as conn:
                        current = conn.execute(select(self.turns).where(self.turns.c.id == turn_id)).mappings().one()
                        if not current['body'].get('terminal'):
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
        with self.db.write() as conn:
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
            self._bounded(self._context(row, candidate))
            self._save_turn(conn, turn, body)
            self._save_session(conn, row, row['body'])
            self._command(conn, owner, request.requestId, fingerprint, 'correct', identifier, turn['id'])

    async def stop(self, owner, identifier, request):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'stop', 'sessionId': identifier})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            row = self._row(conn, owner, identifier)
            if old is None:
                self._save_session(conn, row, {**row['body'], 'stopped': True, 'stopRequestId': request.requestId})
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
        turn = conn.execute(select(self.turns).where(self.turns.c.owner_id == context.user_id,
            self.turns.c.application_request_id == task['request_id'].removeprefix('application-start:'))).mappings().first()
        if turn is None or task['request_id'] != factory_request_id(turn['application_request_id']):
            raise PermissionError('RESEARCH_SESSION_ORIGINAL_TURN_REQUIRED')
        row = self._row(conn, context.user_id, turn['session_id'])
        plan = self.store.plan(task['plan_id'], context.user_id)
        expected = row['body']['configuration']
        if plan.get('applicationRef') != expected['applicationRef'] or plan.get('mode') != MODE:
            raise PermissionError('RESEARCH_SESSION_PLAN_MISMATCH')
        if (plan.get('inputValues') or {}).get('turnId') != turn['id']:
            raise PermissionError('RESEARCH_SESSION_INPUT_MISMATCH')
        original = self.store.sql('SELECT fingerprint FROM af_plan_requests WHERE owner_id=:owner '
            'AND request_id=:request AND plan_id=:plan', owner=context.user_id,
            request=task['request_id'], plan=task['plan_id'])
        if len(original) != 1 or original[0]['fingerprint'] != turn['body']['startFingerprint']:
            raise PermissionError('RESEARCH_SESSION_ADMISSION_PAYLOAD_MISMATCH')
        latest = self._turns(conn, row['id'])[-1]
        if latest['id'] != turn['id'] or row['body']['stopped'] or task['cancel_requested']:
            raise RunCancelledException('RESEARCH_SESSION_STOP_REQUESTED')
        if turn['body'].get('blockReason'):
            raise StopAgentRun(turn['body']['blockReason'])
        return row, turn, task

    def authorize_tool(self, context, tool_name):
        self.auth.require_member(context.user_id)
        with self.db.read() as conn:
            row, turn, _ = self._execution(conn, context)
            self._sources(context.user_id, row['body']['sharedSourceIds'])
            self.store.authorize_tool(context, tool_name)
            return {'id': row['id'], 'ownerId': row['owner_id'], 'turnId': turn['id'],
                    'limits': deepcopy(row['body']['limits']), 'workspaceRef': row['id']}

    def record_source(self, context, identifier):
        with self.db.write() as conn:
            row, _, _ = self._execution(conn, context)
            self._sources(context.user_id, [identifier])
            body = deepcopy(row['body'])
            if identifier not in body['sharedSourceIds']:
                body['sharedSourceIds'].append(identifier)
                self._bounded(self._context({**row, 'body': body}, self._turns(conn, row['id'])))
                self._save_session(conn, row, body)

    def before_model(self, context, messages):
        blocked = None
        with self.db.write() as conn:
            row, turn, task = self._execution(conn, context)
            body = deepcopy(turn['body'])
            effects = self.store.effects(task['id'])
            ticket = self.runs.factory.bridge.native_db.get_job(context.run_id)
            if not ticket or ticket.get('session_id') != task['id'] or ticket.get('user_id') != context.user_id:
                blocked = 'RESEARCH_QUEUE_IDENTITY_UNCONFIRMED'
            elif type(ticket.get('attempt')) is not int or ticket['attempt'] < 1:
                blocked = 'RESEARCH_QUEUE_ATTEMPT_UNCONFIRMED'
            elif ticket['attempt'] > 1 and effects:
                blocked = 'RESEARCH_RESTART_REQUIRES_RECONCILIATION'
            elif any(effect_unresolved(item, self.store) for item in effects):
                blocked = 'RESEARCH_EFFECT_UNCONFIRMED'
            else:
                self._sources(context.user_id, row['body']['sharedSourceIds'])
                self._bounded(self._context(row, self._turns(conn, row['id'])))
                body['lastAttempt'] = ticket['attempt']
                present = {item.id for item in messages}
                for item in body['messages']:
                    if item['kind'] == 'correction' and 'research-message:' + item['id'] not in present:
                        messages.append(Message(id='research-message:' + item['id'], role='user',
                            content='本会话的补充纠正（保留原目标与停止边界）：\n' + item['text']))
                    item['state'], item['includedAt'] = 'included', item['includedAt'] or now()
                # A correction received while a provider was producing its final
                # answer has no later request in that turn. It remains durable
                # and is acknowledged only when this new turn actually includes
                # it in the immutable context prepared before admission.
                prior_ids = {item['id'] for previous in json.loads(body['context'])['turns']
                             for item in previous.get('messages', [])}
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
            if blocked:
                body['blockReason'] = blocked
                self.store.event(task['id'], 'research_reconciliation_required', '原执行需要核对，已阻止新的模型调用。', {'code': blocked})
            self._save_turn(conn, turn, body)
        if blocked:
            raise StopAgentRun(blocked)

    def mark_cancel(self, store, task_id):
        task = store.task(task_id)
        with self.db.write() as conn:
            turn = conn.execute(select(self.turns).where(self.turns.c.owner_id == task['owner_id'],
                self.turns.c.application_request_id == task['request_id'].removeprefix('application-start:'))).mappings().first()
            if turn is not None:
                row = self._row(conn, task['owner_id'], turn['session_id'])
                if self._turns(conn, row['id'])[-1]['id'] == turn['id']:
                    self._save_session(conn, row, {**row['body'], 'stopped': True})

    def task_held(self, store, task):
        with self.db.read() as conn:
            turn = conn.execute(select(self.turns.c.body).where(self.turns.c.owner_id == task['owner_id'],
                self.turns.c.application_request_id == task['request_id'].removeprefix('application-start:'))).scalar_one_or_none()
            return bool(turn and turn.get('blockReason'))

    async def read(self, owner, identifier):
        self.auth.require_member(owner)
        await self._refresh(owner, identifier)
        with self.db.read() as conn:
            row, turns = self._row(conn, owner, identifier), self._turns(conn, identifier)
            body = row['body']
            latest = turns[-1] if turns else None
            safe = not latest or self._safe(owner, latest)
            block = latest['body'].get('blockReason') if latest else None
            if latest and latest['body']['status'] == 'unknown':
                block = block or 'RESEARCH_ORIGINAL_OUTCOME_UNCONFIRMED'
            characters = len(self._context(row, turns))
            if characters > CONTEXT_CHARACTERS:
                block = block or 'RESEARCH_CONTEXT_LIMIT'
            try:
                self._sources(owner, body['sharedSourceIds'])
            except HTTPException:
                block = block or 'RESEARCH_SOURCE_UNAVAILABLE'
            state = ('blocked' if block else 'stopped' if body['stopped'] and safe else
                     'stopping' if body['stopped'] else 'idle' if safe else 'running')
            actions = []
            if safe and not block and len(turns) < body['limits']['maxTurns']:
                actions.append('start')
            if latest and not body['stopped'] and not block:
                actions.append('correct')
            if not safe or not body['stopped']:
                actions.append('stop')
            return {'id': row['id'], 'assistantId': row['assistant_id'],
                **{key: deepcopy(body[key]) for key in ('title', 'goal', 'boundaries', 'createdAt', 'updatedAt', 'limits', 'sharedSourceIds')},
                'model': deepcopy(body['configuration']['model']), 'state': state, 'allowedActions': actions,
                'blockReason': block, 'context': {'characters': characters, 'maximumCharacters': CONTEXT_CHARACTERS},
                'turns': [{'id': item['id'], 'sequence': item['sequence'], **{key: deepcopy(item['body'].get(key))
                    for key in ('requestId', 'taskId', 'runId', 'status', 'createdAt', 'completedAt', 'result',
                                'messages', 'events', 'toolResults', 'failure')}} for item in turns]}

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

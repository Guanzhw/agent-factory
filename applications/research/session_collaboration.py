"""Research continuations attached to the existing private message event."""
from copy import deepcopy
from typing import cast
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, UniqueConstraint, select

from agent_factory.store import digest, now
from agent_factory.personal_tool_contract import ToolInvocationError
from agent_factory.runtime_hooks import effect_unresolved, runtime_custody_held
from .conversations import SessionQuestion
from .session_setup import rejected
from . import session_context


TERMINAL = {'included', 'blocked', 'stopped'}
QUESTION_BLOCKS = {'RESEARCH_EFFECT_UNCONFIRMED', 'RESEARCH_RESTART_REQUIRES_RECONCILIATION'}


class ResearchCollaboration:
    def __init__(self, sessions, conversations, events):
        self.sessions, self.conversations, self.events = sessions, conversations, events
        self.store = sessions.store
        metadata = MetaData()
        self.intents = Table('research_collaboration_intents', metadata,
            Column('question_id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('session_id', String, nullable=False), Column('request_id', String, nullable=False),
            Column('created_at', String, nullable=False), Column('body', JSON, nullable=False),
            UniqueConstraint('owner_id', 'request_id'))
        metadata.create_all(self.store.engine)

    def _rows(self, conn, owner, session_id):
        return list(conn.execute(select(self.intents).where(self.intents.c.owner_id == owner,
            self.intents.c.session_id == session_id).order_by(self.intents.c.created_at,
                self.intents.c.question_id)).mappings())

    def _save(self, conn, intent, **changes):
        body = {**intent['body'], **changes}
        conn.execute(self.intents.update().where(self.intents.c.question_id == intent['question_id']).values(body=body))
        return {**intent, 'body': body}

    @staticmethod
    def _request(context, call_id):
        return 'research-ask:' + digest({'runId': context.run_id, 'callId': call_id})

    @staticmethod
    def _ack(intent):
        return {'questionId': intent['question_id'], 'state': 'saved'}

    def directory(self, context):
        self.sessions.authorize_tool(context, 'research_assistant_directory')
        return self.sessions.assistants.list(context.user_id)

    def ask(self, context, call_id, arguments):
        try:
            return self._ask(context, call_id, arguments)
        except HTTPException as error:
            detail = error.detail
            code = str(cast(dict, detail)['code'] if isinstance(detail, dict) else detail)
            raise ToolInvocationError(code, outcome='failed', stopped=True) from error

    def _ask(self, context, call_id, arguments):
        service = self.sessions
        with service._write() as conn:
            row, turn, task = service._execution(conn, context)
            service.authorize_tool(context, 'research_ask_assistant')
            if row['body']['configuration'].get('autonomousCollaboration') is not True:
                raise rejected('RESEARCH_COLLABORATION_UNAVAILABLE', '原会话未配置自主协作工具。')
            request_id = self._request(context, call_id)
            old = conn.execute(select(self.intents).where(self.intents.c.owner_id == context.user_id,
                self.intents.c.request_id == request_id)).mappings().first()
            if old is not None:
                if old['body']['arguments'] != arguments or old['body']['originTaskId'] != task['id']:
                    raise rejected('RESEARCH_QUESTION_REQUEST_CONFLICT', '原工具请求已绑定其他问题。')
                return self._ack(old)
            effect_request = {'ownerId': context.user_id, 'taskId': task['id'], 'sessionId': row['id'],
                'turnId': turn['id'], 'toolName': 'research_ask_assistant', 'callId': call_id,
                'arguments': arguments}
            effect_key = context.run_id + ':research-session-tool:' + call_id
            effect = self.store.sql('SELECT fingerprint FROM af_effects WHERE effect_key=:key', key=effect_key)
            if len(effect) != 1 or effect[0]['fingerprint'] != digest(effect_request):
                raise PermissionError('RESEARCH_COLLABORATION_EFFECT_MISMATCH')
            question = SessionQuestion(requestId=request_id, assistantId=arguments['assistant_id'], text=arguments['text'])
            message, _ = self.conversations._reserve(context.user_id, row['id'], question)
            event = self.events.emit_collaboration(conn, context.user_id, message['id'], task['id'])
            body = {'originTurnId': turn['id'], 'originTaskId': task['id'], 'runId': context.run_id,
                'callId': call_id, 'arguments': deepcopy(arguments), 'eventId': event['id'],
                'effectKey': effect_key, 'effectFingerprint': digest(effect_request), 'state': 'waiting'}
            conn.execute(self.intents.insert().values(question_id=message['id'], owner_id=context.user_id,
                session_id=row['id'], request_id=request_id, created_at=now(), body=body))
            return {'questionId': message['id'], 'state': 'saved'}

    def _proof(self, intent):
        body = intent['body']
        expected = {'ownerId': intent['owner_id'], 'taskId': body['originTaskId'], 'sessionId': intent['session_id'],
            'turnId': body['originTurnId'], 'toolName': 'research_ask_assistant', 'callId': body['callId'],
            'arguments': body['arguments']}
        task = self.store.task(body['originTaskId'], intent['owner_id'])
        if (task['run_id'] != body['runId'] or body['effectFingerprint'] != digest(expected)
                or body['effectKey'] != body['runId'] + ':research-session-tool:' + body['callId']):
            raise PermissionError('RESEARCH_COLLABORATION_EFFECT_MISMATCH')
        message = self.conversations.messages.request(intent['owner_id'], intent['request_id'])
        if (message['id'] != intent['question_id'] or message['senderId'] != intent['owner_id']
                or message['text'] != body['arguments']['text']):
            raise PermissionError('RESEARCH_COLLABORATION_MESSAGE_MISMATCH')
        question = SessionQuestion(requestId=intent['request_id'],
            assistantId=body['arguments']['assistant_id'], text=body['arguments']['text'])
        endpoint, _ = self.sessions.assistants.question_target(intent['owner_id'], question.assistantId, question)
        if endpoint != message['endpointId']:
            raise PermissionError('RESEARCH_COLLABORATION_MESSAGE_MISMATCH')
        effect = self.store.sql('SELECT fingerprint FROM af_effects WHERE effect_key=:key', key=body['effectKey'])
        if len(effect) != 1 or effect[0]['fingerprint'] != body['effectFingerprint']:
            raise PermissionError('RESEARCH_COLLABORATION_EFFECT_MISMATCH')
        return self._ack(intent)

    def reconcile(self, context, call_id, arguments):
        with self.sessions.db.read() as conn:
            intent = conn.execute(select(self.intents).where(self.intents.c.owner_id == context.user_id,
                self.intents.c.request_id == self._request(context, call_id))).mappings().first()
            if intent is None:
                return None
            body = intent['body']
            if (body['originTaskId'], body['runId'], body['callId'], body['arguments']) != (
                    context.session_id, context.run_id, call_id, arguments):
                raise PermissionError('RESEARCH_COLLABORATION_MESSAGE_MISMATCH')
            self.store.task(context.session_id, context.user_id)
            return self._proof(intent)

    def _reconcile_receipt(self, intent):
        ack = self._proof(intent)
        body = intent['body']
        effect = next(item for item in self.store.effects(body['originTaskId'])
            if item['effect_key'] == body['effectKey'])
        if effect['status'] == 'UNKNOWN':
            self.store.effect_complete(body['runId'], 'research-session-tool:' + body['callId'],
                {'outcome': 'completed', 'output': ack})

    def retain_after_native_failure(self, conn, row, turn, task):
        if (row['body']['stopped'] or turn['body'].get('stopRequestId')
                or turn['body'].get('blockReason') not in {None, *QUESTION_BLOCKS}):
            return False
        history = self.store.sql("""SELECT
            EXISTS(SELECT 1 FROM af_events WHERE task_id=:task AND type='research_reconciliation_required'
                AND data->>'code' IN ('RESEARCH_EFFECT_UNCONFIRMED','RESEARCH_RESTART_REQUIRES_RECONCILIATION')) AS guarded,
            EXISTS(SELECT 1 FROM af_events WHERE task_id=:task AND (
                type IN ('protected_denied','tool_failed','experiment_failed','cancel_requested') OR
                type='research_reconciliation_required' AND data->>'code' NOT IN
                    ('RESEARCH_EFFECT_UNCONFIRMED','RESEARCH_RESTART_REQUIRES_RECONCILIATION') OR
                type='lifecycle_cleanup_requested' AND data->>'reason'<>'native-failure')) AS protected
            """, task=task['id'])[0]
        if not history['guarded'] or history['protected']:
            return False
        intents = {item['body']['effectKey']: item for item in self._rows(conn, row['owner_id'], row['id'])
            if (item['body']['originTaskId'], item['body']['originTurnId'], item['body']['runId']) ==
               (task['id'], turn['id'], task['run_id'])}
        if not any(intent['body']['state'] not in TERMINAL for intent in intents.values()):
            return False
        effects = self.store.effects(task['id'])
        if not effects:
            return False
        for effect in effects:
            original = intents.get(effect['effect_key'])
            if original is None or effect['status'] not in {'DONE', 'UNKNOWN'}:
                return False
            try:
                ack = self._proof(original)
            except (HTTPException, PermissionError):
                return False
            if effect['status'] == 'DONE' and effect['result'] != {'outcome': 'completed', 'output': ack}:
                return False
        return True

    async def _release_question_block(self, origin_task, intent):
        service = self.sessions
        owner, session_id = intent['owner_id'], intent['session_id']
        with service.db.read() as conn:
            row = service._row(conn, owner, session_id)
            turn = conn.execute(select(service.turns).where(
                service.turns.c.id == intent['body']['originTurnId'])).mappings().one()
            if (row['body']['stopped'] or intent['body']['state'] in TERMINAL
                    or turn['body'].get('blockReason') not in QUESTION_BLOCKS):
                return False
        observer = self.store.lifecycle_observer
        native_db = service.runs.factory.bridge.native_db
        ticket = native_db.get_job(origin_task['run_id'], strict=True)
        observed = await observer.inspect_subtree(owner, origin_task['id'])
        fact = observed['parent']
        ended = {'completed': {'completed'}, 'failed': {'error', 'failed'}, 'cancelled': {'cancelled'}}
        if (fact.get('nativeStatus') not in ended
                or fact.get('persistedRunStatus') not in ended[fact['nativeStatus']]
                or any(not child['stopped'] for child in observed['children'])):
            return False
        if not ticket or ticket['status'] != fact['nativeStatus']:
            return False
        with service._write() as conn:
            current = self.store.task(origin_task['id'], owner)
            if (any(current[key] != origin_task[key] for key in ('run_id', 'request_id', 'plan_id'))
                    or native_db.get_job(current['run_id'], strict=True) != ticket):
                return False
            row = service._row(conn, owner, session_id)
            intent = conn.execute(select(self.intents).where(
                self.intents.c.question_id == intent['question_id'])).mappings().one()
            turn = conn.execute(select(service.turns).where(
                service.turns.c.id == intent['body']['originTurnId'])).mappings().one()
            if (row['body']['stopped'] or intent['body']['state'] in TERMINAL
                    or turn['body'].get('blockReason') not in QUESTION_BLOCKS):
                return False
            intents = {item['body']['effectKey']: item for item in self._rows(conn, owner, session_id)
                if (item['body']['originTaskId'], item['body']['originTurnId'], item['body']['runId']) ==
                   (current['id'], turn['id'], current['run_id'])}
            effects = self.store.effects(current['id'])
            if not effects:
                return False
            for effect in effects:
                original = intents.get(effect['effect_key'])
                if original is None or effect['status'] != 'DONE' or effect_unresolved(effect, self.store):
                    return False
                ack = self._proof(original)
                if effect['result'] != {'outcome': 'completed', 'output': ack}:
                    return False
            body = {**turn['body'], 'blockReason': None}
            service._save_turn(conn, turn, body)
            if (runtime_custody_held(self.store, current['id'])
                    or self.store.delegation.has_pending_children(current['id'])):
                service._save_turn(conn, turn, turn['body'])
                return False
            self.store.event(current['id'], 'research_question_receipts_reconciled',
                '原生运行已结束；逐条核对原问题保存回执，等待既有执行观察器结算。',
                {'code': turn['body']['blockReason'], 'createsExecution': False})
        return True

    def projection(self, conn, owner, request_id):
        intent = conn.execute(select(self.intents).where(self.intents.c.owner_id == owner,
            self.intents.c.request_id == request_id)).mappings().first()
        if intent is None:
            return {'origin': 'manual'}
        body = intent['body']
        projection = {key: body[key] for key in
            ('originTurnId', 'state', 'code', 'includedTurnId', 'continuedTurnId') if key in body}
        if body['state'] not in TERMINAL and not body.get('code'):
            code = self.events.event(owner, body['eventId'])['errorCode']
            if code:
                projection['code'] = code
        return {'origin': 'agent', 'collaboration': projection}

    def stop(self, conn, owner, session_id):
        reserved_turns = set()
        for intent in self._rows(conn, owner, session_id):
            if intent['body']['state'] not in TERMINAL:
                self._save(conn, intent, state='stopped', code='RESEARCH_SESSION_STOP_REQUESTED')
                if intent['body'].get('continuedTurnId'):
                    reserved_turns.add(intent['body']['continuedTurnId'])
        for turn in self.sessions._turns(conn, session_id):
            if (turn['id'] in reserved_turns and not turn['body']['terminal']
                    and self.sessions._task(owner, turn) is None):
                # Under the admission lock, the revoked intent prevents any later INSERT.
                self.sessions._save_turn(conn, turn, {**turn['body'], 'status': 'canceled', 'terminal': True,
                    'completedAt': now(), 'neverDispatched': True})

    @staticmethod
    def _adopted(turns):
        return {snapshot['questionId']: turn['id'] for turn in turns for snapshot in
            ([turn['body']['assistantReply']] if 'assistantReply' in turn['body'] else [])
            + turn['body'].get('assistantReplies', [])}

    def _ready(self, conn, row, turns):
        ready = []
        adopted = self._adopted(turns)
        by_id = {turn['id']: turn for turn in turns}
        for intent in self._rows(conn, row['owner_id'], row['id']):
            body = intent['body']
            if body['state'] in TERMINAL:
                continue
            if intent['question_id'] in adopted:
                # Inclusion is recorded only by before_model, not reservation.
                if by_id[adopted[intent['question_id']]]['body']['terminal']:
                    self._save(conn, intent, state='blocked', code='RESEARCH_COLLABORATION_CONTINUATION_NOT_INCLUDED')
                continue
            message = self.conversations.messages.read(row['owner_id'], intent['question_id'])
            if message['reply'] is not None:
                if message['reply']['state'] != 'available':
                    self._save(conn, intent, state='blocked', code='RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')
                    continue
                snapshot = self.conversations.adopt(row['owner_id'], row['id'], intent['question_id'])
                intent = self._save(conn, intent, state='pending', code=None)
                ready.append((intent, snapshot))
            elif message['delivery']['state'] == 'rejected':
                self._save(conn, intent, state='blocked', code='RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')
            elif message['delivery']['taskId']:
                try:
                    task = self.store.task(message['delivery']['taskId'], message['recipientId'])
                except HTTPException as error:
                    if error.status_code != 404:
                        raise
                    self._save(conn, intent, code='RESEARCH_ORIGINAL_OUTCOME_UNCONFIRMED')
                else:
                    if task['terminal']:
                        self._save(conn, intent, state='blocked', code='RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')
        return ready

    def receive(self, conn, row, turn):
        turns = self.sessions._turns(conn, row['id'])
        ready = self._ready(conn, row, turns)
        if not ready:
            return turn
        body = deepcopy(turn['body'])
        body['assistantReplies'] = [*body.get('assistantReplies', []), *[snapshot for _, snapshot in ready]]
        prospective = [{**item, 'body': body} if item['id'] == turn['id'] else item for item in turns]
        try:
            self.sessions._capacity(row, prospective)
        except HTTPException as error:
            for intent, _ in ready:
                self._save(conn, intent, state='blocked', code=cast(dict, error.detail)['code'])
            return turn
        self.sessions._save_turn(conn, turn, body)
        return {**turn, 'body': body}

    def included(self, conn, row, turn):
        adopted = self._adopted(self.sessions._turns(conn, row['id']))
        for intent in self._rows(conn, row['owner_id'], row['id']):
            if intent['body']['state'] not in TERMINAL and intent['question_id'] in adopted:
                self._save(conn, intent, state='included', code=None, includedTurnId=turn['id'])

    def _event_intent(self, conn, owner, origin_task, event_id, message_id=None):
        intent = conn.execute(select(self.intents).where(self.intents.c.owner_id == owner,
            self.intents.c.body['eventId'].as_string() == event_id)).mappings().one_or_none()
        if (intent is None or intent['body']['originTaskId'] != origin_task['id']
                or message_id is not None and intent['question_id'] != message_id):
            raise rejected('RESEARCH_COLLABORATION_BINDING_MISMATCH', '原协作事件绑定不一致。')
        return intent

    def validate_admission(self, origin_task, event_id, request_id, plan):
        service = self.sessions
        with service._write() as conn:
            intent = self._event_intent(conn, origin_task['owner_id'], origin_task, event_id)
            row = service._row(conn, intent['owner_id'], intent['session_id'])
            turns = service._turns(conn, row['id'])
            turn_id = intent['body'].get('continuedTurnId')
            turn = turns[-1] if turns else None
            if (row['body']['stopped'] or intent['body']['state'] in TERMINAL
                    or turn is None or turn['id'] != turn_id or turn['body'].get('stopRequestId')):
                raise rejected('RESEARCH_SESSION_STOP_REQUESTED', '协作继续已停止或被后续轮次取代。')
            if ('application-start:' + turn['application_request_id'] != request_id
                    or turn['body'].get('collaborationEventId') != event_id
                    or plan.get('applicationRef') != row['body']['configuration']['applicationRef']
                    or plan.get('inputValues') != service._start(row, turn).inputValues):
                raise rejected('RESEARCH_COLLABORATION_BINDING_MISMATCH', '原协作继续请求绑定不一致。')
            original = self.store.sql('SELECT fingerprint FROM af_plan_requests WHERE owner_id=:owner '
                'AND request_id=:request AND plan_id=:plan', owner=intent['owner_id'], request=request_id, plan=plan['id'])
            if len(original) != 1 or original[0]['fingerprint'] != turn['body']['startFingerprint']:
                raise rejected('RESEARCH_COLLABORATION_BINDING_MISMATCH', '原协作继续准入内容不一致。')
            service._sources(intent['owner_id'], row['body']['sharedSourceIds'])
            service._replies(intent['owner_id'], row['id'], turns)

    def _reserve(self, conn, row, turns, ready, event_id):
        service = self.sessions
        if len(turns) >= row['body']['limits']['maxTurns']:
            raise rejected('RESEARCH_TURN_LIMIT', '会话已达到约定轮数。')
        service._sources(row['owner_id'], row['body']['sharedSourceIds'])
        service._replies(row['owner_id'], row['id'], turns)
        identifier, stamp = str(uuid4()), now()
        origin = next(intent for intent, _ in ready if intent['body']['eventId'] == event_id)
        request_id = 'research-collaboration:' + origin['question_id']
        body = {'requestId': request_id, 'taskId': None, 'runId': None, 'status': 'reserved',
            'createdAt': stamp, 'completedAt': None, 'result': None, 'failure': None, 'terminal': False,
            'blockReason': None, 'messages': [], 'lastAttempt': 0, 'dispatchStarted': False,
            'events': [], 'toolResults': [], 'assistantReplies': [snapshot for _, snapshot in ready],
            'continuation': {'questionIds': [intent['question_id'] for intent, _ in ready]},
            'collaborationEventId': event_id}
        turn = {'id': identifier, 'session_id': row['id'], 'owner_id': row['owner_id'],
            'application_request_id': request_id, 'sequence': len(turns) + 1, 'body': body}
        context, compaction = session_context.prepare(row, turns, prospective=turn)
        body['context'] = context
        if compaction:
            body['compaction'] = compaction
        body['startFingerprint'] = digest(service._start(row, turn).model_dump(exclude={'interfaceVersion', 'requestId'}))
        conn.execute(service.turns.insert().values(**turn))
        for intent, _ in ready:
            self._save(conn, intent, continuedTurnId=identifier)
        service._command(conn, row['owner_id'], request_id,
            digest({'action': 'collaboration', 'eventId': event_id, 'questionIds': body['continuation']['questionIds']}),
            'collaboration', row['id'], identifier)
        service._save_session(conn, row, row['body'])
        return turn

    async def deliver(self, origin_task, event_id, message_id):
        service, owner = self.sessions, origin_task['owner_id']
        with service._write() as conn:
            intent = self._event_intent(conn, owner, origin_task, event_id, message_id)
            self._reconcile_receipt(intent)
            identifier = intent['session_id']
        if await self._release_question_block(origin_task, intent):
            return False
        message = self.conversations.messages.read(owner, message_id)
        if message['reply'] is None and message['delivery']['taskId']:
            try:
                task = self.store.task(message['delivery']['taskId'], message['recipientId'])
                if not task['terminal']:
                    await service.runs.factory.detail(task)
            except HTTPException:
                pass  # Failed observation does not establish a terminal outcome or permit replay.
        await service._refresh(owner, identifier)
        start = None
        with service._write() as conn:
            intent = self._event_intent(conn, owner, origin_task, event_id, message_id)
            row, turns = service._row(conn, owner, identifier), service._turns(conn, identifier)
            if row['body']['stopped']:
                self.stop(conn, owner, identifier)
                return True
            if intent['body']['state'] in TERMINAL:
                return True
            ready = self._ready(conn, row, turns)
            intent = self._event_intent(conn, owner, origin_task, event_id, message_id)
            if intent['body']['state'] in TERMINAL:
                return True
            if turns and not service._safe(owner, turns[-1]):
                latest = turns[-1]
                if (latest['body'].get('collaborationEventId') == event_id
                        and not latest['body']['terminal'] and service._task(owner, latest) is None):
                    start = service._start(row, latest)
                else:
                    return False
            elif ready and any(pending['question_id'] == message_id for pending, _ in ready):
                try:
                    turn = self._reserve(conn, row, turns, ready, event_id)
                except HTTPException as error:
                    for pending, _ in ready:
                        self._save(conn, pending, state='blocked', code=cast(dict, error.detail)['code'])
                    return True
                start = service._start(row, turn)
            else:
                updated = self._event_intent(conn, owner, origin_task, event_id, message_id)
                return updated['body']['state'] in TERMINAL
            target = conn.execute(select(service.turns).where(service.turns.c.id == start.inputValues['turnId'])).mappings().one()
            service._save_turn(conn, target, {**target['body'], 'dispatchStarted': True})
        if start is not None:
            try:
                await service.runs.start(owner, start, private_event_id=event_id)
            except HTTPException as error:
                # The original admission may exist. Only its request is reconciled on the next event pass.
                detail = error.detail
                code = str(cast(dict, detail).get('code') if isinstance(detail, dict) else detail).split(':', 1)[0]
                if not code.isupper() or not code.replace('_', '').isalnum():
                    code = 'RESEARCH_COLLABORATION_ADMISSION_UNCONFIRMED'
                with service._write() as conn:
                    for pending in self._rows(conn, owner, identifier):
                        if (pending['body'].get('continuedTurnId') == start.inputValues['turnId']
                                and pending['body']['state'] not in TERMINAL):
                            self._save(conn, pending, code=code)
                    target = conn.execute(select(service.turns).where(
                        service.turns.c.id == start.inputValues['turnId'])).mappings().one()
                    if not target['body']['terminal']:
                        service._save_turn(conn, target, {**target['body'], 'status': 'unknown',
                            'failure': '尚未确认自动继续的原提交结果；保留原请求核对，不另建轮次。'})
                return False
        return False

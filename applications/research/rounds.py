"""Research decisions and evidence over original native roots and custody."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, UniqueConstraint, inspect, or_, select, text

from agent_factory.application_content import ContentPublication, ContentSource
from agent_factory.application_interface import ApplicationStart
from agent_factory.application_runs import factory_request_id
from agent_factory.assistant_endpoints import EndpointConfiguration
from agent_factory.assistant_events import ContentEvent, EventSubscription
from agent_factory.delegated_operations import DELEGATED_OPERATION_PIN
from agent_factory.store import digest, now
from agent_factory.workflow_control import WorkflowCommand
from .projects import Agreement, reject


class ResearchRounds:
    def __init__(self, legacy_runs, *, events, endpoints, custody, control, pin):
        self.legacy = legacy_runs
        self.projects, self.db = legacy_runs.projects, legacy_runs.projects.db
        self.events, self.endpoints, self.custody, self.control = events, endpoints, custody, control
        self.scopes, self.content, self.pin = legacy_runs.scopes, legacy_runs.records.content, dict(pin)
        metadata = MetaData()
        self.rounds = Table('research_rounds', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('project_id', String, nullable=False), Column('goal_version', Integer, nullable=False),
            Column('scope_id', String, nullable=False), Column('allocation_id', String, nullable=False, unique=True),
            Column('factory_request', String, nullable=False), Column('request', JSON),
            Column('task_id', String, unique=True), Column('delivery_id', String, unique=True),
            Column('predecessor_id', String), Column('endpoint_id', String, nullable=False),
            Column('decision', JSON), Column('terminal', JSON), Column('terminal_record', String),
            Column('continuations', JSON, nullable=False), Column('created_at', String, nullable=False),
            UniqueConstraint('owner_id', 'factory_request'))
        metadata.create_all(self.db.store.engine)
        self._migrate_attempts()

    def _migrate_attempts(self):
        # These two old one-root constraints are application schema, not core state.
        with self.db.write() as conn:
            for table, unique_column, additions in (
                (self.legacy.experiments, 'project_id', ('round_id',)),
                (self.legacy.attempts, 'experiment_id', ('round_id', 'operation_id')),
            ):
                constraints = [c for c in inspect(conn).get_unique_constraints(table.name)
                               if c['column_names'] == [unique_column]]
                if constraints and conn.dialect.name == 'sqlite':
                    replacement = table.to_metadata(MetaData(), name=table.name + '_multiple')
                    for constraint in list(replacement.constraints):
                        if isinstance(constraint, UniqueConstraint) and list(constraint.columns.keys()) == [unique_column]:
                            replacement.constraints.remove(constraint)
                    replacement.create(conn)
                    columns = list(table.columns.keys())
                    conn.execute(replacement.insert().from_select(columns, select(table)))
                    table.drop(conn)
                    conn.execute(text(f'ALTER TABLE {replacement.name} RENAME TO {table.name}'))
                elif constraints:
                    quote = conn.dialect.identifier_preparer.quote
                    for constraint in constraints:
                        conn.execute(text(f'ALTER TABLE {table.name} DROP CONSTRAINT {quote(constraint["name"])}'))
                existing = {c['name'] for c in inspect(conn).get_columns(table.name)}
                for name in additions:
                    if name not in existing:
                        conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {name} VARCHAR'))
                    if name not in table.c:
                        table.append_column(Column(name, String))

    def supports(self, execution):
        if execution is None:
            return False
        application = self.legacy.applications.require_current(execution['applicationRef'])
        return application['modes'].get(execution['mode'], {}).get('nativeComponent') == self.pin

    def _goal(self, conn, project_id, version):
        row = conn.execute(select(self.projects.goals).where(self.projects.goals.c.project_id == project_id,
            self.projects.goals.c.version == version)).mappings().one()
        return Agreement.model_validate(row['agreement'])

    def availability(self, conn, project):
        if project['state'] != 'ready':
            return {'available': False, 'reason': 'RESEARCH_PROJECT_ENDED' if project['state'] == 'ended'
                    else 'RESEARCH_CONFIRMED_GOAL_REQUIRED'}
        agreement = self._goal(conn, project['id'], project['goal_version'])
        if not self.supports(agreement.model_dump()['execution']):
            return self.legacy.availability(conn, project)
        assert agreement.execution is not None
        if agreement.execution.deadline <= time.time():
            return {'available': False, 'reason': 'LOCAL_BUDGET_EXPIRED'}
        rows = conn.execute(select(self.rounds).where(self.rounds.c.project_id == project['id'])).mappings().all()
        reason = None
        if rows and (any(row['terminal'] is None for row in rows)
                     or max(row['goal_version'] for row in rows) == project['goal_version']):
            reason = 'RESEARCH_ORIGINAL_ATTEMPT_REQUIRED'
        return {'available': reason is None, 'reason': reason}

    def require_same_commitment(self, conn, project_id, agreement):
        self.legacy.require_same_commitment(conn, project_id, agreement)
        first = conn.execute(select(self.rounds).where(self.rounds.c.project_id == project_id)
                             .order_by(self.rounds.c.created_at).limit(1)).mappings().first()
        if first and agreement.execution != self._goal(conn, project_id, first['goal_version']).execution:
            reject('RESEARCH_EXECUTION_FROZEN', '修订不能替换原研究执行配置')

    def stop(self, conn, owner, project_id):
        self.legacy.stop(conn, owner, project_id)

    @contextmanager
    def _write(self):
        with self.db.store.transaction() as conn:
            self.scopes.admission_lock(conn)
            with self.db.write(), self.content.db.write(), self.events.db.write(), self.endpoints.db.write():
                yield conn

    def _publish(self, owner, identifier, revision, content):
        return self.content.publish(owner, ContentPublication(source=ContentSource(
            application='research', record=identifier, revision=revision), content=content, visibility='team'),
            'research-record:' + identifier + ':' + revision)['id']

    def _prepare(self, owner, project_id, body):
        self.projects.auth.require_member(owner)
        fingerprint = digest({'action': 'round.start', 'project': project_id, **body.model_dump(exclude={'requestId'})})
        with self._write() as conn:
            project = self.projects._owned(conn, owner, project_id)
            prior = self.db.old(conn, self.projects.commands, owner, body.requestId, fingerprint)
            if prior is not None:
                return prior
            if project['state'] != 'ready' or project['goal_version'] != body.expectedVersion:
                reject('RESEARCH_CONFIRMED_GOAL_REQUIRED', '请确认当前研究约定')
            agreement = self._goal(conn, project_id, body.expectedVersion)
            execution = agreement.execution
            if execution is None or not self.supports(execution.model_dump()):
                reject('RESEARCH_NATIVE_COMPONENT_REQUIRED', '自主研究需要固定研究组件')
            existing = conn.execute(select(self.rounds).where(self.rounds.c.project_id == project_id)
                                    .order_by(self.rounds.c.created_at)).mappings().all()
            if existing:
                return self._resume(conn, owner, project, body, agreement, existing, fingerprint)
            if conn.execute(select(self.legacy.experiments.c.id).where(
                    self.legacy.experiments.c.project_id == project_id).limit(1)).first():
                reject('RESEARCH_ORIGINAL_ATTEMPT_REQUIRED', '旧实验保留原身份，不自动转换为研究轮次')
            identifier, scope_id = str(uuid4()), str(uuid4())
            endpoint = self.endpoints.configure(owner, EndpointConfiguration(name='Research ' + project_id,
                **execution.model_dump(include={'applicationRef', 'mode', 'materialChoices', 'connectionRefs'})),
                'research-endpoint:' + identifier)
            native = ApplicationStart(requestId='research:' + identifier, application=execution.applicationRef.id,
                applicationRef=execution.applicationRef.model_dump(), mode=execution.mode, goal=agreement.execution_goal(),
                inputValues=self.legacy._input_values(execution, agreement.execution_goal()),
                materialChoices={k: v.model_dump() for k, v in execution.materialChoices.items()},
                connectionRefs=execution.connectionRefs)
            commitment = {'budget': agreement.budget.model_dump(), 'deadline': execution.deadline}
            self.scopes.create_scope(owner, scope_id, digest(commitment), commitment['budget'], execution.deadline)
            conn.execute(self.legacy.commitments.insert().values(project_id=project_id, scope_id=scope_id, commitment=commitment))
            if agreement.budget.rounds >= 2:
                self.events.configure(owner, EventSubscription(endpointId=endpoint['id'], namespace='research',
                    eventType='round.continue', scopeId=scope_id, caps=execution.perRoundCaps.model_dump(),
                    deadline=execution.deadline, maxDepth=agreement.budget.rounds - 2, maxCandidates=1),
                    'research-subscription:' + identifier)
            self.scopes.allocate(conn, owner, scope_id, identifier, digest(native.model_dump()), execution.perRoundCaps.model_dump())
            self.scopes.bind_request(conn, owner, identifier, factory_request_id(native.requestId))
            conn.execute(self.rounds.insert().values(id=identifier, owner_id=owner, project_id=project_id,
                goal_version=body.expectedVersion, scope_id=scope_id, allocation_id=identifier,
                factory_request=factory_request_id(native.requestId), request=native.model_dump(),
                endpoint_id=endpoint['id'], continuations=[], created_at=now()))
            result = {'projectId': project_id, 'goalVersion': body.expectedVersion, 'roundId': identifier,
                'scopeId': scope_id, 'allocationId': identifier, 'request': native.model_dump()}
            return self.db.record(conn, self.projects.commands, owner, body.requestId, fingerprint, 'research.round.start', result)

    async def start(self, owner, project_id, body):
        with self.db.read() as conn:
            project = self.projects._owned(conn, owner, project_id)
            agreement = self._goal(conn, project_id, project['goal_version']) if project['goal_version'] else None
        if agreement is None or not self.supports(agreement.model_dump()['execution']):
            return await self.legacy.start(owner, project_id, body)
        intent = await asyncio.to_thread(self._prepare, owner, project_id, body)
        if 'request' not in intent:
            return intent
        receipt = await asyncio.to_thread(self.legacy._receipt, owner, intent['request']['requestId'], intent['scopeId'], intent['allocationId'])
        if receipt is None or receipt['taskId'] is None:
            project = await asyncio.to_thread(self.projects.read, owner, project_id)
            if project['state'] == 'ended':
                reject('RESEARCH_PROJECT_ENDED', '项目已结束')
            await self.legacy.runs.start(owner, ApplicationStart.model_validate(intent['request']), allocation_id=intent['allocationId'])
            receipt = await asyncio.to_thread(self.legacy._receipt, owner, intent['request']['requestId'], intent['scopeId'], intent['allocationId'])
        return {k: v for k, v in intent.items() if k != 'request'} | {'execution': receipt}

    def _bound(self, conn, ctx):
        owner, task_id = ctx.user_id, ctx.session_id
        self.projects.auth.require_member(owner)
        request = ctx.session_state['factory_envelope']['request_id']
        receipt = self.legacy.runs.request(owner, request.removeprefix('application-start:'))
        if receipt['taskId'] != task_id or receipt['runId'] != ctx.run_id:
            reject('RESEARCH_ORIGINAL_RUN_REQUIRED', '研究步骤必须属于原任务')
        row = conn.execute(select(self.rounds).where(self.rounds.c.owner_id == owner,
            self.rounds.c.factory_request == request)).mappings().first()
        if row is None:
            delivery = self.events.delivery_for_task(owner, task_id)
            if delivery is None:
                reject('RESEARCH_ORIGINAL_INTENT_REQUIRED', '普通消息不能启动研究实验')
            publication = self.content.read(owner, delivery['contentId'])
            prior = conn.execute(select(self.rounds).where(self.rounds.c.owner_id == owner,
                self.rounds.c.scope_id == delivery['scopeId'])).mappings().all()
            matches = [(r, t) for r in prior for t in r['continuations']
                       if t['eventId'] == delivery['eventId'] and t['contentId'] == delivery['contentId']]
            if len(matches) != 1 or publication['ownerId'] != owner:
                reject('RESEARCH_ORIGINAL_INTENT_REQUIRED', '缺少原研究后继事件')
            parent, trigger = matches[0]
            project = self.projects._owned(conn, owner, parent['project_id'])
            if project['state'] != 'ready' or project['goal_version'] != trigger['goalVersion']:
                reject('RESEARCH_GOAL_VERSION_CONFLICT', '旧后继事件不能启动已修订目标')
            identifier = str(uuid4())
            conn.execute(self.rounds.insert().values(id=identifier, owner_id=owner, project_id=parent['project_id'],
                goal_version=trigger['goalVersion'], scope_id=delivery['scopeId'], allocation_id=delivery['allocationId'],
                factory_request=request, task_id=task_id, delivery_id=delivery['deliveryId'], predecessor_id=parent['id'],
                endpoint_id=parent['endpoint_id'], continuations=[], created_at=now()))
            row = conn.execute(select(self.rounds).where(self.rounds.c.id == identifier)).mappings().one()
        elif row['task_id'] is None:
            scope = self.scopes.inspect(owner, row['scope_id'])
            if not any(a['allocationId'] == row['allocation_id'] and a['taskId'] == task_id for a in scope['allocations']):
                reject('RESEARCH_ALLOCATION_TASK_MISMATCH', '原分配与任务不匹配')
            conn.execute(self.rounds.update().where(self.rounds.c.id == row['id']).values(task_id=task_id))
            row = dict(row) | {'task_id': task_id}
        elif row['task_id'] != task_id:
            reject('RESEARCH_ORIGINAL_RUN_REQUIRED', '研究轮次已有原任务')
        return dict(row)

    def context(self, run_context):
        with self._write() as conn:
            row = self._bound(conn, run_context)
            agreement = self._goal(conn, row['project_id'], row['goal_version'])
            sources = []
            previous_observation = None
            if row['predecessor_id']:
                prior = conn.execute(select(self.rounds).where(self.rounds.c.id == row['predecessor_id'])).mappings().one()
                if prior['terminal_record']:
                    sources.append(self.content.read(row['owner_id'], prior['terminal_record']))
                attempt = conn.execute(select(self.legacy.attempts).where(
                    self.legacy.attempts.c.round_id == prior['id'])).mappings().first()
                if attempt and attempt['operation_id']:
                    original = self.custody.read(row['owner_id'], attempt['operation_id'])
                    if original['taskId'] != prior['task_id'] or not original['closed']:
                        reject('RESEARCH_ORIGINAL_RESULT_REQUIRED', '前轮原操作尚未确认结束')
                    previous_observation = deepcopy(original['observation'])
            return {'roundId': row['id'], 'projectId': row['project_id'], 'goalVersion': row['goal_version'],
                'agreement': agreement.model_dump(exclude={'execution', 'resourceRefs'}),
                'scope': self.scopes.inspect(row['owner_id'], row['scope_id']), 'sources': sources,
                'previousObservation': previous_observation,
                'evidenceIds': [item['id'] for item in sources]}

    async def launch(self, run_context, decision):
        def prepare():
            with self._write() as conn:
                row = self._bound(conn, run_context)
                project = self.projects._owned(conn, row['owner_id'], row['project_id'])
                if project['state'] == 'ended':
                    reject('RESEARCH_PROJECT_ENDED', '项目已结束')
                old = conn.execute(select(self.legacy.attempts).where(self.legacy.attempts.c.round_id == row['id'])).mappings().first()
                if old:
                    if old['request'] != decision.model_dump():
                        reject('RESEARCH_DECISION_CONFLICT', '原轮次不能替换实验意图')
                    return row, dict(old)
                experiment_id, attempt_id = str(uuid4()), str(uuid4())
                conn.execute(self.legacy.experiments.insert().values(id=experiment_id, project_id=row['project_id'],
                    goal_version=row['goal_version'], hypothesis=decision.hypothesis,
                    conditions={'description': decision.conditions}, round_id=row['id'], created_at=now()))
                conn.execute(self.legacy.attempts.insert().values(id=attempt_id, experiment_id=experiment_id,
                    allocation_id=row['allocation_id'], request=decision.model_dump(), round_id=row['id']))
                self._publish(row['owner_id'], attempt_id, 'start', {'kind': 'research.experiment.start',
                    'state': 'pending_admission', 'projectId': row['project_id'], 'goalVersion': row['goal_version'],
                    'roundId': row['id'], 'experimentId': experiment_id, 'attemptId': attempt_id,
                    'hypothesis': decision.hypothesis, 'conditions': decision.conditions})
                return row, {'id': attempt_id, 'operation_id': None}
        row, attempt = await asyncio.to_thread(prepare)
        operation = await self.custody.start(run_context, 'research_launch', 'experiment',
            DELEGATED_OPERATION_PIN, {'goal': decision.goal, 'mode': 'experiment'})
        with self.db.write() as conn:
            conn.execute(self.legacy.attempts.update().where(self.legacy.attempts.c.id == attempt['id']).values(operation_id=operation['id']))
        return operation

    def results(self, run_context):
        with self._write() as conn:
            row = self._bound(conn, run_context)
            attempt = conn.execute(select(self.legacy.attempts).where(self.legacy.attempts.c.round_id == row['id'])).mappings().one()
            operation = self.custody.read(row['owner_id'], attempt['operation_id'])
            if operation['taskId'] != row['task_id'] or operation['nativeRunId'] != run_context.run_id or not operation['closed']:
                reject('RESEARCH_ORIGINAL_RESULT_REQUIRED', '原操作尚未确认结束')
            agreement = self._goal(conn, row['project_id'], row['goal_version'])
            return {'agreement': agreement.model_dump(exclude={'execution', 'resourceRefs'}),
                'evidenceIds': [operation['id']], 'operation': deepcopy(operation['observation'])}

    def record_decision(self, run_context, decision):
        with self._write() as conn:
            row = self._bound(conn, run_context)
            valid = set()
            if row['predecessor_id']:
                prior = conn.execute(select(self.rounds).where(self.rounds.c.id == row['predecessor_id'])).mappings().one()
                if prior['terminal_record']:
                    valid.add(prior['terminal_record'])
            attempt = conn.execute(select(self.legacy.attempts).where(self.legacy.attempts.c.round_id == row['id'])).mappings().first()
            if attempt:
                operation = self.custody.read(row['owner_id'], attempt['operation_id'])
                if not operation['closed']:
                    reject('RESEARCH_ORIGINAL_RESULT_REQUIRED', '原操作结果未知')
                valid.add(operation['id'])
                if operation['observation']['state'] != 'COMPLETED' and decision.get('outcome') == 'met':
                    reject('RESEARCH_TECHNICAL_FAILURE_NOT_SUCCESS', '技术失败不能判为科研达标')
            if set(decision['evidenceIds']) - valid:
                reject('RESEARCH_EVIDENCE_MISMATCH', '决定引用必须来自本轮原证据')
            if row['decision'] is not None and row['decision'] != decision:
                reject('RESEARCH_DECISION_CONFLICT', '原轮次决定不可替换')
            conn.execute(self.rounds.update().where(self.rounds.c.id == row['id']).values(decision=decision))
            return {'roundId': row['id'], 'decision': deepcopy(decision), 'verificationStatus': 'agent_analysis'}

    def _remaining(self, owner, row, agreement):
        scope = self.scopes.inspect(owner, row['scope_id'])
        caps = agreement.execution.perRoundCaps
        if scope['state'] != 'ACTIVE':
            return 'LOCAL_BUDGET_CLOSED_OR_EXPIRED'
        if time.time() >= scope['deadline']:
            return 'LOCAL_BUDGET_EXPIRED'
        if (scope['allocatedRounds'] >= scope['caps']['rounds'] or
                scope['heldToolCalls'] + scope['settledToolCalls'] + caps.toolCalls > scope['caps']['toolCalls']):
            return 'LOCAL_BUDGET_EXHAUSTED'
        usage = scope['usage']
        if usage and (usage['held_tokens'] + usage['settled_tokens'] + caps.tokenLimit > scope['caps']['tokenLimit'] or
                      usage['held_amount'] + usage['settled_amount'] + caps.amountMicros > scope['caps']['amountMicros']):
            return 'LOCAL_BUDGET_EXHAUSTED'
        return None

    def _emit(self, conn, row, agreement, content_id, version):
        event = self.events.emit(conn, row['owner_id'], ContentEvent(namespace='research', eventType='round.continue',
            contentId=content_id, candidates=[row['endpoint_id']], deadline=agreement.execution.deadline),
            'research-continue:' + row['id'] + ':' + str(version),
            parent_delivery_id=row['delivery_id'], task_id=row['task_id'] if row['delivery_id'] else None)
        trigger = {'eventId': event['id'], 'contentId': content_id, 'goalVersion': version}
        conn.execute(self.rounds.update().where(self.rounds.c.id == row['id']).values(
            continuations=[*row['continuations'], trigger]))
        return trigger

    def _resume(self, conn, owner, project, body, agreement, existing, fingerprint):
        if any(row['terminal'] is None for row in existing):
            reject('RESEARCH_ORIGINAL_ATTEMPT_REQUIRED', '原轮次尚未确认结束')
        tail = existing[-1]
        if body.expectedVersion <= max(row['goal_version'] for row in existing):
            reject('RESEARCH_ORIGINAL_ATTEMPT_REQUIRED', '同一目标仅沿原后继事件继续')
        for row in existing:
            for trigger in row['continuations']:
                if trigger['goalVersion'] == body.expectedVersion:
                    result = {'projectId': project['id'], 'goalVersion': body.expectedVersion, **trigger}
                    return self.db.record(conn, self.projects.commands, owner, body.requestId, fingerprint, 'research.round.resume', result)
        reason = self._remaining(owner, tail, agreement)
        if reason:
            reject(reason, '原项目承诺不再允许下一轮')
        content_id = self._publish(owner, tail['id'], 'goal-' + str(body.expectedVersion), {
            'kind': 'research.goal.resume', 'projectId': project['id'], 'goalVersion': body.expectedVersion,
            'roundId': tail['id'], 'previousRecordId': tail['terminal_record'],
            'objective': agreement.objective, 'evaluation': agreement.evaluation, 'stopConditions': agreement.stopConditions})
        trigger = self._emit(conn, tail, agreement, content_id, body.expectedVersion)
        result = {'projectId': project['id'], 'goalVersion': body.expectedVersion, **trigger}
        return self.db.record(conn, self.projects.commands, owner, body.requestId, fingerprint, 'research.round.resume', result)

    @contextmanager
    def finalization_context(self, conn, task):
        with self.db.write(), self.content.db.write(), self.events.db.write():
            yield lambda payload: self._finalize(conn, task, payload)

    def _finalize(self, conn, task, payload):
        row = conn.execute(select(self.rounds).where(self.rounds.c.owner_id == task['owner_id'],
            or_(self.rounds.c.task_id == task['id'], self.rounds.c.factory_request == task['request_id']))).mappings().first()
        if row is None:
            original = conn.execute(select(self.projects.commands.c.request_id).where(
                self.projects.commands.c.actor_id == task['owner_id'],
                self.projects.commands.c.action == 'research.round.start',
                self.projects.commands.c.result['request']['requestId'].as_string() ==
                    task['request_id'].removeprefix('application-start:'))).first()
            if original is not None:
                reject('RESEARCH_ORIGINAL_INTENT_MISSING', '原研究意图已缺失，不能确认完成')
            return
        if row['terminal'] is not None:
            return
        row = dict(row) | {'task_id': task['id']}
        project = self.projects._owned(conn, task['owner_id'], row['project_id'])
        agreement = self._goal(conn, row['project_id'], row['goal_version'])
        group = [{'taskId': item['id'], 'runId': item.get('run_id'),
                  'status': item['body']['stoppedStatus']} for item in payload['group']]
        succeeded = all(item['status'] == 'completed' for item in group)
        terminal = {'taskId': task['id'], 'runId': task.get('run_id'), 'decision': row['decision'],
                    'runtime': deepcopy(group), 'verificationStatus': 'unverified', 'sharing': 'published', 'continuationBlocked': None}
        try:
            self.projects.auth.require_member(task['owner_id'])
        except HTTPException as error:
            if error.status_code not in {401, 403, 404}:
                raise
            terminal['sharing'] = 'authorization_withdrawn'
            terminal['continuationBlocked'] = 'AUTHORIZATION_WITHDRAWN'
        content_id = None
        if terminal['sharing'] == 'published':
            evidence = None
            attempt = conn.execute(select(self.legacy.attempts).where(
                self.legacy.attempts.c.round_id == row['id'])).mappings().first()
            if attempt:
                experiment = conn.execute(select(self.legacy.experiments).where(
                    self.legacy.experiments.c.id == attempt['experiment_id'])).mappings().one()
                evidence = {'hypothesis': experiment['hypothesis'], 'conditions': experiment['conditions'],
                            'operation': None}
                if attempt['operation_id']:
                    operation = self.custody.read(task['owner_id'], attempt['operation_id'])
                    evidence['operation'] = {'id': operation['id'], 'state': operation['observation']['state'],
                                             'allStopped': operation['closed']}
            content_id = self._publish(task['owner_id'], row['id'], 'terminal', {
                'kind': 'research.round.terminal', 'projectId': row['project_id'], 'goalVersion': row['goal_version'],
                'roundId': row['id'], 'taskId': task['id'], 'decision': row['decision'],
                'runtime': group, 'experiment': evidence,
                'evidenceLevel': 'agent_analysis' if row['decision'] else 'runtime_fact'})
            if row['decision'] and row['decision']['action'] == 'continue':
                reason = ('RESEARCH_PROJECT_ENDED' if project['state'] == 'ended' else
                          'RESEARCH_GOAL_VERSION_CONFLICT' if project['state'] != 'ready' or project['goal_version'] != row['goal_version']
                          else self._remaining(task['owner_id'], row, agreement))
                if reason is None and succeeded:
                    self._emit(conn, row, agreement, content_id, row['goal_version'])
                else:
                    terminal['continuationBlocked'] = reason or 'RESEARCH_NATIVE_FAILED'
        conn.execute(self.rounds.update().where(self.rounds.c.id == row['id']).values(
            task_id=task['id'], terminal=terminal, terminal_record=content_id))
        if (succeeded and row['decision'] and row['decision']['action'] == 'stop' and project['state'] == 'ready'
                and project['goal_version'] == row['goal_version']):
            conn.execute(self.projects.projects.update().where(self.projects.projects.c.id == row['project_id']).values(
                state='ended', ending={'outcome': row['decision']['outcome'], 'reason': row['decision']['reason'],
                    'endedAt': now(), 'goalVersion': row['goal_version'], 'resourceCleanup': 'stopped',
                    'verificationStatus': 'agent_analysis'}))

    async def observe_waits(self, observer, task):
        with self.db.read() as conn:
            row = conn.execute(select(self.rounds).where(self.rounds.c.task_id == task['id'])).mappings().first()
            if row is None:
                return
            attempt = conn.execute(select(self.legacy.attempts).where(self.legacy.attempts.c.round_id == row['id'])).mappings().first()
        if not attempt or not attempt['operation_id']:
            return
        try:
            operation = self.custody.read(task['owner_id'], attempt['operation_id'])
            if not operation['closed']:
                observe = self.custody.lookup if operation['handle'] is None else self.custody.inspect
                operation = await observe(task['owner_id'], operation['id'])
        except HTTPException as error:
            if error.status_code in {401, 403}:
                return  # Core still owns revoked-operation cleanup.
            raise
        if not operation['closed']:
            return
        snapshot = await self.control.snapshot(task['owner_id'], task['id'])
        view = snapshot.get('workflow')
        if not view or view['status'].lower() != 'paused' or not any(r['kind'] == 'external' for r in view['requirements']):
            return
        command_id = 'research-reconcile:' + operation['id']
        try:
            await self.control.receipt(task['owner_id'], task['id'], command_id)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            await self.control.submit(task['owner_id'], task['id'], WorkflowCommand(commandId=command_id,
                action='reconcile', version=view['version'], operationId=operation['id']))

    def list(self, owner, project_id):
        self.projects.auth.require_member(owner)
        with self.db.read() as conn:
            self.projects._owned(conn, owner, project_id)
            rows = conn.execute(select(self.rounds).where(self.rounds.c.project_id == project_id)
                                .order_by(self.rounds.c.created_at)).mappings().all()
            if not rows:
                return {**self.legacy.list(owner, project_id), 'rounds': []}
            experiments = conn.execute(select(self.legacy.experiments).where(self.legacy.experiments.c.project_id == project_id)).mappings().all()
            items = []
            for experiment in experiments:
                attempts = conn.execute(select(self.legacy.attempts).where(self.legacy.attempts.c.experiment_id == experiment['id'])).mappings().all()
                items.append({'id': experiment['id'], 'projectId': project_id, 'goalVersion': experiment['goal_version'],
                    'hypothesis': experiment['hypothesis'], 'conditions': deepcopy(experiment['conditions']),
                    'attempts': [{'id': a['id'], 'operationId': a['operation_id'],
                                  'operation': self.custody.read(owner, a['operation_id']) if a['operation_id'] else None} for a in attempts]})
            return {'items': items, 'rounds': [{'id': row['id'], 'goalVersion': row['goal_version'],
                'scopeId': row['scope_id'], 'allocationId': row['allocation_id'], 'taskId': row['task_id'],
                'deliveryId': row['delivery_id'], 'decision': deepcopy(row['decision']), 'terminal': deepcopy(row['terminal']),
                'terminalRecordId': row['terminal_record'], 'continuations': [
                    {**trigger, 'delivery': self.events.event(owner, trigger['eventId'])}
                    for trigger in row['continuations']]} for row in rows]}

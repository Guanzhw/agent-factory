"""Persist research intent; core alone admits and recovers native execution."""
import asyncio
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, select

from agent_factory.application_interface import ApplicationStart
from agent_factory.input_schema import validate_input_values
from agent_factory.store import digest
from .projects import ProjectCommand, reject


class ResearchRuns:
    def __init__(self, projects, application_runs, scopes, applications, records):
        self.projects, self.runs, self.scopes = projects, application_runs, scopes
        self.applications, self.records = applications, records
        metadata = MetaData()
        self.commitments = Table('research_execution_commitments', metadata,
            Column('project_id', String, primary_key=True), Column('scope_id', String, nullable=False),
            Column('commitment', JSON, nullable=False))
        self.experiments = Table('research_experiments', metadata,
            Column('id', String, primary_key=True), Column('project_id', String, nullable=False, unique=True),
            Column('goal_version', Integer, nullable=False), Column('hypothesis', String, nullable=False),
            Column('conditions', JSON, nullable=False), Column('created_at', String, nullable=False))
        self.attempts = Table('research_attempts', metadata,
            Column('id', String, primary_key=True), Column('experiment_id', String, nullable=False, unique=True),
            Column('allocation_id', String, nullable=False), Column('request', JSON, nullable=False))
        metadata.create_all(projects.db.store.engine)
        projects.execution = self

    def availability(self, conn, project):
        reason = 'RESEARCH_NATIVE_COMPONENT_REQUIRED'
        if project['state'] == 'ended':
            reason = 'RESEARCH_PROJECT_ENDED'
        elif project['state'] != 'ready':
            reason = 'RESEARCH_CONFIRMED_GOAL_REQUIRED'
        elif conn.execute(select(self.commitments.c.project_id).where(
                self.commitments.c.project_id == project['id'])).first():
            reason = 'RESEARCH_ORIGINAL_ATTEMPT_REQUIRED'
        return {'available': False, 'reason': reason}

    def require_same_commitment(self, conn, project_id, agreement):
        old = conn.execute(select(self.commitments).where(self.commitments.c.project_id == project_id)).mappings().first()
        if old and (agreement.execution is None or old['commitment'] != {
                'budget': agreement.budget.model_dump(), 'deadline': agreement.execution.deadline}):
            reject('RESEARCH_COMMITMENT_FROZEN', '目标修订不能重置项目预算或延长截止时间')

    def stop(self, conn, owner, project_id):
        row = conn.execute(select(self.commitments).where(self.commitments.c.project_id == project_id)).mappings().first()
        if row:
            self.scopes.cancel(owner, row['scope_id'])

    def _input_values(self, execution, text):
        application = self.applications.require_current(execution.applicationRef.model_dump())
        mode = application['modes'].get(execution.mode)
        if mode is None:
            reject('RESEARCH_MODE_NOT_FOUND', '所选执行模式不存在', 422)
        self.applications.chosen_refs(mode, {key: value.model_dump() for key, value in execution.materialChoices.items()})
        schema = mode.get('inputSchema')
        if schema is None:
            return None
        if schema['properties'].get('goal', {}).get('type') != 'string' or set(schema.get('required', [])) - {'goal'}:
            reject('RESEARCH_TEXT_INPUT_INCOMPATIBLE', '所选执行模式不能接收完整研究约定文本', 422)
        try:
            return validate_input_values(schema, {'goal': text})
        except ValueError:
            reject('RESEARCH_TEXT_INPUT_INCOMPATIBLE', '完整研究约定不符合所选模式的输入约束', 422)

    def original_intent(self, conn, owner, project_id, body):
        action = conn.execute(select(self.projects.commands.c.action).where(
            self.projects.commands.c.actor_id == owner,
            self.projects.commands.c.request_id == body.requestId)).scalar_one_or_none()
        if action is None:
            return None
        if action not in {'research.start', 'research.round.start', 'research.round.resume'}:
            raise HTTPException(409, 'IDEMPOTENCY_CONFLICT: governed intent changed')
        fingerprint = digest({'action': 'start' if action == 'research.start' else 'round.start',
            'project': project_id, **body.model_dump(exclude={'requestId'})})
        return self.projects.db.old(conn, self.projects.commands, owner, body.requestId, fingerprint)

    def _prepare(self, owner, project_id, body):
        self.projects.auth.require_member(owner)
        with self.projects.db.read() as conn:
            self.projects._owned(conn, owner, project_id)
            original = self.original_intent(conn, owner, project_id, body)
        if original is None:
            reject('RESEARCH_NATIVE_COMPONENT_REQUIRED', '新研究需要已安装的固定研究组件；历史请求只能恢复原身份')
        return original

    def _receipt(self, owner, request_id, scope_id, allocation_id):
        try:
            receipt = self.runs.request(owner, request_id)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            return None
        if receipt['taskId'] is not None:
            scope = self.scopes.inspect(owner, scope_id)
            allocation = next((value for value in scope['allocations'] if value['allocationId'] == allocation_id), None)
            if allocation is None or allocation['taskId'] != receipt['taskId']:
                reject('RESEARCH_ALLOCATION_TASK_MISMATCH', '原任务回执与已冻结预算分配不一致')
        return receipt

    async def start(self, owner, project_id, body):
        intent = await asyncio.to_thread(self._prepare, owner, project_id, body)
        return await self.recover_intent(owner, project_id, intent)

    async def recover_intent(self, owner, project_id, intent):
        if 'request' not in intent:
            return intent
        receipt = await asyncio.to_thread(self._receipt, owner, intent['request']['requestId'], intent['scopeId'], intent['allocationId'])
        if receipt is None or receipt['taskId'] is None:
            project = await asyncio.to_thread(self.projects.read, owner, project_id)
            if project['state'] == 'ended':
                reject('RESEARCH_PROJECT_ENDED', '项目已结束，不能恢复未准入执行')
            # Core reuses the original request and checks the allocation again
            # inside reservation. End can cancel its scope before that commit.
            await self.runs.start(owner, ApplicationStart.model_validate(intent['request']),
                                  allocation_id=intent['allocationId'])
            receipt = await asyncio.to_thread(self._receipt, owner, intent['request']['requestId'], intent['scopeId'], intent['allocationId'])
        return {key: value for key, value in intent.items() if key != 'request'} | {'execution': receipt}

    def list(self, owner, project_id):
        projects = self.projects
        projects.auth.require_member(owner)
        with projects.db.read() as conn:
            projects._owned(conn, owner, project_id)
            rows = conn.execute(select(self.experiments, self.attempts.c.id.label('attempt_id'),
                self.attempts.c.allocation_id, self.attempts.c.request, self.commitments.c.scope_id).join(self.attempts,
                    self.attempts.c.experiment_id == self.experiments.c.id).join(self.commitments,
                    self.commitments.c.project_id == self.experiments.c.project_id)
                .where(self.experiments.c.project_id == project_id)).mappings().all()
            return {'items': [{'id': row['id'], 'projectId': project_id, 'goalVersion': row['goal_version'],
                'hypothesis': row['hypothesis'], 'conditions': deepcopy(row['conditions']), 'createdAt': row['created_at'],
                'attempt': {'id': row['attempt_id'], 'allocationId': row['allocation_id'],
                    'requestId': row['request']['requestId'],
                    'execution': self._receipt(owner, row['request']['requestId'], row['scope_id'], row['allocation_id'])}} for row in rows]}


def runs_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/projects')

    @router.post('/{identifier}/start', status_code=202)
    async def start(identifier: str, body: ProjectCommand, request: Request):
        return await service.start(auth.user(request)['id'], identifier, body)

    @router.get('/{identifier}/experiments')
    def experiments(identifier: str, request: Request):
        return service.list(auth.user(request)['id'], identifier)

    return router

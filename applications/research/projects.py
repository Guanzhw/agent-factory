"""Owner research agreements; native tasks remain the execution authority."""
from copy import deepcopy
from typing import Annotated, Literal, NoReturn
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, select

from agent_factory.applications import GovernedStorage
from agent_factory.material_governance import PinnedRef
from agent_factory.store import digest, now

RequestId = Annotated[str, Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]+$')]
Reference = Annotated[str, Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9_.:-]+$')]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class Budget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rounds: Annotated[StrictInt, Field(ge=1)]
    toolCalls: Annotated[StrictInt, Field(ge=1)]
    tokenLimit: Annotated[StrictInt, Field(ge=0)] | None = None
    amountMicros: Annotated[StrictInt, Field(ge=0)] | None = None
    currency: Literal['USD', 'EUR', 'CNY'] | None = None

    @model_validator(mode='after')
    def metering(self):
        if self.tokenLimit is None:
            if self.amountMicros is not None or self.currency is not None:
                raise ValueError('Unmetered budgets cannot claim a monetary limit')
        elif self.amountMicros is None or self.currency is None:
            raise ValueError('Metered budgets require an amount and currency')
        return self


class ExecutionConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    applicationRef: PinnedRef
    mode: Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')]
    materialChoices: dict[Reference, PinnedRef] = Field(default_factory=dict, max_length=30)
    connectionRefs: dict[Reference, Reference] = Field(default_factory=dict, max_length=30)
    deadline: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
    perRoundCaps: Budget

    @model_validator(mode='after')
    def one_round(self):
        if self.perRoundCaps.rounds != 1:
            raise ValueError('Each native root allocation is exactly one round')
        return self


class Agreement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    objective: Text
    evaluation: Text
    stopConditions: Text
    resourceRefs: dict[Reference, Reference] = Field(default_factory=dict, max_length=30)
    budget: Budget
    execution: ExecutionConfiguration | None = None

    def execution_goal(self):
        return f'研究目标：{self.objective}\n评价标准：{self.evaluation}\n停止条件：{self.stopConditions}'

    @model_validator(mode='after')
    def allocation_within_commitment(self):
        if self.execution is None:
            return self
        if len(self.execution_goal()) > 2000:
            raise ValueError('Complete executable agreement must fit 2000 characters without truncation')
        round_caps = self.execution.perRoundCaps
        if (round_caps.tokenLimit is None) != (self.budget.tokenLimit is None) or round_caps.currency != self.budget.currency:
            raise ValueError('Round and project metering must agree')
        for field in ('toolCalls', 'tokenLimit', 'amountMicros'):
            total, requested = getattr(self.budget, field), getattr(round_caps, field)
            if total is not None and requested > total:
                raise ValueError('Round allocation exceeds project commitment')
        return self


class CreateProject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    title: str = Field(min_length=1, max_length=120)
    assistantId: Reference | None = None


class ProjectCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    expectedVersion: Annotated[StrictInt, Field(ge=0)]


class ReviseGoal(ProjectCommand):
    agreement: Agreement


class EndProject(ProjectCommand):
    outcome: Literal['not_met', 'cancelled']
    reason: Text


def reject(code, message, status=409) -> NoReturn:
    raise HTTPException(status, {'code': code, 'message': message})


class ResearchProjects:
    def __init__(self, store, auth, endpoints):
        self.auth, self.endpoints = auth, endpoints
        self.execution = None
        self.db = GovernedStorage(store, 'research_projects_v1')
        metadata = MetaData()
        self.projects = Table('research_projects', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('title', String, nullable=False), Column('assistant_id', String),
            Column('state', String, nullable=False), Column('goal_version', Integer, nullable=False),
            Column('ending', JSON), Column('created_at', String, nullable=False))
        self.goals = Table('research_goal_versions', metadata,
            Column('project_id', String, primary_key=True), Column('version', Integer, primary_key=True),
            Column('agreement', JSON, nullable=False), Column('created_at', String, nullable=False),
            Column('confirmed_at', String))
        self.commands = self.db.command_table('research_project_commands', metadata)
        metadata.create_all(store.engine)

    def _owned(self, conn, owner, identifier):
        row = conn.execute(select(self.projects).where(
            self.projects.c.id == identifier, self.projects.c.owner_id == owner)).mappings().first()
        if row is None:
            reject('RESEARCH_PROJECT_NOT_FOUND', '未找到自己的研究项目', 404)
        return row

    def _summary(self, row):
        execution = {'available': False, 'reason': 'RESEARCH_EXECUTION_NOT_INSTALLED'}
        if self.execution is not None:
            with self.db.read() as conn:
                execution = self.execution.availability(conn, row)
        return {'id': row['id'], 'ownerId': row['owner_id'], 'title': row['title'],
            'assistantId': row['assistant_id'], 'state': row['state'],
            'currentGoalVersion': row['goal_version'], 'ending': deepcopy(row['ending']),
            'createdAt': row['created_at'],
            'execution': execution}

    def _detail(self, conn, row):
        goals = conn.execute(select(self.goals).where(self.goals.c.project_id == row['id'])
            .order_by(self.goals.c.version)).mappings().all()
        return {**self._summary(row), 'goals': [{'version': goal['version'],
            'agreement': deepcopy(goal['agreement']), 'createdAt': goal['created_at'],
            'confirmedAt': goal['confirmed_at']} for goal in goals]}

    def create(self, owner, body: CreateProject):
        self.auth.require_member(owner)
        value = body.model_dump(exclude={'requestId'})
        fingerprint = digest({'action': 'create', **value})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, body.requestId, fingerprint)
            if old is not None:
                return old
            if body.assistantId is not None:
                self.endpoints.owned(owner, body.assistantId)
            identifier = str(uuid4())
            conn.execute(self.projects.insert().values(id=identifier, owner_id=owner,
                title=body.title, assistant_id=body.assistantId, state='draft', goal_version=0,
                ending=None, created_at=now()))
            result = self._detail(conn, self._owned(conn, owner, identifier))
            return self.db.record(conn, self.commands, owner, body.requestId, fingerprint, 'research.create', result)

    def read(self, owner, identifier):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            return self._detail(conn, self._owned(conn, owner, identifier))

    def list(self, owner, *, after='', limit=20):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            rows = conn.execute(select(self.projects).where(self.projects.c.owner_id == owner,
                self.projects.c.id > after).order_by(self.projects.c.id).limit(limit + 1)).mappings().all()
            return {'items': [self._summary(row) for row in rows[:limit]],
                'nextCursor': rows[limit - 1]['id'] if len(rows) > limit else None}

    def change(self, owner, identifier, action, body: ProjectCommand):
        self.auth.require_member(owner)
        value = body.model_dump(exclude={'requestId'})
        fingerprint = digest({'action': action, 'project': identifier, **value})
        with self.db.write() as conn:
            row = self._owned(conn, owner, identifier)
            old = self.db.old(conn, self.commands, owner, body.requestId, fingerprint)
            if old is not None:
                return old
            if row['goal_version'] != body.expectedVersion:
                reject('RESEARCH_GOAL_VERSION_CONFLICT', '目标版本已变化，请读取当前版本')
            if row['state'] == 'ended':
                reject('RESEARCH_PROJECT_ENDED', '项目已结束，请建立新项目继续研究')
            if action == 'revise':
                assert isinstance(body, ReviseGoal)
                if self.execution is not None:
                    self.execution.require_same_commitment(conn, identifier, body.agreement)
                version = row['goal_version'] + 1
                conn.execute(self.goals.insert().values(project_id=identifier, version=version,
                    agreement=body.agreement.model_dump(), created_at=now(), confirmed_at=None))
                updates = {'goal_version': version, 'state': 'draft'}
            elif action == 'confirm':
                if row['goal_version'] == 0:
                    reject('RESEARCH_AGREEMENT_REQUIRED', '请先填写研究约定')
                if row['state'] != 'ready':
                    conn.execute(self.goals.update().where(self.goals.c.project_id == identifier,
                        self.goals.c.version == row['goal_version']).values(confirmed_at=now()))
                updates = {'state': 'ready'}
            else:
                assert action == 'end' and isinstance(body, EndProject)
                if body.outcome == 'not_met' and row['goal_version'] == 0:
                    reject('RESEARCH_AGREEMENT_REQUIRED', '未建立目标，不能记录未达标结论')
                if self.execution is not None:
                    self.execution.stop(conn, owner, identifier)
                updates = {'state': 'ended', 'ending': {'outcome': body.outcome, 'reason': body.reason,
                    'goalVersion': row['goal_version'], 'endedAt': now(), 'resourceCleanup': 'not_observed'}}
            changed = conn.execute(self.projects.update().where(self.projects.c.id == identifier,
                self.projects.c.goal_version == body.expectedVersion).values(**updates))
            if changed.rowcount != 1:
                reject('RESEARCH_GOAL_VERSION_CONFLICT', '目标版本已变化，请读取当前版本')
            result = self._detail(conn, self._owned(conn, owner, identifier))
            return self.db.record(conn, self.commands, owner, body.requestId, fingerprint,
                'research.' + action, result)


def projects_router(auth, service):
    router = APIRouter(prefix='/api/factory/research')

    @router.get('/projects')
    def listing(request: Request, after: str = Query(default='', max_length=200),
                limit: int = Query(default=20, ge=1, le=100)):
        return service.list(auth.user(request)['id'], after=after, limit=limit)

    @router.post('/projects', status_code=201)
    def create(body: CreateProject, request: Request):
        return service.create(auth.user(request)['id'], body)

    @router.get('/projects/{identifier}')
    def read(identifier: str, request: Request):
        return service.read(auth.user(request)['id'], identifier)

    @router.post('/projects/{identifier}/goals')
    def revise(identifier: str, body: ReviseGoal, request: Request):
        return service.change(auth.user(request)['id'], identifier, 'revise', body)

    @router.post('/projects/{identifier}/confirm')
    def confirm(identifier: str, body: ProjectCommand, request: Request):
        return service.change(auth.user(request)['id'], identifier, 'confirm', body)

    @router.post('/projects/{identifier}/end')
    def end(identifier: str, body: EndProject, request: Request):
        return service.change(auth.user(request)['id'], identifier, 'end', body)

    return router

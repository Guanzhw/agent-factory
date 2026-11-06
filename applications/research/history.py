"""Read existing research execution records without resuming retired controllers."""
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import MetaData, Table, inspect, select

from .projects import ProjectCommand


class ResearchHistory:
    def __init__(self, runs, *, events, custody, associations=None):
        self.legacy, self.projects = runs, runs.projects
        self.db, self.scopes, self.content = runs.projects.db, runs.scopes, runs.records.content
        self.events, self.custody = events, custody
        self.peer_sources = associations.sources if associations is not None else None
        metadata = MetaData()
        engine = self.db.store.engine
        self.rounds = (Table('research_rounds', metadata, autoload_with=engine)
                       if inspect(engine).has_table('research_rounds') else None)
        self.experiments = Table('research_experiments', metadata, autoload_with=engine)
        self.attempts = Table('research_attempts', metadata, autoload_with=engine)

    async def start(self, owner, project_id, body):
        # Even an original request must not replay through the replacement app.
        self.projects.auth.require_member(owner)
        with self.db.read() as conn:
            self.projects._owned(conn, owner, project_id)
        raise HTTPException(409, 'RESEARCH_USE_AGENT_SESSION')

    def list(self, owner, project_id):
        self.projects.auth.require_member(owner)
        with self.db.read() as conn:
            self.projects._owned(conn, owner, project_id)
            rows = (conn.execute(select(self.rounds).where(self.rounds.c.project_id == project_id)
                    .order_by(self.rounds.c.created_at)).mappings().all() if self.rounds is not None else [])
            if not rows:
                return {**self.legacy.list(owner, project_id), 'rounds': []}
            experiments = conn.execute(select(self.experiments).where(
                self.experiments.c.project_id == project_id)).mappings().all()
            items = []
            for experiment in experiments:
                attempts = conn.execute(select(self.attempts).where(
                    self.attempts.c.experiment_id == experiment['id'])).mappings().all()
                if self.peer_sources and not self.peer_sources.available(owner,
                        self.peer_sources.dependencies(experiment['round_id'])):
                    items.append({'id': experiment['id'], 'projectId': project_id,
                        'goalVersion': experiment['goal_version'], 'sourceUnavailable': True,
                        'attempts': [{'id': a['id'], 'operationId': a['operation_id']} for a in attempts]})
                    continue
                items.append({'id': experiment['id'], 'projectId': project_id,
                    'goalVersion': experiment['goal_version'], 'hypothesis': experiment['hypothesis'],
                    'conditions': deepcopy(experiment['conditions']), 'attempts': [
                        {'id': a['id'], 'operationId': a['operation_id'],
                         'operation': self.custody.read(owner, a['operation_id']) if a['operation_id'] else None}
                        for a in attempts]})
            result = {'items': items, 'rounds': [{'id': row['id'], 'goalVersion': row['goal_version'],
                'scopeId': row['scope_id'], 'allocationId': row['allocation_id'], 'taskId': row['task_id'],
                'deliveryId': row['delivery_id'], 'decision': deepcopy(row['decision']),
                'terminal': deepcopy(row['terminal']), 'terminalRecordId': row['terminal_record'],
                'continuations': [{**trigger, 'delivery': self.events.event(owner, trigger['eventId'])}
                    for trigger in row['continuations']]} for row in rows]}
            if self.peer_sources:
                for item in result['rounds']:
                    if not self.peer_sources.available(owner, self.peer_sources.dependencies(item['id'])):
                        item['decision'] = None
                        item['terminal'] = {'state': 'ended'} if item['terminal'] else None
                        item['sourceUnavailable'] = True
            return result


def history_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/projects')

    @router.post('/{identifier}/start', status_code=202)
    async def start(identifier: str, body: ProjectCommand, request: Request):
        return await service.start(auth.user(request)['id'], identifier, body)

    @router.get('/{identifier}/experiments')
    def experiments(identifier: str, request: Request):
        return service.list(auth.user(request)['id'], identifier)

    return router

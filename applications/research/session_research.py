"""Optional research operations for the existing autonomous session Agent."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.application_content import ContentPublication, ContentSource
from agent_factory.personal_tool_contract import ToolInvocationError
from agent_factory.store import digest, now


RESEARCH_TOOLS = {'research_project', 'research_experiment', 'research_record_experiment',
                  'research_experiment_result', 'research_assess'}
RESEARCH_WRITES = {'research_experiment', 'research_record_experiment', 'research_assess'}


def rejected(code):
    return ToolInvocationError(code, outcome='failed', stopped=True)


class ResearchSessionResearch:
    def __init__(self, sessions, projects, content):
        self.sessions, self.projects, self.content = sessions, projects, content
        self.store, self.db = sessions.store, sessions.db
        metadata = MetaData()
        self.experiments = Table('research_session_experiments', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('session_id', String, nullable=False), Column('task_id', String, nullable=False),
            Column('body', JSON, nullable=False))
        metadata.create_all(self.store.engine)

    def _context(self, context):
        with self.db.read() as conn:
            row, _, _ = self.sessions._execution(conn, context)
        return row

    def _project(self, owner, row):
        identifier = row['body'].get('projectId')
        if identifier is None:
            return None
        project = self.projects.read(owner, identifier)
        if project.get('sourceUnavailable'):
            raise rejected('RESEARCH_SOURCE_UNAVAILABLE')
        return project

    def _row(self, owner, session_id, identifier):
        with self.db.read() as conn:
            row = conn.execute(select(self.experiments).where(self.experiments.c.id == identifier,
                self.experiments.c.owner_id == owner, self.experiments.c.session_id == session_id)).mappings().first()
        if row is None:
            raise rejected('RESEARCH_EXPERIMENT_NOT_FOUND')
        return row

    def _save(self, identifier, body):
        with self.db.write() as conn:
            current = conn.execute(select(self.experiments.c.body).where(self.experiments.c.id == identifier)).scalar_one()
            merged = {**current, **body}
            if current.get('assessments'):
                merged['assessments'] = {**body.get('assessments', {}), **current['assessments']}
            if current.get('terminalRecordId'):
                merged.update(terminalRecordId=current['terminalRecordId'], status=current['status'])
            conn.execute(self.experiments.update().where(self.experiments.c.id == identifier).values(body=merged))

    def _publish(self, row, revision, assessment=None, source_ids=None):
        body = row['body']
        # These are explicitly submitted research notes, not automatic workspace or transcript capture.
        content = {key: deepcopy(body[key]) for key in
            ('hypothesis', 'conditions', 'projectId', 'goalVersion', 'status', 'evidenceIds', 'observations') if key in body}
        content.update(kind='research.experiment.' + revision, experimentId=row['id'],
                       verificationStatus='unverified')
        if revision == 'start':
            content.update(status='pending_admission', evidenceIds=[])
            content.pop('observations', None)
        if assessment is not None:
            content.update(assessment=assessment, verificationStatus='agent_analysis')
        publication = ContentPublication(source=ContentSource(application='research', record=row['id'], revision=revision),
            content=content, visibility='team', sourceContentIds=(body.get('sourceContentIds', [])
                if source_ids is None else source_ids))
        return self.content.publish(row['owner_id'], publication,
            'session-experiment:' + row['id'] + ':' + revision)['id']

    @staticmethod
    def _identifier(context, call_id):
        return str(uuid5(NAMESPACE_URL, 'research-experiment:' + context.user_id + ':' + context.run_id + ':' + call_id))

    @staticmethod
    def _record(values):
        return {'status': 'recorded',
                'evidenceIds': deepcopy(values.get('evidenceIds', values.get('effectKeys', []))),
                'observations': deepcopy(values.get('observations', []))}

    def _create(self, context, call_id, name, values, session):
        identifier = self._identifier(context, call_id)
        source_ids = set()
        for source_id in session['body'].get('sharedSourceIds', []):
            source = self.content.read(context.user_id, source_id)
            source_ids.update([source_id, *source.get('sourceContentIds', [])])
        body = {'hypothesis': values.get('hypothesis', ''), 'conditions': values.get('conditions', ''),
                'projectId': session['body'].get('projectId'),
                'goalVersion': session['body'].get('projectGoalVersion'),
                'status': 'pending_admission', 'evidenceIds': [], 'sourceContentIds': sorted(source_ids),
                'createdAt': now(), 'request': deepcopy(values), 'toolName': name,
                'callId': call_id, 'runId': context.run_id}
        if name != 'research_experiment':
            body.update(self._record(values))
        with self.db.write() as conn:
            existing = conn.execute(select(self.experiments).where(self.experiments.c.id == identifier)).mappings().first()
            if existing is None:
                conn.execute(self.experiments.insert().values(id=identifier, owner_id=context.user_id,
                    session_id=session['id'], task_id=self.store.task_for_context(context)["id"], body=body))
            elif existing['body']['request'] != values or existing['body']['toolName'] != name:
                raise rejected('RESEARCH_EXPERIMENT_REQUEST_CONFLICT')
        return self._row(context.user_id, session['id'], identifier), existing is not None

    def reconcile(self, context, call_id, name, values):
        session = self._context(context)
        identifier = values.get('experimentId') if name == 'research_assess' else None
        identifier = identifier or self._identifier(context, call_id)
        row = self._row(context.user_id, session['id'], identifier)
        body = row['body']
        if name == 'research_assess':
            item = body.get('assessments', {}).get(context.run_id + ':' + call_id)
            if item and all(item.get(field) == values[field] for field in
                            ('assessment', 'evidenceIds', 'observations') if field in values):
                return self._assessment_receipt(row, context.run_id + ':' + call_id)
            return None
        if body['request'] != values or body['toolName'] != name:
            raise rejected('RESEARCH_EXPERIMENT_REQUEST_CONFLICT')
        return self._recover(row)

    def _recover(self, row):
        body = row['body']
        name = body['toolName']
        if name == 'research_assess':
            key = body['runId'] + ':' + body['callId']
            return self._assessment_receipt(row, key) if key in body.get('assessments', {}) else None
        context = SimpleNamespace(user_id=row['owner_id'], session_id=row['task_id'], run_id=body['runId'])
        if name == 'research_record_experiment' and body['status'] == 'pending_admission':
            body = {**body, **self._record(body['request'])}
        if name == 'research_experiment' and not body.get('childTaskId'):
            # A lost response is reconciled against the exact durable child
            # request. Never dispatch a replacement child to discover its state.
            links = self.store.sql('SELECT * FROM af_delegation_links WHERE owner_id=:owner '
                'AND parent_id=:parent AND request_id=:request', owner=context.user_id,
                parent=row['task_id'], request='research-child:' + digest({'run': body['runId'], 'call': body['callId']}))
            if len(links) != 1 or not links[0]['child_id']:
                return None
            child = self.store.task(links[0]['child_id'], context.user_id)
            body = {**body, 'childTaskId': child['id'], 'status': 'unknown', 'evidenceIds': [child['id']]}
        if name == 'research_experiment' and not body.get('startRecordId'):
            body['startRecordId'] = self._publish({**row, 'body': body}, 'start')
        if name == 'research_record_experiment' and body['status'] in {'recorded', 'completed', 'failed', 'canceled'} and not body.get('terminalRecordId'):
            body['terminalRecordId'] = self._publish({**row, 'body': body}, 'terminal')
        self._save(row['id'], body)
        return self._projection(self._row(row['owner_id'], row['session_id'], row['id']))

    def _assessment_receipt(self, row, key):
        item = deepcopy(row['body']['assessments'][key])
        if not item.get('recordId'):
            publication = {**row, 'body': {**row['body'], **{field: item[field] for field in
                ('evidenceIds', 'observations') if field in item}}}
            item['recordId'] = self._publish(publication, 'assessment-' + digest(key)[:32], item['assessment'],
                item.get('sourceContentIds', row['body'].get('sourceContentIds', [])))
            with self.db.write() as conn:
                body = deepcopy(conn.execute(select(self.experiments.c.body).where(
                    self.experiments.c.id == row['id'])).scalar_one())
                body['assessments'][key] = item
                conn.execute(self.experiments.update().where(self.experiments.c.id == row['id']).values(body=body))
        return item

    @staticmethod
    def _projection(row):
        return {'experimentId': row['id'], **{key: deepcopy(value) for key, value in row['body'].items()
            if key not in {'request', 'toolName', 'callId', 'runId'}}}

    async def invoke(self, context, call_id, name, values):
        session = self._context(context)
        project = self._project(context.user_id, session) if name in {'research_project', 'research_experiment'} else None
        if name == 'research_project':
            if project:
                # Execution bindings and resource references remain owner custody.
                project = deepcopy(project)
                for goal in project.get('goals', []):
                    goal.get('agreement', {}).pop('execution', None)
                    goal.get('agreement', {}).pop('resourceRefs', None)
            return {'project': project, 'sessionGoal': session['body']['goal'],
                    'boundaries': session['body']['boundaries']}
        if name in {'research_experiment_result', 'research_assess'}:
            if name == 'research_assess' and not values.get('experimentId'):
                row, _ = self._create(context, call_id, name, values, session)
            else:
                row = self._row(context.user_id, session['id'], values['experimentId'])
            if name == 'research_experiment_result':
                await self._observe(row)
                return self._projection(self._row(context.user_id, session['id'], row['id']))
            dependencies = set(row['body'].get('sourceContentIds', []))
            for identifier in session['body'].get('sharedSourceIds', []):
                source = self.content.read(context.user_id, identifier)
                dependencies.update([identifier, *source.get('sourceContentIds', [])])
            with self.db.write() as conn:
                row = conn.execute(select(self.experiments).where(self.experiments.c.id == row['id'])).mappings().one()
                body = deepcopy(row['body'])
                item = {'experimentId': row['id'], 'assessment': values['assessment'],
                        'evidenceIds': deepcopy(values.get('evidenceIds', body['evidenceIds'])),
                        'observations': deepcopy(values.get('observations', body.get('observations', []))),
                        'verificationStatus': 'agent_analysis', 'sourceContentIds': sorted(dependencies)}
                key = context.run_id + ':' + call_id
                old = body.setdefault('assessments', {}).get(key)
                if old is not None and any(old.get(field) != values[field] for field in
                                          ('assessment', 'evidenceIds', 'observations') if field in values):
                    raise rejected('RESEARCH_EXPERIMENT_REQUEST_CONFLICT')
                body['assessments'][key] = old or item
                conn.execute(self.experiments.update().where(self.experiments.c.id == row['id']).values(body=body))
            return self._assessment_receipt(self._row(context.user_id, session['id'], row['id']), key)
        if name == 'research_experiment' and project and project['state'] == 'ended':
            raise rejected('RESEARCH_PROJECT_ENDED')
        row, existing = self._create(context, call_id, name, values, session)
        identifier, body = row['id'], deepcopy(row['body'])
        if existing:
            result = self.reconcile(context, call_id, name, values)
            if result is None:
                return {**self._projection(row), 'status': 'unknown', 'outcome': 'unknown',
                        'code': 'RESEARCH_TOOL_OUTCOME_UNKNOWN',
                        'message': 'The original experiment outcome is unconfirmed. Do not restart it. '
                                   'Other work can continue.'}
            return result
        if name == 'research_record_experiment':
            body['terminalRecordId'] = self._publish(row, 'terminal')
            self._save(identifier, body)
        else:
            body['startRecordId'] = self._publish(row, 'start')
            self._save(identifier, body)
            child = await self.sessions.subagents.start(context, call_id, values['goal'])
            body.update(childTaskId=child['childTaskId'], status=child['status'], evidenceIds=[child['childTaskId']])
            self._save(identifier, body)
            await self._observe(self._row(context.user_id, session['id'], identifier))
        return self._projection(self._row(context.user_id, session['id'], identifier))

    async def _observe(self, row):
        body = deepcopy(row['body'])
        if body.get('terminalRecordId') or not body.get('childTaskId'):
            return
        child = self.store.task(body['childTaskId'], row['owner_id'])
        group = await self.store.lifecycle_observer.inspect_subtree(row['owner_id'], child['id'])
        projection = self.sessions.subagents._projection(child, group)
        facts = [group.get('parent', {}), *group.get('children', [])]
        body['status'] = ('unknown' if group['unknown'] else
            'running' if not group['allStopped'] else
            'failed' if any(fact.get('failed') for fact in facts) else
            'canceled' if any(fact.get('nativeStatus') in {'canceled', 'cancelled'} for fact in facts) else
            projection['status'])
        if group['allStopped'] and not group['unknown'] and body['status'] in {'completed', 'failed', 'canceled'}:
            body['observations'] = [{'evidenceId': child['id'], 'nativeStatus': body['status'], 'stopped': True}]
            body['terminalRecordId'] = self._publish({**row, 'body': body}, 'terminal')
        self._save(row['id'], body)

    async def observe(self, task):
        run_id = task.get('run_id')
        if not run_id:
            # Pending admission has no native run identity or original effects
            # to reconcile. Do not substitute an empty matching prefix.
            return
        with self.db.read() as conn:
            rows = list(conn.execute(select(self.experiments).where(
                self.experiments.c.owner_id == task['owner_id'])).mappings())
        effects = {item['effect_key']: item for item in self.store.effects(task['id'])}
        prefix = run_id + ':'

        def complete(run_id, call_id, output):
            key = 'research-session-tool:' + call_id
            effect = effects.get(run_id + ':' + key)
            if effect and effect['status'] == 'UNKNOWN' and output is not None:
                self.store.effect_complete(run_id, key, {'outcome': 'completed', 'output': output})

        for row in rows:
            if row['task_id'] == task['id']:
                recovered = self._recover(row)
                if recovered is not None:
                    complete(row['body']['runId'], row['body']['callId'], recovered)
                    await self._observe(self._row(row['owner_id'], row['session_id'], row['id']))
            for key in row['body'].get('assessments', {}):
                if key.startswith(prefix):
                    item = self._assessment_receipt(row, key)
                    complete(task['run_id'], key.removeprefix(prefix), item)

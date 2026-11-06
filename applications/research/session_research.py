"""Optional research operations for the existing autonomous session Agent."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from agno.exceptions import StopAgentRun
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
    def __init__(self, sessions, projects, records):
        self.sessions, self.projects, self.records = sessions, projects, records
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
        # Share curated intent and receipt identities, never command output,
        # private conversation context, workspace paths or resource credentials.
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
        return self.records.content.publish(row['owner_id'], publication,
            'session-experiment:' + row['id'] + ':' + revision)['id']

    @staticmethod
    def _identifier(context, call_id):
        return str(uuid5(NAMESPACE_URL, 'research-experiment:' + context.user_id + ':' + context.run_id + ':' + call_id))

    def _direct(self, context, values):
        effects = {item['effect_key']: item for item in self.store.effects(context.session_id)
                   if item['effect_key'].startswith(context.run_id + ':research-session-tool:')
                   and item['status'] == 'DONE' and (item.get('result') or {}).get('outcome') == 'completed'
                   and isinstance((item.get('result') or {}).get('output'), dict)
                   and isinstance(item['result']['output'].get('exitCode'), int)
                   and item['result']['output'].get('stopped') is True}
        keys = values.get('effectKeys') or list(effects)
        if not keys or set(keys) - effects.keys():
            raise rejected('RESEARCH_ORIGINAL_RESULT_REQUIRED')
        return {'status': 'completed' if all(effects[key]['result']['output']['exitCode'] == 0 for key in keys)
                else 'failed', 'evidenceIds': keys, 'observations': [
                    {'evidenceId': key, 'exitCode': effects[key]['result']['output']['exitCode'], 'stopped': True}
                    for key in keys]}

    def reconcile(self, context, call_id, name, values):
        session = self._context(context)
        identifier = values['experimentId'] if name == 'research_assess' else self._identifier(context, call_id)
        row = self._row(context.user_id, session['id'], identifier)
        body = row['body']
        if name == 'research_assess':
            item = body.get('assessments', {}).get(context.run_id + ':' + call_id)
            if item and item['assessment'] == values['assessment']:
                return self._assessment_receipt(row, context.run_id + ':' + call_id)
            return None
        if body['request'] != values or body['toolName'] != name:
            raise rejected('RESEARCH_EXPERIMENT_REQUEST_CONFLICT')
        return self._recover(row)

    def _recover(self, row):
        body = row['body']
        name = body['toolName']
        context = SimpleNamespace(user_id=row['owner_id'], session_id=row['task_id'], run_id=body['runId'])
        if name == 'research_record_experiment' and body['status'] == 'pending_admission':
            body = {**body, **self._direct(context, body['request'])}
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
        if not body.get('startRecordId'):
            body['startRecordId'] = self._publish({**row, 'body': body}, 'start')
        if name == 'research_record_experiment' and body['status'] in {'completed', 'failed', 'canceled'} and not body.get('terminalRecordId'):
            body['terminalRecordId'] = self._publish({**row, 'body': body}, 'terminal')
        self._save(row['id'], body)
        return self._projection(self._row(row['owner_id'], row['session_id'], row['id']))

    def _assessment_receipt(self, row, key):
        item = deepcopy(row['body']['assessments'][key])
        if not item.get('recordId'):
            item['recordId'] = self._publish(row, 'assessment-' + digest(key)[:32], item['assessment'],
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
        project = self._project(context.user_id, session)
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
            row = self._row(context.user_id, session['id'], values['experimentId'])
            if name == 'research_experiment_result':
                await self._observe(row)
                return self._projection(self._row(context.user_id, session['id'], row['id']))
            if not row['body'].get('terminalRecordId'):
                raise rejected('RESEARCH_ORIGINAL_RESULT_REQUIRED')
            dependencies = set(row['body'].get('sourceContentIds', []))
            for identifier in session['body'].get('sharedSourceIds', []):
                source = self.records.content.read(context.user_id, identifier)
                dependencies.update([identifier, *source.get('sourceContentIds', [])])
            with self.db.write() as conn:
                row = conn.execute(select(self.experiments).where(self.experiments.c.id == row['id'])).mappings().one()
                body = deepcopy(row['body'])
                item = {'assessment': values['assessment'], 'evidenceIds': body['evidenceIds'],
                        'verificationStatus': 'agent_analysis', 'sourceContentIds': sorted(dependencies)}
                key = context.run_id + ':' + call_id
                old = body.setdefault('assessments', {}).get(key)
                if old is not None and old['assessment'] != values['assessment']:
                    raise rejected('RESEARCH_EXPERIMENT_REQUEST_CONFLICT')
                body['assessments'][key] = old or item
                conn.execute(self.experiments.update().where(self.experiments.c.id == row['id']).values(body=body))
            return self._assessment_receipt(self._row(context.user_id, session['id'], row['id']), key)
        if project and (project['state'] != 'ready' or project['currentGoalVersion'] != session['body']['projectGoalVersion']):
            raise rejected('RESEARCH_CONFIRMED_GOAL_REQUIRED')
        identifier = self._identifier(context, call_id)
        direct = self._direct(context, values) if name == 'research_record_experiment' else None
        source_ids = set()
        for source_id in session['body'].get('sharedSourceIds', []):
            source = self.records.content.read(context.user_id, source_id)
            source_ids.update([source_id, *source.get('sourceContentIds', [])])
        with self.db.write() as conn:
            existing = conn.execute(select(self.experiments).where(self.experiments.c.id == identifier)).mappings().first()
            body = {'hypothesis': values['hypothesis'], 'conditions': values['conditions'],
                    'projectId': session['body'].get('projectId'),
                    'goalVersion': session['body'].get('projectGoalVersion'),
                    'status': 'pending_admission', 'evidenceIds': [], 'sourceContentIds': sorted(source_ids), 'createdAt': now(),
                    'request': deepcopy(values), 'toolName': name, 'callId': call_id, 'runId': context.run_id}
            if existing is None:
                conn.execute(self.experiments.insert().values(id=identifier, owner_id=context.user_id,
                    session_id=session['id'], task_id=context.session_id, body=body))
        if existing is not None:
            result = self.reconcile(context, call_id, name, values)
            if result is None:
                raise StopAgentRun('RESEARCH_TOOL_OUTCOME_UNKNOWN')
            return result
        row = self._row(context.user_id, session['id'], identifier)
        body['startRecordId'] = self._publish(row, 'start')
        self._save(identifier, body)
        if direct is not None:
            body.update(direct)
        else:
            child = await self.sessions.subagents.start(context, call_id, values['goal'])
            body.update(childTaskId=child['childTaskId'], status=child['status'], evidenceIds=[child['childTaskId']])
        self._save(identifier, body)
        row = self._row(context.user_id, session['id'], identifier)
        if direct is not None:
            body['terminalRecordId'] = self._publish(row, 'terminal')
            self._save(identifier, body)
        else:
            await self._observe(row)
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

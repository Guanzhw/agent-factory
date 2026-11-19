"""Optional research operations for the existing autonomous session Agent."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Column, JSON, MetaData, String, Table, func, select, text

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
        if self.store.engine.dialect.name == 'postgresql':
            with self.store.engine.begin() as conn:
                conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS research_experiments_owner_task
                    ON research_session_experiments (owner_id, task_id)""")
                conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS research_experiments_assessed_session
                    ON research_session_experiments (owner_id, session_id) WHERE body->'assessments' IS NOT NULL""")

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
            content=content, visibility=body.get('visibility', 'team'), sourceContentIds=(body.get('sourceContentIds', [])
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
        body = {'visibility': values.get('visibility', 'team'), 'hypothesis': values.get('hypothesis', ''), 'conditions': values.get('conditions', ''),
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
        return self.visible_output(context, self._reconcile(context, call_id, name, values, session), session)

    def _reconcile(self, context, call_id, name, values, session):
        identifier = values.get('experimentId') if name == 'research_assess' else None
        identifier = identifier or self._identifier(context, call_id)
        row = self._row(context.user_id, session['id'], identifier)
        body = row['body']
        if name == 'research_assess':
            item = body.get('assessments', {}).get(context.run_id + ':' + call_id)
            if item and all(item.get(field) == values[field] for field in
                            ('assessment', 'visibility', 'evidenceIds', 'observations') if field in values):
                return self._assessment_receipt(row, context.run_id + ':' + call_id)
            return None
        if body['request'] != values or body['toolName'] != name:
            raise rejected('RESEARCH_EXPERIMENT_REQUEST_CONFLICT')
        return self._recover(row)

    @staticmethod
    def _has_receipt(body):
        if body['toolName'] == 'research_experiment':
            return bool(body.get('childTaskId') and body.get('startRecordId'))
        return bool(body.get('terminalRecordId'))

    def _recover(self, row):
        body = row['body']
        name = body['toolName']
        if name == 'research_assess':
            key = body['runId'] + ':' + body['callId']
            return self._assessment_receipt(row, key) if key in body.get('assessments', {}) else None
        if self._has_receipt(body):
            return self._projection(row)
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
        if 'sourceContentIds' not in item and row['body'].get('sourceContentIds'):
            item['sourceContentIds'] = row['body']['sourceContentIds']
        if not item.get('recordId'):
            publication = {**row, 'body': {'visibility': row['body'].get('visibility', 'team'), **item}}
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

    def visible_output(self, context, output, session=None):
        if not output or 'experimentId' not in output:
            return output
        base = set(output.get('sourceContentIds', []))
        assessments = output.get('assessments', {})
        required = base.union(*(item.get('sourceContentIds', []) for item in assessments.values()))
        if not required:
            return output
        allowed = self.content.readable_ids({context.user_id}, required)
        visible = set()
        if base <= allowed:
            result = dict(output)
            visible.update(base)
        else:
            result = {'experimentId': output['experimentId'], 'sourceUnavailable': True}
        if assessments:
            result['assessments'] = {}
            for key, item in assessments.items():
                sources = item.get('sourceContentIds', base)
                if allowed.issuperset(sources):
                    result['assessments'][key] = item
                    visible.update(sources)
        if visible:
            session = session or self._context(context)
            missing = visible.difference(session['body'].get('sharedSourceIds', []))
            if missing:
                self.sessions.record_sources(context, sorted(missing))
        return result

    async def invoke(self, context, call_id, name, values):
        session = self._context(context)
        output = await self._invoke(context, call_id, name, values, session)
        return self.visible_output(context, output, session)

    async def _invoke(self, context, call_id, name, values, session):
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
                if not row['body'].get('terminalRecordId') and row['body'].get('childTaskId'):
                    await self._observe(row)
                    row = self._row(context.user_id, session['id'], row['id'])
                return self._projection(row)
            dependencies = set(row['body'].get('sourceContentIds', []))
            dependencies.update(row['body'][field] for field in ('startRecordId', 'terminalRecordId')
                                if row['body'].get(field))
            if dependencies and self.content.readable_ids({context.user_id}, dependencies) != dependencies:
                raise rejected('RESEARCH_SOURCE_UNAVAILABLE')
            for identifier in session['body'].get('sharedSourceIds', []):
                source = self.content.read(context.user_id, identifier)
                dependencies.update([identifier, *source.get('sourceContentIds', [])])
            with self.db.write() as conn:
                row = conn.execute(select(self.experiments).where(self.experiments.c.id == row['id'])).mappings().one()
                body = deepcopy(row['body'])
                item = {'visibility': values.get('visibility', 'team'), 'experimentId': row['id'], 'assessment': values['assessment'],
                        'evidenceIds': deepcopy(values.get('evidenceIds', [])),
                        'observations': deepcopy(values.get('observations', [])),
                        'verificationStatus': 'agent_analysis', 'sourceContentIds': sorted(dependencies)}
                key = context.run_id + ':' + call_id
                old = body.setdefault('assessments', {}).get(key)
                if old is not None and any(old.get(field) != values[field] for field in
                                          ('assessment', 'visibility', 'evidenceIds', 'observations') if field in values):
                    raise rejected('RESEARCH_EXPERIMENT_REQUEST_CONFLICT')
                body['assessments'][key] = old or item
                conn.execute(self.experiments.update().where(self.experiments.c.id == row['id']).values(body=body))
            return self._assessment_receipt(self._row(context.user_id, session['id'], row['id']), key)
        if name == 'research_experiment' and project and project['state'] == 'ended':
            raise rejected('RESEARCH_PROJECT_ENDED')
        row, existing = self._create(context, call_id, name, values, session)
        identifier, body = row['id'], deepcopy(row['body'])
        if existing:
            result = self._reconcile(context, call_id, name, values, session)
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
        changes = {key: body[key] for key in ('status', 'observations', 'terminalRecordId')
                   if key in body and body[key] != row['body'].get(key)}
        if changes:
            self._save(row['id'], changes)

    async def observe(self, task, session_id):
        run_id = task.get('run_id')
        if not run_id:
            # Pending admission has no native run identity or original effects
            # to reconcile. Do not substitute an empty matching prefix.
            return
        prefix = run_id + ':'
        # Assessments can belong to this run even when an earlier task created the experiment.
        columns = self.experiments.c
        key = func.json_object_keys(columns.body['assessments']).column_valued('assessment_key')
        matching_assessment = select(1).where(func.starts_with(key, prefix)).correlate(self.experiments).exists()
        assessed = text("body->'assessments' IS NOT NULL") & matching_assessment
        if session_id is not None:
            assessed = (columns.session_id == session_id) & assessed
        with self.db.read() as conn:
            rows = conn.execute(select(self.experiments).where(columns.owner_id == task['owner_id'],
                (columns.task_id == task['id']) | assessed)).mappings().all()
        if not rows:
            return
        unknown = {item['effect_key'] for item in self.store.effects(task['id']) if item['status'] == 'UNKNOWN'}

        def pending(original_run, call_id):
            return original_run + ':research-session-tool:' + call_id in unknown

        def complete(original_run, call_id, output):
            self.store.effect_complete(original_run, 'research-session-tool:' + call_id,
                                       {'outcome': 'completed', 'output': output})

        for row in rows:
            body = row['body']
            if row['task_id'] == task['id'] and body['toolName'] != 'research_assess':
                missing = not self._has_receipt(body)
                waiting = pending(body['runId'], body['callId'])
                if missing or waiting:
                    recovered = self._recover(row)
                    if recovered is not None:
                        if waiting:
                            complete(body['runId'], body['callId'], recovered)
                        if missing and body['toolName'] == 'research_experiment':
                            row = self._row(row['owner_id'], row['session_id'], row['id'])
                if body['toolName'] == 'research_experiment':
                    await self._observe(row)
            for key, assessment in row['body'].get('assessments', {}).items():
                if key.startswith(prefix):
                    call_id = key.removeprefix(prefix)
                    waiting = pending(run_id, call_id)
                    if waiting or not assessment.get('recordId'):
                        item = self._assessment_receipt(row, key)
                        if waiting:
                            complete(run_id, call_id, item)

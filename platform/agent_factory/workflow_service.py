"""Durable agent-selected stages; runtime callbacks never execute under SQL locks.

Definitions and adapters are operator registrations. An uncertain start is never
replayed: only an original returned handle can be inspected or cancelled.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import re
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import text
from fastapi import HTTPException

from .store import canonical, digest
from .workflow_contracts import WorkflowAcknowledgementUnknown, WorkflowContext, validate_runtime_observation, validate_workflow_definition, workflow_fingerprint

ERROR = 'WORKFLOW_CUSTODY_INVALID'
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED'}
WORKFLOW_TOOLS = frozenset({'workflow_read', 'workflow_choose', 'workflow_inspect', 'workflow_wait', 'workflow_finish'})


def require(value):
    if not value:
        raise ValueError(ERROR)


def decoded(value):
    return json.loads(value) if isinstance(value, str) else deepcopy(value)


def require_workflow_plan_current(owner, plan, *, definitions, runtimes, tool_name=None, run_context=None):
    """Nonrecursive execution guard; historical reads and cleanup remain separate."""
    selected = [name for name in plan.get('tools', []) if isinstance(name, str) and name in WORKFLOW_TOOLS]
    if not selected:
        return None
    try:
        require(plan.get('ownerId') == owner and type(plan.get('applicationRef')) is dict)
        specs = [spec for spec in plan.get('executionBindings', {}).get('tools', [])
                 if spec.get('toolName') in WORKFLOW_TOOLS]
        require(len(specs) == len(selected) and {spec.get('toolName') for spec in specs} == set(selected))
        config = specs[0].get('config')
        require(type(config) is dict and set(config) == {'workflowId', 'workflowSha256'})
        for spec in specs:
            name = spec.get('toolName')
            require(name in WORKFLOW_TOOLS
                    and spec.get('adapterId') == 'workflow-' + name.removeprefix('workflow_') + '-v1'
                    and spec.get('revision') == '1' and spec.get('config') == config)
        definition = definitions.get(config['workflowId'])
        require(definition is not None and config['workflowSha256'] == workflow_fingerprint(definition))
        definition = cast(dict, definition)
        for stage in definition['stages']:
            runtime = runtimes.get((stage['adapterId'], stage['revision']))
            require(runtime is not None and all(callable(getattr(runtime, method, None)) for method in ('start', 'inspect', 'cancel')))
        return deepcopy(definition)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(409, 'WORKFLOW_CURRENT_DEFINITION_UNAVAILABLE') from None


class WorkflowService:
    def __init__(self, store, auth, *, definitions, runtimes):
        self.store, self.auth = store, auth
        self.definitions = {key: validate_workflow_definition(value) for key, value in definitions.items()}
        require(all(key == value['id'] for key, value in self.definitions.items()))
        self.runtimes = dict(runtimes)
        for definition in self.definitions.values():
            for stage in definition['stages']:
                runtime = self.runtimes.get((stage['adapterId'], stage['revision']))
                require(runtime is not None and all(callable(getattr(runtime, method, None)) for method in ('start', 'inspect', 'cancel')))
        with store.engine.begin() as conn:
            conn.execute(text('CREATE TABLE IF NOT EXISTS af_workflow_runs (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, task_id TEXT NOT NULL UNIQUE, native_run_id TEXT NOT NULL UNIQUE, body JSONB NOT NULL)'))
            conn.execute(text('CREATE TABLE IF NOT EXISTS af_workflow_commands (workflow_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, body JSONB NOT NULL, PRIMARY KEY(workflow_id,request_id))'))
            if conn.dialect.name == 'postgresql':
                # Recover original custody left terminal by a pre-fix observer.
                # This re-holds accounting only; it never dispatches operations.
                original_held = """SELECT task.id FROM af_tasks task JOIN af_workflow_runs workflow
                    ON workflow.task_id=task.id AND workflow.owner_id=task.owner_id
                    AND workflow.native_run_id=task.run_id
                    AND workflow.body->>'planId'=task.plan_id
                    WHERE workflow.body->>'status' NOT IN ('COMPLETED','CANCELLED')"""
                held = original_held
                if getattr(store, 'delegation', None) is not None:
                    held += (' UNION SELECT parent_id FROM af_delegation_links WHERE child_id IN (' + original_held + ')'
                             ' UNION SELECT root_id FROM af_delegation_links WHERE child_id IN (' + original_held + ')')
                conn.execute(text('UPDATE af_tasks SET terminal=FALSE WHERE terminal AND id IN (' + held + ')'))
                conn.execute(text("UPDATE af_disk_holds SET state='HELD' WHERE state='RELEASED' AND task_id IN (" + held + ')'))
                if getattr(store, 'delegation', None) is not None:
                    conn.execute(text('UPDATE af_delegation_roots SET reclaimed=FALSE WHERE reclaimed AND (root_id IN (' + held + ') '
                        'OR root_id IN (SELECT root_id FROM af_delegation_links WHERE child_id IN (' + held + ')))'))

    @contextmanager
    def _transaction(self):
        with self.store.transaction() as conn:
            if conn.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_workflow_runs'))"))
            elif conn.dialect.name == 'sqlite':
                conn.exec_driver_sql('BEGIN IMMEDIATE')
            yield conn

    def _load(self, conn, identifier, owner):
        row = conn.execute(text('SELECT * FROM af_workflow_runs WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).mappings().first()
        require(row is not None)
        body = decoded(row['body'])
        require(body['id'] == identifier and body['ownerId'] == owner and body['taskId'] == row['task_id']
                and body['nativeRunId'] == row['native_run_id'])
        return body

    def _save(self, conn, body):
        body['version'] += 1
        conn.execute(text('UPDATE af_workflow_runs SET body=CAST(:body AS JSONB) WHERE id=:id AND owner_id=:owner') if conn.dialect.name == 'postgresql' else text('UPDATE af_workflow_runs SET body=:body WHERE id=:id AND owner_id=:owner'),
                     {'body': canonical(body), 'id': body['id'], 'owner': body['ownerId']})

    def require_plan_current(self, owner, plan, tool_name=None, run_context=None):
        return require_workflow_plan_current(owner, plan, definitions=self.definitions, runtimes=self.runtimes,
                                             tool_name=tool_name, run_context=run_context)

    def _current(self, ctx, tool='workflow_read'):
        plan = self.store.authorize_tool(ctx, tool)
        task = self.store.task(ctx.session_id, ctx.user_id)
        require(task['run_id'] == ctx.run_id and not task['cancel_requested'] and not task['terminal'])
        plan = {key: value for key, value in plan.items() if key not in {'taskId', 'runId'}}
        definition = self.require_plan_current(ctx.user_id, plan, tool_name=tool, run_context=ctx)
        require(definition is not None)
        return task, plan, cast(dict, definition)

    def _bound(self, ctx, tool='workflow_read'):
        task, plan, definition = self._current(ctx, tool)
        with self.store.engine.connect() as conn:
            row = conn.execute(text('SELECT id FROM af_workflow_runs WHERE task_id=:task AND owner_id=:owner'),
                               {'task': task['id'], 'owner': ctx.user_id}).first()
            require(row is not None)
            body = self._load(conn, row[0], ctx.user_id)
        require(body['nativeRunId'] == ctx.run_id and body['planId'] == task['plan_id']
                and body['planSha256'] == digest(plan) and body['definition'] == definition
                and not body['cancelRequested'])
        return body

    def _command(self, conn, body, request_id, operation):
        require(type(request_id) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', request_id))
        fingerprint = digest(operation)
        row = conn.execute(text('SELECT fingerprint FROM af_workflow_commands WHERE workflow_id=:id AND request_id=:request'),
                           {'id': body['id'], 'request': request_id}).first()
        if row:
            require(row[0] == fingerprint)
            return False
        statement = 'INSERT INTO af_workflow_commands VALUES(:id,:request,:fp,' + ('CAST(:body AS JSONB)' if conn.dialect.name == 'postgresql' else ':body') + ')'
        conn.execute(text(statement), {'id': body['id'], 'request': request_id, 'fp': fingerprint, 'body': canonical(operation)})
        return True

    def open(self, ctx, request_id):
        task, plan, definition = self._current(ctx)
        with self._transaction() as conn:
            if conn.dialect.name == 'postgresql':
                # Serialize first custody publication with Store terminal release.
                current = conn.execute(text('SELECT * FROM af_tasks WHERE id=:task FOR UPDATE'),
                                       {'task': task['id']}).mappings().first()
                require(current is not None and not current['terminal'] and not current['cancel_requested']
                        and current['owner_id'] == ctx.user_id and current['run_id'] == ctx.run_id
                        and current['plan_id'] == task['plan_id'])
            row = conn.execute(text('SELECT id FROM af_workflow_runs WHERE task_id=:task'), {'task': task['id']}).first()
            if row:
                body = self._load(conn, row[0], ctx.user_id)
                require(body['nativeRunId'] == ctx.run_id and body['planSha256'] == digest(plan))
            else:
                body = {'schema': 1, 'version': 0, 'id': str(uuid4()), 'ownerId': ctx.user_id, 'taskId': task['id'],
                    'nativeRunId': ctx.run_id, 'planId': task['plan_id'], 'planSha256': digest(plan),
                    'applicationRef': deepcopy(plan['applicationRef']), 'inputValues': deepcopy(plan.get('inputValues', {})),
                    'status': 'ACTIVE', 'definition': definition, 'definitionSha256': workflow_fingerprint(definition), 'cancelRequested': False,
                    'stages': {stage['id']: {'state': 'HUMAN_WAIT' if stage['humanGate'] else 'PENDING', 'operationId': None, 'handle': None, 'observation': None,
                        'approved': not stage['humanGate']} for stage in definition['stages']}}
                statement = 'INSERT INTO af_workflow_runs VALUES(:id,:owner,:task,:run,' + ('CAST(:body AS JSONB)' if conn.dialect.name == 'postgresql' else ':body') + ')'
                conn.execute(text(statement), {'id': body['id'], 'owner': ctx.user_id, 'task': task['id'], 'run': ctx.run_id, 'body': canonical(body)})
            self._command(conn, body, request_id, {'kind': 'open'})
            return deepcopy(body)

    def read(self, owner, identifier):
        self.auth.require(owner, 'read')
        with self.store.engine.connect() as conn:
            body = self._load(conn, identifier, owner)
        self.store.task(body['taskId'], owner)
        return body

    def snapshot_task(self, owner, task_id):
        self.auth.require(owner, 'read'); self.store.task(task_id, owner)
        with self.store.engine.connect() as conn:
            row = conn.execute(text('SELECT id FROM af_workflow_runs WHERE task_id=:task AND owner_id=:owner'), {'task': task_id, 'owner': owner}).first()
            return None if row is None else self._load(conn, row[0], owner)

    def _stage(self, body, stage_id):
        stages = [stage for stage in body['definition']['stages'] if stage['id'] == stage_id]
        require(len(stages) == 1)
        return stages[0]

    def admissible(self, body, stage_id):
        stage = self._stage(body, stage_id)
        entry = body['stages'][stage_id]
        if body['cancelRequested'] or entry['state'] != 'PENDING' or not entry['approved']:
            return False
        incoming = [source for source in body['definition']['stages'] if stage_id in source['failureRoutes'].values()]
        if incoming and not any(self._routed(body, source, stage_id) for source in incoming):
            return False
        return all(self._satisfied(body, dep) or self._routed(body, self._stage(body, dep), stage_id)
                   for dep in stage['dependencies'])

    def _routed(self, body, source, destination):
        entry = body['stages'][source['id']]
        failure = (entry['observation'] or {}).get('failure')
        return entry['state'] == 'FAILED' and failure is not None and source['failureRoutes'].get(failure['code']) == destination

    def _satisfied(self, body, stage_id):
        entry = body['stages'][stage_id]
        if entry['state'] == 'COMPLETED':
            return True
        if entry['state'] != 'FAILED':
            return False
        stage = self._stage(body, stage_id)
        target = stage['failureRoutes'].get(entry['observation']['failure']['code'])
        return target is not None and self._satisfied(body, target)

    def finish(self, ctx, request_id):
        body = self._bound(ctx, 'workflow_finish')
        with self._transaction() as conn:
            current = self._load(conn, body['id'], body['ownerId'])
            if not self._command(conn, current, request_id, {'kind': 'finish'}):
                return current
            routed = {destination for stage in current['definition']['stages'] for destination in stage['failureRoutes'].values()}
            inactive = {identifier for identifier in routed if not any(self._routed(current, source, identifier)
                        for source in current['definition']['stages'])}
            require(all(entry['operationId'] is None for identifier, entry in current['stages'].items() if identifier in inactive))
            require(all(self._satisfied(current, identifier) for identifier in current['stages'] if identifier not in inactive))
            for identifier in inactive:
                current['stages'][identifier]['state'] = 'SKIPPED'
            current['status'] = 'COMPLETED'
            self._save(conn, current)
            return current

    def _runtime_context(self, body, stage):
        return WorkflowContext(workflow_id=body['id'], run_id=body['nativeRunId'], owner_id=body['ownerId'],
                               stage_id=stage['id'], definition_sha256=body['definitionSha256'])

    def _accept(self, body, stage_id, observation):
        stage = self._stage(body, stage_id)
        with self._transaction() as conn:
            current = self._load(conn, body['id'], body['ownerId']); entry = current['stages'][stage_id]
            require(entry['operationId'] == body['stages'][stage_id]['operationId'])
            result = validate_runtime_observation(observation, operation_id=entry['operationId'], adapter_id=stage['adapterId'],
                revision=stage['revision'], previous_handle=entry['handle'])
            if entry['state'] in TERMINAL:
                require(result == entry['observation'])
                return current
            entry.update(state=result['state'], handle=result['handle'], observation=result)
            self._save(conn, current)
            return current

    async def choose(self, ctx, stage_id, request_id, *, expected_version=None, command_kind='choose'):
        body = self._bound(ctx, 'workflow_choose'); stage = self._stage(body, stage_id)
        with self._transaction() as conn:
            current = self._load(conn, body['id'], body['ownerId'])
            if not self._command(conn, current, request_id, {'kind': command_kind, 'stageId': stage_id, 'version': expected_version}):
                return current
            require(expected_version is None or (type(expected_version) is int and current['version'] == expected_version))
            require(self.admissible(current, stage_id))
            require(sum(entry['operationId'] is not None and entry['state'] not in TERMINAL for entry in current['stages'].values())
                    < current['definition']['maxParallel'])
            current['stages'][stage_id].update(state='UNKNOWN', operationId=str(uuid4()))
            self._save(conn, current); body = current
        # An exception here retains UNKNOWN and the original operation ID.
        self._bound(ctx, 'workflow_choose')
        runtime = self.runtimes[(stage['adapterId'], stage['revision'])]
        inputs = {'values': body['inputValues'], 'stage': stage['inputs'],
                  'dependencies': {dep: body['stages'][dep]['observation'] for dep in stage['dependencies']}}
        try:
            result = await runtime.start(self._runtime_context(body, stage), body['stages'][stage_id]['operationId'], deepcopy(inputs))
        except WorkflowAcknowledgementUnknown:
            # Only an explicit adapter ambiguity is a recoverable observation.
            # Read current custody again: cancellation/authority loss still fails.
            return self._bound(ctx, 'workflow_choose')
        return self._accept(body, stage_id, result)

    async def inspect(self, ctx, stage_id):
        body = self._bound(ctx, 'workflow_inspect'); stage = self._stage(body, stage_id); entry = body['stages'][stage_id]
        if entry['handle'] is None or entry['state'] in TERMINAL:
            return body
        result = await self.runtimes[(stage['adapterId'], stage['revision'])].inspect(self._runtime_context(body, stage), deepcopy(entry['handle']))
        return self._accept(body, stage_id, result)

    async def reconcile(self, ctx, stage_id, request_id, *, expected_version):
        body = self._bound(ctx, 'workflow_inspect'); stage = self._stage(body, stage_id)
        with self._transaction() as conn:
            current = self._load(conn, body['id'], body['ownerId'])
            if not self._command(conn, current, request_id, {'kind': 'reconcile', 'stageId': stage_id, 'version': expected_version}):
                return current
            require(type(expected_version) is int and current['version'] == expected_version)
            require(current['stages'][stage_id]['operationId'] is not None)
            body = current
        entry = body['stages'][stage_id]
        if entry['state'] in TERMINAL:
            return body
        if entry['handle'] is not None:
            return await self.inspect(ctx, stage_id)
        lookup = getattr(self.runtimes[(stage['adapterId'], stage['revision'])], 'lookup', None)
        if not callable(lookup):
            return body
        self._bound(ctx, 'workflow_inspect')
        result = await cast(Any, lookup)(self._runtime_context(body, stage), entry['operationId'])
        return self._accept(body, stage_id, result)

    def decide(self, ctx, stage_id, approved, request_id, *, expected_version):
        require(type(approved) is bool)
        body = self._bound(ctx); stage = self._stage(body, stage_id)
        require(stage['humanGate'])
        with self._transaction() as conn:
            current = self._load(conn, body['id'], body['ownerId'])
            if self._command(conn, current, request_id, {'kind': 'decide', 'stageId': stage_id, 'approved': approved, 'version': expected_version}):
                require(type(expected_version) is int and current['version'] == expected_version)
                require(current['stages'][stage_id]['state'] in {'PENDING', 'HUMAN_WAIT'} and current['stages'][stage_id]['operationId'] is None)
                current['stages'][stage_id]['approved'] = approved
                current['stages'][stage_id]['state'] = 'PENDING' if approved else 'HUMAN_WAIT'
                self._save(conn, current)
            return current

    async def resume(self, ctx, stage_id, request_id, *, expected_version):
        return await self.choose(ctx, stage_id, request_id, expected_version=expected_version, command_kind='resume')

    def for_task(self, owner, task_id):
        return self.snapshot_task(owner, task_id)

    def task_held(self, task_id):
        # Reuse an active Store transaction during admission/terminal checks;
        # borrowing another metadata connection can deadlock a one-slot pool.
        rows = self.store.sql('SELECT body FROM af_workflow_runs WHERE task_id=:task', task=task_id)
        return bool(rows) and decoded(rows[0]['body'])['status'] not in {'COMPLETED', 'CANCELLED'}

    async def cancel(self, owner, identifier):
        # Cleanup uses original owned task custody, not a fresh execution grant.
        with self._transaction() as conn:
            body = self._load(conn, identifier, owner)
            task = self.store.task(body['taskId'], owner)
            require(task['run_id'] == body['nativeRunId'] and task['plan_id'] == body['planId'])
            if body['status'] in {'COMPLETED', 'CANCELLED'}:
                return True
            body['cancelRequested'] = True
            self._save(conn, body)
        for stage in body['definition']['stages']:
            entry = body['stages'][stage['id']]
            try:
                runtime = self.runtimes[(stage['adapterId'], stage['revision'])]
                lookup = getattr(runtime, 'lookup', None)
                if entry['operationId'] is not None and entry['handle'] is None and callable(lookup):
                    result = await cast(Any, lookup)(self._runtime_context(body, stage), entry['operationId'])
                    body = self._accept(body, stage['id'], result)
                    entry = body['stages'][stage['id']]
                if entry['handle'] is not None and entry['state'] not in TERMINAL:
                    result = await runtime.cancel(self._runtime_context(body, stage), deepcopy(entry['handle']))
                    body = self._accept(body, stage['id'], result)
            except Exception:
                # One uncertain adapter must not prevent stopping independent
                # original handles. Its persisted state continues to hold custody.
                continue
        with self._transaction() as conn:
            body = self._load(conn, identifier, owner)
            stopped = all(entry['operationId'] is None or entry['state'] in TERMINAL for entry in body['stages'].values())
            if stopped:
                for entry in body['stages'].values():
                    if entry['operationId'] is None and entry['state'] != 'SKIPPED':
                        entry['state'] = 'CANCELLED'
                body['status'] = 'CANCELLED'; self._save(conn, body)
            return stopped

    async def cancel_task(self, owner, task_id):
        task = self.store.task(task_id, owner)
        with self.store.engine.connect() as conn:
            row = conn.execute(text('SELECT id FROM af_workflow_runs WHERE task_id=:task AND owner_id=:owner'),
                               {'task': task_id, 'owner': owner}).first()
            if row is None:
                return True
            body = self._load(conn, row[0], owner)
            require(body['nativeRunId'] == task['run_id'] and body['planId'] == task['plan_id'])
        return await self.cancel(owner, body['id'])

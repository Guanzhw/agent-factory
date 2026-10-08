"""Original external-effect custody, independent of native workflow progress.

No stages, routes, approvals, scheduler, or workflow completion live here. The
caller supplies the persisted native step invocation, never a model-selected
replacement. An uncertain dispatch can only be looked up, inspected or stopped.
"""
from copy import deepcopy
import json
import re
from uuid import uuid4

from fastapi import HTTPException

from .input_schema import bounded_json
from .store import canonical, digest
from .workflow_contracts import WorkflowAcknowledgementUnknown, WorkflowContext, validate_runtime_observation

ERROR = 'EXTERNAL_OPERATION_CUSTODY_INVALID'


def require(value):
    if not value:
        raise HTTPException(409, ERROR)


def identifier(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', value) is not None


class OperationCustody:
    def __init__(self, store, auth, *, runtimes):
        self.store, self.auth = store, auth
        self.runtimes = dict(runtimes)
        for key, runtime in self.runtimes.items():
            require(type(key) is tuple and len(key) == 3 and all(identifier(v) for v in key[:2])
                and type(key[2]) is str and re.fullmatch('[a-f0-9]{64}', key[2]) is not None
                and all(callable(getattr(runtime, method, None)) for method in ('start', 'inspect', 'lookup', 'cancel')))
        self.store.sql('CREATE TABLE IF NOT EXISTS af_external_operations ('
            'id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,task_id TEXT NOT NULL,'
            'native_run_id TEXT NOT NULL,effect_slot TEXT NOT NULL,closed BOOLEAN NOT NULL,'
            'body JSONB NOT NULL,UNIQUE(native_run_id,effect_slot))')
        if self._postgres:
            self._repair_accounting()

    @property
    def _postgres(self):
        return self.store.engine.dialect.name == 'postgresql'

    def _lock_task(self, owner, task_id):
        rows = self.store.sql('SELECT id FROM af_tasks WHERE id=:id AND owner_id=:owner'
            + (' FOR UPDATE' if self._postgres else ''), id=task_id, owner=owner)
        if len(rows) != 1:
            raise HTTPException(404, 'EXTERNAL_OPERATION_NOT_FOUND')

    def _load(self, owner, operation_id):
        rows = self.store.sql('SELECT * FROM af_external_operations WHERE id=:id AND owner_id=:owner',
            id=operation_id, owner=owner)
        if len(rows) != 1:
            raise HTTPException(404, 'EXTERNAL_OPERATION_NOT_FOUND')
        row = rows[0]
        body = json.loads(row['body']) if isinstance(row['body'], str) else deepcopy(row['body'])
        require(body['id'] == row['id'] and body['ownerId'] == row['owner_id']
            and body['taskId'] == row['task_id'] and body['nativeRunId'] == row['native_run_id']
            and body['effectSlot'] == row['effect_slot'] and body['closed'] == bool(row['closed']))
        require(type(body['closed']) is bool and type(body['cancelRequested']) is bool)
        if body['observation'] is None:
            require(body['handle'] is None and not body['closed'])
        else:
            pin = body['adapterPin']
            observed = validate_runtime_observation(body['observation'], body['id'],
                pin['adapterId'], pin['revision'], previous_handle=body['handle'])
            require(observed['handle'] == body['handle'] and observed['allStopped'] == body['closed'])
        return body

    def _identity(self, body):
        task = self.store.task(body['taskId'], body['ownerId'])
        plan = self.store.plan(task['plan_id'], body['ownerId'])
        require(task['run_id'] == body['nativeRunId'] and task['plan_id'] == body['planId']
            and digest(plan) == body['planSha256'])
        return task, plan

    def _original(self, body):
        task, plan = self._identity(body)
        pin = body['adapterPin']
        runtime = self.runtimes.get((pin['adapterId'], pin['revision'], pin['configFingerprint']))
        require(runtime is not None)
        assert runtime is not None
        return task, plan, runtime

    def _repair_accounting(self):
        """Rehold exact original custody; no registration or backend call needed.

        Native completion is not evidence that an external operation stopped.
        Only accounting flags change, never native progress or custody receipts.
        """
        with self.store.transaction():
            rows = self.store.sql('SELECT id,owner_id,task_id FROM af_external_operations WHERE NOT closed')
            held = set()
            for row in rows:
                try:
                    self._lock_task(row['owner_id'], row['task_id'])
                    body = self._load(row['owner_id'], row['id'])
                    self._identity(body)
                    if not body['closed']:
                        held.add((body['ownerId'], body['taskId']))
                except (HTTPException, ValueError, KeyError, TypeError):
                    # An inconsistent/foreign binding is never adopted.
                    continue
            pending = list(held)
            while pending and getattr(self.store, 'delegation', None) is not None:
                owner, child = pending.pop()
                links = self.store.sql('SELECT link.parent_id,link.root_id FROM af_delegation_links link '
                    'JOIN af_tasks child ON child.id=link.child_id AND child.owner_id=link.owner_id '
                    'AND child.plan_id=link.plan_id WHERE link.child_id=:child AND link.owner_id=:owner',
                    child=child, owner=owner)
                for link in links:
                    for identifier in (link['parent_id'], link['root_id']):
                        if (owner, identifier) in held:
                            continue
                        try:
                            self._lock_task(owner, identifier)
                        except HTTPException:
                            continue
                        held.add((owner, identifier))
                        pending.append((owner, identifier))
            for owner, identifier in held:
                self.store.sql('UPDATE af_tasks SET terminal=FALSE WHERE id=:id AND owner_id=:owner',
                    id=identifier, owner=owner)
                self.store.sql("UPDATE af_disk_holds SET state='HELD' WHERE task_id=:id AND owner_id=:owner AND state='RELEASED'",
                    id=identifier, owner=owner)
                if getattr(self.store, 'delegation', None) is not None:
                    self.store.sql('UPDATE af_delegation_roots SET reclaimed=FALSE WHERE root_id=:id AND owner_id=:owner',
                        id=identifier, owner=owner)

    def _fresh(self, ctx):
        task = self.store.task(ctx.session_id, ctx.user_id)
        require(task['run_id'] == ctx.run_id and not task['terminal'] and not task['cancel_requested'])
        plan = self.store.plan(task['plan_id'], ctx.user_id)
        self.auth.require(ctx.user_id, 'run')
        self.store.require_plan_execution(ctx.user_id, plan, run_context=ctx)
        return task, plan

    def _context(self, body):
        return WorkflowContext(workflow_id=body['taskId'], run_id=body['nativeRunId'],
            owner_id=body['ownerId'], stage_id=body['stepId'], definition_sha256=body['planSha256'])

    def _save(self, body):
        body['version'] += 1
        value = 'CAST(:body AS JSONB)' if self._postgres else ':body'
        result = self.store.sql('UPDATE af_external_operations SET body=' + value
            + ',closed=:closed WHERE id=:id AND owner_id=:owner RETURNING id',
            body=canonical(body), closed=body['closed'], id=body['id'], owner=body['ownerId'])
        require(len(result) == 1)

    async def start(self, ctx, step_id, effect_slot, adapter_pin, inputs):
        require(identifier(step_id) and identifier(effect_slot) and type(adapter_pin) is dict
            and set(adapter_pin) == {'adapterId', 'revision', 'configFingerprint'})
        pin = deepcopy(adapter_pin)
        require(all(identifier(pin[k]) for k in ('adapterId', 'revision'))
            and type(pin['configFingerprint']) is str and re.fullmatch('[a-f0-9]{64}', pin['configFingerprint']) is not None)
        require(type(inputs) is dict)
        checked_inputs = bounded_json(inputs, maximum=16384)
        slot = 'external-operation:' + digest({'stepId': step_id, 'slot': effect_slot})
        with self.store.transaction():
            self._lock_task(ctx.user_id, ctx.session_id)
            task, plan = self._fresh(ctx)
            request = {'taskId': task['id'], 'nativeRunId': ctx.run_id, 'planSha256': digest(plan),
                'stepId': step_id, 'effectSlot': slot, 'adapterPin': pin, 'inputsSha256': digest(checked_inputs)}
            reserved = self.store.effect_reserve(ctx.run_id, slot, request)
            rows = self.store.sql('SELECT id FROM af_external_operations WHERE native_run_id=:run AND effect_slot=:slot',
                run=ctx.run_id, slot=slot)
            if rows:
                body = self._load(ctx.user_id, rows[0]['id'])
                require(body['requestSha256'] == digest(request))
                self._original(body)
                return body
            require(reserved['status'] == 'new')
            body = {'schema': 1, 'id': str(uuid4()), 'ownerId': ctx.user_id,
                'taskId': task['id'], 'nativeRunId': ctx.run_id, 'planId': task['plan_id'],
                'planSha256': digest(plan), 'stepId': step_id, 'effectSlot': slot, 'adapterPin': pin,
                'inputsSha256': digest(checked_inputs), 'requestSha256': digest(request),
                'version': 0, 'closed': False, 'cancelRequested': False, 'handle': None, 'observation': None}
            self._original(body)
            value = 'CAST(:body AS JSONB)' if self._postgres else ':body'
            self.store.sql('INSERT INTO af_external_operations VALUES(:id,:owner,:task,:run,:slot,FALSE,' + value + ')',
                id=body['id'], owner=ctx.user_id, task=task['id'], run=ctx.run_id, slot=slot, body=canonical(body))
        # Intent is durable first. No SQL connection is held over adapter awaits.
        self._fresh(ctx)
        body = self._load(ctx.user_id, body['id'])
        require(not body['cancelRequested'] and not body['closed'])
        _, _, runtime = self._original(body)
        try:
            observed = await runtime.start(self._context(body), body['id'], checked_inputs)
        except WorkflowAcknowledgementUnknown:
            self._fresh(ctx)
            return self.read(ctx.user_id, body['id'])
        return self._accept(body, observed)

    def read(self, owner, operation_id):
        self.auth.require(owner, 'read')
        body = self._load(owner, operation_id)
        self._identity(body)
        return body

    def _accept(self, original, observed):
        with self.store.transaction():
            self._lock_task(original['ownerId'], original['taskId'])
            body = self._load(original['ownerId'], original['id'])
            self._original(body)
            pin = body['adapterPin']
            result = validate_runtime_observation(observed, body['id'], pin['adapterId'], pin['revision'],
                previous_handle=body['handle'])
            if body['closed']:
                # A late read cannot regress or replace original terminal proof.
                return body
            body.update(handle=result['handle'], observation=result, closed=result['allStopped'])
            self._save(body)
            if body['closed']:
                self.store.effect_complete(body['nativeRunId'], body['effectSlot'],
                    {'operationId': body['id'], 'observation': result, 'cancelled': result['state'] == 'CANCELLED'})
            return body

    async def inspect(self, owner, operation_id):
        body = self.read(owner, operation_id)
        if body['closed'] or body['handle'] is None:
            return body
        _, _, runtime = self._original(body)
        return self._accept(body, await runtime.inspect(self._context(body), deepcopy(body['handle'])))

    async def lookup(self, owner, operation_id):
        body = self.read(owner, operation_id)
        if body['closed']:
            return body
        _, _, runtime = self._original(body)
        return self._accept(body, await runtime.lookup(self._context(body), body['id']))

    async def cancel(self, owner, operation_id):
        # Internal cleanup is original custody, not a new execution grant.
        body = self._load(owner, operation_id)
        with self.store.transaction():
            self._lock_task(owner, body['taskId'])
            body = self._load(owner, operation_id)
            self._original(body)
            if body['closed']:
                return body
            body['cancelRequested'] = True
            self._save(body)
        _, _, runtime = self._original(body)
        if body['handle'] is None:
            body = self._accept(body, await runtime.lookup(self._context(body), body['id']))
        if not body['closed'] and body['handle'] is not None:
            body = self._accept(body, await runtime.cancel(self._context(body), deepcopy(body['handle'])))
        return body

    def task_held(self, task_id):
        rows = self.store.sql('SELECT id,owner_id,closed FROM af_external_operations WHERE task_id=:task', task=task_id)
        for row in rows:
            if not row['closed']:
                return True
            try:
                if not self._load(row['owner_id'], row['id'])['closed']:
                    return True
            except (HTTPException, ValueError, KeyError, TypeError):
                return True
        return False

    async def cancel_task(self, owner, task_id):
        self.store.task(task_id, owner)
        rows = self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task AND owner_id=:owner AND NOT closed',
            task=task_id, owner=owner)
        for row in rows:
            try:
                await self.cancel(owner, row['id'])
            except Exception:
                # Continue independent original operations; unresolved ones hold.
                continue
        return not self.task_held(task_id)

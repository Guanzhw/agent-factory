"""Governed commands and read projections over native Workflow state.

Only Agno stores workflow progress. This journal binds user intent to native
requirements/acceptance; external-operation custody remains a separate ledger.
"""
from copy import deepcopy
import json
from typing import Any, Literal

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.run.requirement import RunRequirement
from agno.workflow.types import StepRequirement
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from .control_commands import ControlCommand
from .input_schema import bounded_json
from .store import canonical, digest


def require(value):
    if not value:
        raise HTTPException(409, 'NATIVE_WORKFLOW_COMMAND_CONFLICT')


class WorkflowCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    commandId: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_.:-]+$')
    action: Literal['decide', 'reconcile', 'cancel']
    version: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    requirementId: str | None = None
    operationId: str | None = None
    approved: StrictBool | None = None
    values: dict[str, Any] | None = None

    @model_validator(mode='after')
    def exact(self):
        fields = self.model_fields_set - {'commandId', 'action'}
        if self.action == 'cancel':
            require(not fields)
        elif self.action == 'reconcile':
            require(fields == {'version', 'operationId'} and self.version and self.operationId)
        else:
            require(fields in ({'version', 'requirementId', 'approved'}, {'version', 'requirementId', 'values'})
                    and self.version and self.requirementId)
            if self.values is not None:
                bounded_json(self.values, maximum=16384)
        return self


class WorkflowControl:
    def __init__(self, service, api):
        self.service, self.api = service, api
        self.store, self.auth = api.store, api.auth
        self.store.sql('CREATE TABLE IF NOT EXISTS af_native_workflow_commands ('
            'owner_id TEXT NOT NULL,command_id TEXT NOT NULL,task_id TEXT NOT NULL,'
            'boundary TEXT NOT NULL,body JSONB NOT NULL,PRIMARY KEY(owner_id,command_id),'
            'UNIQUE(task_id,boundary))')

    def context(self, task):
        return RunContext(run_id=task['run_id'], session_id=task['id'], user_id=task['owner_id'],
            session_state={'factory_envelope': {'plan_ref': task['plan_id'], 'user_id': task['owner_id'],
                'task_id': task['id'], 'request_id': task['request_id']}})

    def _operations(self, task):
        rows = self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task AND owner_id=:owner ORDER BY id',
                              task=task['id'], owner=task['owner_id'])
        return [self.service.read(task['owner_id'], row['id']) for row in rows]

    async def _native(self, owner, task_id):
        self.auth.require(owner, 'read')
        task = self.store.task(task_id, owner)
        plan = self.store.plan(task['plan_id'], owner)
        if plan.get('nativeComponent', {}).get('kind') != 'workflow':
            return task, plan, None
        require(task.get('run_id'))
        native = await self.api.bridge.detail(task['run_id'], task['id'], owner)
        require(native.get('run_id') == task['run_id'] and native.get('workflow_id') == plan['nativeComponent']['id'])
        return task, plan, native

    @staticmethod
    def _requirements(native):
        return [item for item in native.get('step_requirements') or []
                if not StepRequirement.from_dict(item).is_resolved]

    def _view(self, task, plan, native):
        operations = self._operations(task)
        requirements = self._requirements(native)
        steps = []
        def collect(items, depth=0):
            require(depth <= 8)
            for item in items:
                require(len(steps) < 128)
                steps.append({'id': item.get('step_id') or item.get('step_name') or str(len(steps)),
                    'name': item.get('step_name') or 'Native step',
                    'status': 'paused' if item.get('is_paused') else 'failed' if item.get('success') is False else 'completed'})
                if item.get('steps'):
                    collect(item['steps'], depth + 1)
        collect(native.get('step_results') or [])
        projected_requirements = []
        for req in requirements:
            kind = 'external' if req.get('requires_executor_input') else 'input' if req.get('requires_user_input') else 'confirmation'
            projected_requirements.append({'id': digest(req), 'stepName': req.get('step_name') or req['step_id'],
                'kind': kind, 'fields': [{'name': field['name'], 'type': field.get('field_type', 'str'),
                    'required': field.get('required', False)} for field in req.get('user_input_schema') or []]})
        view = {'schema': 2, 'id': plan['nativeComponent']['id'], 'ownerId': task['owner_id'],
            'taskId': task['id'], 'nativeRunId': task['run_id'], 'planId': plan['id'], 'planSha256': digest(plan),
            'status': native.get('status', 'unknown'), 'steps': steps, 'requirements': projected_requirements,
            'operations': [{'id': op['id'], 'stepId': op['stepId'],
                'state': (op['observation'] or {}).get('state', 'UNKNOWN'), 'allStopped': op['closed']} for op in operations]}
        view['version'] = digest({'view': view, 'requirements': requirements, 'queue': (native.get('queue') or {}).get('status'),
                                  'operations': [(op['id'], op['version']) for op in operations]})
        return view

    async def snapshot(self, owner, task_id):
        task, plan, native = await self._native(owner, task_id)
        if native is None:
            return {'available': False}
        view = self._view(task, plan, native)
        actions = [{'action': 'cancel'}]
        try:
            self.store.require_plan_execution(owner, plan, run_context=self.context(task))
            if not task['cancel_requested'] and not task['terminal'] and (native.get('queue') or {}).get('status') == 'paused':
                actions += [{'action': 'decide', 'requirementId': req['id']}
                    for req in view['requirements'] if req['kind'] in {'confirmation', 'input'}]
        except (HTTPException, PermissionError, RunCancelledException):
            pass
        actions += [{'action': 'reconcile', 'operationId': op['id']} for op in view['operations'] if not op['allStopped']]
        return {'available': True, 'workflow': view, 'allowedActions': actions}

    def _load(self, owner, task_id, command_id):
        rows = self.store.sql('SELECT body,task_id FROM af_native_workflow_commands WHERE owner_id=:owner AND command_id=:id',
                              owner=owner, id=command_id)
        if not rows:
            raise HTTPException(404, 'NATIVE_WORKFLOW_COMMAND_NOT_FOUND')
        require(rows[0]['task_id'] == task_id)
        return json.loads(rows[0]['body']) if isinstance(rows[0]['body'], str) else deepcopy(rows[0]['body'])

    def _save(self, owner, command_id, body):
        value = 'CAST(:body AS JSONB)' if self.store.engine.dialect.name == 'postgresql' else ':body'
        self.store.sql('UPDATE af_native_workflow_commands SET body=' + value + ' WHERE owner_id=:owner AND command_id=:id',
                       owner=owner, id=command_id, body=canonical(body))

    @staticmethod
    def _cancel_status(receipt):
        return ('completed' if receipt.get('stopConfirmed') else 'recorded' if receipt.get('decisionRecorded')
                else 'rejected' if receipt.get('state') == 'REJECTED' else 'unknown')

    async def receipt(self, owner, task_id, command_id):
        task, plan, native = await self._native(owner, task_id)
        require(native is not None)
        assert native is not None
        row = self._load(owner, task_id, command_id)
        receipt = row['receipt']
        if row.get('cancelCommand') and receipt['status'] in {'recorded', 'unknown'}:
            try:
                cancel = await self.api.commands.recover(owner, task_id, row['cancelCommand'])
            except HTTPException as error:
                if error.status_code != 404:
                    raise
            else:
                receipt['status'] = self._cancel_status(cancel)
                self._save(owner, command_id, row)
        submitted = row.get('submitted')
        if receipt['status'] in {'recorded', 'unknown'} and submitted is not None:
            accepted = ((native.get('queue') or {}).get('payload') or {}).get('continue', {}).get('step_requirements')
            # Native ticket proves this exact continuation. A changed body is not
            # accepted merely because the native queue attached an older click.
            if accepted == submitted:
                receipt['status'] = 'completed'
                receipt['nativeEvidence'] = {'runId': task['run_id'], 'requirementsSha256': digest(submitted)}
                self._save(owner, command_id, row)
        return {**receipt, 'workflow': self._view(task, plan, native)}

    def _external(self, task, req):
        if not req.get('requires_executor_input'):
            return None
        updated = deepcopy(req)
        requirements = updated.get('executor_requirements') or []
        require(len(requirements) == 1)
        wrapper = requirements[0]
        execution = wrapper.get('tool_execution') or {}
        require(execution.get('tool_name') == 'factory_wait_operations' and execution.get('external_execution_required')
                and execution.get('result') is None and execution.get('tool_call_id'))
        ids = (execution.get('tool_args') or {}).get('operationIds')
        require(type(ids) is list and 0 < len(ids) <= 16 and len(ids) == len(set(ids)))
        assert isinstance(ids, list)
        operations = [self.service.read(task['owner_id'], identifier) for identifier in ids]
        require(all(op['taskId'] == task['id'] and op['nativeRunId'] == task['run_id'] for op in operations))
        if not all(op['closed'] for op in operations):
            return None
        resolved = RunRequirement.from_dict(wrapper)
        resolved.set_external_execution_result(canonical({'operations': [op['observation'] for op in operations]}))
        # Agno consumes the original external-execution flag to insert the tool
        # result message. Clearing it here would silently discard that result.
        updated['executor_requirements'] = [resolved.to_dict()]
        return updated

    async def submit(self, owner, task_id, command):
        intent = command.model_dump(exclude_none=True)
        task, plan, native = await self._native(owner, task_id)
        require(native is not None)
        assert native is not None
        try:
            prior = self._load(owner, task_id, command.commandId)
        except HTTPException as error:
            if error.status_code != 404:
                raise
        else:
            require(prior['intent'] == intent)
            return await self.receipt(owner, task_id, command.commandId)
        self.auth.require(owner, 'run')
        view = self._view(task, plan, native)
        if command.action != 'cancel':
            require(command.version == view['version'])
        submitted = None
        original_requirement = None
        if command.action == 'decide':
            self.store.require_plan_execution(owner, plan, run_context=self.context(task))
            require(not task['cancel_requested'] and not task['terminal'] and (native.get('queue') or {}).get('status') == 'paused')
            originals = self._requirements(native)
            require(len(originals) == 1 and digest(originals[0]) == command.requirementId)
            original = originals[0]
            req = StepRequirement.from_dict(original)
            if req.requires_confirmation and command.approved is not None:
                req.confirm() if command.approved else req.reject()
            elif req.requires_user_input and command.values is not None:
                require(not set(command.values) - {field.name for field in req.user_input_schema or []})
                req.set_user_input(**command.values)
            else:
                raise HTTPException(409, 'UNSUPPORTED_NATIVE_REQUIREMENT')
            require(req.is_resolved)
            submitted = [req.to_dict()]
            original_requirement = digest(original)
        elif command.action == 'reconcile':
            original = self.service.read(owner, command.operationId)
            require(original['taskId'] == task_id)
        boundary = 'cancel' if command.action == 'cancel' else digest({'version': command.version,
            'requirement': command.requirementId, 'operation': command.operationId})
        row = {'intent': intent, 'receipt': {'commandId': command.commandId, 'status': 'recorded'}, 'submitted': submitted}
        if command.action == 'cancel':
            row['cancelCommand'] = command.commandId
        with self.store.transaction():
            suffix = ' FOR UPDATE' if self.store.engine.dialect.name == 'postgresql' else ''
            self.store.sql('SELECT id FROM af_tasks WHERE id=:id AND owner_id=:owner' + suffix, id=task_id, owner=owner)
            occupied = self.store.sql('SELECT command_id FROM af_native_workflow_commands WHERE task_id=:task AND boundary=:boundary',
                                      task=task_id, boundary=boundary)
            require(not occupied)
            value = 'CAST(:body AS JSONB)' if self.store.engine.dialect.name == 'postgresql' else ':body'
            self.store.sql('INSERT INTO af_native_workflow_commands(owner_id,command_id,task_id,boundary,body) '
                'VALUES(:owner,:id,:task,:boundary,' + value + ')', owner=owner, id=command.commandId,
                task=task_id, boundary=boundary, body=canonical(row))
        try:
            if command.action == 'cancel':
                cancelled = await self.api.commands.submit(owner, task_id, ControlCommand(commandId=command.commandId, action='cancel'))
                row['receipt']['status'] = self._cancel_status(cancelled)
                row['cancelCommand'] = command.commandId
            else:
                if command.action == 'reconcile':
                    if original['handle'] is None:
                        await self.service.lookup(owner, command.operationId)
                    else:
                        await self.service.inspect(owner, command.operationId)
                    _, _, native = await self._native(owner, task_id)
                    require(native is not None)
                    assert native is not None
                    originals = self._requirements(native)
                    if (native.get('queue') or {}).get('status') == 'paused' and len(originals) == 1:
                        resolved = self._external(task, originals[0])
                        if resolved is not None:
                            submitted = [resolved]
                            original_requirement = digest(originals[0])
                            row['submitted'] = submitted
                            self._save(owner, command.commandId, row)
                    if submitted is None:
                        row['receipt']['status'] = 'completed'
                if submitted is not None:
                    fresh_task, fresh_plan, fresh_native = await self._native(owner, task_id)
                    require(fresh_native is not None and not fresh_task['cancel_requested'] and not fresh_task['terminal'])
                    assert fresh_native is not None
                    self.store.require_plan_execution(owner, fresh_plan, run_context=self.context(fresh_task))
                    require((fresh_native.get('queue') or {}).get('status') == 'paused')
                    # Decisions are rechecked against their exact original
                    # requirement immediately before the native effect.
                    require([digest(r) for r in self._requirements(fresh_native)] == [original_requirement])
                    for item in submitted:
                        for requirement in item.get('executor_requirements') or []:
                            execution = requirement.get('tool_execution') or {}
                            call_id = 'native-wait:' + digest({'stepId': item['step_id'],
                                'toolCallId': execution['tool_call_id']})
                            self.store.delegation.consume_tool_budget(self.context(task), call_id, 'factory_wait_operations')
                    await self.api.bridge.continue_run(task['run_id'], task_id, owner, submitted)
                    row['receipt']['status'] = 'unknown'
        except Exception as error:
            row['receipt']['status'] = 'unknown'
            row['errorType'] = type(error).__name__
        self._save(owner, command.commandId, row)
        return await self.receipt(owner, task_id, command.commandId)


def workflow_router(auth, control):
    router = APIRouter(prefix='/api/factory/workflows')

    @router.get('/{task_id}')
    async def read(request: Request, task_id: str):
        return await control.snapshot(auth.user(request)['id'], task_id)

    @router.get('/{task_id}/commands/{command_id}')
    async def receipt(request: Request, task_id: str, command_id: str):
        return await control.receipt(auth.user(request)['id'], task_id, command_id)

    @router.post('/{task_id}/commands')
    async def command(request: Request, task_id: str, body: WorkflowCommand):
        return await control.submit(auth.user(request)['id'], task_id, body)

    return router

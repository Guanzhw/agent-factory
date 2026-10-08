"""Owner-scoped workflow decisions and original native external-tool continuation.

No polling scheduler or model replacement. An uncertain command is read back,
never dispatched again; the original runtime operation remains in custody.
"""
from types import SimpleNamespace
from typing import Literal

from agno.exceptions import RunCancelledException
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from sqlalchemy import text

from .control_commands import COMMAND_ID, ControlCommand
from .store import canonical, digest
from .workflow_service import decoded, require


class WorkflowCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    commandId: str = Field(pattern=COMMAND_ID)
    action: Literal['reconcile', 'decide', 'resume', 'cancel']
    stageId: str | None = Field(default=None, min_length=1, max_length=120)
    approved: StrictBool | None = None
    version: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def exact(self):
        if self.action == 'cancel':
            valid = self.stageId is None and self.approved is None and self.version is None
        else:
            valid = self.stageId is not None and self.version is not None
            valid = valid and (self.approved is not None if self.action == 'decide' else self.approved is None)
        if not valid:
            raise ValueError('WORKFLOW_COMMAND_INVALID')
        return self


class WorkflowControl:
    def __init__(self, service, api):
        self.service, self.api, self.store, self.auth = service, api, api.store, api.auth
        with self.store.engine.begin() as conn:
            conn.execute(text('CREATE TABLE IF NOT EXISTS af_workflow_actions (owner_id TEXT NOT NULL, command_id TEXT NOT NULL, task_id TEXT NOT NULL, fingerprint TEXT NOT NULL, body JSONB NOT NULL, PRIMARY KEY(owner_id,command_id))'))

    def context(self, task):
        context = SimpleNamespace(user_id=task['owner_id'], session_id=task['id'], run_id=task['run_id'],
            session_state={'factory_envelope': {'plan_ref': task['plan_id'], 'user_id': task['owner_id'],
                'task_id': task['id'], 'request_id': task['request_id']}})
        plan = self.store.plan(task['plan_id'], task['owner_id'])
        self.store.require_plan_execution(task['owner_id'], plan, run_context=context)
        self.store.execution_bindings.recheck(plan, context)
        return context

    async def require_paused(self, task, stage_id):
        """Explicit resume may only select the stage of the original parked wait."""
        from .auth import EXECUTOR_ID
        from .factory_api import native_requirements
        snapshot = await self.api.bridge.detail(task['run_id'], task['id'], task['owner_id'])
        ticket = snapshot.get('queue') or {}; run = snapshot.get('run', snapshot)
        require(ticket.get('status') == 'paused' and str(run.get('status')).lower() in {'paused', 'runstatus.paused'}
                and ticket.get('id') == task['run_id'] and ticket.get('session_id') == task['id']
                and ticket.get('user_id') == task['owner_id'] and ticket.get('component_type') == 'agent'
                and ticket.get('component_id') == EXECUTOR_ID and ticket.get('job_type', 'run') == 'run'
                and run.get('run_id') == task['run_id']
                and run.get('session_id', task['id']) == task['id']
                and run.get('user_id', task['owner_id']) == task['owner_id']
                and run.get('agent_id', EXECUTOR_ID) == EXECUTOR_ID)
        requirements = [item for item in native_requirements(snapshot)
                        if (item.get('tool_execution') or {}).get('external_execution_required') is True
                        and (item.get('tool_execution') or {}).get('result') is None]
        require(len(requirements) == 1)
        tool = requirements[0].get('tool_execution') or {}
        require(tool.get('tool_name') == 'workflow_wait' and tool.get('tool_args') == {'stageId': stage_id}
                and bool(tool.get('tool_call_id')) and bool(requirements[0].get('id')))
        self.context(self.store.task(task['id'], task['owner_id']))

    async def completion(self, task, requirement):
        from .factory_api import native_requirements, requirement_version
        fresh = self.store.task(task['id'], task['owner_id'])
        require(all(task[key] == fresh[key] for key in ('id', 'owner_id', 'plan_id', 'run_id')))
        context = self.context(fresh)
        body = self.service._bound(context, 'workflow_wait')
        snapshot = await self.api.bridge.detail(task['run_id'], task['id'], task['owner_id'])
        original = next((item for item in native_requirements(snapshot) if item.get('id') == requirement.get('id')), None)
        require(original is not None and requirement_version(original) == requirement_version(requirement))
        assert original is not None
        execution = original.get('tool_execution') or {}
        args = execution.get('tool_args')
        require(execution.get('tool_name') == 'workflow_wait' and execution.get('external_execution_required') is True
                and execution.get('result') is None and bool(execution.get('tool_call_id'))
                and type(args) is dict and set(args) == {'stageId'} and args['stageId'] in body['stages'])
        assert isinstance(args, dict)
        stage_id = args['stageId']; entry = body['stages'][stage_id]
        require(entry['state'] in {'COMPLETED', 'FAILED', 'CANCELLED', 'SKIPPED'} or self.service.admissible(body, stage_id))
        return {'schema': 1, 'workflowId': body['id'], 'nativeRunId': body['nativeRunId'],
                'stageId': stage_id, 'requirementId': original['id'], 'ready': True}

    async def complete_external(self, task, requirement):
        """Mutating continuation boundary; native external tools skip pre-hooks."""
        result = await self.completion(task, requirement)
        context = self.context(self.store.task(task['id'], task['owner_id']))
        self.store.delegation.consume_tool_budget(context,
            requirement['tool_execution']['tool_call_id'], 'workflow_wait')
        return result

    async def continue_ready(self, task):
        from .factory_api import native_requirements, requirement_version
        snapshot = await self.api.bridge.detail(task['run_id'], task['id'], task['owner_id'])
        requirements = [item for item in native_requirements(snapshot)
                        if (item.get('tool_execution') or {}).get('tool_name') == 'workflow_wait'
                        and (item.get('tool_execution') or {}).get('result') is None]
        if len(requirements) != 1:
            return None
        requirement = requirements[0]
        try:
            await self.completion(task, requirement)
        except (ValueError, HTTPException):
            return None
        return await self.api.commands.submit(task['owner_id'], task['id'], ControlCommand(
            commandId='workflow:' + digest({'task': task['id'], 'run': task['run_id'], 'requirement': requirement}),
            action='approve', approved=True, requirementId=requirement['id'], version=requirement_version(requirement)))

    def snapshot(self, owner, task_id):
        body = self.service.for_task(owner, task_id)
        if body is None:
            return {'available': False}
        actions = []
        task = self.store.task(task_id, owner)
        try:
            self.auth.require(owner, 'run')
            self.context(task)
            if not task['terminal'] and not task['cancel_requested'] and body['status'] == 'ACTIVE':
                actions.append({'action': 'cancel'})
                for identifier, entry in body['stages'].items():
                    if entry['state'] == 'HUMAN_WAIT':
                        actions.append({'action': 'decide', 'stageId': identifier})
                    if self.service.admissible(body, identifier):
                        actions.append({'action': 'resume', 'stageId': identifier})
                    if entry['operationId'] is not None:
                        actions.append({'action': 'reconcile', 'stageId': identifier})
        except (ValueError, HTTPException, PermissionError, RunCancelledException):
            pass
        return {'available': True, 'workflow': body, 'allowedActions': actions}

    async def receipt(self, owner, task_id, command_id):
        self.auth.require(owner, 'read'); self.store.task(task_id, owner)
        with self.store.engine.connect() as conn:
            row = conn.execute(text('SELECT task_id,body FROM af_workflow_actions WHERE owner_id=:owner AND command_id=:id'),
                               {'owner': owner, 'id': command_id}).mappings().first()
        if row is None or row['task_id'] != task_id:
            raise HTTPException(404, 'WORKFLOW_COMMAND_NOT_FOUND')
        saved = decoded(row['body'])
        receipt = saved['receipt']
        if receipt['status'] in {'recorded', 'unknown'}:
            intent = saved['intent']
            body = self.service.for_task(owner, task_id)
            if intent['action'] == 'cancel':
                try:
                    native = await self.api.commands.recover(owner, task_id, command_id)
                    if native.get('decisionRecorded') is True:
                        receipt = {**receipt, 'status': 'completed', 'workflow': body, 'nativeContinuation': native}
                except HTTPException as error:
                    if error.status_code != 404:
                        raise
            elif body is not None:
                with self.store.engine.connect() as conn:
                    proof = conn.execute(text('SELECT body FROM af_workflow_commands WHERE workflow_id=:workflow AND request_id=:id'),
                                         {'workflow': body['id'], 'id': command_id}).first()
                if proof is not None:
                    operation = decoded(proof[0])
                    expected = {'kind': intent['action'], 'stageId': intent['stageId'], 'version': intent['version']}
                    if intent['action'] == 'decide':
                        expected['approved'] = intent['approved']
                    entry = body['stages'][intent['stageId']]
                    if operation == expected and (intent['action'] == 'decide' or entry['state'] != 'UNKNOWN'):
                        # Positive original journal/observation only. This read
                        # never dispatches a runtime or native continuation.
                        receipt = {**receipt, 'status': 'completed', 'workflow': body}
        return receipt

    async def preflight(self, task, command):
        if command.action == 'cancel':
            return
        context = self.context(task)
        tool = 'workflow_choose' if command.action == 'resume' else 'workflow_inspect' if command.action == 'reconcile' else 'workflow_read'
        body = self.service._bound(context, tool)
        require(body['version'] == command.version and command.stageId in body['stages'])
        entry = body['stages'][command.stageId]
        if command.action == 'resume':
            require(self.service.admissible(body, command.stageId))
            await self.require_paused(task, command.stageId)
        elif command.action == 'decide':
            require(self.service._stage(body, command.stageId)['humanGate'] and entry['state'] in {'PENDING', 'HUMAN_WAIT'} and entry['operationId'] is None)
        else:
            require(entry['operationId'] is not None)

    async def submit(self, owner, task_id, command):
        self.auth.require(owner, 'run')
        task = self.store.task(task_id, owner)
        fingerprint = digest({'taskId': task_id, 'runId': task['run_id'], 'planId': task['plan_id'], 'command': command.model_dump()})
        rejected = False
        try:
            await self.preflight(task, command)
        except Exception:
            # No dispatch, budget debit or workflow mutation has occurred at
            # this boundary, including native mandate/guardrail refusals.
            rejected = True
        with self.service._transaction() as conn:
            row = conn.execute(text('SELECT task_id,fingerprint,body FROM af_workflow_actions WHERE owner_id=:owner AND command_id=:id'),
                               {'owner': owner, 'id': command.commandId}).mappings().first()
            if row:
                require(row['task_id'] == task_id and row['fingerprint'] == fingerprint)
                return decoded(row['body'])['receipt']
            receipt = {'commandId': command.commandId, 'status': 'recorded'}
            if rejected:
                receipt['status'] = 'rejected'
            saved = {'intent': command.model_dump(), 'receipt': receipt}
            value = 'CAST(:body AS JSONB)' if conn.dialect.name == 'postgresql' else ':body'
            conn.execute(text('INSERT INTO af_workflow_actions VALUES(:owner,:id,:task,:fp,' + value + ')'),
                         {'owner': owner, 'id': command.commandId, 'task': task_id, 'fp': fingerprint, 'body': canonical(saved)})
        if receipt['status'] == 'rejected':
            return receipt
        try:
            if command.action == 'cancel':
                continuation = await self.api.commands.submit(owner, task_id, ControlCommand(commandId=command.commandId, action='cancel'))
            else:
                context = self.context(task)
                if command.action == 'decide':
                    self.service.decide(context, command.stageId, command.approved, command.commandId, expected_version=command.version)
                elif command.action == 'resume':
                    await self.require_paused(task, command.stageId)
                    # Native calls debit through the existing pre-hook; explicit
                    # user resumes share that exact root budget ledger.
                    self.store.delegation.consume_tool_budget(context, 'workflow-command:' + command.commandId, 'workflow_choose')
                    resumed = await self.service.resume(context, command.stageId, command.commandId, expected_version=command.version)
                    if resumed['stages'][command.stageId]['state'] == 'UNKNOWN':
                        raise ValueError('WORKFLOW_ACKNOWLEDGEMENT_UNKNOWN')
                else:
                    await self.service.reconcile(context, command.stageId, command.commandId, expected_version=command.version)
                continuation = await self.continue_ready(task)
            receipt.update(status='completed', workflow=self.service.for_task(owner, task_id), nativeContinuation=continuation)
        except Exception:
            receipt.update(status='unknown', workflow=self.service.for_task(owner, task_id))
        with self.store.engine.begin() as conn:
            value = 'CAST(:body AS JSONB)' if conn.dialect.name == 'postgresql' else ':body'
            conn.execute(text('UPDATE af_workflow_actions SET body=' + value + ' WHERE owner_id=:owner AND command_id=:id'),
                         {'body': canonical({'intent': command.model_dump(), 'receipt': receipt}), 'owner': owner, 'id': command.commandId})
        return receipt


def workflow_router(auth, control):
    router = APIRouter(prefix='/api/factory/workflows')

    @router.get('/{task_id}')
    async def read(request: Request, task_id: str):
        return control.snapshot(auth.user(request)['id'], task_id)

    @router.get('/{task_id}/commands/{command_id}')
    async def receipt(request: Request, task_id: str, command_id: str):
        return await control.receipt(auth.user(request)['id'], task_id, command_id)

    @router.post('/{task_id}/commands')
    async def command(request: Request, task_id: str, body: WorkflowCommand):
        try:
            return await control.submit(auth.user(request)['id'], task_id, body)
        except ValueError:
            raise HTTPException(409, 'WORKFLOW_COMMAND_CONFLICT') from None

    return router

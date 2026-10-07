"""Explicit original-run controller for a whole ORX session outside a native worker.

No scheduler scans or restarts sessions. A durable unknown controller intent is
never resubmitted. Only native external-execution continuation consumes results.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import time
from types import SimpleNamespace

from agno.db.base import SessionType
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.requirement import RunRequirement
from agno.tools import tool

from .execution_bindings import BindingContext
from .store import canonical, digest

TOOL = 'autoresearch_session_run'
CALL_ID = 'autoresearch-original-session'
MODEL_ID = 'autoresearch-external-session-control-v1'
PROVIDER_ID = 'controlled-autoresearch-session-control'
EFFECT = 'autoresearch-session-v1'


def _require(value):
    if not value:
        raise ValueError('AUTORESEARCH_SESSION_CONTROL_UNCONFIRMED')


class SessionControlModel(Model):
    def __init__(self, ctx):
        super().__init__(id=MODEL_ID, provider=PROVIDER_ID, name='Original session pause controller', retries=0)
        self._ctx = ctx

    async def aresponse(self, *args, **kwargs):
        return self._response(args, kwargs, streaming=False)

    async def aresponse_stream(self, *args, **kwargs):
        yield self._response(args, kwargs, streaming=True)

    def _response(self, args, kwargs, *, streaming):
        _scope(self._ctx)
        messages = args[0] if args else kwargs.get('messages')
        _require(type(messages) is list)
        results = [item for item in messages if item.role == 'tool' and item.tool_name == TOOL]
        if results:
            _require(len(results) == 1 and not results[0].tool_call_error
                     and results[0].tool_call_id == CALL_ID and type(results[0].content) is str)
            result = json.loads(results[0].content)
            _require(type(result) is dict and result.get('allStopped') is True
                     and result.get('scientificConclusionVerified') is False)
            run = self._ctx.run_context
            _require(not self._ctx.store.autoresearch._unresolved_tools(run.session_id))
            effects = [item for item in self._ctx.store.effects(run.session_id)
                       if item['effect_key'] == run.run_id + ':' + EFFECT]
            original_result = {key: value for key, value in result.items() if key != 'accepted'}
            _require(len(effects) == 1 and effects[0]['status'] == 'DONE'
                     and effects[0]['result'] == original_result
                     and ('accepted' not in result or result['accepted'] is True))
            content = canonical(result)
            messages.append(Message(role='assistant', content=content))
            return ModelResponse(role='assistant', content=content)
        _require(not any(call.get('function', {}).get('name') == TOOL
                         for message in messages for call in message.tool_calls or []))
        response = kwargs.get('run_response')
        run = self._ctx.run_context
        _require(response is not None and response.run_id == run.run_id
                 and response.session_id == run.session_id and response.user_id == run.user_id)
        call = {'id': CALL_ID, 'type': 'function', 'function': {'name': TOOL, 'arguments': '{}'}}
        messages.append(Message(role='assistant', tool_calls=[call]))
        execution = ToolExecution(tool_call_id=CALL_ID, tool_name=TOOL, tool_args={}, external_execution_required=True)
        if not streaming:
            if response.requirements is None:
                response.requirements = []
            response.requirements.append(RunRequirement(tool_execution=execution))
        return ModelResponse(event=ModelResponseEvent.tool_call_paused.value, tool_executions=[execution])

    def invoke(self, *args, **kwargs): raise ValueError('AUTORESEARCH_CONTROL_NO_PROVIDER')
    async def ainvoke(self, *args, **kwargs): raise ValueError('AUTORESEARCH_CONTROL_NO_PROVIDER')
    def invoke_stream(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_CONTROL_NO_PROVIDER')
        yield  # pragma: no cover
    async def ainvoke_stream(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_CONTROL_NO_PROVIDER')
        yield  # pragma: no cover
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response): return response


def _scope(ctx):
    preset = ctx.store.autoresearch.current(ctx)
    _require(getattr(preset, 'external_session', False) is True
             and ctx.settings.demo is True and TOOL in ctx.plan['tools'])


def model_factory(ctx):
    _scope(ctx)
    return SessionControlModel(ctx)


def tool_factory(ctx):
    _scope(ctx)
    @tool(external_execution=True)
    def autoresearch_session_run() -> str:
        """Wait for the original authorized research session controller."""
        raise ValueError('AUTORESEARCH_EXTERNAL_SESSION_REQUIRED')
    return autoresearch_session_run


class AutoResearchSessionControl:
    def __init__(self, store, auth, *, complete=None):
        self.store, self.auth, self.complete = store, auth, complete
        self.active: dict[str, asyncio.Task] = {}
        self.closed = False
        self.failures: dict[str, asyncio.Task] = {}

    def _context(self, task):
        run = SimpleNamespace(user_id=task['owner_id'], session_id=task['id'], run_id=task['run_id'],
            session_state={'factory_envelope': {'plan_ref': task['plan_id'], 'user_id': task['owner_id'],
                'task_id': task['id'], 'request_id': task['request_id']}})
        plan = self.store.plan(task['plan_id'], task['owner_id'])
        self.store.require_plan_execution(task['owner_id'], plan, run_context=run)
        manifest = self.store.execution_bindings.recheck(plan, run)
        _require(type(manifest.get('model')) is dict)
        ctx = BindingContext(self.store.settings, self.store, plan, run, manifest['model'])
        _scope(ctx)
        self.store.authorize_tool(run, TOOL)
        return ctx

    def paused(self, task):
        from .factory_api import requirement_version
        self._context(task)
        _require(task.get('run_id') and not task['cancel_requested'] and not task['terminal'])
        ticket = self.store.lifecycle_observer._binding(task)
        _require(ticket is not None and ticket['id'] == task['run_id'] and ticket['status'] == 'paused'
                 and ticket['persistedRunStatus'] == 'paused')
        session = self.store.native_db.get_session(task['id'], session_type=SessionType.AGENT, user_id=task['owner_id'])
        _require(session is not None)
        runs = [run for run in session.runs or [] if run.run_id == task['run_id'] and run.agent_id == 'factory-executor']
        _require(len(runs) == 1)
        requirements = [item.to_dict() for item in runs[0].requirements or []]
        _require(len(requirements) == 1)
        requirement = requirements[0]
        execution = requirement.get('tool_execution') or {}
        _require(execution.get('tool_name') == TOOL and execution.get('tool_call_id') == CALL_ID
                 and execution.get('external_execution_required') is True and execution.get('result') is None
                 and execution.get('tool_args') in ({}, None) and type(requirement.get('id')) is str)
        return requirement, {'taskId': task['id'], 'ownerId': task['owner_id'], 'nativeRunId': task['run_id'],
            'planId': task['plan_id'], 'planSha256': digest(self.store.plan(task['plan_id'], task['owner_id'])),
            'requirementId': requirement['id'], 'version': requirement_version(requirement)}

    async def _failed(self, original, error):
        """Stop original owned work after authority ends; never infer stop/release."""
        task_id, owner = original['id'], original['owner_id']
        if task_id not in self.failures:
            async def cleanup():
                fresh = self.store.task(task_id, owner)
                _require(all(fresh[key] == original[key] for key in ('id', 'owner_id', 'run_id', 'plan_id')))
                def mark(body):
                    body['sessionControlFailure'] = 'CANCELLED' if isinstance(error, asyncio.CancelledError) else 'CONTROL_FAILED'
                    if body.get('status') != 'unknown':
                        body['status'] = 'failed'
                delegation = self.store.delegation
                with delegation._root_lock(task_id):
                    fresh = self.store.task(task_id, owner)
                    _require(all(fresh[key] == original[key] for key in ('id', 'owner_id', 'run_id', 'plan_id')))
                    tasks = [fresh]
                    self.store.request_cancel(fresh['id'])
                    for link in delegation._descendants(task_id):
                        _require(link['owner_id'] == owner and link['root_id'] == task_id)
                        # An unbound durable delegation intent is UNKNOWN,
                        # not a task that can be canceled or replayed.
                        if link['child_id'] is None:
                            continue
                        child = self.store.task(link['child_id'], owner)
                        self.store.request_cancel(child['id'])
                        tasks.append(child)
                # Failure diagnostics must never block original cancellation.
                try:
                    self.store.autoresearch.change(owner, task_id, mark)
                except Exception:
                    pass
                # No authorization-to-create check: these are original stop-only
                # lifecycle calls, including cleanup following role revocation.
                for task in reversed(tasks):
                    try:
                        await self.store.lifecycle_observer._cancel_bound(task)
                    except Exception:
                        pass  # durable intent remains; UNKNOWN custody is retained
            pending = asyncio.create_task(cleanup())
            self.failures[task_id] = pending
            pending.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        pending = self.failures[task_id]
        end = asyncio.get_running_loop().time() + 5
        while not pending.done() and asyncio.get_running_loop().time() < end:
            try:
                await asyncio.wait_for(asyncio.shield(pending), max(.01, end - asyncio.get_running_loop().time()))
            except asyncio.CancelledError:
                continue
            except Exception:
                break

    async def run(self, owner, task_id):
        self.auth.require(owner, 'run')
        task = deepcopy(self.store.task(task_id, owner))
        _, pin = self.paused(task)
        def admit(body):
            _require(body.get('sessionControl') is None)
            body['sessionControl'] = pin
        self.store.autoresearch.change(owner, task_id, admit)
        try:
            _require(self.paused(self.store.task(task_id, owner))[1] == pin)
            ctx = self._context(task)
            self.store.delegation.consume_tool_budget(ctx.run_context, CALL_ID, TOOL)
            await self.store.autoresearch.execute(ctx)
            return await self.completion(task, self.paused(self.store.task(task_id, owner))[0])
        except BaseException as error:
            await self._failed(task, error)
            raise

    async def completion(self, task, requirement):
        from .factory_api import requirement_version
        fresh = self.store.task(task['id'], task['owner_id'])
        _require(all(fresh[key] == task[key] for key in ('id', 'owner_id', 'run_id', 'plan_id')))
        original, pin = self.paused(fresh)
        body = self.store.autoresearch.row(task['owner_id'], task['id'])['body']
        _require(body.get('sessionControl') == pin and body['status'] in {'awaiting-continuation', 'completed'}
                 and requirement.get('id') == original['id']
                 and requirement_version(requirement) == pin['version'])
        _require(not self.store.autoresearch._unresolved_tools(task['id']))
        effects = [item for item in self.store.effects(task['id']) if item['effect_key'] == task['run_id'] + ':' + EFFECT]
        _require(len(effects) == 1 and effects[0]['status'] == 'DONE')
        result = effects[0]['result']
        _require(type(result) is dict and result.get('allStopped') is True and result.get('cancelled') is False
                 and result.get('scientificConclusionVerified') is False)
        return deepcopy(result)

    def start(self, owner, task_id):
        _require(not self.closed)
        self.auth.require(owner, 'run')
        admitted = self.store.task(task_id, owner)
        identity = {key: admitted[key] for key in ('id', 'owner_id', 'plan_id', 'run_id')}
        _require(bool(identity['run_id']))
        if task_id in self.active:
            return self.active[task_id]
        body = self.store.autoresearch.row(owner, task_id)['body']
        _require(body.get('sessionControl') is None)
        async def drive():
            try:
                async with asyncio.timeout(60):
                    while True:
                        task = self.store.task(task_id, owner)
                        _require(all(task[key] == value for key, value in identity.items())
                                 and not task['cancel_requested'] and not task['terminal'])
                        ticket = self.store.lifecycle_observer._binding(task)
                        if ticket and ticket['status'] == 'paused':
                            break
                        _require(ticket is None or ticket['status'] in {'pending', 'queued', 'running'})
                        await asyncio.sleep(.05)
                result = await self.run(owner, task_id)
                if self.complete is not None:
                    requirement, _ = self.paused(self.store.task(task_id, owner))
                    await self.complete(task, requirement)
                    deadline = self.store.autoresearch.row(owner, task_id)['body']['deadline']
                    while True:
                        fresh = self.store.task(task_id, owner)
                        _require(all(fresh[key] == value for key, value in identity.items())
                                 and not fresh['cancel_requested'])
                        ticket = self.store.lifecycle_observer._binding(fresh)
                        _require(ticket is not None and ticket['id'] == identity['run_id'])
                        if ticket['status'] == ticket.get('persistedRunStatus') == 'completed':
                            self.store.autoresearch.change(owner, task_id, lambda body: body.update(status='completed'))
                            break
                        _require(time.time() < deadline and ticket['status'] in {'paused', 'pending', 'queued', 'running'})
                        await asyncio.sleep(.05)
                return result
            except BaseException as error:
                await self._failed(identity, error)
                raise
        pending = asyncio.create_task(drive())
        self.active[task_id] = pending
        # Retrieve background exceptions without exposing arbitrary exception text.
        pending.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return pending

    async def close(self):
        self.closed = True
        end = asyncio.get_running_loop().time() + 35
        pending = [task for task in self.active.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=max(.01, end - asyncio.get_running_loop().time()))
        # A bounded failed controller may have left original cleanup in progress.
        # Do not cancel or forget that work, and do not claim shutdown completed.
        remaining = [task for task in (*self.active.values(), *self.failures.values()) if not task.done()]
        if remaining:
            _, unresolved = await asyncio.wait(remaining, timeout=max(.01, end - asyncio.get_running_loop().time()))
            return not unresolved
        return True

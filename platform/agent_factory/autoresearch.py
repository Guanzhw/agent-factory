"""Goal-only admission over existing immutable plans and native Factory tasks.

ORX owns research decisions. This service owns admission, original identities,
durable effects, evidence and current authority; it never invents a candidate.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import inspect
import json
import time
from typing import Any, Callable, cast
from uuid import uuid4

from agno.exceptions import RunCancelledException
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .store import canonical, digest, effect_unresolved

ACCEPTANCE = ('modelExecuted', 'instructionsRead', 'agentDecision', 'managedExperiment',
              'independentResult', 'nextDecision')


@dataclass(frozen=True)
class ResearchPreset:
    id: str
    name: str
    default_goal: str
    owner_id: str
    instructions: str
    manifest: dict
    limits: dict
    application_ref: dict = field(default_factory=dict)
    connection_refs: dict = field(default_factory=dict)
    runtime_factory: Callable | None = field(default=None, repr=False)
    context_reader: Callable | None = field(default=None, repr=False)
    candidate_validator: Callable | None = field(default=None, repr=False)
    candidate_builder: Callable | None = field(default=None, repr=False)
    experiment: Callable | None = field(default=None, repr=False)
    # Explicit development operator standing approval, never model/user JSON.
    review_owner: str | None = None
    # Explicit reviewed native pause boundary; existing inline presets remain unchanged.
    external_session: bool = False
    blockers: tuple[str, ...] = ()

    def public_context(self):
        return {'name': self.name, 'instructions': self.instructions, 'manifest': self.manifest}

    @property
    def fingerprint(self):
        return digest({'id': self.id, 'owner': self.owner_id, 'context': self.public_context(),
            'defaultGoal': self.default_goal, 'limits': self.limits, 'application': self.application_ref,
            'connections': self.connection_refs, 'reviewOwner': self.review_owner,
            'externalSession': self.external_session,
            **({'candidateInput': 'parameter-changes-v1'} if callable(self.candidate_builder) else {})})

    def unavailable(self):
        return list(self.blockers) + ([] if self.application_ref and all(callable(value) for value in
            (self.runtime_factory, self.context_reader, self.candidate_validator, self.experiment))
            else ['研究预设尚未完成受管运行时与实验连接。'])


class AutoResearchService:
    def __init__(self, store, auth, bridge, presets, *, commands=None):
        self.store, self.auth, self.bridge, self.presets = store, auth, bridge, presets
        self.commands = commands
        self.active: dict[str, Any] = {}
        self.cleanups: dict[str, asyncio.Task] = {}
        store.sql('''CREATE TABLE IF NOT EXISTS af_autoresearch_runs (
            task_id TEXT PRIMARY KEY REFERENCES af_tasks(id), owner_id TEXT NOT NULL,
            request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, body JSONB NOT NULL,
            UNIQUE(owner_id,request_id))''')

    def preset(self, owner, identifier):
        value = self.presets.get(identifier)
        if type(value) is not ResearchPreset or value.owner_id != owner:
            raise HTTPException(404, 'RESEARCH_PRESET_NOT_FOUND')
        return value

    def unavailable(self, preset):
        blockers = preset.unavailable()
        if preset.external_session and getattr(self.store, 'autoresearch_children', None) is None:
            blockers.append('原父任务下的科研资源与子阶段尚未配置。')
        return blockers

    def list_presets(self, owner):
        self.auth.require(owner, 'read')
        return [{'id': p.id, 'name': p.name, 'defaultGoal': p.default_goal,
                 'ready': not self.unavailable(p), 'blockers': self.unavailable(p), 'limits': p.limits}
                for p in self.presets.values() if type(p) is ResearchPreset and p.owner_id == owner]

    def row(self, owner, task_id):
        self.store.task(task_id, owner)
        rows = self.store.sql('SELECT * FROM af_autoresearch_runs WHERE task_id=:task AND owner_id=:owner',
                              task=task_id, owner=owner)
        if not rows:
            raise HTTPException(404, 'RESEARCH_RUN_NOT_FOUND')
        return rows[0]

    def change(self, owner, task_id, fn):
        with self.store.transaction() as conn:
            row = conn.execute(text('SELECT * FROM af_autoresearch_runs WHERE task_id=:task AND owner_id=:owner FOR UPDATE'),
                               {'task': task_id, 'owner': owner}).mappings().first()
            if row is None:
                raise HTTPException(404, 'RESEARCH_RUN_NOT_FOUND')
            body = json.loads(canonical(row['body']))
            result = fn(body)
            conn.execute(text('UPDATE af_autoresearch_runs SET body=CAST(:body AS JSONB) WHERE task_id=:task'),
                         {'task': task_id, 'body': canonical(body)})
            return result

    def projection(self, owner, task_id):
        self.auth.require(owner, 'read')
        row = self.row(owner, task_id)
        body = dict(row['body'])
        if body['status'] in {'completed', 'failed', 'awaiting-continuation'} and self._unresolved_tools(task_id):
            # A read projection must not rewrite historical effects or their receipts.
            body['status'] = 'unknown'
        actions = []
        try:
            self.auth.require(owner, 'run')
            if body['status'] not in {'completed', 'failed', 'blocked'}:
                actions = ['cancel']
        except HTTPException:
            pass
        return {key: body[key] for key in ('id', 'ownerId', 'presetId', 'requestId', 'goal', 'status',
            'steps', 'evidence', 'acceptance')} | {'allowedActions': actions}

    def _unresolved_tools(self, task_id):
        task = self.store.task(task_id)
        prefix = task['run_id'] + ':autoresearch-tool:'
        return any(effect['effect_key'].startswith(prefix) and effect_unresolved(effect)
                   for effect in self.store.effects(task_id))

    def recover(self, owner, request_id):
        self.auth.require(owner, 'read')
        rows = self.store.sql('SELECT task_id FROM af_autoresearch_runs WHERE owner_id=:owner AND request_id=:request',
                              owner=owner, request=request_id)
        return self.projection(owner, rows[0]['task_id']) if rows else None

    async def start(self, owner, preset_id, goal, request_id):
        self.auth.require(owner, 'run')
        preset = self.preset(owner, preset_id)
        goal = goal.strip() if goal and goal.strip() else preset.default_goal
        if not 2 <= len(goal) <= 2000:
            raise HTTPException(422, 'RESEARCH_GOAL_INVALID')
        fingerprint = digest({'preset': preset.fingerprint, 'goal': goal})
        old = self.recover(owner, request_id)
        if old:
            row = self.row(owner, old['id'])
            if row['fingerprint'] != fingerprint:
                raise HTTPException(409, 'RESEARCH_REQUEST_CONFLICT')
            return old
        if self.unavailable(preset):
            raise HTTPException(409, 'RESEARCH_PRESET_UNAVAILABLE')
        key = 'autoresearch:' + digest({'owner': owner, 'request': request_id})
        proposal = self.store.composition.propose(owner, goal, application_ref=preset.application_ref,
            connection_refs=preset.connection_refs, request_id=key + ':proposal')
        plan = self.store.composition.accept(owner, proposal['id'], key + ':accept')
        if plan['status'] != 'ready':
            raise HTTPException(409, 'RESEARCH_PLAN_BLOCKED')
        authorization = self.store.plan_policy.status(owner, plan)
        if not authorization['executionAllowed']:
            if not self.store.settings.demo or not preset.review_owner:
                raise HTTPException(409, 'RESEARCH_PLAN_REVIEW_REQUIRED')
            review = self.store.plan_policy.request_review(owner, plan['id'], key + ':review')
            self.store.plan_policy.decide(preset.review_owner, review['id'], True, key + ':decision')
        self.store.require_plan_execution(owner, plan)
        task, _ = self.store.reserve_task(plan, request_id)
        body = {'id': task['id'], 'ownerId': owner, 'presetId': preset.id, 'presetFingerprint': preset.fingerprint,
            'requestId': request_id, 'goal': goal, 'status': 'starting', 'steps': [], 'evidence': [],
            'acceptance': {**dict.fromkeys(ACCEPTANCE, False), 'scientificConclusionVerified': False},
            'dispatchAttempted': True, 'session': None, 'intents': {}, 'candidates': {}, 'results': {},
            'experimentCount': 0, 'toolCount': 0, 'deadline': time.time() + preset.limits['totalSeconds']}
        inserted = self.store.sql('''INSERT INTO af_autoresearch_runs VALUES(:task,:owner,:request,:fp,CAST(:body AS JSONB))
            ON CONFLICT DO NOTHING RETURNING task_id''', task=task['id'], owner=owner, request=request_id,
            fp=fingerprint, body=canonical(body))
        if inserted:
            try:
                receipt = await self.bridge.submit({**plan, 'task_id': task['id']}, owner, request_id)
                self.store.accept(task['id'], receipt['run_id'])
            except BaseException:
                self.store.admission_unknown(task['id'])
                self.change(owner, task['id'], lambda b: b.update(status='unknown'))
                raise
            if preset.external_session:
                control = getattr(self.store, 'autoresearch_session_control', None)
                if control is None:
                    raise HTTPException(409, 'RESEARCH_SESSION_CONTROL_UNAVAILABLE')
                control.start(owner, task['id'])
        return self.projection(owner, task['id'])

    def current(self, ctx):
        run = ctx.run_context
        if self.store.cancellation_requested(run.run_id):
            raise RunCancelledException('RESEARCH_CANCEL_REQUESTED')
        plan = self.store.resolve_run(run)
        self.store.require_plan_execution(run.user_id, plan, run_context=run)
        self.store.execution_bindings.recheck(plan, run)
        body = self.row(run.user_id, run.session_id)['body']
        preset = self.preset(run.user_id, body['presetId'])
        if body['presetFingerprint'] != preset.fingerprint or time.time() >= body['deadline']:
            raise ValueError('RESEARCH_PRESET_OR_DEADLINE_CHANGED')
        return preset

    def record(self, ctx, kind, message, *, accepted=None):
        if kind not in {'model-instructions', 'action', 'experiment', 'assessment', 'next-decision'}:
            raise ValueError('RESEARCH_EVIDENCE_KIND')
        def update(body):
            if len(body['steps']) >= 256:
                raise ValueError('RESEARCH_EVIDENCE_LIMIT')
            body['steps'].append({'id': str(uuid4()), 'kind': kind, 'status': 'observed', 'text': message[:16000]})
            if accepted in ACCEPTANCE:
                body['acceptance'][accepted] = True
        self.change(ctx.run_context.user_id, ctx.run_context.session_id, update)

    def commit_intent(self, ctx, *, intent):
        self.current(ctx)
        def update(body):
            key = intent['key']
            if key in body['intents']:
                raise ValueError('RESEARCH_ORIGINAL_EFFECT_UNKNOWN')
            body['intents'][key] = dict(intent)
        self.change(ctx.run_context.user_id, ctx.run_context.session_id, update)

    def commit_stop_intent(self, ctx, *, intent):
        """Cleanup can proceed after revoke/deadline; identity cannot change."""
        run = ctx.run_context
        task = self.store.task(run.session_id, run.user_id)
        body = self.row(run.user_id, run.session_id)['body']
        session = body.get('session') or {}
        if (task['run_id'] != run.run_id or intent.get('operation') != 'interrupt'
                or not session.get('id') or intent.get('sessionId') != session['id']):
            raise ValueError('RESEARCH_STOP_IDENTITY_INVALID')
        def update(body):
            old = body['intents'].get(intent['key'])
            if old is not None:
                raise ValueError('RESEARCH_ORIGINAL_STOP_UNKNOWN')
            body['intents'][intent['key']] = dict(intent)
        self.change(run.user_id, run.session_id, update)

    async def execute(self, ctx):
        preset = self.current(ctx)
        run = ctx.run_context
        effect = self.store.effect_reserve(run.run_id, 'autoresearch-session-v1', {'preset': preset.fingerprint})
        if effect['status'] == 'done':
            if self._unresolved_tools(run.session_id):
                raise ValueError('RESEARCH_TOOL_EFFECT_UNKNOWN')
            if effect['result'].get('outcome') != 'completed':
                raise ValueError('RESEARCH_ORIGINAL_SESSION_FAILED')
            return effect['result']
        if effect['status'] != 'new':
            raise ValueError('RESEARCH_ORIGINAL_SESSION_REQUIRES_RECONCILIATION')
        self.change(run.user_id, run.session_id, lambda b: b.update(status='running'))
        runtime: Any = None
        failure = None
        result = None
        try:
            factory = preset.runtime_factory
            if factory is None:
                raise ValueError('RESEARCH_RUNTIME_UNAVAILABLE')
            runtime = factory(ctx, self)
            if inspect.isawaitable(runtime):
                runtime = await runtime
            self.active[run.session_id] = runtime
            result = await runtime.run()
            self.current(ctx)
        except BaseException as error:
            failure = error
        stopped = False
        if runtime is not None:
            async def stop_original_tree():
                runtime_stopped = False
                try:
                    runtime_stopped = await cast(Any, runtime).stop() is True
                finally:
                    children = getattr(self.store, 'autoresearch_children', None)
                    has_experiment = self.row(run.user_id, run.session_id)['body']['experimentCount'] > 0
                    children_stopped = (not preset.external_session or not has_experiment)
                    if preset.external_session and has_experiment and children is not None:
                        children_stopped = await children.cleanup(ctx) is True
                return runtime_stopped and children_stopped
            cleanup = asyncio.create_task(stop_original_tree())
            self.cleanups[run.session_id] = cleanup
            # Preserve the same cleanup operation despite repeated native cancellation.
            # The runtime owns a bounded stop timeout and positive container/experiment proof.
            deadline = asyncio.get_running_loop().time() + 30
            while not cleanup.done() and asyncio.get_running_loop().time() < deadline:
                try:
                    await asyncio.wait_for(asyncio.shield(cleanup), max(.01, deadline - asyncio.get_running_loop().time()))
                except asyncio.CancelledError as error:
                    failure = failure or error
                except Exception:
                    break
            if cleanup.done() and not cleanup.cancelled():
                try:
                    stopped = cleanup.result() is True
                except BaseException:
                    pass
        if not stopped:
            self.change(run.user_id, run.session_id, lambda b: b.update(status='unknown'))
            # Keep original live/cleanup handles for operator reconciliation; no new session.
            if failure is not None:
                raise failure
            raise ValueError('RESEARCH_STOP_PROOF_UNKNOWN')
        self.active.pop(run.session_id, None)
        self.cleanups.pop(run.session_id, None)
        if self._unresolved_tools(run.session_id):
            self.change(run.user_id, run.session_id, lambda b: b.update(status='unknown'))
            # Runtime exit is known, but it cannot settle another unknown effect.
            # Keep the original session reservation too; never rerun the session.
            if failure is not None:
                raise failure
            raise ValueError('RESEARCH_TOOL_EFFECT_UNKNOWN')
        cancelled = self.store.cancellation_requested(run.run_id)
        saved = {'allStopped': True, 'cancelled': cancelled, 'research': result,
                 'outcome': 'failed' if failure is not None or cancelled else 'completed',
                 'scientificConclusionVerified': False}
        self.store.effect_complete(run.run_id, 'autoresearch-session-v1', saved)
        self.change(run.user_id, run.session_id, lambda b: b.update(
            status='failed' if failure is not None or cancelled else 'awaiting-continuation' if preset.external_session else 'completed'))
        if failure is not None:
            raise failure
        return saved

    def _tool_preflight(self, preset, body, name, payload):
        """Pure admission checks before a new effect; never rerun on old effects."""
        if len(body['steps']) >= 256:
            raise ValueError('RESEARCH_EVIDENCE_LIMIT')
        if name == 'research_context':
            if payload:
                raise ValueError('RESEARCH_TOOL_PAYLOAD')
            if preset.context_reader is None:
                raise ValueError('RESEARCH_CONTEXT_UNAVAILABLE')
        elif name == 'research_candidate':
            if (set(payload) not in ({'hypothesis', 'trainPy'}, {'hypothesis', 'changes'})
                    or type(payload['hypothesis']) is not str or not 1 <= len(payload['hypothesis']) <= 4000):
                raise ValueError('RESEARCH_CANDIDATE_PAYLOAD')
            if 'changes' in payload:
                if not callable(preset.candidate_builder) or type(payload['changes']) is not dict:
                    raise ValueError('RESEARCH_CANDIDATE_UNAVAILABLE')
                train_py = preset.candidate_builder(deepcopy(payload['changes']))
            else:
                train_py = payload['trainPy']
            if (preset.candidate_validator is None or type(train_py) is not str
                    or len(train_py.encode()) > 256 * 1024):
                raise ValueError('RESEARCH_CANDIDATE_UNAVAILABLE')
            return {'trainPy': train_py, 'validated': preset.candidate_validator(train_py)}
        elif name in {'research_experiment', 'research_result'}:
            if (set(payload) != {'candidateId'} or type(payload['candidateId']) is not str
                    or not 1 <= len(payload['candidateId']) <= 200):
                raise ValueError('RESEARCH_EXPERIMENT_PAYLOAD' if name == 'research_experiment' else 'RESEARCH_RESULT_PAYLOAD')
            if name == 'research_experiment':
                if preset.experiment is None:
                    raise ValueError('RESEARCH_EXPERIMENT_UNAVAILABLE')
                if body.get('decision', {}).get('action') == 'stop':
                    raise ValueError('RESEARCH_AGENT_STOPPED')
                if payload['candidateId'] not in body['candidates'] or body['experimentCount'] >= preset.limits['maxExperiments']:
                    raise ValueError('RESEARCH_EXPERIMENT_BUDGET')
                if time.time() + preset.limits['experimentSeconds'] > body['deadline']:
                    raise ValueError('RESEARCH_EXPERIMENT_DEADLINE')
            else:
                result = body['results'].get(payload['candidateId'])
                if result is None or result.get('independentResult') is not True:
                    raise ValueError('RESEARCH_INDEPENDENT_RESULT_UNAVAILABLE')
        elif name == 'research_decision':
            if (set(payload) != {'action', 'reason'} or type(payload['action']) is not str
                    or payload['action'] not in {'continue', 'stop'} or type(payload['reason']) is not str
                    or not 1 <= len(payload['reason']) <= 4000):
                raise ValueError('RESEARCH_DECISION_PAYLOAD')
            if not body['acceptance']['independentResult']:
                raise ValueError('RESEARCH_DECISION_WITHOUT_RESULT')
        else:
            raise ValueError('RESEARCH_TOOL_NOT_REGISTERED')
        return None

    async def tool(self, ctx, name, payload):
        preset = self.current(ctx)
        run = ctx.run_context
        self.store.authorize_tool(run, name)
        if type(payload) is not dict:
            raise ValueError('RESEARCH_TOOL_PAYLOAD')
        payload = dict(payload)
        call_id = payload.pop('_factoryCallId', None)
        if type(call_id) is not str or not 1 <= len(call_id) <= 200:
            raise ValueError('RESEARCH_TOOL_CALL_ID_REQUIRED')
        self.store.delegation.consume_tool_budget(run, call_id, name)
        effect_key = 'autoresearch-tool:' + call_id
        existing = [effect for effect in self.store.effects(run.session_id)
                    if effect['effect_key'] == run.run_id + ':' + effect_key]
        validated = None
        if not existing:
            validated = self._tool_preflight(preset, self.row(run.user_id, run.session_id)['body'], name, payload)
            self.current(ctx)
        # The original effect still owns conflict detection and replay. In particular,
        # a completed experiment may be replayed after its lifetime budget is spent.
        original = self.store.effect_reserve(run.run_id, effect_key, {'tool': name, 'payload': payload})
        if original['status'] == 'done':
            return original['result']
        if original['status'] != 'new':
            raise ValueError('RESEARCH_TOOL_ORIGINAL_UNKNOWN')
        if name == 'research_context':
            if payload:
                raise ValueError('RESEARCH_TOOL_PAYLOAD')
            if preset.context_reader is None:
                raise ValueError('RESEARCH_CONTEXT_UNAVAILABLE')
            result = preset.context_reader()
            if inspect.isawaitable(result):
                result = await result
            self.record(ctx, 'model-instructions', '研究 agent 读取了经审批的项目说明与上下文。', accepted='instructionsRead')
        elif name == 'research_candidate':
            if type(validated) is not dict or set(validated) != {'trainPy', 'validated'}:
                raise ValueError('RESEARCH_CANDIDATE_UNAVAILABLE')
            train_py, validated = validated['trainPy'], validated['validated']
            candidate_id = digest({'hypothesis': payload['hypothesis'], 'validated': validated,
                                   'trainPy': train_py})
            self.change(run.user_id, run.session_id, lambda b: b['candidates'].update({candidate_id: {
                'hypothesis': payload['hypothesis'], 'trainPy': train_py, 'validated': validated}}))
            self.record(ctx, 'action', payload['hypothesis'], accepted='agentDecision')
            result = {'candidateId': candidate_id, 'validation': validated}
        elif name == 'research_experiment':
            if set(payload) != {'candidateId'}:
                raise ValueError('RESEARCH_EXPERIMENT_PAYLOAD')
            def admit(body):
                candidate = body['candidates'].get(payload['candidateId'])
                if body.get('decision', {}).get('action') == 'stop':
                    raise ValueError('RESEARCH_AGENT_STOPPED')
                if candidate is None or body['experimentCount'] >= preset.limits['maxExperiments']:
                    raise ValueError('RESEARCH_EXPERIMENT_BUDGET')
                if time.time() + preset.limits['experimentSeconds'] > body['deadline']:
                    raise ValueError('RESEARCH_EXPERIMENT_DEADLINE')
                body['experimentCount'] += 1
                return candidate
            candidate = self.change(run.user_id, run.session_id, admit)
            if preset.experiment is None:
                raise ValueError('RESEARCH_EXPERIMENT_UNAVAILABLE')
            result = await preset.experiment(ctx, candidate, call_id)
            if not isinstance(result, dict) or result.get('cleanupConfirmed') is not True:
                raise ValueError('RESEARCH_EXPERIMENT_CUSTODY_UNKNOWN')
            self.change(run.user_id, run.session_id, lambda b: b['results'].update({payload['candidateId']: result}))
            self.record(ctx, 'experiment', '受管实验返回原始执行回执。', accepted='managedExperiment')
        elif name == 'research_result':
            if set(payload) != {'candidateId'}:
                raise ValueError('RESEARCH_RESULT_PAYLOAD')
            result = self.row(run.user_id, run.session_id)['body']['results'].get(payload['candidateId'])
            if result is None or result.get('independentResult') is not True:
                raise ValueError('RESEARCH_INDEPENDENT_RESULT_UNAVAILABLE')
            self.record(ctx, 'assessment', '研究 agent 读取了独立评估回执。', accepted='independentResult')
        elif name == 'research_decision':
            if set(payload) != {'action', 'reason'} or payload['action'] not in {'continue', 'stop'} or not isinstance(payload['reason'], str) or not 1 <= len(payload['reason']) <= 4000:
                raise ValueError('RESEARCH_DECISION_PAYLOAD')
            body = self.row(run.user_id, run.session_id)['body']
            if not body['acceptance']['independentResult']:
                raise ValueError('RESEARCH_DECISION_WITHOUT_RESULT')
            self.record(ctx, 'next-decision', payload['reason'], accepted='nextDecision')
            result = {'action': payload['action'], 'reason': payload['reason']}
            self.change(run.user_id, run.session_id, lambda b: b.update(decision=result))
        else:
            raise ValueError('RESEARCH_TOOL_NOT_REGISTERED')
        self.current(ctx)
        self.store.effect_complete(run.run_id, effect_key, result)
        return result

    async def cancel(self, owner, task_id, request_id):
        self.auth.require(owner, 'run')
        self.row(owner, task_id)
        from .control_commands import ControlCommand
        if self.commands is None:
            raise HTTPException(409, 'RESEARCH_NATIVE_CANCEL_UNAVAILABLE')
        await self.commands.submit(owner, task_id, ControlCommand(commandId=request_id, action='cancel'))
        body = self.row(owner, task_id)['body']
        if body['status'] not in {'completed', 'failed', 'blocked'}:
            self.change(owner, task_id, lambda b: b.update(status='stopping'))
        runtime = self.active.get(task_id)
        if runtime is not None:
            await runtime.cancel()
        return self.projection(owner, task_id)


class ResearchStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    presetId: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')
    goal: str | None = Field(default=None, max_length=2000)
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')


class ResearchCancel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')


def autoresearch_router(auth, service):
    router = APIRouter(prefix='/api/factory/autoresearch')

    @router.get('/presets')
    def presets(request: Request):
        return service.list_presets(auth.user(request)['id'])

    @router.post('/runs', status_code=202)
    async def start(body: ResearchStart, request: Request):
        return await service.start(auth.user(request)['id'], body.presetId, body.goal, body.requestId)

    @router.get('/requests/{request_id}')
    def recover(request_id: str, request: Request):
        return service.recover(auth.user(request)['id'], request_id)

    @router.get('/runs/{task_id}')
    def inspect_run(task_id: str, request: Request):
        return service.projection(auth.user(request)['id'], task_id)

    @router.post('/runs/{task_id}/cancel')
    async def cancel(task_id: str, body: ResearchCancel, request: Request):
        return await service.cancel(auth.user(request)['id'], task_id, body.requestId)

    return router

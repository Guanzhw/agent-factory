"""Inert Agno pause controller for an explicitly installed managed attachment.

The model does not call a provider or own an inference loop. Existing native
external-execution continuation invokes the existing bounded process service;
real provider requests are accounted only inside ManagedORXSessionProvider.
"""
import json
from typing import Any, cast

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.requirement import RunRequirement

from .execution_bindings import AdapterRegistration
from .managed_orx_attachment import ManagedORXSessionProvider, require
from .orx_research_broker import MODEL
from .process_runtime_profile import TOOL_NAME
from .store import canonical

MODEL_ADAPTER = 'managed-orx-pause-model-v1'
PROVIDER = 'opencode-go-development'
CALL_ID = 'managed-original-attached-turn'


def _provider(store, target_ref):
    resources = store.process_runtime.resources
    target = resources.targets.get(target_ref)
    require(target is not None and type(target.provider) is ManagedORXSessionProvider)
    return target.provider


class ManagedAttachmentControlModel(Model):
    def __init__(self, ctx: Any = None, target_ref=None):
        super().__init__(id=MODEL, provider=PROVIDER, name='Managed native attachment pause controller', retries=0)
        self._ctx: Any = ctx
        self._target = target_ref

    def _scope(self):
        ctx = self._ctx
        require(ctx is not None)
        ctx.store.require_plan_execution(ctx.run_context.user_id, ctx.plan, run_context=ctx.run_context)
        ctx.store.authorize_tool(ctx.run_context, TOOL_NAME)
        provider = _provider(ctx.store, self._target)
        require(ctx.plan.get('inputValues', {}).get('managedAttachment') == provider.contract)
        ctx.store.process_runtime.validate_execution(ctx.run_context.user_id,
            ctx.store.task(ctx.run_context.session_id, ctx.run_context.user_id), ctx.plan, self._target,
            {'nativeRunId': ctx.run_context.run_id, 'effectKey': 'bounded-process-run-v1'})
        return provider

    async def aresponse(self, *args, **kwargs):
        return self._response(args, kwargs, streaming=False)

    async def aresponse_stream(self, *args, **kwargs):
        yield self._response(args, kwargs, streaming=True)

    def _response(self, args, kwargs, *, streaming):
        self._scope()
        messages = args[0] if args else kwargs.get('messages')
        require(type(messages) is list)
        results = [m for m in messages if m.role == 'tool' and m.tool_name == TOOL_NAME]
        if results:
            require(len(results) == 1 and not results[0].tool_call_error and results[0].tool_call_id == CALL_ID)
            value = json.loads(results[0].content)
            require(value.get('stopEvidence', {}).get('allStopped') is True and value.get('state') == 'RECLAIMED')
            original = self._ctx.store.process_runtime._original(self._ctx.run_context.session_id)
            require(original is not None and value.get('leaseId') == original['lease_id']
                and value.get('nativeRunId') == self._ctx.run_context.run_id)
            content = canonical(value)
            messages.append(Message(role='assistant', content=content))
            return ModelResponse(role='assistant', content=content)
        require(not any(c.get('function', {}).get('name') == TOOL_NAME for m in messages for c in m.tool_calls or []))
        response = kwargs.get('run_response')
        run = self._ctx.run_context
        require(response is not None and response.run_id == run.run_id and response.session_id == run.session_id
                and response.user_id == run.user_id)
        messages.append(Message(role='assistant', tool_calls=[{'id': CALL_ID, 'type': 'function',
            'function': {'name': TOOL_NAME, 'arguments': '{}'}}]))
        execution = ToolExecution(tool_call_id=CALL_ID, tool_name=TOOL_NAME, tool_args={}, external_execution_required=True)
        if not streaming:
            if response.requirements is None:
                response.requirements = []
            response.requirements.append(RunRequirement(tool_execution=execution))
        return ModelResponse(event=ModelResponseEvent.tool_call_paused.value, tool_executions=[execution])

    def invoke(self, *args, **kwargs): raise ValueError('MANAGED_ORX_BROKER_ONLY')
    async def ainvoke(self, *args, **kwargs): raise ValueError('MANAGED_ORX_BROKER_ONLY')
    def invoke_stream(self, *args, **kwargs):
        raise ValueError('MANAGED_ORX_BROKER_ONLY')
        yield
    async def ainvoke_stream(self, *args, **kwargs):
        raise ValueError('MANAGED_ORX_BROKER_ONLY')
        yield
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response): return response


def model_registration(target_ref):
    def validate(config):
        require(config == {'targetRef': target_ref})
    def factory(ctx):
        validate(dict(ctx.spec['config']))
        return ManagedAttachmentControlModel(ctx, target_ref)
    return AdapterRegistration('model', MODEL_ADAPTER, '1', factory, validator=validate)


def request_guard(model, arguments, keyword_arguments, commitment):
    require(type(model) is ManagedAttachmentControlModel and model.retries == 0)
    body = arguments[0] if arguments else keyword_arguments.get('body')
    require(type(body) is dict and body.get('model') == MODEL and not body.get('tools')
            and type(body.get('messages')) is list)
    body = cast(dict[str, Any], body)
    require(type(body.get('max_tokens')) is int and 1 <= body['max_tokens'] <= commitment['perAttemptOutputTokens'])
    require(len(canonical(body).encode()) + 512 * (1 + len(body['messages'])) <= commitment['perAttemptInputTokens'])


def exact_input_schema(contract):
    def schema(value):
        if type(value) is dict:
            return {'type': 'object', 'properties': {k: schema(v) for k, v in value.items()},
                'required': list(value), 'additionalProperties': False}
        if type(value) is str:
            return {'type': 'string', 'minLength': 1, 'maxLength': max(1, len(value)), 'enum': [value]}
        if type(value) is bool:
            return {'type': 'boolean', 'enum': [value]}
        if value is None:
            return {'type': 'null'}
        require(type(value) is int)
        return {'type': 'integer', 'minimum': value, 'maximum': value, 'enum': [value]}
    return schema({'managedAttachment': contract})


def install_completion_handler(store):
    """Trusted startup only. Standard commands still verify owner/stale approval."""
    async def completion(task, requirement):
        from .factory_api import requirement_version, native_requirements
        fresh = store.task(task['id'], task['owner_id'])
        require(all(fresh.get(k) == task.get(k) for k in ('id', 'owner_id', 'run_id', 'plan_id')))
        context = store.process_runtime._context(fresh)
        plan = store.plan(fresh['plan_id'], fresh['owner_id'])
        store.require_plan_execution(fresh['owner_id'], plan, run_context=context)
        binding = store.execution_bindings.manifest(plan, context=context)
        spec = binding.get('model') or {}
        require(spec.get('adapterId') == MODEL_ADAPTER and spec.get('revision') == '1')
        target_ref = spec.get('config', {}).get('targetRef')
        provider = _provider(store, target_ref)
        require(plan.get('inputValues', {}).get('managedAttachment') == provider.contract)
        ticket = store.lifecycle_observer._binding(fresh)
        require(ticket and ticket['status'] == 'paused' and ticket['persistedRunStatus'] == 'paused')
        execution = requirement.get('tool_execution') or {}
        require(execution.get('tool_name') == TOOL_NAME and execution.get('tool_call_id') == CALL_ID
            and execution.get('external_execution_required') is True and execution.get('result') is None
            and execution.get('tool_args') in ({}, None))
        # Native persisted requirement identity is checked independently of UI input.
        from agno.db.base import SessionType
        native = store.native_db.get_session(fresh['id'], session_type=SessionType.AGENT, user_id=fresh['owner_id'])
        runs = [r for r in native.runs or [] if r.run_id == fresh['run_id']] if native is not None else []
        require(len(runs) == 1)
        current = native_requirements(runs[0].to_dict())
        require(len(current) == 1 and current[0].get('id') == requirement.get('id')
                and requirement_version(current[0]) == requirement_version(requirement))
        if store.delegation is not None:
            store.delegation.consume_tool_budget(context, CALL_ID, TOOL_NAME)
        result = await store.process_runtime.run(context, {'targetRef': target_ref})
        from .managed_orx_attachment import EFFECT
        effects = [e for e in store.effects(task['id']) if e.get('effect_key') == context.run_id + ':' + EFFECT]
        require(len(effects) == 1 and effects[0]['status'] == 'DONE' and effects[0]['result'].get('nativeResult') is not None)
        return {**result, 'nativeResult': effects[0]['result'].get('nativeResult')}
    require(TOOL_NAME not in store.external_execution_handlers)
    store.external_execution_handlers[TOOL_NAME] = completion
    return completion

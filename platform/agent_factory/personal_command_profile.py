"""Ordinary remote commands executed by Agno's governed native tool loop.

The local model is a deterministic command controller, never an inference proxy.
Command completion proves HTTP acceptance only; remote usage remains advisory.
"""
from copy import deepcopy
import json
import asyncio
from typing import Any, cast

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool
from fastapi import HTTPException

from .execution_bindings import AdapterRegistration, EnvironmentLimits
from .store import canonical, digest
from .tool_policy_registry import ToolPolicyRegistration
from .usage_ledger import PricingRevision

APPLICATION_ID = 'personal-agent-command-v1'
MODEL_ID = 'personal-command-controller-v1'
PROVIDER_ID = 'local-no-provider'
TOOL_ID = 'personal-agent-command-tool-v1'
TOOL_NAME = 'personal_agent_command'
ENVIRONMENT_ID = 'personal-command-environment-v1'
PERMISSION = 'personal-agent:command'
CONTRACT = 'personal-external-v1'
EFFECT = 'personal-agent-command-v1'
INSTRUCTIONS = ('Execute the exact approved personal_agent_command once. Report only command acceptance or '
    'uncertainty. Remote model usage is advisory and remote process stop is unverified.')


def require(value, code='PERSONAL_COMMAND_SCOPE_INVALID'):
    if not value:
        raise HTTPException(409, code)


class PersonalCommandModel(Model):
    def __init__(self):
        super().__init__(id=MODEL_ID, provider=PROVIDER_ID, name='Personal remote command controller', retries=0)

    def _response(self, messages):
        results = [m for m in messages if m.role == 'tool' and m.tool_name == TOOL_NAME]
        if results:
            require(len(results) == 1 and not results[0].tool_call_error)
            return ModelResponse(role='assistant', content=results[0].content)
        require(not any(c.get('function', {}).get('name') == TOOL_NAME for m in messages for c in m.tool_calls or []))
        return ModelResponse(role='assistant', tool_calls=[{'id': EFFECT, 'type': 'function',
            'function': {'name': TOOL_NAME, 'arguments': '{}'}}])

    def invoke(self, messages, **kwargs): return self._response(messages)
    async def ainvoke(self, messages, **kwargs): return self._response(messages)
    def invoke_stream(self, messages, **kwargs): yield self._response(messages)
    async def ainvoke_stream(self, messages, **kwargs): yield self._response(messages)
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response): return response


def command_scope(ctx, run_context):
    require(all(getattr(run_context, k, None) == getattr(ctx.run_context, k, None)
                for k in ('user_id', 'session_id', 'run_id')))
    plan = ctx.store.authorize_tool(run_context, TOOL_NAME)
    require(plan['id'] == ctx.plan['id'] and plan.get('applicationRef') == ctx.plan.get('applicationRef')
        and plan.get('inputValues') == ctx.plan.get('inputValues')
        and plan.get('application') == APPLICATION_ID and plan.get('mode') == 'personal-command'
        and plan.get('tools') == [TOOL_NAME] and not plan.get('delegation') and not plan.get('remoteHandoff'))
    return command_from_plan(plan)


def command_from_plan(plan):
    require(plan.get('application') == APPLICATION_ID and plan.get('mode') == 'personal-command'
        and plan.get('tools') == [TOOL_NAME] and not plan.get('delegation') and not plan.get('remoteHandoff'))
    command = deepcopy(plan['inputValues'])
    command['connectionPin'] = json.loads(command['connectionPin'])
    require(type(command['connectionPin']) is dict)
    for key in ('nativeSessionId', 'agent'):
        if command[key] == '': command[key] = None
    require(command['executionContract'] == CONTRACT and command['action'] in {'create', 'prompt', 'interrupt'})
    return command


def validate_intent(command, intent):
    expected = {key: command[key] for key in ('executionContract', 'action', 'requestId',
        'connectionPin', 'nativeProjectId', 'nativeSessionId')}
    if command['action'] == 'create':
        expected['title'] = command['title']
        require(type(intent.get('factorySessionId')) is str and intent['factorySessionId'].startswith('personal-'))
        generated = {'factorySessionId'}
    else:
        expected['factorySessionId'] = command['factorySessionId']
        generated = {'nativeMessageId'} if command['action'] == 'prompt' else set()
        if command['action'] == 'prompt':
            expected.update(text=command['text'], agent=command['agent'])
            if intent.get('nativeMessageId') is None:
                # Native ORX has no read-addressable client message ID. Its
                # unknown dispatch cannot be recovered by invented correlation.
                require(command['connectionPin'].get('kind') == 'orx')
            else:
                from .personal_agent_transport import native_id
                native_id(intent['nativeMessageId'])
    require(set(intent) == set(expected) | generated and all(intent.get(k) == v for k, v in expected.items()))


def admission_for(ctx, run_context, command):
    """Closure bound to one actual native context, never HTTP input or global state."""
    seen = []
    def admission(owner, intent):
        current = command_scope(ctx, run_context)
        require(owner == run_context.user_id and current == command)
        validate_intent(command, intent)
        if seen: require(seen[0] == intent)
        else: seen.append(deepcopy(intent))
        return {'executionContract': CONTRACT, 'planId': ctx.plan['id'],
            'taskId': run_context.session_id, 'nativeRunId': run_context.run_id}
    return admission


def command_receipt(result):
    return {'executionContract': CONTRACT, 'meaning': 'remote-command-acceptance-only',
        'remoteStopVerified': False, 'remoteUsageEnforcement': 'advisory', **result}


def reconcile_command(store, service, owner, request_id):
    """Settle only the original command effect from durable acceptance evidence.

    This is an owner-scoped observation, not execution or reauthorization. It
    can run after permission revocation and never dispatches a remote command.
    """
    service.auth.require(owner, 'read')
    row = service._command(owner, request_id)  # Validates persisted intent/identity hashes.
    if row is None or row['state'] not in {'acknowledged', 'result_observed'}: return
    if row['intent']['action'] in {'attach', 'rebind'}: return  # Local metadata has no native command task.
    identity = row['identity']
    require(type(identity) is dict and set(identity) == {'executionContract', 'planId', 'taskId', 'nativeRunId'}
        and identity['executionContract'] == CONTRACT, 'PERSONAL_COMMAND_IDENTITY_CHANGED')
    require(all(type(identity[key]) is str and identity[key] for key in ('planId', 'taskId', 'nativeRunId')))
    identity = cast(dict[str, Any], identity)
    task = store.task(identity['taskId'], owner)
    require(task['owner_id'] == owner and task['plan_id'] == identity['planId']
        and task['run_id'] == identity['nativeRunId'], 'PERSONAL_COMMAND_IDENTITY_CHANGED')
    plan = store.plan(identity['planId'], owner)
    command = command_from_plan(plan)
    require(command['requestId'] == request_id)
    validate_intent(command, row['intent'])
    if command['action'] == 'prompt':
        require((row['result'] or {}).get('nativeMessageId') == row['intent']['nativeMessageId'])
    effects = store.sql('SELECT * FROM af_effects WHERE effect_key=:key AND task_id=:task AND run_id=:run',
        key=identity['nativeRunId'] + ':' + EFFECT, task=identity['taskId'], run=identity['nativeRunId'])
    require(len(effects) == 1 and effects[0]['fingerprint'] == digest(command), 'PERSONAL_COMMAND_EFFECT_CHANGED')
    if effects[0]['status'] == 'DONE': return
    require(effects[0]['status'] == 'UNKNOWN', 'PERSONAL_COMMAND_EFFECT_CHANGED')
    result = service.request_result(owner, request_id)
    require(result.get('factoryIdentity') == identity and result.get('state') in {'acknowledged', 'result_observed'})
    store.effect_complete(identity['nativeRunId'], EFFECT, command_receipt(result))


def registrations():
    def validate(config): require(config == {})
    def runner(ctx):
        validate(dict(ctx.spec['config']))
        def execute_command(run_context: RunContext) -> str:
            from .personal_agent_sessions import PersonalAgentSessions
            command = command_scope(ctx, run_context)
            service = PersonalAgentSessions(ctx.store.connections,
                admission=admission_for(ctx, run_context, command))
            effect = ctx.store.effect_reserve(run_context.run_id, EFFECT, command)
            if effect['status'] == 'done': return canonical(effect['result'])
            action, owner, request = command['action'], run_context.user_id, command['requestId']
            if effect['status'] != 'new':
                # A native retry/restart can only read the original operation.
                # A crash before its durable reservation remains unknown too.
                try:
                    result = service.request_result(owner, request)
                except HTTPException as error:
                    if error.status_code != 404: raise
                    return canonical({'executionContract': CONTRACT, 'state': 'ack_unknown',
                        'remoteStopVerified': False, 'meaning': 'remote-command-acceptance-only'})
            elif action == 'create':
                result = service.create(owner, command['connectionPin']['ref'], command['nativeProjectId'], request,
                    title=command['title'])
            elif action == 'prompt':
                result = service.prompt(owner, command['factorySessionId'], command['text'], request, agent=command['agent'])
            else:
                result = service.interrupt(owner, command['factorySessionId'], request)
            expected = {'executionContract': CONTRACT, 'planId': ctx.plan['id'],
                'taskId': run_context.session_id, 'nativeRunId': run_context.run_id}
            require(result.get('factoryIdentity') == expected, 'PERSONAL_COMMAND_IDENTITY_CHANGED')
            receipt = command_receipt(result)
            if result['state'] in {'acknowledged', 'result_observed'}:
                ctx.store.effect_complete(run_context.run_id, EFFECT, receipt)
            return canonical(receipt)

        @tool
        async def personal_agent_command(run_context: RunContext) -> str:
            """Send only the immutable approved remote command; never attest process stop."""
            # Agno's async protected tool hook runs on its event loop. Keep the
            # entire synchronous service and its immutable admission closure in
            # one worker thread; native ORX internally bridges async HTTP safely.
            return await asyncio.to_thread(execute_command, run_context)
        return personal_agent_command
    return [AdapterRegistration('model', MODEL_ID, '1', lambda ctx: PersonalCommandModel(), validator=validate),
        AdapterRegistration('tool', TOOL_ID, '1', runner, tool_name=TOOL_NAME, permissions=(PERMISSION,), validator=validate),
        AdapterRegistration('environment', ENVIRONMENT_ID, '1', lambda ctx: EnvironmentLimits(
            runtime_id=ENVIRONMENT_ID, timeout_seconds=30), validator=validate)]


def tool_policy(): return ToolPolicyRegistration(TOOL_ID, '1', 'personal-command-policy-v1', False)
def pricing(): return PricingRevision(MODEL_ID, '1', PROVIDER_ID, MODEL_ID,
    'personal-controller-zero-v1', local_model_type=PersonalCommandModel)


def input_schema():
    def string(n=200, **kw): return {'type': 'string', 'maxLength': n, **kw}
    properties = {'executionContract': string(enum=[CONTRACT]), 'action': string(enum=['create', 'prompt', 'interrupt']),
        'requestId': string(100, minLength=8), 'nativeProjectId': string(), 'nativeSessionId': string(),
        'factorySessionId': string(), 'title': string(120), 'text': string(16000), 'agent': string(),
        'connectionPin': string(8000)}
    # Canonical JSON preserves the complete immutable connection projection.
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def publish_application(state, *, author, reviewer):
    """Explicit trusted installer; independent material/application review required."""
    require(author != reviewer, 'PERSONAL_INDEPENDENT_REVIEW_REQUIRED')
    state['auth'].require(author, 'components:write')
    state['auth'].require(reviewer, 'agent_os:admin')
    governance, applications = state['material_governance'], state['applications']
    materials = []
    for kind, name, adapter in (('prompt', 'instructions', None), ('model', 'model', MODEL_ID),
            ('tool', TOOL_NAME, TOOL_ID), ('environment', 'environment', ENVIRONMENT_ID)):
        identifier = APPLICATION_ID + '-' + name
        definition = {'id': identifier, 'kind': kind, 'name': 'Personal command ' + name,
            'description': INSTRUCTIONS, 'content': INSTRUCTIONS if kind == 'prompt' else name,
            'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': [PERMISSION] if kind == 'tool' else [],
            'provenance': {'kind': 'original', 'notice': 'Remote command acceptance only; live integration unverified.'}}
        if adapter: definition['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': {}}
        material = governance.create_draft(author, definition, identifier + ':draft')
        review = governance.request_publication(author, identifier, material['version'], identifier + ':review')
        governance.decide_publication(reviewer, review['id'], True, identifier + ':approve')
        materials.append(material)
    definition = {'id': APPLICATION_ID, 'name': 'Personal remote agent commands', 'defaultMode': 'personal-command',
        'description': INSTRUCTIONS, 'discoveryKeywords': ['personal', 'remote', 'opencode'],
        'modes': {'personal-command': {'materialRefs': [{k: row[k] for k in ('id', 'version', 'sha256')} for row in materials],
            'capabilities': [PERMISSION], 'toolOrder': [TOOL_NAME], 'config': {}, 'connectionRequirements': [],
            'inputSchema': input_schema(), 'budget': {'toolCalls': 1, 'maxDepth': 1, 'maxChildren': 1,
                'experimentSeconds': 30, 'outputBytes': 65536}}}}
    application = applications.create_draft(author, definition, APPLICATION_ID + ':draft')
    review = applications.request_publication(author, application['id'], application['version'], APPLICATION_ID + ':review')
    applications.decide_publication(reviewer, review['id'], True, APPLICATION_ID + ':approve')
    return application

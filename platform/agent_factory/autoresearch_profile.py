"""Governed native entry into one ORX-owned research turn.

ORX owns reasoning and its tool loop. This model only delegates, persists its
terminal response, and exposes trusted catalog authority. Provider accounting
belongs to each real broker request, never to this outer response wrapper.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from types import MappingProxyType
from typing import Any, cast

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from .execution_bindings import AdapterRegistration, BindingContext, EnvironmentLimits, KnowledgeContext
from .store import digest
from .usage_ledger import PricingRevision, native_response_usage

APPLICATION_ID = 'autoresearch-goal-session-v1'
MODEL_ADAPTER_ID = 'autoresearch-orx-model-v1'
MODEL_ID = 'deepseek-flash'
PROVIDER_ID = 'opencode-go-development'
KNOWLEDGE_ID = 'autoresearch-project-knowledge-v1'
ENVIRONMENT_ID = 'autoresearch-session-environment-v1'
RUNTIME_ID = 'autoresearch-session-v1'
SESSION_RESOURCE_LIMITS = MappingProxyType({'cpus': 1, 'memoryMb': 1024, 'pids': 64, 'maxSessionSeconds': 3600})
TOOL_NAMES = ('research_context', 'research_candidate', 'research_experiment', 'research_result', 'research_decision')
TOOL_IDS = {name: 'autoresearch-' + name.replace('_', '-') + '-v1' for name in TOOL_NAMES}
PERMISSIONS = ('research:read', 'compute:local')
SESSION_TOOL = 'autoresearch_session_run'
SCIENTIFIC_AUTHORITY_TOOLS = ('bounded_process_run', 'research_process_run')
SCIENTIFIC_TOOLS = (*TOOL_NAMES, SESSION_TOOL, *SCIENTIFIC_AUTHORITY_TOOLS)
SCIENTIFIC_TOOL_IDS = {name: 'autoresearch-parent-' + name.replace('_', '-') + '-v1'
                       for name in (SESSION_TOOL, *SCIENTIFIC_AUTHORITY_TOOLS)}
DESCRIPTIONS = {
    'research_context': 'Read the approved project instructions and original research evidence.',
    'research_candidate': 'Submit candidate bytes and a hypothesis to the existing controlled research workflow.',
    'research_experiment': 'Request the controlled candidate experiment through original native confirmation and execution.',
    'research_result': 'Read authoritative evaluation results from original execution custody.',
    'research_decision': 'Record the research reason and next action: stop or continue.',
}


def _require(condition):
    if not condition:
        raise ValueError('AUTORESEARCH_PROFILE_INVALID')


def _config(value):
    _require(type(value) is dict and set(value) == {'presetId'} and type(value['presetId']) is str
             and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', value['presetId']) is not None)


def _field(preset, name):
    return preset.get(name) if type(preset) is dict else getattr(preset, name, None)


def _checked(ctx):
    _require(ctx.settings.demo is True)
    value = dict(ctx.spec['config']); _config(value)
    presets = getattr(ctx.settings, 'autoresearch_presets', None)
    _require(type(presets) is dict and value['presetId'] in presets)
    preset = cast(dict, presets)[value['presetId']]
    expected_tools = SCIENTIFIC_TOOLS if _field(preset, 'external_session') is True else TOOL_NAMES
    owner = getattr(ctx.run_context, 'user_id', None)
    _require(type(owner) is str and bool(owner) and ctx.plan.get('ownerId') == owner
             and _field(preset, 'owner_id') == owner and _field(preset, 'id') == value['presetId']
             and ctx.plan.get('application') == APPLICATION_ID
             and (ctx.plan.get('applicationRef') or {}).get('id') == APPLICATION_ID
             and ctx.plan.get('mode') == 'research' and not ctx.plan.get('delegation')
             and not ctx.plan.get('remoteHandoff') and ctx.plan.get('tools') == list(expected_tools)
             and set(ctx.plan.get('capabilities', [])) == set(PERMISSIONS))
    return preset


def _json(value):
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    _require(len(text.encode()) <= 1024 * 1024)
    return text


def _public_context(preset):
    method = getattr(preset, 'public_context', None)
    value = method() if callable(method) else {key: _field(preset, key) for key in ('name', 'instructions', 'manifest')}
    _require(type(value) is dict and set(value) == {'name', 'instructions', 'manifest'}
             and type(value['name']) is str and type(value['instructions']) is str
             and type(value['manifest']) is dict)
    _json(value)
    return deepcopy(value)


class ORXResearchModel(Model):
    """An async native response boundary, never an independent provider/tool loop."""
    def __init__(self, context: BindingContext):
        _checked(context)
        super().__init__(id=MODEL_ID, name='ORX research session', provider=PROVIDER_ID, retries=0)
        self._context = context
        self._preset_id = context.spec['config']['presetId']

    async def aresponse(self, *args, **kwargs):
        messages = args[0] if args else kwargs.get('messages')
        _require(type(messages) is list and self.retries == 0)
        _checked(self._context)
        _require(self._context.spec['config']['presetId'] == self._preset_id)
        result = await self._context.store.autoresearch.execute(self._context)
        _require(type(result) is dict)
        content = _json(result)
        cast(list, messages).append(Message(role='assistant', content=content))
        return ModelResponse(role='assistant', content=content)

    async def aresponse_stream(self, *args, **kwargs):
        yield await self.aresponse(*args, **kwargs)

    def response(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_ASYNC_RESPONSE_REQUIRED')

    def response_stream(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_ASYNC_RESPONSE_REQUIRED')
        yield  # pragma: no cover

    def invoke(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_BROKER_REQUIRED')

    async def ainvoke(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_BROKER_REQUIRED')

    def invoke_stream(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_BROKER_REQUIRED')
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args, **kwargs):
        raise ValueError('AUTORESEARCH_BROKER_REQUIRED')
        yield  # pragma: no cover

    def _parse_provider_response(self, response, **kwargs):
        raise ValueError('AUTORESEARCH_BROKER_REQUIRED')

    def _parse_provider_response_delta(self, response):
        raise ValueError('AUTORESEARCH_BROKER_REQUIRED')


def registrations(*, external_session=False):
    _require(type(external_session) is bool)
    def knowledge(ctx):
        value = _public_context(_checked(ctx))
        return KnowledgeContext(_json(value), {'evidenceKind': 'autoresearch-approved-project',
            'presetId': ctx.spec['config']['presetId'], 'contextSha256': digest(value)})

    def environment(ctx):
        _checked(ctx)
        return EnvironmentLimits(runtime_id=RUNTIME_ID, timeout_seconds=30, output_bytes=65536,
            memory_bytes=SESSION_RESOURCE_LIMITS['memoryMb'] * 1024 * 1024,
            process_limit=SESSION_RESOURCE_LIMITS['pids'], cpu_percent=SESSION_RESOURCE_LIMITS['cpus'] * 100)

    def tool_factory(name):
        def factory(ctx):
            _checked(ctx)
            async def execute(run_context: RunContext, payload: dict[str, Any]) -> str:
                _require(all(getattr(run_context, key, None) == getattr(ctx.run_context, key, None)
                             for key in ('user_id', 'session_id', 'run_id')))
                _checked(ctx); _require(type(payload) is dict); _json(payload)
                ctx.store.authorize_tool(run_context, name)
                result = await ctx.store.autoresearch.tool(ctx, name, payload)
                ctx.store.authorize_tool(run_context, name)
                return _json(result)
            execute.__name__, execute.__doc__ = name, DESCRIPTIONS[name]
            return tool(execute)
        return factory

    def model(ctx):
        preset = _checked(ctx)
        _require((_field(preset, 'external_session') is True) == external_session)
        if external_session:
            from .autoresearch_session_control import model_factory
            return model_factory(ctx)
        return ORXResearchModel(ctx)

    entries = [AdapterRegistration('model', MODEL_ADAPTER_ID, '1', model, validator=_config, demo_only=True),
        AdapterRegistration('knowledge', KNOWLEDGE_ID, '1', knowledge, validator=_config, demo_only=True),
        AdapterRegistration('environment', ENVIRONMENT_ID, '1', environment, validator=_config, demo_only=True),
        *[AdapterRegistration('tool', TOOL_IDS[name], '1', tool_factory(name), validator=_config,
            demo_only=True, tool_name=name, permissions=('compute:local',) if name == 'research_experiment' else ('research:read',))
          for name in TOOL_NAMES]]
    if external_session:
        def session(ctx):
            _checked(ctx)
            from .autoresearch_session_control import tool_factory
            return tool_factory(ctx)
        entries.append(AdapterRegistration('tool', SCIENTIFIC_TOOL_IDS[SESSION_TOOL], '1', session,
            validator=_config, demo_only=True, tool_name=SESSION_TOOL, permissions=('research:read',)))
        def authority_factory(name):
            def factory(ctx):
                _checked(ctx)
                def deny() -> str:
                    raise ValueError('AUTORESEARCH_CHILD_EXECUTION_ONLY')
                deny.__name__ = name
                deny.__doc__ = 'Authority declaration only; execution requires an original delegated scientific child.'
                return tool(deny)
            return factory
        for name in SCIENTIFIC_AUTHORITY_TOOLS:
            entries.append(AdapterRegistration('tool', SCIENTIFIC_TOOL_IDS[name], '1', authority_factory(name),
                validator=_config, demo_only=True, tool_name=name, permissions=('compute:local',)))
    return entries


def request_guard(model, arguments, keyword_arguments, commitment):
    """Broker calls this with the exact outgoing ChatCompletions body."""
    _require(type(model) is ORXResearchModel and model.retries == 0)
    body = arguments[0] if arguments else keyword_arguments.get('body')
    _require(type(body) is dict and body.get('model') == MODEL_ID and body.get('stream') is True
             and type(body.get('messages')) is list and bool(body['messages']))
    cap = body.get('max_tokens')
    _require(type(cap) is int and 1 <= cap <= commitment['perAttemptOutputTokens'])
    _require('max_completion_tokens' not in body and 'n' not in body)
    tools = body.get('tools', [])
    _require(type(tools) is list)
    encoded = _json(body).encode()
    _require(len(encoded) + 512 * (1 + len(cast(list, body['messages'])) + len(cast(list, tools)))
             <= commitment['perAttemptInputTokens'])


def pricing_registration(*, request_guard=request_guard, usage_reader=native_response_usage,
                         input_tokens=32768, output_tokens=4096):
    return PricingRevision(MODEL_ADAPTER_ID, '1', PROVIDER_ID, MODEL_ID,
        'autoresearch-broker-operator-nominal-v1', input_micros_per_million=1000000,
        output_micros_per_million=1000000, per_attempt_input_tokens=input_tokens,
        per_attempt_output_tokens=output_tokens, request_guard=request_guard, usage_reader=usage_reader,
        accounting_basis='operator-nominal-not-invoice')


def material_drafts(preset_id, *, external_session=False):
    _require(type(external_session) is bool)
    config = {'presetId': preset_id}; _config(config)
    rows = []
    entries = [('skill', 'method', None), ('prompt', 'instructions', None),
               ('knowledge', 'project', KNOWLEDGE_ID), ('model', 'model', MODEL_ADAPTER_ID),
               ('environment', 'environment', ENVIRONMENT_ID),
               *[('tool', name, TOOL_IDS[name]) for name in TOOL_NAMES]]
    if external_session:
        entries.extend(('tool', name, SCIENTIFIC_TOOL_IDS[name]) for name in (SESSION_TOOL, *SCIENTIFIC_AUTHORITY_TOOLS))
    for kind, name, adapter in entries:
        row = {'id': 'autoresearch-' + preset_id + '-' + name, 'kind': kind,
            'name': 'AutoResearch · ' + name, 'description': DESCRIPTIONS.get(name, '经审批的研究项目；整轮推理由 ORX 负责，结果以原执行凭据为准。'),
            'content': name if kind == 'tool' else 'Use the approved project instructions and original evidence through the ORX research session.',
            'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': ['compute:local'] if name == 'research_experiment' or name in SCIENTIFIC_AUTHORITY_TOOLS else ['research:read'] if kind == 'tool' else [],
            'provenance': {'kind': 'original', 'notice': 'Native governed entry to an ORX-owned research session.'}}
        if kind == 'environment':
            row['description'] = ('ORX 会话固定资源：1 CPU、1024 MiB 内存、64 进程；'
                '原生阶段启动最多 30 秒，会话总期限另由 preset 限制且不得超过 3600 秒。')
            row['content'] = _json({'runtimeId': RUNTIME_ID, 'adapterRevision': '1',
                'sessionResourceLimits': dict(SESSION_RESOURCE_LIMITS),
                'nativePhaseTimeoutSeconds': 30, 'outputBytes': 65536})
        _require(len(row['id']) <= 100)
        if adapter: row['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': dict(config)}
        rows.append(row)
    return rows


def application_definition(materials: list[dict[str, Any]], preset_id, *, limits, external_session=False, scientific_modes=None):
    _config({'presetId': preset_id})
    expected = material_drafts(preset_id, external_session=external_session)
    _require(type(materials) is list and len(materials) == len(expected)
             and {row['id'] for row in materials} == {row['id'] for row in expected})
    _require(type(limits) is dict and set(limits) == {'toolCalls', 'maxDepth', 'maxChildren', 'experimentSeconds', 'outputBytes'})
    _require((scientific_modes is None and not external_session) or (external_session and type(scientific_modes) is dict
        and set(scientific_modes) == {'scientific-preparation', 'scientific-training', 'scientific-evaluation'}))
    if external_session:
        _require(limits['maxChildren'] == 3 and limits['maxDepth'] == 1)
    result = {'id': APPLICATION_ID, 'name': 'AutoResearch 目标驱动研究',
        'description': '选择经审批的项目，交给 ORX 进行研究，并保留原任务、执行、评估和用量凭据。',
        'defaultMode': 'research', 'discoveryKeywords': ['AutoResearch', '自主研究'],
        'modes': {'research': {'materialRefs': [{key: row[key] for key in ('id', 'version', 'sha256')} for row in materials],
            'capabilities': list(PERMISSIONS), 'toolOrder': list(SCIENTIFIC_TOOLS if external_session else TOOL_NAMES), 'config': {},
            'connectionRequirements': [], 'budget': deepcopy(limits)}}}
    if external_session:
        result['modes'].update(deepcopy(scientific_modes))
    return result

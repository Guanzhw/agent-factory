"""Ancestor-bound scientific orchestration profiles; never standalone launchers.

Each factory resolves a durable child pin through the operator service. The
preparation tool verifies retained original preparation evidence; training/evaluation retain native
external-execution requirements and ResearchProcessRuntimeService admission.
Deterministic models select a single control action, never scientific decisions.
"""
from copy import deepcopy
import json
from typing import Any, cast

from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from .autoresearch_profile import APPLICATION_ID
from .execution_bindings import AdapterRegistration, EnvironmentLimits, KnowledgeContext
from .research_manifest import manifest_fingerprint, validate_manifest
from .research_runtime_profile import ResearchProcessFixtureModel
from .usage_ledger import PricingRevision

PHASES = ('preparation', 'training', 'evaluation')
MODE_NAMES = {phase: 'scientific-' + phase for phase in PHASES}
PROVIDER_ID = 'controlled-scientific-child-orchestration'
MODEL_ID = 'scientific-child-control-v1'
CAPABILITIES = {phase: ('research:read' if phase == 'preparation' else 'compute:local') for phase in PHASES}
TOOLS = {'preparation': 'research_preparation_verify', 'training': 'research_process_run', 'evaluation': 'research_process_run'}


def _require(value):
    if not value:
        raise ValueError('AUTORESEARCH_SCIENTIFIC_CHILD_INVALID')


def adapter_id(phase, kind):
    _require(phase in PHASES and kind in {'model', 'environment', 'knowledge', 'tool'})
    return 'autoresearch-child-' + phase + '-' + kind + '-v1'


def child_pin(ctx, phase, *, custody=False):
    _require(phase in PHASES and ctx.settings.demo is True and ctx.settings.temporary_policy == 'admin-review')
    config = ctx.spec['config']
    _require(type(config) is dict and set(config) == {'presetId', 'phase'} and config['phase'] == phase)
    parent = ctx.plan.get('delegation')
    _require(type(parent) is dict and set(parent) == {'parentTaskId', 'rootTaskId', 'depth'}
        and type(parent['depth']) is int and parent['depth'] == 1
        and type(parent['parentTaskId']) is str and bool(parent['parentTaskId'])
        and parent['parentTaskId'] == parent['rootTaskId']
        and ctx.plan.get('application') == APPLICATION_ID
        and (ctx.plan.get('applicationRef') or {}).get('id') == APPLICATION_ID
        and ctx.plan.get('mode') == MODE_NAMES[phase] and not ctx.plan.get('remoteHandoff')
        and ctx.plan.get('ownerId') == ctx.run_context.user_id
        and ctx.plan.get('tools') == [TOOLS[phase]] and ctx.plan.get('capabilities') == [CAPABILITIES[phase]])
    # The service verifies persisted ancestry, parent/preset/candidate fingerprints,
    # phase and exact original child identity, plus current authority. Never cache.
    resolve = (ctx.store.autoresearch_children.require_child_custody if custody
               else ctx.store.autoresearch_children.require_child)
    pin = resolve(ctx, phase)
    _require(type(pin) is dict and set(pin) == {'targetRef', 'comparisonManifestSha256', 'variantSha256', 'comparisonManifest'})
    pin = cast(dict[str, Any], pin)
    manifest = validate_manifest(pin['comparisonManifest'])
    _require(pin['comparisonManifestSha256'] == manifest_fingerprint(manifest)
        and type(pin['targetRef']) is str and 1 <= len(pin['targetRef']) <= 120
        and type(pin['variantSha256']) is str and len(pin['variantSha256']) == 64
        and all(c in '0123456789abcdef' for c in pin['variantSha256']))
    return deepcopy(pin)


class ScientificChildControlModel(ResearchProcessFixtureModel):
    def __init__(self, ctx, phase):
        super().__init__()
        self.id, self.provider = MODEL_ID, PROVIDER_ID
        self._ctx, self._phase = ctx, phase

    def _response(self, messages):
        child_pin(self._ctx, self._phase)
        name = TOOLS[self._phase]
        results = [m for m in messages if m.role == 'tool' and m.tool_name == name]
        if results:
            _require(len(results) == 1 and not results[0].tool_call_error)
            return ModelResponse(role='assistant', content=json.dumps({'status': 'control-action-complete',
                'orchestrationKind': 'deterministic-scientific-child', 'scientificConclusionVerified': False}))
        return ModelResponse(role='assistant', tool_calls=[{'id': 'scientific-' + self._phase + '-call',
            'type': 'function', 'function': {'name': name, 'arguments': '{}'}}])


def registrations(preset_id):
    _require(type(preset_id) is str and 1 <= len(preset_id) <= 60)
    entries = []
    def phase_entries(phase):
        expected = {'presetId': preset_id, 'phase': phase}
        def config(value):
            _require(type(value) is dict and value == expected)
        def checked(ctx):
            config(ctx.spec['config']); return child_pin(ctx, phase)
        def model(ctx):
            checked(ctx); return ScientificChildControlModel(ctx, phase)
        def environment(ctx):
            checked(ctx)
            return EnvironmentLimits(runtime_id='research-process-v1' if phase != 'preparation' else 'autoresearch-session-v1',
                timeout_seconds=30, memory_bytes=128 * 1024**2, output_bytes=1024**2)
        def knowledge(ctx):
            pin = checked(ctx)
            return KnowledgeContext(json.dumps(pin['comparisonManifest'], sort_keys=True, separators=(',', ':')),
                {'evidenceKind': 'offline_research_experiment_manifest'})
        def runner(ctx):
            checked(ctx)
            if phase == 'preparation':
                @tool
                async def research_preparation_verify(run_context: RunContext) -> str:
                    _require(all(getattr(run_context, key) == getattr(ctx.run_context, key)
                        for key in ('user_id', 'session_id', 'run_id')))
                    checked(ctx)
                    ctx.store.authorize_tool(run_context, 'research_preparation_verify')
                    result = await ctx.store.autoresearch_children.verify_preparation(ctx)
                    checked(ctx)
                    return json.dumps(result, sort_keys=True, allow_nan=False)
                return research_preparation_verify
            @tool(external_execution=True)
            def research_process_run(run_context: RunContext) -> str:
                checked(ctx)
                raise ValueError('RESEARCH_EXTERNAL_EXECUTION_REQUIRED')
            return research_process_run
        for kind, factory in (('model', model), ('environment', environment), ('knowledge', knowledge), ('tool', runner)):
            entries.append(AdapterRegistration(kind, adapter_id(phase, kind), '1', factory, validator=config,
                demo_only=True, **({'tool_name': TOOLS[phase], 'permissions': (CAPABILITIES[phase],)} if kind == 'tool' else {})))
    for phase in PHASES: phase_entries(phase)
    return entries


def pricing_registrations():
    return tuple(PricingRevision(adapter_id(phase, 'model'), '1', PROVIDER_ID, MODEL_ID,
        'controlled-scientific-child-zero-v1', local_model_type=ScientificChildControlModel) for phase in PHASES)


def material_drafts(preset_id, phase):
    _require(phase in PHASES and type(preset_id) is str and 1 <= len(preset_id) <= 40)
    rows = []
    for kind in ('prompt', 'knowledge', 'model', 'tool', 'environment'):
        row = {'id': 'ar-child-' + preset_id + '-' + phase + '-' + kind, 'kind': kind,
            'name': 'Scientific child ' + phase + ' ' + kind,
            'description': 'Ancestor-bound original candidate control; not a scientific decision or execution proof.',
            'content': TOOLS[phase] if kind == 'tool' else 'Perform one governed original ' + phase + ' control action.',
            'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': [CAPABILITIES[phase]] if kind == 'tool' else [],
            'provenance': {'kind': 'original', 'notice': 'Deterministic orchestration; original provider/evaluator receipts establish custody.'}}
        if kind != 'prompt':
            row['runtimeBinding'] = {'adapterId': adapter_id(phase, kind), 'revision': '1',
                                     'config': {'presetId': preset_id, 'phase': phase}}
        rows.append(row)
    return rows


def mode_definition(materials, phase, *, limits):
    _require(phase in PHASES)
    return {'materialRefs': [{key: row[key] for key in ('id', 'version', 'sha256')} for row in materials],
        'capabilities': [CAPABILITIES[phase]], 'toolOrder': [TOOLS[phase]], 'config': {},
        'connectionRequirements': [], 'budget': deepcopy(limits)}

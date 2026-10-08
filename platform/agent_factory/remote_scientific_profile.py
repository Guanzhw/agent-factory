"""Distinct receiver-only scientific adapters; no cloud-parent emulation.

Deterministic orchestration requests one native phase action, never a scientific
choice. Original receiver handoff authority is resolved on every bind/use.
"""
from copy import deepcopy
import json

from agno.exceptions import InputCheckError
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from .autoresearch_profile import APPLICATION_ID
from .execution_bindings import AdapterRegistration, EnvironmentLimits, KnowledgeContext
from .research_runtime_profile import ResearchProcessFixtureModel
from .usage_ledger import PricingRevision

PHASES = ('preparation', 'training', 'evaluation')
MODE_NAMES = {phase: 'remote-scientific-' + phase for phase in PHASES}
TOOLS = {'preparation': 'research_preparation_verify', 'training': 'research_process_run', 'evaluation': 'research_process_run'}
CAPABILITIES = {phase: 'research:read' if phase == 'preparation' else 'compute:local' for phase in PHASES}
MODEL_ID = 'remote-scientific-phase-control-v1'
PROVIDER_ID = 'controlled-remote-scientific-orchestration'


def _require(value):
    if not value:
        raise ValueError('REMOTE_SCIENTIFIC_PROFILE_INVALID')


def adapter_id(phase, kind):
    _require(phase in PHASES and kind in ('model', 'environment', 'knowledge', 'tool'))
    return 'remote-scientific-' + phase + '-' + kind + '-v1'


def call_id(phase):
    _require(phase in PHASES)
    return 'remote-scientific-' + phase + '-call'


def phase_pin(ctx, phase, *, custody=False):
    _require(phase in PHASES and ctx.settings.temporary_policy == 'admin-review')
    config = ctx.spec['config']
    _require(type(config) is dict and set(config) == {'projectId', 'phase'} and config['phase'] == phase
             and ctx.plan.get('application') == APPLICATION_ID
             and (ctx.plan.get('applicationRef') or {}).get('id') == APPLICATION_ID
             and ctx.plan.get('mode') == MODE_NAMES[phase]
             and ctx.plan.get('ownerId') == ctx.run_context.user_id
             and ctx.plan.get('tools') == [TOOLS[phase]] and ctx.plan.get('capabilities') == [CAPABILITIES[phase]]
             and type(ctx.plan.get('remoteHandoff')) is dict)
    return ctx.store.remote_scientific_receiver.require_phase(ctx, phase, custody=custody)


class RemoteScientificControlModel(ResearchProcessFixtureModel):
    def __init__(self, ctx, phase):
        super().__init__()
        self.id, self.provider = MODEL_ID, PROVIDER_ID
        self._ctx, self._phase = ctx, phase

    def _response(self, messages):
        phase_pin(self._ctx, self._phase)
        results = [m for m in messages if m.role == 'tool' and m.tool_name == TOOLS[self._phase]]
        if results:
            _require(len(results) == 1 and not results[0].tool_call_error
                     and results[0].tool_call_id == call_id(self._phase))
            return ModelResponse(role='assistant', content=json.dumps({'status': 'control-action-complete',
                'orchestrationKind': 'deterministic-remote-scientific-phase', 'scientificConclusionVerified': False}))
        return ModelResponse(role='assistant', tool_calls=[{'id': call_id(self._phase), 'type': 'function',
            'function': {'name': TOOLS[self._phase], 'arguments': '{}'}}])


def registrations(project_id):
    _require(type(project_id) is str and 1 <= len(project_id) <= 60)
    entries = []
    def add_phase(phase):
        expected = {'projectId': project_id, 'phase': phase}
        def config(value):
            _require(type(value) is dict and value == expected)
        def checked(ctx):
            config(ctx.spec['config'])
            return phase_pin(ctx, phase)
        def model(ctx):
            checked(ctx)
            return RemoteScientificControlModel(ctx, phase)
        def environment(ctx):
            checked(ctx)
            return EnvironmentLimits(runtime_id='autoresearch-session-v1' if phase == 'preparation' else 'research-process-v1',
                timeout_seconds=30, memory_bytes=128 * 1024**2, output_bytes=1024**2)
        def knowledge(ctx):
            pin = checked(ctx)
            return KnowledgeContext(json.dumps(pin['comparisonManifest'], sort_keys=True, separators=(',', ':')),
                                    {'evidenceKind': 'offline_research_experiment_manifest'})
        def runner(ctx):
            checked(ctx)
            if phase == 'preparation':
                def debit(run_context, fc):
                    try:
                        _require(all(getattr(run_context, key) == getattr(ctx.run_context, key)
                                     for key in ('user_id', 'session_id', 'run_id'))
                                 and fc.call_id == call_id(phase) and fc.arguments in (None, {})
                                 and fc.function.name == TOOLS[phase])
                        ctx.store.remote_scientific_receiver.consume_tool(ctx, phase, fc.call_id)
                    except Exception as error:
                        # Agno ignores ordinary pre-hook exceptions; guardrail errors abort.
                        raise InputCheckError('REMOTE_SCIENTIFIC_TOOL_DEBIT_DENIED') from error
                @tool(pre_hook=debit)
                async def research_preparation_verify(run_context: RunContext) -> str:
                    _require(all(getattr(run_context, key) == getattr(ctx.run_context, key)
                                 for key in ('user_id', 'session_id', 'run_id')))
                    checked(ctx)
                    result = await ctx.store.remote_scientific_receiver.verify_preparation(ctx)
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
    for phase in PHASES:
        add_phase(phase)
    return entries


def pricing_registrations():
    return tuple(PricingRevision(adapter_id(phase, 'model'), '1', PROVIDER_ID, MODEL_ID,
        'controlled-remote-scientific-zero-v1', local_model_type=RemoteScientificControlModel) for phase in PHASES)


def material_drafts(project_id, phase):
    _require(phase in PHASES and type(project_id) is str and 1 <= len(project_id) <= 40)
    rows = []
    for kind in ('prompt', 'knowledge', 'model', 'tool', 'environment'):
        row = {'id': 'remote-science-' + project_id + '-' + phase + '-' + kind, 'kind': kind,
            'name': 'Receiver scientific ' + phase + ' ' + kind,
            'description': 'Original receiver phase bound to authenticated cloud ancestry and local scientific custody.',
            'content': TOOLS[phase] if kind == 'tool' else 'Perform one original governed ' + phase + ' action.',
            'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': [CAPABILITIES[phase]] if kind == 'tool' else [],
            'provenance': {'kind': 'original', 'notice': 'Deterministic remote control is not scientific execution proof.'}}
        if kind != 'prompt':
            row['runtimeBinding'] = {'adapterId': adapter_id(phase, kind), 'revision': '1',
                                     'config': {'projectId': project_id, 'phase': phase}}
        rows.append(row)
    return rows


def mode_definition(materials, phase, *, limits):
    _require(phase in PHASES)
    return {'materialRefs': [{key: row[key] for key in ('id', 'version', 'sha256')} for row in materials],
        'capabilities': [CAPABILITIES[phase]], 'toolOrder': [TOOLS[phase]], 'config': {},
        'connectionRequirements': [], 'budget': deepcopy(limits)}

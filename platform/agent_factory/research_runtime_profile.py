"""Explicit controlled native external-execution fixture; never launches training.

The native runtime must pause on research_process_run. A separate authorized
service owns submission and consumes original trusted receipts on completion.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from pathlib import Path

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from .config import Settings
from .execution_bindings import AdapterRegistration, EnvironmentLimits, KnowledgeContext
from .process_runtime_profile import _target
from .research_manifest import manifest_fingerprint, validate_manifest
from .store import digest
from .usage_ledger import PricingRevision

APPLICATION_ID = 'research-process-fixture-v1'
MODEL_ID = 'research-process-fixture-model-v1'
PROVIDER_ID = 'controlled-research-process-fixture'
TOOL_ID = 'research-process-run-v1'
ENVIRONMENT_ID = 'research-process-environment-v1'
KNOWLEDGE_ID = 'research-process-knowledge-v1'
TOOL_NAME = 'research_process_run'
TOOL_CONTRACT = 'research-process-v1'
PERMISSION = 'compute:local'
INSTRUCTIONS = ('Call research_process_run exactly once and wait for its external execution result. '
    'Do not execute code, submit processes, invent evaluation results or retry an uncertain launch. '
    'This is a controlled native workflow fixture, not verified autoresearch training.')


def _require(value):
    if not value:
        raise ValueError('RESEARCH_PROCESS_PROFILE_INVALID')


class ResearchProcessFixtureModel(Model):
    def __init__(self):
        super().__init__(id=MODEL_ID, name='Controlled research pause fixture', provider=PROVIDER_ID, retries=0)

    def _response(self, messages):
        results = [message for message in messages if message.role == 'tool' and message.tool_name == TOOL_NAME]
        if results:
            _require(len(results) == 1 and not results[0].tool_call_error)
            return ModelResponse(role='assistant', content=json.dumps({
                'status': 'controlled-fixture-complete', 'modelExecution': 'controlled-fixture',
                'scientificConclusionVerified': False}))
        return ModelResponse(role='assistant', tool_calls=[{'id': 'research-process-fixture-call', 'type': 'function',
            'function': {'name': TOOL_NAME, 'arguments': '{}'}}])

    def invoke(self, messages, **kwargs):
        return self._response(messages)

    async def ainvoke(self, messages, **kwargs):
        return self._response(messages)

    def invoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def _manifest_content(comparison_manifest):
    content = json.dumps(validate_manifest(comparison_manifest), sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    _require(len(content.encode('ascii')) <= 16000)
    return content


def _config(target_ref, comparison_manifest, variant_sha256=None):
    _manifest_content(comparison_manifest)
    variant = comparison_manifest['baselineSourceManifestSha256'] if variant_sha256 is None else variant_sha256
    _require(type(variant) is str and re.fullmatch('[a-f0-9]{64}', variant) is not None)
    return {'targetRef': _target(target_ref), 'comparisonManifestSha256': manifest_fingerprint(comparison_manifest), 'variantSha256': variant}


def registrations(*, target_ref, comparison_manifest, owner='alice', variant_sha256=None):
    expected = _config(target_ref, comparison_manifest, variant_sha256)
    content = _manifest_content(comparison_manifest)
    _require(type(owner) is str and bool(owner))

    def config(value):
        _require(type(value) is dict and set(value) == {'targetRef', 'comparisonManifestSha256', 'variantSha256'})
        _require(type(value['targetRef']) is str and type(value['comparisonManifestSha256']) is str and type(value['variantSha256']) is str and value == expected)

    def scope(ctx):
        config(ctx.spec['config'])
        _require(ctx.settings.demo is True and ctx.settings.temporary_policy == 'admin-review'
            and ctx.run_context.user_id == owner and ctx.plan.get('ownerId') == owner
            and ctx.plan.get('application') == APPLICATION_ID
            and (ctx.plan.get('applicationRef') or {}).get('id') == APPLICATION_ID
            and ctx.plan.get('mode') == 'controlled-fixture' and not ctx.plan.get('delegation')
            and not ctx.plan.get('remoteHandoff') and ctx.plan.get('tools') == [TOOL_NAME]
            and ctx.plan.get('capabilities') == [PERMISSION])

    def runner(ctx):
        config(ctx.spec['config'])

        @tool(external_execution=True)
        def research_process_run(run_context: RunContext) -> str:
            """Pause for governed external process execution; accept no model arguments."""
            raise ValueError('RESEARCH_EXTERNAL_EXECUTION_REQUIRED')
        return research_process_run

    def model(ctx):
        scope(ctx)
        return ResearchProcessFixtureModel()

    def environment(ctx):
        config(ctx.spec['config'])
        # Native phase metadata, not training GPU quota or the experiment wall budget.
        return EnvironmentLimits(runtime_id=TOOL_CONTRACT, timeout_seconds=30,
            memory_bytes=128 * 1024 * 1024, output_bytes=1024 * 1024)

    def knowledge(ctx):
        config(ctx.spec['config'])
        return KnowledgeContext(content, {'evidenceKind': 'offline_research_experiment_manifest'})

    return [AdapterRegistration('knowledge', KNOWLEDGE_ID, '1', knowledge, validator=config),
            AdapterRegistration('tool', TOOL_ID, '1', runner, tool_name=TOOL_NAME,
                permissions=(PERMISSION,), validator=config),
            AdapterRegistration('model', MODEL_ID, '1', model, validator=config, demo_only=True),
            AdapterRegistration('environment', ENVIRONMENT_ID, '1', environment, validator=config)]


def research_settings(*, db_url, workspace: Path, target_ref, remote_targets, comparison_manifest, owner='alice', variant_sha256=None):
    _require(type(remote_targets) is dict and target_ref in remote_targets)
    return Settings(db_url=db_url, workspace=workspace, demo=True, max_workers=1, max_tool_calls=2,
        runtime_tool_contract=TOOL_CONTRACT, temporary_policy='admin-review',
        experiment_timeout_seconds=30, experiment_output_bytes=1024 * 1024,
        policy_revision=APPLICATION_ID, material_policy_revision=APPLICATION_ID,
        runtime_adapters=registrations(target_ref=target_ref, comparison_manifest=comparison_manifest, owner=owner, variant_sha256=variant_sha256),
        remote_targets=dict(remote_targets), usage_pricing=(PricingRevision(MODEL_ID, '1', PROVIDER_ID, MODEL_ID,
            'controlled-local-zero-v1', local_model_type=ResearchProcessFixtureModel,
            per_attempt_input_tokens=32768, per_attempt_output_tokens=4096),))


def material_drafts(*, target_ref, comparison_manifest, variant_sha256=None):
    config = _config(target_ref, comparison_manifest, variant_sha256)
    definitions = []
    for kind, name, adapter in (('prompt', 'instructions', None), ('model', 'model', MODEL_ID),
            ('tool', TOOL_NAME, TOOL_ID), ('environment', 'environment', ENVIRONMENT_ID),
            ('knowledge', 'comparison-manifest', KNOWLEDGE_ID)):
        row = {'id': APPLICATION_ID + '-' + name, 'kind': kind, 'name': 'Controlled research fixture ' + name,
            'description': 'Synthetic native external-execution workflow; no verified training or hardware claim.',
            'content': INSTRUCTIONS if kind == 'prompt' else _manifest_content(comparison_manifest) if kind == 'knowledge' else name, 'license': 'MIT',
            'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': [PERMISSION] if kind == 'tool' else [],
            'provenance': {'kind': 'original', 'notice': 'Controlled fixture orchestration only; supplied manifest identities remain declarations.'}}
        if adapter is not None:
            row['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': deepcopy(config)}
        definitions.append(row)
    return definitions


def application_definition(materials):
    return {'id': APPLICATION_ID, 'name': '受控科研进程暂停流程', 'defaultMode': 'controlled-fixture',
        'description': '合成原生外部执行流程；不代表真实训练或科研验收。', 'discoveryKeywords': [],
        'modes': {'controlled-fixture': {
            'materialRefs': [{key: row[key] for key in ('id', 'version', 'sha256')} for row in materials],
            'capabilities': [PERMISSION], 'toolOrder': [TOOL_NAME], 'config': {}, 'connectionRequirements': [],
            'budget': {'toolCalls': 2, 'maxDepth': 1, 'maxChildren': 1, 'experimentSeconds': 30, 'outputBytes': 1024 * 1024}}}}


def publish_research_application(state, *, target_ref, comparison_manifest, author, reviewer, variant_sha256=None):
    _require(author != reviewer)
    state['auth'].require(author, 'components:write')
    state['auth'].require(reviewer, 'agent_os:admin')
    definitions = material_drafts(target_ref=target_ref, comparison_manifest=comparison_manifest, variant_sha256=variant_sha256)
    governance, applications = state['material_governance'], state['applications']
    materials = []
    for definition in definitions:
        key = 'research-fixture:' + digest(definition)
        material = governance.create_draft(author, definition, key + ':draft')
        review = governance.request_publication(author, material['id'], material['version'], key + ':review')
        governance.decide_publication(reviewer, review['id'], True, key + ':approve')
        materials.append(material)
    definition = application_definition(materials)
    key = 'research-fixture-app:' + manifest_fingerprint(comparison_manifest) + ':' + digest(definition)
    application = applications.create_draft(author, definition, key + ':draft')
    review = applications.request_publication(author, application['id'], application['version'], key + ':review')
    applications.decide_publication(reviewer, review['id'], True, key + ':approve')
    return application

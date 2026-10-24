"""Explicit operator settings and governed publication, never a server launcher.

Members publish exact application and material versions through owner-scoped
governance services.
"""
from dataclasses import replace
from pathlib import Path

from agent_factory_research.autoresearch import ResearchPreset
from agent_factory_research.autoresearch_profile import (RUNTIME_ID, application_definition,
    material_drafts, pricing_registration, registrations)
from agent_factory_research import autoresearch_scientific_child as children
from agent_factory.applications import Budget
from agent_factory_research.config import ResearchSettings as Settings
from agent_factory.store import digest
from agent_factory.usage_ledger import UsagePolicy

MEMBER_POLICY_REVISION = 'autoresearch-goal-department-plan-v1'
MEMBER_MATERIAL_POLICY_REVISION = 'autoresearch-goal-department-material-v1'
ERROR = 'AUTORESEARCH_BOOTSTRAP_INVALID'


def require(value):
    if not value:
        raise ValueError(ERROR)


def application_budget(preset):
    require(type(preset) is ResearchPreset)
    if preset.external_session:
        require(preset.limits.get('maxExperiments') == 1 and type(preset.limits.get('maxExperiments')) is int)
    value = {'toolCalls': preset.limits.get('toolCalls', 32), 'maxDepth': 1, 'maxChildren': 3 if preset.external_session else 1,
        'experimentSeconds': preset.limits['experimentSeconds'],
        'outputBytes': preset.limits.get('outputBytes', 65536)}
    return Budget.model_validate(value).model_dump()


def settings(*, db_url: str, workspace: Path, preset: ResearchPreset, jwt_key: str = '',
             temporary_policy: str = 'member-self-service', material_review_mode: str = 'member-self-service'):
    """Build task-development settings; caller owns existing DB and private workspace.

    This installs only the selected native profile. It neither publishes the
    preset nor clears readiness blockers. JWT configuration remains in memory.
    """
    budget = application_budget(preset)
    requests = preset.limits.get('modelRequests', 3)
    output = preset.limits.get('modelOutputTokens', 512)
    require(type(requests) is int and 1 <= requests <= 16 and type(output) is int and 1 <= output <= 4096)
    nominal = requests * (32768 + output)
    return Settings(db_url=db_url, workspace=workspace, demo=True, jwt_key=jwt_key,
        host='127.0.0.1', native_timeout_seconds=max(60, preset.limits['totalSeconds']), max_workers=1, max_tool_calls=budget['toolCalls'],
        experiment_timeout_seconds=budget['experimentSeconds'], experiment_output_bytes=budget['outputBytes'],
        temporary_policy=temporary_policy, material_review_mode=material_review_mode,
        policy_revision=MEMBER_POLICY_REVISION,
        material_policy_revision=MEMBER_MATERIAL_POLICY_REVISION,
        runtime_tool_contract=RUNTIME_ID, runtime_adapters=registrations(external_session=preset.external_session)
            + (children.registrations(preset.id) if preset.external_session else []),
        usage_pricing=(pricing_registration(output_tokens=output),)
            + (children.pricing_registrations() if preset.external_session else ()),
        usage_policy=UsagePolicy(revision='autoresearch-nominal-not-invoice-v1',
            task_token_limit=nominal, task_amount_micros=nominal,
            user_token_limit=nominal, user_amount_micros=nominal),
        autoresearch_presets={preset.id: preset})


def publish_application(state, preset: ResearchPreset, *, author: str):
    """Publish the owner's exact material and application versions.

    Returns a replacement preset with the published exact application reference;
    does not mutate Settings, register callbacks, or mark a blocked preset ready.
    Permission and idempotency checks remain in the existing governance services.
    """
    require(type(preset) is ResearchPreset and type(author) is str and bool(author))
    budget = application_budget(preset)
    governance, applications = state['material_governance'], state['applications']
    state['auth'].require_member(author)
    def publish_material(definition):
        key = 'ar-material:' + digest(definition)
        material = governance.create_draft(author, definition, key + ':draft')
        governance.publish(author, material['id'], material['version'], key + ':publish')
        return material
    materials = [publish_material(row) for row in material_drafts(preset.id, external_session=preset.external_session)]
    modes = None
    if preset.external_session:
        modes = {children.MODE_NAMES[phase]: children.mode_definition(
            [publish_material(row) for row in children.material_drafts(preset.id, phase)], phase, limits=budget)
            for phase in children.PHASES}
    definition = application_definition(materials, preset.id, limits=budget,
        external_session=preset.external_session, scientific_modes=modes)
    key = 'ar-application:' + digest(definition)
    application = applications.create_draft(author, definition, key + ':draft')
    applications.publish(author, application['id'], application['version'], key + ':publish')
    return replace(preset, application_ref={k: application[k] for k in ('id', 'version', 'sha256')})

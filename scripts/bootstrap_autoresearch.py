"""Explicit operator settings and governed publication, never a server launcher.

Publication is a separate, opt-in call through existing governance. Distinct code
identities are not a claim of independent human approval. No credentials, model
calls, baseline discovery, subordinate execution, or provider activation occur.
"""
from dataclasses import replace
from pathlib import Path

from agent_factory.autoresearch import ResearchPreset
from agent_factory.autoresearch_profile import (RUNTIME_ID, application_definition,
    material_drafts, pricing_registration, registrations)
from agent_factory import autoresearch_scientific_child as children
from agent_factory.applications import Budget
from agent_factory.config import Settings
from agent_factory.store import digest
from agent_factory.usage_ledger import UsagePolicy

POLICY_REVISION = 'autoresearch-goal-plan-v1'
MATERIAL_POLICY_REVISION = 'autoresearch-goal-material-v1'
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


def settings(*, db_url: str, workspace: Path, preset: ResearchPreset, jwt_key: str = ''):
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
        temporary_policy='admin-review', material_review_mode='separate-admin',
        policy_revision=POLICY_REVISION, material_policy_revision=MATERIAL_POLICY_REVISION,
        runtime_tool_contract=RUNTIME_ID, runtime_adapters=registrations(external_session=preset.external_session)
            + (children.registrations(preset.id) if preset.external_session else []),
        usage_pricing=(pricing_registration(output_tokens=output),)
            + (children.pricing_registrations() if preset.external_session else ()),
        usage_policy=UsagePolicy(revision='autoresearch-nominal-not-invoice-v1',
            task_token_limit=nominal, task_amount_micros=nominal,
            user_token_limit=nominal, user_amount_micros=nominal),
        autoresearch_presets={preset.id: preset})


def publish_application(state, preset: ResearchPreset, *, author: str, reviewer: str):
    """Publish all material kinds and the app with existing separate review APIs.

    Returns a replacement preset with the approved exact application reference;
    does not mutate Settings, register callbacks, or mark a blocked preset ready.
    Permission and idempotency checks remain in the existing governance services.
    """
    require(type(preset) is ResearchPreset and type(author) is str and bool(author)
            and type(reviewer) is str and bool(reviewer) and author != reviewer)
    budget = application_budget(preset)
    state['auth'].require(author, 'components:write')
    state['auth'].require(reviewer, 'agent_os:admin')
    governance, applications = state['material_governance'], state['applications']
    def publish_material(definition):
        key = 'ar-material:' + digest(definition)
        material = governance.create_draft(author, definition, key + ':draft')
        review = governance.request_publication(author, material['id'], material['version'], key + ':review')
        governance.decide_publication(reviewer, review['id'], True, key + ':approve')
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
    review = applications.request_publication(author, application['id'], application['version'], key + ':review')
    applications.decide_publication(reviewer, review['id'], True, key + ':approve')
    return replace(preset, application_ref={k: application[k] for k in ('id', 'version', 'sha256')})

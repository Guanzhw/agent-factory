"""One immutable development policy contract for control and research entrypoints."""
from dataclasses import replace

LEGACY_REVISION = 'task-research-bootstrap-v1'
REVISION = 'task-research-bootstrap-department-v1'


def development_settings(settings):
    if not (settings.demo is True and settings.host == '127.0.0.1'
            and settings.temporary_policy in {'member-self-service', 'admin-review'} and settings.max_workers == 1):
        raise ValueError('RESEARCH_BOOTSTRAP_ASSEMBLY_INVALID')
    revision = REVISION if settings.temporary_policy == 'member-self-service' else LEGACY_REVISION
    return replace(settings, runtime_tool_contract='research-bootstrap-v1',
        policy_revision=revision, material_policy_revision=revision,
        plan_review_ttl_seconds=86400)

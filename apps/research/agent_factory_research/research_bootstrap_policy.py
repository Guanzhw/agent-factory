"""Shared local development runtime settings for research entrypoints."""
from dataclasses import replace

REVISION = 'task-research-bootstrap-department-v1'


def development_settings(settings):
    if not (settings.demo is True and settings.host == '127.0.0.1'
            and settings.max_workers == 1):
        raise ValueError('RESEARCH_BOOTSTRAP_ASSEMBLY_INVALID')
    return replace(settings, runtime_tool_contract='research-bootstrap-v1',
        policy_revision=REVISION, material_policy_revision=REVISION)

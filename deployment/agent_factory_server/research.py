"""Explicit research deployment; the default core composition stays app-free."""
from copy import copy
import os
from pathlib import Path

from agent_factory.config import Settings
from research.public import install
from research.qa_workflow import ResearchQAWorkflow
from research.session_tools import ResearchSessionTools
from research.workflow import ResearchWorkflow
from .application_composition import ApplicationAssembly
from .main import create_app as create_deployment


def create_app(settings=None, *, session_tools=None):
    if settings is None and session_tools is None:
        session_tools = _session_tools_from_env()
    settings = copy(settings or Settings.from_env())
    workflow = ResearchWorkflow()
    qa_workflow = ResearchQAWorkflow()
    session_tools = session_tools or ResearchSessionTools()
    settings.native_workflows = (*settings.native_workflows, workflow.registration, qa_workflow.registration)
    settings.runtime_adapters = [*settings.runtime_adapters, *workflow.tool_registrations,
        *qa_workflow.tool_registrations, qa_workflow.environment_registration,
        *session_tools.tool_registrations, session_tools.environment_registration]
    return create_deployment(settings, applications=(ApplicationAssembly(
        name='research', install=lambda state: install(state, workflow=workflow, qa_workflow=qa_workflow,
            session_tools=session_tools)),))


def _session_tools_from_env():
    enabled = os.environ.get('FACTORY_RESEARCH_HOST_COMMANDS', '0')
    if enabled not in {'0', '1'}:
        raise ValueError('FACTORY_RESEARCH_HOST_COMMANDS must be 0 or 1')
    root = os.environ.get('FACTORY_RESEARCH_WORKSPACE_ROOT')
    return ResearchSessionTools(workspace_root=Path(root) if root else None,
        host_commands=enabled == '1', command_path=os.environ.get('FACTORY_RESEARCH_COMMAND_PATH', os.defpath))


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings, session_tools=_session_tools_from_env()),
        host=settings.host, port=settings.port, access_log=False)


if __name__ == '__main__':
    main()

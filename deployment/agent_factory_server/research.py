"""Explicit research deployment; the default core composition stays app-free."""
from copy import copy
import os
from pathlib import Path

from agent_factory.config import Settings
from research.public import install
from research.session_tools import ResearchSessionTools
from .application_composition import ApplicationAssembly
from .main import create_app as create_deployment


def create_app(settings=None, *, session_tools=None):
    settings = copy(settings or Settings.from_env())
    if session_tools is None:
        session_tools = _session_tools_from_env(settings)
    session_tools = session_tools or ResearchSessionTools()
    return create_deployment(settings, applications=(ApplicationAssembly(
        name='research', install=lambda state: install(state, session_tools=session_tools)),))


def _session_tools_from_env(settings=None):
    enabled = os.environ.get('FACTORY_RESEARCH_HOST_COMMANDS', '1')
    if enabled not in {'0', '1'}:
        raise ValueError('FACTORY_RESEARCH_HOST_COMMANDS must be 0 or 1')
    root = os.environ.get('FACTORY_RESEARCH_WORKSPACE_ROOT')
    workspace = Path(root) if root else Path(settings.workspace if settings is not None else os.environ.get('FACTORY_WORKSPACE', '.local')) / 'research'
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return ResearchSessionTools(workspace_root=workspace,
        host_commands=enabled == '1', command_path=os.environ.get('FACTORY_RESEARCH_COMMAND_PATH'))


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings, session_tools=_session_tools_from_env(settings)),
        host=settings.host, port=settings.port, access_log=False, timeout_graceful_shutdown=35)


if __name__ == '__main__':
    main()

"""Explicit research deployment; the default core composition stays app-free."""
from copy import copy

from agent_factory.config import Settings
from research.public import install
from research.qa_workflow import ResearchQAWorkflow
from research.workflow import ResearchWorkflow
from .application_composition import ApplicationAssembly
from .main import create_app as create_deployment


def create_app(settings=None):
    settings = copy(settings or Settings.from_env())
    workflow = ResearchWorkflow()
    qa_workflow = ResearchQAWorkflow()
    settings.native_workflows = (*settings.native_workflows, workflow.registration, qa_workflow.registration)
    settings.runtime_adapters = [*settings.runtime_adapters, *workflow.tool_registrations,
        *qa_workflow.tool_registrations, qa_workflow.environment_registration]
    return create_deployment(settings, applications=(ApplicationAssembly(
        name='research', install=lambda state: install(state, workflow=workflow, qa_workflow=qa_workflow)),))


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == '__main__':
    main()

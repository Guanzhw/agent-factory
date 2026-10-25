"""Explicit optional installation; the deployment owns ApplicationAssembly."""
from agent_factory.application_runs import ApplicationRuns
from .runs import ResearchRuns, runs_router
from .projects import ResearchProjects, projects_router


def install(state):
    projects = ResearchProjects(state['store'], state['auth'], state['assistant_endpoints'])
    state['http_app'].include_router(projects_router(state['auth'], projects))
    state['research_projects'] = projects
    runs = ResearchRuns(projects, ApplicationRuns(state['factory_api']), state['local_budget_scopes'], state['applications'])
    state['http_app'].include_router(runs_router(state['auth'], runs))
    state['research_runs'] = runs

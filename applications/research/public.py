"""Explicit optional installation; the deployment owns ApplicationAssembly."""
from .projects import ResearchProjects, projects_router


def install(state):
    projects = ResearchProjects(state['store'], state['auth'], state['assistant_endpoints'])
    state['http_app'].include_router(projects_router(state['auth'], projects))
    state['research_projects'] = projects

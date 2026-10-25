"""Explicit optional installation; the deployment owns ApplicationAssembly."""
from agent_factory.application_runs import ApplicationRuns
from .runs import ResearchRuns, runs_router
from .records import ResearchRecords
from .projects import ResearchProjects, projects_router


def install(state, *, workflow=None):
    projects = ResearchProjects(state['store'], state['auth'], state['assistant_endpoints'])
    state['http_app'].include_router(projects_router(state['auth'], projects))
    state['research_projects'] = projects
    records = ResearchRecords(state['application_content'])
    runs = ResearchRuns(projects, ApplicationRuns(state['factory_api']), state['local_budget_scopes'], state['applications'], records)
    if workflow is not None:
        from .rounds import ResearchRounds
        from .workflow import WORKFLOW_ID
        store = state['store']
        pin = store.native_workflows.pin(WORKFLOW_ID)
        rounds = ResearchRounds(runs, events=state['assistant_events'],
            endpoints=state['assistant_endpoints'], custody=store.workflow,
            control=store.workflow_control, pin=pin)
        workflow.bind(rounds)
        store.application_runtime.register('research-round', rounds,
            native_components=(tuple(pin[key] for key in ('kind', 'id', 'revision', 'sha256')),),
            finalizes=True)
        projects.execution = rounds
        state['research_rounds'] = rounds
        runs = rounds
    state['http_app'].include_router(runs_router(state['auth'], runs))
    state['research_runs'] = runs

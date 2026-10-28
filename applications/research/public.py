"""Explicit optional installation; the deployment owns ApplicationAssembly."""
from types import SimpleNamespace
from agent_factory.application_runs import ApplicationRuns
from .runs import ResearchRuns, runs_router
from .records import ResearchRecords
from .projects import ResearchProjects, projects_router


def install(state, *, workflow=None, qa_workflow=None, session_tools=None):
    assistants = None
    if qa_workflow is not None:
        from .assistants import ResearchAssistants, assistants_router
        from .qa import ResearchQA
        from .peer_sources import ResearchPeerSources
        from .associations import ResearchAssociations, associations_router
        from .qa_workflow import WORKFLOW_ID as QA_WORKFLOW_ID
        store = state['store']
        assistants = ResearchAssistants(store, state['auth'], state['assistant_endpoints'],
            state['assistant_messages'], state['local_budget_scopes'],
            pin=store.native_workflows.pin(QA_WORKFLOW_ID), tool_registrations=qa_workflow.tool_registrations,
            environment_registration=qa_workflow.environment_registration, events=state['assistant_events'])
        sources = ResearchPeerSources(store, state['application_content'], state['local_budget_scopes'])
        associations = ResearchAssociations(sources, assistants, state['assistant_events'])
        qa = ResearchQA(store, assistants, state['assistant_messages'], ApplicationRuns(state['factory_api']),
            state['application_content'], associations=associations)
        qa_workflow.bind(qa)
        state['research_assistants'], state['research_qa'] = assistants, qa
        state['research_peer_sources'], state['research_associations'] = sources, associations
        state['http_app'].include_router(associations_router(state['auth'], associations))
        state['http_app'].include_router(assistants_router(state['auth'], assistants))
    if session_tools is not None:
        from .sessions import ResearchSessions
        from .session_routes import session_router
        if assistants is None:
            raise ValueError('Research sessions require the existing personal assistant identity service')
        sessions = ResearchSessions(state['store'], state['auth'], assistants,
            ApplicationRuns(state['factory_api']), connections=state['connections'],
            models=state['store'].personal_models, content=state['application_content'], tools=session_tools)
        from .conversations import ResearchConversations, conversations_router
        conversations = ResearchConversations(state['store'], state['auth'], assistants, sessions)
        sessions.conversations = conversations
        from .session_collaboration import ResearchCollaboration
        sessions.collaboration = ResearchCollaboration(sessions, conversations, state['assistant_events'])
        state['research_conversations'] = conversations
        state['http_app'].include_router(conversations_router(state['auth'], conversations))
        session_tools.bind(sessions, state['application_content'])
        state['research_sessions'] = sessions
        state['http_app'].include_router(session_router(state['auth'], sessions))
    projects = ResearchProjects(state['store'], state['auth'], state['assistant_endpoints'], assistants=assistants)
    state['http_app'].include_router(projects_router(state['auth'], projects))
    state['research_projects'] = projects
    records = ResearchRecords(state['application_content'], state.get('research_associations'))
    runs = ResearchRuns(projects, ApplicationRuns(state['factory_api']), state['local_budget_scopes'], state['applications'], records)
    if workflow is not None:
        from .rounds import ResearchRounds
        from .setup import ResearchSetup, setup_router
        from .workflow import WORKFLOW_ID
        store = state['store']
        pin = store.native_workflows.pin(WORKFLOW_ID)
        setup = ResearchSetup(store, state['auth'], state['connections'], store.personal_models,
            controller_registrations=workflow.tool_registrations, qa_workflow=qa_workflow)
        state['research_setup'] = setup
        state['http_app'].include_router(setup_router(state['auth'], setup))
        rounds = ResearchRounds(runs, events=state['assistant_events'],
            endpoints=state['assistant_endpoints'], custody=store.workflow,
            control=store.workflow_control, pin=pin, associations=state.get('research_associations'))
        projects.peer_sources = rounds.peer_sources
        workflow.bind(rounds)
        store.application_runtime.register('research-round', rounds,
            native_components=(tuple(pin[key] for key in ('kind', 'id', 'revision', 'sha256')),),
            finalizes=True)
        # Baseline 62614177 stopped tasks need their original completion responsibility.
        store.application_runtime.register('research-round-62614177-completion',
            SimpleNamespace(finalization_context=rounds.finalization_context), native_components=((
                'workflow', 'research-round', '1', '2c1fcb5650d8473d2171f6d374035b8d4db452b53603337e2b13f3b43f661c54'),),
            finalizes=True)
        projects.execution = rounds
        state['research_rounds'] = rounds
        from .delivery import ResearchDelivery, delivery_router
        delivery = ResearchDelivery(rounds)
        state['research_delivery'] = delivery
        state['http_app'].include_router(delivery_router(state['auth'], delivery))
        runs = rounds
    state['http_app'].include_router(runs_router(state['auth'], runs))
    state['research_runs'] = runs

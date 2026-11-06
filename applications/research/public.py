"""Explicit optional installation; the deployment owns ApplicationAssembly."""
from agent_factory.application_runs import ApplicationRuns
from .runs import ResearchRuns
from .records import ResearchRecords
from .projects import ResearchProjects, projects_router


def install(state, *, qa_workflow=None, session_tools=None):
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
    from .history import ResearchHistory, history_router
    history = ResearchHistory(runs, events=state['assistant_events'], custody=state['store'].workflow,
        associations=state.get('research_associations'))
    projects.peer_sources = history.peer_sources
    state['research_history'] = history
    state['http_app'].include_router(history_router(state['auth'], history))
    from .delivery import ResearchDelivery, delivery_router
    delivery = ResearchDelivery(history)
    state['research_delivery'] = delivery
    router = delivery_router(state['auth'], delivery)
    router.routes = [route for route in router.routes if 'GET' in getattr(route, 'methods', set())]
    state['http_app'].include_router(router)
    if qa_workflow is not None:
        from .setup import ResearchSetup, setup_router
        setup = ResearchSetup(state['store'], state['auth'], state['connections'], state['store'].personal_models,
            qa_workflow=qa_workflow)
        state['research_setup'] = setup
        state['http_app'].include_router(setup_router(state['auth'], setup))
    runs = history
    if session_tools is not None:
        from .session_research import ResearchSessionResearch
        sessions.projects = projects
        sessions.research = ResearchSessionResearch(sessions, projects, records)
    state['research_runs'] = runs

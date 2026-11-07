"""Explicit optional installation; the deployment owns ApplicationAssembly."""
from agent_factory.application_runs import ApplicationRuns
from .projects import ResearchProjects, projects_router


def install(state, *, session_tools=None):
    assistants = None
    if session_tools is not None:
        from .assistants import ResearchAssistants, assistants_router
        from .qa import ResearchQA
        from .peer_sources import ResearchPeerSources
        from .associations import ResearchAssociations, associations_router
        store = state['store']
        assistants = ResearchAssistants(store, state['auth'], state['assistant_endpoints'],
            state['assistant_messages'],
            events=state['assistant_events'])
        sources = ResearchPeerSources(store, state['application_content'])
        associations = ResearchAssociations(sources, assistants, state['assistant_events'])
        qa = ResearchQA(store, assistants, state['assistant_messages'], ApplicationRuns(state['factory_api']),
            state['application_content'], associations=associations)
        store.research_qa = qa
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
        from .skills import ResearchSkills
        state['executor'].skills = ResearchSkills(session_tools)
        state['research_sessions'] = sessions
        state['store'].research_sessions = sessions
        state['http_app'].include_router(session_router(state['auth'], sessions))
    projects = ResearchProjects(state['store'], state['auth'], state['assistant_endpoints'], assistants=assistants)
    state['http_app'].include_router(projects_router(state['auth'], projects))
    state['research_projects'] = projects
    projects.peer_sources = state.get('research_peer_sources')
    if session_tools is not None:
        from .session_research import ResearchSessionResearch
        sessions.projects = projects
        sessions.research = ResearchSessionResearch(sessions, projects, state['application_content'])

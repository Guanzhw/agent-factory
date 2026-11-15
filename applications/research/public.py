"""Explicit optional installation; the deployment owns ApplicationAssembly."""
from agent_factory.application_runs import ApplicationRuns
from .projects import ResearchProjects, projects_router


def install(state, *, session_tools=None):
    assistants = None
    if session_tools is not None:
        from .assistants import ResearchAssistants, assistants_router
        from .qa import INSTRUCTIONS as QA_INSTRUCTIONS, ResearchQA
        from .peer_sources import ResearchPeerSources
        from .associations import ResearchAssociations, associations_router
        from .session_setup import INSTRUCTIONS
        store = state['store']
        runs = ApplicationRuns(state['factory_api'], application='research-chat',
            instructions=[INSTRUCTIONS])
        state['assistant_messages'].runs = runs
        state['assistant_messages'].question_instructions = [QA_INSTRUCTIONS]
        assistants = ResearchAssistants(store, state['auth'], state['assistant_endpoints'],
            state['assistant_messages'],
            events=state['assistant_events'])
        sources = ResearchPeerSources(store, state['application_content'])
        associations = ResearchAssociations(sources, assistants, state['assistant_events'])
        qa = ResearchQA(store, assistants, state['assistant_messages'], runs,
            state['application_content'], associations=associations)
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
            runs, connections=state['connections'],
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
        skills = ResearchSkills(session_tools)
        from .runtime import ResearchRuntime
        state['application_runtimes']['research-chat'] = ResearchRuntime(
            sessions, session_tools, qa, skills)
        state['research_sessions'] = sessions
        state['store'].research_sessions = sessions
        state['http_app'].include_router(session_router(state['auth'], sessions))
        from .session_git import ResearchSessionGit, git_router
        session_git = ResearchSessionGit(sessions)
        sessions.git = session_git
        state['research_session_git'] = session_git
        state['http_app'].include_router(git_router(state['auth'], session_git))
        from .git_review import ResearchGitReview, git_review_router
        sessions.git_review = review = ResearchGitReview(sessions, session_git)
        state['research_git_review'] = review
        state['http_app'].include_router(git_review_router(state['auth'], review))
    projects = ResearchProjects(state['store'], state['auth'], state['assistant_endpoints'], assistants=assistants)
    state['http_app'].include_router(projects_router(state['auth'], projects))
    state['research_projects'] = projects
    projects.peer_sources = state.get('research_peer_sources')
    if session_tools is not None:
        from .session_research import ResearchSessionResearch
        sessions.projects = projects
        sessions.research = ResearchSessionResearch(sessions, projects, state['application_content'])

        from .session_triggers import ResearchTriggers, event_router
        sessions.triggers = ResearchTriggers(sessions)
        state['research_triggers'] = sessions.triggers
        state['application_content'].on_shared = sessions.triggers.published
        state['http_app'].include_router(event_router(state['auth'], sessions.triggers))
        from .session_discovery import ResearchDiscovery, discovery_router
        sessions.discovery = ResearchDiscovery(sessions)
        state['research_discovery'] = sessions.discovery
        state['http_app'].include_router(discovery_router(state['auth'], sessions.discovery))

        from .team_work import ResearchTeamWork, team_work_router
        sessions.team_work = ResearchTeamWork(sessions)
        state['research_team_work'] = sessions.team_work
        state['http_app'].include_router(team_work_router(state['auth'], sessions.team_work))

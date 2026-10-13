"""Explicit installation of the single research application into this deployment."""
from contextlib import asynccontextmanager

from agent_factory.resources import PersistentResourceService
from .services import services_for, release_services
from .synthetic_runtime import default_bindings as synthetic_bindings


def research_bindings(settings, store, connections):
    from .orx_tools import register_orx_adapter
    from .orx_literature_tools import register_literature_adapters, LiteratureEvidenceModel, MODEL_ID
    from .orx_experiment_tools import register_orx_experiment_adapters, LocalORXWorkflowModel, MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION
    bindings = synthetic_bindings(settings, store, connections)
    register_orx_adapter(bindings)
    register_literature_adapters(bindings)
    bindings.register('model', MODEL_ID, '1', lambda context: LiteratureEvidenceModel())
    register_orx_experiment_adapters(bindings)
    bindings.register('model', MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION, lambda context: LocalORXWorkflowModel())
    return bindings


def install_research(state):
    store, auth, settings = state['store'], state['auth'], state['settings']
    bridge, factory_api = state['bridge'], state['factory_api']
    base, connections = state['http_app'], state['connections']
    resources, credential_vault = state['resources'], state['credential_vault']
    handoff_client, receiver = state['handoff_client'], state['handoff_receiver']
    research = services_for(store)
    from .orx_experiment_tools import initialize_orx_experiments
    initialize_orx_experiments(store)
    from .inference_wait import initialize, mark_cancel_requested
    initialize(store)
    store.runtime_mark_cancel_requested = lambda task_id: mark_cancel_requested(store, task_id)
    from .research_runtime_hooks import ResearchRuntimeHooks
    store.runtime_effect_held = ResearchRuntimeHooks.effect_held
    store.runtime_cancel_owned = lambda task: ResearchRuntimeHooks.cancel(store, task)
    store.runtime_ended_reason = lambda task: ResearchRuntimeHooks.ended_reason(store, task)
    ResearchRuntimeHooks.reconcile_capacity(store)
    from agent_factory.application_environments import ApplicationEnvironments, environment_router
    environment_packages = {}
    server_catalog = None
    personal_ssh = None
    ssh_config = settings.ssh_openresearch
    if settings.ssh_self_service is not None:
        from agent_factory.personal_ssh import PersonalSSHServers, SSHEnrollmentConfig
        from agent_factory_research.ssh_openresearch import SSHOpenResearchConfig, BASE
        from .platform_openresearch import PlatformOpenResearchConfig
        if credential_vault is None or not isinstance(settings.ssh_self_service, SSHEnrollmentConfig):
            raise ValueError('Self-service SSH requires explicit global policy and encrypted vault')
        if not isinstance(settings.ssh_self_service.runtime, PlatformOpenResearchConfig):
            raise ValueError("Self-service SSH research requires pinned OpenResearch runtime config")
        personal_ssh = PersonalSSHServers(auth, connections, credential_vault, settings.ssh_self_service,
            probe_source=(BASE / "ssh_prerequisites.py").read_text())
        if ssh_config is None:
            ssh_config = SSHOpenResearchConfig(settings.ssh_self_service.runtime, (), personal_ssh.static_unavailable)
        elif not isinstance(ssh_config, SSHOpenResearchConfig) or ssh_config.runtime != settings.ssh_self_service.runtime:
            raise ValueError('Self-service and registered SSH packages must have identical runtime pins')
    if settings.platform_openresearch is not None:
        from agent_factory_research.platform_openresearch import PlatformOpenResearchConfig, PlatformOpenResearchPackage
        if not settings.personal_agent_commands_enabled or not isinstance(settings.platform_openresearch, PlatformOpenResearchConfig):
            raise ValueError('Platform OpenResearch requires the native personal-command channel and trusted package config')
        package = PlatformOpenResearchPackage(settings.platform_openresearch,
            settings.workspace.resolve() / 'platform-openresearch')
        environment_packages['openresearch'] = package
        connections.personal.providers[package.provider_id] = package.provider
    if ssh_config is not None:
        from agent_factory_research.ssh_openresearch import SSHOpenResearchConfig, SSHOpenResearchPackage
        if not settings.personal_agent_commands_enabled or not isinstance(ssh_config, SSHOpenResearchConfig):
            raise ValueError('SSH OpenResearch requires trusted server bindings and the native personal-command channel')
        ssh_package = SSHOpenResearchPackage(ssh_config, settings.workspace.resolve() / 'ssh-openresearch')
        ssh_package.personal_servers = personal_ssh
        if personal_ssh is not None: personal_ssh.package = ssh_package
        environment_packages['openresearch:ssh'] = ssh_package
        connections.personal.providers[ssh_package.provider_id] = ssh_package.provider
        server_catalog = ssh_package.servers
    store.application_environments = ApplicationEnvironments(store, auth, store.personal_models, connections,
        environment_packages, server_catalog=server_catalog, self_service_servers=personal_ssh is not None)
    store.personal_ssh = personal_ssh
    from agent_factory_research.synthesis_sources import SynthesisSourceService
    research.synthesis_sources = SynthesisSourceService(store, auth)
    from agent_factory_research.autoresearch import AutoResearchService, autoresearch_router
    research.autoresearch = AutoResearchService(store, auth, bridge, settings.autoresearch_presets, commands=factory_api.commands)
    base.include_router(autoresearch_router(auth, research.autoresearch))
    from agent_factory_research.openresearch_workspace import OpenResearchWorkspace, openresearch_workspace_router
    openresearch_workspace = OpenResearchWorkspace(store, auth, research.autoresearch, factory=factory_api)
    base.include_router(openresearch_workspace_router(auth, openresearch_workspace))
    from agent_factory_research.autoresearch_session_control import AutoResearchSessionControl
    async def complete_research_session(task, requirement):
        from agent_factory.control_commands import ControlCommand
        from agent_factory.factory_api import requirement_version
        await factory_api.commands.submit(task['owner_id'], task['id'], ControlCommand(
            commandId='ar-session:' + task['run_id'], action='approve', approved=True,
            requirementId=requirement['id'], version=requirement_version(requirement)))
    research.autoresearch_session_control = AutoResearchSessionControl(store, auth, complete=complete_research_session)
    if settings.managed_orx_profiles_factory is not None:
        import copy
        profiles = settings.managed_orx_profiles_factory(store, auth, resources)
        if type(profiles) is not dict or any(type(k) is not str or type(v) is not dict for k, v in profiles.items()):
            raise ValueError('OPENRESEARCH_MANAGED_PROFILES_INVALID')
        required = {'ownerId', 'targetRef', 'applicationRef', 'mode', 'nativeProfileId',
            'connectionPin', 'contractSha256', 'sessionId'}
        if any(not required.issubset(value) for value in profiles.values()):
            raise ValueError('OPENRESEARCH_MANAGED_PROFILE_PIN_REQUIRED')
        # A trusted installer may add an existing-store provider only after
        # process service construction; reapply the normal target/pool checks.
        resources.targets = PersistentResourceService(store, auth, resources.targets).targets
        openresearch_workspace.managed_profiles = copy.deepcopy(profiles)
        from agent_factory_research.managed_orx_profile import install_completion_handler
        install_completion_handler(store)
    from agent_factory_research.research_runtime import ResearchProcessRuntimeService
    research.research_runtime = ResearchProcessRuntimeService(store, auth, resources)
    resources.execution_runtimes["research-process-run-v1"] = research.research_runtime
    if settings.research_evaluators:
        from agent_factory_research.research_evaluation_service import ResearchEvaluationService
        research.research_evaluation = ResearchEvaluationService(store, auth, resources, settings.research_evaluators)
    if settings.remote_scientific_factory is not None:
        from agent_factory_research.remote_scientific_origin import RemoteScientificOrigin
        from agent_factory_research.remote_scientific_receiver import RemoteScientificReceiver
        scientific = settings.remote_scientific_factory(store, auth, resources, handoff_client,
            receiver, factory_api.commands)
        if type(scientific) is RemoteScientificOrigin:
            research.remote_scientific = scientific
            handoff_client.scientific_service = scientific
        elif type(scientific) is RemoteScientificReceiver:
            research.remote_scientific_receiver = scientific
            receiver.scientific_service = scientific
            store.remote_bindings.delegated_root_validator = receiver.validate_delegated_root
        else:
            raise ValueError('REMOTE_SCIENTIFIC_SERVICE_INVALID')
    if settings.autoresearch_children_factory is not None:
        from agent_factory_research.autoresearch_children import AutoResearchChildren
        children = settings.autoresearch_children_factory(store, auth, research.autoresearch, resources)
        from agent_factory_research.autoresearch_remote_children import AutoResearchRemoteChildren
        if type(children) not in (AutoResearchChildren, AutoResearchRemoteChildren):
            raise ValueError('AUTORESEARCH_CHILD_SERVICE_INVALID')
        research.autoresearch_children = children
    from agent_factory_research.comparison_workflow import ComparisonService, comparison_router
    research.comparisons = ComparisonService(store, auth)
    base.include_router(comparison_router(auth, research.comparisons))
    from agent_factory.personal_ssh import personal_ssh_router
    base.include_router(personal_ssh_router(auth, personal_ssh))
    base.include_router(environment_router(auth, store.application_environments))
    from .synthesis_api import synthesis_router
    base.include_router(synthesis_router(auth, research.synthesis_sources, settings))
    from .personal_research import personal_research_router
    base.include_router(personal_research_router(auth, store, factory_api))
    if settings.personal_agent_commands_enabled:
        from .personal_command_api import PersonalCommandAPI
        base.include_router(PersonalCommandAPI(store, auth, factory_api).router)
    research.workspace = openresearch_workspace
    state.update(research=research, openresearch_workspace=openresearch_workspace,
        synthesis_sources=research.synthesis_sources, research_runtime=research.research_runtime,
        research_evaluation=research.research_evaluation)


@asynccontextmanager
async def research_lifespan(app):
    state = app.state.factory
    try:
        yield
    finally:
        store = state['store']
        research = services_for(store)
        if research.remote_scientific_receiver is not None:
            await research.remote_scientific_receiver.close()
        if research.autoresearch_session_control is not None:
            await research.autoresearch_session_control.close()
        if store.application_environments is not None:
            store.application_environments.close()
        if store.personal_ssh is not None:
            store.personal_ssh.close()



def research_shutdown(state):
    """Release the application graph only after native/observer shutdown drains."""
    release_services(state['store'])


def abort_research_install(state):
    """Undo local constructor resources when no HTTP/native lifespan has started."""
    store = state['store']
    # Async controllers start owned work only through HTTP/native admission.
    # Package/SSH constructors can already own local handles, so close each even
    # if a different constructor or closer failed. Preserve the startup error.
    for service in (store.application_environments, store.personal_ssh):
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
    try:
        for close in (store.dispose_root_locks, store.engine.dispose):
            try:
                close()
            except Exception:
                pass
    finally:
        release_services(store)

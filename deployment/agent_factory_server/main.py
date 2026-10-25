"""Static deployment composition: public Factory plus the research application."""
from dataclasses import dataclass, field, fields
from copy import copy
from functools import partial
from typing import cast

from agent_factory.main import create_app as create_core_app
from agent_factory.config import Settings
from .shutdown import shutdown_failed, shutdown_guard
from .application_composition import (ApplicationAssembly, validate_applications,
    install_applications, application_lifespan, release_applications)
from agent_factory.material_governance import GovernanceConfig
from agent_factory.plan_policy import PlanPolicyConfig, PolicyName, ToolContract
from agent_factory_research.assembly import (install_research, research_bindings, research_lifespan,
    research_shutdown, abort_research_application)
from agent_factory_research.bootstrap_catalog import SEEDS, all_demo_definitions
from agent_factory_research.config import ResearchSettings
from agent_factory_research.services import ResearchServices, bind_registrations
from agent_factory_research.connections_compatibility import ResearchConnectionService
from agent_factory_research.delegation_compatibility import ResearchDelegationService
from agent_factory_research.handoff_compatibility import ResearchHandoffClient, ResearchPreparedHandoffService
from agent_factory_research.model_compatibility import ResearchDelegatingModel
from agent_factory_research.policy_compatibility import ResearchPlanPolicyService
from agent_factory_research.storage_compatibility import ResearchStorageGovernance
from agent_factory_research.synthetic_runtime import default_zero_prices
from agent_factory_research.tools import build_tools


def factory_state(app):
    while not hasattr(getattr(app, 'state', None), 'factory'):
        app = app.app
    return app.state.factory


@dataclass(frozen=True)
class ResearchApplicationAssembly(ApplicationAssembly):
    research: ResearchServices = field(default_factory=ResearchServices, kw_only=True)


def research_application():
    research = ResearchServices()
    return ResearchApplicationAssembly('research', partial(install_research, research=research), research_lifespan,
        research_shutdown, abort_research_application, research=research, shared_claims=(
            'application_environments', 'personal_ssh.package', 'personal_ssh.probe_source',
            'remote_bindings.delegated_root_validator', 'handoff.scientific_service'))



def _abort_shared_store(store):
    if store is None:
        return
    native = getattr(getattr(store, 'native_db', None), 'db_engine', None)
    for closer in (getattr(getattr(store, 'personal_ssh', None), 'close', None),
                   getattr(store, 'dispose_root_locks', None),
                   getattr(native, 'dispose', None), getattr(store.engine, 'dispose', None)):
        if closer is not None:
            try:
                closer()
            except Exception:
                pass  # Preserve the original constructor error.

def create_app(settings=None, *, diagnostics=None, applications=None):
    applications = validate_applications((research_application(),) if applications is None else applications)
    research_instances = [app.research for app in applications if isinstance(app, ResearchApplicationAssembly)]
    if len(research_instances) != 1 or research_instances[0].factory_store is not None:
        raise ValueError('RESEARCH_APPLICATION_INSTANCE_REQUIRED')
    research = research_instances[0]
    settings = settings or ResearchSettings.from_env()
    if not isinstance(settings, ResearchSettings):
        settings = ResearchSettings(**{field.name: getattr(settings, field.name) for field in fields(Settings)})
    settings = copy(settings)
    extra_adapters, extra_prices = [], list(default_zero_prices())
    if settings.source_synthesis_enabled:
        from agent_factory_research.synthesis_runtime import registrations, pricing_registration
        extra_adapters.extend(registrations())
        extra_prices.append(pricing_registration())
    if settings.development_profile == 'opencode-go':
        # Explicit operator development selection, never loaded by the core.
        from agent_factory.go_development import model_registrations, MODEL_ADAPTER_IDS
        from agent_factory.go_usage import pricing_registrations
        extra_adapters.extend(model_registrations())
        extra_prices.extend(pricing_registrations(MODEL_ADAPTER_IDS))
    # Keep existing explicit operator overrides last, as in the original startup.
    settings.runtime_adapters = bind_registrations([*settings.runtime_adapters, *extra_adapters], research)
    settings.usage_pricing = (*extra_prices, *settings.usage_pricing)
    governance = GovernanceConfig(
        review_mode='member-self-service',
        revision=settings.material_policy_revision, tool_contract=cast(ToolContract, settings.runtime_tool_contract),
        source_synthesis_enabled=settings.source_synthesis_enabled)
    policy = PlanPolicyConfig(name=cast(PolicyName, settings.temporary_policy),
        revision=settings.policy_revision,
        tool_contract=cast(ToolContract, settings.runtime_tool_contract),
        source_synthesis_enabled=settings.source_synthesis_enabled)
    try:
        app = create_core_app(settings, diagnostics=diagnostics,
            storage_governance_type=ResearchStorageGovernance,
            model_dispatch_type=ResearchDelegatingModel,
            handoff_client_type=ResearchHandoffClient, handoff_receiver_type=ResearchPreparedHandoffService,
            bindings_factory=partial(research_bindings, research=research), seed_materials=SEEDS, demo_definitions=all_demo_definitions,
            governance_config=governance, policy_config=policy, tool_catalog_factory=build_tools,
            lifespan_context=application_lifespan(applications),
            shutdown_callback=lambda state: release_applications(state, applications), shutdown_guard=shutdown_guard,
            plan_policy_type=partial(ResearchPlanPolicyService, research=research),
            delegation_service_type=ResearchDelegationService,
            connection_service_type=ResearchConnectionService,
            queue_max_attempts=1 if settings.development_live_validation or settings.runtime_tool_contract == 'autoresearch-session-v1' else 2)
    except BaseException:
        _abort_shared_store(research.factory_store)
        research.release()
        raise
    state = factory_state(app)
    state.update(shutdown_failed=shutdown_failed, research=research)
    try:
        install_applications(state, applications)
    except BaseException:
        # Application aborts run first while shared dependencies remain usable.
        _abort_shared_store(state['store'])
        research.release()
        raise
    return app


def main():
    import uvicorn
    settings = ResearchSettings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == '__main__':
    main()

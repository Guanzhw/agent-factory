"""Static deployment composition: public Factory plus the research application."""
from dataclasses import fields
from copy import copy
from typing import cast, Literal

from agent_factory.main import create_app as create_core_app
from agent_factory.config import Settings
from agent_factory.material_governance import GovernanceConfig
from agent_factory.plan_policy import PlanPolicyConfig, PolicyName, ToolContract
from agent_factory.tool_policy_registry import resolve_tool_policies
from agent_factory_research.assembly import (install_research, research_bindings, research_lifespan,
    research_shutdown, abort_research_install)
from agent_factory_research.bootstrap_catalog import SEEDS, all_demo_definitions
from agent_factory_research.config import ResearchSettings
from agent_factory_research.factory_compatibility import ResearchFactoryAPI
from agent_factory_research.handoff_compatibility import ResearchHandoffClient, ResearchPreparedHandoffService
from agent_factory_research.lifecycle_compatibility import ResearchLifecycleObserver
from agent_factory_research.model_compatibility import ResearchDelegatingModel
from agent_factory_research.policy_compatibility import ResearchPlanPolicyService
from agent_factory_research.storage_compatibility import ResearchStorageGovernance
from agent_factory_research.synthetic_runtime import default_zero_prices
from agent_factory_research.tools import build_tools


def factory_state(app):
    while not hasattr(getattr(app, 'state', None), 'factory'):
        app = app.app
    return app.state.factory


def create_app(settings=None, *, diagnostics=None):
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
    settings.runtime_adapters = [*settings.runtime_adapters, *extra_adapters]
    settings.usage_pricing = (*extra_prices, *settings.usage_pricing)
    policies = resolve_tool_policies(settings.tool_policies, settings.runtime_adapters)
    governance = GovernanceConfig(
        review_mode=cast(Literal['member-self-service', 'separate-admin', 'demo-self-review'], settings.material_review_mode),
        revision=settings.material_policy_revision, tool_contract=cast(ToolContract, settings.runtime_tool_contract),
        source_synthesis_enabled=settings.source_synthesis_enabled, tool_policies=policies)
    policy = PlanPolicyConfig(name=cast(PolicyName, settings.temporary_policy),
        revision=settings.policy_revision, review_ttl_seconds=settings.plan_review_ttl_seconds,
        tool_contract=cast(ToolContract, settings.runtime_tool_contract),
        source_synthesis_enabled=settings.source_synthesis_enabled, tool_policies=policies)
    app = create_core_app(settings, diagnostics=diagnostics, factory_api_type=ResearchFactoryAPI,
        storage_governance_type=ResearchStorageGovernance,
        lifecycle_observer_type=ResearchLifecycleObserver, model_dispatch_type=ResearchDelegatingModel,
        handoff_client_type=ResearchHandoffClient, handoff_receiver_type=ResearchPreparedHandoffService,
        bindings_factory=research_bindings, seed_materials=SEEDS, demo_definitions=all_demo_definitions,
        governance_config=governance, policy_config=policy, tool_catalog_factory=build_tools,
        lifespan_context=research_lifespan, shutdown_callback=research_shutdown,
        plan_policy_type=ResearchPlanPolicyService,
        queue_max_attempts=1 if settings.development_live_validation or settings.runtime_tool_contract == 'autoresearch-session-v1' else 2)
    state = factory_state(app)
    try:
        install_research(state)
    except BaseException:
        abort_research_install(state)
        raise
    return app


def main():
    import uvicorn
    settings = ResearchSettings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == '__main__':
    main()

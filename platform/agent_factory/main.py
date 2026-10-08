import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, cast

os.environ["AGNO_TELEMETRY"] = "false"

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .tool_policy_registry import resolve_tool_policies
from .auth import AuthService, CookieBridge
from .catalog import seed_catalog
from .config import Settings
from .connections import ConnectionService, connection_router
from .execution_bindings import default_bindings
from .orx_tools import register_orx_adapter
from .orx_literature_tools import register_literature_adapters, LiteratureEvidenceModel, MODEL_ID as LITERATURE_MODEL_ID
from .orx_experiment_tools import (LocalORXWorkflowModel, initialize_orx_experiments,
                                   register_orx_experiment_adapters, MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION)
from .applications import ApplicationService, application_router
from .composition import CompositionService, composition_router
from .delegation import DelegationService
from .factory_api import FactoryAPI
from .event_replay import EventReplay
from .lifecycle_observer import FactoryLifecycleObserver
from .material_governance import GovernanceConfig, MaterialGovernance, material_governance_router
from .native_bridge import INTERNAL_NATIVE, NativeBridge
from .runtime import build_runtime
from .resources import PersistentResourceService
from .resource_maintenance import ResourceMaintenance
from .resource_api import resource_router
from .store import Store
from .usage_ledger import UsageLedger, default_zero_prices
from .plan_policy import ToolContract, PolicyName, PlanPolicyConfig, PlanPolicyService, persisted_ancestor_guard, plan_policy_router
from .scheduling import SchedulingService
from .remote_handoff import PreparedHandoffService, TrustedHandoffClient
from .remote_bindings import RemoteBindingService
from .remote_authority import origin_authority_router
from .remote_execution import RemoteExecution
from .scheduling_api import scheduling_router


class NativeIngress:
    """The native executor accepts lifecycle calls through the scoped factory only.

    A context variable is trusted in-process, not a user-controlled HTTP header.
    Native middleware still authenticates and authorizes every internal call.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        protected = scope.get("path", "").startswith(("/agents/", "/workflows/", "/schedules"))
        if scope["type"] == "websocket" and protected and not INTERNAL_NATIVE.get():
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "http" and protected and not INTERNAL_NATIVE.get():
            await JSONResponse({"message": "Use the scoped factory API", "code": "FACTORY_ENVELOPE_REQUIRED"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(settings=None, *, diagnostics=None):
    # Trusted operator diagnostics only; fixed stage strings, no configuration.
    def at(stage):
        if diagnostics is not None:
            diagnostics.at(stage)
    at('PREPARATION_APP_SETTINGS')
    settings = settings or Settings.from_env()
    settings.runtime_directory.mkdir(parents=True, exist_ok=True)
    at('PREPARATION_APP_NATIVE_DB')
    native_db = PostgresDb(db_url=settings.db_url, id="factory-native-postgres")
    at('PREPARATION_APP_STORE')
    store = Store(settings.db_url, settings)
    at('PREPARATION_APP_ORX_SCHEMA')
    initialize_orx_experiments(store)
    store.native_db = native_db
    at('PREPARATION_APP_AUTH')
    auth = AuthService(settings, native_db)
    at('PREPARATION_APP_DEMO_IDENTITIES')
    auth.initialize_demo()
    store.auth = auth
    from .storage_governance import StorageGovernance
    from .storage_api import storage_router
    at('PREPARATION_APP_STORAGE')
    store.storage = StorageGovernance(store, auth)
    at('PREPARATION_APP_EVENT_REPLAY')
    replay = EventReplay(store, auth, signing_key=auth._key)
    store.event_replay = replay
    at('PREPARATION_APP_CATALOG')
    if settings.demo:
        seed_catalog(store)
    at('PREPARATION_APP_GOVERNANCE')
    governance = MaterialGovernance(store, auth, GovernanceConfig(
        review_mode=cast(Literal["separate-admin", "demo-self-review"], settings.material_review_mode), revision=settings.material_policy_revision, tool_contract=cast(ToolContract, settings.runtime_tool_contract), source_synthesis_enabled=settings.source_synthesis_enabled, tool_policies=resolve_tool_policies(settings.tool_policies, settings.runtime_adapters)))
    at('PREPARATION_APP_DEMO_GOVERNANCE')
    if settings.demo:
        governance.adopt_demo_bootstrap()
    store.material_governance = governance
    store.register_execution_guard("material-governance",
        lambda owner, plan, context, tool: governance.require_materials_current(plan), tool_independent=True)
    at('PREPARATION_APP_CONNECTIONS')
    credential_vault = settings.credential_vault_factory(store.engine) if settings.credential_vault_factory else None
    bind_vault_reads = getattr(credential_vault, 'bind_read_context', None)
    if callable(bind_vault_reads):
        bind_vault_reads(store._connection)
    personal_providers = dict(settings.personal_connection_providers)
    for provider_id, factory in settings.personal_connection_provider_factories.items():
        if credential_vault is None or provider_id in personal_providers or not callable(factory):
            raise ValueError('Personal provider requires explicit vault and unique trusted factory')
        provider = factory(credential_vault)
        if getattr(provider, "provider_id", None) != provider_id:
            raise ValueError('Personal provider identity differs from trusted registration')
        personal_providers[provider_id] = provider
    connections = ConnectionService(store, auth, settings.trusted_connections,
        personal_providers=personal_providers)
    store.connections = connections
    from .synthesis_sources import SynthesisSourceService
    at('PREPARATION_APP_SYNTHESIS_SOURCES')
    store.synthesis_sources = SynthesisSourceService(store, auth)
    at('PREPARATION_APP_BINDINGS')
    bindings = default_bindings(settings, store, connections)
    register_orx_adapter(bindings)
    register_literature_adapters(bindings)
    bindings.register("model", LITERATURE_MODEL_ID, "1", lambda context: LiteratureEvidenceModel())
    register_orx_experiment_adapters(bindings)
    bindings.register("model", MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION, lambda context: LocalORXWorkflowModel())
    at('PREPARATION_APP_RUNTIME_ADAPTERS')
    for entry in settings.runtime_adapters:
        bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
            tool_name=entry.tool_name, connection_kind=entry.connection_kind,
            required_capabilities=entry.required_capabilities, permissions=entry.permissions,
            demo_only=entry.demo_only, validator=entry.validator, connection_adapter_ref=entry.connection_adapter_ref)
    if settings.development_profile == "opencode-go":
        from .go_development import model_registrations
        for entry in model_registrations():
            bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                connection_kind=entry.connection_kind, required_capabilities=entry.required_capabilities,
                permissions=entry.permissions, demo_only=entry.demo_only, validator=entry.validator,
                connection_adapter_ref=entry.connection_adapter_ref)
    if settings.source_synthesis_enabled:
        from .synthesis_runtime import registrations as synthesis_registrations
        for entry in synthesis_registrations():
            bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                tool_name=entry.tool_name, connection_kind=entry.connection_kind,
                required_capabilities=entry.required_capabilities, permissions=entry.permissions,
                demo_only=entry.demo_only, validator=entry.validator, connection_adapter_ref=entry.connection_adapter_ref)
    store.execution_bindings = bindings
    prices = { (price.adapter_id, price.adapter_revision): price for price in default_zero_prices() }
    if settings.development_profile == "opencode-go":
        from .go_development import MODEL_ADAPTER_IDS
        from .go_usage import pricing_registrations
        for price in pricing_registrations(MODEL_ADAPTER_IDS):
            prices[(price.adapter_id, price.adapter_revision)] = price
    if settings.source_synthesis_enabled:
        from .synthesis_runtime import pricing_registration
        price = pricing_registration()
        prices[(price.adapter_id, price.adapter_revision)] = price
    for price in settings.usage_pricing:
        prices[(price.adapter_id, price.adapter_revision)] = price
    at('PREPARATION_APP_USAGE_LEDGER')
    store.usage_ledger = UsageLedger(store, prices=tuple(prices.values()), policy=settings.usage_policy)
    at('PREPARATION_APP_REMOTE_BINDINGS')
    remote_bindings = RemoteBindingService(store, auth, bindings, connections, settings.remote_binding_mappings)
    store.remote_bindings = remote_bindings
    at('PREPARATION_APP_APPLICATIONS')
    applications = ApplicationService(store, auth)
    if settings.demo:
        applications.seed_demo()
    store.applications = applications
    at('PREPARATION_APP_COMPOSITION')
    composition = CompositionService(store, auth, applications, bindings, connections)
    store.composition = composition
    store.register_execution_guard("execution-bindings",
        lambda owner, plan, context, tool: bindings.recheck(plan, context), tool_independent=True)
    store.register_execution_guard("application-governance",
        lambda owner, plan, context, tool: applications.require_plan_current(plan), tool_independent=True)
    at('PREPARATION_APP_NATIVE_GRAPH')
    executor, registry = build_runtime(settings, store, native_db)
    at('PREPARATION_APP_BRIDGE')
    from .native_workflows import NativeWorkflows
    store.native_workflows = NativeWorkflows(store, auth, native_db, settings.native_workflows)
    store.register_execution_guard("native-workflow", store.native_workflows.require_plan_current)
    bridge = NativeBridge(settings, native_db, auth)
    bridge.configure_components(store.native_workflows.component_for_task)
    at('PREPARATION_APP_DELEGATION')
    delegation = DelegationService(settings, store, auth, bridge)
    delegation.initialize()
    store.delegation = delegation
    at('PREPARATION_APP_PLAN_POLICY')
    policy = PlanPolicyService(store, auth, PlanPolicyConfig(
        name=cast(PolicyName, settings.temporary_policy), revision=settings.policy_revision,
        review_ttl_seconds=settings.plan_review_ttl_seconds, tool_contract=cast(ToolContract, settings.runtime_tool_contract), source_synthesis_enabled=settings.source_synthesis_enabled, tool_policies=resolve_tool_policies(settings.tool_policies, settings.runtime_adapters)), ancestor_guard=persisted_ancestor_guard(store))
    store.plan_policy = policy
    at('PREPARATION_APP_HANDOFF')
    handoff_client = TrustedHandoffClient(store, auth, settings.handoff_targets)
    handoff_client.install_guard()
    store.handoff_client = handoff_client
    store.remote_execution = RemoteExecution(store, handoff_client)
    receiver = PreparedHandoffService(store, auth, bridge, settings.handoff_origins) if settings.handoff_origins else None
    store.handoff_receiver = receiver
    if receiver:
        receiver.install_guard()
    at('PREPARATION_APP_SCHEDULING')
    schedules = SchedulingService(settings, store, native_db, auth, bridge)
    schedules.initialize()
    from .schedule_management import ScheduleManagement, schedule_management_router
    schedule_management = ScheduleManagement(schedules)
    at('PREPARATION_APP_ROUTES')
    base = FastAPI(title="Agent Factory", version="0.2.0", lifespan=schedules.lifespan)
    if receiver:
        base.include_router(receiver.router)
    if settings.handoff_targets:
        base.include_router(origin_authority_router(auth, handoff_client))
    base.include_router(material_governance_router(auth, governance))
    base.include_router(connection_router(auth, connections))
    from .personal_connections import personal_connection_router
    base.include_router(personal_connection_router(auth, connections.personal))
    if credential_vault is not None:
        from .credential_vault import credential_vault_router
        base.include_router(credential_vault_router(auth, credential_vault))
    else:
        @base.get('/api/factory/personal-credentials/capabilities')
        def credential_capabilities(request: Request):
            auth.require(auth.user(request)['id'], 'read')
            return JSONResponse({'enabled': False, 'providerIds': []},
                headers={'Cache-Control': 'private, no-store'})
    base.include_router(application_router(auth, applications))
    base.include_router(composition_router(auth, composition))
    from .synthesis_api import synthesis_router
    base.include_router(synthesis_router(auth, store.synthesis_sources, settings))
    base.include_router(plan_policy_router(auth, policy))
    base.include_router(scheduling_router(auth, schedules))
    base.include_router(schedule_management_router(auth, schedule_management))
    factory_api = FactoryAPI(settings, store, auth, bridge)
    base.include_router(factory_api.router)
    if settings.personal_agent_commands_enabled:
        from .personal_command_api import PersonalCommandAPI
        personal_commands = PersonalCommandAPI(store, auth, factory_api)
        base.include_router(personal_commands.router)
    from .workflow_operations import OperationCustody
    from .workflow_control import WorkflowControl, workflow_router
    # Durable custody remains readable even after operator registrations end.
    store.workflow = OperationCustody(store, auth, runtimes=settings.workflow_runtimes)
    store.workflow_control = WorkflowControl(store.workflow, factory_api)
    base.include_router(workflow_router(auth, store.workflow_control))
    from .autoresearch import AutoResearchService, autoresearch_router
    store.autoresearch = AutoResearchService(store, auth, bridge, settings.autoresearch_presets, commands=factory_api.commands)
    base.include_router(autoresearch_router(auth, store.autoresearch))
    from .openresearch_workspace import OpenResearchWorkspace, openresearch_workspace_router
    openresearch_workspace = OpenResearchWorkspace(store, auth, store.autoresearch, factory=factory_api)
    base.include_router(openresearch_workspace_router(auth, openresearch_workspace))
    from .autoresearch_session_control import AutoResearchSessionControl
    async def complete_research_session(task, requirement):
        from .control_commands import ControlCommand
        from .factory_api import requirement_version
        await factory_api.commands.submit(task['owner_id'], task['id'], ControlCommand(
            commandId='ar-session:' + task['run_id'], action='approve', approved=True,
            requirementId=requirement['id'], version=requirement_version(requirement)))
    store.autoresearch_session_control = AutoResearchSessionControl(store, auth, complete=complete_research_session)
    at('PREPARATION_APP_RESOURCES')
    resources = PersistentResourceService(store, auth, settings.remote_targets)
    from .process_runtime import ProcessRuntimeService
    at('PREPARATION_APP_PROCESS_RUNTIME')
    store.process_runtime = ProcessRuntimeService(store, auth, resources)
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
        from .managed_orx_profile import install_completion_handler
        install_completion_handler(store)
    from .research_runtime import ResearchProcessRuntimeService
    at('PREPARATION_APP_RESEARCH_RUNTIME')
    store.research_runtime = ResearchProcessRuntimeService(store, auth, resources)
    if settings.research_evaluators:
        from .research_evaluation_service import ResearchEvaluationService
        store.research_evaluation = ResearchEvaluationService(store, auth, resources, settings.research_evaluators)
    if settings.remote_scientific_factory is not None:
        from .remote_scientific_origin import RemoteScientificOrigin
        from .remote_scientific_receiver import RemoteScientificReceiver
        scientific = settings.remote_scientific_factory(store, auth, resources, handoff_client,
            receiver, factory_api.commands)
        if type(scientific) is RemoteScientificOrigin:
            store.remote_scientific = scientific
        elif type(scientific) is RemoteScientificReceiver:
            store.remote_scientific_receiver = scientific
        else:
            raise ValueError('REMOTE_SCIENTIFIC_SERVICE_INVALID')
    if settings.autoresearch_children_factory is not None:
        from .autoresearch_children import AutoResearchChildren
        children = settings.autoresearch_children_factory(store, auth, store.autoresearch, resources)
        from .autoresearch_remote_children import AutoResearchRemoteChildren
        if type(children) not in (AutoResearchChildren, AutoResearchRemoteChildren):
            raise ValueError('AUTORESEARCH_CHILD_SERVICE_INVALID')
        store.autoresearch_children = children
    from .comparison_workflow import ComparisonService, comparison_router
    at('PREPARATION_APP_COMPARISONS')
    store.comparisons = ComparisonService(store, auth)
    base.include_router(comparison_router(auth, store.comparisons))
    resource_maintenance = ResourceMaintenance(resources)
    base.include_router(resource_router(auth, resources, resource_maintenance))
    base.include_router(storage_router(auth, store.storage))

    @base.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        detail = error.detail
        if isinstance(detail, dict):
            return JSONResponse(detail, status_code=error.status_code)
        message = str(detail)
        return JSONResponse({"message": message, "code": message.split(":", 1)[0] if ":" in message else "REQUEST_REJECTED"}, status_code=error.status_code)

    @base.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse({"message": "Invalid request fields", "code": "INVALID_REQUEST"}, status_code=422)

    @base.get("/api/factory/auth/config")
    def browser_auth_config():
        from .browser_auth import CONFIG
        return JSONResponse({**CONFIG, "enabled": False}, headers={"Cache-Control": "no-store"})

    @base.get("/api/health")
    def health():
        store.sql("SELECT 1")
        return {"ok": True, "runtime": "Agno 3.1.0", "liveResearchVerified": False}

    web = Path(__file__).resolve().parents[2] / "dist"
    if (web / "assets").is_dir():
        base.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

    @base.get("/")
    def index():
        if not web.joinpath("index.html").exists():
            return JSONResponse({"message": "Build the frontend with npm run build"}, status_code=503)
        return FileResponse(web / "index.html", headers={"Cache-Control": "no-store"})

    @base.get("/favicon.ico", status_code=204)
    def favicon():
        return None

    at('PREPARATION_APP_AGENTOS')
    native = AgentOS(id="agent-factory", agents=[executor], workflows=store.native_workflows.components, db=native_db, registry=registry,
                     base_app=base, on_route_conflict="preserve_base_app", **auth.agentos_kwargs(),
                     queue=QueueConfig(durable=True, max_concurrency=settings.max_workers,
                         max_queue_depth=settings.max_queued,
                         max_attempts=1 if settings.development_live_validation or settings.runtime_tool_contract == "autoresearch-session-v1" else 2, retry_delay_seconds=0,
                         lock_grace_seconds=6, stop_timeout_seconds=2, poll_interval=settings.queue_poll,
                         timeout_seconds=settings.native_timeout_seconds), telemetry=False, mcp=False, scheduler=False,
                     tracing=False, cors_allowed_origins=[f"http://127.0.0.1:{settings.port}"]).get_app()
    at('PREPARATION_APP_ATTACH')
    native.add_middleware(NativeIngress)
    bridge.attach(native)
    # Start after the native DB/worker lifespans; stop before their drain.
    at('PREPARATION_APP_OBSERVER')
    observer = FactoryLifecycleObserver(store, auth, native_db,
                                        lambda: getattr(native.state, "queue_worker", None))
    store.lifecycle_observer = observer
    native_lifespan = native.router.lifespan_context

    @asynccontextmanager
    async def observed_lifespan(app: FastAPI):
        try:
            async with native_lifespan(app) as state:
                async with observer.lifespan(app):
                    try:
                        yield state or {}
                    finally:
                        if store.remote_scientific_receiver is not None:
                            await store.remote_scientific_receiver.close()
                        await store.autoresearch_session_control.close()
        finally:
            # Observer and native worker finish before their shared lock pool.
            store.dispose_root_locks()

    native.router.lifespan_context = observed_lifespan
    native.state.factory = {"store": store, "auth": auth, "bridge": bridge, "settings": settings, "schedules": schedules, "schedule_management": schedule_management, "plan_policy": policy, "handoff_client": handoff_client, "handoff_receiver": receiver, "material_governance": governance, "event_replay": replay, "lifecycle_observer": observer, "connections": connections, "execution_bindings": bindings, "applications": applications, "composition": composition, "synthesis_sources": store.synthesis_sources, "remote_bindings": remote_bindings}
    native.state.factory.update(credential_vault=credential_vault, openresearch_workspace=openresearch_workspace, resources=resources, resource_maintenance=resource_maintenance, process_runtime=store.process_runtime,
        research_runtime=store.research_runtime, research_evaluation=store.research_evaluation)
    at('PREPARATION_APP_BROWSER_AUTH')
    external = None
    if settings.oidc_identity is not None:
        from .oidc_identity import OIDCAccessTokenVerifier, OIDCIdentityBridge
        external = OIDCIdentityBridge(native, auth, OIDCAccessTokenVerifier(settings.oidc_identity))
    if settings.development_mock_login:
        from .development_identity import DevelopmentIdentityProvider
        from .browser_auth import BrowserAuthBridge, BrowserSessionService
        provider = DevelopmentIdentityProvider(demo=settings.demo, public_origin=cast(str, settings.development_public_origin))
        browser_auth = BrowserSessionService(store, auth, provider.config, exchanger=provider.exchanger)
        native.state.factory.update(browser_auth=browser_auth, development_identity=provider)
        return BrowserAuthBridge(native, browser_auth, development_app=provider.app)
    if settings.browser_oidc is not None:
        from .browser_auth import BrowserAuthBridge, BrowserSessionService
        browser_auth = BrowserSessionService(store, auth, settings.browser_oidc)
        native.state.factory["browser_auth"] = browser_auth
        return BrowserAuthBridge(native, browser_auth, bearer_app=external)
    return external if external is not None else CookieBridge(native, settings)


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()

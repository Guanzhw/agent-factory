import os
from contextlib import ExitStack, asynccontextmanager, nullcontext
from typing import cast

os.environ["AGNO_TELEMETRY"] = "false"

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .auth import AuthService, EXECUTOR_ID, MemberTokenBoundary, UnconfiguredIdentityBoundary
from .config import Settings
from .connections import ConnectionService, connection_router
from .execution_bindings import default_bindings
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
    """Factory-bound executors receive their plan through the factory API.

    A context variable is trusted in-process, not a user-controlled HTTP header.
    Native middleware still authenticates and authorizes every internal call.
    """
    def __init__(self, app, workflow_ids=()):
        self.app = app
        self.prefixes = (f"/agents/{EXECUTOR_ID}/", *(f"/workflows/{identifier}/" for identifier in workflow_ids))

    async def __call__(self, scope, receive, send):
        protected = scope.get("path", "").startswith(self.prefixes)
        if scope["type"] == "websocket" and protected and not INTERNAL_NATIVE.get():
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "http" and protected and not INTERNAL_NATIVE.get():
            await JSONResponse({"message": "Use the scoped factory API", "code": "FACTORY_ENVELOPE_REQUIRED"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(settings=None, *, diagnostics=None, factory_api_type=None,
               storage_governance_type=None, lifecycle_observer_type=None,
               model_dispatch_type=None, handoff_client_type=None, handoff_receiver_type=None,
               bindings_factory=None, governance_config=None, policy_config=None,
               queue_max_attempts=2, lifespan_context=None, tool_catalog_factory=None,
               plan_policy_type=None, shutdown_callback=None, delegation_service_type=None,
               connection_service_type=None, shutdown_guard=None):
    """Build the application-neutral Factory; deployment code selects trusted implementations.

    These are ordinary constructor arguments, never request-driven discovery or
    application manifest code. The core works with no research package installed.
    """
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
    store.native_db = native_db
    at('PREPARATION_APP_AUTH')
    auth = AuthService(settings, native_db)
    store.auth = auth
    from .storage_governance import StorageGovernance
    from .storage_api import storage_router
    at('PREPARATION_APP_STORAGE')
    store.storage = (storage_governance_type or StorageGovernance)(store, auth)
    at('PREPARATION_APP_EVENT_REPLAY')
    replay = EventReplay(store, auth, signing_key=auth._key)
    store.event_replay = replay
    at('PREPARATION_APP_GOVERNANCE')
    governance = MaterialGovernance(store, auth, governance_config or GovernanceConfig(
        review_mode="member-self-service", revision=settings.material_policy_revision,
        tool_contract=cast(ToolContract, settings.runtime_tool_contract)))
    store.material_governance = governance
    store.register_execution_guard("material-governance",
        lambda owner, plan, context, tool: governance.require_materials_current(plan), tool_independent=True)
    at('PREPARATION_APP_CONNECTIONS')
    from .local_credentials import local_credential_vault
    credential_vault = (settings.credential_vault_factory(store.engine) if settings.credential_vault_factory
        else local_credential_vault(store.engine, settings.runtime_directory))
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
    from .personal_remote_provider import OpenCodeServeProvider, PROVIDER_ID as OPENCODE_PROVIDER
    from .credential_vault import VaultSecretProvider
    if OPENCODE_PROVIDER in credential_vault.capabilities()['providerIds']:
        personal_providers.setdefault(OPENCODE_PROVIDER, OpenCodeServeProvider(VaultSecretProvider(credential_vault, OPENCODE_PROVIDER)))
    connections = (connection_service_type or ConnectionService)(store, auth, settings.trusted_connections,
        personal_providers=personal_providers)
    store.connections = connections
    from .personal_ssh import PersonalSSHServers, SSHEnrollmentConfig, personal_ssh_router
    from .ssh_credentials import PROVIDER_ID as SSH_PROVIDER
    store.personal_ssh = (PersonalSSHServers(auth, connections, credential_vault,
        settings.ssh_self_service or SSHEnrollmentConfig())
        if SSH_PROVIDER in credential_vault.capabilities()['providerIds'] else None)
    from .personal_tools import PersonalTools, personal_tool_router
    store.personal_tools = PersonalTools(connections, credential_vault, settings.personal_tool_adapters)
    connections.personal_tools = store.personal_tools
    from .personal_models import PersonalModels, personal_model_router
    store.personal_models = PersonalModels(store, auth, connections, credential_vault,
        transport_factory=settings.owner_model_transport_factory,
        trusted_model_proxy=settings.owner_model_trusted_proxy,
        proxy_environment_id=settings.owner_model_proxy_environment_id)
    connections.owner_models = store.personal_models
    at('PREPARATION_APP_BINDINGS')
    bindings = (bindings_factory or default_bindings)(settings, store, connections)
    store.personal_models.register(bindings)
    at('PREPARATION_APP_RUNTIME_ADAPTERS')
    for entry in settings.runtime_adapters:
        bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
            tool_name=entry.tool_name, connection_kind=entry.connection_kind,
            required_capabilities=entry.required_capabilities, permissions=entry.permissions,
            validator=entry.validator, connection_adapter_ref=entry.connection_adapter_ref)
    store.personal_tools.register(bindings)
    store.execution_bindings = bindings
    prices = { (price.adapter_id, price.adapter_revision): price for price in default_zero_prices() }
    for price in settings.usage_pricing:
        prices[(price.adapter_id, price.adapter_revision)] = price
    at('PREPARATION_APP_USAGE_LEDGER')
    if settings.fee_management_enabled:
        store.usage_ledger = UsageLedger(store, prices=tuple(prices.values()), policy=settings.usage_policy)
    from .local_budget_scopes import LocalBudgetScopes
    store.local_budget_scopes = LocalBudgetScopes(store, getattr(store, 'usage_ledger', None))
    store.register_execution_guard('local-budget-scopes', store.local_budget_scopes.require_current)
    from .owner_submission import OwnerSubmissions
    store.owner_submissions = OwnerSubmissions(store)
    at('PREPARATION_APP_REMOTE_BINDINGS')
    remote_bindings = RemoteBindingService(store, auth, bindings, connections, settings.remote_binding_mappings)
    store.remote_bindings = remote_bindings
    at('PREPARATION_APP_APPLICATIONS')
    applications = ApplicationService(store, auth)
    store.applications = applications
    at('PREPARATION_APP_COMPOSITION')
    composition = CompositionService(store, auth, applications, bindings, connections)
    store.composition = composition
    store.register_execution_guard("execution-bindings", bindings.require_execution, tool_independent=True)
    store.register_execution_guard("application-governance",
        lambda owner, plan, context, tool: applications.require_plan_current(plan), tool_independent=True)
    at('PREPARATION_APP_NATIVE_GRAPH')
    executor, registry = build_runtime(settings, store, native_db, model_dispatch_type=model_dispatch_type,
        catalog=tool_catalog_factory(settings, store) if tool_catalog_factory else None)
    at('PREPARATION_APP_BRIDGE')
    from .native_workflows import NativeWorkflows
    store.native_workflows = NativeWorkflows(store, auth, native_db, settings.native_workflows)
    store.register_execution_guard("native-workflow", store.native_workflows.require_plan_current)
    bridge = NativeBridge(settings, native_db, auth)
    bridge.configure_components(store.native_workflows.component_for_task)
    at('PREPARATION_APP_DELEGATION')
    delegation = (delegation_service_type or DelegationService)(settings, store, auth, bridge)
    delegation.initialize()
    store.delegation = delegation
    at('PREPARATION_APP_PLAN_POLICY')
    policy = (plan_policy_type or PlanPolicyService)(store, auth, policy_config or PlanPolicyConfig(
        name=cast(PolicyName, settings.temporary_policy), revision=settings.policy_revision,
        tool_contract=cast(ToolContract, settings.runtime_tool_contract)), ancestor_guard=persisted_ancestor_guard(store))
    store.plan_policy = policy
    at('PREPARATION_APP_HANDOFF')
    handoff_client = (handoff_client_type or TrustedHandoffClient)(store, auth, settings.handoff_targets)
    handoff_client.install_guard()
    store.handoff_client = handoff_client
    store.remote_execution = RemoteExecution(store, handoff_client)
    receiver = (handoff_receiver_type or PreparedHandoffService)(store, auth, bridge, settings.handoff_origins) if settings.handoff_origins else None
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
    from .accounts import account_router
    base.include_router(account_router(auth))
    base.include_router(personal_ssh_router(auth, store.personal_ssh))
    if receiver:
        base.include_router(receiver.router)
    if settings.handoff_targets:
        base.include_router(origin_authority_router(auth, handoff_client))
    base.include_router(material_governance_router(auth, governance))
    base.include_router(connection_router(auth, connections))
    base.include_router(personal_tool_router(auth, store.personal_tools))
    from .personal_connections import personal_connection_router
    base.include_router(personal_connection_router(auth, connections.personal))
    from .credential_vault import credential_vault_router
    base.include_router(credential_vault_router(auth, credential_vault))
    base.include_router(application_router(auth, applications))
    from .assistant_endpoints import AssistantEndpoints, assistant_endpoints_router
    assistant_endpoints = AssistantEndpoints(store, auth, applications)
    base.include_router(assistant_endpoints_router(auth, assistant_endpoints))
    from .application_content import ApplicationContent, application_content_router
    application_content = ApplicationContent(store, auth, connections.sharing)
    base.include_router(application_content_router(auth, application_content))
    base.include_router(composition_router(auth, composition))
    base.include_router(plan_policy_router(auth, policy))
    base.include_router(scheduling_router(auth, schedules))
    base.include_router(schedule_management_router(auth, schedule_management))
    factory_api = (factory_api_type or FactoryAPI)(settings, store, auth, bridge)
    base.include_router(factory_api.router)
    from .application_runs import ApplicationRuns
    from .assistant_messages import AssistantMessages, assistant_messages_router
    assistant_messages = AssistantMessages(store, auth, assistant_endpoints, ApplicationRuns(factory_api), application_content)
    store.assistant_messages = assistant_messages
    base.include_router(assistant_messages_router(auth, assistant_messages))
    from .assistant_events import AssistantEvents
    from .assistant_delivery import assistant_delivery_lifespan
    assistant_events = AssistantEvents(store, auth, assistant_endpoints, application_content,
        assistant_messages, store.local_budget_scopes)
    store.assistant_events = assistant_events
    base.include_router(personal_model_router(auth, store.personal_models))
    from .workflow_operations import OperationCustody
    from .workflow_control import WorkflowControl, workflow_router
    # Durable custody remains readable even after operator registrations end.
    store.workflow = OperationCustody(store, auth, runtimes=settings.workflow_runtimes)
    store.workflow_control = WorkflowControl(store.workflow, factory_api)
    base.include_router(workflow_router(auth, store.workflow_control))
    at('PREPARATION_APP_RESOURCES')
    resources = PersistentResourceService(store, auth, settings.remote_targets)
    from .process_runtime import ProcessRuntimeService
    at('PREPARATION_APP_PROCESS_RUNTIME')
    store.process_runtime = ProcessRuntimeService(store, auth, resources)
    if settings.ssh_training_profiles:
        from .ssh_operation_runtime import SSHOperationRuntime
        from .ssh_operation_waits import SSHOperationWaits
        from .ssh_process_contract import BINDINGS, OPERATION_PIN, RUNTIME_OWNER
        from .ssh_process_provider import EFFECT
        from .ssh_tool_factory import ssh_tool_registrations
        if store.personal_ssh is None:
            raise ValueError('SSH training requires the existing personal SSH credential service')
        ssh_runtime = SSHOperationRuntime(store, resources, store.personal_ssh, settings.ssh_training_profiles)
        resources.ssh_targets = ssh_runtime
        resources.execution_runtimes[EFFECT] = ssh_runtime
        operation_key = tuple(OPERATION_PIN[key] for key in ('adapterId', 'revision', 'configFingerprint'))
        if operation_key in store.workflow.runtimes:
            raise ValueError('SSH operation runtime is already registered')
        store.workflow.runtimes[operation_key] = ssh_runtime
        for entry in ssh_tool_registrations(ssh_runtime):
            bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                tool_name=entry.tool_name, connection_kind=entry.connection_kind,
                required_capabilities=entry.required_capabilities, permissions=entry.permissions,
                validator=entry.validator, connection_adapter_ref=entry.connection_adapter_ref)
        store.application_runtime.register(RUNTIME_OWNER,
            SSHOperationWaits(store, store.workflow, OPERATION_PIN, commands=factory_api.commands,
                runs=ApplicationRuns(factory_api)),
            bindings=BINDINGS)
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

    web = settings.web_directory
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
                         max_attempts=queue_max_attempts, retry_delay_seconds=0,
                         lock_grace_seconds=6, stop_timeout_seconds=2, poll_interval=settings.queue_poll,
                         timeout_seconds=settings.native_timeout_seconds), telemetry=False, mcp=False, scheduler=False,
                     tracing=False, cors_allowed_origins=[f"http://127.0.0.1:{settings.port}"]).get_app()
    at('PREPARATION_APP_ATTACH')
    native.add_middleware(MemberTokenBoundary)
    native.add_middleware(NativeIngress, workflow_ids=tuple(workflow.id for workflow in store.native_workflows.components))
    bridge.attach(native)
    # Start after the native DB/worker lifespans; stop before their drain.
    at('PREPARATION_APP_OBSERVER')
    observer = (lifecycle_observer_type or FactoryLifecycleObserver)(store, auth, native_db,
                                        lambda: getattr(native.state, "queue_worker", None))
    store.lifecycle_observer = observer
    from .delegated_operations import DELEGATED_OPERATION_PIN, DelegatedOperations
    delegated_key = tuple(DELEGATED_OPERATION_PIN[field] for field in ('adapterId', 'revision', 'configFingerprint'))
    if delegated_key in store.workflow.runtimes:
        raise ValueError('The built-in delegated operation pin cannot be replaced')
    store.workflow.runtimes[delegated_key] = DelegatedOperations(delegation, observer, DELEGATED_OPERATION_PIN)
    native_lifespan = native.router.lifespan_context

    @asynccontextmanager
    async def observed_lifespan(app: FastAPI):
        # Arm a deployment-selected process policy only when shutdown begins,
        # before any application/native context exits; keep it through cleanup.
        with ExitStack() as shutdown:
            armed = False
            def begin_shutdown():
                nonlocal armed
                if not armed:
                    armed = True
                    if assistant_events.admission_stopping is not None:
                        assistant_events.admission_stopping.set()
                    if shutdown_guard is not None:
                        deadline = shutdown.enter_context(shutdown_guard())
                        if deadline is not None:
                            native.state.factory['shutdown_deadline'] = deadline
            native.state.factory['begin_shutdown'] = begin_shutdown
            try:
                async with native_lifespan(app) as state:
                    async with observer.lifespan(app):
                        async with assistant_delivery_lifespan(assistant_events):
                            async with lifespan_context(app) if lifespan_context else nullcontext():
                                try:
                                    yield state or {}
                                finally:
                                    begin_shutdown()
            finally:
                begin_shutdown()
                native.state.factory.pop('begin_shutdown', None)
                # Observer and native worker finish before their shared lock pool.
                try:
                    store.dispose_root_locks()
                finally:
                    if store.personal_ssh is not None:
                        store.personal_ssh.close()
                    if shutdown_callback is not None:
                        shutdown_callback(native.state.factory)

    native.router.lifespan_context = observed_lifespan
    native.state.factory = {"store": store, "auth": auth, "bridge": bridge, "settings": settings, "schedules": schedules, "schedule_management": schedule_management, "plan_policy": policy, "handoff_client": handoff_client, "handoff_receiver": receiver, "material_governance": governance, "event_replay": replay, "lifecycle_observer": observer, "connections": connections, "execution_bindings": bindings, "applications": applications, "composition": composition, "remote_bindings": remote_bindings}
    native.state.factory.update(credential_vault=credential_vault, resources=resources,
        resource_maintenance=resource_maintenance, process_runtime=store.process_runtime,
        factory_api=factory_api, assistant_endpoints=assistant_endpoints,
        assistant_messages=assistant_messages, application_content=application_content,
        assistant_events=assistant_events, local_budget_scopes=store.local_budget_scopes, http_app=native)
    at('PREPARATION_APP_BROWSER_AUTH')
    external = None
    if settings.oidc_identity is not None:
        from .oidc_identity import OIDCAccessTokenVerifier, OIDCIdentityBridge
        external = OIDCIdentityBridge(native, auth, OIDCAccessTokenVerifier(settings.oidc_identity))
    if settings.browser_oidc is not None:
        from .browser_auth import BrowserAuthBridge, BrowserSessionService
        browser_auth = BrowserSessionService(store, auth, settings.browser_oidc)
        native.state.factory["browser_auth"] = browser_auth
        return BrowserAuthBridge(native, browser_auth, bearer_app=external)
    return external if external is not None else UnconfiguredIdentityBoundary(native)


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()

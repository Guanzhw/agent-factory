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
        protected = scope.get("path", "").startswith(("/agents/factory-executor", "/schedules"))
        if scope["type"] == "http" and protected and not INTERNAL_NATIVE.get():
            await JSONResponse({"message": "Use the scoped factory API", "code": "FACTORY_ENVELOPE_REQUIRED"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    settings.runtime_directory.mkdir(parents=True, exist_ok=True)
    native_db = PostgresDb(db_url=settings.db_url, id="factory-native-postgres")
    store = Store(settings.db_url, settings)
    initialize_orx_experiments(store)
    store.native_db = native_db
    auth = AuthService(settings, native_db)
    auth.initialize_demo()
    store.auth = auth
    from .storage_governance import StorageGovernance
    from .storage_api import storage_router
    store.storage = StorageGovernance(store, auth)
    replay = EventReplay(store, auth, signing_key=auth._key)
    store.event_replay = replay
    if settings.demo:
        seed_catalog(store)
    governance = MaterialGovernance(store, auth, GovernanceConfig(
        review_mode=cast(Literal["separate-admin", "demo-self-review"], settings.material_review_mode), revision=settings.material_policy_revision, tool_contract=cast(ToolContract, settings.runtime_tool_contract)))
    if settings.demo:
        governance.adopt_demo_bootstrap()
    store.material_governance = governance
    store.register_execution_guard("material-governance",
        lambda owner, plan, context, tool: governance.require_materials_current(plan), tool_independent=True)
    connections = ConnectionService(store, auth, settings.trusted_connections)
    store.connections = connections
    bindings = default_bindings(settings, store, connections)
    register_orx_adapter(bindings)
    register_literature_adapters(bindings)
    bindings.register("model", LITERATURE_MODEL_ID, "1", lambda context: LiteratureEvidenceModel())
    register_orx_experiment_adapters(bindings)
    bindings.register("model", MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION, lambda context: LocalORXWorkflowModel())
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
    store.execution_bindings = bindings
    prices = { (price.adapter_id, price.adapter_revision): price for price in default_zero_prices() }
    if settings.development_profile == "opencode-go":
        from .go_development import MODEL_ADAPTER_IDS
        from .go_usage import pricing_registrations
        for price in pricing_registrations(MODEL_ADAPTER_IDS):
            prices[(price.adapter_id, price.adapter_revision)] = price
    for price in settings.usage_pricing:
        prices[(price.adapter_id, price.adapter_revision)] = price
    store.usage_ledger = UsageLedger(store, prices=tuple(prices.values()), policy=settings.usage_policy)
    remote_bindings = RemoteBindingService(store, auth, bindings, connections, settings.remote_binding_mappings)
    store.remote_bindings = remote_bindings
    applications = ApplicationService(store, auth)
    if settings.demo:
        applications.seed_demo()
    store.applications = applications
    composition = CompositionService(store, auth, applications, bindings, connections)
    store.composition = composition
    store.register_execution_guard("execution-bindings",
        lambda owner, plan, context, tool: bindings.recheck(plan, context), tool_independent=True)
    store.register_execution_guard("application-governance",
        lambda owner, plan, context, tool: applications.require_plan_current(plan), tool_independent=True)
    executor, registry = build_runtime(settings, store, native_db)
    bridge = NativeBridge(settings, native_db, auth)
    delegation = DelegationService(settings, store, auth, bridge)
    delegation.initialize()
    store.delegation = delegation
    policy = PlanPolicyService(store, auth, PlanPolicyConfig(
        name=cast(PolicyName, settings.temporary_policy), revision=settings.policy_revision,
        review_ttl_seconds=settings.plan_review_ttl_seconds, tool_contract=cast(ToolContract, settings.runtime_tool_contract)), ancestor_guard=persisted_ancestor_guard(store))
    store.plan_policy = policy
    handoff_client = TrustedHandoffClient(store, auth, settings.handoff_targets)
    handoff_client.install_guard()
    store.remote_execution = RemoteExecution(store, handoff_client)
    receiver = PreparedHandoffService(store, auth, bridge, settings.handoff_origins) if settings.handoff_origins else None
    store.handoff_receiver = receiver
    if receiver:
        receiver.install_guard()
    schedules = SchedulingService(settings, store, native_db, auth, bridge)
    schedules.initialize()
    base = FastAPI(title="Agent Factory", version="0.2.0", lifespan=schedules.lifespan)
    if receiver:
        base.include_router(receiver.router)
    if settings.handoff_targets:
        base.include_router(origin_authority_router(auth, handoff_client))
    base.include_router(material_governance_router(auth, governance))
    base.include_router(connection_router(auth, connections))
    base.include_router(application_router(auth, applications))
    base.include_router(composition_router(auth, composition))
    base.include_router(plan_policy_router(auth, policy))
    base.include_router(scheduling_router(auth, schedules))
    base.include_router(FactoryAPI(settings, store, auth, bridge).router)
    resources = PersistentResourceService(store, auth, settings.remote_targets)
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

    native = AgentOS(id="agent-factory", agents=[executor], db=native_db, registry=registry,
                     base_app=base, on_route_conflict="preserve_base_app", **auth.agentos_kwargs(),
                     queue=QueueConfig(durable=True, max_concurrency=settings.max_workers,
                         max_queue_depth=settings.max_queued,
                         max_attempts=1 if settings.development_live_validation else 2, retry_delay_seconds=0,
                         lock_grace_seconds=6, stop_timeout_seconds=2, poll_interval=settings.queue_poll,
                         timeout_seconds=60), telemetry=False, mcp=False, scheduler=False,
                     tracing=False, cors_allowed_origins=[f"http://127.0.0.1:{settings.port}"]).get_app()
    native.add_middleware(NativeIngress)
    bridge.attach(native)
    # Start after the native DB/worker lifespans; stop before their drain.
    observer = FactoryLifecycleObserver(store, auth, native_db,
                                        lambda: getattr(native.state, "queue_worker", None))
    store.lifecycle_observer = observer
    native_lifespan = native.router.lifespan_context

    @asynccontextmanager
    async def observed_lifespan(app: FastAPI):
        try:
            async with native_lifespan(app) as state:
                async with observer.lifespan(app):
                    yield state or {}
        finally:
            # Observer and native worker finish before their shared lock pool.
            store.dispose_root_locks()

    native.router.lifespan_context = observed_lifespan
    native.state.factory = {"store": store, "auth": auth, "bridge": bridge, "settings": settings, "schedules": schedules, "plan_policy": policy, "handoff_client": handoff_client, "handoff_receiver": receiver, "material_governance": governance, "event_replay": replay, "lifecycle_observer": observer, "connections": connections, "execution_bindings": bindings, "applications": applications, "composition": composition, "remote_bindings": remote_bindings}
    native.state.factory.update(resources=resources, resource_maintenance=resource_maintenance)
    if settings.oidc_identity is not None:
        from .oidc_identity import OIDCAccessTokenVerifier, OIDCIdentityBridge
        return OIDCIdentityBridge(native, auth, OIDCAccessTokenVerifier(settings.oidc_identity))
    return CookieBridge(native, settings)


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()

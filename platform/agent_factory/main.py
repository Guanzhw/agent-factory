import os
from contextlib import ExitStack, asynccontextmanager, nullcontext

os.environ["AGNO_TELEMETRY"] = "false"

from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .auth import AuthService, MemberTokenBoundary, UnconfiguredIdentityBoundary
from .config import Settings
from .connections import ConnectionService, connection_router
from .delegation import DelegationService
from .factory_api import FactoryAPI
from .lifecycle_observer import FactoryLifecycleObserver
from .native_bridge import NativeBridge
from .runtime import build_runtime
from .store import Store


async def http_error(request: Request, error: HTTPException):
    detail = error.detail
    if isinstance(detail, dict):
        return JSONResponse(detail, status_code=error.status_code, headers=error.headers)
    message = str(detail)
    return JSONResponse({"message": message, "code": message.split(":", 1)[0] if ":" in message else "REQUEST_REJECTED"},
                        status_code=error.status_code, headers=error.headers)


def create_app(settings=None, *, diagnostics=None, queue_max_attempts=2,
               lifespan_context=None, shutdown_callback=None, shutdown_guard=None):
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
    connections = ConnectionService(store, auth, settings.trusted_connections,
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
    store.personal_models = PersonalModels(store, auth, connections, credential_vault)
    connections.owner_models = store.personal_models
    at('PREPARATION_APP_NATIVE_GRAPH')
    executor, registry = build_runtime(store, native_db)
    at('PREPARATION_APP_BRIDGE')
    bridge = NativeBridge(settings, native_db, auth, store=store)
    at('PREPARATION_APP_DELEGATION')
    delegation = DelegationService(settings, store, auth, bridge)
    delegation.initialize()
    store.delegation = delegation
    at('PREPARATION_APP_ROUTES')
    base = FastAPI(title="Agent Factory", version="0.2.0")
    from .accounts import account_router
    base.include_router(account_router(auth))
    base.include_router(personal_ssh_router(auth, store.personal_ssh))
    base.include_router(connection_router(auth, connections))
    base.include_router(personal_tool_router(auth, store.personal_tools))
    from .personal_connections import personal_connection_router
    base.include_router(personal_connection_router(auth, connections.personal))
    from .credential_vault import credential_vault_router
    base.include_router(credential_vault_router(auth, credential_vault))
    from .assistant_endpoints import AssistantEndpoints, assistant_endpoints_router
    assistant_endpoints = AssistantEndpoints(store, auth)
    base.include_router(assistant_endpoints_router(auth, assistant_endpoints))
    from .application_content import ApplicationContent, application_content_router
    application_content = ApplicationContent(store, auth, connections.sharing)
    base.include_router(application_content_router(auth, application_content))
    factory_api = FactoryAPI(settings, store, auth, bridge)
    base.include_router(factory_api.router)
    from .application_runs import ApplicationRuns
    from .assistant_messages import AssistantMessages, assistant_messages_router
    assistant_messages = AssistantMessages(store, auth, assistant_endpoints, ApplicationRuns(factory_api), application_content)
    store.assistant_messages = assistant_messages
    base.include_router(assistant_messages_router(auth, assistant_messages))
    from .assistant_events import AssistantEvents
    from .assistant_delivery import assistant_delivery_lifespan
    assistant_events = AssistantEvents(store, auth, assistant_endpoints, application_content,
        assistant_messages)
    store.assistant_events = assistant_events
    base.include_router(personal_model_router(auth, store.personal_models))
    base.exception_handler(HTTPException)(http_error)

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
    native = AgentOS(id="agent-factory", agents=[executor], workflows=[], db=native_db, registry=registry,
                     base_app=base, on_route_conflict="preserve_base_app", **auth.agentos_kwargs(),
                     queue=QueueConfig(durable=True, max_concurrency=settings.max_workers,
                         max_queue_depth=settings.max_queued,
                         max_attempts=queue_max_attempts, retry_delay_seconds=0,
                         lock_grace_seconds=6, stop_timeout_seconds=2, poll_interval=settings.queue_poll,
                         timeout_seconds=settings.native_timeout_seconds), telemetry=False, mcp=False, scheduler=False,
                     tracing=False, cors_allowed_origins=[f"http://127.0.0.1:{settings.port}"]).get_app()
    at('PREPARATION_APP_ATTACH')
    native.add_middleware(MemberTokenBoundary)
    bridge.attach(native)
    # Start after the native DB/worker lifespans; stop before their drain.
    at('PREPARATION_APP_OBSERVER')
    observer = FactoryLifecycleObserver(store, auth, native_db,
                                        lambda: getattr(native.state, "queue_worker", None))
    store.lifecycle_observer = observer
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
    native.state.factory = {
        "store": store, "auth": auth, "bridge": bridge, "settings": settings, "executor": executor,
        "lifecycle_observer": observer, "connections": connections,
        "credential_vault": credential_vault, "factory_api": factory_api,
        "assistant_endpoints": assistant_endpoints, "assistant_messages": assistant_messages,
        "application_content": application_content, "assistant_events": assistant_events,
        "http_app": native,
    }
    at('PREPARATION_APP_BROWSER_AUTH')
    external = None
    if settings.oidc_identity is not None:
        from .oidc_identity import OIDCAccessTokenVerifier, OIDCIdentityBridge
        external = OIDCIdentityBridge(native, auth, OIDCAccessTokenVerifier(settings.oidc_identity))
    if settings.browser_oidc is not None or settings.local_login_origin is not None:
        from .browser_auth import BrowserAuthBridge, BrowserSessionService
        browser_auth = BrowserSessionService(store, auth, settings.browser_oidc,
            local_login_origin=settings.local_login_origin)
        native.state.factory["browser_auth"] = browser_auth
        return BrowserAuthBridge(native, browser_auth, bearer_app=external)
    return external if external is not None else UnconfiguredIdentityBoundary(native)


def main():
    import uvicorn
    from .shutdown import shutdown_guard
    settings = Settings.from_env()
    uvicorn.run(create_app(settings, shutdown_guard=shutdown_guard), host=settings.host, port=settings.port,
        access_log=False, timeout_graceful_shutdown=35)


if __name__ == "__main__":
    main()

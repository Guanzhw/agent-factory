"""Static deployment composition for the application-independent Factory."""
from copy import copy

from agent_factory.main import create_app as create_core_app
from agent_factory.config import Settings
from .shutdown import shutdown_failed, shutdown_guard
from .application_composition import (validate_applications, install_applications,
    application_lifespan, release_applications)


def factory_state(app):
    while not hasattr(getattr(app, 'state', None), 'factory'):
        app = app.app
    return app.state.factory


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

def native_queue_attempts(settings):
    # Go already owns bounded provider retries and UNKNOWN usage custody.
    # A second native job attempt must not create another paid request after
    # a failed/ambiguous model call. This responsibility does not belong to an app.
    return 1 if settings.development_profile == 'opencode-go' or settings.development_live_validation else 2


def create_app(settings=None, *, diagnostics=None, applications=None):
    applications = validate_applications(() if applications is None else applications)
    settings = copy(settings or Settings.from_env())
    if settings.development_profile == 'opencode-go':
        # Explicit operator development selection, never loaded by the core.
        from agent_factory.go_development import model_registrations, MODEL_ADAPTER_IDS
        from agent_factory.go_usage import pricing_registrations
        settings.runtime_adapters = [*settings.runtime_adapters, *model_registrations()]
        # Keep explicit operator pricing overrides last.
        settings.usage_pricing = (*pricing_registrations(MODEL_ADAPTER_IDS), *settings.usage_pricing)
    app = create_core_app(settings, diagnostics=diagnostics,
        lifespan_context=application_lifespan(applications),
        shutdown_callback=lambda state: release_applications(state, applications),
        shutdown_guard=shutdown_guard,
        queue_max_attempts=native_queue_attempts(settings))
    state = factory_state(app)
    state.update(shutdown_failed=shutdown_failed)
    try:
        install_applications(state, applications)
    except BaseException:
        # Application aborts run first while shared dependencies remain usable.
        _abort_shared_store(state['store'])
        raise
    return app


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == '__main__':
    main()

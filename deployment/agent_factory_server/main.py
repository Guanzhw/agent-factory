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
    return 2


def create_app(settings=None, *, diagnostics=None, applications=None):
    applications = validate_applications(() if applications is None else applications)
    settings = copy(settings or Settings.from_env())
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

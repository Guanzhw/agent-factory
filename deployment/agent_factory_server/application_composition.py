"""Explicit static application assembly; no request-driven discovery or DI."""
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from inspect import iscoroutinefunction
from typing import Any, Callable


@dataclass(frozen=True)
class ApplicationAssembly:
    name: str
    install: Callable[[dict], Any]
    lifespan: Callable | None = None
    shutdown: Callable[[dict], Any] | None = None
    abort: Callable[[dict], Any] | None = None
    # Exclusive mutation slots; consumers may share these resources without
    # claiming their installation. Constructors and aborts are synchronous and
    # must not start execution or unbounded cleanup before the runtime lifespan.
    shared_claims: tuple[str, ...] = ()


def validate_applications(applications):
    """Reject ambiguous ownership before constructing stores or dispatchers."""
    names, claims = set(), set()
    result = tuple(applications)
    for application in result:
        if not isinstance(application, ApplicationAssembly) or not application.name:
            raise ValueError('APPLICATION_ASSEMBLY_INVALID')
        if any(callback is not None and (not callable(callback) or iscoroutinefunction(callback))
               for callback in (application.install, application.shutdown, application.abort)):
            raise ValueError('APPLICATION_ASSEMBLY_SYNC_CALLBACK_REQUIRED')
        if application.name in names:
            raise ValueError('APPLICATION_OWNER_DUPLICATE')
        names.add(application.name)
        for claim in application.shared_claims:
            if not claim or claim in claims:
                raise ValueError('APPLICATION_SHARED_OWNER_DUPLICATE')
            claims.add(claim)
    return result


def install_applications(state, applications):
    started = []
    try:
        for application in applications:
            # Include a partially constructed owner in constructor cleanup.
            started.append(application)
            application.install(state)
    except BaseException:
        for application in reversed(started):
            if application.abort is not None:
                try:
                    application.abort(state)
                except Exception:
                    pass  # Preserve the original construction failure.
        raise


def application_lifespan(applications):
    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            try:
                for application in applications:
                    if application.lifespan is not None:
                        await stack.enter_async_context(application.lifespan(app))
                yield
            finally:
                # Also arm before partial-startup unwind; no owner can begin
                # blocking cleanup before the deployment's shared deadline.
                state = getattr(getattr(app, 'state', None), 'factory', {})
                begin = state.get('begin_shutdown')
                if begin is not None:
                    begin()
    return lifespan


def release_applications(state, applications):
    # Core invokes this only after all app contexts, observer and native stop.
    for application in reversed(applications):
        if application.shutdown is not None:
            application.shutdown(state)

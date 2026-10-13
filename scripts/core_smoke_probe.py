"""Installed-wheel child probe; called by check_core_install.py with python -I.

Uses production-mode Settings and the application-neutral core create_app.
Research table/route/catalog assertions match test_core_package_distribution.
No deployment entrypoint, app registration, task submission or model request
is made here; a synthetic member exists only in the disposable DB and sends GETs.
"""
import argparse
import asyncio
from contextlib import ExitStack, redirect_stdout
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


# The explicit application-schema contract from test_core_package_distribution;
# this is not a whole-repository name scan or a model/provider denylist.
RESEARCH_TABLE_PREFIXES = ("af_orx", "af_autoresearch", "af_openresearch", "af_inference",
    "af_research", "af_literature", "af_synthesis", "af_comparison", "af_remote_scientific")


class SmokeFailure(RuntimeError):
    """Fixed probe diagnostics safe to include without runtime secrets."""


def request(port, route, headers=None):
    opener = build_opener(ProxyHandler({}))
    try:
        response = opener.open(Request(f"http://127.0.0.1:{port}{route}", headers=headers or {}), timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def health(port):
    status, body = request(port, "/api/health")
    if status != 200 or body.get("ok") is not True:
        raise SmokeFailure("Core health response was not ready")


def empty_catalog(native, port):
    auth = native.state.factory["auth"]
    owner, role = "core-smoke-member", "core-smoke-member-role"
    auth.directory.upsert(owner, name="Synthetic core smoke member")
    # Match the existing distribution test's member capabilities. The catalog
    # currently requires the member's run capability even for these GETs.
    auth.authorization.define_role(role, ["agents:factory-executor:read", "agents:factory-executor:run", "components:read",
        "registry:read", "sessions:read", "filesystem:read"])
    auth.authorization.assign(owner, role)
    headers = {"Authorization": "Bearer " + auth._issue_native_token(owner)}
    for route in ("/api/factory/materials", "/api/factory/applications"):
        status, body = request(port, route, headers)
        if status != 200 or body != []:
            raise SmokeFailure(f"Expected empty catalog at {route}; received HTTP {status}")
    if request(port, "/api/factory/openresearch/capabilities", headers)[0] != 404:
        raise SmokeFailure("Standalone core exposed the research capability route")


async def probe(timeout, summary):
    summary["phase"] = "isolation"
    if sys.prefix == sys.base_prefix:
        raise SmokeFailure("Core smoke requires a fresh virtual environment")
    for module in ("agent_factory_research", "agent_factory_server"):
        if importlib.util.find_spec(module) is not None:
            raise SmokeFailure("An application/deployment package is importable")
    import agent_factory
    if not Path(agent_factory.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise SmokeFailure("Core was not imported from the smoke virtual environment")
    summary["appPackagesAbsent"] = True
    from agent_factory.config import Settings
    from agent_factory.main import create_app
    from sqlalchemy import create_engine, text
    import uvicorn

    with ExitStack() as cleanup, TemporaryDirectory(prefix="workspace-", dir=Path.cwd()) as workspace, socket.socket() as listener:
        settings = Settings(db_url=os.environ["FACTORY_CORE_SMOKE_DATABASE_URL"], demo=False,
            jwt_key=secrets.token_urlsafe(48), workspace=Path(workspace), max_workers=1,
            web_directory=Path(workspace) / "no-web")
        if (settings.runtime_adapters or settings.usage_pricing or settings.native_workflows
                or any(hasattr(settings, name) for name in
                    ("autoresearch_presets", "research_evaluators", "platform_openresearch", "ssh_openresearch"))):
            raise SmokeFailure("Core Settings retained application configuration or registrations")
        engine = create_engine(settings.db_url)
        cleanup.callback(engine.dispose)
        def tables():
            with engine.connect() as connection:
                names = sorted(row[0] for row in connection.execute(text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog','information_schema')")))
            if any(name.startswith(RESEARCH_TABLE_PREFIXES) for name in names):
                raise SmokeFailure("Standalone core created a research table")
            return names
        snapshots = {"before": tables()}
        if snapshots["before"]:
            raise SmokeFailure("Core smoke requires a new empty database")
        summary["phase"] = "create_app"
        app = create_app(settings)
        native = app
        while not hasattr(getattr(native, "state", None), "factory"):
            native = native.app
        store = native.state.factory["store"]
        cleanup.callback(store.engine.dispose)
        cleanup.callback(store.native_db.db_engine.dispose)
        snapshots["assembled"] = tables()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on",
            access_log=False, log_level="error"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            summary["phase"] = "startup"
            async with asyncio.timeout(timeout):
                while not server.started:
                    if serving.done():
                        await serving
                        raise SmokeFailure("Server exited before lifespan readiness")
                    await asyncio.sleep(.05)
                summary["lifespanReady"] = True
                summary["phase"] = "health"
                await asyncio.to_thread(health, port)
                if serving.done():
                    await serving
                    raise SmokeFailure("Server exited before health observation completed")
                summary["healthOK"] = True
                summary["phase"] = "application_absence"
                if getattr(native.state, "queue_worker", None) is None:
                    raise SmokeFailure("Native queue worker was not started")
                await asyncio.to_thread(empty_catalog, native, port)
                snapshots["running"] = await asyncio.to_thread(tables)
                if not {"af_tasks", "af_materials"} <= set(snapshots["running"]):
                    raise SmokeFailure("Core tables were not initialized")
                summary.update(nativeWorkerReady=True, materialsEmpty=True, applicationsEmpty=True, researchRouteAbsent=True)
        finally:
            if summary.get("researchRouteAbsent"):
                summary["phase"] = "shutdown"
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=timeout)
            # Uvicorn logs lifespan failures and may return without raising.
            if server.lifespan.startup_failed or server.lifespan.shutdown_failed or server.lifespan.error_occurred:
                raise SmokeFailure("ASGI lifespan reported a startup/shutdown failure")
        summary["cleanShutdown"] = True
        snapshots["stopped"] = tables()
        if snapshots["running"] != snapshots["stopped"]:
            raise SmokeFailure("Schema changed during shutdown")
        if any(name.split(".")[0] in {"agent_factory_research", "agent_factory_server"} for name in sys.modules):
            raise SmokeFailure("An application package was loaded during core startup")
        summary.update(researchTablesAbsent=True, tableCounts={phase: len(names) for phase, names in snapshots.items()})
    summary.update(phase="complete", accepted=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    summary = {"accepted": False, "modelRunRequested": False}
    try:
        if args.timeout <= 0:
            raise ValueError("Timeout must be positive")
        # Runtime logs do not mix with the one machine-readable result.
        with redirect_stdout(sys.stderr):
            asyncio.run(probe(args.timeout, summary))
    except Exception as error:
        summary.update(accepted=False, errorType=type(error).__name__)
        if isinstance(error, SmokeFailure):
            summary["failure"] = str(error)
        if isinstance(error, ModuleNotFoundError):
            summary["missingModule"] = error.name
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

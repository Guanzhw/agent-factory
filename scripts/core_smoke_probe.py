"""Installed-wheel child probe; called by check_core_install.py with python -I.

Pending A confirmation: core exposes agent_factory.config.Settings and
agent_factory.main.create_app, accepts production-mode Settings without app
registrations, and serves /api/health returning {"ok": true}. No deployment
entrypoint, app registration, task submission or model request is made here.
"""
import argparse
import asyncio
from contextlib import redirect_stdout
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from tempfile import TemporaryDirectory
from urllib.request import ProxyHandler, build_opener


def health(port):
    with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
        if response.status != 200 or json.load(response).get("ok") is not True:
            raise RuntimeError("Core health response was not ready")


async def probe(timeout, summary):
    summary["phase"] = "isolation"
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Core smoke requires a fresh virtual environment")
    for module in ("agent_factory_research", "agent_factory_server"):
        if importlib.util.find_spec(module) is not None:
            raise RuntimeError("An application/deployment package is importable")
    import agent_factory
    if not Path(agent_factory.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Core was not imported from the smoke virtual environment")
    summary["appPackagesAbsent"] = True
    from agent_factory.config import Settings
    from agent_factory.main import create_app
    import uvicorn

    with TemporaryDirectory(prefix="workspace-", dir=Path.cwd()) as workspace, socket.socket() as listener:
        summary["phase"] = "create_app"
        app = create_app(Settings(db_url=os.environ["FACTORY_CORE_SMOKE_DATABASE_URL"], demo=False,
            jwt_key=secrets.token_urlsafe(48), workspace=Path(workspace)))
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
                        raise RuntimeError("Server exited before lifespan readiness")
                    await asyncio.sleep(.05)
                summary["lifespanReady"] = True
                summary["phase"] = "health"
                await asyncio.to_thread(health, port)
                if serving.done():
                    await serving
                    raise RuntimeError("Server exited before health observation completed")
                summary["healthOK"] = True
        finally:
            if summary.get("healthOK"):
                summary["phase"] = "shutdown"
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=timeout)
            # Uvicorn logs lifespan failures and may return without raising.
            if server.lifespan.startup_failed or server.lifespan.shutdown_failed or server.lifespan.error_occurred:
                raise RuntimeError("ASGI lifespan reported a startup/shutdown failure")
        summary["cleanShutdown"] = True
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
        if isinstance(error, ModuleNotFoundError):
            summary["missingModule"] = error.name
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

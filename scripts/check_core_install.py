"""Build/install/start the core without application source, using disposable PG.

Run: uv run python scripts/check_core_install.py --root /path/to/checkout
Requires FACTORY_TEST_DATABASE_URL and the outer environment's PG dependencies.

The standalone distribution is platform/pyproject.toml with platform/LICENSE
and agent_factory sources beside it. platform/tests/pg_fixture.py provides the
outer disposable database; none of its test code is installed into the venv.
The copied stage deliberately has no apps, deployment, tests, lockfile or Git
checkout. The fresh venv installs the wheel's declared dependencies, not an
editable checkout.
Installation/lifecycle evidence must be paired with the real ownership gate:
the old flat package can still contain application implementations internally.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def command(arguments, directory, *, timeout=300, env=None):
    result = subprocess.run(arguments, cwd=directory, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Build/install logs can contain configured index URLs. Keep the summary
        # independent of credentials and never print a database URL or env dump.
        raise RuntimeError(f"{Path(arguments[0]).name} {arguments[1]} exited {result.returncode}")
    return result


def postgres_fixture(root):
    spec = importlib.util.spec_from_file_location("core_smoke_pg_fixture", root / "platform/tests/pg_fixture.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Disposable PostgreSQL fixture is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.IsolatedPostgres


def run(root, timeout, summary):
    database_url = os.environ.get("FACTORY_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("FACTORY_TEST_DATABASE_URL is required for disposable PostgreSQL")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to build and install the core wheel")
    with TemporaryDirectory(prefix="factory-core-install-") as directory:
        temporary = Path(directory)
        build_env = {**os.environ, "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(temporary / "uv-cache"))}
        stage, wheels, environment, runtime = (temporary / name for name in ("stage", "wheels", "venv", "runtime"))
        stage.mkdir(); wheels.mkdir(); runtime.mkdir()
        summary["phase"] = "stage"
        for filename in ("pyproject.toml", "LICENSE"):
            shutil.copy2(root / "platform" / filename, stage / filename)
        shutil.copytree(root / "platform/agent_factory", stage / "agent_factory",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        probe = temporary / "core_smoke_probe.py"
        shutil.copy2(Path(__file__).with_name("core_smoke_probe.py"), probe)
        summary["phase"] = "build"
        command([uv, "build", "--wheel", "--out-dir", str(wheels)], stage, env=build_env)
        artifacts = list(wheels.glob("*.whl"))
        if len(artifacts) != 1:
            raise RuntimeError("Expected exactly one core wheel")
        summary["wheel"] = artifacts[0].name
        summary["phase"] = "install"
        command([uv, "venv", "--python", sys.executable, str(environment)], temporary, env=build_env)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command([uv, "pip", "install", "--python", str(python), str(artifacts[0])], runtime, env=build_env)
        summary["wheelInstalled"] = True
        summary["phase"] = "database"
        with postgres_fixture(root)(database_url) as database:
            # The runtime receives the isolated DB and OS necessities only;
            # provider credentials and checkout/PYTHONPATH settings are absent.
            env = {name: value for name, value in os.environ.items()
                   if name.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "TMPDIR"}}
            env.update(FACTORY_CORE_SMOKE_DATABASE_URL=database.url, AGNO_TELEMETRY="false")
            summary["phase"] = "runtime"
            result = subprocess.run([str(python), "-I", "-B", str(probe), "--timeout", str(timeout)],
                cwd=runtime, env=env, capture_output=True, text=True, timeout=2 * timeout + 15)
            child = json.loads(result.stdout)
            summary.update(child)
            # Only the outer process can accept after database cleanup too.
            summary["accepted"] = False
            if result.returncode or child.get("accepted") is not True:
                raise RuntimeError("Core lifecycle probe failed")
        summary.update(phase="complete", accepted=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="Checkout to build in isolation")
    parser.add_argument("--timeout", type=float, default=60, help="Seconds allowed for each startup/shutdown phase")
    args = parser.parse_args(argv)
    summary = {"suite": "core_install_smoke", "accepted": False, "modelRunRequested": False}
    try:
        if args.timeout <= 0:
            raise ValueError("Timeout must be positive")
        run(args.root.resolve(), args.timeout, summary)
    except Exception as error:
        summary["accepted"] = False
        summary.setdefault("errorType", type(error).__name__)
        # These are fixed driver messages, not arbitrary third-party exceptions.
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

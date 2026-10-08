"""Explicit loopback-only demo. Uses already installed PostgreSQL binaries.

No downloads, system service, firewall change, model account or global install.
Only .local/postgres is initialized. Ctrl+C stops owned processes.
"""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def command(args):
    return subprocess.run([str(arg) for arg in args], check=True, capture_output=True, text=True,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", default=os.getenv("FACTORY_POSTGRES_BIN", ""))
    parser.add_argument("--db-port", type=int, default=65431)
    parser.add_argument("--port", type=int, default=3100)
    args = parser.parse_args()
    extension = ".exe" if os.name == "nt" else ""
    bin_path = Path(args.postgres_bin) if args.postgres_bin else Path(shutil.which("postgres") or "").parent
    def binary(name):
        return bin_path / (name + extension)
    if not binary("initdb").is_file():
        parser.error("Set --postgres-bin to an existing PostgreSQL bin directory")
    local = ROOT / ".local"
    data = (local / "postgres").resolve()
    if not data.is_relative_to(local.resolve()):
        raise ValueError("Demo cluster path escaped project .local")
    local.mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", args.db_port))
    if not data.joinpath("PG_VERSION").exists():
        command([binary("initdb"), "-D", data, "-U", "factory_demo", "-A", "trust", "--encoding=UTF8", "--locale=C"])
        data.joinpath("pg_hba.conf").write_text("host all all 127.0.0.1/32 trust\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with local.joinpath("postgres.log").open("ab") as log:
        pg = subprocess.Popen([str(binary("postgres")), "-D", str(data), "-h", "127.0.0.1", "-p", str(args.db_port)],
                              stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        api = None
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                ready = subprocess.run([str(binary("pg_isready")), "-h", "127.0.0.1", "-p", str(args.db_port), "-U", "factory_demo"], capture_output=True, creationflags=flags)
                if ready.returncode == 0:
                    break
                if pg.poll() is not None:
                    raise RuntimeError("Owned demo PostgreSQL exited; inspect .local/postgres.log")
                time.sleep(.1)
            else:
                raise TimeoutError("Demo PostgreSQL did not become ready")
            command([binary("psql"), "-h", "127.0.0.1", "-p", args.db_port, "-U", "factory_demo", "-d", "postgres", "-c", "SELECT 1"])
            probe = command([binary("psql"), "-h", "127.0.0.1", "-p", args.db_port, "-U", "factory_demo", "-d", "postgres", "-Atc", "SELECT 1 FROM pg_database WHERE datname='factory_demo'"])
            if not probe.stdout.strip():
                command([binary("createdb"), "-h", "127.0.0.1", "-p", args.db_port, "-U", "factory_demo", "factory_demo"])
            env = {**os.environ, "PYTHONPATH": str(ROOT / "platform"), "FACTORY_MODE": "demo",
                   "FACTORY_DATABASE_URL": f"postgresql+psycopg://factory_demo@127.0.0.1:{args.db_port}/factory_demo",
                   "FACTORY_WORKSPACE": str(local), "FACTORY_PORT": str(args.port), "AGNO_TELEMETRY": "false"}
            print(f"Synthetic demo only: http://127.0.0.1:{args.port}. Ctrl+C stops owned services.", flush=True)
            with local.joinpath("api.log").open("ab") as api_log:
                api = subprocess.Popen([sys.executable, "-m", "agent_factory"], cwd=ROOT, env=env, creationflags=flags, stdout=api_log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
                returncode = api.wait()
                if returncode:
                    raise RuntimeError(f"Factory exited with code {returncode}; inspect .local/api.log")
        finally:
            if api and api.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(api.pid), "/T", "/F"], check=True, capture_output=True, creationflags=flags)
                else:
                    import signal
                    os.killpg(api.pid, signal.SIGTERM)
                api.wait(timeout=10)
            if pg.poll() is None:
                command([binary("pg_ctl"), "stop", "-D", data, "-m", "fast", "-w", "-t", "20"])
                pg.wait(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

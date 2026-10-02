"""Opt-in task-owned loopback ORX toy service with generated demo identities.

Only a newly generated database receives fixture reviewer grants. The marker,
store and experiment workspaces are retained for exact-run restart/recovery.
No provider credentials, cloud resources, dashboard warm-up or paid models.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform"))
os.environ["AGNO_TELEMETRY"] = "false"

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
import uvicorn

from agent_factory.local_orx_profile import (APPLICATION_ID, CONNECTION_NAME, PROFILE_REVISION,
    REGISTRATION_REF, local_profile_settings, publish_local_orx_application)
from agent_factory.main import create_app
from agent_factory.orx_experiment_tools import READ_CAPABILITY, RUN_CAPABILITY, reclaim_orx_experiment
from agent_factory.orx_local import TaskLocalORXProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated-demo", action="store_true", required=True,
                        help="Required explicit opt-in: generated demo identities and a dedicated loopback database")
    parser.add_argument("--database-url", required=True, help="Authorized existing loopback PostgreSQL base URL")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--git-binary", type=Path, required=True)
    parser.add_argument("--python-binary", type=Path, default=Path(sys._base_executable))
    parser.add_argument("--fixture-file", type=Path, help="Optional private generated browser credentials; never commit")
    parser.add_argument("--port", type=int, default=3104)
    args = parser.parse_args()
    if os.name != "nt" or not 1024 <= args.port <= 65535:
        parser.error("This actual toy profile requires Windows job containment and an unprivileged loopback port")
    base = make_url(args.database_url)
    if base.get_backend_name() != "postgresql" or base.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("The service creates only an owned database on an authorized loopback PostgreSQL server")
    workspace = args.workspace.resolve()
    marker_path = workspace / ".owned-orx-local-profile.json"
    endpoint = {"host": base.host, "port": base.port, "username": base.username}
    if args.resume:
        if workspace.is_symlink() or not marker_path.is_file() or marker_path.is_symlink():
            parser.error("Resume requires an exact existing generated profile marker")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("schema") != 1 or marker.get("profile") != PROFILE_REVISION or marker.get("endpoint") != endpoint:
            parser.error("The existing workspace/database identity differs from this profile")
        name = marker.get("databaseName", "")
        if not re.fullmatch(r"af_orx_demo_[0-9a-f]{32}", name):
            parser.error("The existing database is not a generated local profile")
    else:
        workspace.mkdir(parents=True, exist_ok=False)
        name = "af_orx_demo_" + uuid4().hex
        admin = create_engine(base, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as connection:
                connection.execute(text('CREATE DATABASE "' + name + '"'))
        finally:
            admin.dispose()
        marker = {"schema": 1, "profile": PROFILE_REVISION, "databaseName": name, "endpoint": endpoint,
                  "createdAt": datetime.now(timezone.utc).isoformat()}
        marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    url = base.set(database=name).render_as_string(hide_password=False)
    provider = TaskLocalORXProvider(binary=args.binary.resolve(), source_archive=args.source_archive.resolve(),
        git_binary=args.git_binary.resolve(), python_binary=args.python_binary.resolve())
    settings = local_profile_settings(db_url=url, workspace=workspace, provider=provider, port=args.port)
    application = create_app(settings)
    state = application.app.state.factory
    auth, store = state["auth"], state["store"]
    if not args.resume:
        # Only the just-created generated fixture store gets a distinct native admin.
        auth.authorization.unassign("bob", "factory-user")
        auth.authorization.assign("bob", "factory-manager")
    published = publish_local_orx_application(state, author="manager", reviewer="bob")
    connection = state["connections"].bind("alice", REGISTRATION_REF, PROFILE_REVISION + ":owner-binding",
        capabilities=[READ_CAPABILITY, RUN_CAPABILITY])
    if args.fixture_file:
        args.fixture_file.parent.mkdir(parents=True, exist_ok=True)
        args.fixture_file.write_text(json.dumps({"baseUrl": f"http://127.0.0.1:{args.port}",
            "applicationId": APPLICATION_ID, "connectionRefs": {CONNECTION_NAME: connection["ref"]},
            "ownerHeaders": {"Authorization": "Bearer " + auth._issue_native_token("alice", lifetime_seconds=3600)},
            "reviewerHeaders": {"Authorization": "Bearer " + auth._issue_native_token("manager", lifetime_seconds=3600)}}, indent=2), encoding="utf-8")
    stop = workspace / "stop-local-orx.txt"
    if args.resume and stop.exists():
        if stop.is_symlink() or not stop.is_file():
            parser.error("Owned stop flag must remain a regular file")
        stop.unlink()
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=args.port, access_log=False))
    def observe_stop():
        while not server.should_exit:
            if stop.exists():
                server.should_exit = True
                return
            time.sleep(.25)
    watcher = threading.Thread(target=observe_stop, name="owned-orx-stop", daemon=True)
    watcher.start()
    print(json.dumps({"kind": "owned-loopback-orx-toy", "url": f"http://127.0.0.1:{args.port}",
        "applicationId": published["id"], "applicationVersion": published["version"], "modelProviders": 0,
        "identities": "generated-demo-only", "databaseRetained": True}, ensure_ascii=False), flush=True)
    try:
        server.run()
    finally:
        server.should_exit = True
        watcher.join(timeout=2)
        async def reclaim():
            for task in store.tasks("alice"):
                try:
                    observed = await reclaim_orx_experiment(settings, store, task["id"])
                    if observed and observed.get("status") not in {"NOT_STARTED"} and observed.get("stopEvidence", {}).get("allStopped") is not True:
                        print(json.dumps({"cleanup": "not-confirmed", "taskId": task["id"]}), flush=True)
                except Exception as error:
                    print(json.dumps({"cleanup": "not-confirmed", "taskId": task["id"], "errorType": type(error).__name__}), flush=True)
        asyncio.run(reclaim())
        store.engine.dispose()
        store.native_db.db_engine.dispose()


if __name__ == "__main__":
    main()

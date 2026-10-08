#!/usr/bin/env python3
"""Explicit DEVELOPMENT MOCK login server; never production or provider acceptance."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform"))

from sqlalchemy.engine import make_url
import uvicorn

from agent_factory.config import Settings
from agent_factory.development_identity import validate_development_origin
from agent_factory.development_tls import temporary_development_tls
from agent_factory.main import create_app
from agent_factory.development_workflows import controlled_workflow_settings, initialize_controlled_fixtures


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "DEVELOPMENT_LAUNCH_ARGUMENTS_INVALID\n")


def main(argv=None):
    parser = _Arguments(description=__doc__)
    parser.add_argument("--public-origin", required=True, help="Explicit HTTPS loopback origin including port")
    parser.add_argument("--workspace", required=True, help="Dedicated development workspace")
    parser.add_argument("--database-url", help="Existing PostgreSQL database; alternatively FACTORY_DATABASE_URL")
    parser.add_argument("--profile", choices=("basic", "controlled-workflows"), default="basic",
                        help="Explicit controlled-workflows adds synthetic source/synthesis and fixed local comparisons")
    parser.add_argument("--initialize-controlled-fixtures", action="store_true",
                        help="Explicit separate-review fixture publication and initial owner connection binding; no task approval")
    args = parser.parse_args(argv)
    try:
        if args.initialize_controlled_fixtures and args.profile != "controlled-workflows":
            raise ValueError()
        origin = validate_development_origin(args.public_origin)
        parsed = urlsplit(origin)
        if parsed.port is None:
            raise ValueError()
        database_url = args.database_url if args.database_url is not None else os.getenv("FACTORY_DATABASE_URL")
        if not database_url:
            raise ValueError()
        database = make_url(database_url)
        if database.drivername not in {"postgresql", "postgresql+psycopg"} or not database.database:
            raise ValueError()
        workspace = Path(args.workspace).resolve()
        if workspace == Path(workspace.anchor) or workspace == Path(__file__).resolve().parents[1]:
            raise ValueError()
        assert parsed.hostname is not None
        bind_host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
        settings = Settings(db_url=database_url, workspace=workspace, demo=True,
            development_mock_login=True, development_public_origin=origin,
            temporary_policy="admin-review", max_workers=1, host=bind_host, port=parsed.port)
        with ExitStack() as lifecycle:
            if args.profile == "controlled-workflows":
                settings = lifecycle.enter_context(controlled_workflow_settings(settings))
            application = create_app(settings)
            if args.profile == "controlled-workflows":
                factory = application.app.state.factory
                lifecycle.callback(factory["store"].engine.dispose)
                lifecycle.callback(factory["store"].native_db.db_engine.dispose)
                if args.initialize_controlled_fixtures:
                    initialize_controlled_fixtures(factory)
            certificate, key = lifecycle.enter_context(temporary_development_tls(origin))
            print("DEVELOPMENT MOCK ONLY — synthetic Alice/Bob/manager/manager2; no real unified login.", flush=True)
            print("Base URL: " + origin, flush=True)
            print("Temporary self-signed TLS; no system trust changes. Use only this dedicated development database/workspace.", flush=True)
            print("Development profile: " + args.profile, flush=True)
            if args.profile == "controlled-workflows":
                print("Synthetic sources and controlled synthesis; fixed Linux comparison processes. No live retrieval/model, remote host or aggregate isolation.", flush=True)
                print("Fixture publication is explicit; every task still needs its own current plan review.", flush=True)
            uvicorn.run(application, host=bind_host, port=parsed.port, ssl_certfile=str(certificate), ssl_keyfile=str(key),
                        access_log=False, log_level="warning")
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("DEVELOPMENT_LAUNCH_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

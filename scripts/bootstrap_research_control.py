"""Explicit loopback development control plane, not a training launcher.

Requires an existing, operator-designated PostgreSQL database. No database,
identity credential, task, run, lease, training result or review is fabricated.
A trusted caller may supply build_application(settings) directly to main; module
names, Python paths and executable configuration are never accepted as input.
Deterministic orchestration is distinct from provider/scientific verification.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import stat
import sys
from typing import Callable, cast
from urllib.parse import urlsplit

FAILURE = 'RESEARCH_CONTROL_BOOTSTRAP_FAILED'


def _require(ok):
    if not ok:
        raise ValueError(FAILURE)


def _directory(path):
    _require(os.name == 'posix' and type(path) is str and path.startswith('/')
             and str(Path(path)) == path and '..' not in Path(path).parts)
    flags = getattr(os, 'O_NOFOLLOW', None)
    directory = getattr(os, 'O_DIRECTORY', None)
    _require(type(flags) is int and flags != 0 and type(directory) is int and directory != 0)
    flags, directory = cast(int, flags), cast(int, directory)
    fd = os.open('/', os.O_RDONLY | directory | flags)
    try:
        for part in Path(path).parts[1:]:
            nxt = os.open(part, os.O_RDONLY | directory | flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_database_url(path):
    _require(type(path) is str and path.startswith('/') and str(Path(path)) == path)
    parent = _directory(str(Path(path).parent))
    fd = None
    try:
        nofollow, nonblock, getuid = (getattr(os, name, None) for name in ('O_NOFOLLOW', 'O_NONBLOCK', 'getuid'))
        _require(type(nofollow) is int and nofollow != 0 and type(nonblock) is int and nonblock != 0 and callable(getuid))
        fd = os.open(Path(path).name, os.O_RDONLY | cast(int, nofollow) | cast(int, nonblock), dir_fd=parent)
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_uid == cast(Callable[[], int], getuid)()
                 and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1 and 0 < before.st_size <= 4096)
        raw = os.read(fd, 4097)
        after = os.fstat(fd)
        current = os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
        def stamp(s):
            return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        _require(len(raw) == before.st_size and stamp(before) == stamp(after) == stamp(current))
        value = raw.decode('utf-8')
        _require(value == value.strip() and not any(ord(c) < 32 for c in value) and '\\' not in value)
        parsed = urlsplit(value)
        _require(parsed.scheme == 'postgresql+psycopg' and parsed.hostname in {'127.0.0.1', '::1'}
                 and parsed.port is not None and 1 <= parsed.port <= 65535
                 and not parsed.query and not parsed.fragment and parsed.username
                 and parsed.path.startswith('/') and parsed.path.count('/') == 1 and len(parsed.path) > 1)
        # Literal authority, no percent-encoded host, libpq service or multihost override.
        authority = parsed.netloc.rsplit('@', 1)[-1]
        _require(authority == (f'[{parsed.hostname}]:{parsed.port}' if parsed.hostname == '::1'
                              else f'{parsed.hostname}:{parsed.port}'))
        # Explicit hostaddr prevents an inherited libpq PGHOSTADDR from redirecting transport.
        return value + "?hostaddr=" + str(parsed.hostname) + "&connect_timeout=5"
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def _workspace(path, *, create):
    _require(type(path) is str and path.startswith('/') and str(Path(path)) == path and path != '/')
    parent = _directory(str(Path(path).parent))
    try:
        # Never reset or silently attach to another control plane's custody.
        try:
            os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(FAILURE)
        if create:
            os.mkdir(Path(path).name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
    finally:
        os.close(parent)
    return Path(path)


DEVELOPMENT_REVIEWER = 'task-dev-reviewer'


def ensure_task_development_reviewer(state):
    """Trusted bootstrap only; separate code identity, not independent human review.

    Does not grant a token or restore an existing identity's revoked rights.
    Call from the operator factory before governed publication, on its explicitly
    designated development database. All publication APIs still check authority.
    """
    settings, auth = state['settings'], state['auth']
    _require(settings.demo is True and settings.temporary_policy == 'admin-review'
             and settings.host == '127.0.0.1' and settings.max_workers == 1)
    if auth.directory.get(DEVELOPMENT_REVIEWER) is None:
        auth.directory.upsert(DEVELOPMENT_REVIEWER,
                              name='Task development reviewer (code identity, not independent human)')
        auth.authorization.assign(DEVELOPMENT_REVIEWER, 'factory-manager')
    auth.require(DEVELOPMENT_REVIEWER, 'agent_os:admin')
    return DEVELOPMENT_REVIEWER


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(FAILURE)


def main(argv=None, *, build_application=None, serve=None):
    """Trusted function injection is code-level only; CLI cannot load plugins."""
    previous_logging = logging.root.manager.disable
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument('--database-url-file', required=True)
        parser.add_argument('--workspace', required=True)
        parser.add_argument('--port', type=int, required=True)
        parser.add_argument('--ack-local-development', action='store_true', required=True)
        parser.add_argument('--ack-dedicated-database', action='store_true', required=True)
        parser.add_argument('--check-config', action='store_true')
        args = parser.parse_args(argv)
        _require(1024 <= args.port <= 65535)
        url = read_database_url(args.database_url_file)
        workspace = _workspace(args.workspace, create=False)
        from agent_factory.config import Settings
        settings = Settings(db_url=url, workspace=workspace, demo=True, max_workers=1,
                            max_user_tasks=1, max_total_tasks=1, max_queued=1,
                            temporary_policy='admin-review', host='127.0.0.1', port=args.port)
        from agent_factory.research_bootstrap_policy import development_settings
        settings = development_settings(settings)
        if args.check_config:
            print('RESEARCH_CONTROL_CONFIG_VALID_NOT_CONNECTED')
            return 0
        if build_application is None:
            from agent_factory.main import create_app
            build_application = create_app
        if serve is None:
            from uvicorn import run
            serve = run
        # No DSN/credentials or raw initialization errors reach logs or traceback.
        logging.disable(logging.CRITICAL)
        _workspace(str(workspace), create=True)
        app = build_application(settings)
        serve(app, host='127.0.0.1', port=args.port, workers=1, access_log=False, log_config=None)
        return 0
    except Exception:
        print(FAILURE, file=sys.stderr)
        return 2
    finally:
        logging.disable(previous_logging)


if __name__ == '__main__':
    raise SystemExit(main())

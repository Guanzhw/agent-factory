"""Private declarative operator entry; publication and serving are explicit actions.

Trusted assembly is injected by the control plane, never imported from JSON.
Checking only describes settings and reads existing database policy; it does not
construct an application, publish materials, or access model credentials.
"""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, cast

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from agent_factory.config import Settings
from agent_factory.research_bootstrap_database_preflight import database_preflight

ERROR = 'AUTORESEARCH_OPERATOR_INVALID'
MAX_CONFIG = 2 * 1024**2
# Fixed reviewed sibling modules, including under Python isolated startup.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def require(value):
    if not value:
        raise ValueError(ERROR)


def configuration(raw) -> dict[str, Any]:
    require(type(raw) is bytes and 0 < len(raw) <= MAX_CONFIG)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result); result[key] = value
        return result
    def invalid(_):
        raise ValueError(ERROR)
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid)
    require(type(value) is dict and set(value) == {'schema', 'role', 'workspace', 'port',
        'databaseRef', 'jwtRef', 'handoffBearerRef', 'project', 'publication'})
    value = cast(dict[str, Any], value)
    require(type(value['schema']) is int and value['schema'] == 1
        and value['role'] in ('controller', 'receiver'))
    require(type(value['workspace']) is str and Path(value['workspace']).is_absolute()
        and '..' not in Path(value['workspace']).parts and '\x00' not in value['workspace'])
    require(type(value['port']) is int and 1 <= value['port'] <= 65535)
    for key in ('databaseRef', 'jwtRef', 'handoffBearerRef'):
        require(type(value[key]) is str and re.fullmatch('[A-Z_][A-Z0-9_]{0,127}', value[key]))
    require(type(value['project']) is dict and bool(value['project']))
    publication = value['publication']
    require(type(publication) is dict and set(publication) == {'author', 'reviewer'})
    for owner in publication.values():
        require(type(owner) is str and 1 <= len(owner) <= 200 and owner.isprintable())
    require(publication['author'] != publication['reviewer'])
    json.dumps(value, allow_nan=False)
    return value


def read_configuration(path):
    """Read one owned private regular file through no-follow directory handles."""
    require(os.name == 'posix')
    directory, nofollow = getattr(os, 'O_DIRECTORY', None), getattr(os, 'O_NOFOLLOW', None)
    if type(directory) is not int or type(nofollow) is not int:
        raise ValueError(ERROR)
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts)
    fd = os.open('/', os.O_RDONLY | directory | nofollow)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd); fd = child
        parent = os.fstat(fd)
        require(stat.S_IMODE(parent.st_mode) == 0o700 and parent.st_uid == os.getuid())
        file_fd = os.open(path.name, os.O_RDONLY | nofollow | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(file_fd)
            require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_nlink == 1 and before.st_uid == os.getuid() and 0 < before.st_size <= MAX_CONFIG)
            raw = b''
            while len(raw) < before.st_size:
                chunk = os.read(file_fd, min(65536, before.st_size - len(raw)))
                require(bool(chunk)); raw += chunk
            after = os.fstat(file_fd)
            def stamp(info):
                return tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_size',
                    'st_mode', 'st_nlink', 'st_uid', 'st_mtime_ns', 'st_ctime_ns'))
            require(not os.read(file_fd, 1) and stamp(before) == stamp(after)
                and stamp(os.stat(path.name, dir_fd=fd, follow_symlinks=False)) == stamp(after))
        finally:
            os.close(file_fd)
    finally:
        os.close(fd)
    return configuration(raw)


@dataclass(frozen=True)
class OperatorBindings:
    describe_settings: Callable
    construct_application: Callable
    prepare_publication: Callable


def environment_resolver(reference):
    require(type(reference) is str and re.fullmatch('[A-Z_][A-Z0-9_]{0,127}', reference))
    value = os.environ.get(reference)
    require(type(value) is str and bool(value))
    return value


def default_bindings():
    from autoresearch_operator_bindings import describe_settings, construct_application, prepare_publication
    return OperatorBindings(describe_settings, construct_application, prepare_publication)


def build_operator(config, bindings, *, resolve=environment_resolver):
    require(type(bindings) is OperatorBindings)
    config = configuration(json.dumps(config, allow_nan=False).encode())
    database_url = resolve(config['databaseRef'])
    require(make_url(database_url).get_backend_name() == 'postgresql')
    settings = bindings.describe_settings(config, database_url)
    require(type(settings) is Settings and settings.host == '127.0.0.1'
        and settings.port == config['port'] and settings.workspace == Path(config['workspace'])
        and settings.db_url == database_url)
    return settings


def execute(config, bindings, action, *, resolve=environment_resolver,
            engine_factory=create_engine, preflight=database_preflight, serve=None):
    require(action in ('check', 'prepare', 'serve'))
    settings = build_operator(config, bindings, resolve=resolve)
    engine = engine_factory(settings.db_url, connect_args={'connect_timeout': 5})
    try:
        report = preflight(engine, settings)
    finally:
        engine.dispose()
    if report['status'] != 'PASS' or action == 'check':
        return report
    if action == 'serve':
        require(config['project'].get('applicationRef') is not None)
    app = bindings.construct_application(config, settings, resolve)
    publication = None
    try:
        if action == 'prepare':
            publication = bindings.prepare_publication(app, config['publication'])
        else:
            if serve is None:
                import uvicorn
                serve = uvicorn.run
            serve(app, host='127.0.0.1', port=settings.port, access_log=False)
    finally:
        close = getattr(app, 'close', None)
        if callable(close): close()
    return {'schema': 1, 'kind': 'AUTORESEARCH_OPERATOR', 'status': 'PASS', 'action': action,
        'executionVerified': False, 'scientificConclusionVerified': False,
        **({'publication': publication} if type(publication) is dict else {})}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(ERROR)


def main(argv=None, *, bindings=None):
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument('--config', required=True)
        actions = parser.add_mutually_exclusive_group(required=True)
        actions.add_argument('--check', action='store_true')
        actions.add_argument('--prepare', action='store_true')
        actions.add_argument('--serve', action='store_true')
        args = parser.parse_args(argv)
        config = read_configuration(args.config)
        report = execute(config, bindings or default_bindings(),
            'check' if args.check else 'prepare' if args.prepare else 'serve')
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['status'] == 'PASS' else 2
    except Exception:
        print(json.dumps({'schema': 1, 'kind': 'AUTORESEARCH_OPERATOR', 'status': 'BLOCKED',
            'code': ERROR, 'executionVerified': False, 'scientificConclusionVerified': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Prepare/check one pinned Factory wheel repair in an operator-selected task venv.

Never runs uv, imports installed packages, changes site, or performs rollback.
The operator must select the NEW unsealed task environment, never an original
sealed environment. All paths/snapshots/commands remain in private evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile
from types import SimpleNamespace

# Explicit reviewed sibling tools are available even with Python isolated mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import copy_install_site as copying
import verify_closure as closure

FIX_SHA = 'ee479cf871534572d62b292bdd616e7e657ddc2a93e1d2713e26af78c91bc587'
DIST = 'department_agent_factory-0.2.0.dist-info'
PLAN = 'factory-repair-plan.json'


def need(ok):
    if not ok:
        raise ValueError('FACTORY_REPAIR_REJECTED')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def file_identity(path, *, collect=False, maximum=64 * 1024**2, system_tool=False):
    path = Path(copying.absolute(path))
    parent = copying.open_directory(str(path.parent))
    nofollow, _, nonblock = copying.flags()
    fd = None
    try:
        fd = os.open(path.name, os.O_RDONLY | nofollow | nonblock, dir_fd=parent)
        before = os.fstat(fd)
        if system_tool:
            # The already-approved uv binary may be system-owned. Package and
            # evidence files still require task ownership and one link below.
            need(stat.S_ISREG(before.st_mode) and not before.st_mode & 0o7022 and before.st_mode & 0o111)
        else:
            copying.owned(before)
        need(before.st_size <= maximum)
        digest, pieces, count = hashlib.sha256(), [], 0
        while block := os.read(fd, min(1024**2, maximum - count + 1)):
            count += len(block); need(count <= maximum); digest.update(block)
            if collect: pieces.append(block)
        need(count == before.st_size and copying.stamp(os.fstat(fd)) == copying.stamp(before)
             == copying.stamp(os.stat(path.name, dir_fd=parent, follow_symlinks=False)))
        return {'sha256': digest.hexdigest(), 'size': count, 'mode': stat.S_IMODE(before.st_mode),
                'nlink': before.st_nlink}, b''.join(pieces)
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)


def snapshot(site):
    fd = copying.open_directory(str(site))
    try:
        original, count, total = copying.scan(fd)
        rows = {}
        for parts, stamp in sorted(original.items()):
            if not parts: continue
            name = '/'.join(parts)
            if stat.S_ISDIR(stamp[2]):
                rows[name] = {'kind': 'directory', 'mode': stat.S_IMODE(stamp[2]), 'nlink': stamp[5]}
            else:
                identity, _ = file_identity(site.joinpath(*parts), maximum=copying.MAX_FILE_BYTES)
                rows[name] = {'kind': 'file', **identity}
        need(copying.scan(fd)[0] == original)
        reopened = copying.open_directory(str(site))
        try: need(copying.pin(os.fstat(reopened)) == copying.pin(os.fstat(fd)))
        finally: os.close(reopened)
        return {'rootIdentity': list(copying.pin(os.fstat(fd))), 'files': count, 'bytes': total, 'rows': rows}
    finally:
        os.close(fd)


def non_factory(rows):
    return {name: row for name, row in rows.items()
            if name.split('/')[0] not in {'agent_factory', DIST}}


def package_matches(rows, expected):
    actual = {name: row['sha256'] for name, row in rows.items()
              if name.startswith('agent_factory/') and row['kind'] == 'file'}
    need(actual == expected)  # Also rejects pyc, extensions and stale package files.
    need(all(name.split('/')[0] == DIST for name in rows
             if name.startswith('department_agent_factory-') and '.dist-info' in name))
    need(DIST + '/METADATA' in rows)


def verified_inputs(args):
    need(closure.PATH_FIX_SHA256 == FIX_SHA)
    before = {key: file_identity(getattr(args, key), system_tool=key == 'uv')[0]
              for key in ('wheel', 'base_wheel', 'manifest', 'uv')}
    source = closure.source(args)
    need(len(source) == 135)
    expected = closure.expected_payload(source, True)
    need({key for key in source if source[key] != expected[key]} == {closure.PATH_FIX_FILE})
    for wheel in (args.base_wheel, args.wheel):
        with zipfile.ZipFile(wheel) as archive:
            members = archive.infolist()
            need(len(members) <= 512 and sum(item.file_size for item in members) <= 64 * 1024**2)
            need(all(item.file_size <= 8 * 1024**2 and not item.flag_bits & 1 for item in members))
    closure.verify_repaired_wheel(args.base_wheel, args.wheel, source)
    need(all(file_identity(getattr(args, key), system_tool=key == 'uv')[0] == pin for key, pin in before.items()))
    return source, expected, before


def save(root, name, value):
    raw = encoded(value); need(len(raw) <= 16 * 1024**2)
    parent = copying.open_directory(str(root))
    fd = None
    try:
        info = os.fstat(parent); copying.owned(info, True)
        need(stat.S_IMODE(info.st_mode) == 0o700)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | copying.flags()[0], 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(fd)
        os.fsync(parent)
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)


def prepare(args):
    site = args.venv / 'lib/python3.12/site-packages'
    need(not args.evidence.is_relative_to(args.venv) and not args.venv.is_relative_to(args.evidence))
    evidence_fd = copying.open_directory(str(args.evidence))
    try:
        info = os.fstat(evidence_fd); copying.owned(info, True)
        need(stat.S_IMODE(info.st_mode) == 0o700 and not set(os.listdir(evidence_fd)) & {PLAN, 'factory-repair-checked.json', 'agent_factory', DIST})
    finally: os.close(evidence_fd)
    base, expected, pins = verified_inputs(args)
    old = snapshot(site); package_matches(old['rows'], base)
    versions = closure.versions(site)
    need(len(versions) == 95 and versions.get('department-agent-factory') == '0.2.0')
    versions_path = args.evidence / 'old-versions.json'
    if versions_path.exists():
        version_pin, version_raw = file_identity(versions_path, collect=True)
        need(version_pin['mode'] == 0o600 and json.loads(version_raw) == versions)
    else:
        save(args.evidence, 'old-versions.json', versions)
    # Backup ONLY the two changed namespaces, never recopy the complete venv.
    backups = {}
    for name in ('agent_factory', DIST):
        copying.copy_site(str(site / name), str(args.evidence / name))
        backups[name] = snapshot(args.evidence / name)
        expected_backup = {path[len(name)+1:]: row for path, row in old['rows'].items() if path.startswith(name + '/')}
        need({p: (v.get('sha256'), v.get('size')) for p, v in backups[name]['rows'].items() if v['kind'] == 'file'}
             == {p: (v.get('sha256'), v.get('size')) for p, v in expected_backup.items() if v['kind'] == 'file'})
    need(snapshot(site) == old and closure.versions(site) == versions)
    command = [str(args.uv), 'pip', 'install', '--offline', '--no-deps', '--reinstall-package',
        'department-agent-factory', '--link-mode', 'copy', '--python', str(args.venv / 'bin/python'), str(args.wheel)]
    plan = {'schema': 1, 'site': str(site), 'venv': str(args.venv),
        'arguments': {key: str(getattr(args, key)) for key in ('wheel', 'base_wheel', 'source', 'manifest', 'uv')},
        'inputPins': pins, 'before': old, 'nonFactory': non_factory(old['rows']), 'versions': versions,
        'expectedPackage': expected, 'backups': backups, 'installArgv': command,
        'executionVerified': False, 'installationPerformed': False}
    save(args.evidence, PLAN, plan)
    return {'schema': 1, 'status': 'PREPARED', 'executionVerified': False, 'installationPerformed': False}


def check(args):
    identity, raw = file_identity(args.evidence / PLAN, collect=True, maximum=16 * 1024**2)
    need(identity['mode'] == 0o600)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value); value[key] = item
        return value
    plan = json.loads(raw, object_pairs_hook=unique)
    need(plan['schema'] == 1 and plan['venv'] == str(args.venv)
         and plan['arguments'] == {key: str(getattr(args, key)) for key in ('wheel', 'base_wheel', 'source', 'manifest', 'uv')})
    _, expected, pins = verified_inputs(args)
    need(expected == plan['expectedPackage'] and pins == plan['inputPins'])
    need(set(plan['backups']) == {'agent_factory', DIST})
    for name, old in plan['backups'].items():
        need(name in {'agent_factory', DIST} and snapshot(args.evidence / name) == old)
    site = args.venv / 'lib/python3.12/site-packages'
    after = snapshot(site)
    need(after['rootIdentity'] == plan['before']['rootIdentity'])
    package_matches(after['rows'], expected)
    need(non_factory(after['rows']) == plan['nonFactory'] and closure.versions(site) == plan['versions'])
    save(args.evidence, 'factory-repair-checked.json', {'schema': 1, 'after': after,
        'planSha256': identity['sha256'], 'executionVerified': False, 'nonFactoryUnchanged': True})
    return {'schema': 1, 'status': 'CHECKED', 'executionVerified': False, 'nonFactoryUnchanged': True}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('FACTORY_REPAIR_REJECTED')


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('mode', choices=('prepare', 'check'))
        for key in ('venv', 'wheel', 'base-wheel', 'source', 'manifest', 'evidence', 'uv'):
            parser.add_argument('--' + key, required=True)
        parsed = parser.parse_args(argv)
        args = SimpleNamespace(**{key: Path(copying.absolute(value)) for key, value in vars(parsed).items() if key != 'mode'})
        value = prepare(args) if parsed.mode == 'prepare' else check(args)
        print(json.dumps(value, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        print('{"schema":1,"status":"REJECTED","errorCode":"FACTORY_REPAIR_REJECTED"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

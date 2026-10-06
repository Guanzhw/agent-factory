"""Pinned uv interpreter links for trusted cooperative research execution.

This is a filesystem identity contract, not authority, a launcher, or a sandbox.
No environment credentials, package imports or interpreter subprocesses are used.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
from typing import Any, cast

MAX_CONTRACT_BYTES = 2 * 1024 * 1024
COMPLETE_PROFILE = 'complete-venv-32768-v1'
MAX_COMPLETE_CONTRACT_BYTES = 16 * 1024 * 1024

def inventory_bounds(profile=None):
    if profile is None:
        return (4096, 8192, 4096, 32768, MAX_CONTRACT_BYTES)
    if type(profile) is str and profile == COMPLETE_PROFILE:
        return (32768, 16384, 16384, 65536, MAX_COMPLETE_CONTRACT_BYTES)
    raise ValueError('RESEARCH_INTERPRETER_INVALID')

MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_PACKAGE_BYTES = 8 * 1024**3
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 256 * 1024 * 1024
_ERROR = 'RESEARCH_INTERPRETER_INVALID'
_DIR = {'path', 'device', 'inode', 'mode', 'uid', 'gid'}
_FILE = _DIR | {'sizeBytes', 'sha256', 'mtimeNs', 'ctimeNs', 'nlink'}
_LINK = (_FILE - {'sha256'}) | {'target'}
_FILES = {'pyvenvCfg', 'pyprojectToml', 'uvLock', 'packageInventory'}
_TOP = {'schema', 'kind', 'executable', 'sha256', 'roots', 'directories', 'files', 'packageFiles', 'links', 'target', 'namespaces'}


def _require(value):
    if not value:
        raise ValueError(_ERROR)


def _path(value):
    _require(type(value) is str and 1 <= len(value) <= 4096 and '\x00' not in value
             and value.startswith('/') and value == str(PurePosixPath(value))
             and not value.startswith('//') and '..' not in PurePosixPath(value).parts)
    return value


def _sha(value):
    _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None)


def _inside(path, roots):
    return any(path == root or path.startswith(root.rstrip('/') + '/') for root in roots)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _keys(value, keys):
    _require(type(value) is dict and set(value) == keys)


def _pin(value, *, kind):
    _keys(value, _DIR if kind == 'directory' else _LINK if kind == 'link' else _FILE)
    _path(value['path'])
    for name in ('device', 'inode', 'mode', 'uid', 'gid'):
        _require(type(value[name]) is int and value[name] >= (1 if name in {'device', 'inode'} else 0))
    _require(value['mode'] <= 0o7777)
    if kind != 'directory':
        for name in ('sizeBytes', 'mtimeNs', 'ctimeNs', 'nlink'):
            _require(type(value[name]) is int and value[name] >= 0)
        _require(value['nlink'] == 1)
        if kind == 'link':
            _require(type(value['target']) is str and 0 < len(value['target']) <= 4096 and '\x00' not in value['target'])
        else:
            _sha(value['sha256'])
            _require(value['mode'] & 0o022 == 0)


def _link_target(path, literal):
    # Lexically collapsing '..' could skip an unverified symlink component.
    # This restricted contract supports no parent traversal, even if benign.
    _require('..' not in literal.split('/') and not literal.endswith('/') and not literal.endswith('/.'))
    raw = literal if literal.startswith('/') else str(PurePosixPath(path).parent) + '/' + literal
    parts = []
    for part in raw.split('/'):
        if part in {'', '.'}:
            continue
        parts.append(part)
    return _path('/' + '/'.join(parts))


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value):
    raise ValueError(_ERROR)


def validate_interpreter_contract(raw, executable, sha256):
    """Validate immutable canonical shape and scope only; never touch files."""
    try:
        _require(type(raw) is str and 0 < len(raw.encode('utf-8')) <= MAX_COMPLETE_CONTRACT_BYTES)
        _path(executable); _sha(sha256)
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
        _require(type(value) is dict and type(value.get('schema')) is int and value['schema'] in (1, 2))
        value = cast(dict[str, Any], value)
        complete = value['schema'] == 2
        _keys(value, _TOP | {'boundsProfile'} if complete else _TOP)
        profile = value['boundsProfile'] if complete else None
        _require(not complete or profile == COMPLETE_PROFILE)
        max_files, max_dirs, max_namespaces, max_entries, max_bytes = inventory_bounds(profile)
        _require(len(raw.encode('utf-8')) <= max_bytes)
        _require(_canonical(value) == raw
                 and value['kind'] == ('research-uv-interpreter-v2' if complete else 'research-uv-interpreter-v1')
                 and value['executable'] == executable and value['sha256'] == sha256)
        roots = value['roots']; _keys(roots, {'project', 'venv', 'interpreters'})
        _path(roots['project']); _path(roots['venv'])
        _require(type(roots['interpreters']) is list and 1 <= len(roots['interpreters']) <= 16)
        for root in roots['interpreters']:
            _path(root)
        _require(len(set(roots['interpreters'])) == len(roots['interpreters']))
        allowed = [roots['venv'], *roots['interpreters']]
        _require(_inside(executable, [roots['venv']]))
        directories = value['directories']
        _require(type(directories) is list and 1 <= len(directories) <= max_dirs)
        for pin in directories:
            _pin(pin, kind='directory')
        directories = cast(list[dict[str, Any]], directories)
        directory_paths = [pin['path'] for pin in directories]
        _require(directory_paths == sorted(set(directory_paths)))
        for root in [roots['project'], *allowed]:
            _require(root in directory_paths)
        namespaces = value['namespaces']
        _require(type(namespaces) is list and 1 <= len(namespaces) <= max_namespaces)
        namespace_paths = []; total_entries = 0
        for namespace in namespaces:
            _keys(namespace, {'path', 'entryCount', 'entriesSha256'})
            namespace = cast(dict[str, Any], namespace)
            _path(namespace['path']); _sha(namespace['entriesSha256'])
            _require(type(namespace['entryCount']) is int and 0 <= namespace['entryCount'] <= max_entries)
            total_entries += namespace['entryCount']; namespace_paths.append(namespace['path'])
        _require(total_entries <= max_entries and namespace_paths == [path for path in directory_paths if _inside(path, [roots['venv']])])
        _keys(value['files'], _FILES)
        _require(value['files']['pyvenvCfg']['path'] == roots['venv'].rstrip('/') + '/pyvenv.cfg'
                 and value['files']['pyprojectToml']['path'] == roots['project'].rstrip('/') + '/pyproject.toml'
                 and value['files']['uvLock']['path'] == roots['project'].rstrip('/') + '/uv.lock')
        _require(type(value['packageFiles']) is list and len(value['packageFiles']) <= max_files)
        package_files = cast(list[dict[str, Any]], value['packageFiles'])
        pins = [*value['files'].values(), *package_files]
        for pin in value['files'].values():
            _pin(pin, kind='file'); _require(0 < pin['sizeBytes'] <= MAX_FILE_BYTES)
        for pin in package_files:
            _pin(pin, kind='file'); _require(0 <= pin['sizeBytes'] <= MAX_PACKAGE_BYTES)
        _require(sum(pin['sizeBytes'] for pin in package_files) <= MAX_TOTAL_PACKAGE_BYTES)
        for pin in package_files:
            _require(_inside(pin['path'], [roots['project'], *allowed]))
        _require(len({pin['path'] for pin in pins}) == len(pins))
        links = value['links']; _require(type(links) is list and len(links) <= 8)
        current = executable; seen = set()
        for link in links:
            _pin(link, kind='link')
            link = cast(dict[str, Any], link)
            _require(link['path'] == current and current not in seen and _inside(current, allowed))
            seen.add(current); current = _link_target(current, link['target'])
            _require(_inside(current, allowed))
        target = value['target']; _pin(target, kind='file')
        _require(target['path'] == current and current not in seen and _inside(current, allowed)
                 and target['sha256'] == sha256 and 0 < target['sizeBytes'] <= MAX_EXECUTABLE_BYTES
                 and target['mode'] & 0o111 != 0)
        directory_scope = set(directory_paths)
        for pin in [*pins, *links, target]:
            parent = PurePosixPath(pin['path']).parent
            while True:
                _require(str(parent) in directory_scope)
                if str(parent) == '/':
                    break
                parent = parent.parent
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None


def _flags():
    directory = getattr(os, 'O_DIRECTORY', None)
    nofollow = getattr(os, 'O_NOFOLLOW', None)
    nonblock = getattr(os, 'O_NONBLOCK', None)
    _require(os.name == 'posix' and all(type(flag) is int and flag > 0 for flag in (directory, nofollow, nonblock)))
    return cast(tuple[int, int, int], (directory, nofollow, nonblock))


def _directory_pin(path, info):
    _require(stat.S_ISDIR(info.st_mode))
    return {'path': path, 'device': info.st_dev, 'inode': info.st_ino, 'mode': stat.S_IMODE(info.st_mode),
            'uid': info.st_uid, 'gid': info.st_gid}


def _file_stat(path, info):
    return {'path': path, 'device': info.st_dev, 'inode': info.st_ino, 'mode': stat.S_IMODE(info.st_mode),
            'uid': info.st_uid, 'gid': info.st_gid, 'sizeBytes': info.st_size, 'mtimeNs': info.st_mtime_ns,
            'ctimeNs': info.st_ctime_ns, 'nlink': info.st_nlink}


def _open_directory(path, directories, *, capture=False):
    directory, nofollow, _ = _flags()
    fd = os.open('/', os.O_RDONLY | directory | nofollow)
    try:
        current = '/'
        def check():
            pin = _directory_pin(current, os.fstat(fd))
            if capture:
                _require(current not in directories or directories[current] == pin)
                directories[current] = pin
            else:
                _require(directories.get(current) == pin)
        check()
        for part in PurePosixPath(path).parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd); fd = next_fd
            current = current.rstrip('/') + '/' + part
            check()
        return fd
    except BaseException:
        os.close(fd)
        raise


def _hash_fd(fd, size):
    os.lseek(fd, 0, os.SEEK_SET); digest = hashlib.sha256(); count = 0
    while True:
        chunk = os.read(fd, min(1024 * 1024, size - count + 1))
        if not chunk:
            break
        count += len(chunk); _require(count <= size); digest.update(chunk)
    _require(count == size)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def _read_pin(path, directories, maximum, *, capture=False):
    _, nofollow, nonblock = _flags()
    parent = _open_directory(str(PurePosixPath(path).parent), directories, capture=capture)
    fd = None
    try:
        fd = os.open(PurePosixPath(path).name, os.O_RDONLY | nofollow | nonblock, dir_fd=parent)
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) & 0o022 == 0
                 and info.st_uid in {0, getattr(os, 'getuid')()} and 0 <= info.st_size <= maximum)
        pin = _file_stat(path, info)
        sha = _hash_fd(fd, info.st_size)
        _require(pin == _file_stat(path, os.fstat(fd))
                 and pin == _file_stat(path, os.stat(PurePosixPath(path).name, dir_fd=parent, follow_symlinks=False)))
        return fd, {**pin, 'sha256': sha}
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise
    finally:
        os.close(parent)


def _read_link(path, directories, *, capture=False):
    parent = _open_directory(str(PurePosixPath(path).parent), directories, capture=capture)
    try:
        name = PurePosixPath(path).name
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISLNK(info.st_mode):
            return None
        pin = _file_stat(path, info)
        _require(info.st_nlink == 1 and info.st_uid in {0, getattr(os, 'getuid')()} and 0 < info.st_size <= 4096)
        literal = os.readlink(name, dir_fd=parent)
        _require(pin == _file_stat(path, os.stat(name, dir_fd=parent, follow_symlinks=False)))
        return {**pin, 'target': literal}
    finally:
        os.close(parent)



def _namespace_pin(path, directories, remaining):
    """Hash a bounded immediate namespace without opening or following entries."""
    fd = _open_directory(path, directories)
    try:
        before = os.fstat(fd)
        stamp = (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
        entries = []
        with os.scandir(fd) as iterator:
            for entry in iterator:
                _require(len(entries) < remaining)
                name = entry.name
                _require(type(name) is str and 0 < len(name) <= 255 and '/' not in name and '\x00' not in name)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                item = {'name': name, 'type': stat.S_IFMT(info.st_mode), 'device': info.st_dev,
                    'inode': info.st_ino, 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid,
                    'gid': info.st_gid, 'nlink': info.st_nlink, 'size': info.st_size,
                    'mtimeNs': info.st_mtime_ns, 'ctimeNs': info.st_ctime_ns}
                if stat.S_ISLNK(info.st_mode):
                    literal = os.readlink(name, dir_fd=fd)
                    _require(type(literal) is str and 0 < len(literal) <= 4096)
                    item['literal'] = literal
                # The entry itself must not change while its metadata is read.
                after_entry = os.stat(name, dir_fd=fd, follow_symlinks=False)
                _require((info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                          info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
                         (after_entry.st_dev, after_entry.st_ino, after_entry.st_mode, after_entry.st_uid,
                          after_entry.st_gid, after_entry.st_nlink, after_entry.st_size,
                          after_entry.st_mtime_ns, after_entry.st_ctime_ns))
                entries.append(item)
        # Recheck previously scanned entries too: editing a file's contents
        # changes its ctime but need not change the parent directory stamp.
        for item in entries:
            check = os.stat(item['name'], dir_fd=fd, follow_symlinks=False)
            actual = {'name': item['name'], 'type': stat.S_IFMT(check.st_mode), 'device': check.st_dev,
                'inode': check.st_ino, 'mode': stat.S_IMODE(check.st_mode), 'uid': check.st_uid,
                'gid': check.st_gid, 'nlink': check.st_nlink, 'size': check.st_size,
                'mtimeNs': check.st_mtime_ns, 'ctimeNs': check.st_ctime_ns}
            if stat.S_ISLNK(check.st_mode):
                actual['literal'] = os.readlink(item['name'], dir_fd=fd)
            _require(actual == item)
        after = os.fstat(fd)
        _require(stamp == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns))
        reopened = _open_directory(path, directories)
        try:
            current = os.fstat(reopened)
            _require(stamp == (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_ctime_ns))
        finally:
            os.close(reopened)
        return {'path': path, 'entryCount': len(entries),
            'entriesSha256': hashlib.sha256(_canonical(sorted(entries, key=lambda item: item['name'])).encode('ascii')).hexdigest()}
    finally:
        os.close(fd)


def _namespaces(venv, directories, profile=None):
    _, _, max_namespaces, max_entries, _ = inventory_bounds(profile)
    paths = sorted(path for path in directories if _inside(path, [venv]))
    _require(1 <= len(paths) <= max_namespaces)
    result = []; remaining = max_entries
    for path in paths:
        pin = _namespace_pin(path, directories, remaining)
        remaining -= pin['entryCount']; result.append(pin)
    return result

def _verify(value, *, held_fd=None):
    directories = {pin['path']: pin for pin in value['directories']}
    for pin in value['directories']:
        fd = _open_directory(pin['path'], directories); os.close(fd)
    for pin in [*value['files'].values(), *value['packageFiles']]:
        fd, actual = _read_pin(pin['path'], directories, pin['sizeBytes'])
        os.close(fd); _require(actual == pin)
    for link in value['links']:
        _require(_read_link(link['path'], directories) == link)
    target = value['target']
    fd, actual = _read_pin(target['path'], directories, MAX_EXECUTABLE_BYTES)
    try:
        _require(actual == target)
        if held_fd is not None:
            _require(type(held_fd) is int and held_fd >= 0 and stat.S_ISREG(os.fstat(held_fd).st_mode))
            _require(_file_stat(target['path'], os.fstat(held_fd)) == {k: v for k, v in target.items() if k != 'sha256'})
            _require(_hash_fd(held_fd, target['sizeBytes']) == target['sha256'])
            _require(_file_stat(target['path'], os.fstat(held_fd)) == {k: v for k, v in target.items() if k != 'sha256'})
        # Detect namespace/evidence changes occurring during the bounded scan.
        for pin in [*value['files'].values(), *value['packageFiles'], target]:
            parent = _open_directory(str(PurePosixPath(pin['path']).parent), directories)
            try:
                info = os.stat(PurePosixPath(pin['path']).name, dir_fd=parent, follow_symlinks=False)
                _require(stat.S_ISREG(info.st_mode) and _file_stat(pin['path'], info) == {k: v for k, v in pin.items() if k != 'sha256'})
            finally:
                os.close(parent)
        for link in value['links']:
            _require(_read_link(link['path'], directories) == link)
        _require(_namespaces(value['roots']['venv'], directories, value.get('boundsProfile')) == value['namespaces'])
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_interpreter(raw, executable, sha256):
    """Return a retained verified executable FD. Caller must close it."""
    try:
        return _verify(validate_interpreter_contract(raw, executable, sha256))
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError(_ERROR) from None


def recheck_interpreter(raw, executable, sha256, fd):
    """Recheck the held target and current chain/evidence without executing it."""
    try:
        fresh = _verify(validate_interpreter_contract(raw, executable, sha256), held_fd=fd)
        os.close(fresh)
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError(_ERROR) from None


def capture_interpreter_contract(*, executable, sha256, project_root, venv_root,
        approved_interpreter_roots, pyvenv_cfg, pyproject_toml, uv_lock, package_inventory, package_files=(), bounds_profile=None):
    """Operator-only read-only capture; does not authorize, import or launch."""
    try:
        max_files, _, _, _, _ = inventory_bounds(bounds_profile)
        executable = _path(str(executable)); _sha(sha256)
        project, venv = _path(str(project_root)), _path(str(venv_root))
        _require(type(approved_interpreter_roots) in {list, tuple} and 1 <= len(approved_interpreter_roots) <= 16)
        roots = [_path(str(root)) for root in approved_interpreter_roots]
        _require(type(package_files) in {list, tuple} and len(package_files) <= max_files)
        directories: dict[str, Any] = {}
        for root in [project, venv, *roots]:
            fd = _open_directory(root, directories, capture=True); os.close(fd)
        files = {}
        for key, path in [('pyvenvCfg', pyvenv_cfg), ('pyprojectToml', pyproject_toml), ('uvLock', uv_lock), ('packageInventory', package_inventory)]:
            fd, pin = _read_pin(_path(str(path)), directories, MAX_FILE_BYTES, capture=True)
            os.close(fd); files[key] = pin
        packages = []; total = 0
        for path in package_files:
            fd, pin = _read_pin(_path(str(path)), directories, min(MAX_PACKAGE_BYTES, MAX_TOTAL_PACKAGE_BYTES - total), capture=True)
            os.close(fd); packages.append(pin); total += pin['sizeBytes']
        links = []; current = executable; seen = set(); allowed = [venv, *roots]
        while True:
            _require(current not in seen and _inside(current, allowed)); seen.add(current)
            link = _read_link(current, directories, capture=True)
            if link is None:
                break
            _require(len(links) < 8); links.append(link)
            current = _link_target(current, link['target'])
        fd, target = _read_pin(current, directories, MAX_EXECUTABLE_BYTES, capture=True)
        os.close(fd)
        value = {'schema': 1, 'kind': 'research-uv-interpreter-v1', 'executable': executable, 'sha256': sha256,
            'roots': {'project': project, 'venv': venv, 'interpreters': roots},
            'directories': sorted(directories.values(), key=lambda pin: pin['path']), 'files': files,
            'packageFiles': packages, 'links': links, 'target': target,
            'namespaces': _namespaces(venv, directories, bounds_profile)}
        if bounds_profile is not None:
            value.update(schema=2, kind='research-uv-interpreter-v2', boundsProfile=bounds_profile)
        raw = _canonical(value)
        validated = validate_interpreter_contract(raw, executable, sha256)
        fd = _verify(validated); os.close(fd)
        return raw
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError(_ERROR) from None

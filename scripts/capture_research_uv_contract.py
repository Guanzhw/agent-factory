"""Capture an operator-supplied uv interpreter identity contract, without launch.

Stdout contains private local paths. This is neither admission nor evidence of
installation, model execution, GPU availability or scientific validity.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import PurePosixPath
import stat
import sys
from typing import Any, cast

MAX_CONFIG_BYTES = 2 * 1024 * 1024
_KEYS = {'executable', 'sha256', 'project_root', 'venv_root', 'approved_interpreter_roots',
         'pyvenv_cfg', 'pyproject_toml', 'uv_lock', 'package_inventory', 'package_files'}
_ERROR = 'RESEARCH_UV_CONTRACT_CAPTURE_FAILED'



def capture_interpreter_contract(**value):
    # Import only inside main's protected call path: a missing local install
    # must not print a traceback containing operator paths.
    from agent_factory.research_interpreter import capture_interpreter_contract as capture
    return capture(**value)


def contract_limit():
    from agent_factory.research_interpreter import MAX_CONTRACT_BYTES
    return MAX_CONTRACT_BYTES

def _require(value):
    if not value:
        raise ValueError(_ERROR)


def _absolute(value):
    _require(type(value) is str and 0 < len(value) <= 4096 and value.startswith('/')
             and not value.startswith('//') and '\x00' not in value and '..' not in value.split('/')
             and value == str(PurePosixPath(value)))
    return value


def _capabilities():
    flags = tuple(getattr(os, name, None) for name in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK'))
    _require(os.name == 'posix' and all(type(value) is int and value > 0 for value in flags))
    return cast(tuple[int, int, int], flags)


def _parent(path):
    directory, nofollow, _ = _capabilities()
    fd = os.open('/', os.O_RDONLY | directory | nofollow)
    try:
        for part in PurePosixPath(path).parent.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd); fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _constant(_):
    raise ValueError(_ERROR)


def _shape(value):
    _require(type(value) is dict and set(value) == _KEYS)
    value = cast(dict[str, Any], value)
    for name in _KEYS - {'sha256', 'approved_interpreter_roots', 'package_files'}:
        _absolute(value[name])
    _require(type(value['sha256']) is str and len(value['sha256']) == 64
             and all(char in '0123456789abcdef' for char in value['sha256']))
    for name, minimum, maximum in (('approved_interpreter_roots', 1, 16), ('package_files', 0, 4096)):
        _require(type(value[name]) is list and minimum <= len(value[name]) <= maximum)
        for item in value[name]:
            _absolute(item)
    return value


@contextmanager
def configuration(path):
    """Hold and recheck the original config throughout capture, without writes."""
    path = _absolute(path)
    _, nofollow, nonblock = _capabilities()
    parent = _parent(path)
    fd = None
    try:
        name = PurePosixPath(path).name
        fd = os.open(name, os.O_RDONLY | nofollow | nonblock, dir_fd=parent)
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= MAX_CONFIG_BYTES
                 and stat.S_IMODE(info.st_mode) & 0o022 == 0)
        before = _stamp(info); raw = bytearray()
        while True:
            chunk = os.read(fd, min(65536, MAX_CONFIG_BYTES - len(raw) + 1))
            if not chunk:
                break
            raw.extend(chunk); _require(len(raw) <= MAX_CONFIG_BYTES)
        _require(len(raw) == info.st_size and before == _stamp(os.fstat(fd))
                 and before == _stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)))
        value = _shape(json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_constant))
        yield value
        _require(before == _stamp(os.fstat(fd)))
        reopened = _parent(path)
        try:
            _require(before == _stamp(os.stat(name, dir_fd=reopened, follow_symlinks=False)))
        finally:
            os.close(reopened)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def main(argv=None):
    try:
        args = sys.argv[1:] if argv is None else argv
        _require(type(args) is list and len(args) == 2 and args[0] == '--config')
        maximum = contract_limit()
        with configuration(args[1]) as value:
            contract = capture_interpreter_contract(**value)
            _require(type(contract) is str and 0 < len(contract.encode('utf-8')) <= maximum)
        # No newline or progress output: preserve the helper's canonical bytes.
        sys.stdout.write(contract)
        return 0
    except (Exception, KeyboardInterrupt):
        sys.stderr.write(_ERROR + '\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

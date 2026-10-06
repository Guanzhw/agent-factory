"""Read-only fixed uv startup evidence. Never import or execute startup files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
import sys

MAX_BYTES = 65536
PROFILES = {
    'uv0117-virtualenv-startup-v1': ('0.11.7', '6cf30c56faf2a55228914dbbd17f8088ed371ebb08f5e7fa6fd931f913fcaf1d', 4342),
    'uv01219-virtualenv-startup-v1': ('0.12.19', 'cfb3db86aaa53bb62b5ff764970bec2d71c9228590a0ebec57f6ec926cc0bf1a', 5246),
}
PTH_SHA256 = '69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d'
FIELDS = {'uv', 'include-system-site-packages', 'version_info'}


def _require(value):
    if not value:
        raise ValueError('INVALID_FILE')


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_root(value, directory_flag, nofollow):
    _require(type(value) is str and 1 <= len(value) <= 4096 and value.startswith('/') and value == str(PurePosixPath(value))
             and '..' not in PurePosixPath(value).parts and not value.startswith('//') and '\x00' not in value)
    descriptor = os.open('/', os.O_RDONLY | directory_flag | nofollow)
    try:
        for part in PurePosixPath(value).parts[1:]:
            child = os.open(part, os.O_RDONLY | directory_flag | nofollow, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read(root, parts, flags):
    directory_flag, nofollow, nonblock = flags
    descriptor = os.dup(root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | directory_flag | nofollow, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_fd = os.open(parts[-1], os.O_RDONLY | nofollow | nonblock, dir_fd=descriptor)
        try:
            before = os.fstat(file_fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_BYTES)
            raw = bytearray()
            while len(raw) <= MAX_BYTES:
                block = os.read(file_fd, min(8192, MAX_BYTES + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            _require(len(raw) == before.st_size and _stamp(before) == _stamp(os.fstat(file_fd))
                     and _stamp(before) == _stamp(os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)))
            current = os.dup(root)
            try:
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | directory_flag | nofollow, dir_fd=current)
                    os.close(current)
                    current = child
                _require(_stamp(before) == _stamp(os.stat(parts[-1], dir_fd=current, follow_symlinks=False)))
            finally:
                os.close(current)
            return bytes(raw)
        finally:
            os.close(file_fd)
    finally:
        os.close(descriptor)


def parse_config(raw):
    result = {}
    seen = set()
    for line in raw.decode('utf-8').splitlines():
        if '=' not in line:
            continue
        name, value = (part.strip() for part in line.split('=', 1))
        normalized = name.casefold()
        _require(normalized not in seen)
        seen.add(normalized)
        if name not in FIELDS:
            continue
        _require(name not in result)
        pattern = r'(true|false)' if name == 'include-system-site-packages' else r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}'
        if name == 'version_info':
            pattern = r'[0-9]{1,3}\.[0-9]{1,3}(\.[0-9]{1,3})?'
        _require(re.fullmatch(pattern, value) is not None)
        result[name] = value
    return result


def probe(venv):
    result = {'schema': 1, 'evidenceKind': 'uv_startup_files_read_only', 'status': 'UNCONFIRMED',
              'factoryExecutionVerified': False, 'startupSafetyVerified': False, 'scientificConclusionVerified': False,
              'files': {}, 'configuration': {}, 'startupProfileMatches': {name: False for name in PROFILES}, 'uv0117ConfigMatches': False, 'uv01219ConfigMatches': False}
    flags = tuple(getattr(os, name, None) for name in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK'))
    if os.name != 'posix' or any(type(flag) is not int or flag <= 0 for flag in flags):
        result['status'] = 'PLATFORM_UNSUPPORTED'
        return result
    root = None
    try:
        root = _open_root(venv, flags[0], flags[1])
        root_pin = _stamp(os.fstat(root))[:3]
        site = ('lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages')
        raw_files = {}
        for name, parts in (('pyvenvCfg', ('pyvenv.cfg',)), ('virtualenvPy', (*site, '_virtualenv.py')),
                            ('virtualenvPth', (*site, '_virtualenv.pth'))):
            try:
                raw = _read(root, parts, flags)
                raw_files[name] = raw
                result['files'][name] = {'status': 'OBSERVED_REGULAR_FILE', 'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}
            except FileNotFoundError:
                result['files'][name] = {'status': 'MISSING'}
            except (OSError, ValueError):
                result['files'][name] = {'status': 'UNCONFIRMED'}
        current_root = _open_root(venv, flags[0], flags[1])
        try:
            _require(_stamp(os.fstat(current_root))[:3] == root_pin)
        finally:
            os.close(current_root)
        if 'pyvenvCfg' in raw_files:
            config = parse_config(raw_files['pyvenvCfg'])
            result['configuration'] = config
            result['uv0117ConfigMatches'] = config.get('uv') == '0.11.7' and config.get('include-system-site-packages') == 'false'
            result['uv01219ConfigMatches'] = config.get('uv') == '0.12.19' and config.get('include-system-site-packages') == 'false'
        result['status'] = 'OBSERVED' if len(raw_files) == 3 else 'INCOMPLETE'
        for name, (version, sha, size) in PROFILES.items():
            result['startupProfileMatches'][name] = (result['status'] == 'OBSERVED'
                and result['configuration'].get('uv') == version
                and result['configuration'].get('include-system-site-packages') == 'false'
                and result['files']['virtualenvPy']['sha256'] == sha and result['files']['virtualenvPy']['sizeBytes'] == size
                and result['files']['virtualenvPth']['sha256'] == PTH_SHA256 and result['files']['virtualenvPth']['sizeBytes'] == 18)
    except (OSError, ValueError, UnicodeError):
        result['status'] = 'UNCONFIRMED'
        result['configuration'] = {}
        result['uv0117ConfigMatches'] = result['uv01219ConfigMatches'] = False
    finally:
        if root is not None:
            os.close(root)
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('ARGUMENTS_INVALID')


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument('--venv', required=True)
    try:
        args = parser.parse_args()
    except ValueError:
        print(json.dumps({'schema': 1, 'status': 'ARGUMENTS_INVALID'}))
        return 2
    result = probe(args.venv)
    print(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(',', ':')))
    return 0 if result['status'] == 'OBSERVED' else 1


if __name__ == '__main__':
    raise SystemExit(main())

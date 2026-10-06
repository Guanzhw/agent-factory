"""Read-only current-process diagnostics, never a launch or scientific attestation.

Only fixed top-level package specs are inspected; package loaders are not run.
Python startup has already occurred before this script can report on it.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import machinery
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

PACKAGES = ('agent_factory', 'torch', 'tiktoken', 'pyarrow')
MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024


def _text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('PROBE_INPUT_INVALID')
    return value


def _absolute(value: str) -> Path:
    path = Path(_text(value))
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('PROBE_INPUT_INVALID')
    return path


def _argument(value: object) -> str:
    # A versioned guardian uses a trusted multiline -c prelude. Preserve it in
    # JSON only; unlike path fields, argv can legitimately contain newlines.
    if not isinstance(value, str) or len(value) > 4096 or '\x00' in value:
        raise ValueError('PROBE_INPUT_INVALID')
    return value


def _under(path: str, root: str) -> bool:
    try:
        return Path(path).is_absolute() and Path(path).is_relative_to(Path(root))
    except (ValueError, OSError):
        return False


def passive_file(path: Path) -> dict[str, Any]:
    """No symlink following, parsing, or writes; unsupported safe reads stay unknown."""
    result: dict[str, Any] = {'path': _text(str(path)), 'status': 'UNAVAILABLE'}
    try:
        before = path.lstat()
        result.update(device=before.st_dev, inode=before.st_ino, sizeBytes=before.st_size)
        if stat.S_ISLNK(before.st_mode):
            result.update(status='SYMLINK', linkTarget=_text(os.readlink(path)))
            return result
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            result['status'] = 'NOT_SINGLE_REGULAR_FILE'
            return result
        if not 0 <= before.st_size <= MAX_FILE_BYTES:
            result['status'] = 'SIZE_LIMIT'
            return result
        nofollow = getattr(os, 'O_NOFOLLOW', 0)
        nonblock = getattr(os, 'O_NONBLOCK', 0)
        if not nofollow or not nonblock:
            result['status'] = 'READ_IDENTITY_UNSUPPORTED'
            return result
        descriptor = os.open(path, os.O_RDONLY | nofollow | nonblock)
        try:
            opened = os.fstat(descriptor)
            def signature(s: os.stat_result) -> tuple[int, ...]:
                return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
            if not stat.S_ISREG(opened.st_mode) or signature(before) != signature(opened):
                return result
            digest = hashlib.sha256()
            count = 0
            while chunk := os.read(descriptor, 65536):
                count += len(chunk)
                if count > MAX_FILE_BYTES:
                    result['status'] = 'SIZE_LIMIT'
                    return result
                digest.update(chunk)
            if count != before.st_size or signature(os.fstat(descriptor)) != signature(before) or signature(path.lstat()) != signature(before):
                return result
            result.update(status='OBSERVED_REGULAR_FILE', sha256=digest.hexdigest())
        finally:
            os.close(descriptor)
    except (OSError, ValueError):
        pass
    return result


def package_specs(paths: list[str]) -> dict[str, Any]:
    """Use private FileFinders, never arbitrary meta_path/path hooks or imports.

    This intentionally does not emulate custom/zip importers or prove which code
    an already-customized interpreter would import. All filesystem candidates
    are retained so that a shadow package cannot be hidden by a later match.
    """
    result: dict[str, Any] = {}
    for name in PACKAGES:
        candidates = []
        for item in paths:
            if not item or not Path(item).is_absolute() or not Path(item).is_dir():
                continue
            finder = machinery.FileFinder(item,
                (machinery.ExtensionFileLoader, machinery.EXTENSION_SUFFIXES),
                (machinery.SourceFileLoader, machinery.SOURCE_SUFFIXES),
                (machinery.SourcelessFileLoader, machinery.BYTECODE_SUFFIXES))
            spec = finder.find_spec(name)
            if spec is not None:
                candidates.append({'origin': _text(spec.origin) if spec.origin else None,
                    'locations': [_text(p) for p in spec.submodule_search_locations or ()]})
        result[name] = {'candidates': candidates, 'importedByProbe': False}
    return result


def assess(runtime: dict[str, Any], packages: dict[str, Any], expected_venv: str | None) -> list[str]:
    issues = []
    if expected_venv is None:
        issues.append('EXPECTED_VENV_UNSPECIFIED')
    else:
        _absolute(expected_venv)
        if runtime['prefix'] != expected_venv or runtime['execPrefix'] != expected_venv:
            issues.append('PREFIX_MISMATCH')
        if not _under(runtime['executable'], expected_venv):
            issues.append('EXECUTABLE_OUTSIDE_EXPECTED_VENV')
    if runtime['flags']['no_user_site'] != 1:
        issues.append('USER_SITE_NOT_DISABLED')
    if runtime['flags']['dont_write_bytecode'] != 1:
        issues.append('BYTECODE_WRITES_NOT_DISABLED')
    if runtime['flags']['no_site'] != 1:
        issues.append('STARTUP_SITE_ALREADY_RAN')
    if any(not p or not Path(p).is_absolute() for p in runtime['sysPath']):
        issues.append('RELATIVE_IMPORT_PATH')
    roots = [runtime['basePrefix'], runtime['baseExecPrefix']]
    if expected_venv:
        roots.append(expected_venv)
    if any(p and not any(_under(p, root) for root in roots) for p in runtime['sysPath']):
        issues.append('IMPORT_PATH_OUTSIDE_EXPECTED_ROOTS')
    for name in PACKAGES:
        candidates = packages[name]['candidates']
        if not candidates:
            issues.append('PACKAGE_NOT_OBSERVED_' + name.upper())
        if len(candidates) > 1:
            issues.append('PACKAGE_SHADOW_' + name.upper())
        if expected_venv and any(not c['origin'] or not _under(c['origin'], expected_venv) for c in candidates):
            issues.append('PACKAGE_OUTSIDE_EXPECTED_VENV_' + name.upper())
    return issues


def observe(*, expected_venv: str | None = None, venv_config: str | None = None,
            project_lock: str | None = None) -> dict[str, Any]:
    if expected_venv is not None:
        _absolute(expected_venv)
    if len(sys.path) > 64:
        raise ValueError('PROBE_PATH_LIMIT')
    original_argv = getattr(sys, 'orig_argv', [])
    if not isinstance(original_argv, list) or len(original_argv) > 32:
        raise ValueError('PROBE_ARGV_LIMIT')
    original_argv = [_argument(item) for item in original_argv]
    base_executable = getattr(sys, '_base_executable', None)
    base_executable = _text(base_executable) if isinstance(base_executable, str) else None
    executed_binary_link = None
    if sys.platform == 'linux':
        try:
            executed_binary_link = _text(os.readlink('/proc/self/exe'))
        except (OSError, ValueError):
            pass
    paths = [_text(p) for p in sys.path]
    flags = {name: int(getattr(sys.flags, name)) for name in (
        'isolated', 'ignore_environment', 'no_user_site', 'no_site', 'dont_write_bytecode', 'safe_path')}
    runtime = {'platform': _text(sys.platform), 'implementation': _text(sys.implementation.name),
        'version': list(sys.version_info[:3]), 'executable': _text(sys.executable),
        'prefix': _text(sys.prefix), 'basePrefix': _text(sys.base_prefix),
        'execPrefix': _text(sys.exec_prefix), 'baseExecPrefix': _text(sys.base_exec_prefix),
        'sysPath': paths, 'flags': flags, 'origArgv': original_argv,
        'baseExecutable': base_executable, 'executedBinaryLink': executed_binary_link,
        'cachePrefix': _text(sys.pycache_prefix) if sys.pycache_prefix else None}
    packages = package_specs(paths)
    files = {name: passive_file(_absolute(value)) for name, value in (
        ('venvConfig', venv_config), ('projectLock', project_lock)) if value is not None}
    if sys.executable and Path(sys.executable).is_absolute():
        files['executable'] = passive_file(Path(sys.executable))
    return {'schema': 1, 'mode': 'read-only-current-process', 'runtime': runtime,
        'packages': packages, 'files': files, 'issues': assess(runtime, packages, expected_venv),
        'capabilities': {'packageImportVerified': False, 'startupSafetyVerified': False,
            'fdLaunchVerified': False, 'scientificExecutionVerified': False,
            'productionReady': False}, 'status': 'DIAGNOSTIC_ONLY'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-venv')
    parser.add_argument('--venv-config')
    parser.add_argument('--project-lock')
    arguments = parser.parse_args(argv)
    try:
        report = observe(expected_venv=arguments.expected_venv,
            venv_config=arguments.venv_config, project_lock=arguments.project_lock)
        output = json.dumps(report, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        if len(output.encode()) > MAX_OUTPUT_BYTES:
            raise ValueError('PROBE_OUTPUT_LIMIT')
        print(output)
        return 0
    except (OSError, ValueError, TypeError):
        print('{"schema":1,"status":"UNAVAILABLE","error":"PROBE_OBSERVATION_FAILED"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

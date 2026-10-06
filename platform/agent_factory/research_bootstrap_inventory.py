"""Read-only complete private inventory, never package import or execution proof.

The caller writes returned bytes to private artifacts and independently captures
and admits the original interpreter chain. Paths stay in these private results.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import cast

from .research_environment_observer import _open, _stamp, _tree, UV_STARTUP_PROFILES

PROFILE = 'complete-venv-32768-v1'
MAX_FILES = 32768
MAX_ENTRIES = 65536
MAX_FILE_BYTES = 1024**3
MAX_TOTAL_BYTES = 8 * 1024**3


def _require(value):
    if not value:
        raise ValueError('RESEARCH_BOOTSTRAP_INVENTORY_INVALID')


def _absolute(value):
    path = Path(value)
    _require(path.is_absolute() and '..' not in path.parts)
    return path


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _hash_file(path, observations, *, maximum=MAX_FILE_BYTES, collect=False):
    fd = _open(path)
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and not before.st_mode & 0o022 and 0 <= before.st_size <= maximum)
        hasher, pieces, count = hashlib.sha256(), [], 0
        while True:
            block = os.read(fd, min(1024**2, maximum - count + 1))
            if not block:
                break
            count += len(block)
            _require(count <= maximum)
            hasher.update(block)
            if collect:
                pieces.append(block)
        _require(count == before.st_size and _stamp(os.fstat(fd)) == _stamp(before))
        observations.append((str(path), False, _stamp(before)))
        return {'sha256': hasher.hexdigest(), 'sizeBytes': count}, b''.join(pieces)
    finally:
        os.close(fd)


def _version(raw, module):
    _require(len(raw) <= 1024**2)
    message = BytesParser().parsebytes(raw, headersonly=True)
    _require(len(message.get_all('Name', [])) == 1 and len(message.get_all('Version', [])) == 1)
    name, version = message['Name'], message['Version']
    _require(type(name) is str and re.sub('[-_.]+', '-', name).lower() == module
             and type(version) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}', version))
    return version


def _build_inventory(*, project_root, venv_root, interpreter_target, interpreter_sha256,
                    approved_interpreter_roots, inventory_path, package_versions=None,
                    startup_profile='uv0117-virtualenv-startup-v1'):
    """Return canonical inventory/kernel bytes and full-site capture kwargs.

    No files are written. Supplied versions, when present, must match static
    METADATA; torch's public version is 2.9.1 and its CUDA literal is 12.8.
    The logical interpreter symlink is validated later by the original capture
    API, not followed or implicitly authorized by this inventory builder.
    """
    _require(startup_profile in UV_STARTUP_PROFILES)
    project, venv, target, output = map(_absolute, (project_root, venv_root, interpreter_target, inventory_path))
    roots = tuple(_absolute(root) for root in approved_interpreter_roots)
    _require(bool(roots) and any(target.is_relative_to(root) for root in roots))
    site = venv / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    _require(not output.is_relative_to(site))
    _require(package_versions is None or type(package_versions) is dict
             and set(package_versions) <= {'torch', 'tiktoken', 'pyarrow'})
    observations = []
    output_fd = _open(output.parent, directory=True)
    try:
        output_info = os.fstat(output_fd)
        _require(not output_info.st_mode & 0o022)
        try:
            os.stat(output.name, dir_fd=output_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _require(False)  # Caller must exclusively create a new private artifact.
        output_parent_identity = {'device': output_info.st_dev, 'inode': output_info.st_ino}
        observations.append((str(output.parent), True, _stamp(output_info)))
    finally:
        os.close(output_fd)
    project_fd = _open(project, directory=True)
    try:
        info = os.fstat(project_fd)
        _require(not info.st_mode & 0o022)
        project_identity = {'device': info.st_dev, 'inode': info.st_ino}
        observations.append((str(project), True, _stamp(info)))
    finally:
        os.close(project_fd)
    python_pin, _ = _hash_file(target, observations, maximum=256 * 1024**2)
    _require(python_pin['sizeBytes'] > 0 and python_pin['sha256'] == interpreter_sha256)
    cfg_pin, cfg_raw = _hash_file(venv / 'pyvenv.cfg', observations, maximum=65536, collect=True)
    cfg = {}
    for line in cfg_raw.decode('utf-8').splitlines():
        if '=' in line:
            key, value = (part.strip() for part in line.split('=', 1))
            key = key.casefold()
            _require(key not in cfg)
            cfg[key] = value
    startup_version, startup_files = UV_STARTUP_PROFILES[startup_profile]
    _require(cfg.get('uv') == startup_version and cfg.get('include-system-site-packages', '').casefold() == 'false')
    project_pins = {}
    for name, field in (('pyproject.toml', 'pyprojectToml'), ('uv.lock', 'uvLock')):
        project_pins[field], _ = _hash_file(project / name, observations, maximum=8 * 1024**2)
    paths = _tree(site, observations, max_files=MAX_FILES, max_entries=MAX_ENTRIES)
    _require(bool(paths))
    pins, collected, total = {}, {}, 0
    metadata = {name for name in paths if '/' in name and name.endswith('.dist-info/METADATA')
                and name.count('/') == 1 and any(name.lower().startswith(module + '-') for module in ('torch', 'tiktoken', 'pyarrow'))}
    for name in sorted(paths):
        collect = name in metadata or name == 'torch/version.py'
        maximum = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total, 1024**2 if collect else MAX_FILE_BYTES)
        pin, raw = _hash_file(site / name, observations, maximum=maximum, collect=collect)
        pins[name] = pin
        total += pin['sizeBytes']
        _require(total <= MAX_TOTAL_BYTES)
        if collect:
            collected[name] = raw
    for name, pin in startup_files.items():
        _require(pins.get(name) == pin)
    packages = []
    for module in ('torch', 'tiktoken', 'pyarrow'):
        candidates = [name for name in metadata if name.lower().startswith(module + '-')]
        _require(len(candidates) == 1)
        declared = _version(collected[candidates[0]], module)
        _require(package_versions is None or module not in package_versions or package_versions[module] == declared)
        version = declared.split('+')[0] if module == 'torch' else declared
        _require(module != 'torch' or version == '2.9.1' and declared in {'2.9.1', '2.9.1+cu128'})
        rows = [{'path': name[len(module)+1:], **pin} for name, pin in pins.items() if name.startswith(module + '/')]
        _require(any(row['path'] == '__init__.py' for row in rows))
        packages.append({'module': module, 'version': version, 'root': str(site / module), 'files': rows})
    literals = {}
    for node in ast.parse(collected.get('torch/version.py', b'')).body:
        name = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(name, ast.Name) and name.id in {'__version__', 'cuda'}:
            _require(name.id not in literals)
            literals[name.id] = ast.literal_eval(cast(ast.AST, cast(ast.Assign | ast.AnnAssign, node).value))
    _require(literals.get('__version__') in {'2.9.1', '2.9.1+cu128'} and literals.get('cuda') == '12.8')
    adapter = pins.get('agent_factory/research_torch_runtime.py')
    _require(adapter is not None)
    assert adapter is not None
    inventory = {'schema': 3, 'boundsProfile': PROFILE, 'interpreterMode': 'research-uv-interpreter-v2',
        'python': {'path': str(venv / 'bin' / 'python'), **python_pin},
        'venv': {'root': str(venv), 'sitePackages': str(site), 'pyvenvCfg': cfg_pin},
        'packages': packages, 'siteFiles': [{'path': name, **pin} for name, pin in pins.items()],
        'project': {'root': str(project), 'rootIdentity': project_identity, **project_pins},
        'startupProfile': startup_profile, 'startupFiles': deepcopy(startup_files)}
    kernel = {'schema': 1, 'backend': 'pytorch-sdpa', 'torchVersion': '2.9.1', 'cudaVersion': '12.8',
        'torchFiles': [{'path': name, **pins['torch/' + name]} for name in ('__init__.py', 'version.py')],
        'adapterSha256': adapter['sha256']}
    # Reopen every observed path, then rescan namespaces. Hashing an early file
    # does not permit a later same-name replacement or added startup file.
    _require(_tree(site, max_files=MAX_FILES, max_entries=MAX_ENTRIES) == paths)
    for path, directory, stamp in observations:
        fd = _open(path, directory=directory)
        try:
            _require(_stamp(os.fstat(fd)) == stamp)
        finally:
            os.close(fd)
    capture = {'executable': str(venv / 'bin' / 'python'), 'sha256': interpreter_sha256,
        'project_root': project, 'venv_root': venv, 'approved_interpreter_roots': list(roots),
        'pyvenv_cfg': venv / 'pyvenv.cfg', 'pyproject_toml': project / 'pyproject.toml',
        'uv_lock': project / 'uv.lock', 'package_inventory': output,
        'package_files': [site / name for name in sorted(paths)], 'bounds_profile': PROFILE}
    return {'inventory': inventory, 'inventoryBytes': _canonical(inventory),
            'kernel': kernel, 'kernelBytes': _canonical(kernel), 'captureKwargs': capture,
            'outputParentIdentity': output_parent_identity}


def build_inventory(*, project_root, venv_root, interpreter_target, interpreter_sha256,
                    approved_interpreter_roots, inventory_path, package_versions=None,
                    startup_profile='uv0117-virtualenv-startup-v1'):
    """Build private static evidence only; errors contain no paths or raw input."""
    try:
        return _build_inventory(project_root=project_root, venv_root=venv_root,
            interpreter_target=interpreter_target, interpreter_sha256=interpreter_sha256,
            approved_interpreter_roots=approved_interpreter_roots, inventory_path=inventory_path,
            package_versions=package_versions, startup_profile=startup_profile)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, UnicodeError, OverflowError, RecursionError):
        raise ValueError('RESEARCH_BOOTSTRAP_INVENTORY_INVALID') from None

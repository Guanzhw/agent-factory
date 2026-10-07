"""Bounded read-only static environment observer; never imports ML or runs Python.

VERIFIED means supplied file inventory bytes, selected regular venv interpreter,
closed package trees and restricted startup locations matched. It does NOT prove
actual imports, dependency completeness, GPU compatibility or numerical results.
Only packages listed in the inventory are attested (at least torch/tiktoken/pyarrow).
Base Python stdlib/loader and host remain trusted operator prerequisites. Symlink
interpreters require the explicit schema2 uv chain contract. Arbitrary executable
.pth and sitecustomize remain unsupported; only the reviewed exact uv startup
profile is admitted. Static identity does not prove CPython venv discovery.
Bounds: legacy profiles admit 4096 inventoried files; the explicit complete
profile admits 32768 files and 65536 tree entries. Both retain 1 GiB/file and
8 GiB total bounds. Identical repeated observations share one bounded record;
changed identities are rejected, and every unique record is rechecked. Legacy
observations remain capped at 16384; complete observations at 65536 plus 16
fixed external document/project/cache/stdlib records.
Sample-set identity covers ordered shard pins/split, not consumed token order or
record-level disjointness; the driver separately verifies actual dataset bytes.
"""
from __future__ import annotations

import ast
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, cast

from .research_staging import InputPin
from .store import digest
from .research_manifest import validate_manifest

UV_STARTUP_PROFILE = 'uv01219-virtualenv-startup-v1'
UV_STARTUP_FILES = {
    '_virtualenv.py': {'sha256': 'cfb3db86aaa53bb62b5ff764970bec2d71c9228590a0ebec57f6ec926cc0bf1a', 'sizeBytes': 5246},
    '_virtualenv.pth': {'sha256': '69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d', 'sizeBytes': 18},
}

# Each profile is reviewed source identity, not proof of the installer binary.
# Keep the original aliases above for existing inventory builders.
UV_STARTUP_PROFILES = {
    UV_STARTUP_PROFILE: ('0.12.19', UV_STARTUP_FILES),
    'uv0117-virtualenv-startup-v1': ('0.11.7', {
        '_virtualenv.py': {'sha256': '6cf30c56faf2a55228914dbbd17f8088ed371ebb08f5e7fa6fd931f913fcaf1d', 'sizeBytes': 4342},
        '_virtualenv.pth': {'sha256': '69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d', 'sizeBytes': 18},
    }),
}

SETUPTOOLS_STDLIB_PROFILE = 'uv0117-setuptools82-stdlib-v1'
UV_STARTUP_PROFILES[SETUPTOOLS_STDLIB_PROFILE] = ('0.11.7', {
    **UV_STARTUP_PROFILES['uv0117-virtualenv-startup-v1'][1],
    'distutils-precedence.pth': {'sha256': '2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224',
                                'sizeBytes': 151},
})

SETUPTOOLS_LOCAL_PROFILE = 'uv0117-setuptools82-local-v1'
UV_STARTUP_PROFILES[SETUPTOOLS_LOCAL_PROFILE] = UV_STARTUP_PROFILES[SETUPTOOLS_STDLIB_PROFILE]

MAX_FILES = 4096
MAX_FILE_BYTES = 1024**3
MAX_TOTAL_BYTES = 8 * 1024**3
_REQUEST = {'environment', 'runtimeKernel', 'sampleSetSha256', 'configurationFingerprint',
            'launchSpec', 'trustedRuntimePackage', 'trustedRuntimeFiles', 'runtimeConfig', 'environmentPins'}


def _require(value):
    if not value:
        raise ValueError('ENVIRONMENT_STATIC_IDENTITY_UNVERIFIED')


class _Observations:
    """Bounded unique observations; repeat reads may never erase earlier drift."""
    def __init__(self, maximum):
        _require(type(maximum) is int and maximum > 0)
        self.maximum = maximum
        self._items = {}

    def append(self, observation):
        path, directory, observed_stamp = observation
        prior = self._items.get(path)
        current = (directory, observed_stamp)
        if prior is not None:
            _require(prior == current)
        else:
            _require(len(self._items) < self.maximum)
            self._items[path] = current

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        for path, (directory, observed_stamp) in self._items.items():
            yield path, directory, observed_stamp


def _keys(value, expected):
    _require(type(value) is dict and set(value) == set(expected.split()))


def _unique(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _json(raw) -> Any:
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: _require(False))


def _absolute(path):
    _require(type(path) is str and Path(path).is_absolute() and '..' not in Path(path).parts)
    return Path(path)


def _open(path, *, directory=False):
    path = _absolute(str(path))
    nofollow, directory_flag, nonblock = (getattr(os, key, None) for key in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'))
    _require(all(type(flag) is int and flag > 0 for flag in (nofollow, directory_flag, nonblock)))
    nofollow, directory_flag, nonblock = cast(tuple[int, int, int], (nofollow, directory_flag, nonblock))
    fd = os.open(path.anchor, os.O_RDONLY | directory_flag | nofollow)
    try:
        for index, part in enumerate(path.parts[1:]):
            flags = os.O_RDONLY | nofollow | nonblock
            if directory or index < len(path.parts) - 2:
                flags |= directory_flag
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_nlink)


def _read(path, pin, *, collect=False, observations=None, collect_limit=1024**2) -> Any:
    _keys(pin, 'sha256 sizeBytes')
    _require(type(pin['sha256']) is str and re.fullmatch('[a-f0-9]{64}', pin['sha256']) is not None
             and type(pin['sizeBytes']) is int and (1 if collect else 0) <= pin['sizeBytes'] <= (collect_limit if collect else MAX_FILE_BYTES))
    fd = _open(path)
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == pin['sizeBytes']
                 and not before.st_mode & 0o022)
        hasher, pieces, remaining = hashlib.sha256(), [], pin['sizeBytes']
        while remaining:
            block = os.read(fd, min(remaining, 1024**2))
            _require(bool(block))
            hasher.update(block)
            if collect:
                pieces.append(block)
            remaining -= len(block)
        _require(os.read(fd, 1) == b'' and hasher.hexdigest() == pin['sha256'] and _stamp(os.fstat(fd)) == _stamp(before))
        check = _open(path)
        try:
            _require(_stamp(os.fstat(check)) == _stamp(before))
        finally:
            os.close(check)
        if observations is not None:
            observations.append((str(path), False, _stamp(before)))
        return b''.join(pieces) if collect else hasher.hexdigest()
    finally:
        os.close(fd)


def _relative(path):
    # Package data uses ordinary literal names (including spaces/parentheses).
    # Validate canonical POSIX components, not Python/module identifiers. Never
    # strip, decode or normalize a name; descriptor walks still reject symlinks.
    _require(type(path) is str and 0 < len(path) <= 512 and path.isprintable()
             and '\\' not in path and ':' not in path
             and all(part not in {'', '.', '..'} for part in path.split('/')))
    return path


def _tree(root, observations=None, *, max_files=MAX_FILES, max_entries=8192):
    found = set()
    entries = 0
    def walk(path, prefix='', depth=0):
        nonlocal entries
        _require(depth <= 20)
        fd = _open(path, directory=True)
        try:
            before = os.fstat(fd)
            _require(not before.st_mode & 0o022)
            for name in sorted(os.listdir(fd)):
                entries += 1
                _require(entries <= max_entries)
                relative = prefix + name
                _relative(relative)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    walk(Path(path) / name, relative + '/', depth + 1)
                else:
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
                    found.add(relative)
                    _require(len(found) <= max_files)
            _require(_stamp(before) == _stamp(os.fstat(fd)))
            if observations is not None:
                observations.append((str(path), True, _stamp(before)))
        finally:
            os.close(fd)
    walk(root)
    return found


def _startup(root, observations=None, *, startup_files=None):
    if startup_files is not None:
        for name, pin in startup_files.items():
            _read(Path(root) / name, pin, observations=observations)
    fd = _open(root, directory=True)
    try:
        directory_before = os.fstat(fd)
        for name in os.listdir(fd):
            _require(not any(name == stem or name.startswith(stem + '.')
                             for stem in ('sitecustomize', 'usercustomize')))
            if startup_files is not None and (name == '_virtualenv' or name.startswith('_virtualenv.')):
                _require(name in startup_files)
            if name.endswith('.pth'):
                if startup_files is not None and name in startup_files:
                    continue
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                _require(stat.S_ISREG(info.st_mode) and info.st_size <= 65536)
                child = _open(Path(root) / name)
                try:
                    before = os.fstat(child)
                    _require(_stamp(before) == _stamp(info))
                    raw = os.read(child, 65537)
                    _require(_stamp(os.fstat(child)) == _stamp(before)
                             and _stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) == _stamp(before))
                    _require(len(raw) <= 65536 and all(not line.strip() or line.lstrip().startswith(b'#') for line in raw.splitlines()))
                    if observations is not None:
                        observations.append((str(Path(root) / name), False, _stamp(before)))
                finally:
                    os.close(child)
        current = _open(root, directory=True)
        try:
            _require(_stamp(directory_before) == _stamp(os.fstat(fd)) == _stamp(os.fstat(current)))
            if observations is not None:
                observations.append((str(root), True, _stamp(directory_before)))
        finally:
            os.close(current)
    finally:
        os.close(fd)


def _module_namespace(root, sources, observations):
    """Reject source-shadowing packages/extensions and legacy adjacent bytecode."""
    fd = _open(root, directory=True)
    try:
        before = os.fstat(fd)
        for name in os.listdir(fd):
            for source in sources:
                stem = source[:-3]
                if name == stem or name.startswith(stem + '.'):
                    _require(name == source)
        _require(_stamp(os.fstat(fd)) == _stamp(before))
        observations.append((str(root), True, _stamp(before)))
    finally:
        os.close(fd)


def _cache_prefix(spec, observations):
    argv = spec['argv']
    _require(type(argv) in (list, tuple) and len(argv) == 4 and argv[0] == '-B'
             and argv[2] == '--config')
    pairs = spec['environment']
    _require(type(pairs) in (list, tuple))
    environment = dict(pairs)
    _require(len(environment) == len(pairs))
    root = _absolute(spec['working_directory'])
    _require(environment.get('PYTHONPYCACHEPREFIX') == str(root))
    fd = _open(root, directory=True)
    try:
        before = os.fstat(fd)
        _require(not before.st_mode & 0o022)
        # The driver separately pins the exact sealed file set. Empty prelaunch
        # roots are allowed, but no absolute-path cache subtree may exist.
        for name in os.listdir(fd):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
        _require(_stamp(os.fstat(fd)) == _stamp(before))
        observations.append((str(root), True, _stamp(before)))
    finally:
        os.close(fd)


def _uv_interpreter(request, inventory, inventory_pin, observations, startup_files):
    from .research_interpreter import open_interpreter, recheck_interpreter, validate_interpreter_contract
    spec = request['launchSpec']
    raw = spec['interpreter_contract']
    value = validate_interpreter_contract(raw, spec['executable'], spec['sha256'])
    _require(value.get('boundsProfile') == inventory.get('boundsProfile'))
    if inventory.get('startupProfile') == SETUPTOOLS_LOCAL_PROFILE:
        # This profile's stdlib hook check belongs to this exact interpreter,
        # not an unrelated controller Python installation.
        _require(value['target']['path'] == str(Path(sys.executable).resolve(strict=True)))
    project = inventory['project']
    _keys(project, 'root rootIdentity pyprojectToml uvLock')
    _keys(project['rootIdentity'], 'device inode')
    _require(value['roots']['project'] == project['root']
             and value['roots']['venv'] == inventory['venv']['root']
             and value['target']['sizeBytes'] == inventory['python']['sizeBytes'])
    fd = _open(project['root'], directory=True)
    try:
        info = os.fstat(fd)
        _require(project['rootIdentity'] == {'device': info.st_dev, 'inode': info.st_ino})
        observations.append((project['root'], True, _stamp(info)))
    finally:
        os.close(fd)
    expected = {
        'pyvenvCfg': (str(Path(inventory['venv']['root']) / 'pyvenv.cfg'), inventory['venv']['pyvenvCfg']),
        'pyprojectToml': (str(Path(project['root']) / 'pyproject.toml'), project['pyprojectToml']),
        'uvLock': (str(Path(project['root']) / 'uv.lock'), project['uvLock']),
        'packageInventory': (str(Path(inventory_pin.root) / inventory_pin.file.basename),
                             {'sha256': inventory_pin.file.sha256, 'sizeBytes': inventory_pin.file.size_bytes}),
    }
    for key, (path, pin) in expected.items():
        _keys(pin, 'sha256 sizeBytes')
        actual = value['files'][key]
        _require(actual['path'] == path and {name: actual[name] for name in ('sha256', 'sizeBytes')} == pin)
    locks = [pin for pin in request['environmentPins'] if pin['label'] == 'environment-lockfile']
    _require(len(locks) == 1)
    lock = locks[0]
    _require(lock['kind'] == 'environment' and lock['root'] == project['root']
             and lock['root_identity'] == project['rootIdentity']
             and lock['file'] == {'basename': 'uv.lock', 'sha256': project['uvLock']['sha256'], 'size_bytes': project['uvLock']['sizeBytes']}
             and project['uvLock']['sha256'] == request['environment']['lockfileSha256'])
    coverage = {}
    def include(path, pin):
        normalized = {key: pin[key] for key in ('sha256', 'sizeBytes')}
        _require(path not in coverage or coverage[path] == normalized)
        coverage[path] = normalized
    if inventory.get('schema') == 3:
        for row in inventory['siteFiles']:
            include(str(Path(inventory['venv']['sitePackages']) / _relative(row['path'])), row)
    for package in inventory['packages']:
        for row in package['files']:
            include(str(Path(package['root']) / _relative(row['path'])), row)
    for row in request['trustedRuntimeFiles']:
        _require(type(row['basename']) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.py', row['basename']) is not None)
        include(str(Path(request['trustedRuntimePackage']) / row['basename']), {'sha256': row['sha256'], 'sizeBytes': row['size_bytes']})
    for name, pin in startup_files.items():
        include(str(Path(inventory['venv']['sitePackages']) / name), pin)
    actual_coverage = {pin['path']: {key: pin[key] for key in ('sha256', 'sizeBytes')} for pin in value['packageFiles']}
    _require(actual_coverage == coverage and len(value['packageFiles']) == len(coverage))
    fd = open_interpreter(raw, spec['executable'], spec['sha256'])
    try:
        recheck_interpreter(raw, spec['executable'], spec['sha256'], fd)
    finally:
        os.close(fd)


class ResearchEnvironmentObserver:
    def __init__(self, inventory_pin: InputPin, kernel_pin: InputPin, *, bounds_profile=None):
        from .research_interpreter import inventory_bounds
        self._max_files, _, _, self._max_entries, _ = inventory_bounds(bounds_profile)
        self._bounds_profile = bounds_profile
        # Complete site entries already include every file and directory. Allow
        # the fixed external document/project/cache/stdlib observations too.
        self._max_observations = 16384 if bounds_profile is None else self._max_entries + 16
        self._document_limit = 8 * 1024**2 if bounds_profile is not None else 1024**2
        _require(type(inventory_pin) is InputPin and type(kernel_pin) is InputPin
                 and inventory_pin.kind == kernel_pin.kind == 'environment'
                 and inventory_pin.label == 'environment-inventory' and kernel_pin.label == 'environment-kernel')
        self._inventory, self._kernel = inventory_pin, kernel_pin
        self.configuration_fingerprint = digest({'policy': 'static-regular-venv-inventory-v1',
            'inventory': asdict(inventory_pin), 'kernel': asdict(kernel_pin),
            'maxFiles': self._max_files, 'maxFileBytes': MAX_FILE_BYTES, 'maxTotalBytes': MAX_TOTAL_BYTES,
            **({'boundsProfile': bounds_profile} if bounds_profile is not None else {})})

    def _document(self, pin, observations):
        fd = _open(pin.root, directory=True)
        try:
            info = os.fstat(fd)
            _require((info.st_dev, info.st_ino) == (pin.root_identity.device, pin.root_identity.inode))
            observations.append((pin.root, True, _stamp(info)))
        finally:
            os.close(fd)
        return _json(_read(Path(pin.root) / pin.file.basename,
            {'sha256': pin.file.sha256, 'sizeBytes': pin.file.size_bytes}, collect=True, observations=observations, collect_limit=self._document_limit))

    def __call__(self, request):
        request_hash = digest(request)
        try:
            observation = self._observe(request)
            return {'schema': 1, 'status': 'VERIFIED', 'requestSha256': request_hash, 'observationSha256': digest(observation)}
        except (ValueError, TypeError, KeyError, OSError, UnicodeError, SyntaxError, OverflowError, RecursionError):
            return {'schema': 1, 'status': 'UNKNOWN', 'requestSha256': request_hash,
                'observationSha256': digest({'scope': 'static-environment', 'status': 'UNKNOWN'})}

    def _observe(self, request: Any):
        _require(type(request) is dict and set(request) == _REQUEST
                 and request['configurationFingerprint'] == self.configuration_fingerprint)
        request = cast(dict[str, Any], request)
        for pin, key in ((self._inventory, 'installedInventory'), (self._kernel, 'runtimeKernel')):
            _require(request['environment'][key] == {'sha256': pin.file.sha256, 'sizeBytes': pin.file.size_bytes}
                     and asdict(pin) in request['environmentPins'])
        _require(request['runtimeKernel'] == request['environment']['runtimeKernel'])
        observations = _Observations(self._max_observations)
        _cache_prefix(request['launchSpec'], observations)
        inventory, kernel = self._document(self._inventory, observations), self._document(self._kernel, observations)
        _require(type(inventory) is dict and type(inventory.get('schema')) is int and inventory['schema'] in (1, 2, 3))
        uv_mode = inventory['schema'] in (2, 3)
        complete = inventory['schema'] == 3
        _require(complete == (self._bounds_profile is not None))
        if complete:
            _require(inventory.get('boundsProfile') == self._bounds_profile)
        _keys(inventory, ('schema python venv packages interpreterMode project startupProfile startupFiles' + (' boundsProfile siteFiles' if complete else '')) if uv_mode else 'schema python venv packages')
        python, venv = inventory['python'], inventory['venv']
        _keys(python, 'path sha256 sizeBytes')
        _keys(venv, 'root sitePackages pyvenvCfg')
        root, site = _absolute(venv['root']), _absolute(venv['sitePackages'])
        _require(site.parent.name == f'python{sys.version_info.major}.{sys.version_info.minor}' and site.parent.parent == root / 'lib'
                 and site.name == 'site-packages' and Path(request['trustedRuntimePackage']) == site / 'agent_factory'
                 and Path(python['path']) == root / 'bin' / 'python'
                 and request['launchSpec']['executable'] == python['path'] and request['launchSpec']['sha256'] == python['sha256'])
        startup_version, startup_files = None, None
        if uv_mode:
            _require(inventory['interpreterMode'] == ('research-uv-interpreter-v2' if complete else 'research-uv-interpreter-v1')
                     and type(inventory['startupProfile']) is str
                     and inventory['startupProfile'] in UV_STARTUP_PROFILES)
            startup_version, startup_files = UV_STARTUP_PROFILES[inventory['startupProfile']]
            _require(inventory['startupFiles'] == startup_files)
            if inventory['startupProfile'] in {SETUPTOOLS_STDLIB_PROFILE, SETUPTOOLS_LOCAL_PROFILE}:
                expected_distutils = 'local' if inventory['startupProfile'] == SETUPTOOLS_LOCAL_PROFILE else 'stdlib'
                _require(dict(request['launchSpec']['environment']).get('SETUPTOOLS_USE_DISTUTILS') == expected_distutils)
                _require(expected_distutils != 'local' or complete)
        else:
            _require(request['launchSpec'].get('interpreter_contract') is None)
            _read(python['path'], {key: python[key] for key in ('sha256', 'sizeBytes')}, observations=observations)
        cfg = _read(root / 'pyvenv.cfg', venv['pyvenvCfg'], collect=True, observations=observations).decode('utf-8')
        entries = {}
        for line in cfg.splitlines():
            if '=' in line:
                name, value = (part.strip().lower() for part in line.split('=', 1))
                _require(name not in entries)
                entries[name] = value
        _require(entries.get('include-system-site-packages') == 'false')
        if uv_mode:
            _require(entries.get('uv') == startup_version)
        _startup(site, observations, startup_files=startup_files)
        if uv_mode:
            _uv_interpreter(request, inventory, self._inventory, observations, startup_files)
        site_pins = {}
        site_version_source = None
        if complete:
            site_rows = inventory['siteFiles']
            _require(type(site_rows) is list and 1 <= len(site_rows) <= self._max_files)
            site_total = 0
            for row in site_rows:
                _keys(row, 'path sha256 sizeBytes')
                row = cast(dict[str, Any], row)
                relative = _relative(row['path'])
                _require(relative not in site_pins and type(row['sizeBytes']) is int)
                site_total += row['sizeBytes']
                _require(site_total <= MAX_TOTAL_BYTES)
                pin = {key: row[key] for key in ('sha256', 'sizeBytes')}
                content = _read(site / relative, pin, collect=relative == 'torch/version.py', observations=observations)
                if relative == 'torch/version.py':
                    site_version_source = content
                site_pins[relative] = pin
            _require(set(site_pins) == _tree(site, observations, max_files=self._max_files, max_entries=self._max_entries))
        if inventory.get('startupProfile') == SETUPTOOLS_LOCAL_PROFILE:
            from .research_setuptools_profile import FILES as setuptools_files
            cwd_fd = _open(request['launchSpec']['working_directory'], directory=True)
            try:
                _require('pybuilddir.txt' not in os.listdir(cwd_fd))
            finally:
                os.close(cwd_fd)
            _require(all(site_pins.get(name) == pin for name, pin in setuptools_files.items()
                         if name != 'setuptools-82.0.0.dist-info/RECORD'))
            for name in site_pins:
                if name.startswith(('setuptools/', '_distutils_hack/')) and name not in setuptools_files:
                    _require('/__pycache__/' in name and name.endswith('.pyc'))
                _require(not name.startswith(('setuptools.', '_distutils_hack.', '_distutils_system_mod')))
            # Base stdlib is an existing trusted operator prerequisite. Reject
            # the optional system shim hook rather than silently admitting it.
            import sysconfig
            for location in {sysconfig.get_path('stdlib'), sysconfig.get_path('platstdlib')}:
                fd = _open(location, directory=True)
                try:
                    _require(not any(name.startswith('_distutils_system_mod') for name in os.listdir(fd)))
                    observations.append((location, True, _stamp(os.fstat(fd))))
                finally:
                    os.close(fd)
        packages = inventory['packages']
        _require(type(packages) is list and 3 <= len(packages) <= 128)
        observed, modules, total, count, torch_files = [], set(), 0, 0, {}
        version_source = None
        for package in cast(list[dict[str, Any]], packages):
            _keys(package, 'module version root files')
            name = package['module']
            _require(type(name) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]*' if complete else '[A-Za-z][A-Za-z0-9_]*', name) is not None
                     and name not in modules and type(package['version']) is str and len(package['version']) <= 64
                     and Path(package['root']) == site / name)
            modules.add(name)
            rows = package['files']
            _require(type(rows) is list and 1 <= len(rows) <= self._max_files)
            pins = {}
            for row in cast(list[dict[str, Any]], rows):
                _keys(row, 'path sha256 sizeBytes')
                relative = _relative(row['path'])
                _require(relative not in pins)
                count += 1
                total += row['sizeBytes']
                _require(count <= self._max_files and total <= MAX_TOTAL_BYTES)
                pin = {key: row[key] for key in ('sha256', 'sizeBytes')}
                if complete:
                    _require(site_pins.get(name + '/' + relative) == pin)
                    content = site_version_source if name == 'torch' and relative == 'version.py' else None
                else:
                    content = _read(Path(package['root']) / relative, pin, collect=name == 'torch' and relative == 'version.py', observations=observations)
                if name == 'torch' and relative == 'version.py':
                    version_source = content
                pins[relative] = pin
            _require(set(pins) == _tree(package['root'], observations, max_files=self._max_files, max_entries=self._max_entries if complete else 8192) and '__init__.py' in pins)
            observed.append({'module': name, 'declaredVersion': package['version'], 'files': pins})
            if name == 'torch':
                torch_files = pins
                _require(package['version'] == '2.9.1')
        _require({'torch', 'tiktoken', 'pyarrow'} <= modules and type(version_source) is bytes)
        literals = {}
        for node in ast.parse(cast(bytes, version_source)).body:
            target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else node.target if isinstance(node, ast.AnnAssign) else None
            if isinstance(target, ast.Name) and target.id in {'__version__', 'cuda'}:
                _require(target.id not in literals)
                literals[target.id] = ast.literal_eval(cast(ast.AST, cast(ast.Assign | ast.AnnAssign, node).value))
        _require(type(literals.get('__version__')) is str and literals['__version__'].split('+')[0] == '2.9.1' and literals.get('cuda') == '12.8')
        _keys(kernel, 'schema backend torchVersion cudaVersion torchFiles adapterSha256')
        _require(type(kernel['schema']) is int and kernel['schema'] == 1 and kernel['backend'] == 'pytorch-sdpa'
                 and kernel['torchVersion'] == '2.9.1' and kernel['cudaVersion'] == '12.8'
                 and type(kernel['torchFiles']) is list and bool(kernel['torchFiles']))
        for row in kernel['torchFiles']:
            _keys(row, 'path sha256 sizeBytes')
            _require(torch_files.get(row['path']) == {key: row[key] for key in ('sha256', 'sizeBytes')})
        runtime_files = request['trustedRuntimeFiles']
        _require(type(runtime_files) is list and 1 <= len(runtime_files) <= 128)
        runtime_files = cast(list[dict[str, Any]], runtime_files)
        for row in runtime_files:
            _require(type(row['basename']) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.py', row['basename']) is not None)
        _module_namespace(Path(request['trustedRuntimePackage']), [row['basename'] for row in runtime_files], observations)
        # The selected package itself must not be shadowed by a sibling extension.
        fd = _open(site, directory=True)
        try:
            _require(not any(name.startswith('agent_factory.') for name in os.listdir(fd)))
        finally:
            os.close(fd)
        adapter = [row for row in runtime_files if row['basename'] == 'research_torch_runtime.py']
        _require(len(adapter) == 1 and adapter[0]['sha256'] == kernel['adapterSha256'])
        for row in runtime_files:
            _keys(row, 'basename sha256 size_bytes')
            _require('/' not in row['basename'] and '\\' not in row['basename'] and row['basename'] not in {'.', '..'})
            _read(Path(request['trustedRuntimePackage']) / row['basename'], {'sha256': row['sha256'], 'sizeBytes': row['size_bytes']}, observations=observations)
        manifest = validate_manifest(request['runtimeConfig']['comparisonManifest'])
        _require(not uv_mode or manifest['schema'] == 2)
        _require(manifest['environment'] == request['environment'])
        dataset = manifest['dataset']
        shards = request['runtimeConfig']['dataset']
        _require([{key: row[key] for key in ('id', 'sha256', 'sizeBytes')} for row in shards['shards']] == dataset['shards']
                 and shards['validationShardIds'] == dataset['validationShardIds'])
        sample = {'schema': 1, 'shards': dataset['shards'], 'validationShardIds': dataset['validationShardIds']}
        _require(request['sampleSetSha256'] == dataset['sampleSetSha256'] == digest(sample))
        validation = set(dataset['validationShardIds'])
        train_hashes = {row['sha256'] for row in dataset['shards'] if row['id'] not in validation}
        validation_hashes = {row['sha256'] for row in dataset['shards'] if row['id'] in validation}
        _require(bool(train_hashes) and bool(validation_hashes) and not train_hashes & validation_hashes)
        if uv_mode:
            _uv_interpreter(request, inventory, self._inventory, observations, startup_files)
        for path, directory, stamp in observations:
            fd = _open(path, directory=directory)
            try:
                _require(_stamp(os.fstat(fd)) == stamp)
            finally:
                os.close(fd)
        return {'scope': 'static-listed-files-only', 'python': python, 'packages': observed, 'kernel': kernel,
                'sampleSetSha256': digest(sample), 'importsExecuted': False, 'gpuCompatibilityVerified': False,
                'numericValidation': False, 'dependencyCompletenessVerified': False}

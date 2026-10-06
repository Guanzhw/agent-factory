"""Explicit complete-inventory bounds; inert files only, no interpreter or ML run."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
import unittest

from agent_factory.research_interpreter import capture_interpreter_contract, open_interpreter, recheck_interpreter, validate_interpreter_contract
from agent_factory.research_environment_observer import ResearchEnvironmentObserver
import test_research_interpreter as interpreter_fixture  # pyright: ignore[reportMissingImports]
import test_research_environment_observer as observer_fixture  # pyright: ignore[reportMissingImports]

PROFILE = 'complete-venv-32768-v1'
canonical = interpreter_fixture.canonical


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'POSIX nofollow required')
class ResearchInventoryProfileTests(unittest.TestCase):
    def setUp(self):
        self.fixture = interpreter_fixture.InterpreterTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def capture(self, *, profile=None, files=None):
        f = self.fixture
        return capture_interpreter_contract(executable=str(f.link), sha256=f.sha,
            project_root=f.project, venv_root=f.venv, approved_interpreter_roots=[f.approved],
            pyvenv_cfg=f.cfg, pyproject_toml=f.project_file, uv_lock=f.lock,
            package_inventory=f.inventory, package_files=[f.package] if files is None else files,
            bounds_profile=profile)

    def validate(self, value):
        return validate_interpreter_contract(canonical(value), str(self.fixture.link), self.fixture.sha)

    def test_default_contract_is_unchanged_and_4097_files_still_denied(self):
        raw = self.capture()
        value = json.loads(raw)
        self.assertEqual(value['schema'], 1)
        self.assertEqual(value['kind'], 'research-uv-interpreter-v1')
        self.assertNotIn('boundsProfile', value)
        pin = value['packageFiles'][0]
        value['packageFiles'] = [{**pin, 'path': str(self.fixture.venv / f'file-{number:05d}.py')} for number in range(4097)]
        with self.assertRaises(ValueError):
            self.validate(value)
        with self.assertRaises(ValueError):
            self.capture(files=[self.fixture.package] * 4097)

    def test_explicit_profile_captures_and_rechecks_4097_real_single_link_files(self):
        files = []
        for number in range(4097):
            path = self.fixture.venv / f'file-{number:05d}.py'
            path.write_bytes(b'# inert\n')
            files.append(path)
        raw = self.capture(profile=PROFILE, files=files)
        value = json.loads(raw)
        self.assertEqual((value['schema'], value['kind'], value['boundsProfile']),
                         (2, 'research-uv-interpreter-v2', PROFILE))
        self.assertEqual(len(value['packageFiles']), 4097)
        fd = open_interpreter(raw, str(self.fixture.link), self.fixture.sha)
        try:
            recheck_interpreter(raw, str(self.fixture.link), self.fixture.sha, fd)
            files[-1].write_bytes(b'# changed\n')
            with self.assertRaises(ValueError):
                recheck_interpreter(raw, str(self.fixture.link), self.fixture.sha, fd)
        finally:
            os.close(fd)

    def test_unknown_profile_and_mixed_schema_cannot_borrow_larger_limits(self):
        for profile in ('unknown', '', True):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                self.capture(profile=profile)
        small, large = json.loads(self.capture()), json.loads(self.capture(profile=PROFILE))
        invalid = [small | {'boundsProfile': PROFILE}, small | {'schema': 2},
            large | {'schema': 1}, large | {'kind': 'research-uv-interpreter-v1'},
            large | {'boundsProfile': 'unknown'}]
        missing = deepcopy(large); missing.pop('boundsProfile'); invalid.append(missing)
        for value in invalid:
            with self.subTest(schema=value['schema'], kind=value['kind']), self.assertRaises(ValueError):
                self.validate(value)

    def test_larger_profile_keeps_count_byte_and_namespace_bounds_finite(self):
        base = json.loads(self.capture(profile=PROFILE))
        pin = base['packageFiles'][0]
        cases = []
        value = deepcopy(base)
        value['packageFiles'] = [{**pin, 'path': str(self.fixture.venv / f'x{number}')} for number in range(32769)]
        cases.append(value)
        value = deepcopy(base); value['packageFiles'][0]['sizeBytes'] = 1024**3 + 1; cases.append(value)
        value = deepcopy(base)
        value['packageFiles'] = [{**pin, 'path': str(self.fixture.venv / f'x{number}'), 'sizeBytes': 1024**3} for number in range(9)]
        cases.append(value)
        value = deepcopy(base); value['namespaces'][0]['entryCount'] = 65537; cases.append(value)
        for value in cases:
            with self.assertRaises(ValueError):
                self.validate(value)

    def test_contract_size_limits_are_schema_specific(self):
        small = json.loads(self.capture())
        pin = small['packageFiles'][0]
        # Valid shape, long absolute filenames: no filesystem access is claimed.
        small['packageFiles'] = [{**pin, 'path': str(self.fixture.venv / (f'{number:04d}-' + 'x' * 600))} for number in range(3000)]
        self.assertGreater(len(canonical(small).encode()), 2 * 1024**2)
        with self.assertRaises(ValueError):
            self.validate(small)
        large = small | {'schema': 2, 'kind': 'research-uv-interpreter-v2', 'boundsProfile': PROFILE}
        self.validate(large)
        with self.assertRaises(ValueError):
            validate_interpreter_contract('x' * (16 * 1024**2 + 1), str(self.fixture.link), self.fixture.sha)

    def test_expanded_profile_never_accepts_shared_inode_or_missing_nofollow(self):
        from unittest.mock import patch
        raw = self.capture(profile=PROFILE)
        alias = self.fixture.venv / 'shared-alias.py'
        os.link(self.fixture.package, alias)
        with self.assertRaises(ValueError):
            self.capture(profile=PROFILE)
        with self.assertRaises(ValueError):
            open_interpreter(raw, str(self.fixture.link), self.fixture.sha)
        alias.unlink()
        with patch.object(os, 'O_NOFOLLOW', 0), self.assertRaises(ValueError):
            open_interpreter(raw, str(self.fixture.link), self.fixture.sha)


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'POSIX nofollow required')
class ResearchObserverProfileTests(unittest.TestCase):
    def setUp(self):
        self.f = observer_fixture.ResearchEnvironmentObserverTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def complete_observer(self, *, omit_inventory=None, omit_contract=None):
        """Pin all inert site files; omissions are intentional negative inputs."""
        f = self.f
        inventory = json.loads((f.root / 'inventory.json').read_bytes())
        paths = sorted(path for path in f.site.rglob('*') if path.is_file())
        inventory.update(schema=3, boundsProfile=PROFILE, interpreterMode='research-uv-interpreter-v2',
            siteFiles=[{'path': path.relative_to(f.site).as_posix(),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'sizeBytes': path.stat().st_size}
                       for path in paths if path.relative_to(f.site).as_posix() != omit_inventory])
        pin = f.input('environment-inventory', 'inventory.json', inventory)
        large = ResearchEnvironmentObserver(pin, f.observer._kernel, bounds_profile=PROFILE)
        f.request['configurationFingerprint'] = large.configuration_fingerprint
        f.request['environment']['installedInventory'] = {'sha256': pin.file.sha256, 'sizeBytes': pin.file.size_bytes}
        f.request['environmentPins'][0] = asdict(pin)
        f.request['launchSpec']['interpreter_contract'] = capture_interpreter_contract(
            executable=inventory['python']['path'], sha256=inventory['python']['sha256'],
            project_root=f.root, venv_root=f.venv, approved_interpreter_roots=[f.root / 'managed'],
            pyvenv_cfg=f.venv / 'pyvenv.cfg', pyproject_toml=f.root / 'pyproject.toml', uv_lock=f.root / 'uv.lock',
            package_inventory=f.root / 'inventory.json',
            package_files=[path for path in paths if path.relative_to(f.site).as_posix() != omit_contract],
            bounds_profile=PROFILE)
        return large, pin

    def test_explicit_observer_profile_changes_identity_and_rejects_legacy_inventory(self):
        old = self.f.observer
        large = ResearchEnvironmentObserver(old._inventory, old._kernel, bounds_profile=PROFILE)
        self.assertNotEqual(old.configuration_fingerprint, large.configuration_fingerprint)
        request = deepcopy(self.f.request)
        request['configurationFingerprint'] = large.configuration_fingerprint
        self.assertEqual(large(request)['status'], 'UNKNOWN')
        with self.assertRaises(ValueError):
            ResearchEnvironmentObserver(old._inventory, old._kernel, bounds_profile='unknown')

    def test_collected_inventory_document_limit_changes_only_with_explicit_profile(self):
        f = self.f
        document = {'inertMetadata': 'x' * (1024**2)}
        pin = f.input('environment-inventory', 'large-inventory.json', document)
        legacy = ResearchEnvironmentObserver(pin, f.observer._kernel)
        large = ResearchEnvironmentObserver(pin, f.observer._kernel, bounds_profile=PROFILE)
        with self.assertRaises(ValueError):
            legacy._document(pin, [])
        self.assertEqual(large._document(pin, []), document)
        too_big = f.input('environment-inventory', 'too-large-inventory.json', {'inertMetadata': 'x' * (8 * 1024**2)})
        with self.assertRaises(ValueError):
            ResearchEnvironmentObserver(too_big, f.observer._kernel, bounds_profile=PROFILE)._document(too_big, [])

    def test_schema3_uv_requires_matching_explicit_observer_and_interpreter_profiles(self):
        f = self.f
        f.uv_fixture('uv0117-virtualenv-startup-v1')
        original = f.observer
        old_contract = f.request['launchSpec']['interpreter_contract']
        large, pin = self.complete_observer()
        self.assertEqual(large(f.request)['status'], 'VERIFIED')
        default = ResearchEnvironmentObserver(pin, original._kernel)
        request = deepcopy(f.request); request['configurationFingerprint'] = default.configuration_fingerprint
        self.assertEqual(default(request)['status'], 'UNKNOWN')
        f.request['launchSpec']['interpreter_contract'] = old_contract
        self.assertEqual(large(f.request)['status'], 'UNKNOWN')

    def test_complete_site_rejects_omitted_top_level_metadata_and_extra_module(self):
        f = self.f
        f.uv_fixture('uv0117-virtualenv-startup-v1')
        extras = ('loose.py', 'example.dist-info/METADATA', 'extra_module/__init__.py')
        for name in extras:
            path = f.site / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'# inert synthetic inventory fixture\n')
        large, _ = self.complete_observer()
        self.assertEqual(large(f.request)['status'], 'VERIFIED')
        for name in extras:
            with self.subTest(omitted_inventory=name):
                large, _ = self.complete_observer(omit_inventory=name)
                self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            with self.subTest(omitted_contract=name):
                large, _ = self.complete_observer(omit_contract=name)
                self.assertEqual(large(f.request)['status'], 'UNKNOWN')
        large, _ = self.complete_observer()
        self.assertEqual(large(f.request)['status'], 'VERIFIED')

    def test_setuptools_startup_requires_prestartup_stdlib_environment_and_exact_pth(self):
        from agent_factory import research_environment_observer as module
        f = self.f
        f.uv_fixture('uv0117-virtualenv-startup-v1')
        # Exact bytes read from the official setuptools 82.0.0 wheel; not executed.
        # Its MIT permission notice is retained in fixtures/setuptools82/LICENSE.
        pth = (b"import os; var = 'SETUPTOOLS_USE_DISTUTILS'; enabled = os.environ.get(var, 'local') == 'local'; "
               b"enabled and __import__('_distutils_hack').add_shim(); \n")
        self.assertEqual(len(pth), 151)
        self.assertEqual(hashlib.sha256(pth).hexdigest(),
                         '2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224')
        (f.site / 'distutils-precedence.pth').write_bytes(pth)
        inventory = json.loads((f.root / 'inventory.json').read_bytes())
        inventory['startupProfile'] = module.SETUPTOOLS_STDLIB_PROFILE
        inventory['startupFiles'] = deepcopy(module.UV_STARTUP_PROFILES[module.SETUPTOOLS_STDLIB_PROFILE][1])
        f.input('environment-inventory', 'inventory.json', inventory)
        large, _ = self.complete_observer()
        self.assertEqual(large(f.request)['status'], 'UNKNOWN')

        env = f.request['launchSpec']['environment']
        env.append(['SETUPTOOLS_USE_DISTUTILS', 'local'])
        self.assertEqual(large(f.request)['status'], 'UNKNOWN')
        env[-1][1] = 'stdlib'
        self.assertEqual(large(f.request)['status'], 'VERIFIED')
        (f.site / 'extra.pth').write_bytes(b'import os\n')
        large, _ = self.complete_observer()
        self.assertEqual(large(f.request)['status'], 'UNKNOWN')

    def test_local_shim_requires_complete_official_pins_and_rejects_unlisted_hooks(self):
        from unittest.mock import patch
        from agent_factory import research_environment_observer as module
        from agent_factory import research_setuptools_profile as official
        f = self.f
        f.uv_fixture('uv0117-virtualenv-startup-v1')
        pth = (b"import os; var = 'SETUPTOOLS_USE_DISTUTILS'; enabled = os.environ.get(var, 'local') == 'local'; "
               b"enabled and __import__('_distutils_hack').add_shim(); \n")
        (f.site / 'distutils-precedence.pth').write_bytes(pth)
        tiny = {}
        for name in ('_distutils_hack/__init__.py', '_distutils_hack/override.py',
                     'setuptools/__init__.py', 'setuptools-82.0.0.dist-info/METADATA'):
            path = f.site / name
            path.parent.mkdir(exist_ok=True)
            # If any tested target package is imported, the test must fail.
            body = b'raise AssertionError("target package must not execute")\n'
            path.write_bytes(body)
            tiny[name] = {'sha256': hashlib.sha256(body).hexdigest(), 'sizeBytes': len(body)}
        record_name = 'setuptools-82.0.0.dist-info/RECORD'
        (f.site / record_name).write_bytes(b'installer-rewritten synthetic RECORD\n')
        tiny[record_name] = {'sha256': hashlib.sha256(b'original wheel RECORD').hexdigest(),
                             'sizeBytes': len(b'original wheel RECORD')}
        inventory = json.loads((f.root / 'inventory.json').read_bytes())
        inventory['startupProfile'] = module.SETUPTOOLS_LOCAL_PROFILE
        inventory['startupFiles'] = deepcopy(module.UV_STARTUP_PROFILES[module.SETUPTOOLS_LOCAL_PROFILE][1])
        f.input('environment-inventory', 'inventory.json', inventory)
        with patch.object(official, 'FILES', tiny):
            interpreter_patch = patch.object(module.sys, 'executable', str(f.venv / 'bin' / 'python'))
            interpreter_patch.start()
            self.addCleanup(interpreter_patch.stop)
            large, _ = self.complete_observer()
            self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            env = f.request['launchSpec']['environment']
            env.append(['SETUPTOOLS_USE_DISTUTILS', 'stdlib'])
            self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            env[-1][1] = 'local'
            # Installer-rewritten RECORD stays inventoried, not matched to wheel bytes.
            self.assertEqual(large(f.request)['status'], 'VERIFIED')
            with patch.object(module.sys, 'executable', str(f.root / 'not-the-interpreter')):
                self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            cwd = f.request['launchSpec']['working_directory']
            from pathlib import Path
            marker = Path(cwd) / 'pybuilddir.txt'
            marker.write_bytes(b'not a CPython build\n')
            large, _ = self.complete_observer()
            self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            marker.unlink()
            large, _ = self.complete_observer(omit_inventory='setuptools/__init__.py')
            self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            large, _ = self.complete_observer(omit_inventory=record_name)
            self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            target = f.site / 'setuptools/__init__.py'
            original = target.read_bytes()
            target.write_bytes(b'# different but freshly inventoried source\n')
            large, _ = self.complete_observer()
            self.assertEqual(large(f.request)['status'], 'UNKNOWN')
            target.write_bytes(original)
            for name in ('_distutils_system_mod.py', 'setuptools.py', 'setuptools/extra.py'):
                with self.subTest(hook=name):
                    path = f.site / name
                    path.write_bytes(b'# unapproved hook or source\n')
                    large, _ = self.complete_observer()
                    self.assertEqual(large(f.request)['status'], 'UNKNOWN')
                    path.unlink()
            large, _ = self.complete_observer()
            self.assertEqual(large(f.request)['status'], 'VERIFIED')

    def test_official_setuptools_data_pins_known_wheel_and_startup(self):
        from agent_factory import research_setuptools_profile as official
        self.assertEqual(len(official.FILES), 439)
        self.assertIn('setuptools-82.0.0.dist-info/RECORD', official.FILES)
        self.assertEqual(official.WHEEL_SHA256, '70b18734b607bd1da571d097d236cfcfacaf01de45717d59e6e04b96877532e0')
        self.assertEqual(official.FILES['distutils-precedence.pth'], {
            'sha256': '2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d224', 'sizeBytes': 151})
        self.assertEqual(official.FILES['setuptools-82.0.0.dist-info/METADATA'], {
            'sha256': 'ac7e92d32efa17a0d854cbccbe9c3244f7caa5e5633b32f1a1fde1da26ae915f', 'sizeBytes': 6573})

"""Offline distribution checks for the app-owned, standalone native runtime.

Build with the project's real backend and import only the installed payload in
isolated Python. No native binary, Docker process, SSH connection or model runs.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[4]
PACKAGE = Path('apps/research/agent_factory_research/runtime_packages')
WHEEL_PACKAGE = Path('agent_factory_research/runtime_packages')
MODULES = ('entry', 'bridge', 'supervisor', 'ssh_agent', 'ssh_install', 'ssh_prerequisites')

BUILD = '''
import json, sys
from hatchling.build import build_sdist, build_wheel
print(json.dumps({kind: builder(sys.argv[1]) for kind, builder in
    (("wheel", build_wheel), ("sdist", build_sdist))}))
'''

IMPORT_RUNTIME = '''
import importlib, json, pathlib, sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
package = sys.argv[2]
modules = {name: importlib.import_module(package + "." + name) for name in json.loads(sys.argv[3])}
entry = modules["entry"]
config = SimpleNamespace(validate=lambda: None, cpus=1, memory_mb=1024, pids=64,
    session_root="/synthetic/session", orx=SimpleNamespace(path="/synthetic/orx"),
    opencode=SimpleNamespace(path="/synthetic/opencode"), image="sha256:" + "a" * 64)
command = entry.build_command(config, "factory-orx-" + "b" * 32, "synthetic-capability-0123456789")
print(json.dumps({"files": {name: str(pathlib.Path(module.__file__).resolve())
    for name, module in modules.items()}, "command": command,
    "packageVersion": modules["supervisor"].PACKAGE_VERSION,
    "orxSha256": modules["supervisor"].LINUX_SHA256,
    "opencodeSha256": modules["supervisor"].OPENCODE_SHA256}))
'''


class RuntimePackageDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory(prefix='factory-runtime-distribution-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.source = {path.relative_to(ROOT / PACKAGE).as_posix(): path.read_bytes()
            for path in (ROOT / PACKAGE).rglob('*')
            if path.is_file() and '__pycache__' not in path.parts}
        built = subprocess.run([sys.executable, '-I', '-B', '-c', BUILD, str(cls.root)],
            cwd=ROOT, capture_output=True, text=True, check=True)
        cls.artifacts = json.loads(built.stdout)
        cls.wheel = cls.root / cls.artifacts['wheel']
        cls.site = cls.root / 'installed'
        with zipfile.ZipFile(cls.wheel) as archive:
            archive.extractall(cls.site)

    def runtime(self, site, name, modules=MODULES):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', IMPORT_RUNTIME,
            str(site), name, json.dumps(modules)], cwd=self.root,
            capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def assert_mounts(self, runtime, directory):
        command = runtime['command']
        mounts = [command[index + 1] for index, value in enumerate(command) if value == '--mount']
        for name, destination in (('entry.py', '/trusted/entry.py'), ('bridge.py', '/trusted/bridge.py'),
                                  ('bridge.py', '/trusted/opencode')):
            self.assertIn(f'type=bind,src={directory / name},dst={destination},readonly', mounts)
        self.assertEqual(command[-5:], ['/usr/local/bin/python3', '-I', '-B', '/trusted/entry.py', '--container'])

    def test_wheel_contains_exact_application_runtime_and_license_payload(self):
        with zipfile.ZipFile(self.wheel) as archive:
            prefix = WHEEL_PACKAGE.as_posix() + '/'
            actual = {name[len(prefix):]: archive.read(name) for name in archive.namelist()
                if name.startswith(prefix) and not name.endswith('/')}
            self.assertEqual(actual, self.source)
            self.assertFalse(any(name.startswith('agent_factory/runtime_packages/') for name in archive.namelist()))
        for name in ('ORX-LICENSE.txt', 'OPENCODE-LICENSE.txt', 'FACTORY-LICENSE.txt', 'THIRD_PARTY_NOTICES.md'):
            self.assertIn('openresearch_v1/notices/' + name, self.source)

    def test_installed_runtime_imports_without_factory_and_mounts_installed_scripts(self):
        runtime = self.runtime(self.site, 'agent_factory_research.runtime_packages.openresearch_v1')
        directory = self.site / WHEEL_PACKAGE / 'openresearch_v1'
        self.assertEqual(runtime['files'], {name: str(directory / (name + '.py')) for name in MODULES})
        self.assert_mounts(runtime, directory)

    def test_source_distribution_rebuilds_the_same_runtime_payload(self):
        extracted = self.root / 'source-distribution'
        with tarfile.open(self.root / self.artifacts['sdist']) as archive:
            archive.extractall(extracted, filter='data')
        roots = list(extracted.iterdir())
        self.assertEqual(len(roots), 1)
        source = roots[0]
        actual = {path.relative_to(source / PACKAGE).as_posix(): path.read_bytes()
            for path in (source / PACKAGE).rglob('*') if path.is_file()}
        self.assertEqual(actual, self.source)
        self.assertTrue((source / 'apps/research/tests/python/test_platform_openresearch_runtime.py').is_file())
        output = self.root / 'rebuilt'
        output.mkdir()
        built = subprocess.run([sys.executable, '-I', '-B', '-c',
            'import sys; from hatchling.build import build_wheel; print(build_wheel(sys.argv[1]))', str(output)],
            cwd=source, capture_output=True, text=True, check=True)
        with zipfile.ZipFile(output / built.stdout.strip()) as archive:
            prefix = WHEEL_PACKAGE.as_posix() + '/'
            payload = {name[len(prefix):]: archive.read(name) for name in archive.namelist()
                if name.startswith(prefix) and not name.endswith('/')}
        self.assertEqual(payload, self.source)

    def test_ssh_payload_keeps_flat_factory_package_imports_and_native_identity(self):
        # The existing installer publishes these files directly into
        # <selected-directory>/factory_package, independent of wheel names.
        from agent_factory_research.runtime_packages.openresearch_v1 import ssh_install
        from agent_factory_research.ssh_openresearch import SSHOpenResearchConfig, SSHOpenResearchPackage
        from agent_factory_research.platform_openresearch import PlatformOpenResearchConfig
        from unittest.mock import patch

        binary = self.root / 'synthetic-binary'
        binary.write_bytes(b'SYNTHETIC-NOT-EXECUTED')
        config = PlatformOpenResearchConfig(str(binary), str(binary), 'sha256:' + 'a' * 64)
        with patch.object(PlatformOpenResearchConfig, 'validate'):
            package = SSHOpenResearchPackage(SSHOpenResearchConfig(config, (), lambda **_: None),
                self.root / 'custody')
        self.assertEqual(set(package.files) | {'image.tar'}, ssh_install.FILES)
        target = self.root / 'remote' / 'factory_package'
        target.mkdir(parents=True)
        for name, source in package.files.items():
            shutil.copyfile(source, target / name)
            self.assertEqual((target / name).read_bytes(), source.read_bytes())
        remote = self.runtime(target.parent, 'factory_package', ('entry', 'bridge', 'supervisor', 'ssh_agent'))
        installed = self.runtime(self.site, 'agent_factory_research.runtime_packages.openresearch_v1')
        for key in ('packageVersion', 'orxSha256', 'opencodeSha256'):
            self.assertEqual(remote[key], installed[key])
        self.assert_mounts(remote, target)


if __name__ == '__main__':
    unittest.main()

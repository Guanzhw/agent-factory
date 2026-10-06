"""Synthetic temp installation only; no interpreter, package or GPU execution."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_factory import research_environment_observer as module

from agent_factory.research_environment_observer import ResearchEnvironmentObserver
from agent_factory.research_staging import FilePin, InputPin, RootIdentity
from agent_factory.store import digest
from test_research_manifest import example_manifest  # pyright: ignore[reportMissingImports]


@unittest.skipUnless(os.name == 'posix', 'POSIX nofollow static inventory')
class ResearchEnvironmentObserverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.venv = self.root / 'venv'
        self.site = self.venv / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        self.site.mkdir(parents=True, mode=0o700)
        python = self.write(self.venv / 'bin' / 'python', b'synthetic interpreter bytes, never executable')
        cfg = self.write(self.venv / 'pyvenv.cfg', b'include-system-site-packages = false\n')
        packages = []
        for name in ('torch', 'tiktoken', 'pyarrow'):
            root = self.site / name
            init = self.write(root / '__init__.py', b'' if name == 'pyarrow' else b'# synthetic package, never imported\n')
            rows = [{'path': '__init__.py', **init}]
            if name == 'torch':
                rows.append({'path': 'version.py', **self.write(root / 'version.py', b"__version__ = '2.9.1+cu128'\ncuda: str = '12.8'\n")})
            packages.append({'module': name, 'version': '2.9.1' if name == 'torch' else 'synthetic', 'root': str(root), 'files': rows})
        self.program_root = self.root / 'program'
        self.program_root.mkdir(mode=0o700)
        self.runtime_root = self.site / 'agent_factory'
        adapter = self.write(self.runtime_root / 'research_torch_runtime.py', b'# fixed adapter bytes\n')
        inventory = {'schema': 1, 'python': {'path': str(self.venv / 'bin' / 'python'), **python},
            'venv': {'root': str(self.venv), 'sitePackages': str(self.site), 'pyvenvCfg': cfg}, 'packages': packages}
        kernel = {'schema': 1, 'backend': 'pytorch-sdpa', 'torchVersion': '2.9.1', 'cudaVersion': '12.8',
            'torchFiles': packages[0]['files'], 'adapterSha256': adapter['sha256']}
        inventory_pin = self.input('environment-inventory', 'inventory.json', inventory)
        kernel_pin = self.input('environment-kernel', 'kernel.json', kernel)
        self.observer = ResearchEnvironmentObserver(inventory_pin, kernel_pin)
        manifest = example_manifest()
        manifest['environment']['installedInventory'] = {'sha256': inventory_pin.file.sha256, 'sizeBytes': inventory_pin.file.size_bytes}
        manifest['environment']['runtimeKernel'] = {'sha256': kernel_pin.file.sha256, 'sizeBytes': kernel_pin.file.size_bytes}
        manifest['dataset']['shards'][1]['sha256'] = '9' * 64
        manifest['dataset']['sampleSetSha256'] = digest({'schema': 1, 'shards': manifest['dataset']['shards'],
            'validationShardIds': manifest['dataset']['validationShardIds']})
        self.request = {'environment': manifest['environment'], 'runtimeKernel': manifest['environment']['runtimeKernel'],
            'sampleSetSha256': manifest['dataset']['sampleSetSha256'], 'configurationFingerprint': self.observer.configuration_fingerprint,
            'launchSpec': {'executable': str(self.venv / 'bin' / 'python'), 'sha256': python['sha256'], 'argv': ['-B', str(self.program_root / 'train.py'), '--config', str(self.program_root / 'run-config.json')],
                'working_directory': str(self.program_root), 'environment': [('PYTHONPYCACHEPREFIX', str(self.program_root))]},
            'trustedRuntimePackage': str(self.runtime_root), 'trustedRuntimeFiles': [{'basename': 'research_torch_runtime.py',
                'sha256': adapter['sha256'], 'size_bytes': adapter['sizeBytes']}],
            'runtimeConfig': {'comparisonManifest': manifest, 'dataset': {'shards': [row | {'basename': row['id'] + '.parquet'} for row in manifest['dataset']['shards']],
                'validationShardIds': manifest['dataset']['validationShardIds']}},
            'environmentPins': [asdict(inventory_pin), asdict(kernel_pin)]}

    def write(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(raw)
        path.chmod(0o600)
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}

    def input(self, label, name, value):
        identity = self.write(self.root / name, json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
        info = self.root.stat()
        return InputPin(label, 'environment', str(self.root), RootIdentity(info.st_dev, info.st_ino),
            FilePin(name, identity['sha256'], identity['sizeBytes']))

    def test_static_declared_scope_verified_without_executing_interpreter(self):
        receipt = self.observer(self.request)
        self.assertEqual(receipt['status'], 'VERIFIED')
        self.assertEqual(receipt['requestSha256'], digest(self.request))
        self.assertEqual(set(receipt), {'schema', 'status', 'requestSha256', 'observationSha256'})
        self.assertEqual(receipt, self.observer(deepcopy(self.request)))

    def test_interpreter_file_and_package_extra_or_modified_bytes_unknown(self):
        target = self.venv / 'bin' / 'python'
        original = target.read_bytes()
        target.write_bytes(b'changed')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        target.write_bytes(original)
        extra = self.site / 'torch' / 'injected.py'
        self.write(extra, b'not inventoried')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        extra.unlink()
        (self.site / 'torch' / 'version.py').write_bytes(b"__version__='2.9.1'\ncuda='wrong'\n")
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_earlier_file_mutation_during_later_scan_is_rechecked_at_receipt(self):
        read = module._read
        def later_mutation(path, *args, **kwargs):
            result = read(path, *args, **kwargs)
            if str(path).endswith('research_torch_runtime.py'):
                python = self.venv / 'bin' / 'python'
                python.write_bytes(b'x' * python.stat().st_size)
            return result
        with patch.object(module, '_read', side_effect=later_mutation):
            self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_runtime_package_outside_selected_venv_cannot_be_attested(self):
        request = deepcopy(self.request)
        request['trustedRuntimePackage'] = str(self.root / 'other-package')
        self.assertEqual(self.observer(request)['status'], 'UNKNOWN')

    def test_actual_pinned_torch_version_literals_must_match_kernel_claim(self):
        pin = self.write(self.site / 'torch' / 'version.py', b"__version__ = '2.9.1'\ncuda = 'wrong'\n")
        inventory = json.loads((self.root / 'inventory.json').read_bytes())
        inventory['packages'][0]['files'][1] = {'path': 'version.py', **pin}
        kernel = json.loads((self.root / 'kernel.json').read_bytes())
        kernel['torchFiles'] = inventory['packages'][0]['files']
        first = self.input('environment-inventory', 'inventory.json', inventory)
        second = self.input('environment-kernel', 'kernel.json', kernel)
        self.observer = ResearchEnvironmentObserver(first, second)
        for selected, key in ((first, 'installedInventory'), (second, 'runtimeKernel')):
            self.request['environment'][key] = {'sha256': selected.file.sha256, 'sizeBytes': selected.file.size_bytes}
        self.request['runtimeKernel'] = self.request['environment']['runtimeKernel']
        self.request['configurationFingerprint'] = self.observer.configuration_fingerprint
        self.request['environmentPins'] = [asdict(first), asdict(second)]
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_pth_customization_and_symlink_interpreter_are_unsupported(self):
        path = self.site / 'injection.pth'
        self.write(path, b'import arbitrary_startup\n')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        path.unlink()
        self.write(self.site / 'sitecustomize.py', b'pass')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        (self.site / 'sitecustomize.py').unlink()
        python = self.venv / 'bin' / 'python'
        python.rename(python.with_name('actual'))
        python.symlink_to('actual')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_startup_extensions_and_runtime_shadow_modules_are_rejected(self):
        for root, name in ((self.site, 'sitecustomize.cpython-312-x86_64-linux-gnu.so'),
                           (self.site, 'usercustomize.pyd'),
                           (self.site, 'agent_factory.abi3.so'),
                           (self.runtime_root, 'research_torch_runtime.abi3.so'),
                           (self.runtime_root, 'research_torch_runtime.pyc')):
            with self.subTest(name=name):
                path = root / name
                self.write(path, b'synthetic never-loaded module')
                self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
                path.unlink()
        path = self.runtime_root / 'research_torch_runtime'
        path.mkdir()
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        path.rmdir()
        self.assertEqual(self.observer(self.request)['status'], 'VERIFIED')

    def test_bytecode_read_prefix_requires_B_and_empty_cache_tree(self):
        for change in ('argv', 'environment'):
            request = deepcopy(self.request)
            request['launchSpec'][change] = []
            self.assertEqual(self.observer(request)['status'], 'UNKNOWN')
        request = deepcopy(self.request)
        request['launchSpec']['environment'] = [('PYTHONPYCACHEPREFIX', str(self.root))]
        self.assertEqual(self.observer(request)['status'], 'UNKNOWN')
        cache = self.program_root / 'some-absolute-path'
        cache.mkdir()
        self.write(cache / 'module.pyc', b'synthetic cache never loaded')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_forged_sample_split_reused_shards_and_bad_request_unknown(self):
        changed = deepcopy(self.request)
        changed['sampleSetSha256'] = '0' * 64
        self.assertEqual(self.observer(changed)['status'], 'UNKNOWN')
        changed = deepcopy(self.request)
        dataset = changed['runtimeConfig']['comparisonManifest']['dataset']
        dataset['shards'][1]['sha256'] = dataset['shards'][0]['sha256']
        dataset['sampleSetSha256'] = digest({'schema': 1, 'shards': dataset['shards'], 'validationShardIds': dataset['validationShardIds']})
        changed['sampleSetSha256'] = dataset['sampleSetSha256']
        changed['runtimeConfig']['dataset']['shards'][1]['sha256'] = dataset['shards'][1]['sha256']
        self.assertEqual(self.observer(changed)['status'], 'UNKNOWN')
        changed = deepcopy(self.request)
        changed['untrusted'] = 'ignored?'
        self.assertEqual(self.observer(changed)['status'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()

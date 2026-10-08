"""Synthetic complete site inventory; no interpreter/package/ML execution."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from agent_factory import research_bootstrap_inventory as module
import test_research_environment_observer as environment_fixture  # pyright: ignore[reportMissingImports]


@unittest.skipUnless(os.name == 'posix', 'Descriptor-safe static inventory requires POSIX')
class BootstrapInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'; self.project.mkdir(mode=0o700)
        self.venv = self.project / '.venv'; self.venv.mkdir(mode=0o700)
        (self.venv / 'bin').mkdir()
        self.site = self.venv / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        self.site.mkdir(parents=True)
        self.target = self.root / 'python'; self.target.write_bytes(b'inert interpreter bytes, never executed')
        (self.venv / 'bin' / 'python').symlink_to(self.target)
        (self.venv / 'pyvenv.cfg').write_text('uv = 0.11.7\ninclude-system-site-packages = false\n')
        (self.project / 'pyproject.toml').write_text('[project]\nname="inert"\n')
        (self.project / 'uv.lock').write_text('version = 1\n')
        (self.site / '_virtualenv.py').write_bytes(environment_fixture._UV_0117_STARTUP_SOURCE)
        (self.site / '_virtualenv.pth').write_bytes(b'import _virtualenv')
        for name, version in [('torch', '2.9.1+cu128'), ('tiktoken', '0.12.0'), ('pyarrow', '21.0.0')]:
            package = self.site / name; package.mkdir()
            (package / '__init__.py').write_text("raise RuntimeError('package must never import')\n")
            metadata = self.site / (name + '-' + version + '.dist-info'); metadata.mkdir()
            (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: ' + name + '\nVersion: ' + version + '\n')
        (self.site / 'torch' / 'version.py').write_text("__version__ = '2.9.1+cu128'\ncuda = '12.8'\n")
        factory = self.site / 'agent_factory'; factory.mkdir()
        (factory / 'research_torch_runtime.py').write_text('# inert adapter identity only\n')
        (self.site / 'standalone.py').write_text('# top level must be inventoried\n')
        cache = self.site / '__pycache__'; cache.mkdir()
        (cache / 'compiled.cpython-312.pyc').write_bytes(b'inert bytecode inventory bytes')
        self.kwargs: dict[str, Any] = dict(project_root=self.project, venv_root=self.venv,
            interpreter_target=self.target, interpreter_sha256=hashlib.sha256(self.target.read_bytes()).hexdigest(),
            approved_interpreter_roots=[self.root], inventory_path=self.root / 'inventory.json')

    def test_complete_inventory_and_capture_paths_include_entire_site(self):
        result = module.build_inventory(**self.kwargs)
        inventory = result['inventory']
        self.assertEqual(inventory, json.loads(result['inventoryBytes']))
        names = {row['path'] for row in inventory['siteFiles']}
        self.assertIn('standalone.py', names)
        self.assertIn('__pycache__/compiled.cpython-312.pyc', names)
        self.assertIn('torch-2.9.1+cu128.dist-info/METADATA', names)
        self.assertIn('agent_factory/research_torch_runtime.py', names)
        self.assertEqual({str(path.relative_to(self.site)) for path in result['captureKwargs']['package_files']}, names)
        self.assertEqual(inventory['schema'], 3)
        self.assertEqual(inventory['boundsProfile'], module.PROFILE)
        self.assertEqual([row['version'] for row in inventory['packages']], ['2.9.1', '0.12.0', '21.0.0'])
        self.assertFalse(self.kwargs['inventory_path'].exists())
        self.assertEqual(result['kernel']['torchFiles'][1]['path'], 'version.py')

    def test_reviewed_setuptools_profile_is_inventoried_without_execution(self):
        # Exact reviewed wheel bytes; MIT notice fixtures/setuptools82/LICENSE.
        pth = (b"import os; var = 'SETUPTOOLS_USE_DISTUTILS'; enabled = os.environ.get(var, 'local') == 'local'; "
               b"enabled and __import__('_distutils_hack').add_shim(); \n")
        (self.site / 'distutils-precedence.pth').write_bytes(pth)
        result = module.build_inventory(**self.kwargs, startup_profile='uv0117-setuptools82-stdlib-v1')
        self.assertIn('distutils-precedence.pth', result['inventory']['startupFiles'])
        self.assertEqual(result['inventory']['startupFiles']['distutils-precedence.pth']['sha256'], hashlib.sha256(pth).hexdigest())
        # LaunchSpec still independently needs SETUPTOOLS_USE_DISTUTILS=stdlib.
        self.assertNotIn('executionVerified', result['inventory'])

    def test_existing_output_is_not_an_overwrite_authorization(self):
        output = self.kwargs['inventory_path']
        output.symlink_to(self.target)
        with self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)
        self.assertTrue(output.is_symlink())

    def test_error_does_not_reveal_private_path(self):
        arguments = {**self.kwargs, 'interpreter_target': self.root / 'private-missing-interpreter'}
        with self.assertRaisesRegex(ValueError, '^RESEARCH_BOOTSTRAP_INVENTORY_INVALID$'):
            module.build_inventory(**arguments)

    def test_versions_are_static_and_explicit_mismatch_denied(self):
        with self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs, package_versions={'tiktoken': 'wrong'})
        (self.site / 'torch' / 'version.py').write_text("__version__='2.9.1+cu128'\ncuda='13.0'\n")
        with self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)

    def test_duplicate_metadata_and_cfg_fields_denied(self):
        cfg = self.venv / 'pyvenv.cfg'; original = cfg.read_bytes()
        cfg.write_bytes(original + b'UV=0.11.7\n')
        with self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)
        cfg.write_bytes(original)
        metadata = self.site / 'tiktoken-0.12.0.dist-info' / 'METADATA'
        metadata.write_bytes(metadata.read_bytes() + b'Version: 0.12.0\n')
        with self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)

    def test_symlink_and_hardlink_not_adopted(self):
        link = self.site / 'escape.py'; link.symlink_to(self.target)
        with self.assertRaises((ValueError, OSError)):
            module.build_inventory(**self.kwargs)
        link.unlink(); os.link(self.target, link)
        with self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)

    def test_bounds_and_missing_approved_interpreter_deny(self):
        with patch.object(module, 'MAX_FILES', 2), self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)
        with patch.object(module, 'MAX_TOTAL_BYTES', 1), self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)
        arguments = {**self.kwargs, 'approved_interpreter_roots': [self.site]}
        with self.assertRaises(ValueError):
            module.build_inventory(**arguments)

    def test_post_hash_mutation_and_namespace_addition_fail_final_fence(self):
        original_hash = module._hash_file
        changed = False
        def hash_then_change(path, *args, **kwargs):
            nonlocal changed
            result = original_hash(path, *args, **kwargs)
            if str(path).endswith('version.py') and not changed:
                changed = True
                (self.site / 'standalone.py').write_text('# changed after its hash\n')
            return result
        with patch.object(module, '_hash_file', hash_then_change), self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)
        original_tree = module._tree
        calls = 0
        def tree_then_add(*args, **kwargs):
            nonlocal calls
            result = original_tree(*args, **kwargs); calls += 1
            if calls == 2:
                (self.site / 'new.py').write_text('# unexpected late file\n')
            return result
        with patch.object(module, '_tree', tree_then_add), self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)

    def test_startup_bytes_and_output_under_site_rejected(self):
        arguments = deepcopy(self.kwargs); arguments['inventory_path'] = self.site / 'inventory.json'
        with self.assertRaises(ValueError):
            module.build_inventory(**arguments)
        (self.site / '_virtualenv.pth').write_bytes(b'import wrong_startup')
        with self.assertRaises(ValueError):
            module.build_inventory(**self.kwargs)

"""Package data names through static inventory/capture/observer; no package imports."""
from copy import deepcopy
from dataclasses import asdict
import os
import unittest
from typing import Any

from agent_factory import research_bootstrap_inventory as inventory_module
from agent_factory import research_environment_observer as observer_module
from agent_factory.research_interpreter import capture_interpreter_contract
from agent_factory.research_manifest import validate_manifest
import test_research_environment_observer as fixture

ORDINARY = ('setuptools/script (dev).tmpl', 'setuptools/command/launcher manifest.xml',
            'setuptools/_vendor/jaraco/text/Lorem ipsum.txt')
INVALID = ('', '.', '..', '../escape', 'a/../b', './a', 'a/./b', '/absolute', '//absolute',
           'a//b', 'a/', 'a\\b', 'C:/drive', 'package/name:stream', 'a\x00b', 'a\nb',
           'a\tb', 'a\x7fb', 'a\x85b', 'a\u202eb', 'a\ud800b')


class RelativePackagePathTests(unittest.TestCase):
    def test_printable_data_names_are_preserved_exactly(self):
        for value in (*ORDINARY, 'package/café data (v1).txt', 'package/普通数据 [1], sample.txt',
                      'package/%2e%2e literal.txt'):
            with self.subTest(value=value):
                self.assertEqual(observer_module._relative(value), value)

    def test_unsafe_components_and_unicode_controls_are_rejected(self):
        for index, value in enumerate(INVALID):
            with self.subTest(index=index), self.assertRaises(ValueError):
                observer_module._relative(value)


@unittest.skipUnless(os.name == 'posix', 'Descriptor inventory/capture requires POSIX')
class CompletePackagePathJourneyTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ResearchEnvironmentObserverTests()
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        self.case.uv_fixture('uv0117-virtualenv-startup-v1')
        for name, version in (('torch', '2.9.1+cu128'), ('tiktoken', '0.12.0'), ('pyarrow', '21.0.0')):
            self.case.write(self.case.site / (name + '-' + version + '.dist-info') / 'METADATA',
                ('Metadata-Version: 2.1\nName: ' + name + '\nVersion: ' + version + '\n').encode())
        for index, name in enumerate(ORDINARY):
            self.case.write(self.case.site / name, ('inert package data ' + str(index)).encode())
        self.arguments: dict[str, Any] = dict(project_root=self.case.root, venv_root=self.case.venv,
            interpreter_target=self.case.root / 'managed/python',
            interpreter_sha256=self.case.request['launchSpec']['sha256'],
            approved_interpreter_roots=[self.case.root / 'managed'], inventory_path=self.case.root / 'complete.json')

    def complete(self):
        built = inventory_module.build_inventory(**self.arguments)
        first = self.case.input('environment-inventory', 'complete.json', built['inventory'])
        second = self.case.input('environment-kernel', 'complete-kernel.json', built['kernel'])
        observer = observer_module.ResearchEnvironmentObserver(first, second, bounds_profile=inventory_module.PROFILE)
        request = deepcopy(self.case.request)
        environment = request['runtimeConfig']['comparisonManifest']['environment']
        environment['installedInventory'] = {'sha256': first.file.sha256, 'sizeBytes': first.file.size_bytes}
        environment['runtimeKernel'] = {'sha256': second.file.sha256, 'sizeBytes': second.file.size_bytes}
        request['environment'] = environment
        request['runtimeKernel'] = environment['runtimeKernel']
        request['configurationFingerprint'] = observer.configuration_fingerprint
        request['environmentPins'] = [asdict(first), asdict(second), self.case.request['environmentPins'][-1]]
        request['launchSpec']['interpreter_contract'] = capture_interpreter_contract(**built['captureKwargs'])
        return built, observer, request

    def test_ordinary_setuptools_data_roundtrip_is_inventoried_pinned_and_observed(self):
        built, observer, request = self.complete()
        names = {row['path'] for row in built['inventory']['siteFiles']}
        self.assertTrue(set(ORDINARY) <= names)
        capture_names = {str(path.relative_to(self.case.site)) for path in built['captureKwargs']['package_files']}
        self.assertEqual(capture_names, names)
        self.assertEqual(validate_manifest(request['runtimeConfig']['comparisonManifest']),
                         request['runtimeConfig']['comparisonManifest'])
        self.assertEqual(observer(request)['status'], 'VERIFIED')
        self.case.write(self.case.site / ORDINARY[0], b'changed after contract capture')
        self.assertEqual(observer(request)['status'], 'UNKNOWN')

    def test_package_data_symlink_cannot_enter_inventory(self):
        path = self.case.site / ORDINARY[0]
        path.unlink(); path.symlink_to(self.case.root / 'managed/python')
        with self.assertRaises(ValueError): inventory_module.build_inventory(**self.arguments)

    def test_symlink_replacement_after_capture_cannot_be_verified(self):
        _, observer, request = self.complete()
        path = self.case.site / ORDINARY[-1]
        path.unlink(); path.symlink_to(self.case.root / 'managed/python')
        self.assertEqual(observer(request)['status'], 'UNKNOWN')

    def test_control_and_backslash_filenames_are_rejected_by_inventory(self):
        for index, name in enumerate(('bad\\path', 'control\x01.txt', 'bidi\u202e.txt', 'drive:stream')):
            path = self.case.site / name
            self.case.write(path, b'inert')
            try:
                with self.subTest(index=index), self.assertRaises(ValueError):
                    inventory_module.build_inventory(**self.arguments)
            finally: path.unlink()

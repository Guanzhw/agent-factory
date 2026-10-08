"""Sealing tests use synthetic IDs only; they do not prove native custody."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from agent_factory.research_preparation_driver import PreparationDriver, _entrypoint
import hashlib
import py_compile
import sys
from unittest.mock import patch
from agent_factory.process_enforcement import ProcessSpec
import base64
import json
import os


def tokenizer():
    return json.dumps({'schema': 1, 'pat_str': '.', 'mergeable_ranks':
        [[base64.b64encode(bytes([i])).decode(), i] for i in range(256)],
        'special_tokens': {'<|reserved_0|>': 256}}).encode()


@unittest.skipUnless(os.name == 'posix', 'Descriptor-safe preparation requires POSIX')
class PreparationDriverTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); info = self.root.stat()
        self.reserve = Mock()
        self.driver = PreparationDriver(root=self.root, root_identity={'device': info.st_dev, 'inode': info.st_ino},
            tokenizer_json=tokenizer(), reserve=self.reserve, manifest_sha256='b'*64)
        binding = {'ownerId': 'alice', 'taskId': 'task', 'nativeRunId': 'run', 'planId': 'plan',
            'planFingerprint': 'a'*64, 'leaseId': 'lease', 'providerJobId': 'job',
            'variantSha256': self.driver.configuration_fingerprint, 'manifestSha256': 'b'*64}
        self.reserve.return_value = {'binding': binding, 'destination': {'root': '/unused',
            'basename': 'token-bytes.safetensors', 'rootIdentity': {'device': 1, 'inode': 2}}}
        self.record = {'binding': {'id': 'lease', 'ownerId': 'alice', 'localTaskId': 'task', 'nativeRunId': 'run'},
                       'processPin': {'id': 'job', 'identitySha256': 'c'*64}}

    def test_repeated_seal_preserves_exact_original_bytes_and_inode(self):
        first = self.driver(self.record)
        original = {p.name: (p.read_bytes(), p.stat().st_ino) for p in self.root.iterdir()}
        self.assertEqual(self.driver(self.record), first)
        self.assertEqual(original, {p.name: (p.read_bytes(), p.stat().st_ino) for p in self.root.iterdir()})
        self.reserve.assert_called_with('alice', 'lease', disk_bytes=3 * 1024**2)
        self.assertFalse(first['executionVerified'])

    def test_tampered_and_partial_bundle_never_adopted(self):
        (self.root / 'run-config.json').write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.driver(self.record)
        self.assertFalse((self.root / 'prepare.py').exists())

    def test_sealed_config_change_is_rejected_without_overwrite(self):
        self.driver(self.record)
        path = self.root / 'run-config.json'
        path.chmod(0o600)
        path.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.driver(self.record)
        self.assertEqual(path.read_bytes(), b'{}')

    def test_wrong_original_job_denied_before_staging(self):
        record = deepcopy(self.record); record['processPin']['id'] = 'other'
        with self.assertRaises(ValueError):
            self.driver(record)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_source_loader_ignores_unchecked_pyc_and_package_shadow(self):
        package = self.root / 'source'; package.mkdir()
        init = package / '__init__.py'; init.write_bytes(b'')
        source = package / 'research_preparation_harness.py'
        source.write_text("raise RuntimeError('unchecked cache executed')")
        py_compile.compile(str(source), invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        source.write_text('SOURCE_VERIFIED=True\ndef main(path): pass\n')
        shadow = package / 'research_preparation_harness'; shadow.mkdir()
        (shadow / '__init__.py').write_text("raise RuntimeError('package shadow executed')")
        pins = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (init, source)}
        with patch.dict(sys.modules), patch.object(sys, 'meta_path', list(sys.meta_path)), patch.object(sys, 'argv', ['entry', 'unused']):
            for name in list(sys.modules):
                if name == 'agent_factory' or name.startswith('agent_factory.'):
                    del sys.modules[name]
            exec(_entrypoint(package, pins), {})
            self.assertTrue(getattr(sys.modules['agent_factory.research_preparation_harness'], 'SOURCE_VERIFIED'))

    def test_large_input_rejected_before_reservation_or_staging(self):
        with self.assertRaises(ValueError):
            PreparationDriver(root=self.root, root_identity=self.driver.identity,
                tokenizer_json=b' ' * (1024**2 + 1), reserve=self.reserve, manifest_sha256='b'*64)
        self.reserve.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_spec_must_launch_fixed_entry_and_config(self):
        spec = ProcessSpec(str(self.root / 'python'), 'a'*64,
            ('-I', '-B', str(self.root / 'prepare.py'), str(self.root / 'run-config.json')))
        self.driver.validate_spec(spec)
        with self.assertRaises(ValueError):
            self.driver.validate_spec(ProcessSpec(spec.executable, spec.sha256, ('-c', 'pass')))

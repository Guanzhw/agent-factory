"""Sealing tests use synthetic IDs only; they do not prove native custody."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from agent_factory.research_preparation_driver import PreparationDriver
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
        self.reserve.assert_called_with('alice', 'lease', disk_bytes=65536)
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

    def test_spec_must_launch_fixed_entry_and_config(self):
        spec = ProcessSpec(str(self.root / 'python'), 'a'*64,
            ('-I', '-B', str(self.root / 'prepare.py'), str(self.root / 'run-config.json')))
        self.driver.validate_spec(spec)
        with self.assertRaises(ValueError):
            self.driver.validate_spec(ProcessSpec(spec.executable, spec.sha256, ('-c', 'pass')))

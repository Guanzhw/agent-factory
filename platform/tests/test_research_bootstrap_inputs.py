"""Synthetic pins and mocked AST derivation; no upstream/ML code execution."""
import base64
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_factory import research_bootstrap_inputs as bootstrap
from agent_factory import research_profile
from agent_factory.gpu_custody import GpuBinding
from agent_factory.process_enforcement import ResearchProcessLimits
from agent_factory.research_manifest import validate_manifest
from agent_factory.research_staging import FilePin, InputPin, RootIdentity


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@unittest.skipUnless(sys.platform == 'linux', 'Private POSIX file custody')
class BootstrapInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        info = self.root.stat()
        self.root_identity = RootIdentity(info.st_dev, info.st_ino)
        self.source = {name: ('synthetic-' + name).encode() for name in research_profile.SOURCE_SHA256}
        pins = {name: sha(raw) for name, raw in self.source.items()}
        guard = patch.dict(research_profile.SOURCE_SHA256, pins, clear=True)
        guard.start(); self.addCleanup(guard.stop)
        self.derived = {'identities': {key: {'sha256': sha(key.encode()), 'sizeBytes': len(key), 'content': key.encode()}
            for key in ('baseline', 'evaluatorCode', 'evaluatorConfiguration')},
            'adaptationReceipt': {'syntheticTestOnly': True, 'comparableToUpstreamScore': False}}
        mock = patch.object(bootstrap, 'derive_local_identities', return_value=self.derived)
        self.derive = mock.start(); self.addCleanup(mock.stop)
        tokenizer = {'schema': 1, 'pat_str': 'x',
            'mergeable_ranks': [[base64.b64encode(bytes([n])).decode(), n] for n in range(256)],
            'special_tokens': {'<|reserved_0|>': 256}}
        self.write('tokenizer.json', json.dumps(tokenizer).encode())
        self.write('train.parquet', b'controlled train bytes')
        self.write('val.parquet', b'controlled validation bytes')
        token = self.write('tokens.bin', b'synthetic previously verified preparation bytes')
        binding = {key: ('a' * 64 if key.endswith('Sha256') or key == 'planFingerprint' else 'original-' + key)
                   for key in 'ownerId taskId nativeRunId planId planFingerprint leaseId providerJobId variantSha256 manifestSha256'.split()}
        env = tuple(InputPin('environment-' + label, 'environment', str(self.root), self.root_identity,
            self.write(label + '.json', ('synthetic-' + label).encode())) for label in ('inventory', 'kernel', 'lockfile'))
        self.args = {'input_root': self.root, 'tokenizer_basename': 'tokenizer.json',
            'shards': (('train', 'train.parquet'), ('val', 'val.parquet')), 'validation_ids': ('val',),
            'upstream_files': self.source, 'environment_pins': env,
            'gpu_binding': GpuBinding('a' * 64, 'b' * 64), 'limits': ResearchProcessLimits(),
            'token_bytes_pin': {'root': str(self.root), 'rootIdentity': asdict(self.root_identity),
                'basename': token.basename, 'sha256': token.sha256, 'sizeBytes': token.size_bytes, 'binding': binding}}

    def write(self, name, raw):
        path = self.root / name
        path.write_bytes(raw)
        path.chmod(0o600)
        return FilePin(name, sha(raw), len(raw))

    def call(self, **changes):
        return bootstrap.capture_bootstrap_inputs(**(self.args | changes))

    def test_actual_bytes_build_schema2_and_no_native_identity_invention(self):
        value = self.call()
        manifest = validate_manifest(value['comparisonManifest'])
        self.assertEqual(manifest['schema'], 2)
        self.assertEqual(manifest['protocol']['trainingBudgetSeconds'], 300)
        self.assertEqual(manifest['protocol']['totalWallSeconds'], 900)
        self.assertEqual(manifest['device']['identitySha256'], self.args['gpu_binding'].identity_key)
        self.assertEqual(manifest['dataset']['shards'][0]['sha256'], sha(b'controlled train bytes'))
        sample = {'schema': 1, 'shards': manifest['dataset']['shards'], 'validationShardIds': ['val']}
        self.assertEqual(manifest['dataset']['sampleSetSha256'], bootstrap._digest(sample))
        self.assertEqual(set(value['operatorInputs']), {'inputRoot', 'inputRootIdentity', 'tokenizer', 'tokenBytes', 'dataset', 'outputCheckpoint'})
        self.assertEqual(value['tokenBytesPreparationBinding'], self.args['token_bytes_pin']['binding'])
        self.assertEqual(value['operatorInputs']['tokenBytes'], self.args['token_bytes_pin'])
        self.assertIsNot(value['operatorInputs']['tokenBytes']['binding'], self.args['token_bytes_pin']['binding'])
        self.assertFalse(value['executionVerified'])
        self.assertFalse(value['scientificConclusionVerified'])
        self.derive.assert_called_once_with(self.source, self.source, microbatch=1)

    def test_order_is_part_of_sample_identity(self):
        original = self.call()['comparisonManifest']['dataset']['sampleSetSha256']
        self.assertNotEqual(self.call(shards=tuple(reversed(self.args['shards'])))['comparisonManifest']['dataset']['sampleSetSha256'], original)

    def test_source_mismatch_never_derives(self):
        with self.assertRaisesRegex(ValueError, '^' + bootstrap.ERROR + '$'):
            self.call(upstream_files=self.source | {'train.py': b'changed'})
        self.derive.assert_not_called()

    def test_bad_tokenizer_and_modified_preparation_bytes_rejected(self):
        self.write('tokenizer.json', b'{"schema":1,"schema":1}')
        with self.assertRaises(ValueError):
            self.call()
        self.derive.assert_not_called()

    def test_preparation_and_environment_pin_mismatch(self):
        for name in ('tokens.bin', 'kernel.json'):
            original = (self.root / name).read_bytes()
            self.write(name, b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.call()
            self.write(name, original)

    def test_traversal_symlink_hardlink_and_public_mode_deny(self):
        with self.assertRaises(ValueError):
            self.call(tokenizer_basename='../tokenizer.json')
        target = self.root / 'train.parquet'
        target.chmod(0o644)
        with self.assertRaises(ValueError):
            self.call()
        target.chmod(0o600)
        os.link(target, self.root / 'alias')
        with self.assertRaises(ValueError):
            self.call()
        (self.root / 'alias').unlink()
        target.unlink(); target.symlink_to('val.parquet')
        with self.assertRaises(ValueError):
            self.call()

    def test_duplicate_split_bytes_and_invalid_wall_rejected(self):
        for changes in ({'validation_ids': ('val', 'val')},
                        {'shards': (('train', 'train.parquet'), ('val', 'train.parquet'))},
                        {'limits': ResearchProcessLimits(wall_seconds=300)},
                        {'microbatch': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call(**changes)
        self.write('val.parquet', (self.root / 'train.parquet').read_bytes())
        with self.assertRaises(ValueError):
            self.call()

    def test_budgets_enforced_before_derive(self):
        for name in ('MAX_FILE_BYTES', 'MAX_TOTAL_BYTES', 'MAX_TOKENIZER_BYTES'):
            with self.subTest(name=name), patch.object(bootstrap, name, 1), self.assertRaises(ValueError):
                self.call()
        self.derive.assert_not_called()

    def test_final_multi_file_fence_rejects_mutation_during_derivation(self):
        def mutate(*args, **kwargs):
            self.write('train.parquet', b'changed after capture')
            return self.derived
        self.derive.side_effect = mutate
        with self.assertRaisesRegex(ValueError, '^' + bootstrap.ERROR + '$'):
            self.call()


if __name__ == '__main__':
    unittest.main()

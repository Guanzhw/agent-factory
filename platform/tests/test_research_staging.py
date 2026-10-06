"""Synthetic bytes only: no generated imports, Torch, subprocess or network."""
from dataclasses import replace, FrozenInstanceError
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_factory.research_staging import (
    FilePin, InputPin, ProgramDescriptor, RootIdentity, PROGRAM_FILES, SEAL,
    descriptor_bytes, pin_bytes, stage_own_bundle, verify_staged_program,
)


class StagingContractTests(unittest.TestCase):
    def test_pins_reject_bool_bounds_paths_hashes(self):
        for name in ('../escape', '/absolute', 'nested/file', '.', '..', SEAL):
            with self.subTest(name=name), self.assertRaises(ValueError):
                FilePin(name, 'a' * 64, 10)
        for size in (True, 0, -1, 2**31 + 1):
            with self.assertRaises(ValueError):
                FilePin('data', 'a' * 64, size)
        with self.assertRaises(ValueError):
            RootIdentity(True, 1)
        with self.assertRaises(ValueError):
            FilePin('data', 'A' * 64, 1)

    def test_immutable_pins(self):
        pin = pin_bytes('data', b'example')
        with self.assertRaises(FrozenInstanceError):
            pin.basename = 'other'  # type: ignore[misc]


@unittest.skipUnless(os.name == 'posix', 'Private descriptor-relative POSIX custody contract')
class StagingFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.root, self.inputs = self.parent / 'program', self.parent / 'inputs'
        self.root.mkdir(mode=0o700)
        self.inputs.mkdir(mode=0o700)
        self.files = {name: b'# synthetic; never imported\n' for name in PROGRAM_FILES}
        self.files['run-config.json'] = b'{"schema":1}'
        data = self.inputs / 'data.bin'
        data.write_bytes(b'synthetic source data')
        data.chmod(0o600)
        self.input = InputPin('training-shard', 'data', str(self.inputs), self.identity(self.inputs),
                              pin_bytes('data.bin', data.read_bytes()))
        self.descriptor = ProgramDescriptor('train_baseline.py', self.pins(), 'a' * 64,
            'b' * 64, self.identity(self.root), (self.input,))

    @staticmethod
    def identity(path):
        info = path.stat()
        return RootIdentity(info.st_dev, info.st_ino)

    def pins(self):
        return tuple(pin_bytes(name, raw) for name, raw in sorted(self.files.items()))

    def stage(self, descriptor=None, guard=lambda: None):
        return stage_own_bundle(self.root, self.files, guard, descriptor=descriptor or self.descriptor)

    def test_sealed_roundtrip_all_inputs_rehashed(self):
        calls = []
        result = self.stage(guard=lambda: calls.append(True))
        self.assertEqual(len(calls), 7)
        self.assertFalse(result['executionVerified'])
        self.assertEqual(result, verify_staged_program(self.root, self.descriptor))
        self.assertEqual((self.root / SEAL).read_bytes(), descriptor_bytes(self.descriptor))
        (self.inputs / 'data.bin').write_bytes(b'changed input data!!!')
        with self.assertRaisesRegex(ValueError, '^RESEARCH_STAGING_INVALID$'):
            verify_staged_program(self.root, self.descriptor)

    def test_root_symlink_or_identity_replacement_rejected(self):
        link = self.parent / 'alias'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            stage_own_bundle(link, self.files, lambda: None, descriptor=self.descriptor)
        self.root.rename(self.parent / 'old-program')
        self.root.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            self.stage()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_no_adoption_of_partial_stage_after_authority_loss(self):
        count = 0
        def guard():
            nonlocal count
            count += 1
            if count == 3:
                raise ValueError('synthetic authority ended')
        with self.assertRaises(ValueError):
            self.stage(guard=guard)
        self.assertEqual(len(list(self.root.iterdir())), 2)
        self.assertFalse((self.root / SEAL).exists())
        with self.assertRaises(ValueError):
            self.stage()
        with self.assertRaises(ValueError):
            verify_staged_program(self.root, self.descriptor)

    def test_program_tampering_extra_file_and_descriptor_mismatch(self):
        self.stage()
        with self.assertRaises(ValueError):
            verify_staged_program(self.root, replace(self.descriptor, variant_sha256='c' * 64))
        extra = self.root / 'unexpected'
        extra.write_bytes(b'extra')
        with self.assertRaises(ValueError):
            verify_staged_program(self.root, self.descriptor)
        extra.unlink()
        (self.root / 'train_baseline.py').write_bytes(b'modified')
        with self.assertRaises(ValueError):
            verify_staged_program(self.root, self.descriptor)

    def test_input_hardlink_symlink_and_permissions_fail_closed(self):
        data = self.inputs / 'data.bin'
        hard = self.inputs / 'hard'
        os.link(data, hard)
        with self.assertRaises(ValueError):
            self.stage()
        self.assertFalse((self.root / SEAL).exists())
        # Partial bytes are retained and never silently recycled by the stager.
        for path in self.root.iterdir():
            path.unlink()
        hard.unlink()
        data.chmod(0o644)
        with self.assertRaises(ValueError):
            self.stage()
        for path in self.root.iterdir():
            path.unlink()
        data.chmod(0o600)
        data.rename(self.inputs / 'original')
        data.symlink_to('original')
        with self.assertRaises(ValueError):
            self.stage()

    def test_safe_json_rejects_duplicate_keys_nonfinite_and_not_object(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'[]'):
            self.files['run-config.json'] = raw
            descriptor = replace(self.descriptor, generated=self.pins())
            with self.assertRaises(ValueError):
                self.stage(descriptor)
            self.assertEqual(list(self.root.iterdir()), [])
        self.files['run-config.json'] = b'{}'
        token = self.inputs / 'tokenizer.json'
        token.write_bytes(b'{"vocab":{},"vocab":{}}')
        token.chmod(0o600)
        pin = InputPin('tokenizer', 'tokenizer', str(self.inputs), self.identity(self.inputs),
                       pin_bytes(token.name, token.read_bytes()))
        descriptor = replace(self.descriptor, generated=self.pins(), inputs=(self.input, pin))
        with self.assertRaises(ValueError):
            self.stage(descriptor)
        self.assertFalse((self.root / SEAL).exists())

    def test_eval_requires_original_checkpoint_identity_and_contract(self):
        checkpoint = replace(self.input, label='checkpoint', kind='checkpoint')
        with self.assertRaises(ValueError):
            replace(self.descriptor, entrypoint='evaluate.py')
        with self.assertRaises(ValueError):
            replace(self.descriptor, inputs=(checkpoint,))
        descriptor = replace(self.descriptor, entrypoint='evaluate.py', inputs=(checkpoint,),
            checkpoint_artifact_id='original-artifact', evaluation_contract_sha256='e' * 64)
        result = self.stage(descriptor)
        self.assertFalse(result['executionVerified'])
        with self.assertRaises(ValueError):
            verify_staged_program(self.root, replace(descriptor, checkpoint_artifact_id='another-artifact'))

    def test_symlinked_ancestor_and_async_guard_rejected(self):
        alias = self.parent / 'linked-inputs'
        alias.symlink_to(self.inputs, target_is_directory=True)
        bad = replace(self.input, root=str(alias))
        with self.assertRaises(ValueError):
            self.stage(replace(self.descriptor, inputs=(bad,)))
        for path in self.root.iterdir():
            path.unlink()
        async def async_guard():
            return None
        with self.assertRaises(ValueError):
            self.stage(guard=async_guard)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

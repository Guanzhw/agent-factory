"""Mock tensor bytes and owned small POSIX files; no tensors loaded or executed."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.research_checkpoint import (MAX_BYTES, MAX_HEADER_BYTES, checkpoint_binding,
    open_verified_checkpoint, validate_header, write_checkpoint)


def binding():
    return {'ownerId': '研究者@example.test', 'taskId': 'task-1', 'nativeRunId': 'run-1',
        'planId': 'plan-1', 'planFingerprint': 'a' * 64, 'leaseId': 'lease-1',
        'providerJobId': 'provider-1', 'variantSha256': 'b' * 64, 'manifestSha256': 'c' * 64}


def tensors():
    return {'weight': {'dtype': 'F32', 'shape': [2], 'data_offsets': [0, 8]}}


def header(entries=None):
    return json.dumps({'__metadata__': {'factory.' + k: v for k, v in binding().items()},
        **(entries if entries is not None else tensors())}, separators=(',', ':')).encode()


class CheckpointFormatTests(unittest.TestCase):
    def test_strict_format_byte_geometry_and_original_binding(self):
        self.assertEqual(validate_header(header(), 8, binding()), tensors())
        value = binding(); value['variantSha256'] = 'd' * 64
        with self.assertRaises(ValueError):
            validate_header(header(), 8, value)
        changed = checkpoint_binding(binding()); changed['ownerId'] = 'other'
        self.assertEqual(checkpoint_binding(binding())['ownerId'], '研究者@example.test')
        for field in binding():
            value = binding(); del value[field]
            with self.assertRaises(ValueError):
                checkpoint_binding(value)

    def test_duplicates_invalid_dtypes_shapes_offsets_and_header_budget(self):
        malformed = [header().replace(b'"dtype":"F32"', b'"dtype":"F32","dtype":"F32"'),
            b'[]', b'\xff', b' ' + header(), header() + b'junk', b'{' * (MAX_HEADER_BYTES + 1)]
        for change in ({'dtype': 'PICKLE'}, {'dtype': 'F4'}, {'shape': [True]}, {'shape': [-1]},
                {'shape': [MAX_BYTES, MAX_BYTES]}, {'shape': [1] * 17}, {'data_offsets': [0, 7]},
                {'data_offsets': [1, 9]}, {'extra': True}):
            entry = tensors(); entry['weight'].update(change); malformed.append(header(entry))
        for raw in malformed:
            with self.assertRaisesRegex(ValueError, '^RESEARCH_CHECKPOINT_INVALID$'):
                validate_header(raw, 8, binding())
        overlap = tensors(); overlap['other'] = deepcopy(overlap['weight'])
        with self.assertRaises(ValueError):
            validate_header(header(overlap), 8, binding())
        with self.assertRaises(ValueError):
            validate_header(header(), 9, binding())

    def test_scalars_empty_tensors_and_explicit_subset(self):
        values = {'empty': {'dtype': 'BF16', 'shape': [0], 'data_offsets': [0, 0]},
            'scalar': {'dtype': 'BOOL', 'shape': [], 'data_offsets': [0, 1]}}
        self.assertEqual(validate_header(header(values), 1, binding()), values)
        self.assertEqual(MAX_BYTES, 2 * 1024**3)
        for owner in ('\x00bad', 'bad\n', 'bad\x7f', ''):
            value = binding(); value['ownerId'] = owner
            with self.assertRaises(ValueError):
                checkpoint_binding(value)


_POSIX = os.name == 'posix' and all(type(getattr(os, key, None)) is int and getattr(os, key, 0) > 0
    for key in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'))


@unittest.skipUnless(_POSIX, 'Requires explicit POSIX nofollow/private-file semantics')
class CheckpointFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='checkpoint-owned-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        info = self.root.stat()
        self.root_identity = {'device': info.st_dev, 'inode': info.st_ino}

    def produce(self, **changes):
        values = {'root_identity': self.root_identity, 'binding': binding(), 'max_bytes': 4096,
            'before_effect': lambda: None, **changes}
        return write_checkpoint(self.root, 'model.safetensors', tensors(), [b'\0' * 4, b'\0' * 4], **values)

    def opening(self, **changes):
        values = {'root_identity': self.root_identity, 'binding': binding(), 'max_bytes': 4096, **changes}
        return open_verified_checkpoint(self.root, 'model.safetensors', **values)

    def test_atomic_producer_roundtrip_stream_reset_and_no_overwrite(self):
        receipt = self.produce()
        raw = (self.root / 'model.safetensors').read_bytes()
        self.assertEqual(receipt['identity'], {'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)})
        self.assertFalse(receipt['executionVerified'])
        self.assertEqual((self.root / 'model.safetensors').stat().st_mode & 0o777, 0o600)
        with self.opening() as checked:
            chunks = []
            while chunk := checked.read_chunk(7):
                chunks.append(chunk)
            self.assertEqual(b''.join(chunks), raw)
            checked.reset(); self.assertEqual(checked.read_chunk(8), raw[:8])
            self.assertEqual(checked.provenance, binding())
            self.assertEqual(checked.tensors, tensors())
        with self.assertRaises(ValueError):
            checked.read_chunk()
        with self.assertRaises(ValueError):
            self.produce()
        self.assertEqual((self.root / 'model.safetensors').read_bytes(), raw)

    def test_symlink_hardlink_private_mode_and_root_identity_refused(self):
        self.produce()
        path = self.root / 'model.safetensors'
        alternate = self.root / 'original'
        path.rename(alternate); path.symlink_to(alternate)
        with self.assertRaises(ValueError), self.opening():
            pass
        path.unlink(); os.link(alternate, path)
        with self.assertRaises(ValueError), self.opening():
            pass
        alternate.unlink(); path.chmod(0o644)
        with self.assertRaises(ValueError), self.opening():
            pass
        path.chmod(0o600)
        with self.assertRaises(ValueError), self.opening(root_identity={'device': self.root_identity['device'], 'inode': 0}):
            pass
        linked_root = self.root / 'linked'; linked_root.symlink_to(self.root)
        with self.assertRaises(ValueError), open_verified_checkpoint(linked_root, 'model.safetensors',
                self.root_identity, binding(), 4096):
            pass
        with self.assertRaises(ValueError), open_verified_checkpoint(self.root, '../model.safetensors',
                self.root_identity, binding(), 4096):
            pass

    def test_replacement_and_mutation_after_verification_are_not_consumed(self):
        self.produce()
        path = self.root / 'model.safetensors'
        with self.assertRaises(ValueError), self.opening() as checked:
            path.rename(self.root / 'old')
            path.write_bytes((self.root / 'old').read_bytes()); path.chmod(0o600)
            checked.read_chunk()
        with self.assertRaises(ValueError), self.opening() as checked:
            with path.open('ab') as writer:
                writer.write(b'changed')
            checked.read_chunk()

    def test_mutation_during_hash_and_oversize_prefix_fail_closed(self):
        self.produce()
        path = self.root / 'model.safetensors'
        real_read, mutated = os.read, False
        def changed(fd, size):
            nonlocal mutated
            value = real_read(fd, size)
            if size == 8 and not mutated:
                mutated = True
                with path.open('ab') as writer:
                    writer.write(b'x')
            return value
        with patch('agent_factory.research_checkpoint.os.read', side_effect=changed):
            with self.assertRaises(ValueError), self.opening():
                pass
        path.write_bytes(struct.pack('<Q', MAX_HEADER_BYTES + 1) + b'{}')
        with self.assertRaises(ValueError), self.opening():
            pass
        with self.assertRaises(ValueError), self.opening(max_bytes=MAX_BYTES + 1):
            pass

    def test_authority_failure_keeps_original_exception_and_partial_stage(self):
        denied = PermissionError('Synthetic authority boundary')
        calls = 0
        def authority():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise denied
        with self.assertRaises(PermissionError) as error:
            self.produce(before_effect=authority)
        self.assertIs(error.exception, denied)
        self.assertFalse((self.root / 'model.safetensors').exists())
        self.assertEqual(len(list(self.root.glob('checkpoint-stage-*'))), 1)
        with self.assertRaises(ValueError):
            self.produce(max_bytes=32)

    def test_lost_publication_ack_retains_final_custody_without_replacement(self):
        real_sync = os.fsync
        count = 0
        def lost(fd):
            nonlocal count
            count += 1
            real_sync(fd)
            if count == 2:
                raise OSError('Synthetic directory persistence acknowledgement lost')
        with patch('agent_factory.research_checkpoint.os.fsync', side_effect=lost):
            with self.assertRaises(ValueError):
                self.produce()
        with self.opening() as checkpoint:
            original = checkpoint.identity
        with self.assertRaises(ValueError):
            self.produce()
        with self.opening() as checkpoint:
            self.assertEqual(checkpoint.identity, original)

    def test_link_publication_crash_gap_and_nonregular_file_fail_closed(self):
        with patch('agent_factory.research_checkpoint.os.unlink', side_effect=OSError('Synthetic crash gap')):
            with self.assertRaises(ValueError):
                self.produce()
        self.assertEqual((self.root / 'model.safetensors').stat().st_nlink, 2)
        with self.assertRaises(ValueError), self.opening():
            pass
        for path in self.root.iterdir():
            path.unlink()
        getattr(os, 'mkfifo')(self.root / 'model.safetensors', 0o600)
        with self.assertRaises(ValueError), self.opening():
            pass

    def test_directory_replacement_while_streaming_is_rejected(self):
        self.produce()
        original = self.root.with_name(self.root.name + '-original')
        try:
            with self.assertRaises(ValueError), self.opening() as checked:
                self.root.rename(original)
                self.root.mkdir(mode=0o700)
                checked.read_chunk()
        finally:
            if original.exists():
                self.root.rmdir()
                original.rename(self.root)

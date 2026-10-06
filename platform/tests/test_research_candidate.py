"""Synthetic byte-only candidate validation; never import or execute a candidate."""
import hashlib
import json
import unittest
from unittest.mock import patch

from agent_factory import research_candidate as subject


def baseline():
    return {name: ('synthetic ' + name).encode() for name in subject.REQUIRED_FILES}


class ResearchCandidateTests(unittest.TestCase):
    def invalid(self, original, candidate):
        with self.assertRaisesRegex(ValueError, '^RESEARCH_CANDIDATE_INVALID$'):
            subject.validate_candidate_files(original, candidate)

    def test_actual_bytes_sorted_manifests_and_explicit_offline_claim(self):
        original = baseline()
        original['data/frozen.bin'] = b'\x00\xff'
        candidate = {**original, 'train.py': b'new synthetic candidate'}
        receipt = subject.validate_candidate_files(original, candidate)
        self.assertEqual(receipt['changedFiles'], ['train.py'])
        self.assertEqual(receipt['allowedChanges'], ['train.py'])
        self.assertFalse(receipt['executionVerified'])
        self.assertFalse(receipt['scientificConclusionVerified'])
        for prefix, files in (('baseline', original), ('candidate', candidate)):
            manifest = receipt[prefix + 'Manifest']
            self.assertEqual([row['path'] for row in manifest], sorted(files))
            for row in manifest:
                self.assertEqual(row['sha256'], hashlib.sha256(files[row['path']]).hexdigest())
                self.assertEqual(row['sizeBytes'], len(files[row['path']]))
            raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
            self.assertEqual(receipt[prefix + 'ManifestSha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(receipt['baselineManifestSha256'], receipt['candidateManifestSha256'])
        self.assertEqual(receipt, subject.validate_candidate_files(dict(reversed(list(original.items()))), candidate))
        original['train.py'] = b'later mutation'
        self.assertEqual(receipt['baselineManifest'], subject.validate_candidate_files(baseline() | {'data/frozen.bin': b'\x00\xff'}, candidate)['baselineManifest'])

    def test_unchanged_candidate_allowed_and_every_other_file_protected(self):
        original = baseline() | {'extra.bin': b'protected'}
        self.assertEqual(subject.validate_candidate_files(original, original)['changedFiles'], [])
        for name in original:
            if name != 'train.py':
                with self.subTest(name=name):
                    self.invalid(original, original | {name: b'modified'})
        self.invalid(original, original | {'added.py': b''})
        self.invalid(original, {k: v for k, v in original.items() if k != 'extra.bin'})
        for required in subject.REQUIRED_FILES:
            missing = {k: v for k, v in original.items() if k != required}
            self.invalid(missing, missing)

    def test_noncanonical_paths_aliases_and_file_directory_conflicts(self):
        for path in ('', '.', '..', '/absolute', 'a//b', './train.py', 'a/../b', 'a/./b', 'a/',
                     'a\\b', 'C:/file', 'a\x00b', 'a b', 'a.', 'TRAIN.PY', 'train.py/child',
                     'a' * 101, 'x/' * 121 + 'z', 'con', 'NUL.txt', 'a/COM1', 'é.py'):
            with self.subTest(path=path):
                files = baseline() | {path: b''}
                self.invalid(files, files)

    def test_exact_types_only(self):
        class ByteSubclass(bytes):
            pass
        class DictSubclass(dict):
            pass
        for value in (None, True, 1, 'text', bytearray(b'x'), memoryview(b'x'), ByteSubclass(b'x')):
            self.invalid(baseline(), baseline() | {'train.py': value})
        for value in (None, True, [], DictSubclass(baseline())):
            self.invalid(value, baseline())
            self.invalid(baseline(), value)
        self.invalid(baseline() | {True: b''}, baseline())

    def test_file_count_per_file_and_aggregate_bounds(self):
        exact = baseline() | {f'extra/{i}': b'' for i in range(subject.MAX_FILES - len(baseline()))}
        subject.validate_candidate_files(exact, exact)
        self.invalid(exact | {'one-more': b''}, exact | {'one-more': b''})
        with patch.object(subject, 'MAX_FILE_BYTES', 32), patch.object(subject, 'MAX_TOTAL_BYTES', 160):
            exact = {name: b'x' * 32 for name in subject.REQUIRED_FILES}
            subject.validate_candidate_files(exact, exact)
            self.invalid(exact, exact | {'train.py': b'x' * 33})
            over = exact | {'extra': b'x'}
            self.invalid(over, over)


if __name__ == '__main__':
    unittest.main()

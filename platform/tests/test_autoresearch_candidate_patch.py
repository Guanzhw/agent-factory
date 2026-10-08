"""Literal byte edits only; no imports/execution of generated upstream code."""
import ast
import unittest
from unittest.mock import patch

from agent_factory import autoresearch_candidate_patch as module
from agent_factory import research_training_adapter as adapter
from test_research_training_adapter import synthetic_files


class CandidatePatchTests(unittest.TestCase):
    def test_selected_literal_only_preserves_unicode_comments_and_crlf(self):
        raw = synthetic_files()['train.py'].replace(b'\nEMBEDDING_LR = 0.5',
            '\nmarker = "中文"; EMBEDDING_LR = 0.5 # keep literal 0.5'.encode()).replace(b'\n', b'\r\n')
        result = module.build_candidate(raw, {'EMBEDDING_LR': .25})
        self.assertEqual(result.encode(), raw.replace(b'; EMBEDDING_LR = 0.5', b'; EMBEDDING_LR = 0.25'))
        ast.parse(result)

    def test_beta_array_and_multifield_changes_pass_existing_full_adapter(self):
        files = synthetic_files()
        changes = {'EMBEDDING_LR': .25, 'ADAM_BETAS': [.8, .99], 'TOTAL_BATCH_SIZE': 524288}
        candidate = module.build_candidate(files['train.py'], changes)
        self.assertIn('ADAM_BETAS = (0.8, 0.99)', candidate)
        self.assertIn('TOTAL_BATCH_SIZE = 524288', candidate)
        with patch.object(adapter, 'verify_upstream_source', return_value={'commit': 'synthetic-only', 'sourceSha256': {}}):
            result = adapter.build_training_bundle(files, {**files, 'train.py': candidate.encode()}, microbatch=1)
        self.assertFalse(result['receipt']['executionVerified'])
        self.assertEqual(changes['ADAM_BETAS'], [.8, .99])

    def test_invalid_fields_values_and_expressions_are_rejected(self):
        raw = synthetic_files()['train.py']
        bad = [{}, {'DEPTH': 9}, {'../x': 1}, {'EMBEDDING_LR': True}, {'EMBEDDING_LR': '0.25'},
            {'EMBEDDING_LR': float('nan')}, {'EMBEDDING_LR': float('inf')}, {'EMBEDDING_LR': 10**1000},
            {'EMBEDDING_LR': -1}, {'EMBEDDING_LR': 11}, {'WARMUP_RATIO': 1.1},
            {'TOTAL_BATCH_SIZE': 2049}, {'DEVICE_BATCH_SIZE': 3}, {'ADAM_BETAS': [True, .9]},
            {'ADAM_BETAS': [.9]}, {'ADAM_BETAS': [.9, 1]}, {'ADAM_BETAS': (.8, .9)},
            {'EMBEDDING_LR': '__import__("arbitrary")'}]
        for change in bad:
            with self.subTest(index=bad.index(change)), self.assertRaises(ValueError):
                module.build_candidate(raw, change)

    def test_noop_and_operator_overridden_microbatch_only_changes_are_rejected(self):
        raw = synthetic_files()['train.py']
        for changes in ({'EMBEDDING_LR': .5}, {'TOTAL_BATCH_SIZE': 524288},
                        {'DEVICE_BATCH_SIZE': 1}, {'DEVICE_BATCH_SIZE': 128},
                        {'DEVICE_BATCH_SIZE': 1, 'ADAM_BETAS': [.8, .95]}):
            with self.assertRaises(ValueError): module.build_candidate(raw, changes, microbatch=1)
        result = module.build_candidate(raw, {'DEVICE_BATCH_SIZE': 1, 'EMBEDDING_LR': .25}, microbatch=1)
        self.assertIn('DEVICE_BATCH_SIZE = 1', result)
        with self.assertRaises(ValueError): module.build_candidate(b'x' * (4 * 1024**2 + 1), {'EMBEDDING_LR': .25})

    def test_duplicate_missing_parameter_invalid_utf8_and_microbatch_rejected(self):
        raw = synthetic_files()['train.py']
        for bad in (raw + b'\nEMBEDDING_LR = 0.5\n', raw.replace(b'EMBEDDING_LR = 0.5\n', b''), b'\xff'):
            with self.assertRaises(ValueError): module.build_candidate(bad, {'EMBEDDING_LR': .25})
        for microbatch in (True, 0, 3, 256):
            with self.assertRaises(ValueError): module.build_candidate(raw, {'EMBEDDING_LR': .25}, microbatch=microbatch)

    def test_context_has_exact_eleven_parameters_and_no_full_source_or_selection(self):
        result = module.parameter_context(synthetic_files()['train.py'])
        self.assertEqual(set(result['currentParameters']), adapter.ALLOWED_PARAMETERS)
        self.assertEqual(len(result['allowedParameters']), 11)
        self.assertIsInstance(result['currentParameters']['ADAM_BETAS'], list)
        self.assertNotIn('trainPy', result)
        self.assertIn('changes', result['candidateFormat'])

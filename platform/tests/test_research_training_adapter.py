"""Static synthetic source transformations; no upstream or generated execution."""
import ast
from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

from agent_factory import research_training_adapter as adapter


def synthetic_files():
    source = '@dataclass\nclass GPTConfig:\n    pass\n'
    for name in ('norm', 'has_ve', 'apply_rotary_emb'):
        source += f'def {name}(x):\n    return x\n'
    for name in ('CausalSelfAttention', 'MLP', 'Block', 'GPT'):
        source += f'class {name}:\n    pass\n'
    source += '# Optimizer (MuonAdamW, single GPU only)\npolar_express_coeffs = [(1,2,3)]\n'
    for name in ('adamw_step_fused', 'muon_step_fused'):
        source += f'@torch.compile(dynamic=False)\ndef {name}(x):\n    return x\n'
    source += 'class MuonAdamW:\n    pass\n# Hyperparameters (edit these directly, no CLI flags needed)\n'
    for name in sorted(adapter.ALLOWED_PARAMETERS):
        value = '(0.8, 0.95)' if name == 'ADAM_BETAS' else '128' if name == 'DEVICE_BATCH_SIZE' else '2**19' if name == 'TOTAL_BATCH_SIZE' else '0.5'
        source += f'{name} = {value}\n'
    source += 'DEPTH = 8\nmodel = fixed_model\n# Final eval\nval_bpb = dangerous_candidate_loss()\n'
    prepare = 'def make_dataloader(*args):\n    return None\n@torch.no_grad()\ndef evaluate_bpb(*args):\n    return None\n'
    return {'train.py': source.encode(), 'prepare.py': prepare.encode(), 'README.md': b'public fixture',
            'program.md': b'fixed', 'pyproject.toml': b'fixed', 'uv.lock': b'fixed'}


class ResearchTrainingAdapterTests(unittest.TestCase):
    def setUp(self):
        self.files = synthetic_files()
        self.guard = patch.object(adapter, 'verify_upstream_source', return_value={
            'commit': 'synthetic-test-only', 'sourceSha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in self.files.items()}})
        self.verify = self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_generated_bundle_is_parseable_pinned_and_explicitly_local(self):
        candidate = deepcopy(self.files)
        candidate['train.py'] = candidate['train.py'].replace(b'EMBEDDING_LR = 0.5', b'EMBEDDING_LR = 0.25')
        result = adapter.build_training_bundle(self.files, candidate)
        self.verify.assert_called_once_with(self.files)
        self.assertEqual(set(result['generatedFiles']), {'trusted_architecture.py', 'trusted_data.py',
            'train_baseline.py', 'train_candidate.py', 'evaluate.py'})
        for name, raw in result['generatedFiles'].items():
            ast.parse(raw)
            self.assertEqual(result['receipt']['generatedSha256'][name], hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(result['generatedFiles']['train_candidate.py'], result['generatedFiles']['train_baseline.py'])
        self.assertIn(b'DEVICE_BATCH_SIZE = 8', result['generatedFiles']['train_candidate.py'])
        self.assertNotIn(b'dangerous_candidate_loss', result['generatedFiles']['train_candidate.py'])
        self.assertNotIn(b'get_kernel', result['generatedFiles']['trusted_architecture.py'])
        self.assertNotIn(b'train_candidate', result['generatedFiles']['evaluate.py'])
        self.assertFalse(result['receipt']['executionVerified'])
        self.assertFalse(result['receipt']['comparableToUpstreamScore'])

    def test_architecture_import_optimizer_body_and_loop_edits_are_rejected(self):
        for before, after in ((b'DEPTH = 8', b'DEPTH = 9'), (b'return x', b'return 0'),
                (b'model = fixed_model', b'import evil\nmodel = fixed_model'),
                (b'polar_express_coeffs = [(1,2,3)]', b'polar_express_coeffs = [(0,0,0)]')):
            candidate = self.files | {'train.py': self.files['train.py'].replace(before, after)}
            with self.assertRaises(ValueError):
                adapter.build_training_bundle(self.files, candidate)

    def test_only_bounded_literal_optimization_changes_are_accepted(self):
        for value in (b'True', b'float("nan")', b'__import__("evil")', b'-1', b'11'):
            candidate = self.files | {'train.py': self.files['train.py'].replace(b'EMBEDDING_LR = 0.5', b'EMBEDDING_LR = ' + value)}
            with self.assertRaises(ValueError):
                adapter.build_training_bundle(self.files, candidate)
        for batch in (True, 0, 3, 256):
            with self.assertRaises(ValueError):
                adapter.build_training_bundle(self.files, self.files, microbatch=batch)
        candidate = self.files | {'train.py': self.files['train.py'].replace(b'DEVICE_BATCH_SIZE = 128', b'DEVICE_BATCH_SIZE = 16')}
        with self.assertRaises(ValueError):
            adapter.build_training_bundle(self.files, candidate, microbatch=8)

    def test_changed_protected_file_and_invalid_source_never_generate(self):
        with self.assertRaises(ValueError):
            adapter.build_training_bundle(self.files, self.files | {'prepare.py': b'modified'})
        with self.assertRaises(ValueError):
            adapter.build_training_bundle(self.files, self.files | {'train.py': b'\xff'})
        self.verify.side_effect = ValueError('pinned upstream mismatch')
        with self.assertRaises(ValueError):
            adapter.build_training_bundle(self.files, self.files)


if __name__ == '__main__':
    unittest.main()

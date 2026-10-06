"""Pure synthetic safe tokenizer export; no process, Torch or tiktoken."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from agent_factory.research_preparation_harness import tokenizer_payload, export_token_bytes
from agent_factory.research_checkpoint import open_verified_checkpoint


def tokenizer():
    return json.dumps({'schema': 1, 'pat_str': '.', 'mergeable_ranks':
        [[base64.b64encode(bytes([i])).decode(), i] for i in range(256)],
        'special_tokens': {'<|reserved_0|>': 256}}).encode()


class PreparationHarnessTests(unittest.TestCase):
    def test_utf8_replacement_and_special_semantics(self):
        header, data = tokenizer_payload(tokenizer())
        values = [int.from_bytes(data[i:i+4], 'little') for i in range(0, len(data), 4)]
        self.assertEqual(header['token_bytes']['shape'], [257])
        self.assertEqual(values[:128], [1]*128)
        self.assertEqual(values[128:256], [3]*128)
        self.assertEqual(values[-1], 0)

    def test_large_valid_vocabulary_is_rejected_without_widening_process_limit(self):
        value = json.loads(tokenizer())
        for i in range(256, 8192):
            value['mergeable_ranks'].append([base64.b64encode(b'long' + i.to_bytes(4, 'little')).decode(), i])
        value['special_tokens'] = {'<|reserved_0|>': 8192}
        with self.assertRaisesRegex(ValueError, 'PREPARATION_VOCAB_LIMIT'):
            tokenizer_payload(json.dumps(value).encode())

    def test_no_output_for_changed_input(self):
        with self.assertRaises(ValueError):
            export_token_bytes({'schema': 1, 'tokenizerJson': tokenizer().decode(),
                                'tokenizerSha256': '0'*64, 'reservation': {}})

    @unittest.skipUnless(os.name == 'posix', 'Descriptor-safe preparation requires POSIX')
    def test_real_file_is_bound_i32_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); info = root.stat()
            pin = {'device': info.st_dev, 'inode': info.st_ino}
            binding = {key: 'a'*64 for key in ('planFingerprint', 'manifestSha256', 'variantSha256')}
            binding.update(ownerId='alice', taskId='task', nativeRunId='run', planId='plan', leaseId='lease', providerJobId='job')
            result = export_token_bytes({'schema': 1, 'tokenizerJson': tokenizer().decode(),
                'tokenizerSha256': hashlib.sha256(tokenizer()).hexdigest(),
                'reservation': {'binding': binding, 'destination': {'root': temporary,
                    'rootIdentity': pin, 'basename': 'token-bytes.safetensors'}}})
            with open_verified_checkpoint(root, 'token-bytes.safetensors', pin, binding, 65536) as reader:
                self.assertEqual(reader.identity, result['identity'])
                self.assertEqual(set(reader.tensors), {'token_bytes'})

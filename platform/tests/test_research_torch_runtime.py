"""Pure runtime protocol/mask doubles. No Torch, kernels or GPU execution."""
from contextlib import nullcontext
import json
import builtins
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_factory import research_torch_runtime as module
from test_research_evaluation import example_contract  # pyright: ignore[reportMissingImports]
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_torch_runtime import SDPAAdapter, decode_tokenizer_json, export_tokenizer_json, prepare_tokenizer_export


class Mask:
    def __init__(self, function):
        self.function = function

    def __and__(self, other):
        return Mask(lambda row, column: self.function(row, column) and other.function(row, column))


class Distance:
    def __ge__(self, value):
        return Mask(lambda row, column: row - column >= value)

    def __le__(self, value):
        return Mask(lambda row, column: row - column <= value)


class Positions:
    def __getitem__(self, item):
        return self

    def __sub__(self, other):
        return Distance()


class Tensor:
    ndim = 4
    dtype = 'bf16'
    device = 'synthetic'

    def __init__(self, shape):
        self.shape = shape

    def transpose(self, first, second):
        shape = list(self.shape)
        shape[first], shape[second] = shape[second], shape[first]
        return Tensor(tuple(shape))


class ResearchTorchRuntimeTests(unittest.TestCase):
    def encoding(self):
        return SimpleNamespace(_pat_str='synthetic', _mergeable_ranks={bytes([i]): i for i in range(256)},
            _special_tokens={'<|reserved_0|>': 256}, n_vocab=257,
            decode=lambda ids: '<|reserved_0|>' if ids[0] == 256 else bytes(ids).decode('utf-8', errors='replace'))

    def test_safe_json_preserves_pattern_merge_bytes_ranks_and_specials(self):
        encoding = self.encoding()
        raw = export_tokenizer_json(encoding)
        pattern, ranks, specials = decode_tokenizer_json(raw)
        self.assertEqual(pattern, encoding._pat_str)
        self.assertEqual(ranks, encoding._mergeable_ranks)
        self.assertEqual(specials, encoding._special_tokens)
        assets = prepare_tokenizer_export(encoding)
        self.assertEqual(assets['tokenizerJson'], raw)
        self.assertEqual(assets['tokenBytesHeader']['token_bytes']['shape'], [257])
        self.assertEqual(assets['tokenBytesData'][-4:], b'\0' * 4)
        # Original preparation decodes invalid bytes to U+FFFD (three UTF-8 bytes).
        self.assertEqual(int.from_bytes(assets['tokenBytesData'][128*4:129*4], 'little'), 3)

    def test_json_duplicates_aliases_bad_ranks_and_missing_byte_alphabet_rejected(self):
        raw = export_tokenizer_json(self.encoding())
        with self.assertRaises(ValueError):
            decode_tokenizer_json(raw[:-1] + b',"schema":1}')
        for mutation in ('rank', 'base64', 'alphabet', 'bool'):
            value = json.loads(raw)
            if mutation == 'rank': value['mergeable_ranks'][0][1] = 1
            if mutation == 'base64': value['mergeable_ranks'][0][0] = '**'
            if mutation == 'alphabet': value['mergeable_ranks'] = value['mergeable_ranks'][:1]
            if mutation == 'bool': value['schema'] = True
            with self.assertRaises(ValueError):
                decode_tokenizer_json(json.dumps(value).encode())

    def configuration(self):
        contract = example_contract()
        contract['comparisonManifest']['protocol']['seed'] = 42
        manifest = contract['comparisonManifest']
        training = contract['training']
        binding = {key: training[key] for key in ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256')}
        binding['manifestSha256'] = manifest_fingerprint(manifest)
        root, identity = str(Path.cwd() / 'synthetic-input'), {'device': 1, 'inode': 2}
        return {'schema': 1, 'comparisonManifest': manifest, 'binding': binding,
            'inputRoot': root, 'inputRootIdentity': identity,
            'tokenizer': {'basename': 'tokenizer.json', **manifest['tokenizer']['tokenizer']},
            'tokenBytes': {'root': root, 'basename': 'token-bytes.safetensors', 'rootIdentity': identity,
                'binding': deepcopy(binding), **manifest['tokenizer']['tokenBytes']},
            'dataset': {'shards': [row | {'basename': row['id'] + '.parquet'} for row in manifest['dataset']['shards']],
                'validationShardIds': manifest['dataset']['validationShardIds']},
            'outputCheckpoint': {'root': root, 'basename': 'weights.safetensors', 'rootIdentity': identity},
            'checkpoint': None, 'evaluationContract': None}

    def test_pure_runtime_config_rejects_ignored_initial_checkpoint_and_malformed_pins(self):
        config = self.configuration()
        checked = module.validate_runtime_configuration(config, mode='train', microbatch=8)
        self.assertEqual(checked, config)
        changed = deepcopy(config)
        changed['comparisonManifest']['initialCheckpoint'] = {'sha256': '1' * 64, 'sizeBytes': 1}
        changed['binding']['manifestSha256'] = manifest_fingerprint(changed['comparisonManifest'])
        with self.assertRaises(ValueError):
            module.validate_runtime_configuration(changed, mode='train', microbatch=8)
        for name, replacement in (('checkpoint', {}), ('evaluationContract', {}), ('outputCheckpoint', None),
                                  ('tokenizer', {'basename': '../escape', 'sha256': '0' * 64, 'sizeBytes': 1})):
            with self.assertRaises(ValueError):
                module.validate_runtime_configuration(config | {name: replacement}, mode='train', microbatch=8)
        self.assertIsNot(checked['comparisonManifest'], config['comparisonManifest'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX descriptor custody')
    def test_input_consumption_detects_inplace_mutation_path_and_root_replacement(self):
        for attack in ('inplace', 'path', 'root'):
            with TemporaryDirectory() as temporary:
                root = Path(temporary) / 'root'
                root.mkdir(mode=0o700)
                file = root / 'data.bin'
                file.write_bytes(b'original')
                file.chmod(0o600)
                info = root.stat()
                identity = {'device': info.st_dev, 'inode': info.st_ino}
                pin = {'basename': 'data.bin', 'sha256': hashlib.sha256(b'original').hexdigest(), 'sizeBytes': 8}
                with self.assertRaises(ValueError):
                    with module._input_file(root, identity, pin, 8) as handle:
                        self.assertEqual(handle.read(), b'original')
                        if attack == 'inplace': file.write_bytes(b'modified')
                        elif attack == 'path':
                            file.unlink()
                            file.write_bytes(b'original')
                            file.chmod(0o600)
                        else:
                            root.rename(Path(temporary) / 'old')
                            root.mkdir(mode=0o700)

    @unittest.skipUnless(os.name == 'posix', 'POSIX descriptor custody')
    def test_concurrent_growth_during_hash_is_bounded_and_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / 'data.bin'
            file.write_bytes(b'original')
            file.chmod(0o600)
            info = root.stat()
            pin = {'basename': 'data.bin', 'sha256': hashlib.sha256(b'original').hexdigest(), 'sizeBytes': 8}
            hasher = hashlib.sha256()
            calls = []
            def update(block):
                calls.append(len(block))
                hasher.update(block)
                with file.open('ab') as handle: handle.write(b'growth')
            fake = SimpleNamespace(update=update, hexdigest=hasher.hexdigest)
            with patch.object(module.hashlib, 'sha256', return_value=fake), self.assertRaises(ValueError):
                with module._input_file(root, {'device': info.st_dev, 'inode': info.st_ino}, pin, 8):
                    self.fail('Growing input accepted')
            self.assertEqual(calls, [8])

    def test_independent_evaluator_uses_fixed_logits_and_own_cross_entropy(self):
        class Value:
            shape = (1,)
            dtype = 'f32'
            def reshape(self, *args): return self
            def size(self, *args): return 2
            def __getitem__(self, key): return self
            def __gt__(self, other): return True
            def __mul__(self, other): return self
            def sum(self): return self
            def item(self): return 2.0
            def all(self): return True
        value = Value()
        model = Mock(return_value=value)
        model.to.return_value = model
        model.state_dict.return_value = {'weight': value}
        cross_entropy = Mock(return_value=value)
        torch = SimpleNamespace(no_grad=nullcontext, bfloat16='bf16',
            amp=SimpleNamespace(autocast=lambda **kwargs: nullcontext()), isfinite=lambda _: value,
            nn=SimpleNamespace(functional=SimpleNamespace(cross_entropy=cross_entropy)))
        contract = example_contract()
        training = contract['training']
        binding = contract['evaluatorExecution'] | {'variantSha256': 'f' * 64,
            'manifestSha256': manifest_fingerprint(contract['comparisonManifest'])}
        checkpoint = {'binding': {key: training[key] for key in binding if key != 'manifestSha256'},
            'sha256': training['checkpoint']['sha256'], 'sizeBytes': training['checkpoint']['sizeBytes']}
        checkpoint['binding']['manifestSha256'] = binding['manifestSha256']
        config = {'evaluationContract': contract, 'checkpoint': checkpoint}
        architecture = SimpleNamespace(GPTConfig=lambda **kwargs: kwargs, GPT=lambda _: model)
        data = SimpleNamespace(make_dataloader=lambda *args: iter([(value, value, 0)] * 80))
        previous = dict(module.runtime.__dict__)
        final_input_check = Mock()
        try:
            module.runtime.__dict__.update(torch=torch, config=config, manifest=contract['comparisonManifest'], binding=binding, input_checks=[final_input_check],
                tokenizer_class=lambda: SimpleNamespace(get_vocab_size=lambda: 2), get_token_bytes=lambda **kwargs: value)
            with patch.object(module, 'initialize'), patch.object(module, '_tensors', return_value=iter([('weight', value)])), \
                    patch.object(module.importlib, 'import_module', side_effect=lambda name: {'trusted_architecture': architecture, 'trusted_data': data}[name]) as imports, \
                    patch.object(builtins, 'print') as printed:
                module.evaluate_main(microbatch=128)
            self.assertEqual([call.args[0] for call in imports.call_args_list], ['trusted_architecture', 'trusted_data'])
            self.assertEqual(cross_entropy.call_count, 80)
            final_input_check.assert_called_once()
            self.assertTrue(all(len(call.args) == 1 for call in model.call_args_list))
            self.assertEqual(json.loads(printed.call_args.args[0])['status'], 'completed')
        finally:
            module.runtime.__dict__.clear()
            module.runtime.__dict__.update(previous)

    def test_sdpa_preserves_bthd_gqa_and_inclusive_left_window(self):
        scaled = Mock(side_effect=lambda q, k, v, **kw: q)
        torch = SimpleNamespace(bfloat16='bf16', arange=lambda *args, **kwargs: Positions(),
            nn=SimpleNamespace(functional=SimpleNamespace(scaled_dot_product_attention=scaled)))
        result = SDPAAdapter(torch).flash_attn_func(Tensor((2, 1026, 4, 128)), Tensor((2, 1026, 2, 128)),
            Tensor((2, 1026, 2, 128)), causal=True, window_size=(1024, 0))
        self.assertEqual(result.shape, (2, 1026, 4, 128))
        call = scaled.call_args
        self.assertEqual(call.args[0].shape, (2, 4, 1026, 128))
        self.assertTrue(call.kwargs['enable_gqa'])
        mask = call.kwargs['attn_mask']
        self.assertTrue(mask.function(1024, 0))
        self.assertFalse(mask.function(1025, 0))
        self.assertTrue(mask.function(1025, 1))
        self.assertFalse(mask.function(0, 1))
        self.assertEqual(call.kwargs['dropout_p'], 0.0)
        self.assertFalse(call.kwargs['is_causal'])
        with self.assertRaises(ValueError):
            SDPAAdapter(torch).flash_attn_func(Tensor((1,2,2,4)), Tensor((1,2,2,4)), Tensor((1,2,2,4)), causal=False, window_size=(2,0))


if __name__ == '__main__':
    unittest.main()

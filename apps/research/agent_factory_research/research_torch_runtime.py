"""Explicit operator-launched local runtime. Importing this module loads no ML code.

Generated fixed sources call initialize only after separate process admission.
This is cooperative execution, not hostile-code or network isolation. Tokenizer
JSON reconstructs tiktoken semantics; no pickle/checkpoint Python is imported.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import re
import base64
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any, cast

from .research_checkpoint import open_verified_checkpoint, write_checkpoint, checkpoint_binding
from .research_evaluation import validate_evaluation_contract, evaluation_contract_fingerprint
from .research_manifest import validate_manifest, manifest_fingerprint

runtime = SimpleNamespace()


def _require(condition):
    if not condition:
        raise ValueError('RESEARCH_LOCAL_RUNTIME_INVALID')


def _unique(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _json(raw):
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: _require(False))


def export_tokenizer_json(encoding):
    """Export an already trusted encoding; never reads a pickle or executes source."""
    value = {'schema': 1, 'pat_str': encoding._pat_str,
        'mergeable_ranks': [[base64.b64encode(token).decode('ascii'), rank]
                            for token, rank in sorted(encoding._mergeable_ranks.items(), key=lambda row: row[1])],
        'special_tokens': dict(encoding._special_tokens)}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    decode_tokenizer_json(raw)
    return raw


def decode_tokenizer_json(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= 16 * 1024**2)
    value = _json(raw)
    _require(type(value) is dict and set(value) == {'schema', 'pat_str', 'mergeable_ranks', 'special_tokens'}
             and type(value['schema']) is int and value['schema'] == 1
             and type(value['pat_str']) is str and 0 < len(value['pat_str']) <= 16384)
    rows, specials = value['mergeable_ranks'], value['special_tokens']
    _require(type(rows) is list and 1 <= len(rows) <= 131072 and type(specials) is dict and 1 <= len(specials) <= 256)
    ranks = {}
    for index, row in enumerate(rows):
        _require(type(row) is list and len(row) == 2 and type(row[0]) is str
                 and type(row[1]) is int and row[1] == index)
        try:
            token = base64.b64decode(row[0], validate=True)
        except (ValueError, TypeError):
            raise ValueError('RESEARCH_LOCAL_RUNTIME_INVALID') from None
        _require(0 < len(token) <= 65536 and token not in ranks
                 and base64.b64encode(token).decode('ascii') == row[0])
        ranks[token] = index
    _require(all(type(name) is str and 0 < len(name) <= 256 and type(number) is int
                 for name, number in specials.items())
             and set(specials.values()) == set(range(len(rows), len(rows) + len(specials)))
             and '<|reserved_0|>' in specials)
    _require(all(bytes([byte]) in ranks for byte in range(256)))
    return value['pat_str'], ranks, specials


def prepare_tokenizer_export(encoding):
    """Inert safe-export payloads from a trusted freshly created tiktoken Encoding.

    The operator writes tokenizerJson and feeds tokenBytesHeader/tokenBytesData
    to research_checkpoint.write_checkpoint under the approved artifact binding.
    """
    raw = export_tokenizer_json(encoding)
    _, _, specials = decode_tokenizer_json(raw)
    names = set(specials)
    lengths = []
    for index in range(encoding.n_vocab):
        decoded = encoding.decode([index])
        lengths.append(0 if decoded in names else len(decoded.encode('utf-8')))
    data = b''.join(length.to_bytes(4, 'little', signed=True) for length in lengths)
    return {'tokenizerJson': raw, 'tokenBytesHeader': {'token_bytes': {
        'dtype': 'I32', 'shape': [len(lengths)], 'data_offsets': [0, len(data)]}}, 'tokenBytesData': data}


class SDPAAdapter:
    """Original BTHD API, fixed causal inclusive-left window, no FA kernel loader."""
    def __init__(self, torch_module):
        self.torch = torch_module

    def flash_attn_func(self, q, k, v, *, causal, window_size):
        torch = self.torch
        _require(causal is True and type(window_size) is tuple and len(window_size) == 2
                 and all(type(x) is int for x in window_size) and cast(tuple[int, int], window_size)[0] >= 0 and window_size[1] == 0)
        _require(q.ndim == k.ndim == v.ndim == 4 and q.shape[0:2] == k.shape[0:2] == v.shape[0:2]
                 and k.shape == v.shape and q.shape[-1] == k.shape[-1]
                 and q.shape[2] % k.shape[2] == 0
                 and q.dtype == k.dtype == v.dtype == torch.bfloat16)
        count = q.shape[1]
        positions = torch.arange(count, device=q.device)
        distance = positions[:, None] - positions[None, :]
        mask = (distance >= 0) & (distance <= window_size[0])
        result = torch.nn.functional.scaled_dot_product_attention(q.transpose(1, 2), k.transpose(1, 2),
            v.transpose(1, 2), attn_mask=mask, dropout_p=0.0, is_causal=False, enable_gqa=q.shape[2] != k.shape[2])
        return result.transpose(1, 2)


def _stamp(info):
    return tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_nlink'))


@contextmanager
def _input_file(root, identity, pin: dict[str, Any], maximum):
    _pin(pin, maximum)
    flags = getattr(os, 'O_NOFOLLOW', None), getattr(os, 'O_DIRECTORY', None), getattr(os, 'O_NONBLOCK', None)
    _require(all(type(flag) is int and flag > 0 for flag in flags))
    nofollow, directory, nonblock = cast(tuple[int, int, int], flags)
    root_fd = os.open(root, os.O_RDONLY | nofollow | directory)
    handle = None
    try:
        info = os.fstat(root_fd)
        _require(identity == {'device': info.st_dev, 'inode': info.st_ino} and stat.S_IMODE(info.st_mode) == 0o700)
        fd = os.open(pin['basename'], os.O_RDONLY | nofollow | nonblock, dir_fd=root_fd)
        handle = os.fdopen(fd, 'rb')
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == pin['sizeBytes']
                 and stat.S_IMODE(before.st_mode) == 0o600 and before.st_uid == info.st_uid)
        def check():
            _require(_stamp(os.fstat(fd)) == _stamp(before)
                and _stamp(os.stat(pin['basename'], dir_fd=root_fd, follow_symlinks=False)) == _stamp(before))
            current_root = os.open(root, os.O_RDONLY | nofollow | directory)
            try:
                current = os.fstat(current_root)
                _require(identity == {'device': current.st_dev, 'inode': current.st_ino} and stat.S_IMODE(current.st_mode) == 0o700)
            finally:
                os.close(current_root)
        hasher = hashlib.sha256()
        remaining = pin['sizeBytes']
        while remaining:
            block = handle.read(min(remaining, 1024 * 1024))
            _require(bool(block))
            hasher.update(block)
            remaining -= len(block)
        _require(handle.read(1) == b'')
        _require(hasher.hexdigest() == pin['sha256'])
        check()
        handle.seek(0)
        active = getattr(runtime, 'input_checks', None)
        if active is not None:
            active.append(check)
        try:
            yield handle
        finally:
            try:
                check()
            finally:
                if active is not None:
                    active.remove(check)
    finally:
        if handle is not None:
            handle.close()
        os.close(root_fd)


def verify_open_inputs():
    # Infinite dataloaders may retain their current shard; validate before any
    # checkpoint/result publication, not only at eventual generator destruction.
    for check in tuple(getattr(runtime, 'input_checks', ())):
        check()


def _checkpoint(pin, maximum):
    return open_verified_checkpoint(pin['root'], pin['basename'], pin['rootIdentity'], pin['binding'], maximum)


def _read_exact(reader, size):
    pieces = []
    remaining = size
    while remaining:
        piece = reader.read_chunk(min(remaining, 1024 * 1024))
        _require(type(piece) is bytes and 0 < len(piece) <= remaining)
        pieces.append(piece)
        remaining -= len(piece)
    return b''.join(pieces)


def _tensors(pin, maximum, torch):
    dtype_names = {'F16': 'float16', 'BF16': 'bfloat16', 'F32': 'float32', 'F64': 'float64',
                   'I32': 'int32', 'I64': 'int64', 'U8': 'uint8', 'BOOL': 'bool'}
    with _checkpoint(pin, maximum) as reader:
        _require(reader.identity == {'sha256': pin['sha256'], 'sizeBytes': pin['sizeBytes']})
        reader.reset()
        header_size = int.from_bytes(_read_exact(reader, 8), 'little')
        _read_exact(reader, header_size)
        for name, spec in sorted(reader.tensors.items(), key=lambda row: row[1]['data_offsets'][0]):
            _require(spec['dtype'] in dtype_names)
            size = spec['data_offsets'][1] - spec['data_offsets'][0]
            if size:
                data = bytearray(_read_exact(reader, size))
                tensor = torch.frombuffer(data, dtype=getattr(torch, dtype_names[spec['dtype']])).reshape(spec['shape']).clone()
            else:
                tensor = torch.empty(spec['shape'], dtype=getattr(torch, dtype_names[spec['dtype']]))
            yield name, tensor


def _root_identity(root, identity):
    _require(type(root) is str and Path(root).is_absolute() and '..' not in Path(root).parts
             and type(identity) is dict and set(identity) == {'device', 'inode'}
             and type(identity['device']) is int and identity['device'] >= 0
             and type(identity['inode']) is int and identity['inode'] > 0)


def _pin(pin, maximum):
    _require(type(pin) is dict and set(pin) == {'basename', 'sha256', 'sizeBytes'}
             and type(pin['basename']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}', pin['basename']) is not None
             and type(pin['sha256']) is str and re.fullmatch('[a-f0-9]{64}', pin['sha256']) is not None
             and type(pin['sizeBytes']) is int and 0 < pin['sizeBytes'] <= maximum)


def _checkpoint_pin(pin, maximum):
    _require(type(pin) is dict and set(pin) == {'root', 'basename', 'rootIdentity', 'binding', 'sha256', 'sizeBytes'})
    _root_identity(pin['root'], pin['rootIdentity'])
    _pin({key: pin[key] for key in ('basename', 'sha256', 'sizeBytes')}, maximum)
    checkpoint_binding(pin['binding'])


def validate_runtime_configuration(value, *, mode, microbatch):
    """Pure config validation; installed environment/sample-set observation is external.

    The trusted operator driver must validate current environment inventory/kernel
    pins before launch. Declared sampleSetSha256 is not a measured token-stream hash.
    """
    try:
        config = value
        _require(type(config) is dict and set(config) == {'schema', 'comparisonManifest', 'binding', 'inputRoot',
            'inputRootIdentity', 'tokenizer', 'tokenBytes', 'dataset', 'outputCheckpoint', 'checkpoint', 'evaluationContract'}
            and type(config['schema']) is int and config['schema'] == 1 and mode in {'train', 'evaluate'})
        config = cast(dict[str, Any], config)
        manifest = validate_manifest(config['comparisonManifest'])
        binding = checkpoint_binding(config['binding'])
        _require(binding['manifestSha256'] == manifest_fingerprint(manifest) and manifest['protocol']['seed'] == 42
                 and manifest['initialCheckpoint'] is None)
        _require(type(microbatch) is int and 1 <= microbatch <= 128 and 128 % microbatch == 0)
        _root_identity(config['inputRoot'], config['inputRootIdentity'])
        _pin(config['tokenizer'], 16 * 1024**2)
        _checkpoint_pin(config['tokenBytes'], 16 * 1024**2)
        _require({k: config['tokenizer'][k] for k in ('sha256', 'sizeBytes')} == manifest['tokenizer']['tokenizer']
                 and {k: config['tokenBytes'][k] for k in ('sha256', 'sizeBytes')} == manifest['tokenizer']['tokenBytes'])
        _require(type(config['dataset']) is dict and set(config['dataset']) == {'shards', 'validationShardIds'}
                 and config['dataset']['validationShardIds'] == manifest['dataset']['validationShardIds'])
        dataset = cast(dict[str, Any], config['dataset'])
        shards = dataset['shards']
        _require(type(shards) is list and len(shards) == len(manifest['dataset']['shards']))
        shards = cast(list[dict[str, Any]], shards)
        for shard in shards:
            _require(type(shard) is dict and set(shard) == {'id', 'basename', 'sha256', 'sizeBytes'})
            _pin({k: shard[k] for k in ('basename', 'sha256', 'sizeBytes')}, 2**40)
        _require([{k: row[k] for k in ('id', 'sha256', 'sizeBytes')} for row in shards] == manifest['dataset']['shards']
                 and len({row['basename'] for row in shards}) == len(shards)
                 and len(dataset['validationShardIds']) < len(shards))
        if mode == 'train':
            _require(config['checkpoint'] is None and config['evaluationContract'] is None)
            destination = config['outputCheckpoint']
            _require(type(destination) is dict and set(destination) == {'root', 'basename', 'rootIdentity'})
            _root_identity(destination['root'], destination['rootIdentity'])
            _pin({'basename': destination['basename'], 'sha256': '0' * 64, 'sizeBytes': 1}, 1)
        else:
            _require(config['outputCheckpoint'] is None)
            _checkpoint_pin(config['checkpoint'], min(manifest['artifactLimits']['checkpointBytes'], 2 * 1024**3))
            contract = validate_evaluation_contract(config['evaluationContract'])
            _require(contract['comparisonManifest'] == manifest and all(contract['evaluatorExecution'][key] == binding[key]
                for key in ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId')))
            training, pin = contract['training'], config['checkpoint']
            _require(pin['sha256'] == training['checkpoint']['sha256'] and pin['sizeBytes'] == training['checkpoint']['sizeBytes']
                and all(pin['binding'][key] == training[key] for key in
                    ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256'))
                and pin['binding']['manifestSha256'] == manifest_fingerprint(manifest))
        return deepcopy(config)
    except (KeyError, TypeError, OverflowError, ValueError):
        raise ValueError('RESEARCH_LOCAL_RUNTIME_INVALID') from None


def initialize(*, mode, microbatch):
    """Explicit generated-script entrypoint; all ML imports happen here or later."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    path = Path(args.config)
    _require(path.is_absolute() and path.stat().st_size <= 1024 * 1024)
    config = validate_runtime_configuration(_json(path.read_bytes()), mode=mode, microbatch=microbatch)
    runtime.input_checks = []
    manifest = config['comparisonManifest']
    binding = config['binding']
    shards = config['dataset']['shards']
    with _input_file(config['inputRoot'], config['inputRootIdentity'], config['tokenizer'], 16 * 1024**2) as handle:
        pattern, ranks, specials = decode_tokenizer_json(handle.read())
    torch = importlib.import_module('torch')
    _require(torch.__version__.split('+')[0] == '2.9.1' and torch.version.cuda == '12.8')
    tiktoken = importlib.import_module('tiktoken')
    pq = importlib.import_module('pyarrow.parquet')
    encoding = tiktoken.Encoding(name='operator-frozen-autoresearch', pat_str=pattern, mergeable_ranks=ranks, special_tokens=specials)

    class Tokenizer:
        @classmethod
        def from_directory(cls):
            return cls()

        def get_vocab_size(self):
            return encoding.n_vocab

        def get_bos_token_id(self):
            return encoding.encode_single_token('<|reserved_0|>')

        def encode(self, text, prepend=None, num_threads=8):
            _require(type(text) in {str, list})
            prefix = [] if prepend is None else [prepend if type(prepend) is int else encoding.encode_single_token(prepend)]
            if type(text) is str:
                return prefix + encoding.encode_ordinary(text)
            return [prefix + tokens for tokens in encoding.encode_ordinary_batch(text, num_threads=num_threads)]

    def get_token_bytes(device='cpu'):
        tensors = dict(_tensors(config['tokenBytes'], 16 * 1024**2, torch))
        _require(set(tensors) == {'token_bytes'})
        value = tensors['token_bytes']
        _require(value.dtype == torch.int32 and list(value.shape) == [encoding.n_vocab]
                 and bool((value >= 0).all()))
        expected_lengths = [0 if encoding.decode([index]) in specials else len(encoding.decode([index]).encode('utf-8'))
                            for index in range(encoding.n_vocab)]
        _require(value.tolist() == expected_lengths)
        return value.to(device=device)

    def document_batches(split, tokenizer_batch_size=128):
        _require(split in {'train', 'val'})
        selected = [row for row in shards if (row['id'] in config['dataset']['validationShardIds']) == (split == 'val')]
        _require(bool(selected))
        epoch = 1
        while True:
            for shard in selected:
                pin = {key: shard[key] for key in ('basename', 'sha256', 'sizeBytes')}
                with _input_file(config['inputRoot'], config['inputRootIdentity'], pin, 2**40) as handle:
                    parquet = pq.ParquetFile(handle)
                    for group in range(parquet.num_row_groups):
                        texts = parquet.read_row_group(group, columns=['text']).column('text').to_pylist()
                        _require(all(type(text) is str for text in texts))
                        for start in range(0, len(texts), tokenizer_batch_size):
                            yield texts[start:start + tokenizer_batch_size], epoch
            epoch += 1

    runtime.__dict__.update(config=config, manifest=manifest, binding=binding, torch=torch,
        tokenizer_class=Tokenizer, get_token_bytes=get_token_bytes, document_batches=document_batches, microbatch=microbatch)
    return runtime


def _export_authority():
    _require(runtime.binding['manifestSha256'] == manifest_fingerprint(runtime.manifest))
    verify_open_inputs()


def export_model(model, model_config, training_seconds):
    """Export only the fixed model's tensor state, never a pickled model object."""
    torch, config = runtime.torch, runtime.config
    _require(type(training_seconds) in {int, float} and math.isfinite(training_seconds) and training_seconds >= 300)
    expected = {'sequence_len': 2048, 'vocab_size': runtime.tokenizer_class().get_vocab_size(),
        'n_layer': 8, 'n_head': 4, 'n_kv_head': 4, 'n_embd': 512, 'window_pattern': 'SSSL'}
    _require(model_config == expected)
    state = model.state_dict()
    names = {torch.float32: 'F32', torch.bfloat16: 'BF16', torch.float16: 'F16', torch.int64: 'I64', torch.int32: 'I32'}
    header, offset = {}, 0
    for name, tensor in sorted(state.items()):
        _require(tensor.dtype in names)
        length = tensor.numel() * tensor.element_size()
        header[name] = {'dtype': names[tensor.dtype], 'shape': list(tensor.shape), 'data_offsets': [offset, offset + length]}
        offset += length
    _require(offset <= min(runtime.manifest['artifactLimits']['checkpointBytes'], 2 * 1024**3))

    def chunks():
        for _, tensor in sorted(state.items()):
            raw = tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
            for index in range(0, len(raw), 1024 * 1024):
                yield raw[index:index + 1024 * 1024]
    destination = config['outputCheckpoint']
    receipt = write_checkpoint(destination['root'], destination['basename'], header, chunks(),
        root_identity=destination['rootIdentity'], binding=runtime.binding,
        max_bytes=min(runtime.manifest['artifactLimits']['checkpointBytes'], 2 * 1024**3),
        before_effect=_export_authority)
    print(json.dumps({'schema': 1, 'evidenceKind': 'local-adapted-training-checkpoint', 'checkpoint': receipt,
        'trainingSeconds': training_seconds, 'executionVerified': False, 'scientificConclusionVerified': False}, sort_keys=True))


def evaluate_main(*, microbatch):
    initialize(mode='evaluate', microbatch=microbatch)
    torch, config = runtime.torch, runtime.config
    contract = validate_evaluation_contract(config['evaluationContract'])
    _require(contract['comparisonManifest'] == runtime.manifest and all(contract['evaluatorExecution'][key] == runtime.binding[key]
        for key in ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId')))
    checkpoint = config['checkpoint']
    training = contract['training']
    _require(checkpoint['sha256'] == training['checkpoint']['sha256'] and checkpoint['sizeBytes'] == training['checkpoint']['sizeBytes']
             and all(checkpoint['binding'][key] == training[key] for key in
                ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256'))
             and checkpoint['binding']['manifestSha256'] == manifest_fingerprint(runtime.manifest))
    architecture = importlib.import_module('trusted_architecture')
    data = importlib.import_module('trusted_data')
    tokenizer = runtime.tokenizer_class()
    model_config = architecture.GPTConfig(sequence_len=2048, vocab_size=tokenizer.get_vocab_size(), n_layer=8,
        n_head=4, n_kv_head=4, n_embd=512, window_pattern='SSSL')
    model = architecture.GPT(model_config).to(device='cuda')
    model.init_weights()
    expected = model.state_dict()
    supplied = {}
    for name, tensor in _tensors(checkpoint, min(runtime.manifest['artifactLimits']['checkpointBytes'], 2 * 1024**3), torch):
        _require(name in expected and list(tensor.shape) == list(expected[name].shape) and tensor.dtype == expected[name].dtype
                 and bool(torch.isfinite(tensor).all()))
        supplied[name] = tensor
    _require(set(supplied) == set(expected))
    model.load_state_dict(supplied, strict=True)
    model.eval()
    token_bytes = runtime.get_token_bytes(device='cuda')
    loader = data.make_dataloader(tokenizer, microbatch, 2048, 'val')
    nats, count = 0.0, 0
    with torch.no_grad(), torch.amp.autocast(device_type='cuda', dtype=torch.bfloat16):
        for _ in range(20971520 // (microbatch * 2048)):
            x, y, _ = next(loader)
            logits = model(x)  # Fixed original architecture; never candidate-supplied loss.
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1), reduction='none')
            sizes = token_bytes[y.reshape(-1)]
            nats += (loss * (sizes > 0)).sum().item()
            count += sizes.sum().item()
    _require(count > 0 and math.isfinite(nats) and nats > 0)
    verify_open_inputs()
    print(json.dumps({'schema': 1, 'evaluationContractSha256': evaluation_contract_fingerprint(contract),
        'status': 'completed', 'metric': {'id': 'val_bpb', 'value': nats / (math.log(2) * count)}}, sort_keys=True, allow_nan=False))

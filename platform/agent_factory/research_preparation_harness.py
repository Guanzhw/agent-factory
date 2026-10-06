"""Bounded safe-tokenizer export; no encoding creation, Torch, GPU or training."""
import hashlib
import json

from .research_checkpoint import write_checkpoint, _root
from .research_torch_runtime import decode_tokenizer_json

MAX_VOCAB = 8192
MAX_OUTPUT = 65536


def tokenizer_payload(raw):
    """Match tiktoken's per-token UTF-8 replacement decoding and special zeros."""
    _, ranks, specials = decode_tokenizer_json(raw)
    count = len(ranks) + len(specials)
    if count > MAX_VOCAB:
        raise ValueError('PREPARATION_VOCAB_LIMIT')
    names = set(specials)
    values = [0] * count
    for token, index in ranks.items():
        decoded = token.decode('utf-8', errors='replace')
        values[index] = 0 if decoded in names else len(decoded.encode('utf-8'))
    data = b''.join(value.to_bytes(4, 'little', signed=True) for value in values)
    return {'token_bytes': {'dtype': 'I32', 'shape': [count], 'data_offsets': [0, len(data)]}}, data


def export_token_bytes(config):
    """Called only by the pinned managed process; binding is controller-derived."""
    if type(config) is not dict or set(config) != {'schema', 'tokenizerJson', 'tokenizerSha256', 'reservation'} or type(config['schema']) is not int or config['schema'] != 1:
        raise ValueError('PREPARATION_CONFIG_INVALID')
    raw = config['tokenizerJson'].encode('utf-8')
    if hashlib.sha256(raw).hexdigest() != config['tokenizerSha256']:
        raise ValueError('PREPARATION_INPUT_CHANGED')
    header, data = tokenizer_payload(raw)
    reservation = config['reservation']
    destination = reservation['destination']
    if destination['basename'] != 'token-bytes.safetensors':
        raise ValueError('PREPARATION_DESTINATION_INVALID')
    return write_checkpoint(destination['root'], destination['basename'], header, [data],
        root_identity=destination['rootIdentity'], binding=reservation['binding'],
        max_bytes=MAX_OUTPUT, before_effect=lambda: None)


def main(config_path, *, expected_sha256, root_identity):
    # The controller seals this fixed configuration before original dispatch.
    import os
    import stat
    from pathlib import Path
    path = Path(config_path)
    if path.name != 'run-config.json':
        raise ValueError('PREPARATION_CONFIG_INVALID')
    root_fd = _root(path.parent, root_identity)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2 * 1024**2:
            raise ValueError('PREPARATION_CONFIG_INVALID')
        raw = os.read(fd, info.st_size + 1)
        if len(raw) != info.st_size or (lambda after: (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))(os.fstat(fd)):
            raise ValueError('PREPARATION_CONFIG_INVALID')
    finally:
        os.close(fd)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('PREPARATION_CONFIG_INVALID')
    export_token_bytes(json.loads(raw))

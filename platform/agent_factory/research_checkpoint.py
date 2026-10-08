"""Restricted safetensors byte custody; no tensor deserialization or execution.

Caller owns the storage/retention lock, fresh authority and reserved disk budget.
Metadata binds supplied identities; it does not authenticate a process or model.
Failed producers retain their private staging bytes for original-object cleanup.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, cast
from uuid import uuid4

MAX_BYTES = 2 * 1024**3
MAX_HEADER_BYTES = 1024**2
CHUNK_BYTES = 1024**2
_FIELDS = frozenset('ownerId taskId nativeRunId planId planFingerprint leaseId providerJobId variantSha256 manifestSha256'.split())
_HASH_FIELDS = frozenset({'planFingerprint', 'variantSha256', 'manifestSha256'})
_WIDTH = {'BOOL': 1, 'I8': 1, 'U8': 1, 'I16': 2, 'U16': 2, 'I32': 4, 'U32': 4,
    'I64': 8, 'U64': 8, 'F16': 2, 'BF16': 2, 'F32': 4, 'F64': 8}
_ERROR = 'RESEARCH_CHECKPOINT_INVALID'


def _require(condition):
    if not condition:
        raise ValueError(_ERROR)


def checkpoint_binding(value: Any) -> dict[str, str]:
    _require(type(value) is dict and all(type(key) is str for key in value) and set(value) == _FIELDS)
    for key, item in value.items():
        if key == 'ownerId':
            _require(type(item) is str and 1 <= len(item) <= 200 and all(ord(c) >= 32 and ord(c) != 127 for c in item))
        else:
            pattern = r'[a-f0-9]{64}' if key in _HASH_FIELDS else r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}'
            _require(type(item) is str and re.fullmatch(pattern, item) is not None)
    return dict(value)


def _metadata(binding):
    return {'factory.' + key: value for key, value in checkpoint_binding(binding).items()}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value):
    raise ValueError(_ERROR)


def validate_header(raw: bytes, data_bytes: int, binding: Any) -> dict[str, dict]:
    """Validate the restricted format only, including full contiguous byte coverage."""
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_HEADER_BYTES and raw.startswith(b'{'))
        _require(type(data_bytes) is int and 0 <= data_bytes <= MAX_BYTES)
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_constant)
        _require(type(value) is dict and 2 <= len(value) <= 4097 and value.get('__metadata__') == _metadata(binding))
        value = cast(dict[str, Any], value)
        metadata = value['__metadata__']
        _require(type(metadata) is dict and all(type(v) is str for v in metadata.values()))
        tensors, intervals = {}, []
        for name, entry in value.items():
            if name == '__metadata__':
                continue
            _require(type(name) is str and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,255}', name) is not None)
            _require(type(entry) is dict and set(entry) == {'dtype', 'shape', 'data_offsets'})
            entry = cast(dict[str, Any], entry)
            dtype, shape, offsets = entry['dtype'], entry['shape'], entry['data_offsets']
            _require(type(dtype) is str and dtype in _WIDTH and type(shape) is list and len(shape) <= 16)
            dtype, shape = cast(str, dtype), cast(list[Any], shape)
            count = 1
            for dimension in shape:
                _require(type(dimension) is int and 0 <= dimension <= MAX_BYTES)
                count *= dimension
                _require(count <= MAX_BYTES)
            _require(type(offsets) is list and len(offsets) == 2 and all(type(n) is int for n in offsets))
            start, end = cast(list[int], offsets)
            _require(0 <= start <= end <= data_bytes and end - start == count * _WIDTH[dtype])
            tensors[name] = deepcopy(entry)
            intervals.append((start, end))
        cursor = 0
        for start, end in sorted(intervals):
            _require(start == cursor)
            cursor = end
        _require(cursor == data_bytes)
        return tensors
    except (TypeError, KeyError, ValueError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None


def _flags():
    values = [getattr(os, name, None) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')]
    _require(os.name == 'posix' and all(type(value) is int and value > 0 for value in values))
    return cast(tuple[int, int, int], tuple(values))


def _name(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}', value) is not None
        and value not in {'.', '..'})
    return value


def _uid():
    getter = getattr(os, 'getuid', None)
    if not callable(getter):
        raise ValueError(_ERROR)
    value = getter()
    _require(type(value) is int and value >= 0)
    return value


def _root(root, identity):
    nofollow, directory, _ = _flags()
    _require(type(identity) is dict and set(identity) == {'device', 'inode'} and
        all(type(n) is int and n >= 0 for n in identity.values()))
    path = Path(root).absolute()
    _require('..' not in path.parts)
    fd = os.open(path.anchor, os.O_RDONLY | directory | nofollow)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd); fd = child
        current = os.fstat(fd)
        _require(stat.S_ISDIR(current.st_mode) and current.st_uid == _uid() and
            stat.S_IMODE(current.st_mode) == 0o700 and (current.st_dev, current.st_ino) == (identity['device'], identity['inode']))
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stamp(info):
    return tuple(getattr(info, name) for name in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_nlink', 'st_uid'))


def _file(info, root, max_bytes):
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_uid == _uid() and info.st_dev == root.st_dev and 8 < info.st_size <= max_bytes)


class VerifiedCheckpoint:
    """Scoped stream of the same verified FD. Do not use after context exit."""
    def __init__(self, fd, root_fd, name, stamp, identity, provenance, tensors):
        self._fd, self._root_fd, self._name, self._stamp = fd, root_fd, name, stamp
        self.identity, self.provenance, self.tensors = deepcopy(identity), deepcopy(provenance), deepcopy(tensors)
        self._root_path: Any = None
        self._root_identity: Any = None

    def _check(self):
        _require(self._fd is not None and _stamp(os.fstat(self._fd)) == self._stamp)
        _require(_stamp(os.stat(self._name, dir_fd=self._root_fd, follow_symlinks=False)) == self._stamp)
        if self._root_path is not None:
            check = _root(self._root_path, self._root_identity)
            os.close(check)

    def reset(self):
        self._check()
        os.lseek(self._fd, 0, os.SEEK_SET)

    def read_chunk(self, size=CHUNK_BYTES):
        _require(type(size) is int and 1 <= size <= CHUNK_BYTES)
        self._check()
        result = os.read(self._fd, size)
        self._check()
        return result


def _verify(fd, root_fd, name, binding, max_bytes):
    _require(type(max_bytes) is int and 8 < max_bytes <= MAX_BYTES)
    info = os.fstat(fd)
    _file(info, os.fstat(root_fd), max_bytes)
    os.lseek(fd, 0, os.SEEK_SET)
    prefix = os.read(fd, 8)
    _require(len(prefix) == 8)
    header_size = struct.unpack('<Q', prefix)[0]
    _require(0 < header_size <= MAX_HEADER_BYTES and 8 + header_size <= info.st_size)
    header = os.read(fd, header_size)
    _require(len(header) == header_size)
    tensors = validate_header(header, info.st_size - 8 - header_size, binding)
    hasher = hashlib.sha256(prefix + header)
    remaining = info.st_size - 8 - header_size
    while remaining:
        chunk = os.read(fd, min(remaining, CHUNK_BYTES))
        _require(bool(chunk))
        hasher.update(chunk); remaining -= len(chunk)
    _require(os.read(fd, 1) == b'' and _stamp(os.fstat(fd)) == _stamp(info))
    result = VerifiedCheckpoint(fd, root_fd, name, _stamp(info),
        {'sha256': hasher.hexdigest(), 'sizeBytes': info.st_size}, checkpoint_binding(binding), tensors)
    result.reset()
    return result


@contextmanager
def open_verified_checkpoint(root, basename, root_identity, binding, max_bytes):
    """Hold original directory/file FDs; validate every subsequent stream read."""
    root_fd = fd = None
    verified = None
    caller_scope = False
    try:
        nofollow, _, nonblock = _flags()
        root_fd = _root(root, root_identity)
        fd = os.open(_name(basename), os.O_RDONLY | nofollow | nonblock, dir_fd=root_fd)
        verified = _verify(fd, root_fd, basename, binding, max_bytes)
        verified._root_path, verified._root_identity = root, dict(root_identity)
        caller_scope = True
        yield verified
        caller_scope = False
        verified._check()
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        if caller_scope:
            raise  # Preserve authority/cancellation errors from the caller.
        raise ValueError(_ERROR) from None
    finally:
        if verified is not None:
            verified._fd = None
        if fd is not None:
            os.close(fd)
        if root_fd is not None:
            os.close(root_fd)


def _write(fd, data):
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        _require(count > 0)
        view = view[count:]


def write_checkpoint(root, basename, tensor_header, data_chunks, *, root_identity, binding, max_bytes, before_effect):
    """Exclusive private staging; fsync then publish without replacement.

    Failed staging/publication is retained, never automatically retried or adopted.
    Caller reserves room for staging and owns the producer/retention fence.
    """
    root_fd = fd = None
    authority_error = None
    def authorize():
        nonlocal authority_error
        try:
            result = before_effect()
        except BaseException as error:
            authority_error = error
            raise
        if inspect.iscoroutine(result):
            result.close()
        _require(result is None)
    try:
        _require(callable(before_effect) and type(max_bytes) is int and 8 < max_bytes <= MAX_BYTES)
        name = _name(basename)
        _require(type(tensor_header) is dict and 1 <= len(tensor_header) <= 4096 and '__metadata__' not in tensor_header)
        tensor_header = cast(dict[str, Any], tensor_header)
        for key, value in tensor_header.items():
            _require(type(key) is str and len(key) <= 256 and type(value) is dict
                and set(value) == {'dtype', 'shape', 'data_offsets'})
            value = cast(dict[str, Any], value)
            _require(type(value['dtype']) is str and value['dtype'] in _WIDTH
                and type(value['shape']) is list and len(value['shape']) <= 16
                and all(type(n) is int and 0 <= n <= MAX_BYTES for n in value['shape'])
                and type(value['data_offsets']) is list and len(value['data_offsets']) == 2
                and all(type(n) is int and 0 <= n <= MAX_BYTES for n in value['data_offsets']))
        header = json.dumps({'__metadata__': _metadata(binding), **tensor_header},
            sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
        header += b' ' * (-len(header) % 8)
        _require(len(header) <= MAX_HEADER_BYTES)
        root_fd = _root(root, root_identity)
        stage = 'checkpoint-stage-' + uuid4().hex
        authorize()
        nofollow, _, nonblock = _flags()
        fd = os.open(stage, os.O_CREAT | os.O_EXCL | os.O_RDWR | nofollow | nonblock, 0o600, dir_fd=root_fd)
        size = 8 + len(header)
        _require(size <= max_bytes)
        _write(fd, struct.pack('<Q', len(header)) + header)
        for chunk in data_chunks:
            _require(type(chunk) is bytes and 0 < len(chunk) <= CHUNK_BYTES)
            size += len(chunk)
            _require(size <= max_bytes)
            authorize(); _write(fd, chunk)
        os.fsync(fd)
        checked = _verify(fd, root_fd, stage, binding, max_bytes)
        checked._root_path, checked._root_identity = root, dict(root_identity)
        authorize(); checked._check()
        # link is atomic and fails if destination exists; unlike rename it cannot
        # replace existing custody. Crash during the two-link gap fails validation.
        os.link(stage, name, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        os.unlink(stage, dir_fd=root_fd)
        os.fsync(root_fd)
        final = _verify(fd, root_fd, name, binding, max_bytes)
        final._root_path, final._root_identity = root, dict(root_identity)
        final._check()
        return {'identity': final.identity, 'provenance': final.provenance, 'tensors': final.tensors,
            'format': 'restricted-safetensors-v1', 'executionVerified': False, 'scientificConclusionVerified': False}
    except (OSError, TypeError, ValueError, OverflowError, RecursionError) as error:
        if error is authority_error:
            raise
        raise ValueError(_ERROR) from None
    finally:
        if fd is not None:
            os.close(fd)
        if root_fd is not None:
            os.close(root_fd)

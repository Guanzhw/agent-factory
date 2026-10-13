"""Operator-only private program custody; never imports or executes staged code.

Seal-last publication is atomic for readers of this contract. An incomplete root
cannot be adopted. Caller retains its original storage/authority lock through
verification and launch: hash verification is not a sandbox or execution proof.
"""
from dataclasses import asdict, dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import stat

from .research_checkpoint import _flags, _root, _stamp

ERROR = 'RESEARCH_STAGING_INVALID'
SEAL = 'program.seal.json'
PROGRAM_FILES = frozenset({'trusted_architecture.py', 'trusted_data.py',
    'train_baseline.py', 'train_candidate.py', 'evaluate.py', 'run-config.json'})
MAX_GENERATED_BYTES = 4 * 1024**2
MAX_INPUT_BYTES = 2 * 1024**3
MAX_TOTAL_INPUT_BYTES = 16 * 1024**3
KINDS = frozenset({'data', 'tokenizer', 'tokenBytes', 'environment', 'checkpoint'})


def _require(value):
    if not value:
        raise ValueError(ERROR)


def _hash(value):
    _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None)


def _name(value):
    _require(type(value) is str and re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}', value) is not None
             and value not in {'.', '..', SEAL})


@dataclass(frozen=True)
class RootIdentity:
    device: int
    inode: int

    def __post_init__(self):
        _require(type(self.device) is int and self.device >= 0 and type(self.inode) is int and self.inode > 0)


@dataclass(frozen=True)
class FilePin:
    basename: str
    sha256: str
    size_bytes: int

    def __post_init__(self):
        _name(self.basename)
        _hash(self.sha256)
        _require(type(self.size_bytes) is int and 0 < self.size_bytes <= MAX_INPUT_BYTES)


@dataclass(frozen=True)
class InputPin:
    label: str
    kind: str
    root: str
    root_identity: RootIdentity
    file: FilePin

    def __post_init__(self):
        _name(self.label)
        _require(type(self.kind) is str and self.kind in KINDS)
        _require(type(self.root) is str and len(self.root) <= 4096 and Path(self.root).is_absolute()
                 and '..' not in Path(self.root).parts and '\x00' not in self.root)
        _require(type(self.root_identity) is RootIdentity and type(self.file) is FilePin)
        if self.kind == 'tokenizer':
            _require(self.file.size_bytes <= MAX_GENERATED_BYTES)


@dataclass(frozen=True)
class ProgramDescriptor:
    entrypoint: str
    generated: tuple[FilePin, ...]
    comparison_manifest_sha256: str
    variant_sha256: str
    root_identity: RootIdentity
    inputs: tuple[InputPin, ...]
    checkpoint_artifact_id: str | None = None
    evaluation_contract_sha256: str | None = None
    environment_verification_sha256: str | None = None

    def __post_init__(self):
        _require(type(self.entrypoint) is str and self.entrypoint in
                 {'train_baseline.py', 'train_candidate.py', 'evaluate.py'})
        _hash(self.comparison_manifest_sha256)
        _hash(self.variant_sha256)
        _require(type(self.root_identity) is RootIdentity)
        _require(type(self.generated) is tuple and len(self.generated) == len(PROGRAM_FILES)
                 and all(type(pin) is FilePin for pin in self.generated))
        _require({pin.basename for pin in self.generated} == PROGRAM_FILES
                 and all(pin.size_bytes <= MAX_GENERATED_BYTES for pin in self.generated))
        _require(type(self.inputs) is tuple and 1 <= len(self.inputs) <= 1028
                 and all(type(pin) is InputPin for pin in self.inputs))
        _require(len({pin.label for pin in self.inputs}) == len(self.inputs)
                 and sum(pin.file.size_bytes for pin in self.inputs) <= MAX_TOTAL_INPUT_BYTES)
        if self.environment_verification_sha256 is not None:
            _hash(self.environment_verification_sha256)
        checkpoints = [pin for pin in self.inputs if pin.kind == 'checkpoint']
        if self.entrypoint == 'evaluate.py':
            _require(len(checkpoints) == 1)
            _require(type(self.checkpoint_artifact_id) is str and re.fullmatch(
                '[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', self.checkpoint_artifact_id) is not None)
            _hash(self.evaluation_contract_sha256)
        else:
            _require(not checkpoints and self.checkpoint_artifact_id is None and self.evaluation_contract_sha256 is None)


def pin_bytes(basename, raw):
    _require(type(raw) is bytes)
    return FilePin(basename, hashlib.sha256(raw).hexdigest(), len(raw))


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value)
            value[key] = item
        return value
    def invalid(_value):
        raise ValueError(ERROR)
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid)
    _require(type(value) is dict)
    # Also rejects numeric overflow such as 1e999, which JSON otherwise accepts.
    json.dumps(value, allow_nan=False)
    return value


def descriptor_bytes(descriptor):
    _require(type(descriptor) is ProgramDescriptor)
    return json.dumps(asdict(descriptor), sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _read(root_fd, name, size, expected_hash=None, *, collect=False):
    nofollow, _, nonblock = _flags()
    getuid = getattr(os, 'getuid', None)
    if not callable(getuid):
        raise ValueError(ERROR)
    owner_uid = getuid()
    fd = os.open(name, os.O_RDONLY | nofollow | nonblock, dir_fd=root_fd)
    try:
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == owner_uid
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_dev == os.fstat(root_fd).st_dev
                 and info.st_size == size)
        remaining, hasher, chunks = size, hashlib.sha256(), []
        while remaining:
            chunk = os.read(fd, min(remaining, 1024**2))
            _require(bool(chunk))
            remaining -= len(chunk)
            hasher.update(chunk)
            if collect:
                chunks.append(chunk)
        _require(os.read(fd, 1) == b'' and _stamp(os.fstat(fd)) == _stamp(info)
                 and _stamp(os.stat(name, dir_fd=root_fd, follow_symlinks=False)) == _stamp(info))
        if expected_hash is not None:
            _require(hasher.hexdigest() == expected_hash)
        return b''.join(chunks)
    finally:
        os.close(fd)


def _verify(root, descriptor, *, sealed):
    _require(isinstance(root, (str, Path)) and len(str(root)) <= 4096
             and Path(root).is_absolute() and '..' not in Path(root).parts)
    root_fd = _root(root, asdict(descriptor.root_identity))
    try:
        _require(set(os.listdir(root_fd)) == PROGRAM_FILES | ({SEAL} if sealed else set()))
        if sealed:
            expected = descriptor_bytes(descriptor)
            _require(_read(root_fd, SEAL, len(expected), collect=True) == expected)
        for pin in descriptor.generated:
            raw = _read(root_fd, pin.basename, pin.size_bytes, pin.sha256,
                        collect=pin.basename == 'run-config.json')
            if pin.basename == 'run-config.json':
                _json(raw)
        for pin in descriptor.inputs:
            input_fd = _root(pin.root, asdict(pin.root_identity))
            try:
                raw = _read(input_fd, pin.file.basename, pin.file.size_bytes, pin.file.sha256,
                            collect=pin.kind == 'tokenizer')
                if pin.kind == 'tokenizer':
                    _json(raw)
            finally:
                os.close(input_fd)
            check = _root(pin.root, asdict(pin.root_identity))
            os.close(check)
        check = _root(root, asdict(descriptor.root_identity))
        os.close(check)
    finally:
        os.close(root_fd)


def verify_staged_program(root, descriptor):
    """Rehash every sealed source/config/input immediately before guarded launch.

    Checkpoint format/original execution binding is additionally verified by the
    checkpoint reader; this function only verifies its exact artifact bytes.
    """
    try:
        _require(type(descriptor) is ProgramDescriptor)
        _verify(root, descriptor, sealed=True)
        return {'schema': 1, 'descriptorSha256': hashlib.sha256(descriptor_bytes(descriptor)).hexdigest(),
                'executionVerified': False}
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None


def stage_own_bundle(root, files, before_effect, *, descriptor):
    """Exclusively create all six files, then seal; never adopt an occupied root.

    before_effect is the caller's synchronous fresh-authority/storage guard.
    Failed staging deliberately retains private partial bytes for original-custody
    cleanup. There is no retry/adoption path and no deleting caller-owned files.
    """
    root_fd = None
    try:
        _require(type(descriptor) is ProgramDescriptor and type(files) is dict
                 and set(files) == PROGRAM_FILES and callable(before_effect))
        for pin in descriptor.generated:
            _require(type(files[pin.basename]) is bytes and pin_bytes(pin.basename, files[pin.basename]) == pin)
        _json(files['run-config.json'])
        _require(isinstance(root, (str, Path)) and len(str(root)) <= 4096
                 and Path(root).is_absolute() and '..' not in Path(root).parts)
        root_fd = _root(root, asdict(descriptor.root_identity))
        _require(os.listdir(root_fd) == [])
        def write(name, raw):
            result = before_effect()
            if inspect.iscoroutine(result):
                result.close()
            _require(not inspect.isawaitable(result) and result is not False)
            check = _root(root, asdict(descriptor.root_identity))
            os.close(check)
            nofollow, _, _ = _flags()
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600, dir_fd=root_fd)
            try:
                view = memoryview(raw)
                while view:
                    count = os.write(fd, view)
                    _require(count > 0)
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
        for name in sorted(files):
            write(name, files[name])
        _verify(root, descriptor, sealed=False)
        write(SEAL, descriptor_bytes(descriptor))
        os.fsync(root_fd)
        return verify_staged_program(root, descriptor)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None
    finally:
        if root_fd is not None:
            os.close(root_fd)

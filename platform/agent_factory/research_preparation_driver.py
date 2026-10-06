"""Operator-only original-job preparation closure; no scheduler or executor."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat

from .process_enforcement import ProcessSpec
from .research_checkpoint import _root
from .research_preparation_harness import tokenizer_payload
from .store import canonical, digest

_FILES = ('__init__.py', 'research_preparation_harness.py', 'research_checkpoint.py',
          'research_torch_runtime.py', 'research_evaluation.py', 'research_assessment.py',
          'research_manifest.py', 'research_profile.py')


def _require(ok):
    if not ok:
        raise ValueError('PREPARATION_DRIVER_INVALID')


def _read(fd, name, maximum):
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        before = os.fstat(child)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum)
        raw = os.read(child, maximum + 1)
        _require(len(raw) == before.st_size and (lambda after: (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns))(os.fstat(child)))
        return raw
    finally:
        os.close(child)


class PreparationDriver:
    """Bind safe JSON bytes to the original Store reservation, never caller IDs.

    One private staging root is dedicated to one original effect. Restart may
    verify its exact sealed bytes, but never overwrite or adopt partial staging.
    """
    def __init__(self, *, root, root_identity, tokenizer_json, reserve, manifest_sha256):
        _require(callable(reserve))
        tokenizer_payload(tokenizer_json)
        self.root = Path(root)
        self.identity = deepcopy(root_identity)
        fd = _root(self.root, self.identity)
        os.close(fd)
        self.raw = tokenizer_json
        self.reserve = reserve
        self.manifest_sha256 = manifest_sha256
        _require(type(manifest_sha256) is str and len(manifest_sha256) == 64
                 and all(c in '0123456789abcdef' for c in manifest_sha256))
        self.package = Path(__file__).resolve().parent
        self.pins = {name: hashlib.sha256((self.package / name).read_bytes()).hexdigest() for name in _FILES}
        # Only stdlib imports precede checked package imports. Isolated CPython
        # excludes environment/user-site import redirection.
        self.entry = ("import hashlib,pathlib,sys\n"
            + 'p=pathlib.Path(' + repr(str(self.package)) + ')\n'
            + 'pins=' + repr(self.pins) + '\n'
            + "if any(hashlib.sha256((p/n).read_bytes()).hexdigest()!=h for n,h in pins.items()): raise SystemExit(126)\n"
            + 'sys.path.insert(0,str(p.parent))\n'
            + 'from agent_factory.research_preparation_harness import main\n'
            + 'main(sys.argv[1])\n').encode()
        self.configuration_fingerprint = digest({'revision': 'preparation-driver-v1',
            'root': str(self.root), 'identity': self.identity, 'tokenizerSha256': hashlib.sha256(self.raw).hexdigest(),
            'manifestSha256': manifest_sha256, 'entrySha256': hashlib.sha256(self.entry).hexdigest(), 'runtime': self.pins})

    def validate_spec(self, spec):
        _require(type(spec) is ProcessSpec and spec.argv ==
                 ('-I', '-B', str(self.root / 'prepare.py'), str(self.root / 'run-config.json')))
        fd = _root(self.root, self.identity)
        os.close(fd)
        _require(all(hashlib.sha256((self.package / name).read_bytes()).hexdigest() == pin for name, pin in self.pins.items()))

    def __call__(self, record):
        lease = record['binding']
        reservation = self.reserve(lease['ownerId'], lease['id'], disk_bytes=65536)
        binding = reservation['binding']
        _require(binding['leaseId'] == lease['id'] and binding['ownerId'] == lease['ownerId']
                 and binding['taskId'] == lease['localTaskId'] and binding['nativeRunId'] == lease['nativeRunId']
                 and binding['providerJobId'] == record['processPin']['id']
                 and binding['variantSha256'] == self.configuration_fingerprint
                 and binding['manifestSha256'] == self.manifest_sha256)
        config = {'schema': 1, 'tokenizerJson': self.raw.decode('utf-8'),
                  'tokenizerSha256': hashlib.sha256(self.raw).hexdigest(), 'reservation': reservation}
        config_raw = canonical(config).encode()
        invocation = ('main(sys.argv[1], expected_sha256=' + repr(hashlib.sha256(config_raw).hexdigest())
                      + ', root_identity=' + repr(self.identity) + ')').encode()
        files = {'prepare.py': self.entry.replace(b'main(sys.argv[1])', invocation), 'run-config.json': config_raw}
        descriptor = digest({name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()})
        files['seal.json'] = canonical({'schema': 1, 'descriptorSha256': descriptor}).encode()
        fd = _root(self.root, self.identity)
        try:
            existing = set(os.listdir(fd))
            if existing:
                _require(existing == set(files))
                _require(all(_read(fd, name, 2 * 1024**2) == raw for name, raw in files.items()))
            else:
                for name, raw in files.items():
                    child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=fd)
                    try:
                        with os.fdopen(child, 'wb', closefd=False) as stream:
                            stream.write(raw); stream.flush(); os.fsync(child)
                    finally:
                        os.close(child)
                os.fsync(fd)
        finally:
            os.close(fd)
        return {'schema': 1, 'evidenceKind': 'research-tokenizer-preparation-v1',
            'descriptorSha256': descriptor, 'sourceSha256': self.configuration_fingerprint,
            'manifestSha256': self.manifest_sha256, 'variantSha256': self.configuration_fingerprint,
            'leaseBindingSha256': digest(lease), 'processIdentitySha256': record['processPin']['identitySha256'],
            'executionVerified': False}

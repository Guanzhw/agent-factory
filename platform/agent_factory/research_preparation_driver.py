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
    child = os.open(name, os.O_RDONLY | getattr(os, 'O_NOFOLLOW'), dir_fd=fd)
    try:
        before = os.fstat(child)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum)
        raw = os.read(child, maximum + 1)
        _require(len(raw) == before.st_size and (lambda after: (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns))(os.fstat(child)))
        return raw
    finally:
        os.close(child)


def _entrypoint(package, pins):
    # Source-only closed package loader. Never consult pyc, extension modules,
    # sibling packages, sys.path or a previously imported agent_factory module.
    return ("import hashlib,importlib.abc,importlib.util,os,stat,sys\n"
        + 'package=' + repr(str(package)) + '\npins=' + repr(pins) + '\n'
        + """sources={}
fd=os.open(package,os.O_RDONLY|getattr(os, 'O_DIRECTORY')|getattr(os, 'O_NOFOLLOW'))
try:
 for name,pin in pins.items():
  child=os.open(name,os.O_RDONLY|getattr(os, 'O_NOFOLLOW'),dir_fd=fd)
  try:
   before=os.fstat(child)
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>2097152: raise SystemExit(126)
   raw=os.read(child,2097153)
   after=os.fstat(child)
   fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
   if len(raw)!=before.st_size or any(getattr(before,k)!=getattr(after,k) for k in fields) or hashlib.sha256(raw).hexdigest()!=pin: raise SystemExit(126)
   sources['agent_factory' if name=='__init__.py' else 'agent_factory.'+name[:-3]]=raw
  finally: os.close(child)
finally: os.close(fd)
if any(n=='agent_factory' or n.startswith('agent_factory.') for n in sys.modules): raise SystemExit(126)
class SourceOnly(importlib.abc.MetaPathFinder,importlib.abc.Loader):
 def find_spec(self,name,path=None,target=None):
  if name in sources: return importlib.util.spec_from_loader(name,self,is_package=name=='agent_factory')
  if name.startswith('agent_factory.'): raise ImportError('PREPARATION_SOURCE_UNDECLARED')
 def create_module(self,spec): return None
 def exec_module(self,module): exec(compile(sources[module.__name__],'<verified-preparation-source>','exec'),module.__dict__)
sys.meta_path.insert(0,SourceOnly())
from agent_factory.research_preparation_harness import main
main(sys.argv[1])
""").encode()


class PreparationDriver:
    """Bind safe JSON bytes to the original Store reservation, never caller IDs.

    One private staging root is dedicated to one original effect. Restart may
    verify its exact sealed bytes, but never overwrite or adopt partial staging.
    """
    def __init__(self, *, root, root_identity, tokenizer_json, reserve, manifest_sha256):
        _require(callable(reserve))
        _require(type(tokenizer_json) is bytes and len(tokenizer_json) <= 1024**2)
        tokenizer_payload(tokenizer_json)
        _require(len(canonical(tokenizer_json.decode('utf-8')).encode()) + 65536 <= 2 * 1024**2)
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
        self.entry = _entrypoint(self.package, self.pins)
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
        reservation = self.reserve(lease['ownerId'], lease['id'], disk_bytes=3 * 1024**2)
        binding = reservation['binding']
        _require(binding['leaseId'] == lease['id'] and binding['ownerId'] == lease['ownerId']
                 and binding['taskId'] == lease['localTaskId'] and binding['nativeRunId'] == lease['nativeRunId']
                 and binding['providerJobId'] == record['processPin']['id']
                 and binding['variantSha256'] == self.configuration_fingerprint
                 and binding['manifestSha256'] == self.manifest_sha256)
        config = {'schema': 1, 'tokenizerJson': self.raw.decode('utf-8'),
                  'tokenizerSha256': hashlib.sha256(self.raw).hexdigest(), 'reservation': reservation}
        config_raw = canonical(config).encode()
        _require(len(config_raw) <= 2 * 1024**2)
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
                    child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW'), 0o400, dir_fd=fd)
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

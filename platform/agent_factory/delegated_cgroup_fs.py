"""Opt-in descriptor-pinned Linux cgroup v2 operations; never auto-provisioned.

Only an operator-selected already delegated subtree is accepted. No ancestor
controller enablement, namespaces, mounts, daemon calls or privilege changes.
"""
from dataclasses import asdict, dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

try:
    from .process_enforcement import birth, boot_id, same_birth
except ImportError:  # Standalone isolated guardian.
    from process_enforcement import birth, boot_id, same_birth  # pyright: ignore[reportMissingImports]

_FILES = frozenset({"cgroup.type", "cgroup.events", "cgroup.procs", "cpu.max", "memory.max", "memory.swap.max", "pids.max"})
_WRITES = frozenset({"cpu.max", "memory.max", "memory.swap.max", "pids.max", "cgroup.procs", "cgroup.kill"})


class DelegatedCgroupError(RuntimeError):
    pass


def require(value):
    if not value:
        raise DelegatedCgroupError("DELEGATED_CGROUP_UNCONFIRMED")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class DelegatedCgroupConfig:
    root_path: str
    root_device: int
    root_inode: int
    boot_id: str
    cpu_quota_us: int
    cpu_period_us: int
    memory_bytes: int
    swap_bytes: int
    pids_max: int

    def __post_init__(self):
        require(type(self.root_path) is str and self.root_path.startswith("/")
                and "\x00" not in self.root_path and ".." not in self.root_path.split("/"))
        for value, low, high in ((self.root_device, 0, 2**63-1), (self.root_inode, 1, 2**63-1),
                (self.cpu_quota_us, 1000, 10**9), (self.cpu_period_us, 1000, 1000000),
                (self.memory_bytes, 32*1024*1024, 2**40), (self.swap_bytes, 0, 2**40), (self.pids_max, 1, 4096)):
            require(type(value) is int and low <= value <= high)
        require(type(self.boot_id) is str and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", self.boot_id))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        require(type(value) is dict and set(value) == set(cls.__dataclass_fields__))
        return cls(**value)

    @property
    def fingerprint(self):
        return digest(asdict(self))

    def controls(self):
        return {"cpu.max": f"{self.cpu_quota_us} {self.cpu_period_us}", "memory.max": str(self.memory_bytes),
                "memory.swap.max": str(self.swap_bytes), "pids.max": str(self.pids_max)}


class LinuxDelegatedCgroupFS:
    """No mutation during construction. Each operation reopens original pins."""
    def __init__(self, config):
        require(sys.platform == "linux" and type(config) is DelegatedCgroupConfig)
        self.config = config
        self._directory = getattr(os, "O_DIRECTORY")
        self._nofollow = getattr(os, "O_NOFOLLOW")

    def validate(self):
        root = self._root()
        try:
            self._prerequisites(root)
        finally:
            os.close(root)

    def _read_fd(self, parent, name):
        fd = os.open(name, os.O_RDONLY | self._nofollow, dir_fd=parent)
        try:
            data = os.read(fd, 65537)
            require(len(data) <= 65536)
            return data.decode("ascii").strip()
        finally:
            os.close(fd)

    def _root(self):
        require(boot_id() == self.config.boot_id)
        fd = os.open("/", os.O_RDONLY | self._directory | self._nofollow)
        try:
            for part in Path(self.config.root_path).parts[1:]:
                next_fd = os.open(part, os.O_RDONLY | self._directory | self._nofollow, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            value = os.fstat(fd)
            require((value.st_dev, value.st_ino) == (self.config.root_device, self.config.root_inode))
            # Linux fstatfs magic: a normal fake directory cannot be selected as
            # a real backend. Buffer is larger than Linux struct statfs.
            libc = ctypes.CDLL(None, use_errno=True)
            function = libc.fstatfs
            function.argtypes = [ctypes.c_int, ctypes.c_void_p]
            function.restype = ctypes.c_int
            result = (ctypes.c_long * 64)()
            require(function(fd, ctypes.byref(result)) == 0 and result[0] == 0x63677270)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _prerequisites(self, root):
        require(self._read_fd(root, "cgroup.type") == "domain")
        require({"cpu", "memory", "pids"} <= set(self._read_fd(root, "cgroup.subtree_control").split()))
        # Non-root domain controller delegation requires no internal tasks.
        require(not self._read_fd(root, "cgroup.procs"))

    def root_identity(self):
        fd = self._root()
        try:
            return {"device": self.config.root_device, "inode": self.config.root_inode, "bootId": self.config.boot_id}
        finally:
            os.close(fd)

    def _child(self, root, pin):
        require(type(pin) is dict and set(pin) == {"name", "device", "inode", "bootId", "configSha256"})
        require(type(pin["name"]) is str and re.fullmatch(r"af-[a-f0-9]{32}", pin["name"]))
        require(pin["bootId"] == self.config.boot_id and pin["configSha256"] == self.config.fingerprint)
        child = os.open(pin["name"], os.O_RDONLY | self._directory | self._nofollow, dir_fd=root)
        value = os.fstat(child)
        if (value.st_dev, value.st_ino) != (pin["device"], pin["inode"]):
            os.close(child)
            raise DelegatedCgroupError("DELEGATED_CGROUP_IDENTITY_CHANGED")
        return child

    def create(self, name):
        require(type(name) is str and re.fullmatch(r"af-[a-f0-9]{32}", name))
        root = self._root()
        child = None
        try:
            self._prerequisites(root)
            os.mkdir(name, mode=0o700, dir_fd=root)  # EEXIST never adopts foreign work.
            child = os.open(name, os.O_RDONLY | self._directory | self._nofollow, dir_fd=root)
            value = os.fstat(child)
            require(value.st_dev == self.config.root_device)
            return {"name": name, "device": value.st_dev, "inode": value.st_ino,
                    "bootId": self.config.boot_id, "configSha256": self.config.fingerprint}
        finally:
            if child is not None:
                os.close(child)
            os.close(root)

    def read(self, pin, name):
        require(name in _FILES)
        root = self._root()
        child = None
        try:
            child = self._child(root, pin)
            return self._read_fd(child, name)
        finally:
            if child is not None:
                os.close(child)
            os.close(root)

    def write(self, pin, name, value):
        require(name in _WRITES and type(value) is str and len(value) <= 128 and "\n" not in value)
        root = self._root()
        child = fd = None
        try:
            child = self._child(root, pin)
            require(self._read_fd(child, "cgroup.type") == "domain")
            fd = os.open(name, os.O_WRONLY | self._nofollow, dir_fd=child)
            require(os.write(fd, value.encode("ascii")) == len(value))
        finally:
            if fd is not None:
                os.close(fd)
            if child is not None:
                os.close(child)
            os.close(root)

    def process_identity(self, pid):
        return birth(pid)

    def attach(self, pin, identity):
        require(same_birth(self.process_identity(identity["pid"]), identity))
        self.write(pin, "cgroup.procs", str(identity["pid"]))
        require(same_birth(self.process_identity(identity["pid"]), identity))
        require(identity["pid"] in [int(value) for value in self.read(pin, "cgroup.procs").split()])

    def remove(self, pin):
        root = self._root()
        child = None
        try:
            child = self._child(root, pin)
            events = dict(line.split() for line in self._read_fd(child, "cgroup.events").splitlines())
            require(events.get("populated") == "0")
            require(not any(stat.S_ISDIR(os.stat(name, dir_fd=child, follow_symlinks=False).st_mode)
                            for name in os.listdir(child)))
            # Kernel rmdir itself rejects a group repopulated after this read.
            current = os.stat(pin["name"], dir_fd=root, follow_symlinks=False)
            require((current.st_dev, current.st_ino) == (pin["device"], pin["inode"]))
            os.rmdir(pin["name"], dir_fd=root)
        finally:
            if child is not None:
                os.close(child)
            os.close(root)

    def absent(self, pin):
        root = self._root()
        try:
            try:
                os.stat(pin["name"], dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                return True
            return False
        finally:
            os.close(root)

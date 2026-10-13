"""Pinned SSH identities shared by enrollment and trusted runtime adapters."""
from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Callable

from .store import digest


def require(value):
    if not value:
        # Preserve the persisted adapter's existing validation error code.
        raise ValueError('PLATFORM_ORX_RUNTIME_UNCONFIRMED')


def private_directory(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == getattr(os, 'getuid')())
    return path


@dataclass(frozen=True, repr=False)
class SSHAgentLease:
    socket: str
    public_key: str
    check: Callable = field(repr=False)
    def validate(self):
        self.check()
        path = Path(self.socket)
        private_directory(path.parent)
        info = path.lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == getattr(os, 'getuid')() and stat.S_IMODE(info.st_mode) == 0o600)
        require(re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]{40,120}', self.public_key))
    def __repr__(self): return 'SSHAgentLease(credentials=<redacted>)'


@dataclass(frozen=True)
class SSHServer:
    reference: str
    owner: str
    revision: str
    name: str
    address: str
    port: int
    username: str
    host_key: str
    allowed_root: str
    credential_ref: str
    credential_revision: str
    def validate(self):
        require(re.fullmatch('[A-Za-z0-9_.-]{1,80}', self.reference) and self.owner and self.revision)
        ipaddress.ip_address(self.address)
        require(type(self.port) is int and 1 <= self.port <= 65535)
        require(re.fullmatch('[a-z_][a-z0-9_-]{0,31}', self.username))
        require(re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]{40,120}', self.host_key))
        root = PurePosixPath(self.allowed_root)
        require(root.is_absolute() and '..' not in root.parts and not any(c in str(root) for c in '\n\r,:'))
    def pin(self): return digest(self.__dict__)

    def scope_pin(self):
        return digest({key: getattr(self, key) for key in
            ('reference', 'owner', 'address', 'port', 'username', 'host_key', 'allowed_root')})



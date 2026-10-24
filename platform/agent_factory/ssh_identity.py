"""Pinned SSH identities shared by enrollment and trusted runtime adapters."""
from dataclasses import dataclass, field
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Callable

from .store import digest
from .personal_remote_provider import hostname
from .ssh_credentials import host_identity, ssh_username


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
    def __post_init__(self):
        object.__setattr__(self, 'public_key', host_identity(self.public_key)[0])
    def validate(self):
        self.check()
        path = Path(self.socket)
        private_directory(path.parent)
        info = path.lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == getattr(os, 'getuid')() and stat.S_IMODE(info.st_mode) == 0o600)
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
    actor: str | None = field(default=None, repr=False, compare=False)
    def validate(self):
        require(re.fullmatch('[A-Za-z0-9_.-]{1,80}', self.reference) and self.owner and self.revision)
        require(hostname(self.address) == self.address)
        require(type(self.port) is int and 1 <= self.port <= 65535)
        require(ssh_username(self.username) == self.username)
        require(host_identity(self.host_key)[0] == self.host_key)
        root = PurePosixPath(self.allowed_root)
        require(root.is_absolute() and '..' not in root.parts and not any(ord(c) < 32 for c in str(root)))
    def pin(self): return digest({key: value for key, value in self.__dict__.items() if key != 'actor'})

    def scope_pin(self):
        return digest({key: getattr(self, key) for key in
            ('reference', 'owner', 'address', 'port', 'username', 'host_key', 'allowed_root')})


def pinned_ssh(server, lease, local, command, forward=None):
    """Use exactly the member's endpoint, key and host identity for one process."""
    identity = local / 'identity.pub'; identity.write_text(lease.public_key + '\n'); identity.chmod(0o600)
    known = local / 'known_hosts'; known.write_text('factory-pinned ' + server.host_key + '\n'); known.chmod(0o600)
    args = ['ssh', '-F', 'none', '-a', '-T', '-o', 'HostKeyAlias=factory-pinned',
        '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known}', '-o', 'GlobalKnownHostsFile=/dev/null',
        '-o', 'IdentitiesOnly=yes', '-o', f'IdentityAgent={lease.socket}', '-i', str(identity),
        '-o', 'BatchMode=yes', '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
        '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
        '-o', 'PermitLocalCommand=no', '-o', 'ExitOnForwardFailure=yes', '-o', 'StreamLocalBindUnlink=no',
        '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']
    if forward: args += ['-R', forward]
    args += ['-l', server.username, '-p', str(server.port), server.address, command]
    return subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, bufsize=-1)

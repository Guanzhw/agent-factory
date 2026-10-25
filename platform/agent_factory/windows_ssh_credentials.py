"""Per-invocation Windows SSH credentials over the existing scoped vault."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import shutil
import sys
import sysconfig
import tempfile
import threading
import time
import uuid
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .windows_ssh_process import WindowsSSHProcess

from cryptography.hazmat.primitives import serialization

from .personal_remote_provider import RemoteConnectionError
from .ssh_credentials import PROVIDER_ID


def _unavailable():
    return RemoteConnectionError('SSH_CREDENTIAL_UNAVAILABLE')


@dataclass(eq=False)
class _Carrier:
    cancelled: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    process: WindowsSSHProcess | None = None


@dataclass(frozen=True, repr=False)
class WindowsSSHLease:
    manager: WindowsSSHCredentials
    scope: dict
    guard: Callable[[], None]
    public_key: str
    expires_at: float

    def validate(self):
        self.guard()
        with self.manager.lock:
            closed = self.manager.closed
        if closed or time.monotonic() >= self.expires_at or not self.manager.vault.authorize(**self.scope):
            raise _unavailable()

    def open(self, server, command, *, forward=None, deadline):
        return self.manager.open(self, server, command, forward=forward, deadline=deadline)


class WindowsSSHCredentials:
    def __init__(self, vault, *, max_agents, seconds):
        from . import windows_ssh_support as w
        if type(max_agents) is not int or not 1 <= max_agents <= 64 or seconds <= 0:
            raise ValueError('SSH lease limits invalid')
        self.vault, self.max_agents, self.seconds = vault, max_agents, seconds
        self.lock = threading.RLock()
        self.closed = False
        self.active = set()
        self.root = Path(tempfile.gettempdir()) / ('af-ssh-' + uuid.uuid4().hex)
        w.directory(self.root)

    @staticmethod
    def paths():
        return (Path(os.environ['SystemRoot']) / 'System32' / 'OpenSSH' / 'ssh.exe',
                Path(sysconfig.get_path('scripts')) / 'agent-factory-ssh-askpass.exe')

    def diagnostic(self):
        return None if all(path.is_file() for path in self.paths()) else 'SSH_SYSTEM_CLIENT_UNAVAILABLE'

    def _key(self, scope):
        secret = self.vault.resolve(**scope)
        try:
            return serialization.load_ssh_private_key(base64.b64decode(secret.password, validate=True), password=None)
        finally:
            secret = None

    @staticmethod
    def _public(key):
        return key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()

    def acquire(self, server, destination, guard):
        if code := self.diagnostic():
            raise RemoteConnectionError(code)
        guard()
        scope = dict(owner=server.owner, reference=server.credential_ref,
                     revision=server.credential_revision, provider_id=PROVIDER_ID, destination=destination)
        if not self.vault.authorize(**scope):
            raise _unavailable()
        key = None
        try:
            key = self._key(scope)
            lease = WindowsSSHLease(self, scope, guard, self._public(key), time.monotonic() + self.seconds)
            lease.validate()
            return lease
        except RemoteConnectionError:
            raise
        except Exception:
            raise _unavailable() from None
        finally:
            key = None

    @contextmanager
    def open(self, lease, server, command, *, forward, deadline):
        from . import windows_ssh_support as w
        from .windows_ssh_process import WindowsSSHProcess
        if code := self.diagnostic():
            raise RemoteConnectionError(code)
        lease.validate()
        carrier = _Carrier()
        with self.lock:
            if self.closed:
                raise _unavailable()
            if len(self.active) >= self.max_agents:
                raise RemoteConnectionError('SSH_AGENT_CAPACITY')
            self.active.add(carrier)
        folder = self.root / uuid.uuid4().hex
        password = bytearray()
        pipe = thread = process = key = None
        errors = []
        deadline = min(deadline, lease.expires_at)
        try:
            lease.validate()
            key = self._key(lease.scope)
            if self._public(key) != lease.public_key:
                raise _unavailable()
            password = bytearray(secrets.token_hex(32).encode('ascii'))
            w.directory(folder)
            identity = folder / 'identity'
            w.write_private(identity, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                                        serialization.BestAvailableEncryption(bytes(password))))
            key = None
            w.write_private(Path(str(identity) + '.pub'), (lease.public_key + '\n').encode())
            known = folder / 'known_hosts'
            w.write_private(known, ('factory-pinned ' + server.host_key + '\n').encode())
            ssh, helper = self.paths()
            pipe_name = r'\\.\pipe\af-ssh-' + uuid.uuid4().hex
            pipe = w.server_pipe(pipe_name)
            args = [str(ssh), '-F', 'none', '-a', '-T', '-o', 'HostKeyAlias=factory-pinned',
                    '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known}',
                    '-o', 'GlobalKnownHostsFile=none', '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
                    '-o', 'AddKeysToAgent=no', '-i', 'identity', '-o', 'BatchMode=no',
                    '-o', 'PreferredAuthentications=publickey', '-o', 'NumberOfPasswordPrompts=1',
                    '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
                    '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none', '-o', 'ControlMaster=no',
                    '-o', 'ControlPath=none', '-o', 'PermitLocalCommand=no', '-o', 'ExitOnForwardFailure=yes',
                    '-o', 'StreamLocalBindUnlink=no', '-o', 'ConnectTimeout=10',
                    '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']
            if forward:
                args += ['-R', forward]
            args += ['-l', server.username, '-p', str(server.port), server.address, command]
            env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'ProgramData', 'TEMP', 'TMP') if name in os.environ}
            env.update({'PATH': str(ssh.parent), 'SSH_ASKPASS': str(helper), 'SSH_ASKPASS_REQUIRE': 'force',
                        'FACTORY_SSH_KEY': str(identity), 'FACTORY_SSH_PIPE': pipe_name,
                        'FACTORY_SSH_CONTROLLER': str(os.getpid())})
            spawned = WindowsSSHProcess(args, env, cwd=folder)
            process = spawned
            broker_deadline = min(deadline, time.monotonic() + 6)

            def broker():
                try:
                    w.connect(pipe, broker_deadline, carrier.cancelled)
                    w.check_client(pipe, spawned.process_handle, spawned.pid, helper,
                                   w.image(w.win32api.GetCurrentProcess()), sys.executable)
                    if w.transfer(pipe, broker_deadline, size=16, cancelled=carrier.cancelled) != b'READY':
                        raise _unavailable()
                    lease.validate()
                    if carrier.cancelled.is_set() or time.monotonic() >= deadline:
                        raise _unavailable()
                    w.transfer(pipe, broker_deadline, payload=bytes(password), cancelled=carrier.cancelled)
                    if w.transfer(pipe, broker_deadline, size=16, cancelled=carrier.cancelled) != b'RECEIVED':
                        raise _unavailable()
                except Exception:
                    errors.append(_unavailable())
                    try:
                        spawned.kill()
                    except Exception:
                        errors.append(RuntimeError('SSH_PROCESS_CLEANUP_INCOMPLETE'))
                finally:
                    pipe.Close()

            thread = threading.Thread(target=broker, name='factory-ssh-askpass', daemon=True)
            lease.validate()
            with self.lock:
                if self.closed or carrier.cancelled.is_set() or time.monotonic() >= deadline:
                    raise _unavailable()
                carrier.process = process
                thread.start()
                process.resume()
            yield process
        finally:
            carrier.cancelled.set()
            key = None
            cleanup_error = None
            try:
                if process is not None:
                    try:
                        process.close()
                    except Exception as exc:
                        cleanup_error = exc
                if thread is not None and thread.ident is not None:
                    thread.join(timeout=7)
                    if thread.is_alive():
                        cleanup_error = RuntimeError('SSH_BROKER_CLEANUP_INCOMPLETE')
                elif pipe is not None:
                    pipe.Close()
                if folder.exists():
                    shutil.rmtree(folder)
            except Exception as exc:
                cleanup_error = exc
            finally:
                password[:] = b'\0' * len(password)
                with self.lock:
                    self.active.discard(carrier)
                    carrier.done.set()
            if cleanup_error is not None:
                raise cleanup_error
        if errors:
            raise errors[-1]

    def close(self):
        with self.lock:
            self.closed = True
            active = tuple(self.active)
            for carrier in active:
                carrier.cancelled.set()
        for carrier in active:
            if carrier.process is not None:
                carrier.process.kill()
        end = time.monotonic() + 12
        for carrier in active:
            if not carrier.done.wait(max(0, end - time.monotonic())):
                raise RuntimeError('SSH_CARRIER_CLEANUP_INCOMPLETE')
        if self.root.exists():
            shutil.rmtree(self.root)

"""Trusted owner SSH-agent bindings and pinned package custody on Linux servers.

HTTP accepts an opaque server reference and a directory within its fixed private
root. It never accepts keys, commands, hostnames or grants remote access.
"""
from dataclasses import dataclass, field
import hashlib
import gzip
try:
    import fcntl
except ImportError:
    fcntl = None
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import stat
import subprocess
import threading
import time
from typing import Callable
from tempfile import TemporaryDirectory

from .owner_runtime_broker import OwnerRuntimeBroker
from .platform_openresearch import PlatformOrxProvider, PlatformOpenResearchConfig
from .runtime_packages.openresearch_v1.entry import private_directory, require
from .runtime_packages.openresearch_v1.supervisor import digest

PROVIDER_ID = 'ssh-openresearch-session-v1'
BASE = Path(__file__).resolve().parent / 'runtime_packages/openresearch_v1'


def file_hash(path):
    with path.open('rb') as source: return hashlib.file_digest(source, 'sha256').hexdigest()


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
        root = Path(self.allowed_root)
        require(root.is_absolute() and '..' not in root.parts and not any(c in str(root) for c in '\n\r,:'))
    def pin(self): return digest(self.__dict__)


@dataclass(frozen=True, repr=False)
class SSHOpenResearchConfig:
    runtime: PlatformOpenResearchConfig
    servers: tuple[SSHServer, ...]
    credentials: Callable = field(repr=False)
    def __repr__(self): return 'SSHOpenResearchConfig(credentials=<redacted>)'


class _Channel:
    def __init__(self, process):
        self.process, self.lock, self.pending = process, threading.RLock(), b''
    def call(self, action, body, **values):
        with self.lock:
            identifier = secrets.token_hex(12)
            payload = json.dumps({'id': identifier, 'action': action, 'body': body, **values}).encode() + b'\n'
            require(len(payload) <= 1048576)
            require(self.process.poll() is None)
            self.process.stdin.write(payload); self.process.stdin.flush()
            deadline = time.monotonic() + (150 if action in {'prepare', 'request'} else 40)
            while b'\n' not in self.pending:
                remaining = deadline - time.monotonic()
                require(remaining > 0)
                ready, _, _ = select.select([self.process.stdout], [], [], remaining)
                require(ready)
                chunk = os.read(self.process.stdout.fileno(), 65536)
                require(chunk); self.pending += chunk; require(len(self.pending) <= 1048576)
            line, self.pending = self.pending.split(b'\n', 1)
            response = json.loads(line)
            require(response['id'] == identifier and response['ok'] is True)
            return response['result']
    def close(self):
        try: self.process.stdin.close()
        except Exception: pass
        try: self.process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)


class SSHOrxProvider(PlatformOrxProvider):
    provider_id = PROVIDER_ID
    def verify(self, owner, configuration):
        result = super().verify(owner, configuration)
        return {**result, 'identityBasis': 'owner-pinned-ssh-package-private-native-project'}


class SSHOpenResearchPackage:
    provider_id = PROVIDER_ID
    def __init__(self, config, root):
        require(isinstance(config, SSHOpenResearchConfig) and callable(config.credentials))
        config.runtime.validate()
        for server in config.servers: server.validate()
        require(len({server.reference for server in config.servers}) == len(config.servers))
        self.config, self.root = config, Path(root).resolve()
        self.root.mkdir(mode=0o700, exist_ok=True); private_directory(self.root)
        self.files = {name: BASE / name for name in ('__init__.py', 'entry.py', 'bridge.py', 'supervisor.py', 'ssh_agent.py')}
        self.files.update(orx=Path(config.runtime.orx_path), opencode=Path(config.runtime.opencode_path))
        self.code_pins = {name: file_hash(path) for name, path in self.files.items()}
        self.installer_pin = file_hash(BASE / 'ssh_install.py')
        self.version = 'ssh-openresearch-v1-' + digest({'files': self.code_pins, 'image': config.runtime.image,
            'installer': self.installer_pin})[:24]
        self.live = {}; self.lock = threading.RLock(); self.provider = SSHOrxProvider(self)

    def servers(self, owner):
        return [{'reference': s.reference, 'name': s.name, 'defaultDirectory': str(Path(s.allowed_root) / 'research')}
            for s in self.config.servers if s.owner == owner]

    def _server(self, owner, reference):
        server = next((s for s in self.config.servers if s.reference == reference and s.owner == owner), None)
        if server is None: raise ValueError('SSH_OWNER_SERVER_UNAVAILABLE')
        return server

    def selection(self, owner, reference, directory):
        server = self._server(owner, reference)
        path = Path(directory)
        require(path.is_absolute() and path != Path(server.allowed_root) and path.is_relative_to(server.allowed_root)
            and '..' not in path.parts and len(str(path / 'connections' / ('a' * 24) / 'broker.sock').encode()) < 104 and not any(c in str(path) for c in '\n\r,:'))
        lease = self._credential(server)
        return {'location': 'ssh', 'serverRef': server.reference, 'serverRevision': server.revision,
            'serverPin': server.pin(), 'identityPin': hashlib.sha256(lease.public_key.encode()).hexdigest(),
            'remoteDirectory': str(path)}

    def _credential(self, server):
        lease = self.config.credentials(owner=server.owner, reference=server.credential_ref,
            revision=server.credential_revision, destination=server.pin())
        require(isinstance(lease, SSHAgentLease)); lease.validate()
        return lease

    def _scope(self, body):
        require(body['packageVersion'] == self.version)
        server = self._server(body['ownerId'], body['serverRef'])
        require(self.selection(body['ownerId'], server.reference, body['remoteDirectory']) == {
            key: body[key] for key in ('location', 'serverRef', 'serverRevision', 'serverPin', 'identityPin', 'remoteDirectory')})
        return server, self._credential(server)

    def _ssh(self, server, lease, local, command, forward=None):
        # No ~/.ssh config, agent forwarding, password fallback, proxy commands,
        # inherited forwards, DNS, multiplexed sessions or host-key learning.
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
        args += ['-p', str(server.port), server.username + '@' + server.address, command]
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, bufsize=-1)
        assert process.stdin is not None and process.stdout is not None
        return process

    def _image(self):
        archive = self.root / 'image.tar'
        with (self.root / 'image.lock').open('a+b') as fence:
            getattr(fcntl, 'flock')(fence, getattr(fcntl, 'LOCK_EX'))
            try:
                pin = self.root / 'image.json'
                if not archive.exists():
                    temporary = self.root / 'image.pending'
                    if temporary.exists():
                        info = temporary.lstat()
                        require(stat.S_ISREG(info.st_mode) and info.st_uid == getattr(os, 'getuid')() and info.st_nlink == 1)
                        temporary.unlink()
                    process = subprocess.Popen(['docker', 'save', self.config.runtime.image], stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, bufsize=0)
                    assert process.stdout is not None
                    deadline = time.monotonic() + 120
                    try:
                        with gzip.open(temporary, 'wb', compresslevel=1) as output:
                            while True:
                                remaining = deadline - time.monotonic(); require(remaining > 0)
                                ready, _, _ = select.select([process.stdout], [], [], remaining); require(ready)
                                chunk = os.read(process.stdout.fileno(), 65536)
                                if not chunk: break
                                output.write(chunk)
                        require(process.wait(timeout=max(1, deadline - time.monotonic())) == 0
                            and temporary.stat().st_size <= 1024**3)
                    finally:
                        if process.poll() is None: process.kill(); process.wait(timeout=5)
                    temporary.chmod(0o600)
                    pin.write_text(json.dumps({'image': self.config.runtime.image, 'sha256': file_hash(temporary)}))
                    pin.chmod(0o600); temporary.replace(archive)
                require(archive.is_file() and not archive.is_symlink() and archive.stat().st_nlink == 1
                    and pin.is_file() and not pin.is_symlink())
                require(json.loads(pin.read_text()) == {'image': self.config.runtime.image, 'sha256': file_hash(archive)})
                return archive
            finally: getattr(fcntl, 'flock')(fence, getattr(fcntl, 'LOCK_UN'))

    def _install(self, server, lease, body, local, nonce):
        self.config.runtime.validate()
        require(file_hash(BASE / 'ssh_install.py') == self.installer_pin)
        require(all(file_hash(path) == self.code_pins[name] for name, path in self.files.items()))
        files = {**self.files, 'image.tar': self._image()}
        manifest = {'allowedRoot': server.allowed_root, 'directory': body['remoteDirectory'],
            'image': self.config.runtime.image, 'nonce': nonce,
            'files': {name: {'size': path.stat().st_size, 'sha256': file_hash(path)}
                for name, path in files.items()}}
        command = 'python3 -I -B -c ' + shlex.quote((BASE / 'ssh_install.py').read_text())
        process = self._ssh(server, lease, local, command)
        assert process.stdin is not None and process.stdout is not None
        writer = process.stdin
        failure = []
        def transfer():
            try:
                writer.write(json.dumps(manifest).encode() + b'\n')
                for path in files.values():
                    with path.open('rb') as source:
                        while chunk := source.read(1024**2): writer.write(chunk)
                writer.close()
            except Exception: failure.append(True)
        worker = threading.Thread(target=transfer, daemon=True); worker.start(); worker.join(timeout=240)
        if worker.is_alive() or failure:
            process.kill(); process.wait(timeout=5); raise ValueError('SSH_INSTALL_UNCONFIRMED')
        try:
            require(process.wait(timeout=120) == 0)
            raw = process.stdout.read(4097); require(len(raw) <= 4096)
            result = json.loads(raw); require(result['installed'] is True)
            require(result['package'] == str(Path(body['remoteDirectory']) / 'factory_package')
                and result['control'] == str(Path(body['remoteDirectory']) / 'connections'))
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
        return result

    def prepare(self, body, handle):
        with self.lock:
            server, lease = self._scope(body); handle.check()
            if body['id'] in self.live and self.check(body): return
            old = self.live.pop(body['id'], None)
            if old: old['channel'].close(); old['broker'].close(); old['local'].cleanup()
            nonce = secrets.token_hex(12); folder = TemporaryDirectory(prefix='af-orx-ssh-', dir='/tmp')
            local = Path(folder.name); private_directory(local)
            try: result = self._install(server, lease, body, local, nonce)
            except Exception: folder.cleanup(); raise
            custody = self
            class OwnedHandle:
                body, service = handle.body, handle.service
                def check(self): custody._scope(body); handle.check()
                def credential(self): self.check(); return handle.credential()
            broker = OwnerRuntimeBroker(local / 'broker.sock', OwnedHandle(), ttl=self.config.runtime.max_active_seconds)
            remote_socket = str(Path(result['control']) / nonce / 'broker.sock')
            require(len(remote_socket.encode()) < 104)
            try: broker.start()
            except Exception: broker.close(); folder.cleanup(); raise
            runner = "import sys;sys.path.insert(0,sys.argv[1]);from factory_package.ssh_agent import run;run()"
            command = 'python3 -I -B -c ' + shlex.quote(runner) + ' ' + shlex.quote(body['remoteDirectory'])
            try: process = self._ssh(server, lease, local, command, remote_socket + ':' + str(broker.path))
            except Exception: broker.close(); folder.cleanup(); raise
            assert process.stdin is not None
            channel = _Channel(process)
            runtime = self.config.runtime
            package = Path(result['package'])
            init = {'root': str(Path(body['remoteDirectory']) / 'data'), 'version': self.version,
                'brokerSocket': remote_socket, 'capability': broker.capability,
                'config': {'orx_path': str(package / 'orx'), 'opencode_path': str(package / 'opencode'),
                    'image': runtime.image, 'max_active': runtime.max_active, 'lease_seconds': runtime.lease_seconds,
                    'max_active_seconds': runtime.max_active_seconds}}
            try:
                process.stdin.write(json.dumps(init).encode() + b'\n'); process.stdin.flush()
                self.live[body['id']] = {'body': body, 'broker': broker, 'channel': channel, 'lease': lease, 'local': folder}
                channel.call('prepare', body)
            except Exception:
                channel.close(); broker.close(); folder.cleanup(); self.live.pop(body['id'], None)
                raise ValueError('SSH_PREPARATION_UNCONFIRMED') from None

    def check(self, body):
        try:
            self._scope(body)
            live = self.live.get(body['id'])
            if not live or not live['broker'].authorized(live['broker'].capability): return False
            live['broker'].handle.check(); live['lease'].validate()
            return live['channel'].call('check', body) is True
        except Exception: return False

    def request(self, body, method, path, payload=None):
        self._scope(body)
        live = self.live[body['id']]; live['broker'].handle.check(); live['lease'].validate()
        return live['channel'].call('request', body, method=method, path=path, payload=payload)

    def stop(self, body):
        with self.lock:
            live = self.live.get(body['id'])
            if not live: return False  # Lost custody is unknown, never absence.
            try: stopped = live['channel'].call('stop', body) is True
            except Exception: stopped = False
            live['channel'].close(); live['broker'].close(); live['local'].cleanup(); self.live.pop(body['id'], None)
            return stopped

    def lifecycle_policy(self):
        runtime = self.config.runtime
        return {'leaseSeconds': runtime.lease_seconds, 'maxActiveSeconds': runtime.max_active_seconds,
            'workExtendsLease': True, 'automaticWorkReplay': False,
            'interruptedWorkRecovery': False, 'externalToolNetwork': False}
    def connection_configuration(self, body):
        return {'origin': 'https://' + body['id'] + '.platform.invalid', 'credentialRef': body['id'],
            'credentialRevision': body['modelRevision'], 'authMode': 'bearer', 'projectId': body['projectId'],
            'sessionDefaults': {'harness': 'opencode', 'model': 'factory/owner-model'}}
    def close(self):
        for live in list(self.live.values()): self.stop(live['body'])

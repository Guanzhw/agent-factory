"""Platform location descriptor for a pinned original OpenResearch package.

Operators supply reviewed cached artifacts and an immutable local image. Owners
never install ORX, provide shell commands, select host paths or expose TCP ports.
Separate bounded containers mount only one owner's persistent environment.
"""
from contextlib import contextmanager
from dataclasses import dataclass
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import subprocess
import threading
import time

from .orx_pins import LINUX_SHA256
from .owner_runtime_broker import OwnerRuntimeBroker
from .personal_orx_transport import PersonalOrxHTTPS, PersonalOrxProvider
from .personal_remote_provider import RemoteConnectionError, SecretLease
from .runtime_packages.openresearch_v1.entry import BinaryPin, RuntimeConfig, build_command, environment, private_directory, require, verify_no_startup_dispatch
from .store import digest

PROVIDER_ID = 'platform-openresearch-session-v1'
PACKAGE_VERSION = 'openresearch-f336b121-opencode-1.18.35-v1'
OPENCODE_SHA256 = '77b2cfe4b97df6f15c3673b22100b9f79c711f25ecb9bf513bb82526b15d24fa'


@dataclass(frozen=True)
class PlatformOpenResearchConfig:
    orx_path: str
    opencode_path: str
    image: str
    max_active: int = 2
    lease_seconds: int = 1800

    def validate(self):
        if sys.platform != 'linux' or fcntl is None: raise ValueError('ENVIRONMENT_PLATFORM_UNSUPPORTED')
        require(type(self.max_active) is int and 1 <= self.max_active <= 8)
        require(type(self.lease_seconds) is int and 60 <= self.lease_seconds <= 3600)
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', self.image))
        BinaryPin(self.orx_path, LINUX_SHA256).verify()
        BinaryPin(self.opencode_path, OPENCODE_SHA256).verify()


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=10):
        super().__init__('localhost', timeout=timeout); self.path = path
    def connect(self):
        self.sock = socket.socket(getattr(socket, 'AF_UNIX'), socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        descriptor = os.open(self.path.parent, getattr(os, 'O_DIRECTORY') | getattr(os, 'O_NOFOLLOW'))
        try: self.sock.connect(f'/proc/self/fd/{descriptor}/{self.path.name}')
        finally: os.close(descriptor)


class PlatformOpenResearchPackage:
    version, provider_id = PACKAGE_VERSION, PROVIDER_ID

    def __init__(self, config, root):
        config.validate()
        self.config, self.root = config, Path(root).resolve()
        self.root.mkdir(mode=0o700, exist_ok=True); private_directory(self.root)
        self.scope = hashlib.sha256(str(self.root).encode()).hexdigest()
        self.live = {}; self.lock = threading.RLock()
        self.provider = PlatformOrxProvider(self)

    def __repr__(self): return 'PlatformOpenResearchPackage(credentials=<redacted>)'

    def _root(self, body):
        require(body['packageVersion'] == self.version and re.fullmatch('env-[a-f0-9]{32}', body['id']))
        path = self.root / body['id']; path.mkdir(mode=0o700, exist_ok=True)
        return private_directory(path)

    @contextmanager
    def _capacity(self):
        if sys.platform != 'linux' or fcntl is None: raise ValueError('ENVIRONMENT_PLATFORM_UNSUPPORTED')
        with (self.root / 'capacity.lock').open('a+b') as handle:
            getattr(fcntl, 'flock')(handle, getattr(fcntl, 'LOCK_EX'))
            try: yield
            finally: getattr(fcntl, 'flock')(handle, getattr(fcntl, 'LOCK_UN'))

    @staticmethod
    def _docker(*args, timeout=15, env=None):
        result = subprocess.run(['docker', *args], capture_output=True, timeout=timeout, check=False,
            env=env or {'PATH': '/usr/local/bin:/usr/bin:/bin'})
        require(result.returncode == 0)
        return result.stdout

    def _receipt(self, root, body):
        path = self._control(root) / 'runtime.json'
        if not path.exists(): return None
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4096)
        value = json.loads(path.read_text())
        require(value['bodyHash'] == digest(body) and re.fullmatch('factory-orx-[a-f0-9]{32}', value['name']))
        return value

    @staticmethod
    def _control(root):
        # Supervisor receipts/identity markers are outside the writable mount.
        # Application tools cannot forge a removed-container acknowledgement.
        control = root.with_name(root.name + '.control')
        control.mkdir(mode=0o700, exist_ok=True)
        return private_directory(control)

    def _save(self, root, value):
        control = self._control(root)
        temporary = control / 'runtime.pending'
        with temporary.open('w') as handle:
            json.dump(value, handle); handle.flush(); os.fsync(handle.fileno())
        temporary.chmod(0o600); temporary.replace(control / 'runtime.json')

    def _inspect(self, receipt, root):
        value = json.loads(self._docker('inspect', receipt['name']))
        require(len(value) == 1)
        current = value[0]; labels = current['Config']['Labels']
        require(current['Name'] == '/' + receipt['name'] and labels.get('factory.orx.runtime') == receipt['name']
            and labels.get('factory.environment.scope') == self.scope
            and labels.get('factory.environment.body') == receipt['bodyHash'])
        require(current['HostConfig']['NetworkMode'] == 'none' and current['HostConfig']['ReadonlyRootfs'] is True
            and current['HostConfig']['Privileged'] is False
            and current['Config']['User'] == f'{getattr(os, 'getuid')()}:{getattr(os, 'getgid')()}'
            and len([m for m in current['Mounts'] if m['RW']]) == 1
            and next(m for m in current['Mounts'] if m['RW'])['Source'] == str(root))
        if receipt.get('containerId'): require(receipt['containerId'] == current['Id'])
        return current

    def _remove_stopped(self, receipt, root):
        current = self._inspect(receipt, root)
        if current['State']['Running']:
            self._docker('stop', '--time', '5', current['Id'], timeout=15)
            current = self._inspect(receipt, root)
        require(current['State']['Running'] is False and current['State']['Paused'] is False
            and current['State']['Status'] in {'created', 'exited'} and not current['State']['Dead'])
        if current['State']['Status'] == 'exited':
            require(type(current['State']['ExitCode']) is int
                and current['State']['FinishedAt'] not in ('', '0001-01-01T00:00:00Z'))
        self._docker('rm', current['Id'])
        return True

    def _socket_cleanup(self, path):
        if path.exists() or path.is_symlink():
            info = path.lstat()
            require(stat.S_ISSOCK(info.st_mode) and info.st_uid == getattr(os, 'getuid')())
            path.unlink()

    def prepare(self, body, handle):
        self.config.validate(); handle.check()
        with self.lock, self._capacity():
            root = self._root(body)
            live = self.live.get(body['id'])
            if live and live['broker'].authorized(live['broker'].capability) and self.check(body): return
            receipt = self._receipt(root, body)
            if receipt:
                # A broker capability does not survive service restart. Reconcile
                # and stop only the exact owned container before replacing it.
                if not receipt.get('removed'): self._remove_stopped(receipt, root)
                receipt['removed'] = True; self._save(root, receipt)
            if live:
                live['timer'].cancel(); live['broker'].close(); self.live.pop(body['id'], None)
            # Original up can dispatch persisted queues, experiments and child
            # wakeups. Restart must not cross that work boundary implicitly.
            verify_no_startup_dispatch(root / 'orx/orx.db')
            active = self._docker('ps', '--filter', 'label=factory.environment.scope=' + self.scope, '--format', '{{.ID}}').splitlines()
            require(len(active) < self.config.max_active)
            for name in ('sockets', 'home', 'work', 'orx', 'cache', 'proofs', 'xdg'):
                (root / name).mkdir(mode=0o700, exist_ok=True); private_directory(root / name)
            for name in ('config', 'data', 'cache', 'state'):
                (root / 'xdg' / name).mkdir(mode=0o700, exist_ok=True); private_directory(root / 'xdg' / name)
            marker = self._control(root) / 'environment.json'
            if marker.exists():
                require(not marker.is_symlink() and marker.stat().st_size <= 4096 and json.loads(marker.read_text()) == body)
            else:
                require(not any((root / 'orx').iterdir()) and not any((root / 'work').iterdir()))
                with marker.open('x') as handle_file: json.dump(body, handle_file)
                marker.chmod(0o600)
            for name in ('broker.sock', 'orx.sock'): self._socket_cleanup(root / 'sockets' / name)
            broker = OwnerRuntimeBroker(root / 'sockets/broker.sock', handle, ttl=self.config.lease_seconds)
            broker.start()
            name = 'factory-orx-' + os.urandom(16).hex()
            receipt = {'name': name, 'bodyHash': digest(body), 'removed': False}
            self._save(root, receipt)  # Before Docker create, including unknown ack.
            config = RuntimeConfig(str(root), self.config.image, BinaryPin(self.config.orx_path, LINUX_SHA256),
                BinaryPin(self.config.opencode_path, OPENCODE_SHA256), wall_seconds=self.config.lease_seconds,
                pids=256, project_id=body['projectId'], max_output_tokens=4096)
            command = build_command(config, name, broker.capability)
            position = command.index('--network')
            command[position:position] = ['--label', 'factory.environment.scope=' + self.scope,
                '--label', 'factory.environment.body=' + digest(body)]
            private_env = environment(broker.capability, 4096)
            private_env['ORX_FACTORY_PROJECT_ID'] = body['projectId']
            private_env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
            index = command.index('PATH', command.index('--env'))
            command[index] = 'PATH=' + environment(broker.capability)['PATH']
            timer = threading.Timer(self.config.lease_seconds, lambda: self.stop(body)); timer.daemon = True
            self.live[body['id']] = {'broker': broker, 'body': body, 'timer': timer, 'root': root}
            try:
                result = subprocess.run(command, env=private_env, capture_output=True, timeout=60, check=False)
                require(result.returncode == 0)
                receipt['containerId'] = result.stdout.decode().strip()
                require(re.fullmatch('[a-f0-9]{64}', receipt['containerId']))
                self._save(root, receipt)
                self._docker('start', receipt['containerId'])
                timer.start()
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if self.check(body): return
                    time.sleep(0.2)
                raise ValueError('ENVIRONMENT_HEALTH_FAILED')
            except Exception:
                # Runtime receipt stays for exact reconciliation, data stays.
                self.stop(body)
                raise ValueError('ENVIRONMENT_PREPARATION_UNCONFIRMED') from None

    def check(self, body):
        with self.lock:
            live = self.live.get(body['id'])
            if live is None or not live['broker'].authorized(live['broker'].capability): return False
            try:
                live['broker'].handle.check()
                receipt = self._receipt(live['root'], body)
                require(receipt and not receipt.get('removed'))
                require(self._inspect(receipt, live['root'])['State']['Running'])
                status, value = self.request(body, 'GET', '/api/health')
                return status == 200 and value.get('ok') is True and value.get('version') == '0.2.13' and value.get('dashboardProtocol') == 2
            except Exception: return False

    def request(self, body, method, path, payload=None):
        with self.lock:
            live = self.live.get(body['id'])
            if live is None or not live['broker'].authorized(live['broker'].capability):
                raise ValueError('ENVIRONMENT_UNAVAILABLE')
            live['broker'].handle.check()
            path_socket = live['root'] / 'sockets/orx.sock'
            info = path_socket.lstat()
            require(stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == getattr(os, 'getuid')())
        # Original ORX waits for its coding harness on the first message. The
        # private local command needs that bounded startup window; a timeout
        # still remains an unknown acknowledgement and never authorizes replay.
        startup = method == 'POST' and re.fullmatch(r'/api/chat/sessions/[A-Za-z0-9_-]+/message', path)
        client = _UnixHTTP(path_socket, timeout=120 if startup else 10)
        try:
            client.request(method, path, body=None if payload is None else json.dumps(payload), headers={'Content-Type': 'application/json', 'Connection': 'close'})
            response = client.getresponse(); raw = response.read(1048577)
            require(len(raw) <= 1048576)
            return response.status, json.loads(raw)
        finally: client.close()

    def stop(self, body):
        with self.lock:
            root = self._root(body); live = self.live.get(body['id'])
            receipt = self._receipt(root, body)
            try:
                stopped = receipt is None or receipt.get('removed') or self._remove_stopped(receipt, root)
                if receipt:
                    receipt['removed'] = True; self._save(root, receipt)
                if live:
                    live['timer'].cancel(); live['broker'].close(); self.live.pop(body['id'], None)
                return bool(stopped)
            except Exception: return False

    def close(self):
        for live in list(self.live.values()): self.stop(live['body'])

    def connection_configuration(self, body):
        return {'origin': 'https://' + body['id'] + '.platform.invalid', 'credentialRef': body['id'],
            'credentialRevision': body['modelRevision'], 'authMode': 'bearer', 'projectId': body['projectId'],
            'sessionDefaults': {'harness': 'opencode', 'model': 'factory/owner-model'}}


class _PlatformSecrets:
    def __init__(self, package): self.package = package
    def authorize(self, *, owner, reference, revision, destination):
        live = self.package.live.get(reference)
        return bool(live and live['body']['ownerId'] == owner and live['body']['modelRevision'] == revision
            and destination == 'https://' + reference + '.platform.invalid' and self.package.check(live['body']))
    def resolve(self, **scope):
        if not self.authorize(**scope): raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE')
        return SecretLease('runtime-capability', self.package.live[scope['reference']]['broker'].capability)


class _PlatformTransport:
    allows = staticmethod(PersonalOrxHTTPS.allows)
    def __init__(self, package): self.package = package
    def addresses(self, value): return (value,)
    def request(self, destination, address, method, path, lease, payload=None):
        if lease is None: return 401, {'error': 'PLATFORM_CAPABILITY_REQUIRED'}
        match = re.fullmatch(r'https://(env-[a-f0-9]{32})\.platform\.invalid', destination)
        if not match or address != destination or not self.allows(method, path, payload): raise RemoteConnectionError('REMOTE_PATH_DENIED')
        live = self.package.live.get(match[1])
        if not live or not isinstance(lease, SecretLease) or not live['broker'].authorized(lease.password):
            raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE')
        try: return self.package.request(live['body'], method, path, payload)
        except Exception: raise RemoteConnectionError('REMOTE_RESPONSE_UNCONFIRMED') from None


class PlatformOrxProvider(PersonalOrxProvider):
    provider_id = PROVIDER_ID
    policy_revision = PACKAGE_VERSION
    model_credential_custody = 'owner-vault'
    def __init__(self, package):
        self.package = package
        super().__init__(_PlatformSecrets(package), policy_revision=PACKAGE_VERSION, transport=_PlatformTransport(package))
    def configure(self, configuration):
        result = super().configure(configuration)
        live = self.package.live.get(result['credentialRef'])
        if live is None or result != self.package.connection_configuration(live['body']):
            raise RemoteConnectionError('REMOTE_CONFIGURATION_INVALID')
        return result
    def verify(self, owner, configuration):
        result = super().verify(owner, configuration)
        return {**result, 'identityBasis': 'owner-package-private-unix-native-project', 'sourceRevisionVerified': True}

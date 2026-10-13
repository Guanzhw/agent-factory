"""Owner-vault/platform binding around the shared original-package supervisor."""
import subprocess as subprocess  # Compatibility hooks used by custody tests.
import threading as threading  # Compatibility hooks used by custody tests.
import time as time  # Compatibility hooks used by custody tests.
import re
import os
import stat
import sys

from agent_factory.owner_runtime_broker import OwnerRuntimeBroker
from .personal_orx_transport import PersonalOrxHTTPS, PersonalOrxProvider, worktree_file_path
from agent_factory.personal_remote_provider import RemoteConnectionError, SecretLease
from .runtime_packages.openresearch_v1.supervisor import (
    OpenResearchSupervisor, PlatformOpenResearchConfig as PlatformOpenResearchConfig, PACKAGE_VERSION, PROVIDER_ID,
    _UnixHTTP, OPENCODE_SHA256 as OPENCODE_SHA256,
)
from .runtime_packages.openresearch_v1.entry import build_command, verify_no_startup_dispatch


class PlatformOpenResearchPackage(OpenResearchSupervisor):
    def __init__(self, config, root):
        super().__init__(config, root)
        self.provider = PlatformOrxProvider(self)

    def connection_revision(self, body):
        live = self.live.get(body['id'])
        revision = getattr(live['broker'].handle, 'environment_credential_revision', None) if live else None
        return revision if type(revision) is str else body['modelRevision']

    def connection_configuration(self, body):
        return {**super().connection_configuration(body), 'credentialRevision': self.connection_revision(body)}

    @staticmethod
    def _new_broker(path, handle, *, ttl): return OwnerRuntimeBroker(path, handle, ttl=ttl)
    @staticmethod
    def _new_http(path, *, timeout): return _UnixHTTP(path, timeout=timeout)
    @staticmethod
    def _command(config, name, capability): return build_command(config, name, capability)
    @staticmethod
    def _verify_idle(path): return verify_no_startup_dispatch(path)


class _PlatformSecrets:
    def __init__(self, package): self.package = package
    def authorize(self, *, owner, reference, revision, destination):
        live = self.package.live.get(reference)
        return bool(live and live['body']['ownerId'] == owner and self.package.connection_revision(live['body']) == revision
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
    def worktree_file_bytes(self, owner, configuration, session_id, path):
        """One exact owned native worktree file; no caller-supplied host path."""
        if sys.platform != 'linux': raise RemoteConnectionError('NATIVE_FILE_READER_UNAVAILABLE')
        from .runtime_packages.openresearch_v1.entry import require
        require(worktree_file_path(path) and re.fullmatch(r'chat_[A-Za-z0-9_-]{1,190}', session_id)
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', configuration['projectId']))
        scope = self._scope(owner, configuration)
        if not self.secrets.authorize(**scope): raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE')
        live = self.package.live[configuration['credentialRef']]
        require(live['body']['ownerId'] == owner and live['body']['projectId'] == configuration['projectId'])
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        directory = os.open(live['root'], flags | os.O_DIRECTORY)
        try:
            for part in ['orx', 'worktrees', configuration['projectId'], session_id, *path.split('/')[:-1]]:
                following = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
                os.close(directory); directory = following
            file = os.open(path.split('/')[-1], flags, dir_fd=directory)
            try:
                before = os.fstat(file)
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 512000)
                chunks, total = [], 0
                while True:
                    chunk = os.read(file, min(65536, 512001 - total))
                    if not chunk: break
                    chunks.append(chunk); total += len(chunk)
                    require(total <= 512000)
                after = os.fstat(file)
                require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    and total == before.st_size)
                if not self.secrets.authorize(**scope): raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE')
                return b''.join(chunks)
            finally: os.close(file)
        except (OSError, ValueError):
            raise RemoteConnectionError('NATIVE_FILE_UNAVAILABLE') from None
        finally: os.close(directory)
    def verify(self, owner, configuration):
        result = super().verify(owner, configuration)
        return {**result, 'identityBasis': 'owner-package-private-unix-native-project', 'sourceRevisionVerified': True}

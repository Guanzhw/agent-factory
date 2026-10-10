"""Owner-vault/platform binding around the shared original-package supervisor."""
import subprocess as subprocess  # Compatibility hooks used by custody tests.
import threading as threading  # Compatibility hooks used by custody tests.
import time as time  # Compatibility hooks used by custody tests.
import re

from .owner_runtime_broker import OwnerRuntimeBroker
from .personal_orx_transport import PersonalOrxHTTPS, PersonalOrxProvider
from .personal_remote_provider import RemoteConnectionError, SecretLease
from .runtime_packages.openresearch_v1.supervisor import (
    OpenResearchSupervisor, PlatformOpenResearchConfig as PlatformOpenResearchConfig, PACKAGE_VERSION, PROVIDER_ID,
    _UnixHTTP, OPENCODE_SHA256 as OPENCODE_SHA256,
)
from .runtime_packages.openresearch_v1.entry import build_command, verify_no_startup_dispatch


class PlatformOpenResearchPackage(OpenResearchSupervisor):
    def __init__(self, config, root):
        super().__init__(config, root)
        self.provider = PlatformOrxProvider(self)

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

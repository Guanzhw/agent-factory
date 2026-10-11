"""Trusted SSH credential domain; encrypted custody reuses the owner vault.

Only a dedicated unencrypted Ed25519 private key is accepted at enrollment.
Canonical private bytes are encrypted as a single-line value; never returned.
Host identity is supplied and confirmed by the owner, never learned by probing.
"""
import base64
import hashlib
import ipaddress
import re
from urllib.parse import urlsplit
from typing import NoReturn

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .personal_remote_provider import RemoteConnectionError

PROVIDER_ID = 'owner-ssh-server-v1'


def reject() -> NoReturn:
    raise RemoteConnectionError('SSH_IDENTITY_INVALID')


def host_identity(value):
    try:
        parts = value.strip().split()
        if len(parts) < 2 or parts[0] != 'ssh-ed25519' or any(ord(c) < 32 for c in value.strip()): reject()
        canonical = ' '.join(parts[:2])
        key = serialization.load_ssh_public_key(canonical.encode())
        if not isinstance(key, Ed25519PublicKey): reject()
        raw = base64.b64decode(parts[1], validate=True)
        pin = hashlib.sha256(raw).hexdigest()
        fingerprint = 'SHA256:' + base64.b64encode(bytes.fromhex(pin)).decode().rstrip('=')
        return canonical, pin, fingerprint
    except Exception:
        reject()


def endpoint(address, port, username, host_key):
    try:
        ip = ipaddress.ip_address(address)
        if ip.is_unspecified or ip.is_multicast or ip.is_reserved or '%' in address: reject()
        if type(port) is not int or not 1 <= port <= 65535: reject()
        if username == 'root' or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', username): reject()
        canonical, pin, fingerprint = host_identity(host_key)
        host = f'[{ip}]' if ip.version == 6 else str(ip)
        return {'address': str(ip), 'port': port, 'username': username, 'hostKey': canonical,
            'hostFingerprint': fingerprint, 'origin': f'ssh://{username}@{host}:{port}?hostkey={pin}'}
    except Exception:
        reject()


def ssh_destination(value):
    try:
        parsed = urlsplit(value)
        ip = ipaddress.ip_address(parsed.hostname)
        if (parsed.scheme != 'ssh' or parsed.password is not None or parsed.path or parsed.fragment
                or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', parsed.username or '')
                or parsed.username == 'root'
                or parsed.port is None or not re.fullmatch(r'hostkey=[a-f0-9]{64}', parsed.query)
                or ip.is_unspecified or ip.is_multicast or ip.is_reserved or '%' in str(ip)):
            reject()
        host = f'[{ip}]' if ip.version == 6 else str(ip)
        normalized = f'ssh://{parsed.username}@{host}:{parsed.port}?{parsed.query}'
        if normalized != value: reject()
        return normalized
    except Exception:
        reject()


class SSHCredentialPolicy:
    """Installed once by deployment code, never from an owner request."""
    normalize_destination = staticmethod(ssh_destination)

    def __init__(self, address_policy):
        if not callable(address_policy): raise ValueError('SSH requires a trusted network policy')
        self.address_policy = address_policy

    def __call__(self, destination):
        destination = ssh_destination(destination)
        value = urlsplit(destination)
        if self.address_policy(value.hostname, value.port) is not True: reject()
        return destination

    def prepare_secret(self, destination, username, password):
        try:
            if username != urlsplit(self(destination)).username or len(password) > 4096: reject()
            key = serialization.load_ssh_private_key(password.encode(), password=None)
            if not isinstance(key, Ed25519PrivateKey): reject()
            raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption())
            return username, base64.b64encode(raw).decode()
        except Exception:
            reject()

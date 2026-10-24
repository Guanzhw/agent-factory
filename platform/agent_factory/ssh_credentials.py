"""Trusted SSH credential domain; encrypted custody reuses the owner vault.

Unencrypted private keys accepted by the OpenSSH parser are enrolled.
Canonical private bytes are encrypted as a single-line value; never returned.
Host identity is supplied and confirmed by the owner, never learned by probing.
"""
import base64
import hashlib
import re
from urllib.parse import quote, unquote, urlsplit
from typing import NoReturn

from cryptography.hazmat.primitives import serialization

from .personal_remote_provider import RemoteConnectionError, hostname

PROVIDER_ID = 'owner-ssh-server-v1'


def reject() -> NoReturn:
    raise RemoteConnectionError('SSH_IDENTITY_INVALID')


def host_identity(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 32 for c in value.strip()): reject()
        key = serialization.load_ssh_public_key(value.strip().encode())
        canonical = key.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        raw = base64.b64decode(canonical.split()[1], validate=True)
        pin = hashlib.sha256(raw).hexdigest()
        fingerprint = 'SHA256:' + base64.b64encode(bytes.fromhex(pin)).decode().rstrip('=')
        return canonical, pin, fingerprint
    except Exception:
        reject()


def ssh_username(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or any(ord(c) < 32 or ord(c) == 127 or c == ':' for c in value)):
        reject()
    return value


def endpoint(address, port, username, host_key):
    try:
        address = hostname(address)
        if type(port) is not int or not 1 <= port <= 65535: reject()
        username = ssh_username(username)
        canonical, pin, fingerprint = host_identity(host_key)
        host = f'[{address}]' if ':' in address else address
        return {'address': address, 'port': port, 'username': username, 'hostKey': canonical,
            'hostFingerprint': fingerprint, 'origin': f'ssh://{quote(username, safe="")}@{host}:{port}?hostkey={pin}'}
    except Exception:
        reject()


def ssh_destination(value):
    try:
        parsed = urlsplit(value)
        address = hostname(parsed.hostname)
        username = ssh_username(unquote(parsed.username or ''))
        if (parsed.scheme != 'ssh' or parsed.password is not None or parsed.path or parsed.fragment
                or parsed.port is None or not re.fullmatch(r'hostkey=[a-f0-9]{64}', parsed.query)
                or not 1 <= parsed.port <= 65535):
            reject()
        host = f'[{address}]' if ':' in address else address
        normalized = f'ssh://{quote(username, safe="")}@{host}:{parsed.port}?{parsed.query}'
        if normalized != value: reject()
        return normalized
    except Exception:
        reject()


class SSHCredentialPolicy:
    """Installed once by deployment code, never from an owner request."""
    normalize_destination = staticmethod(ssh_destination)

    def __call__(self, destination):
        return ssh_destination(destination)

    def prepare_secret(self, destination, username, password):
        try:
            if username != unquote(urlsplit(self(destination)).username or ''): reject()
            key = serialization.load_ssh_private_key(password.encode(), password=None)
            raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption())
            return username, base64.b64encode(raw).decode()
        except Exception:
            reject()

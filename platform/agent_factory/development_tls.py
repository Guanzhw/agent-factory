"""Temporary loopback TLS for explicit development mock login only.

No persistent key, system trust installation, certificate renewal or host change.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .development_identity import validate_development_origin


@contextmanager
def temporary_development_tls(public_origin):
    validate_development_origin(public_origin)
    host = urlsplit(public_origin).hostname
    assert host is not None
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Agent Factory DEVELOPMENT MOCK")])
    now = datetime.now(timezone.utc)
    alternative = x509.DNSName(host) if host == "localhost" else x509.IPAddress(ipaddress.ip_address(host))
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=2)).add_extension(x509.SubjectAlternativeName([alternative]), critical=False)
        .sign(key, hashes.SHA256()))
    with TemporaryDirectory(prefix="agent-factory-development-tls-") as directory:
        paths = []
        for name, content in (("certificate.pem", certificate.public_bytes(serialization.Encoding.PEM)),
                              ("private-key.pem", key.private_bytes(serialization.Encoding.PEM,
                               serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))):
            path = Path(directory) / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            paths.append(path)
        yield tuple(paths)

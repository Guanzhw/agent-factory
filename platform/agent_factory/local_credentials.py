"""Persistent local credential custody for member-configured resources."""
import os
from pathlib import Path
import secrets
import tempfile

from .credential_vault import EncryptedCredentialVault


def local_master_key(directory: Path) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "credential-vault.key"
    if not path.exists():
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".vault-key-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("Credential vault key must contain 32 bytes")
    return key


def local_credential_vault(engine, directory: Path):
    from .byok_model import PROVIDER_ID as MODEL_PROVIDER
    from .personal_remote_provider import PROVIDER_ID as REMOTE_PROVIDER, origin
    from .personal_cli import cli_destination
    from .personal_mcp import mcp_url
    from .ssh_credentials import PROVIDER_ID as SSH_PROVIDER, SSHCredentialPolicy

    # URL/command normalization describes the protocol; it grants no host allowlist.
    cli_destination.normalize_destination = cli_destination
    mcp_url.normalize_destination = mcp_url
    return EncryptedCredentialVault(engine, local_master_key(directory), {
        MODEL_PROVIDER: origin, REMOTE_PROVIDER: origin,
        SSH_PROVIDER: SSHCredentialPolicy(), "member-cli": cli_destination, "member-mcp": mcp_url,
    })

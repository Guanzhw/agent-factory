"""Explicit ephemeral signing configuration for disposable tests only."""
from dataclasses import dataclass, field
import secrets

from agent_factory.config import Settings as ProductSettings
from fixture_identity import identity_config
from agent_factory.oidc_identity import OIDCIdentityConfig


@dataclass
class Settings(ProductSettings):
    jwt_key: str = field(default_factory=lambda: secrets.token_urlsafe(48))
    oidc_identity: OIDCIdentityConfig | None = field(default_factory=identity_config)

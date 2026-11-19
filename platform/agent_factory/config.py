from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


@dataclass
class Settings:
    db_url: str
    jwt_key: str = ""
    jwt_audience: str = "agent-factory"
    local_login_origin: str = ""
    max_workers: int = 2
    max_queued: int = 0
    # Legacy constructor fields remain readable; admission no longer counts tasks.
    queue_poll: float = 0.2
    native_timeout_seconds: int | None = None
    workspace: Path = field(default_factory=lambda: Path(".local"))
    web_directory: Path = field(default_factory=lambda: Path("dist").resolve())
    port: int = 3100
    host: str = "127.0.0.1"
    # Operator-only evaluator manifest digests mapped to existing fixed targets.
    # Trusted operator presets; never populated from request JSON.
    # Same-process operator registrations; never populated from user JSON/env secrets.
    trusted_connections: dict = field(default_factory=dict)
    # Built-in protocols are available to every member; installations may add providers.
    personal_connection_providers: dict = field(default_factory=dict)
    credential_vault_factory: Callable | None = field(default=None, repr=False)
    personal_connection_provider_factories: dict = field(default_factory=dict, repr=False)
    ssh_self_service: object | None = field(default=None, repr=False)
    # Shared schemas/installed adapters only. Authentication is resolved per owner.
    personal_tool_adapters: tuple = field(default_factory=tuple, repr=False)
    # Trusted workflow definitions/runtime implementations; never request-loaded.
    def __post_init__(self):
        self.local_login_origin = self.local_login_origin or f"https://127.0.0.1:{self.port}"
        origin = self.local_login_origin
        parsed = urlsplit(origin)
        if (not origin.isascii() or any(char.isspace() or not char.isprintable() for char in origin)
                or parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port == 0 or '\\' in origin
                or origin != f'https://{parsed.netloc}'):
            raise ValueError('Local login requires an exact HTTPS origin without a path')
        if not isinstance(self.jwt_key, str) or len(self.jwt_key.encode()) < 32:
            raise ValueError("Production requires an explicitly configured JWT key of at least 32 bytes")
        if type(self.max_workers) is not int or self.max_workers < 1:
            raise ValueError("Worker concurrency must be a positive integer")

    @property
    def runtime_directory(self) -> Path:
        return self.workspace / "runtime"

    @classmethod
    def from_env(cls, *, db_url=None, jwt_key=None, local_login_origin=None):
        url = db_url if db_url is not None else os.getenv("FACTORY_DATABASE_URL", "")
        if not url.startswith("postgresql"):
            raise ValueError("FACTORY_DATABASE_URL must configure PostgreSQL; no SQLite queue fallback")
        key = jwt_key if jwt_key is not None else os.getenv("FACTORY_JWT_KEY", "")
        if len(key.encode()) < 32:
            raise ValueError("Production requires an operator-configured JWT key (at least 32 bytes)")
        return cls(db_url=url, jwt_key=key,
                   native_timeout_seconds=int(os.environ['FACTORY_NATIVE_TIMEOUT_SECONDS']) if os.getenv('FACTORY_NATIVE_TIMEOUT_SECONDS') else None,
                   local_login_origin=local_login_origin or os.getenv('FACTORY_LOCAL_LOGIN_ORIGIN', ''),
                   workspace=Path(os.getenv("FACTORY_WORKSPACE", ".local")).resolve(),
                   max_workers=int(os.getenv("FACTORY_MAX_WORKERS", "2")),
                   port=int(os.getenv("FACTORY_PORT", "3100")))

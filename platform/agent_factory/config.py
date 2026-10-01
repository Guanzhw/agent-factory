from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets


@dataclass
class Settings:
    db_url: str
    demo: bool = True
    jwt_key: str = ""
    jwt_audience: str = "agent-factory"
    max_workers: int = 2
    max_queued: int = 20
    max_user_tasks: int = 2
    max_total_tasks: int = 12
    queue_poll: float = 0.2
    max_tool_calls: int = 8
    experiment_timeout_seconds: int = 8
    experiment_output_bytes: int = 65536
    workspace: Path = field(default_factory=lambda: Path(".local"))
    temporary_policy: str = "bounded-synthetic"
    port: int = 3100
    host: str = "127.0.0.1"
    remote_targets: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.demo and len(self.jwt_key) < 32:
            raise ValueError("Production requires an explicitly configured JWT key")
        if self.demo and not self.jwt_key:
            self.jwt_key = secrets.token_urlsafe(48)
        if not 1 <= self.max_workers <= 4:
            raise ValueError("Worker concurrency must be 1–4 until a capacity benchmark is approved")
        if self.temporary_policy not in {"bounded-synthetic", "unset"}:
            raise ValueError("Unsupported temporary-plan policy; keep unset until implemented and reviewed")
        if not self.demo and self.temporary_policy != "unset":
            raise ValueError("Production temporary-plan policy is not implemented; use unset")

    @property
    def runtime_directory(self) -> Path:
        return self.workspace / "runtime"

    @classmethod
    def from_env(cls):
        demo = os.getenv("FACTORY_MODE", "demo") == "demo"
        url = os.getenv("FACTORY_DATABASE_URL", "")
        if not url.startswith("postgresql"):
            raise ValueError("FACTORY_DATABASE_URL must configure PostgreSQL; no SQLite queue fallback")
        key = os.getenv("FACTORY_JWT_KEY", "")
        if not demo and len(key) < 32:
            raise ValueError("Production requires an operator-configured JWT key (at least 32 characters)")
        policy = os.getenv("FACTORY_TEMPORARY_POLICY", "bounded-synthetic" if demo else "unset")
        if not demo and policy == "bounded-synthetic":
            raise ValueError("The synthetic temporary-plan policy is restricted to demo mode")
        return cls(db_url=url, demo=demo, jwt_key=key or secrets.token_urlsafe(48),
                   workspace=Path(os.getenv("FACTORY_WORKSPACE", ".local")).resolve(),
                   temporary_policy=policy, max_workers=int(os.getenv("FACTORY_MAX_WORKERS", "2")),
                   port=int(os.getenv("FACTORY_PORT", "3100")))

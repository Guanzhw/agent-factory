from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import re


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
    temporary_policy: str | None = None
    policy_revision: str = "plan-policy-v1"
    plan_review_ttl_seconds: int = 3600
    material_review_mode: str = "separate-admin"
    material_policy_revision: str = "material-governance-v1"
    port: int = 3100
    host: str = "127.0.0.1"
    remote_targets: dict = field(default_factory=dict)
    handoff_targets: dict = field(default_factory=dict)
    handoff_origins: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.demo and len(self.jwt_key) < 32:
            raise ValueError("Production requires an explicitly configured JWT key")
        if self.demo and not self.jwt_key:
            self.jwt_key = secrets.token_urlsafe(48)
        if self.material_review_mode not in {"separate-admin", "demo-self-review"}:
            raise ValueError("Unsupported material review mode")
        if not self.demo and self.material_review_mode == "demo-self-review":
            raise ValueError("Material self-review compatibility requires explicit demo mode")
        if not 1 <= self.max_workers <= 4:
            raise ValueError("Worker concurrency must be 1–4 until a capacity benchmark is approved")
        if self.temporary_policy is None:
            self.temporary_policy = "bounded-synthetic" if self.demo else "admin-review"
        if self.temporary_policy not in {"bounded-synthetic", "unset", "admin-review", "read-only-auto"}:
            raise ValueError("Unsupported temporary-plan policy")
        if not self.demo and self.temporary_policy == "bounded-synthetic":
            raise ValueError("The synthetic temporary-plan policy is restricted to demo mode")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", self.policy_revision):
            raise ValueError("Policy revision must be a bounded identifier")
        if not 60 <= self.plan_review_ttl_seconds <= 86400:
            raise ValueError("Plan review TTL must be 60 through 86400 seconds")

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
        policy = os.getenv("FACTORY_TEMPORARY_POLICY", "bounded-synthetic" if demo else "admin-review")
        if not demo and policy == "bounded-synthetic":
            raise ValueError("The synthetic temporary-plan policy is restricted to demo mode")
        return cls(db_url=url, demo=demo, jwt_key=key or secrets.token_urlsafe(48),
                   workspace=Path(os.getenv("FACTORY_WORKSPACE", ".local")).resolve(),
                   temporary_policy=policy, policy_revision=os.getenv("FACTORY_POLICY_REVISION", "plan-policy-v1"),
                   plan_review_ttl_seconds=int(os.getenv("FACTORY_PLAN_REVIEW_TTL_SECONDS", "3600")),
                   material_review_mode=os.getenv("FACTORY_MATERIAL_REVIEW_MODE", "separate-admin"),
                   material_policy_revision=os.getenv("FACTORY_MATERIAL_POLICY_REVISION", "material-governance-v1"),
                   max_workers=int(os.getenv("FACTORY_MAX_WORKERS", "2")),
                   port=int(os.getenv("FACTORY_PORT", "3100")))

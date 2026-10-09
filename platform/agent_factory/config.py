from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import re
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .usage_ledger import UsagePolicy
    from .oidc_identity import OIDCIdentityConfig
    from .browser_oidc import BrowserOIDCConfig


@dataclass
class Settings:
    db_url: str
    demo: bool = True
    jwt_key: str = ""
    jwt_audience: str = "agent-factory"
    # Operator-pinned public verification keys and existing-owner mapping only.
    oidc_identity: "OIDCIdentityConfig | None" = None
    browser_oidc: "BrowserOIDCConfig | None" = None
    source_synthesis_enabled: bool = False
    development_mock_login: bool = False
    development_public_origin: str | None = None
    max_workers: int = 2
    max_queued: int = 20
    max_user_tasks: int = 2
    max_total_tasks: int = 12
    queue_poll: float = 0.2
    native_timeout_seconds: int = 60
    max_tool_calls: int = 8
    experiment_timeout_seconds: int = 8
    experiment_output_bytes: int = 65536
    workspace: Path = field(default_factory=lambda: Path(".local"))
    storage_task_reserve_bytes: int = 64 * 1024 * 1024
    storage_low_water_bytes: int = 1024 * 1024 * 1024
    storage_monitor_paths: tuple[Path, ...] = ()
    storage_scan_entries: int = 20000
    storage_hash_bytes: int = 64 * 1024 * 1024
    storage_retention_grace_seconds: int = 86400
    storage_allow_purge: bool = False
    temporary_policy: str | None = None
    policy_revision: str = "plan-policy-v1"
    plan_review_ttl_seconds: int = 3600
    material_review_mode: str = "separate-admin"
    material_policy_revision: str = "material-governance-v1"
    port: int = 3100
    host: str = "127.0.0.1"
    remote_targets: dict = field(default_factory=dict)
    # Operator-only evaluator manifest digests mapped to existing fixed targets.
    research_evaluators: dict = field(default_factory=dict)
    # Trusted operator presets; never populated from request JSON.
    autoresearch_presets: dict = field(default_factory=dict)
    personal_agent_commands_enabled: bool = False
    managed_orx_profiles_factory: Callable | None = field(default=None, repr=False)
    autoresearch_children_factory: Callable | None = field(default=None, repr=False)
    remote_scientific_factory: Callable | None = field(default=None, repr=False)
    handoff_targets: dict = field(default_factory=dict)
    handoff_origins: dict = field(default_factory=dict)
    remote_binding_mappings: dict = field(default_factory=dict)
    # Same-process operator registrations; never populated from user JSON/env secrets.
    trusted_connections: dict = field(default_factory=dict)
    # Globally installed safe providers; users own their endpoint configurations.
    # No default secret backend or implicit remote-access grant.
    personal_connection_providers: dict = field(default_factory=dict)
    credential_vault_factory: Callable | None = field(default=None, repr=False)
    personal_connection_provider_factories: dict = field(default_factory=dict, repr=False)
    runtime_adapters: list = field(default_factory=list)
    tool_policies: tuple = field(default_factory=tuple)
    # Trusted workflow definitions/runtime implementations; never request-loaded.
    native_workflows: tuple = field(default_factory=tuple)
    workflow_runtimes: dict = field(default_factory=dict)
    runtime_tool_contract: str = "legacy-v1"
    # Explicit coding-development profile; never credential discovery or production default.
    development_profile: str = "disabled"
    # Operator-only dedicated validation instance; no environment/public API switch.
    development_live_validation: bool = False
    # Frozen operator price/policy registrations, never loaded from model input.
    fee_management_enabled: bool = False
    platform_paid_models_enabled: bool = False
    # Trusted test transport only; never accepted from HTTP or environment.
    owner_model_transport_factory: Callable | None = field(default=None, repr=False)
    usage_pricing: tuple = field(default_factory=tuple)
    usage_policy: "UsagePolicy | None" = None

    def __post_init__(self):
        if type(self.fee_management_enabled) is not bool or type(self.platform_paid_models_enabled) is not bool:
            raise ValueError('Billing enablement requires explicit booleans')
        if self.platform_paid_models_enabled and not self.fee_management_enabled:
            raise ValueError('Managed paid profiles require actual hard budget management')
        if type(self.personal_agent_commands_enabled) is not bool:
            raise ValueError('Personal command enablement must be an explicit boolean')
        if self.personal_agent_commands_enabled:
            from .personal_command_profile import registrations, tool_policy, pricing
            entries = registrations()
            if any(a.adapter_id in {e.adapter_id for e in entries} for a in self.runtime_adapters):
                raise ValueError('Personal command adapters cannot be replaced')
            self.runtime_adapters = [*self.runtime_adapters, *entries]
            self.tool_policies = (*self.tool_policies, tool_policy())
            self.usage_pricing = (*self.usage_pricing, pricing())
        from .tool_policy_registry import validate_tool_policies
        self.tool_policies = validate_tool_policies(self.tool_policies, self.runtime_adapters)
        if type(self.native_timeout_seconds) is not int or not 60 <= self.native_timeout_seconds <= 3600:
            raise ValueError("Native task timeout must be 60 through 3600 seconds")
        if type(self.source_synthesis_enabled) is not bool or (self.source_synthesis_enabled
                and (self.demo is not True or self.temporary_policy != "admin-review")):
            raise ValueError("Controlled source synthesis requires explicit demo mode and independent plan review")
        if type(self.development_mock_login) is not bool:
            raise ValueError("Development mock login requires explicit boolean configuration")
        if self.development_mock_login:
            from .development_identity import validate_development_origin
            if self.demo is not True or self.browser_oidc is not None or self.oidc_identity is not None:
                raise ValueError("Development mock login is disabled in production")
            validate_development_origin(self.development_public_origin)  # type: ignore[arg-type]
        elif self.development_public_origin is not None:
            raise ValueError("Development origin requires explicit mock login")
        if self.browser_oidc is not None:
            from .browser_oidc import BrowserOIDCConfig
            if self.demo or type(self.browser_oidc) is not BrowserOIDCConfig:
                raise ValueError("Browser OIDC requires an explicit production configuration")
        if self.oidc_identity is not None:
            from .oidc_identity import OIDCIdentityConfig
            if self.demo or type(self.oidc_identity) is not OIDCIdentityConfig:
                raise ValueError("External access-token identity requires an explicit production configuration")
        if self.development_profile not in {"disabled", "opencode-go"}:
            raise ValueError("Unsupported development profile")
        if self.development_profile != "disabled" and not self.demo:
            raise ValueError("Go development profile cannot enable a production provider")
        if type(self.development_live_validation) is not bool or (self.development_live_validation
                and (not self.demo or self.development_profile != "opencode-go" or self.max_workers != 1)):
            raise ValueError("Live development validation requires an explicit single-worker development instance")
        if min(self.storage_task_reserve_bytes, self.storage_low_water_bytes, self.storage_scan_entries, self.storage_hash_bytes) < 1:
            raise ValueError("Storage budgets must be positive")
        if self.storage_retention_grace_seconds < (0 if self.demo else 60):
            raise ValueError("Production retention needs a positive recovery window")
        if self.runtime_tool_contract not in {"legacy-v1", "registered-runtime-v1", "local-orx-v1", "orx-evidence-v2", "pubmed-host-evidence-v1", "scientific-synthesis-fixture-v1", "bounded-process-v1", "controlled-development-v1", "research-process-v1", "research-bootstrap-v1", "autoresearch-session-v1"}:
            raise ValueError("Unsupported runtime tool contract")
        if self.runtime_tool_contract != "legacy-v1" and (self.policy_revision == "plan-policy-v1" or self.material_policy_revision == "material-governance-v1"):
            raise ValueError("Registered runtime tools require distinct operator policy/governance revisions")
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
                   source_synthesis_enabled=os.getenv("FACTORY_SOURCE_SYNTHESIS_ENABLED", "false") == "true",
                   runtime_tool_contract=os.getenv("FACTORY_RUNTIME_TOOL_CONTRACT", "legacy-v1"),
                   development_profile=os.getenv("FACTORY_DEVELOPMENT_PROFILE", "disabled"),
                   storage_task_reserve_bytes=int(os.getenv("FACTORY_STORAGE_TASK_RESERVE_BYTES", str(64 * 1024 * 1024))),
                   storage_low_water_bytes=int(os.getenv("FACTORY_STORAGE_LOW_WATER_BYTES", str(1024 * 1024 * 1024))),
                   storage_monitor_paths=tuple(Path(path).resolve() for path in os.getenv("FACTORY_STORAGE_MONITOR_PATHS", "").split(os.pathsep) if path),
                   storage_retention_grace_seconds=int(os.getenv("FACTORY_STORAGE_RETENTION_GRACE_SECONDS", "86400")),
                   storage_allow_purge=os.getenv("FACTORY_STORAGE_ALLOW_PURGE", "false") == "true",
                   max_workers=int(os.getenv("FACTORY_MAX_WORKERS", "2")),
                   port=int(os.getenv("FACTORY_PORT", "3100")))

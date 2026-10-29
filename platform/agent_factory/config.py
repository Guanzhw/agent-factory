from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .usage_ledger import UsagePolicy
    from .oidc_identity import OIDCIdentityConfig
    from .browser_oidc import BrowserOIDCConfig


@dataclass
class Settings:
    db_url: str
    jwt_key: str = ""
    jwt_audience: str = "agent-factory"
    # Operator-pinned public verification keys and existing-owner mapping only.
    oidc_identity: "OIDCIdentityConfig | None" = None
    browser_oidc: "BrowserOIDCConfig | None" = None
    local_login_origin: str | None = None
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
    web_directory: Path = field(default_factory=lambda: Path("dist").resolve())
    storage_task_reserve_bytes: int = 64 * 1024 * 1024
    storage_low_water_bytes: int = 1024 * 1024 * 1024
    storage_monitor_paths: tuple[Path, ...] = ()
    storage_scan_entries: int = 20000
    storage_hash_bytes: int = 64 * 1024 * 1024
    storage_retention_grace_seconds: int = 86400
    storage_allow_purge: bool = False
    temporary_policy: str = "member-self-service"
    policy_revision: str = "department-member-v1"
    material_review_mode: str = "member-self-service"
    material_policy_revision: str = "material-department-v1"
    port: int = 3100
    host: str = "127.0.0.1"
    remote_targets: dict = field(default_factory=dict)
    # Operator-only evaluator manifest digests mapped to existing fixed targets.
    # Trusted operator presets; never populated from request JSON.
    handoff_targets: dict = field(default_factory=dict)
    handoff_origins: dict = field(default_factory=dict)
    remote_binding_mappings: dict = field(default_factory=dict)
    # Same-process operator registrations; never populated from user JSON/env secrets.
    trusted_connections: dict = field(default_factory=dict)
    # Built-in protocols are available to every member; installations may add providers.
    personal_connection_providers: dict = field(default_factory=dict)
    credential_vault_factory: Callable | None = field(default=None, repr=False)
    personal_connection_provider_factories: dict = field(default_factory=dict, repr=False)
    ssh_self_service: object | None = field(default=None, repr=False)
    ssh_training_profiles: dict = field(default_factory=dict, repr=False)
    # Shared schemas/installed adapters only. Authentication is resolved per owner.
    personal_tool_adapters: tuple = field(default_factory=tuple, repr=False)
    runtime_adapters: list = field(default_factory=list)
    # Trusted workflow definitions/runtime implementations; never request-loaded.
    native_workflows: tuple = field(default_factory=tuple)
    workflow_runtimes: dict = field(default_factory=dict)
    runtime_tool_contract: str = "legacy-v1"
    # Frozen operator price/policy registrations, never loaded from model input.
    fee_management_enabled: bool = False
    platform_paid_models_enabled: bool = False
    # Trusted test transport only; never accepted from HTTP or environment.
    owner_model_transport_factory: Callable | None = field(default=None, repr=False)
    # Explicit, owner/model-version-scoped gateway grant for one deployment only.
    # Never loaded from ambient proxy/CA variables or HTTP/material configuration.
    owner_model_trusted_proxy: object | None = field(default=None, repr=False)
    owner_model_proxy_environment_id: str | None = field(default=None, repr=False)
    # Operator-installed immutable artifacts; no runtime paths/commands in HTTP.
    # None leaves preparation unavailable. Owners only configure their own model.
    # Trusted owned-server registrations + existing agent bindings; never HTTP keys.
    usage_pricing: tuple = field(default_factory=tuple)
    usage_policy: "UsagePolicy | None" = None

    def __post_init__(self):
        if self.owner_model_trusted_proxy is not None:
            from .trusted_model_proxy import TrustedModelProxy
            if (not isinstance(self.owner_model_trusted_proxy, TrustedModelProxy)
                    or self.owner_model_transport_factory is not None):
                raise ValueError('TRUSTED_MODEL_PROXY_CONFIGURATION_INVALID')
            self.owner_model_trusted_proxy.validate_environment(self.owner_model_proxy_environment_id)
        if type(self.fee_management_enabled) is not bool or type(self.platform_paid_models_enabled) is not bool:
            raise ValueError('Billing enablement requires explicit booleans')
        if self.platform_paid_models_enabled and not self.fee_management_enabled:
            raise ValueError('Managed paid profiles require actual hard budget management')
        if self.personal_tool_adapters:
            from .personal_tool_execution import personal_tool_registration
            if type(self.personal_tool_adapters) is not tuple or len(self.personal_tool_adapters) > 64:
                raise ValueError('Personal tools require a bounded static tuple')
            registrations = [personal_tool_registration(adapter) for adapter in self.personal_tool_adapters]
            keys = [(entry.adapter_id, entry.revision) for entry in registrations]
            if len(set(keys)) != len(keys):
                raise ValueError('Personal tool adapter registrations must be unique')
            # A settings dataclass may be copied into the selected deployment's
            # settings type. Reuse only these exact generated registrations.
            installed = {(entry.adapter_id, entry.revision): entry for entry in self.runtime_adapters}
            for registration in registrations:
                key = (registration.adapter_id, registration.revision)
                previous = installed.get(key)
                if previous is not None and getattr(previous.factory, '_personal_tool_adapter', None) is not getattr(registration.factory, '_personal_tool_adapter', None):
                    raise ValueError('Personal tool adapter conflicts with another registration')
            self.runtime_adapters = [*self.runtime_adapters, *[entry for entry in registrations
                if (entry.adapter_id, entry.revision) not in installed]]
        if type(self.native_timeout_seconds) is not int or not 60 <= self.native_timeout_seconds <= 3600:
            raise ValueError("Native task timeout must be 60 through 3600 seconds")
        if type(self.experiment_timeout_seconds) is not int or not 1 <= self.experiment_timeout_seconds <= 600:
            raise ValueError("Operation timeout must be 1 through 600 seconds")
        if self.browser_oidc is not None:
            from .browser_oidc import BrowserOIDCConfig
            if type(self.browser_oidc) is not BrowserOIDCConfig:
                raise ValueError("Browser OIDC requires an explicit production configuration")
        if self.local_login_origin is not None:
            from .browser_oidc import _origin
            if _origin(self.local_login_origin)[1] != self.local_login_origin:
                raise ValueError('Local login requires an exact HTTPS origin without a path')
            if self.browser_oidc is not None and self.browser_oidc.app_origin != self.local_login_origin:
                raise ValueError('Local and OIDC login must use the same browser origin')
        if self.oidc_identity is not None:
            from .oidc_identity import OIDCIdentityConfig
            if type(self.oidc_identity) is not OIDCIdentityConfig:
                raise ValueError("External access-token identity requires an explicit production configuration")
        if min(self.storage_task_reserve_bytes, self.storage_low_water_bytes, self.storage_scan_entries, self.storage_hash_bytes) < 1:
            raise ValueError("Storage budgets must be positive")
        if self.storage_retention_grace_seconds < 60:
            raise ValueError("Production retention needs a positive recovery window")
        if not isinstance(self.jwt_key, str) or len(self.jwt_key.encode()) < 32:
            raise ValueError("Production requires an explicitly configured JWT key of at least 32 bytes")
        if self.material_review_mode != "member-self-service":
            raise ValueError("Material review modes were removed; members publish their own materials")
        if not 1 <= self.max_workers <= 4:
            raise ValueError("Worker concurrency must be 1–4 until a capacity benchmark is approved")
        if self.temporary_policy != "member-self-service":
            raise ValueError("Plan approval modes were removed; members execute their own plans")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", self.policy_revision):
            raise ValueError("Policy revision must be a bounded identifier")

    @property
    def runtime_directory(self) -> Path:
        return self.workspace / "runtime"

    @classmethod
    def from_env(cls):
        if os.getenv("FACTORY_MODE", "production") != "production":
            raise ValueError("FACTORY_MODE only supports production; demo mode was removed")
        obsolete = ("FACTORY_DEVELOPMENT_PROFILE", "FACTORY_DEVELOPMENT_MOCK_LOGIN",
                    "FACTORY_DEVELOPMENT_PUBLIC_ORIGIN", "FACTORY_DEVELOPMENT_LIVE_VALIDATION")
        if any(name in os.environ for name in obsolete):
            raise ValueError("Development identity/profile configuration was removed")
        url = os.getenv("FACTORY_DATABASE_URL", "")
        if not url.startswith("postgresql"):
            raise ValueError("FACTORY_DATABASE_URL must configure PostgreSQL; no SQLite queue fallback")
        key = os.getenv("FACTORY_JWT_KEY", "")
        if len(key.encode()) < 32:
            raise ValueError("Production requires an operator-configured JWT key (at least 32 bytes)")
        policy = os.getenv("FACTORY_TEMPORARY_POLICY", "member-self-service")
        return cls(db_url=url, jwt_key=key,
                   experiment_timeout_seconds=int(os.getenv('FACTORY_OPERATION_TIMEOUT_SECONDS', '8')),
                   native_timeout_seconds=int(os.getenv('FACTORY_NATIVE_TIMEOUT_SECONDS', '60')),
                   local_login_origin=os.getenv('FACTORY_LOCAL_LOGIN_ORIGIN') or None,
                   workspace=Path(os.getenv("FACTORY_WORKSPACE", ".local")).resolve(),
                   temporary_policy=policy, policy_revision=os.getenv("FACTORY_POLICY_REVISION", "department-member-v1"),
                   material_review_mode=os.getenv("FACTORY_MATERIAL_REVIEW_MODE", "member-self-service"),
                   material_policy_revision=os.getenv("FACTORY_MATERIAL_POLICY_REVISION", "material-department-v1"),
                   runtime_tool_contract=os.getenv("FACTORY_RUNTIME_TOOL_CONTRACT", "legacy-v1"),
                   storage_task_reserve_bytes=int(os.getenv("FACTORY_STORAGE_TASK_RESERVE_BYTES", str(64 * 1024 * 1024))),
                   storage_low_water_bytes=int(os.getenv("FACTORY_STORAGE_LOW_WATER_BYTES", str(1024 * 1024 * 1024))),
                   storage_monitor_paths=tuple(Path(path).resolve() for path in os.getenv("FACTORY_STORAGE_MONITOR_PATHS", "").split(os.pathsep) if path),
                   storage_retention_grace_seconds=int(os.getenv("FACTORY_STORAGE_RETENTION_GRACE_SECONDS", "86400")),
                   storage_allow_purge=os.getenv("FACTORY_STORAGE_ALLOW_PURGE", "false") == "true",
                   max_workers=int(os.getenv("FACTORY_MAX_WORKERS", "2")),
                   port=int(os.getenv("FACTORY_PORT", "3100")))

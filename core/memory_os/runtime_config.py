"""Runtime adapter configuration contracts for Memory OS."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TenantMode(str, Enum):
    """Declared runtime tenancy shape."""

    LOCAL_SINGLE_USER = "local_single_user"
    SELF_HOSTED_ADMIN = "self_hosted_admin"


@dataclass(frozen=True)
class RuntimeAdapterSelection:
    """Named adapter choices without constructing runtime dependencies."""

    record_ledger: str = "sqlite"
    artifact_store: str = "filesystem"
    vector_index: str = "lancedb"
    graph_index: str = "kuzu"
    job_runner: str = "local"

    @classmethod
    def local_defaults(cls) -> "RuntimeAdapterSelection":
        return cls()


@dataclass(frozen=True)
class RuntimePolicy:
    """Runtime policy flags for local and private self-hosted runtimes."""

    daemon_only_writes: bool = True
    allow_legacy_fallback: bool = True
    rebuild_retrieval_on_startup: bool = True
    require_tenant_id: bool = False
    require_authorization_context: bool = False
    enforce_workspace_filters: bool = False
    allow_local_artifact_paths: bool = True
    allow_unsigned_artifact_handles: bool = True

    @classmethod
    def local_defaults(cls) -> "RuntimePolicy":
        return cls()

    @classmethod
    def self_hosted_admin_defaults(cls) -> "RuntimePolicy":
        return cls()

    def validate_for(self, tenant_mode: TenantMode) -> None:
        TenantMode(tenant_mode)


@dataclass(frozen=True)
class MemoryOSRuntimeConfig:
    """Dependency-free Memory OS runtime wiring declaration."""

    data_root: Path | str
    tenant_mode: TenantMode | str = TenantMode.LOCAL_SINGLE_USER
    object_root: Path | str | None = None
    adapters: RuntimeAdapterSelection | None = None
    policy: RuntimePolicy | None = None
    embedder_id: str = "all-MiniLM-L6-v2"

    def __post_init__(self) -> None:
        tenant_mode = TenantMode(self.tenant_mode)
        data_root = Path(self.data_root)
        object_root = Path(self.object_root) if self.object_root is not None else data_root / "objects"

        policy = self.policy
        if policy is None:
            if tenant_mode is TenantMode.SELF_HOSTED_ADMIN:
                policy = RuntimePolicy.self_hosted_admin_defaults()
            else:
                policy = RuntimePolicy.local_defaults()
        policy.validate_for(tenant_mode)

        adapters = self.adapters
        if adapters is None:
            adapters = RuntimeAdapterSelection.local_defaults()

        object.__setattr__(self, "tenant_mode", tenant_mode)
        object.__setattr__(self, "data_root", data_root)
        object.__setattr__(self, "object_root", object_root)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "adapters", adapters)

    @classmethod
    def local(cls, data_root: str | Path) -> "MemoryOSRuntimeConfig":
        return cls(data_root=data_root, tenant_mode=TenantMode.LOCAL_SINGLE_USER)

    @classmethod
    def self_hosted_admin(cls, data_root: str | Path) -> "MemoryOSRuntimeConfig":
        return cls(data_root=data_root, tenant_mode=TenantMode.SELF_HOSTED_ADMIN)

    @property
    def ledger_path(self) -> Path:
        return self.data_root / "ledger.sqlite3"

    @property
    def vector_root(self) -> Path:
        return self.data_root / "lance"

    @property
    def graph_root(self) -> Path:
        return self.data_root / "kuzu"

    def as_dict(self) -> dict[str, object]:
        return {
            "data_root": str(self.data_root),
            "object_root": str(self.object_root),
            "tenant_mode": self.tenant_mode.value,
            "adapters": {
                "record_ledger": self.adapters.record_ledger,
                "artifact_store": self.adapters.artifact_store,
                "vector_index": self.adapters.vector_index,
                "graph_index": self.adapters.graph_index,
                "job_runner": self.adapters.job_runner,
            },
            "policy": {
                "daemon_only_writes": self.policy.daemon_only_writes,
                "allow_legacy_fallback": self.policy.allow_legacy_fallback,
                "rebuild_retrieval_on_startup": self.policy.rebuild_retrieval_on_startup,
                "require_tenant_id": self.policy.require_tenant_id,
                "require_authorization_context": self.policy.require_authorization_context,
                "enforce_workspace_filters": self.policy.enforce_workspace_filters,
                "allow_local_artifact_paths": self.policy.allow_local_artifact_paths,
                "allow_unsigned_artifact_handles": self.policy.allow_unsigned_artifact_handles,
            },
            "embedder_id": self.embedder_id,
        }

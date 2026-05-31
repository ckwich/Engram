"""Policy constants for boxed legacy JSON/Chroma compatibility.

This module is intentionally lightweight. Importing it must not import the
legacy memory manager, ChromaDB, or Memory OS runtime services.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Iterable


LEGACY_COMPATIBILITY_MODE: Final[dict[str, object]] = {
    "runtime_role": "compatibility_recovery",
    "product_core": False,
    "deletion_allowed": False,
    "allowed_callers": [
        "direct_server_debug_mode",
        "legacy_recovery_backup",
        "legacy_memory_os_migration",
        "legacy_retrieval_parity",
        "operator_rebuild_or_export",
    ],
    "blocked_callers": [
        "new_memory_os_features",
        "thin_daemon_client",
        "hosted_product_core",
        "background_ingestion_workers",
    ],
}

DIRECT_LEGACY_MEMORY_MANAGER_IMPORTERS: Final[frozenset[str]] = frozenset(
    {
        "server.py",  # Direct-mode compatibility entrypoint and self-test harness.
        "engramd.py",
        "engram_index.py",
        "core/engramd_api.py",  # Daemon bridge around legacy fallback tools.
        "hooks/engram_evaluator.py",
    }
)

BANNED_MEMORY_OS_LEGACY_IMPORTS: Final[tuple[str, ...]] = (
    "core.memory_manager",
    "core.legacy",
    "chromadb",
)

MEMORY_OS_LEGACY_COMPATIBILITY_MODULES: Final[frozenset[str]] = frozenset(
    {
        "core.memory_os.corpus_inventory",
        "core.memory_os.legacy_import",
        "core.memory_os.legacy_migration_service",
        "core.memory_os.legacy_recovery_backup",
        "core.memory_os.legacy_retrieval_parity",
    }
)

LEGACY_MIGRATION_KERNEL_IMPORTERS: Final[frozenset[str]] = frozenset(
    {
        "core.graph_backend_status",
        "core.memory_os._migration_bridge",
        "core.memory_os.bundles",
        "core.memory_os.corpus_inventory",
        "core.memory_os.legacy_import",
        "core.memory_os.legacy_migration_service",
        "core.memory_os.retrieval",
        "core.retrieval_backend_status",
        "core.vector_index_rebuild",
    }
)


@dataclass(frozen=True)
class LegacyRetirementGate:
    """One required proof before legacy stores can be retired."""

    gate_id: str
    label: str
    required_evidence: str


LEGACY_RETIREMENT_GATES: Final[tuple[LegacyRetirementGate, ...]] = (
    LegacyRetirementGate(
        gate_id="migration_replay_stable",
        label="Migration replay remains stable",
        required_evidence=(
            "Legacy memory and legacy related_to graph migrations prepare cleanly, "
            "apply through daemon-owned Memory OS, and replay idempotently on the "
            "current corpus."
        ),
    ),
    LegacyRetirementGate(
        gate_id="corpus_parity_verified",
        label="Corpus parity is verified",
        required_evidence=(
            "Memory OS ledger, source, retrieval, and graph records match the "
            "legacy corpus through deterministic count, hash, lifecycle, known-key, "
            "hybrid identifier, project-alias, and search-to-chunk-to-memory probes."
        ),
    ),
    LegacyRetirementGate(
        gate_id="daemon_serving_stable",
        label="Daemon serving is the active path",
        required_evidence=(
            "Health and search receipts prove memory_os is serving retrieval with "
            "fallback_used=false across the supported agent ladder."
        ),
    ),
    LegacyRetirementGate(
        gate_id="rollback_backup_verified",
        label="Rollback backup is verified",
        required_evidence=(
            "Legacy JSON, Chroma, and graph recovery backups are written only after "
            "acceptance, checksum-verified, and restored into a scratch root."
        ),
    ),
    LegacyRetirementGate(
        gate_id="operator_backup_verified",
        label="Operator backup is retained",
        required_evidence=(
            "A human operator verifies the retained backup archive, manifest, "
            "restore notes, and off-machine or durable retention location before "
            "legacy stores are deleted or archived."
        ),
    ),
    LegacyRetirementGate(
        gate_id="cross_platform_restart_verified",
        label="Cross-platform restart is proven",
        required_evidence=(
            "macOS/Linux and Windows restart probes prove daemon-owned Memory OS "
            "comes back without legacy fallback or index ownership drift."
        ),
    ),
    LegacyRetirementGate(
        gate_id="release_cycle_observed",
        label="Release-cycle stability is observed",
        required_evidence=(
            "One full release cycle passes with no production recovery action that "
            "depends on legacy JSON/Chroma as the serving path."
        ),
    ),
    LegacyRetirementGate(
        gate_id="operator_retirement_approval",
        label="Operator retirement approval is recorded",
        required_evidence=(
            "A human operator approves the retirement plan, retained backup archive, "
            "rollback procedure, and final deletion or archival command."
        ),
    ),
)

REQUIRED_LEGACY_RETIREMENT_GATE_IDS: Final[tuple[str, ...]] = tuple(
    gate.gate_id for gate in LEGACY_RETIREMENT_GATES
)


def legacy_retirement_gate_report(completed_gate_ids: Iterable[str] | None = None) -> dict[str, object]:
    """Return the retirement readiness report without touching legacy stores."""
    completed_input = {str(gate_id) for gate_id in (completed_gate_ids or [])}
    required = set(REQUIRED_LEGACY_RETIREMENT_GATE_IDS)
    completed = sorted(completed_input & required)
    unknown = sorted(completed_input - required)
    missing = [gate_id for gate_id in REQUIRED_LEGACY_RETIREMENT_GATE_IDS if gate_id not in completed]
    retirement_allowed = not missing and not unknown
    return {
        "schema_version": "2026-05-21.legacy_compatibility_policy.v1",
        "operation": "legacy_retirement_gate_report",
        "status": "ready_for_operator_retirement_action" if retirement_allowed else "blocked",
        "runtime_role": LEGACY_COMPATIBILITY_MODE["runtime_role"],
        "product_core": LEGACY_COMPATIBILITY_MODE["product_core"],
        "write_performed": False,
        "active_memory_write_performed": False,
        "deletion_performed": False,
        "retirement_allowed": retirement_allowed,
        "completed_gate_ids": completed,
        "missing_gate_ids": missing,
        "unknown_gate_ids": unknown,
        "required_gates": [asdict(gate) for gate in LEGACY_RETIREMENT_GATES],
    }

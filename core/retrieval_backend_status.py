"""Retrieval backend readiness checks for the Engram Memory OS rebuild.

This module reports backend readiness without changing live retrieval behavior.
The current public server still uses the legacy Chroma-backed memory manager;
Memory OS backend promotion requires explicit migration and adapter proof.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.backend_config import load_backend_config
from core.memory_os_migration import LEDGER_FILENAME, MemoryOSMigrationKernel
from core.retrieval_backend_eval import skipped_retrieval_comparison
from core.vector_index_rebuild import run_vector_index_rebuild_dry_run


STATUS_SCHEMA_VERSION = "2026-05-12.retrieval_backend_status.v1"
DEFAULT_OPERATOR_DOCS_PATH = Path(__file__).resolve().parents[1] / "docs" / "OPERATOR_RECOVERY.md"
FINAL_STATE_POLICY = (
    "For local 1.0, the daemon-owned Memory OS path is the product path. "
    "Direct JSON/Chroma remains compatibility and recovery input. "
    "No optional backend becomes default until parity, recovery, restart, and operator docs pass."
)

DependencyProbe = Callable[[str], bool]


def build_retrieval_backend_status(
    *,
    store_root: str | Path | None = None,
    include_rebuild_probe: bool = False,
    rebuild_batch_size: int = 128,
    dependency_probe: DependencyProbe | None = None,
    operator_docs_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return an evidence-led readiness report for retrieval backend promotion."""
    if rebuild_batch_size < 1:
        raise ValueError("rebuild_batch_size must be positive")

    backend_config = load_backend_config()
    module_available = dependency_probe or _module_available
    chroma_installed = module_available("chromadb")
    lancedb_installed = module_available("lancedb")
    runtime_mode = _runtime_mode()
    store_probe = _build_store_probe(store_root)
    rebuild_probe = _build_rebuild_probe(
        store_root,
        store_probe,
        include_rebuild_probe=include_rebuild_probe,
        rebuild_batch_size=rebuild_batch_size,
    )
    golden_comparison_probe = skipped_retrieval_comparison(
        "No Chroma-vs-candidate golden query comparison was requested."
    )
    corpus_parity_status = _corpus_parity_status(golden_comparison_probe)
    operator_docs_status = _operator_docs_status(
        operator_docs_path,
        required_terms=("backend readiness", "skipped parity", "recovery"),
    )
    recovery_gate_status = _recovery_gate_status(
        operator_docs_status=operator_docs_status,
        corpus_parity_status=corpus_parity_status,
    )
    readiness_gates = _build_readiness_gates(
        lancedb_installed=lancedb_installed,
        daemon_owned=runtime_mode["daemon_owned"],
        store_probe=store_probe,
        rebuild_probe=rebuild_probe,
        golden_comparison_probe=golden_comparison_probe,
        corpus_parity_status=corpus_parity_status,
        recovery_gate_status=recovery_gate_status,
        operator_docs_status=operator_docs_status,
    )
    direct_legacy_backend = _direct_legacy_backend(chroma_installed)
    daemon_memory_os_backend = _daemon_memory_os_backend(runtime_mode)

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "operation": "retrieval_backend_status",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_retrieval_changed": False,
        "runtime_mode": runtime_mode["runtime_mode"],
        "daemon_owned": runtime_mode["daemon_owned"],
        "direct_mode_legacy": runtime_mode["direct_mode_legacy"],
        "runtime": runtime_mode,
        "final_state_policy": FINAL_STATE_POLICY,
        "current_live_backend": (
            daemon_memory_os_backend
            if runtime_mode["daemon_owned"]
            else _current_direct_legacy_backend(direct_legacy_backend)
        ),
        "direct_legacy_backend": direct_legacy_backend,
        "daemon_memory_os_backend": daemon_memory_os_backend,
        "backend_config": backend_config.to_dict(),
        "candidate_dependency_available": lancedb_installed,
        "candidate_backend": {
            "backend": "lancedb",
            "role": "memory_os_candidate_retrieval_index",
            "required": False,
            "requested": backend_config.retrieval_backend == "lancedb",
            "promotion_ready": False,
            "availability": {
                "installed": lancedb_installed,
                "adapter_module": True,
                "contract": "VectorIndex",
            },
            "promotion_blockers": _promotion_blockers(lancedb_installed),
        },
        "vector_contract": {
            "contract": "core.vector_index.VectorIndex",
            "in_memory_adapter": "available_for_contract_and_rebuild_tests",
            "lancedb_adapter": "optional_adapter_not_live",
            "live_retrieval_backend": "unchanged",
        },
        "store_probe": store_probe,
        "rebuild_probe": rebuild_probe,
        "golden_comparison_probe": golden_comparison_probe,
        "corpus_parity_status": corpus_parity_status,
        "recovery_gate_status": recovery_gate_status,
        "operator_docs_status": operator_docs_status,
        "live_switch_decision": _live_switch_decision(),
        "readiness_gates": readiness_gates,
        "recommendation": _recommendation(lancedb_installed, readiness_gates),
        "error": None,
    }


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _runtime_mode() -> dict[str, Any]:
    daemon_url = os.environ.get("ENGRAM_DAEMON_URL", "").strip()
    daemon_owned = bool(daemon_url)
    return {
        "runtime_mode": "daemon_owned_memory_os" if daemon_owned else "direct_legacy_compatibility",
        "daemon_owned": daemon_owned,
        "direct_mode_legacy": not daemon_owned,
        "daemon_url_configured": daemon_owned,
        "daemon_url": daemon_url or None,
    }


def _direct_legacy_backend(chroma_installed: bool) -> dict[str, Any]:
    return {
        "backend": "chroma",
        "role": "compatibility_and_recovery_input",
        "legacy_role": "legacy_live_index",
        "available": chroma_installed,
        "source_of_truth": "legacy JSON memory files remain authoritative; Chroma is rebuildable index state",
    }


def _current_direct_legacy_backend(backend: dict[str, Any]) -> dict[str, Any]:
    current = dict(backend)
    current["role"] = "legacy_live_index"
    return current


def _daemon_memory_os_backend(runtime_mode: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": "memory_os",
        "role": "product_path",
        "daemon_owned": runtime_mode["daemon_owned"],
        "components": ["sqlite_ledger", "content_store", "retrieval_service"],
        "source_of_truth": "daemon-owned Memory OS ledger and content store",
    }


def _build_store_probe(store_root: str | Path | None) -> dict[str, Any]:
    if store_root is None:
        return {
            "requested": False,
            "store_root": None,
            "ledger_exists": None,
            "vector_source_count": None,
            "error": None,
        }

    root = Path(store_root)
    ledger_path = root / LEDGER_FILENAME
    if not ledger_path.exists():
        return {
            "requested": True,
            "store_root": str(root),
            "ledger_exists": False,
            "vector_source_count": None,
            "error": f"Memory OS ledger not found: {ledger_path}",
        }

    try:
        sources = MemoryOSMigrationKernel(root).read_vector_source_records()
    except sqlite3.DatabaseError as exc:
        return {
            "requested": True,
            "store_root": str(root),
            "ledger_exists": True,
            "vector_source_count": None,
            "error": (
                "Memory OS ledger exists but is not compatible with migration "
                f"vector-source probe: {exc}"
            ),
        }
    return {
        "requested": True,
        "store_root": str(root),
        "ledger_exists": True,
        "vector_source_count": len(sources),
        "error": None,
    }


def _build_rebuild_probe(
    store_root: str | Path | None,
    store_probe: dict[str, Any],
    *,
    include_rebuild_probe: bool,
    rebuild_batch_size: int,
) -> dict[str, Any]:
    if not include_rebuild_probe:
        return {
            "requested": False,
            "status": "skipped",
            "source_count": None,
            "document_count": None,
            "batch_count": None,
            "error": None,
        }

    if store_root is None or not store_probe.get("ledger_exists"):
        return {
            "requested": True,
            "status": "blocked",
            "source_count": None,
            "document_count": None,
            "batch_count": None,
            "error": store_probe.get("error") or "store_root with an existing ledger is required",
        }

    report = run_vector_index_rebuild_dry_run(
        store_root,
        batch_size=rebuild_batch_size,
    )
    receipt = report["rebuild_receipt"]
    return {
        "requested": True,
        "status": receipt["status"],
        "source_count": report["source_count"],
        "document_count": receipt["document_count"],
        "batch_count": receipt["batch_count"],
        "embedding_provider": report["embedding_provider"],
        "error": None,
    }


def _build_readiness_gates(
    *,
    lancedb_installed: bool,
    daemon_owned: bool,
    store_probe: dict[str, Any],
    rebuild_probe: dict[str, Any],
    golden_comparison_probe: dict[str, Any],
    corpus_parity_status: dict[str, Any],
    recovery_gate_status: dict[str, Any],
    operator_docs_status: dict[str, Any],
) -> dict[str, dict[str, str]]:
    store_requested = bool(store_probe.get("requested"))
    ledger_exists = bool(store_probe.get("ledger_exists")) and store_probe.get("error") is None
    rebuild_status = str(rebuild_probe.get("status"))
    return {
        "adapter_contract": {
            "status": "pass",
            "evidence": "VectorIndex contract and deterministic in-memory adapter exist for parity tests.",
        },
        "migrated_store_probe": {
            "status": "pass" if ledger_exists else ("blocked" if store_requested else "unknown"),
            "evidence": _store_probe_evidence(store_probe),
        },
        "deterministic_rebuild_probe": {
            "status": "pass" if rebuild_status == "pass" else rebuild_status,
            "evidence": _rebuild_probe_evidence(rebuild_probe),
        },
        "lancedb_dependency": {
            "status": "ready_for_spike" if lancedb_installed else "blocked",
            "evidence": "lancedb import is available." if lancedb_installed else "lancedb is not installed.",
        },
        "real_lancedb_corpus_spike": {
            "status": "blocked",
            "evidence": "Real LanceDB persistence, metadata filtering, hybrid search, and Windows behavior are not yet proven against the migrated corpus.",
        },
        "metadata_filtering": {
            "status": "blocked",
            "evidence": "Real LanceDB metadata filtering has not passed against the migrated corpus.",
        },
        "golden_retrieval_comparison": {
            "status": str(golden_comparison_probe.get("status") or "skipped"),
            "evidence": _golden_comparison_evidence(golden_comparison_probe),
        },
        "corpus_parity": {
            "status": str(corpus_parity_status["status"]),
            "evidence": str(corpus_parity_status["evidence"]),
        },
        "multi_session_daemon": {
            "status": "pass" if daemon_owned else "blocked",
            "evidence": (
                "ENGRAM_DAEMON_URL is configured; daemon-owned Memory OS is the product path."
                if daemon_owned
                else "Direct compatibility mode is active; daemon-owned Memory OS is not the current entrypoint."
            ),
        },
        "recovery_gate": {
            "status": str(recovery_gate_status["status"]),
            "evidence": str(recovery_gate_status["evidence"]),
        },
        "operator_docs": {
            "status": str(operator_docs_status["status"]),
            "evidence": str(operator_docs_status["evidence"]),
        },
        "windows_path_reliability": {
            "status": "blocked",
            "evidence": "Windows path/restart reliability has not passed for a live retrieval backend switch.",
        },
        "live_backend_switch": {
            "status": "blocked",
            "evidence": FINAL_STATE_POLICY,
        },
    }


def _store_probe_evidence(store_probe: dict[str, Any]) -> str:
    if not store_probe.get("requested"):
        return "No migrated store was supplied."
    if store_probe.get("ledger_exists"):
        return f"Ledger exists with {store_probe.get('vector_source_count')} vector source records."
    return str(store_probe.get("error") or "Ledger does not exist.")


def _rebuild_probe_evidence(rebuild_probe: dict[str, Any]) -> str:
    status = rebuild_probe.get("status")
    if status == "pass":
        return (
            f"Deterministic dry-run rebuilt {rebuild_probe.get('document_count')} "
            f"documents from {rebuild_probe.get('source_count')} source records."
        )
    if status == "skipped":
        return "Rebuild probe was not requested."
    return str(rebuild_probe.get("error") or "Rebuild probe did not pass.")


def _golden_comparison_evidence(golden_comparison_probe: dict[str, Any]) -> str:
    status = golden_comparison_probe.get("status")
    if status == "pass":
        return (
            f"Candidate matched golden retrieval expectations for "
            f"{golden_comparison_probe.get('query_count')} queries."
        )
    if status == "fail":
        return (
            f"Candidate failed {golden_comparison_probe.get('failed_count')} "
            "golden retrieval queries."
        )
    return str(
        golden_comparison_probe.get("reason")
        or "Golden retrieval comparison was not requested."
    )


def _corpus_parity_status(golden_comparison_probe: dict[str, Any]) -> dict[str, Any]:
    source_status = str(golden_comparison_probe.get("status") or "skipped")
    if source_status == "pass":
        return {
            "status": "pass",
            "source_status": source_status,
            "blocker": False,
            "evidence": _golden_comparison_evidence(golden_comparison_probe),
        }
    return {
        "status": "blocked",
        "source_status": source_status,
        "blocker": True,
        "evidence": "Skipped or failed Chroma-vs-candidate corpus parity blocks retrieval promotion.",
    }


def _operator_docs_status(
    operator_docs_path: str | Path | None,
    *,
    required_terms: tuple[str, ...],
) -> dict[str, Any]:
    path = Path(operator_docs_path) if operator_docs_path is not None else DEFAULT_OPERATOR_DOCS_PATH
    if not path.exists():
        return {
            "status": "blocked",
            "path": str(path),
            "missing_terms": list(required_terms),
            "evidence": f"Operator recovery documentation not found: {path}",
        }
    text = path.read_text(encoding="utf-8").lower()
    missing_terms = [term for term in required_terms if term.lower() not in text]
    return {
        "status": "pass" if not missing_terms else "blocked",
        "path": str(path),
        "missing_terms": missing_terms,
        "evidence": (
            "Operator backend recovery documentation covers required terms."
            if not missing_terms
            else f"Operator backend documentation is missing: {', '.join(missing_terms)}"
        ),
    }


def _recovery_gate_status(
    *,
    operator_docs_status: dict[str, Any],
    corpus_parity_status: dict[str, Any],
) -> dict[str, Any]:
    if operator_docs_status.get("status") != "pass":
        return {
            "status": "blocked",
            "blocker": True,
            "evidence": "Recovery gate is blocked because operator recovery documentation is incomplete.",
        }
    if corpus_parity_status.get("status") != "pass":
        return {
            "status": "blocked",
            "blocker": True,
            "evidence": "Recovery gate is blocked until corpus parity and rollback drills pass.",
        }
    return {
        "status": "blocked",
        "blocker": True,
        "evidence": "Recovery drill is documented but has not been executed for a live retrieval switch.",
    }


def _live_switch_decision() -> dict[str, Any]:
    return {
        "decision": "deferred",
        "allow_live_switch": False,
        "policy": FINAL_STATE_POLICY,
    }


def _promotion_blockers(lancedb_installed: bool) -> list[str]:
    blockers = [
        "real LanceDB corpus spike has not proven persistence, filtering, hybrid search, and rebuild behavior",
        "golden Chroma-vs-candidate retrieval comparison has not passed",
        "Memory OS daemon/single-owner retrieval backend has not replaced legacy embedded Chroma",
    ]
    if not lancedb_installed:
        blockers.insert(0, "LanceDB optional dependency is not installed")
    return blockers


def _recommendation(lancedb_installed: bool, readiness_gates: dict[str, dict[str, str]]) -> str:
    if not lancedb_installed:
        return (
            "Keep Chroma as the legacy live index and run a dedicated optional LanceDB spike before "
            "promoting LanceDB as the Memory OS retrieval backend."
        )
    if readiness_gates["deterministic_rebuild_probe"]["status"] != "pass":
        return (
            "Run retrieval_backend_status with include_rebuild_probe=True against a migrated store, "
            "then prove the same corpus through the real LanceDB adapter."
        )
    return (
        "Dependency is available, but promotion still needs real LanceDB corpus tests and the "
        "single-owner daemon path before live retrieval can switch."
    )

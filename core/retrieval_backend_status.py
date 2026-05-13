"""Retrieval backend readiness checks for the Engram Memory OS rebuild.

This module reports backend readiness without changing live retrieval behavior.
The current public server still uses the legacy Chroma-backed memory manager;
Memory OS backend promotion requires explicit migration and adapter proof.
"""
from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.backend_config import load_backend_config
from core.memory_os_migration import LEDGER_FILENAME, MemoryOSMigrationKernel
from core.retrieval_backend_eval import skipped_retrieval_comparison
from core.vector_index_rebuild import run_vector_index_rebuild_dry_run


STATUS_SCHEMA_VERSION = "2026-05-12.retrieval_backend_status.v1"

DependencyProbe = Callable[[str], bool]


def build_retrieval_backend_status(
    *,
    store_root: str | Path | None = None,
    include_rebuild_probe: bool = False,
    rebuild_batch_size: int = 128,
    dependency_probe: DependencyProbe | None = None,
) -> dict[str, Any]:
    """Return an evidence-led readiness report for retrieval backend promotion."""
    if rebuild_batch_size < 1:
        raise ValueError("rebuild_batch_size must be positive")

    backend_config = load_backend_config()
    module_available = dependency_probe or _module_available
    chroma_installed = module_available("chromadb")
    lancedb_installed = module_available("lancedb")
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
    readiness_gates = _build_readiness_gates(
        lancedb_installed=lancedb_installed,
        store_probe=store_probe,
        rebuild_probe=rebuild_probe,
        golden_comparison_probe=golden_comparison_probe,
    )

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "operation": "retrieval_backend_status",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_retrieval_changed": False,
        "current_live_backend": {
            "backend": "chroma",
            "role": "legacy_live_index",
            "available": chroma_installed,
            "source_of_truth": "legacy JSON memory files remain authoritative; Chroma is rebuildable index state",
        },
        "backend_config": backend_config.to_dict(),
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
        "readiness_gates": readiness_gates,
        "recommendation": _recommendation(lancedb_installed, readiness_gates),
        "error": None,
    }


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


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

    sources = MemoryOSMigrationKernel(root).read_vector_source_records()
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
    store_probe: dict[str, Any],
    rebuild_probe: dict[str, Any],
    golden_comparison_probe: dict[str, Any],
) -> dict[str, dict[str, str]]:
    store_requested = bool(store_probe.get("requested"))
    ledger_exists = bool(store_probe.get("ledger_exists"))
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
        "golden_retrieval_comparison": {
            "status": str(golden_comparison_probe.get("status") or "skipped"),
            "evidence": _golden_comparison_evidence(golden_comparison_probe),
        },
        "multi_session_daemon": {
            "status": "blocked",
            "evidence": "The Memory OS daemon/single-owner backend path has not replaced legacy embedded Chroma retrieval.",
        },
        "live_backend_switch": {
            "status": "blocked",
            "evidence": "Live retrieval must remain on legacy Chroma until migration, adapter, and daemon gates pass.",
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

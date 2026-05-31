"""Graph backend readiness checks for the Engram Memory OS rebuild.

The live graph path remains the JSON-backed GraphStore. Kuzu is an optional
candidate backend until dependency, corpus, and daemon migration gates pass.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.backend_config import load_backend_config
from core.graph_backend_eval import skipped_graph_parity
from core.graph_store import EDGES_PATH, JsonGraphStore
from core.memory_os_migration import LEDGER_FILENAME, MemoryOSMigrationKernel


STATUS_SCHEMA_VERSION = "2026-05-12.graph_backend_status.v1"
DEFAULT_OPERATOR_DOCS_PATH = Path(__file__).resolve().parents[1] / "docs" / "OPERATOR_RECOVERY.md"
FINAL_STATE_POLICY = (
    "For local 1.0, the daemon-owned Memory OS path is the product path. "
    "Direct JSON/Chroma remains compatibility and recovery input. "
    "No optional backend becomes default until parity, recovery, restart, and operator docs pass."
)

DependencyProbe = Callable[[str], bool]


def build_graph_backend_status(
    *,
    store_root: str | Path | None = None,
    graph_path: str | Path | None = EDGES_PATH,
    dependency_probe: DependencyProbe | None = None,
    operator_docs_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a no-write graph backend readiness report."""
    backend_config = load_backend_config()
    module_available = dependency_probe or _module_available
    kuzu_installed = module_available("kuzu")
    runtime_mode = _runtime_mode()
    live_probe = _build_live_graph_probe(graph_path)
    store_probe = _build_store_probe(store_root)
    graph_parity_probe = skipped_graph_parity(
        "No Kuzu-vs-JSON graph parity run was requested."
    )
    corpus_parity_status = _corpus_parity_status(graph_parity_probe)
    operator_docs_status = _operator_docs_status(
        operator_docs_path,
        required_terms=("backend readiness", "skipped parity", "recovery"),
    )
    recovery_gate_status = _recovery_gate_status(
        operator_docs_status=operator_docs_status,
        corpus_parity_status=corpus_parity_status,
    )
    readiness_gates = _build_readiness_gates(
        kuzu_installed=kuzu_installed,
        daemon_owned=runtime_mode["daemon_owned"],
        live_probe=live_probe,
        store_probe=store_probe,
        graph_parity_probe=graph_parity_probe,
        corpus_parity_status=corpus_parity_status,
        recovery_gate_status=recovery_gate_status,
        operator_docs_status=operator_docs_status,
    )
    direct_legacy_backend = _direct_legacy_backend(live_probe)
    daemon_memory_os_backend = _daemon_memory_os_backend(runtime_mode)

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "operation": "graph_backend_status",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_graph_backend_changed": False,
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
        "candidate_dependency_available": kuzu_installed,
        "candidate_backend": {
            "backend": "kuzu",
            "role": "memory_os_candidate_graph_store",
            "required": False,
            "requested": backend_config.graph_backend == "kuzu",
            "promotion_ready": False,
            "availability": {
                "installed": kuzu_installed,
                "adapter_module": True,
                "contract": "GraphStore",
            },
            "promotion_blockers": _promotion_blockers(kuzu_installed),
        },
        "graph_contract": {
            "contract": "core.graph_store.GraphStore",
            "json_adapter": "live_default",
            "kuzu_adapter": "optional_adapter_not_live",
            "traversal_contract": "graph traversal returns refs and evidence, not memory bodies",
        },
        "live_graph_probe": live_probe,
        "store_probe": store_probe,
        "graph_parity_probe": graph_parity_probe,
        "corpus_parity_status": corpus_parity_status,
        "recovery_gate_status": recovery_gate_status,
        "operator_docs_status": operator_docs_status,
        "live_switch_decision": _live_switch_decision(),
        "readiness_gates": readiness_gates,
        "recommendation": _recommendation(kuzu_installed, readiness_gates),
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


def _direct_legacy_backend(live_probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": "json_graph_store",
        "role": "compatibility_and_recovery_input",
        "legacy_role": "legacy_live_graph_store",
        "graph_path": live_probe["graph_path"],
        "edge_count": live_probe["edge_count"],
        "available": live_probe["error"] is None,
        "source_of_truth": "JSON graph document remains the local-first compatibility graph store.",
    }


def _current_direct_legacy_backend(backend: dict[str, Any]) -> dict[str, Any]:
    current = dict(backend)
    current["role"] = "legacy_live_graph_store"
    return current


def _daemon_memory_os_backend(runtime_mode: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": "memory_os",
        "role": "product_path",
        "daemon_owned": runtime_mode["daemon_owned"],
        "components": ["sqlite_ledger", "kuzu_graph_service", "graph_evidence_packets"],
        "source_of_truth": "daemon-owned Memory OS graph records",
    }


def _build_live_graph_probe(graph_path: str | Path | None) -> dict[str, Any]:
    if graph_path is None:
        return {
            "requested": False,
            "graph_path": None,
            "exists": None,
            "edge_count": None,
            "schema_version": None,
            "error": None,
        }

    path = Path(graph_path)
    if not path.exists():
        return {
            "requested": True,
            "graph_path": str(path),
            "exists": False,
            "edge_count": 0,
            "schema_version": None,
            "error": None,
        }

    graph = JsonGraphStore(edges_path=path).load_graph()
    edges = graph.get("edges") if isinstance(graph, dict) else []
    edge_count = len(edges) if isinstance(edges, list) else 0
    return {
        "requested": True,
        "graph_path": str(path),
        "exists": True,
        "edge_count": edge_count,
        "schema_version": graph.get("schema_version") if isinstance(graph, dict) else None,
        "error": None,
    }


def _build_store_probe(store_root: str | Path | None) -> dict[str, Any]:
    if store_root is None:
        return {
            "requested": False,
            "store_root": None,
            "ledger_exists": None,
            "graph_edge_count": None,
            "error": None,
        }

    root = Path(store_root)
    ledger_path = root / LEDGER_FILENAME
    if not ledger_path.exists():
        return {
            "requested": True,
            "store_root": str(root),
            "ledger_exists": False,
            "graph_edge_count": None,
            "error": f"Memory OS ledger not found: {ledger_path}",
        }

    try:
        edges = MemoryOSMigrationKernel(root).read_graph_edge_records()
    except sqlite3.DatabaseError as exc:
        return {
            "requested": True,
            "store_root": str(root),
            "ledger_exists": True,
            "graph_edge_count": None,
            "error": (
                "Memory OS ledger exists but is not compatible with migration "
                f"graph-edge probe: {exc}"
            ),
        }
    return {
        "requested": True,
        "store_root": str(root),
        "ledger_exists": True,
        "graph_edge_count": len(edges),
        "error": None,
    }


def _build_readiness_gates(
    *,
    kuzu_installed: bool,
    daemon_owned: bool,
    live_probe: dict[str, Any],
    store_probe: dict[str, Any],
    graph_parity_probe: dict[str, Any],
    corpus_parity_status: dict[str, Any],
    recovery_gate_status: dict[str, Any],
    operator_docs_status: dict[str, Any],
) -> dict[str, dict[str, str]]:
    store_requested = bool(store_probe.get("requested"))
    ledger_exists = bool(store_probe.get("ledger_exists")) and store_probe.get("error") is None
    live_requested = bool(live_probe.get("requested"))
    live_status = "pass" if live_probe.get("error") is None else "blocked"
    return {
        "graph_store_contract": {
            "status": "pass",
            "evidence": "JsonGraphStore and optional KuzuGraphStore preserve the GraphStore document contract.",
        },
        "live_json_graph_probe": {
            "status": live_status if live_requested else "unknown",
            "evidence": _live_probe_evidence(live_probe),
        },
        "migrated_graph_edges": {
            "status": "pass" if ledger_exists else ("blocked" if store_requested else "unknown"),
            "evidence": _store_probe_evidence(store_probe),
        },
        "kuzu_dependency": {
            "status": "ready_for_spike" if kuzu_installed else "blocked",
            "evidence": "kuzu import is available." if kuzu_installed else "kuzu is not installed.",
        },
        "real_kuzu_corpus_spike": {
            "status": "blocked",
            "evidence": "Real Kuzu persistence, traversal, import parity, and Windows behavior are not yet proven against the migrated corpus.",
        },
        "metadata_filtering": {
            "status": "blocked",
            "evidence": "Real Kuzu graph filters and traversal query shapes have not passed against the migrated corpus.",
        },
        "graph_parity": {
            "status": str(graph_parity_probe.get("status") or "skipped"),
            "evidence": _graph_parity_evidence(graph_parity_probe),
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
            "evidence": "Windows path/restart reliability has not passed for a live graph backend switch.",
        },
        "live_backend_switch": {
            "status": "blocked",
            "evidence": FINAL_STATE_POLICY,
        },
    }


def _live_probe_evidence(live_probe: dict[str, Any]) -> str:
    if not live_probe.get("requested"):
        return "No live graph path was supplied."
    if live_probe.get("exists"):
        return f"Graph document exists with {live_probe.get('edge_count')} edges."
    return "Graph document does not exist; JsonGraphStore would load an empty graph."


def _store_probe_evidence(store_probe: dict[str, Any]) -> str:
    if not store_probe.get("requested"):
        return "No migrated store was supplied."
    if store_probe.get("ledger_exists"):
        return f"Ledger exists with {store_probe.get('graph_edge_count')} graph edge records."
    return str(store_probe.get("error") or "Ledger does not exist.")


def _graph_parity_evidence(graph_parity_probe: dict[str, Any]) -> str:
    status = graph_parity_probe.get("status")
    if status == "pass":
        return (
            f"Graph parity passed for {graph_parity_probe.get('edge_count')} edges, "
            f"including {graph_parity_probe.get('cross_document_edge_count')} cross-document edges."
        )
    if status == "fail":
        return (
            f"Graph parity failed with {graph_parity_probe.get('issue_count')} issues."
        )
    return str(
        graph_parity_probe.get("reason")
        or "Graph parity was not requested."
    )


def _corpus_parity_status(graph_parity_probe: dict[str, Any]) -> dict[str, Any]:
    source_status = str(graph_parity_probe.get("status") or "skipped")
    if source_status == "pass":
        return {
            "status": "pass",
            "source_status": source_status,
            "blocker": False,
            "evidence": _graph_parity_evidence(graph_parity_probe),
        }
    return {
        "status": "blocked",
        "source_status": source_status,
        "blocker": True,
        "evidence": "Skipped or failed Kuzu-vs-JSON corpus parity blocks graph promotion.",
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
        "evidence": "Recovery drill is documented but has not been executed for a live graph switch.",
    }


def _live_switch_decision() -> dict[str, Any]:
    return {
        "decision": "deferred",
        "allow_live_switch": False,
        "policy": FINAL_STATE_POLICY,
    }


def _promotion_blockers(kuzu_installed: bool) -> list[str]:
    blockers = [
        "real Kuzu corpus spike has not proven import parity, traversal behavior, and persistence",
        "Kuzu-vs-JSON graph parity has not passed",
        "Memory OS daemon/single-owner graph backend has not replaced legacy JSON graph storage",
    ]
    if not kuzu_installed:
        blockers.insert(0, "Kuzu optional dependency is not installed")
    return blockers


def _recommendation(kuzu_installed: bool, readiness_gates: dict[str, dict[str, str]]) -> str:
    if not kuzu_installed:
        return (
            "Keep JSON graph storage as the live backend and run a dedicated optional Kuzu spike "
            "before promoting Kuzu as the Memory OS graph backend."
        )
    if readiness_gates["migrated_graph_edges"]["status"] != "pass":
        return (
            "Probe a migrated Memory OS store with graph edges, then prove the same corpus through "
            "the real Kuzu adapter."
        )
    return (
        "Dependency is available, but promotion still needs real Kuzu corpus tests and the "
        "single-owner daemon path before live graph storage can switch."
    )

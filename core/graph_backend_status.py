"""Graph backend readiness checks for the Engram Memory OS rebuild.

The live graph path remains the JSON-backed GraphStore. Kuzu is an optional
candidate backend until dependency, corpus, and daemon migration gates pass.
"""
from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.backend_config import load_backend_config
from core.graph_store import EDGES_PATH, JsonGraphStore
from core.memory_os_migration import LEDGER_FILENAME, MemoryOSMigrationKernel


STATUS_SCHEMA_VERSION = "2026-05-12.graph_backend_status.v1"

DependencyProbe = Callable[[str], bool]


def build_graph_backend_status(
    *,
    store_root: str | Path | None = None,
    graph_path: str | Path | None = EDGES_PATH,
    dependency_probe: DependencyProbe | None = None,
) -> dict[str, Any]:
    """Return a no-write graph backend readiness report."""
    backend_config = load_backend_config()
    module_available = dependency_probe or _module_available
    kuzu_installed = module_available("kuzu")
    live_probe = _build_live_graph_probe(graph_path)
    store_probe = _build_store_probe(store_root)
    readiness_gates = _build_readiness_gates(
        kuzu_installed=kuzu_installed,
        live_probe=live_probe,
        store_probe=store_probe,
    )

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "operation": "graph_backend_status",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_graph_backend_changed": False,
        "current_live_backend": {
            "backend": "json_graph_store",
            "role": "legacy_live_graph_store",
            "graph_path": live_probe["graph_path"],
            "edge_count": live_probe["edge_count"],
            "available": live_probe["error"] is None,
            "source_of_truth": "JSON graph document remains the local-first live graph store.",
        },
        "backend_config": backend_config.to_dict(),
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
        "readiness_gates": readiness_gates,
        "recommendation": _recommendation(kuzu_installed, readiness_gates),
        "error": None,
    }


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


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

    edges = MemoryOSMigrationKernel(root).read_graph_edge_records()
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
    live_probe: dict[str, Any],
    store_probe: dict[str, Any],
) -> dict[str, dict[str, str]]:
    store_requested = bool(store_probe.get("requested"))
    ledger_exists = bool(store_probe.get("ledger_exists"))
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
        "multi_session_daemon": {
            "status": "blocked",
            "evidence": "The Memory OS daemon/single-owner graph backend path has not replaced legacy JSON graph storage.",
        },
        "live_backend_switch": {
            "status": "blocked",
            "evidence": "Live graph storage must remain JSON-backed until migration, adapter, and daemon gates pass.",
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


def _promotion_blockers(kuzu_installed: bool) -> list[str]:
    blockers = [
        "real Kuzu corpus spike has not proven import parity, traversal behavior, and persistence",
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

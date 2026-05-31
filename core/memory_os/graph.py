"""Memory OS graph service over the swappable GraphStore contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.graph_store import GraphStore, empty_graph
from core.kuzu_graph_store import KuzuGraphStore
from core.memory_os._records import hash_payload, list_records, upsert_record
from core.memory_os.ledger import MemoryOSLedger

GRAPH_RECONCILIATION_SCHEMA_VERSION = "2026-05-21.graph-reconciliation.v1"
GRAPH_STORE_REPAIR_SCHEMA_VERSION = "2026-05-22.graph-store-repair.v1"
GRAPH_STORE_REPAIR_MODES = {"upsert_missing", "rebuild_from_ledger"}
CONFLICT_EDGE_TYPES = {"contradicts", "supersedes"}
REQUIRED_EDGE_FIELDS = {
    "edge_id",
    "from_ref",
    "to_ref",
    "edge_type",
    "confidence",
    "evidence",
    "source",
    "status",
    "created_by",
    "created_at",
    "updated_at",
}
EDGE_SIGNATURE_FIELDS = (
    "edge_id",
    "from_ref",
    "to_ref",
    "edge_type",
    "confidence",
    "evidence",
    "source",
    "status",
    "created_by",
    "created_at",
    "updated_at",
)


class MemoryOSGraph:
    """Import and traverse evidence-bearing graph edges without loading bodies."""

    def __init__(
        self,
        ledger: MemoryOSLedger | None = None,
        *,
        graph_store: GraphStore | None = None,
        database_path: str | Path = "data/memory_os_graph.kuzu",
    ) -> None:
        self.ledger = ledger
        self.graph_store = graph_store or KuzuGraphStore(database_path)

    def import_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [self._normalize_edge(edge) for edge in edges]
        edge_ids = [edge["edge_id"] for edge in normalized]
        incremental_upsert = getattr(self.graph_store, "upsert_edges", None)
        if callable(incremental_upsert):
            incremental_upsert(normalized)
            for edge in normalized:
                if self.ledger is not None:
                    upsert_record(self.ledger, "graph_edges", edge["edge_id"], edge)
            return {"imported_count": len(normalized), "edge_ids": edge_ids}

        graph = self.graph_store.load_graph()
        graph.setdefault("edges", [])
        by_id = {
            str(edge.get("edge_id")): edge
            for edge in graph.get("edges", [])
            if isinstance(edge, dict) and edge.get("edge_id")
        }
        for edge in normalized:
            by_id[edge["edge_id"]] = edge
        graph["edges"] = [by_id[edge_id] for edge_id in sorted(by_id)]
        self.graph_store.save_graph(graph)
        for edge in normalized:
            if self.ledger is not None:
                upsert_record(self.ledger, "graph_edges", edge["edge_id"], edge)
        return {"imported_count": len(normalized), "edge_ids": edge_ids}

    def load_edges(self) -> list[dict[str, Any]]:
        graph = self.graph_store.load_graph() or empty_graph()
        edges = graph.get("edges", [])
        return [dict(edge) for edge in edges if isinstance(edge, dict)]

    def reconciliation_state(self, *, sample_limit: int = 10) -> dict[str, Any]:
        """Compare ledger graph-edge records to the graph store contract view."""
        if self.ledger is None:
            return {
                "schema_version": GRAPH_RECONCILIATION_SCHEMA_VERSION,
                "status": "untracked",
                "trusted_for_evidence": False,
                "repair_required": False,
                "ledger": None,
                "graph_store": {
                    "backend": type(self.graph_store).__name__,
                    "edge_count": None,
                    "edge_hash": None,
                },
                "drift": None,
                "repair_guidance": {
                    "message": "Graph reconciliation requires a Memory OS ledger authority.",
                    "can_repair_automatically": False,
                },
            }

        try:
            ledger_edges = list_records(self.ledger, "graph_edges")
        except Exception as exc:
            return _graph_reconciliation_error(
                backend=type(self.graph_store).__name__,
                phase="ledger_read",
                error=exc,
            )

        try:
            store_edges = self.load_edges()
        except Exception as exc:
            return _graph_reconciliation_error(
                backend=type(self.graph_store).__name__,
                phase="graph_store_read",
                error=exc,
            )

        return _graph_reconciliation_report(
            ledger_edges,
            store_edges,
            backend=type(self.graph_store).__name__,
            sample_limit=sample_limit,
        )

    def repair_store_from_ledger(
        self,
        *,
        repair_mode: str = "upsert_missing",
        limit: int = 5000,
        accept: bool = False,
        approved_by: str | None = None,
        sample_limit: int = 10,
    ) -> dict[str, Any]:
        """Replay exact ledger graph-edge records into the graph store after review."""
        normalized_mode = str(repair_mode or "upsert_missing").strip() or "upsert_missing"
        normalized_limit = _positive_int(limit, default=5000)
        normalized_sample_limit = _positive_int(sample_limit, default=10)
        base: dict[str, Any] = {
            "schema_version": GRAPH_STORE_REPAIR_SCHEMA_VERSION,
            "operation": "repair_graph_store_reconciliation",
            "repair_mode": normalized_mode,
            "limit": normalized_limit,
            "candidate_count": 0,
            "candidate_edge_id_sample": [],
            "repaired_count": 0,
            "repaired_edge_id_sample": [],
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }
        if normalized_mode not in GRAPH_STORE_REPAIR_MODES:
            return {
                **base,
                "status": "invalid_request",
                "error": {
                    "code": "unsupported_repair_mode",
                    "message": f"Unsupported graph store repair mode: {normalized_mode}",
                    "supported_modes": sorted(GRAPH_STORE_REPAIR_MODES),
                },
            }
        if self.ledger is None:
            return {
                **base,
                "status": "unavailable",
                "error": {
                    "code": "ledger_unavailable",
                    "message": "Graph store repair requires a Memory OS ledger authority.",
                },
            }

        try:
            ledger_edges = list_records(self.ledger, "graph_edges")
        except Exception as exc:
            return {
                **base,
                "status": "error",
                "error": {"code": "ledger_read_failed", "message": str(exc)},
            }
        try:
            store_edges = self.load_edges()
        except Exception as exc:
            return {
                **base,
                "status": "error",
                "error": {"code": "graph_store_read_failed", "message": str(exc)},
            }

        before = _graph_reconciliation_report(
            ledger_edges,
            store_edges,
            backend=type(self.graph_store).__name__,
            sample_limit=normalized_sample_limit,
        )
        base["before"] = before
        if before["status"] == "reconciled":
            return {**base, "status": "noop", "after": before}

        plan = _graph_store_repair_plan(
            ledger_edges,
            store_edges,
            before,
            repair_mode=normalized_mode,
            limit=normalized_limit,
            sample_limit=normalized_sample_limit,
        )
        candidate_edges = plan.get("candidate_edges_for_write") or []
        public_plan = {
            key: value
            for key, value in plan.items()
            if key != "candidate_edges_for_write"
        }
        response = {
            **base,
            **public_plan,
        }
        if plan.get("status") == "blocked":
            return response
        if not accept:
            return {**response, "status": "prepared"}
        if not str(approved_by or "").strip():
            return {
                **response,
                "status": "policy_denied",
                "error": {
                    "code": "approval_required",
                    "message": "Graph store repair requires approved_by when accept=True.",
                },
            }

        if not candidate_edges and normalized_mode != "rebuild_from_ledger":
            return {**response, "status": "noop", "after": before}

        if normalized_mode == "upsert_missing":
            self._upsert_graph_store_edges(candidate_edges)
        else:
            graph = empty_graph()
            graph["edges"] = list(candidate_edges)
            self.graph_store.save_graph(graph)

        after = self.reconciliation_state(sample_limit=normalized_sample_limit)
        repaired_ids = [str(edge.get("edge_id") or "") for edge in candidate_edges if edge.get("edge_id")]
        return {
            **response,
            "status": "ok" if after.get("status") == "reconciled" else "partial",
            "approved_by": approved_by,
            "after": after,
            "repaired_count": len(repaired_ids),
            "repaired_edge_id_sample": repaired_ids[:normalized_sample_limit],
            "write_performed": True,
            "graph_write_performed": True,
        }

    def _upsert_graph_store_edges(self, edges: list[dict[str, Any]]) -> None:
        incremental_upsert = getattr(self.graph_store, "upsert_edges", None)
        if callable(incremental_upsert):
            incremental_upsert(edges)
            return
        graph = self.graph_store.load_graph()
        graph.setdefault("edges", [])
        by_id = {
            str(edge.get("edge_id")): edge
            for edge in graph.get("edges", [])
            if isinstance(edge, dict) and edge.get("edge_id")
        }
        for edge in edges:
            by_id[str(edge["edge_id"])] = edge
        graph["edges"] = [by_id[edge_id] for edge_id in sorted(by_id)]
        self.graph_store.save_graph(graph)

    def find_paths(
        self,
        from_ref: dict[str, Any],
        to_ref: dict[str, Any],
        *,
        max_hops: int = 2,
        edge_types: set[str] | list[str] | None = None,
    ) -> dict[str, Any]:
        allowed_types = set(edge_types or [])
        paths: list[dict[str, Any]] = []
        queue: list[tuple[dict[str, Any], list[dict[str, Any]]]] = [(from_ref, [])]
        while queue:
            current_ref, path_edges = queue.pop(0)
            if len(path_edges) >= max_hops:
                continue
            for edge in self.load_edges():
                if allowed_types and edge.get("edge_type") not in allowed_types:
                    continue
                if edge.get("from_ref") != current_ref:
                    continue
                next_edges = [*path_edges, _edge_payload(edge)]
                if edge.get("to_ref") == to_ref:
                    paths.append(
                        {
                            "edges": next_edges,
                            "evidence": [item["evidence"] for item in next_edges],
                        }
                    )
                    continue
                queue.append((edge.get("to_ref"), next_edges))
        return {"from_ref": from_ref, "to_ref": to_ref, "count": len(paths), "paths": paths}

    def impact_scan(
        self,
        root_ref: dict[str, Any],
        *,
        edge_types: set[str] | list[str] | None = None,
    ) -> dict[str, Any]:
        allowed_types = set(edge_types or [])
        edges = [
            _edge_payload(edge)
            for edge in self.load_edges()
            if edge.get("from_ref") == root_ref and (not allowed_types or edge.get("edge_type") in allowed_types)
        ]
        return {"root_ref": root_ref, "count": len(edges), "edges": edges}

    def conflict_paths(self, ref: dict[str, Any]) -> dict[str, Any]:
        paths = [
            {
                "edges": [_edge_payload(edge)],
                "evidence": [str(edge["evidence"])],
            }
            for edge in self.load_edges()
            if edge.get("from_ref") == ref and edge.get("edge_type") in CONFLICT_EDGE_TYPES
        ]
        return {"from_ref": ref, "count": len(paths), "paths": paths}

    @staticmethod
    def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
        missing = REQUIRED_EDGE_FIELDS - set(edge)
        if missing:
            raise ValueError(f"graph edge missing required field: {sorted(missing)[0]}")
        normalized = dict(edge)
        normalized["from_ref"] = dict(edge["from_ref"])
        normalized["to_ref"] = dict(edge["to_ref"])
        normalized["confidence"] = float(edge["confidence"])
        return normalized


def _edge_payload(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": edge["edge_id"],
        "from_ref": edge["from_ref"],
        "to_ref": edge["to_ref"],
        "edge_type": edge["edge_type"],
        "confidence": edge["confidence"],
        "evidence": edge["evidence"],
        "source": edge["source"],
        "status": edge["status"],
        "created_by": edge["created_by"],
        "created_at": edge["created_at"],
        "updated_at": edge["updated_at"],
    }


def _graph_reconciliation_report(
    ledger_edges: list[dict[str, Any]],
    store_edges: list[dict[str, Any]],
    *,
    backend: str,
    sample_limit: int,
) -> dict[str, Any]:
    ledger_signature = _edge_signature_summary(ledger_edges)
    store_signature = _edge_signature_summary(store_edges)
    ledger_by_id = _edges_by_id(ledger_edges)
    store_by_id = _edges_by_id(store_edges)

    ledger_ids = set(ledger_by_id)
    store_ids = set(store_by_id)
    missing_in_store = sorted(ledger_ids - store_ids)
    extra_in_store = sorted(store_ids - ledger_ids)
    mismatched = sorted(
        edge_id
        for edge_id in ledger_ids & store_ids
        if _edge_signature_payload(ledger_by_id[edge_id])
        != _edge_signature_payload(store_by_id[edge_id])
    )
    duplicate_ledger_edge_ids = _duplicate_edge_ids(ledger_edges)
    duplicate_store_edge_ids = _duplicate_edge_ids(store_edges)
    ledger_missing_edge_id_count = sum(1 for edge in ledger_edges if not edge.get("edge_id"))
    store_missing_edge_id_count = sum(1 for edge in store_edges if not edge.get("edge_id"))
    ledger_malformed = _malformed_edge_samples(ledger_edges, sample_limit=sample_limit)
    store_malformed = _malformed_edge_samples(store_edges, sample_limit=sample_limit)
    drifted = bool(
        missing_in_store
        or extra_in_store
        or mismatched
        or duplicate_ledger_edge_ids
        or duplicate_store_edge_ids
        or ledger_missing_edge_id_count
        or store_missing_edge_id_count
        or ledger_malformed["count"]
        or store_malformed["count"]
        or ledger_signature["edge_hash"] != store_signature["edge_hash"]
    )

    return {
        "schema_version": GRAPH_RECONCILIATION_SCHEMA_VERSION,
        "status": "drift" if drifted else "reconciled",
        "trusted_for_evidence": not drifted,
        "repair_required": drifted,
        "ledger": ledger_signature,
        "graph_store": {
            "backend": backend,
            **store_signature,
        },
        "drift": {
            "missing_in_store_count": len(missing_in_store),
            "missing_in_store_sample": missing_in_store[:sample_limit],
            "extra_in_store_count": len(extra_in_store),
            "extra_in_store_sample": extra_in_store[:sample_limit],
            "mismatched_edge_count": len(mismatched),
            "mismatched_edge_sample": mismatched[:sample_limit],
            "duplicate_ledger_edge_id_count": len(duplicate_ledger_edge_ids),
            "duplicate_ledger_edge_id_sample": duplicate_ledger_edge_ids[:sample_limit],
            "duplicate_store_edge_id_count": len(duplicate_store_edge_ids),
            "duplicate_store_edge_id_sample": duplicate_store_edge_ids[:sample_limit],
            "ledger_missing_edge_id_count": ledger_missing_edge_id_count,
            "store_missing_edge_id_count": store_missing_edge_id_count,
            "ledger_malformed_edge_count": ledger_malformed["count"],
            "ledger_malformed_edge_sample": ledger_malformed["sample"],
            "store_malformed_edge_count": store_malformed["count"],
            "store_malformed_edge_sample": store_malformed["sample"],
        },
        "repair_guidance": _graph_repair_guidance(drifted),
    }


def _graph_reconciliation_error(*, backend: str, phase: str, error: Exception) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_RECONCILIATION_SCHEMA_VERSION,
        "status": "error",
        "trusted_for_evidence": False,
        "repair_required": True,
        "ledger": None,
        "graph_store": {
            "backend": backend,
            "edge_count": None,
            "edge_hash": None,
        },
        "drift": {
            "phase": phase,
            "error": str(error),
        },
        "repair_guidance": {
            "message": (
                "Graph evidence should be treated as unavailable until the ledger and graph "
                "store can be read and reconciled."
            ),
            "can_repair_automatically": False,
        },
    }


def _graph_store_repair_plan(
    ledger_edges: list[dict[str, Any]],
    store_edges: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    *,
    repair_mode: str,
    limit: int,
    sample_limit: int,
) -> dict[str, Any]:
    drift = reconciliation.get("drift") if isinstance(reconciliation, dict) else {}
    drift = drift if isinstance(drift, dict) else {}
    ledger_by_id = _edges_by_id(ledger_edges)
    store_by_id = _edges_by_id(store_edges)
    ledger_ids = set(ledger_by_id)
    store_ids = set(store_by_id)
    missing_ids = sorted(ledger_ids - store_ids)
    mismatched_ids = sorted(
        edge_id
        for edge_id in ledger_ids & store_ids
        if _edge_signature_payload(ledger_by_id[edge_id])
        != _edge_signature_payload(store_by_id[edge_id])
    )

    blocking_reasons = _graph_store_repair_blockers(drift, repair_mode=repair_mode)
    if blocking_reasons:
        return {
            "status": "blocked",
            "blocking_reasons": blocking_reasons,
            "error": {
                "code": "unsupported_drift_shape",
                "message": (
                    "Graph store repair is blocked for this drift shape. Use a reviewed "
                    "full rebuild only when ledger records are valid and store extras or "
                    "malformed store records must be discarded."
                ),
            },
        }

    if repair_mode == "upsert_missing":
        candidate_ids = sorted(set(missing_ids) | set(mismatched_ids))
        candidate_edges = [ledger_by_id[edge_id] for edge_id in candidate_ids]
    else:
        candidate_ids = [str(edge.get("edge_id") or "") for edge in ledger_edges if edge.get("edge_id")]
        candidate_edges = list(ledger_edges)

    if len(candidate_edges) > limit:
        return {
            "status": "blocked",
            "candidate_count": len(candidate_edges),
            "candidate_edge_id_sample": candidate_ids[:sample_limit],
            "blocking_reasons": ["repair_limit_exceeded"],
            "error": {
                "code": "repair_limit_exceeded",
                "message": (
                    f"Graph store repair would write {len(candidate_edges)} edges, "
                    f"which exceeds the requested limit of {limit}."
                ),
            },
        }

    return {
        "status": "planned",
        "candidate_count": len(candidate_edges),
        "candidate_edge_id_sample": candidate_ids[:sample_limit],
        "candidate_edges_for_write": candidate_edges,
        "blocking_reasons": [],
    }


def _graph_store_repair_blockers(drift: dict[str, Any], *, repair_mode: str) -> list[str]:
    blockers: list[str] = []
    ledger_blocker_fields = {
        "duplicate_ledger_edge_id_count": "duplicate_ledger_edge_ids",
        "ledger_missing_edge_id_count": "ledger_missing_edge_ids",
        "ledger_malformed_edge_count": "ledger_malformed_edges",
    }
    store_blocker_fields = {
        "extra_in_store_count": "extra_store_edges",
        "duplicate_store_edge_id_count": "duplicate_store_edge_ids",
        "store_missing_edge_id_count": "store_missing_edge_ids",
        "store_malformed_edge_count": "store_malformed_edges",
    }
    for field, reason in ledger_blocker_fields.items():
        if int(drift.get(field) or 0):
            blockers.append(reason)
    if repair_mode == "upsert_missing":
        for field, reason in store_blocker_fields.items():
            if int(drift.get(field) or 0):
                blockers.append(reason)
    return blockers


def _edge_signature_summary(edges: list[dict[str, Any]]) -> dict[str, Any]:
    projected = [_edge_signature_payload(edge) for edge in edges]
    projected.sort(key=lambda edge: str(edge.get("edge_id") or ""))
    return {
        "edge_count": len(edges),
        "edge_hash": hash_payload(projected),
    }


def _edge_signature_payload(edge: dict[str, Any]) -> dict[str, Any]:
    return {field: edge.get(field) for field in EDGE_SIGNATURE_FIELDS}


def _edges_by_id(edges: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        if edge_id and edge_id not in by_id:
            by_id[edge_id] = edge
    return by_id


def _duplicate_edge_ids(edges: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        if edge_id in seen:
            duplicates.add(edge_id)
        seen.add(edge_id)
    return sorted(duplicates)


def _malformed_edge_samples(edges: list[dict[str, Any]], *, sample_limit: int) -> dict[str, Any]:
    malformed: list[dict[str, Any]] = []
    for index, edge in enumerate(edges):
        missing = sorted(REQUIRED_EDGE_FIELDS - set(edge))
        if not missing:
            continue
        malformed.append(
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "index": index,
                "missing_fields": missing,
            }
        )
    return {"count": len(malformed), "sample": malformed[:sample_limit]}


def _graph_repair_guidance(drifted: bool) -> dict[str, Any]:
    if not drifted:
        return {
            "message": "Ledger graph records and graph store edge records are reconciled.",
            "can_repair_automatically": False,
        }
    return {
        "message": (
            "Treat graph evidence as degraded. Repair must replay exact ledger graph-edge "
            "records into the graph store or rebuild the graph store from ledger records "
            "after operator review; do not synthesize replacement graph evidence."
        ),
        "can_repair_automatically": False,
    }


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)

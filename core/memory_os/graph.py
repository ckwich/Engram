"""Memory OS graph service over the swappable GraphStore contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.graph_store import GraphStore, empty_graph
from core.kuzu_graph_store import KuzuGraphStore
from core.memory_os._records import upsert_record
from core.memory_os.ledger import MemoryOSLedger

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
        graph = self.graph_store.load_graph()
        graph.setdefault("edges", [])
        by_id = {
            str(edge.get("edge_id")): edge
            for edge in graph.get("edges", [])
            if isinstance(edge, dict) and edge.get("edge_id")
        }
        for edge in normalized:
            by_id[edge["edge_id"]] = edge
            if self.ledger is not None:
                upsert_record(self.ledger, "graph_edges", edge["edge_id"], edge)
        graph["edges"] = [by_id[edge_id] for edge_id in sorted(by_id)]
        self.graph_store.save_graph(graph)
        return {"imported_count": len(normalized), "edge_ids": [edge["edge_id"] for edge in normalized]}

    def load_edges(self) -> list[dict[str, Any]]:
        graph = self.graph_store.load_graph() or empty_graph()
        edges = graph.get("edges", [])
        return [dict(edge) for edge in edges if isinstance(edge, dict)]

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

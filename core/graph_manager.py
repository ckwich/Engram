from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from core.graph_store import EDGES_PATH, GRAPH_DIR, GRAPH_SCHEMA_VERSION, GraphStore, JsonGraphStore

GRAPH_EDGE_TYPES = {
    "related_to",
    "derived_from",
    "supersedes",
    "contradicts",
    "supports",
    "depends_on",
    "blocks",
    "implements",
    "mentions",
    "validates",
    "invalidates",
    "exemplifies",
    "warns_against",
}
GRAPH_EDGE_STATUSES = {"active", "archived"}
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


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _edge_id(payload: dict[str, Any]) -> str:
    base = {
        "from_ref": payload["from_ref"],
        "to_ref": payload["to_ref"],
        "edge_type": payload["edge_type"],
        "source": payload.get("source"),
    }
    digest = hashlib.sha256(_stable_json(base).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _refs_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _stable_json(left) == _stable_json(right)


class GraphManager:
    def __init__(self, store: GraphStore | None = None) -> None:
        self._store = store

    def reset_store(self, store: GraphStore | None = None) -> None:
        self._store = store

    def _get_store(self) -> GraphStore:
        if self._store is None:
            self._store = JsonGraphStore(edges_path=EDGES_PATH)
        return self._store

    def _load_graph(self) -> dict[str, Any]:
        return self._get_store().load_graph()

    def _save_graph(self, graph: dict[str, Any]) -> None:
        self._get_store().save_graph(graph)

    def _validate_ref(self, ref: dict[str, Any], label: str) -> None:
        if not isinstance(ref, dict):
            raise ValueError(f"{label} must be a dict")
        if not ref.get("kind"):
            raise ValueError(f"{label}.kind is required")
        if not ref.get("key"):
            raise ValueError(f"{label}.key is required")

    def _validate_status(self, status: str | None) -> None:
        if status is not None and status not in GRAPH_EDGE_STATUSES:
            raise ValueError(f"Unsupported status: {status}")

    def add_edge(
        self,
        *,
        from_ref: dict[str, Any],
        to_ref: dict[str, Any],
        edge_type: str,
        confidence: float = 1.0,
        evidence: str = "",
        source: str = "manual",
        created_by: str = "agent",
        status: str = "active",
    ) -> dict[str, Any]:
        if edge_type not in GRAPH_EDGE_TYPES:
            raise ValueError(f"Unsupported edge_type: {edge_type}")
        self._validate_ref(from_ref, "from_ref")
        self._validate_ref(to_ref, "to_ref")
        self._validate_status(status)
        if not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")

        timestamp = _now()
        edge = {
            "from_ref": from_ref,
            "to_ref": to_ref,
            "edge_type": edge_type,
            "confidence": float(confidence),
            "evidence": evidence,
            "source": source,
            "status": status,
            "created_by": created_by,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        edge["edge_id"] = _edge_id(edge)

        graph = self._load_graph()
        edges = graph.setdefault("edges", [])
        for index, existing in enumerate(edges):
            if existing.get("edge_id") == edge["edge_id"]:
                edge["created_at"] = existing.get("created_at", timestamp)
                edges[index] = edge
                self._save_graph(graph)
                return edge

        edges.append(edge)
        self._save_graph(graph)
        return edge

    def list_edges(
        self,
        *,
        ref: dict[str, Any] | None = None,
        edge_type: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        if edge_type is not None and edge_type not in GRAPH_EDGE_TYPES:
            raise ValueError(f"Unsupported edge_type: {edge_type}")
        self._validate_status(status)
        if ref is not None:
            self._validate_ref(ref, "ref")

        edges = []
        for edge in self._load_graph().get("edges", []):
            if status is not None and edge.get("status") != status:
                continue
            if edge_type is not None and edge.get("edge_type") != edge_type:
                continue
            if ref is not None and not (
                _refs_equal(edge.get("from_ref", {}), ref)
                or _refs_equal(edge.get("to_ref", {}), ref)
            ):
                continue
            edges.append(edge)

        return {"count": len(edges), "edges": edges, "error": None}

    def impact_scan(
        self,
        root_ref: dict[str, Any],
        *,
        max_hops: int = 1,
        edge_types: list[str] | None = None,
    ) -> dict[str, Any]:
        self._validate_ref(root_ref, "root_ref")
        allowed_types = set(edge_types or GRAPH_EDGE_TYPES)
        unknown_types = allowed_types - GRAPH_EDGE_TYPES
        if unknown_types:
            raise ValueError(f"Unsupported edge_type: {sorted(unknown_types)[0]}")

        all_edges = [
            edge for edge in self._load_graph().get("edges", [])
            if edge.get("status") == "active" and edge.get("edge_type") in allowed_types
        ]
        selected: list[dict[str, Any]] = []
        seen_edge_ids: set[str] = set()
        seen_refs: set[str] = {_stable_json(root_ref)}
        frontier = [root_ref]

        for _ in range(max(0, int(max_hops))):
            next_frontier: list[dict[str, Any]] = []
            for current_ref in frontier:
                for edge in all_edges:
                    from_ref = edge.get("from_ref", {})
                    to_ref = edge.get("to_ref", {})
                    if not _refs_equal(from_ref, current_ref):
                        continue
                    edge_id = edge.get("edge_id")
                    if edge_id not in seen_edge_ids:
                        selected.append(edge)
                        seen_edge_ids.add(edge_id)
                    to_key = _stable_json(to_ref)
                    if to_key not in seen_refs:
                        seen_refs.add(to_key)
                        next_frontier.append(to_ref)
            frontier = next_frontier

        return {
            "root_ref": root_ref,
            "max_hops": max_hops,
            "count": len(selected),
            "edges": selected,
            "error": None,
        }

    def audit_graph(self) -> dict[str, Any]:
        graph = self._load_graph()
        issues: list[dict[str, Any]] = []

        for index, edge in enumerate(graph.get("edges", [])):
            missing = sorted(REQUIRED_EDGE_FIELDS - set(edge.keys()))
            if missing:
                issues.append(
                    {
                        "code": "missing_required_field",
                        "edge_index": index,
                        "fields": missing,
                    }
                )
                continue
            if edge.get("edge_type") not in GRAPH_EDGE_TYPES:
                issues.append(
                    {
                        "code": "unsupported_edge_type",
                        "edge_index": index,
                        "edge_type": edge.get("edge_type"),
                    }
                )
            if edge.get("status") not in GRAPH_EDGE_STATUSES:
                issues.append(
                    {
                        "code": "unsupported_status",
                        "edge_index": index,
                        "status": edge.get("status"),
                    }
                )

        return {
            "schema_version": graph.get("schema_version"),
            "issue_count": len(issues),
            "issues": issues,
            "error": None,
        }


graph_manager = GraphManager()

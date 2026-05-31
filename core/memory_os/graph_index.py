"""Query-oriented graph index seam for bounded graph evidence."""
from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from core.graph_store import GraphStore, empty_graph

GraphDirection = Literal["outgoing", "incoming", "both"]

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

BODY_REF_FIELDS = {
    "body",
    "content",
    "markdown",
    "memory_body",
    "payload",
    "payload_json",
    "raw_text",
    "text",
}


class GraphIndex(Protocol):
    """Query-oriented graph contract for refs, edges, and evidence only."""

    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        ...

    def edges_for_ref(
        self,
        ref: dict[str, Any],
        *,
        direction: GraphDirection = "outgoing",
        edge_types: set[str] | list[str] | None = None,
        limit: int = 20,
        max_evidence_chars: int = 500,
    ) -> dict[str, Any]:
        ...

    def find_paths(
        self,
        from_ref: dict[str, Any],
        to_ref: dict[str, Any],
        *,
        max_hops: int = 2,
        edge_types: set[str] | list[str] | None = None,
        max_paths: int = 10,
        max_evidence_chars: int = 500,
    ) -> dict[str, Any]:
        ...


class LocalGraphIndex:
    """GraphIndex facade over the existing GraphStore document contract."""

    def __init__(self, graph_store: GraphStore) -> None:
        self.graph_store = graph_store

    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [_normalize_edge(edge) for edge in edges]
        edge_ids = [edge["edge_id"] for edge in normalized]
        incremental_upsert = getattr(self.graph_store, "upsert_edges", None)
        if callable(incremental_upsert):
            incremental_upsert(normalized)
        else:
            graph = self.graph_store.load_graph() or empty_graph()
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
        return {"upserted_count": len(normalized), "edge_ids": edge_ids}

    def edges_for_ref(
        self,
        ref: dict[str, Any],
        *,
        direction: GraphDirection = "outgoing",
        edge_types: set[str] | list[str] | None = None,
        limit: int = 20,
        max_evidence_chars: int = 500,
    ) -> dict[str, Any]:
        direction = _validate_direction(direction)
        limit = _validate_limit(limit, name="limit")
        query_ref = _bounded_ref(ref)
        allowed_types = set(edge_types or [])
        matches: list[dict[str, Any]] = []
        for edge in self._load_edges():
            if allowed_types and edge.get("edge_type") not in allowed_types:
                continue
            from_ref = _bounded_ref(edge.get("from_ref"))
            to_ref = _bounded_ref(edge.get("to_ref"))
            outgoing = direction in {"outgoing", "both"} and from_ref == query_ref
            incoming = direction in {"incoming", "both"} and to_ref == query_ref
            if outgoing or incoming:
                matches.append(edge)

        returned = matches[:limit]
        return {
            "ref": query_ref,
            "direction": direction,
            "count": len(returned),
            "total_count": len(matches),
            "truncated": len(matches) > len(returned),
            "edges": [
                _bounded_edge(edge, max_evidence_chars=max_evidence_chars)
                for edge in returned
            ],
            "entity_refs": _neighbor_refs(returned, query_ref=query_ref),
        }

    def impact_scan(
        self,
        root_ref: dict[str, Any],
        *,
        edge_types: set[str] | list[str] | None = None,
        limit: int = 20,
        max_evidence_chars: int = 500,
    ) -> dict[str, Any]:
        return self.edges_for_ref(
            root_ref,
            direction="outgoing",
            edge_types=edge_types,
            limit=limit,
            max_evidence_chars=max_evidence_chars,
        )

    def find_paths(
        self,
        from_ref: dict[str, Any],
        to_ref: dict[str, Any],
        *,
        max_hops: int = 2,
        edge_types: set[str] | list[str] | None = None,
        max_paths: int = 10,
        max_evidence_chars: int = 500,
    ) -> dict[str, Any]:
        max_hops = _validate_limit(max_hops, name="max_hops", minimum=1, maximum=8)
        max_paths = _validate_limit(max_paths, name="max_paths", minimum=1, maximum=50)
        allowed_types = set(edge_types or [])
        start_ref = _bounded_ref(from_ref)
        target_ref = _bounded_ref(to_ref)
        edges = [
            edge
            for edge in self._load_edges()
            if not allowed_types or edge.get("edge_type") in allowed_types
        ]

        paths: list[list[dict[str, Any]]] = []
        queue: list[tuple[dict[str, Any], list[dict[str, Any]], set[str]]] = [
            (start_ref, [], {_ref_key(start_ref)})
        ]
        while queue and len(paths) < max_paths:
            current_ref, path_edges, visited = queue.pop(0)
            if len(path_edges) >= max_hops:
                continue
            for edge in edges:
                if _bounded_ref(edge.get("from_ref")) != current_ref:
                    continue
                next_ref = _bounded_ref(edge.get("to_ref"))
                next_key = _ref_key(next_ref)
                next_path = [*path_edges, edge]
                if next_ref == target_ref:
                    paths.append(next_path)
                    if len(paths) >= max_paths:
                        break
                elif next_key not in visited:
                    queue.append((next_ref, next_path, {*visited, next_key}))

        return {
            "from_ref": start_ref,
            "to_ref": target_ref,
            "count": len(paths),
            "truncated": len(paths) == max_paths and bool(queue),
            "paths": [
                {
                    "edges": [
                        _bounded_edge(edge, max_evidence_chars=max_evidence_chars)
                        for edge in path
                    ],
                    "evidence_refs": _path_evidence_refs(path),
                }
                for path in paths
            ],
        }

    def _load_edges(self) -> list[dict[str, Any]]:
        graph = self.graph_store.load_graph() or empty_graph()
        return [dict(edge) for edge in graph.get("edges", []) if isinstance(edge, dict)]


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    missing = REQUIRED_EDGE_FIELDS - set(edge)
    if missing:
        raise ValueError(f"graph edge missing required field: {sorted(missing)[0]}")
    normalized = {
        "edge_id": str(edge["edge_id"]),
        "from_ref": _bounded_ref(edge["from_ref"]),
        "to_ref": _bounded_ref(edge["to_ref"]),
        "edge_type": str(edge["edge_type"]),
        "confidence": float(edge["confidence"]),
        "evidence": str(edge["evidence"]),
        "source": str(edge["source"]),
        "status": str(edge["status"]),
        "created_by": str(edge["created_by"]),
        "created_at": str(edge["created_at"]),
        "updated_at": str(edge["updated_at"]),
    }
    evidence_refs = _evidence_refs(edge)
    if evidence_refs:
        normalized["evidence_refs"] = evidence_refs
    return normalized


def _bounded_edge(edge: dict[str, Any], *, max_evidence_chars: int) -> dict[str, Any]:
    max_evidence_chars = _validate_limit(
        max_evidence_chars,
        name="max_evidence_chars",
        minimum=0,
        maximum=4000,
    )
    evidence = str(edge.get("evidence") or "")
    bounded_evidence = evidence[:max_evidence_chars]
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "from_ref": _bounded_ref(edge.get("from_ref")),
        "to_ref": _bounded_ref(edge.get("to_ref")),
        "edge_type": str(edge.get("edge_type") or ""),
        "confidence": float(edge.get("confidence") or 0.0),
        "evidence": bounded_evidence,
        "evidence_truncated": len(evidence) > len(bounded_evidence),
        "evidence_refs": _evidence_refs(edge),
        "source": str(edge.get("source") or ""),
        "status": str(edge.get("status") or ""),
    }


def _bounded_ref(ref: Any) -> dict[str, Any]:
    if not isinstance(ref, dict):
        return {"value": str(ref)}
    bounded: dict[str, Any] = {}
    for key in sorted(ref):
        key_text = str(key)
        if key_text in BODY_REF_FIELDS:
            continue
        value = ref[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            bounded[key_text] = value
        elif isinstance(value, dict):
            nested = _bounded_ref(value)
            if nested:
                bounded[key_text] = nested
        elif isinstance(value, list):
            bounded[key_text] = [
                item
                for item in value
                if isinstance(item, (str, int, float, bool)) or item is None
            ][:20]
    return bounded


def _evidence_refs(edge: dict[str, Any]) -> list[dict[str, Any]]:
    refs = edge.get("evidence_refs")
    if refs is None:
        refs = edge.get("citations")
    if refs is None and edge.get("citation") is not None:
        refs = [edge["citation"]]
    if refs is None:
        return []
    if isinstance(refs, dict):
        refs = [refs]
    if not isinstance(refs, list):
        return [{"value": str(refs)}]
    return [_bounded_ref(ref) for ref in refs[:20]]


def _path_evidence_refs(path: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in path:
        for ref in _evidence_refs(edge):
            key = _ref_key(ref)
            if key not in seen:
                refs.append(ref)
                seen.add(key)
    return refs


def _neighbor_refs(edges: list[dict[str, Any]], *, query_ref: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in edges:
        from_ref = _bounded_ref(edge.get("from_ref"))
        to_ref = _bounded_ref(edge.get("to_ref"))
        if from_ref == query_ref:
            neighbor = {
                "ref": to_ref,
                "via_edge_id": str(edge.get("edge_id") or ""),
                "direction": "outgoing",
            }
        elif to_ref == query_ref:
            neighbor = {
                "ref": from_ref,
                "via_edge_id": str(edge.get("edge_id") or ""),
                "direction": "incoming",
            }
        else:
            continue
        key = _ref_key(neighbor)
        if key not in seen:
            refs.append(neighbor)
            seen.add(key)
    return refs


def _validate_direction(direction: str) -> GraphDirection:
    if direction not in {"outgoing", "incoming", "both"}:
        raise ValueError("direction must be outgoing, incoming, or both")
    return direction  # type: ignore[return-value]


def _validate_limit(
    value: int,
    *,
    name: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    value = int(value)
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        return maximum
    return value


def _ref_key(ref: dict[str, Any]) -> str:
    return json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from core.graph_store import GRAPH_SCHEMA_VERSION, empty_graph


class KuzuGraphStore:
    """Optional Kuzu-backed graph store preserving the GraphStore document contract."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        database_factory: Callable[[str], Any] | None = None,
        connection_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.database_path = str(database_path)
        if database_factory is None or connection_factory is None:
            kuzu = _load_kuzu()
            database_factory = database_factory or kuzu.Database
            connection_factory = connection_factory or kuzu.Connection
        self._db = database_factory(self.database_path)
        self._conn = connection_factory(self._db)
        self._schema_ready = False

    def load_graph(self) -> dict[str, Any]:
        self._ensure_schema()
        rows = self._execute(
            """
            MATCH (from:GraphRef)-[edge:GraphEdge]->(to:GraphRef)
            RETURN edge.edge_id, edge.from_ref_json, edge.to_ref_json,
                   edge.edge_type, edge.confidence, edge.evidence, edge.source,
                   edge.status, edge.created_by, edge.created_at, edge.updated_at
            ORDER BY edge.edge_id
            """
        )
        graph = empty_graph()
        graph["edges"] = [_edge_from_row(row) for row in rows]
        return graph

    def save_graph(self, graph: dict[str, Any]) -> None:
        self._ensure_schema()
        edges = list(graph.get("edges", [])) if isinstance(graph, dict) else []
        self._execute("MATCH (n:GraphRef) DETACH DELETE n")

        refs: dict[str, dict[str, Any]] = {}
        for edge in edges:
            for ref in (edge.get("from_ref"), edge.get("to_ref")):
                if isinstance(ref, dict):
                    refs[_ref_id(ref)] = ref

        for ref_id, ref in sorted(refs.items()):
            self._execute(
                """
                CREATE (ref:GraphRef {id: $id, payload_json: $payload_json})
                """,
                {"id": ref_id, "payload_json": _stable_json(ref)},
            )

        for edge in edges:
            self._write_edge(edge)

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        self._execute(
            """
            CREATE NODE TABLE IF NOT EXISTS GraphRef (
                id STRING PRIMARY KEY,
                payload_json STRING
            )
            """
        )
        self._execute(
            """
            CREATE REL TABLE IF NOT EXISTS GraphEdge (
                FROM GraphRef TO GraphRef,
                edge_id STRING,
                edge_type STRING,
                confidence DOUBLE,
                evidence STRING,
                source STRING,
                status STRING,
                created_by STRING,
                created_at STRING,
                updated_at STRING,
                from_ref_json STRING,
                to_ref_json STRING
            )
            """
        )
        self._schema_ready = True

    def _write_edge(self, edge: dict[str, Any]) -> None:
        from_ref = edge.get("from_ref")
        to_ref = edge.get("to_ref")
        if not isinstance(from_ref, dict) or not isinstance(to_ref, dict):
            return
        params = {
            "from_id": _ref_id(from_ref),
            "to_id": _ref_id(to_ref),
            "edge_id": str(edge.get("edge_id") or ""),
            "edge_type": str(edge.get("edge_type") or ""),
            "confidence": float(edge.get("confidence") or 0.0),
            "evidence": str(edge.get("evidence") or ""),
            "source": str(edge.get("source") or ""),
            "status": str(edge.get("status") or ""),
            "created_by": str(edge.get("created_by") or ""),
            "created_at": str(edge.get("created_at") or ""),
            "updated_at": str(edge.get("updated_at") or ""),
            "from_ref_json": _stable_json(from_ref),
            "to_ref_json": _stable_json(to_ref),
        }
        self._execute(
            """
            MATCH (from:GraphRef {id: $from_id}), (to:GraphRef {id: $to_id})
            CREATE (from)-[:GraphEdge {
                edge_id: $edge_id,
                edge_type: $edge_type,
                confidence: $confidence,
                evidence: $evidence,
                source: $source,
                status: $status,
                created_by: $created_by,
                created_at: $created_at,
                updated_at: $updated_at,
                from_ref_json: $from_ref_json,
                to_ref_json: $to_ref_json
            }]->(to)
            """,
            params,
        )

    def _execute(self, query: str, parameters: dict[str, Any] | None = None):
        if parameters is None:
            return self._conn.execute(query)
        return self._conn.execute(query, parameters=parameters)


def _load_kuzu():
    try:
        import kuzu
    except ImportError as error:
        raise RuntimeError(
            "Kuzu is not installed. Install the optional 'kuzu' dependency "
            "before using KuzuGraphStore."
        ) from error
    return kuzu


def _edge_from_row(row: Any) -> dict[str, Any]:
    return {
        "edge_id": _row_value(row, 0, "edge_id"),
        "from_ref": _json_object(_row_value(row, 1, "from_ref_json")),
        "to_ref": _json_object(_row_value(row, 2, "to_ref_json")),
        "edge_type": _row_value(row, 3, "edge_type"),
        "confidence": float(_row_value(row, 4, "confidence") or 0.0),
        "evidence": _row_value(row, 5, "evidence"),
        "source": _row_value(row, 6, "source"),
        "status": _row_value(row, 7, "status"),
        "created_by": _row_value(row, 8, "created_by"),
        "created_at": _row_value(row, 9, "created_at"),
        "updated_at": _row_value(row, 10, "updated_at"),
    }


def _row_value(row: Any, index: int, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    decoded = json.loads(str(raw))
    return decoded if isinstance(decoded, dict) else {}


def _ref_id(ref: dict[str, Any]) -> str:
    digest = hashlib.sha256(_stable_json(ref).encode("utf-8")).hexdigest()
    return f"ref:{digest}"


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

from __future__ import annotations

import builtins

import pytest

from core.graph_manager import GRAPH_SCHEMA_VERSION, GraphManager
from core.kuzu_graph_store import KuzuGraphStore


class FakeKuzuConnection:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.edge_rows: list[tuple] = []

    def execute(self, query: str, parameters: dict | None = None):
        self.calls.append({"query": query, "parameters": parameters or {}})
        if "RETURN edge.edge_id" in query:
            return list(self.edge_rows)
        if "CREATE (from)-[:GraphEdge" in query:
            params = parameters or {}
            self.edge_rows.append(
                (
                    params["edge_id"],
                    params["from_ref_json"],
                    params["to_ref_json"],
                    params["edge_type"],
                    params["confidence"],
                    params["evidence"],
                    params["source"],
                    params["status"],
                    params["created_by"],
                    params["created_at"],
                    params["updated_at"],
                )
            )
        if "DETACH DELETE" in query:
            self.edge_rows = []
        return []


def test_kuzu_graph_store_round_trips_graph_document_with_parameterized_writes(tmp_path):
    connection = FakeKuzuConnection()
    store = KuzuGraphStore(
        tmp_path / "graph.kuzu",
        database_factory=lambda path: {"path": path},
        connection_factory=lambda db: connection,
    )
    graph = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "edges": [
            {
                "edge_id": "sha256:edge",
                "from_ref": {"kind": "memory", "key": "alpha"},
                "to_ref": {"kind": "memory", "key": "beta"},
                "edge_type": "supports",
                "confidence": 0.75,
                "evidence": "Alpha supports beta.",
                "source": "test",
                "status": "active",
                "created_by": "pytest",
                "created_at": "2026-05-11T00:00:00-07:00",
                "updated_at": "2026-05-11T00:00:00-07:00",
            }
        ],
    }

    store.save_graph(graph)
    restored = store.load_graph()

    assert restored == graph
    assert any("CREATE NODE TABLE IF NOT EXISTS GraphRef" in call["query"] for call in connection.calls)
    assert any("CREATE REL TABLE IF NOT EXISTS GraphEdge" in call["query"] for call in connection.calls)
    edge_write = next(call for call in connection.calls if "CREATE (from)-[:GraphEdge" in call["query"])
    assert edge_write["parameters"]["edge_id"] == "sha256:edge"
    assert "$edge_id" in edge_write["query"]


def test_kuzu_graph_store_preserves_graph_manager_contract(tmp_path):
    connection = FakeKuzuConnection()
    store = KuzuGraphStore(
        tmp_path / "graph.kuzu",
        database_factory=lambda path: {"path": path},
        connection_factory=lambda db: connection,
    )
    manager = GraphManager(store=store)

    edge = manager.add_edge(
        from_ref={"kind": "memory", "key": "alpha"},
        to_ref={"kind": "memory", "key": "beta"},
        edge_type="depends_on",
        evidence="Alpha depends on beta.",
    )

    payload = manager.list_edges(ref={"kind": "memory", "key": "alpha"})

    assert payload["count"] == 1
    assert payload["edges"][0]["edge_id"] == edge["edge_id"]
    assert "content" not in payload["edges"][0]


def test_kuzu_graph_store_missing_dependency_error_is_actionable(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "kuzu":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(RuntimeError, match="Install the optional 'kuzu' dependency"):
        KuzuGraphStore(tmp_path / "graph.kuzu")

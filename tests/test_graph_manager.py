from __future__ import annotations

import json

from core.graph_manager import GRAPH_SCHEMA_VERSION, GraphManager
from core.graph_store import JsonGraphStore


class RecordingGraphStore:
    def __init__(self):
        self.graph = {"schema_version": GRAPH_SCHEMA_VERSION, "edges": []}
        self.saved_graphs = []

    def load_graph(self):
        return self.graph

    def save_graph(self, graph):
        self.saved_graphs.append(json.loads(json.dumps(graph)))
        self.graph = graph


def test_graph_manager_uses_injected_store_for_future_backends():
    store = RecordingGraphStore()
    gm = GraphManager(store=store)

    edge = gm.add_edge(
        from_ref={"kind": "memory", "key": "alpha"},
        to_ref={"kind": "memory", "key": "beta"},
        edge_type="supports",
        evidence="Alpha supports beta.",
    )

    assert store.saved_graphs
    assert store.saved_graphs[-1]["edges"][0]["edge_id"] == edge["edge_id"]
    assert gm.list_edges(ref={"kind": "memory", "key": "alpha"})["count"] == 1


def test_json_graph_store_round_trips_existing_edge_document(tmp_path):
    edges_path = tmp_path / "edges.json"
    edge = {
        "edge_id": "sha256:existing",
        "from_ref": {"kind": "memory", "key": "alpha"},
        "to_ref": {"kind": "memory", "key": "beta"},
        "edge_type": "supports",
        "confidence": 0.9,
        "evidence": "Existing relationship.",
        "source": "import",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-04-29T00:00:00-07:00",
        "updated_at": "2026-04-29T00:00:00-07:00",
    }
    edges_path.write_text(
        json.dumps({"schema_version": GRAPH_SCHEMA_VERSION, "edges": [edge]}),
        encoding="utf-8",
    )

    store = JsonGraphStore(edges_path=edges_path)
    graph = store.load_graph()

    store.save_graph(graph)
    saved = json.loads(edges_path.read_text(encoding="utf-8"))
    assert saved["edges"] == [edge]


def test_add_edge_persists_json_first(isolated_graph_storage):
    gm = isolated_graph_storage.graph_manager

    edge = gm.add_edge(
        from_ref={"kind": "memory", "key": "alpha"},
        to_ref={"kind": "memory", "key": "beta"},
        edge_type="supports",
        confidence=0.75,
        evidence="Alpha supports beta.",
        source="test",
        created_by="pytest",
    )

    assert edge["edge_type"] == "supports"
    assert edge["edge_id"].startswith("sha256:")
    assert isolated_graph_storage.EDGES_PATH.exists()
    saved = json.loads(isolated_graph_storage.EDGES_PATH.read_text(encoding="utf-8"))
    assert saved["edges"][0]["edge_id"] == edge["edge_id"]


def test_add_edge_rejects_unknown_edge_type(isolated_graph_storage):
    gm = isolated_graph_storage.graph_manager

    try:
        gm.add_edge(
            from_ref={"kind": "memory", "key": "alpha"},
            to_ref={"kind": "memory", "key": "beta"},
            edge_type="mystery",
        )
    except ValueError as exc:
        assert "Unsupported edge_type" in str(exc)
    else:
        raise AssertionError("unknown edge type should fail")


def test_add_edge_rejects_unknown_status(isolated_graph_storage):
    gm = isolated_graph_storage.graph_manager

    try:
        gm.add_edge(
            from_ref={"kind": "memory", "key": "alpha"},
            to_ref={"kind": "memory", "key": "beta"},
            edge_type="supports",
            status="acitve",
        )
    except ValueError as exc:
        assert "Unsupported status" in str(exc)
    else:
        raise AssertionError("unknown edge status should fail")


def test_impact_scan_returns_ids_without_memory_bodies(isolated_graph_storage):
    gm = isolated_graph_storage.graph_manager
    gm.add_edge(
        from_ref={"kind": "memory", "key": "alpha"},
        to_ref={"kind": "memory", "key": "beta"},
        edge_type="depends_on",
        evidence="Alpha depends on beta.",
    )

    payload = gm.impact_scan({"kind": "memory", "key": "alpha"}, max_hops=1)

    assert payload["root_ref"] == {"kind": "memory", "key": "alpha"}
    assert payload["count"] == 1
    assert payload["edges"][0]["to_ref"] == {"kind": "memory", "key": "beta"}
    assert "content" not in payload["edges"][0]


def test_audit_graph_reports_missing_required_fields(isolated_graph_storage):
    isolated_graph_storage.EDGES_PATH.write_text(
        '{"schema_version":"2026-04-27","edges":[{"edge_type":"supports"}]}',
        encoding="utf-8",
    )
    isolated_graph_storage.graph_manager.reset_store()

    payload = isolated_graph_storage.graph_manager.audit_graph()

    assert payload["issue_count"] == 1
    assert payload["issues"][0]["code"] == "missing_required_field"


def test_audit_graph_reports_unknown_status(isolated_graph_storage):
    gm = isolated_graph_storage.graph_manager
    edge = gm.add_edge(
        from_ref={"kind": "memory", "key": "alpha"},
        to_ref={"kind": "memory", "key": "beta"},
        edge_type="supports",
    )
    edge["status"] = "acitve"
    isolated_graph_storage.EDGES_PATH.write_text(
        json.dumps({"schema_version": "2026-04-27", "edges": [edge]}),
        encoding="utf-8",
    )
    gm.reset_store()

    payload = gm.audit_graph()

    assert payload["issue_count"] == 1
    assert payload["issues"][0]["code"] == "unsupported_status"

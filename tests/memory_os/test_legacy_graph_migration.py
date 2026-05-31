import json

from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _write_legacy(path, name, payload):
    (path / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _runtime(tmp_path):
    root = tmp_path / "memory_os"
    root.mkdir()
    runtime = MemoryOSRuntime(
        root,
        embed_text=lambda text: [1.0],
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def _edges_by_source(runtime, source):
    return [
        edge
        for edge in list_records(runtime.ledger, "graph_edges")
        if edge.get("source") == source
    ]


def test_legacy_related_to_graph_migration_preserves_policy_and_evidence(tmp_path):
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    _write_legacy(
        legacy_dir,
        "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha active memory.",
            "project": "Engram",
            "status": "active",
            "related_to": ["beta", "missing_target"],
        },
    )
    _write_legacy(
        legacy_dir,
        "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta active memory.",
            "project": "Engram",
            "status": "active",
        },
    )
    _write_legacy(
        legacy_dir,
        "draft.json",
        {
            "key": "draft_alpha",
            "title": "Draft Alpha",
            "content": "Draft memory.",
            "project": "Engram",
            "status": "draft",
            "related_to": ["alpha"],
        },
    )
    _write_legacy(
        legacy_dir,
        "historical.json",
        {
            "key": "historical_alpha",
            "title": "Historical Alpha",
            "content": "Historical memory.",
            "project": "Engram",
            "status": "historical",
            "related_to": ["alpha"],
        },
    )
    runtime = _runtime(tmp_path)
    runtime.apply_legacy_memory_os_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="agent-review",
    )

    prepared = runtime.prepare_legacy_related_to_graph_migration(legacy_dir=legacy_dir)
    prepared_edges = _edges_by_source(runtime, "legacy_related_to")
    denied = runtime.apply_legacy_related_to_graph_migration(
        legacy_dir=legacy_dir,
        accept=False,
        approved_by="agent-review",
    )
    applied = runtime.apply_legacy_related_to_graph_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="agent-review",
    )
    first_edges = _edges_by_source(runtime, "legacy_related_to")
    alpha_impact = runtime.graph.impact_scan({"kind": "memory", "key": "alpha"})
    alpha_legacy_impact_edges = [
        edge for edge in alpha_impact["edges"] if edge.get("source") == "legacy_related_to"
    ]
    replayed = runtime.apply_legacy_related_to_graph_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="agent-review",
    )

    assert prepared["operation"] == "prepare_legacy_related_to_graph_migration"
    assert prepared["status"] == "prepared"
    assert prepared["write_performed"] is False
    assert prepared["active_memory_write_performed"] is False
    assert prepared["graph_write_performed"] is False
    assert prepared["candidate_edge_count"] == 4
    assert prepared["graphable_edge_count"] == 2
    assert prepared["skipped_edge_count"] == 2
    assert prepared["skipped_by_status"] == {"draft": 1, "historical": 1}
    assert prepared["missing_ref_count"] == 1
    assert prepared["missing_refs"] == [{"from_key": "alpha", "to_key": "missing_target"}]
    assert prepared_edges == []
    assert denied["status"] == "policy_denied"
    assert denied["write_performed"] is False
    assert applied["status"] == "ok"
    assert applied["write_performed"] is True
    assert applied["active_memory_write_performed"] is False
    assert applied["graph_write_performed"] is True
    assert applied["candidate_edge_count"] == 4
    assert applied["graph_edges_written"] == applied["edge_ids"]
    assert len(applied["graph_edges_written"]) == 2
    assert len(first_edges) == 2
    assert {edge["source"] for edge in first_edges} == {"legacy_related_to"}
    assert {edge["status"] for edge in first_edges} == {"active"}
    assert {edge["from_ref"]["key"] for edge in first_edges} == {"alpha"}
    assert {edge["to_ref"]["key"] for edge in first_edges} == {"beta", "missing_target"}
    assert all(edge["confidence"] == 1.0 for edge in first_edges)
    assert all(edge["created_by"] == "legacy_related_to_migration" for edge in first_edges)
    assert len(alpha_legacy_impact_edges) == 2
    assert all("content" not in edge and "text" not in edge for edge in alpha_legacy_impact_edges)
    assert replayed["status"] == "ok"
    assert replayed["write_performed"] is False
    assert replayed["graph_write_performed"] is False
    assert replayed["idempotent_replay"] is True
    assert _edges_by_source(runtime, "legacy_related_to")[0]["updated_at"] == first_edges[0]["updated_at"]

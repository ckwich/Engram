from core.graph_store import JsonGraphStore
from core.memory_os.graph import MemoryOSGraph
from core.memory_os.ledger import MemoryOSLedger


def _edge(edge_id, from_ref, to_ref, edge_type, evidence):
    return {
        "edge_id": edge_id,
        "from_ref": from_ref,
        "to_ref": to_ref,
        "edge_type": edge_type,
        "confidence": 0.86,
        "evidence": evidence,
        "source": "book_import",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-13T00:00:00-07:00",
        "updated_at": "2026-05-13T00:00:00-07:00",
    }


def test_graph_import_preserves_edge_ids_and_returns_evidence_paths(tmp_path):
    graph = MemoryOSGraph(
        MemoryOSLedger(tmp_path / "engram.sqlite"),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    edges = [
        _edge(
            "sha256:book-a",
            {"kind": "book", "key": "book_a"},
            {"kind": "concept", "key": "visual_hierarchy"},
            "defines",
            "Book A defines visual hierarchy.",
        ),
        _edge(
            "sha256:book-b",
            {"kind": "concept", "key": "visual_hierarchy"},
            {"kind": "book", "key": "book_b"},
            "applies_to",
            "Book B applies visual hierarchy.",
        ),
    ]

    report = graph.import_edges(edges)
    paths = graph.find_paths(
        {"kind": "book", "key": "book_a"},
        {"kind": "book", "key": "book_b"},
        max_hops=2,
    )

    assert report["imported_count"] == 2
    assert [edge["edge_id"] for edge in graph.load_edges()] == ["sha256:book-a", "sha256:book-b"]
    assert paths["count"] == 1
    assert [edge["edge_id"] for edge in paths["paths"][0]["edges"]] == [
        "sha256:book-a",
        "sha256:book-b",
    ]
    assert all("content" not in edge for edge in paths["paths"][0]["edges"])
    assert "Book A defines visual hierarchy." in paths["paths"][0]["evidence"][0]


def test_graph_conflict_paths_query_contradictions_and_supersessions(tmp_path):
    graph = MemoryOSGraph(
        MemoryOSLedger(tmp_path / "engram.sqlite"),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    graph.import_edges(
        [
            _edge(
                "sha256:contradicts",
                {"kind": "claim", "key": "new_claim"},
                {"kind": "claim", "key": "old_claim"},
                "contradicts",
                "New evidence contradicts old claim.",
            ),
            _edge(
                "sha256:supersedes",
                {"kind": "decision", "key": "new_decision"},
                {"kind": "decision", "key": "old_decision"},
                "supersedes",
                "New decision supersedes old decision.",
            ),
        ]
    )

    conflicts = graph.conflict_paths({"kind": "claim", "key": "new_claim"})
    impact = graph.impact_scan({"kind": "decision", "key": "new_decision"})

    assert conflicts["count"] == 1
    assert conflicts["paths"][0]["edges"][0]["edge_type"] == "contradicts"
    assert impact["count"] == 1
    assert impact["edges"][0]["edge_type"] == "supersedes"
    assert "content" not in impact["edges"][0]

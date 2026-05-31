from core.graph_store import JsonGraphStore
from core.memory_os.graph_index import LocalGraphIndex


def _edge(edge_id, from_ref, to_ref, edge_type, evidence, evidence_refs=None):
    edge = {
        "edge_id": edge_id,
        "from_ref": from_ref,
        "to_ref": to_ref,
        "edge_type": edge_type,
        "confidence": 0.91,
        "evidence": evidence,
        "source": "test",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-21T00:00:00-07:00",
        "updated_at": "2026-05-21T00:00:00-07:00",
    }
    if evidence_refs is not None:
        edge["evidence_refs"] = evidence_refs
    return edge


def test_graph_index_returns_bounded_refs_and_evidence_without_bodies(tmp_path):
    index = LocalGraphIndex(JsonGraphStore(tmp_path / "edges.json"))
    index.upsert_edges(
        [
            _edge(
                "edge:1",
                {"kind": "memory", "key": "alpha", "content": "do not return"},
                {"kind": "concept", "key": "runtime_seams", "text": "do not return"},
                "supports",
                "Runtime seams support hosted wiring without changing local runtime.",
                evidence_refs=[
                    {
                        "kind": "chunk",
                        "key": "alpha",
                        "chunk_id": 0,
                        "content": "do not return",
                    }
                ],
            ),
            _edge(
                "edge:2",
                {"kind": "memory", "key": "alpha"},
                {"kind": "concept", "key": "graph_index"},
                "mentions",
                "A second edge proves result limiting.",
            ),
        ]
    )

    result = index.edges_for_ref(
        {"kind": "memory", "key": "alpha"},
        direction="outgoing",
        limit=1,
        max_evidence_chars=24,
    )

    assert result["count"] == 1
    assert result["total_count"] == 2
    assert result["truncated"] is True
    edge = result["edges"][0]
    assert edge["edge_id"] == "edge:1"
    assert len(edge["evidence"]) == 24
    assert edge["evidence_truncated"] is True
    assert "content" not in edge["from_ref"]
    assert "text" not in edge["to_ref"]
    assert "content" not in edge["evidence_refs"][0]
    assert result["entity_refs"] == [
        {
            "ref": {"key": "runtime_seams", "kind": "concept"},
            "via_edge_id": "edge:1",
            "direction": "outgoing",
        }
    ]


def test_graph_index_find_paths_returns_bounded_evidence_refs(tmp_path):
    index = LocalGraphIndex(JsonGraphStore(tmp_path / "edges.json"))
    index.upsert_edges(
        [
            _edge(
                "edge:a",
                {"kind": "memory", "key": "a", "body": "do not return"},
                {"kind": "concept", "key": "seam", "payload_json": "{}"},
                "supports",
                "A supports the seam.",
                evidence_refs=[{"kind": "chunk", "key": "a", "chunk_id": 0}],
            ),
            _edge(
                "edge:b",
                {"kind": "concept", "key": "seam"},
                {"kind": "memory", "key": "b", "content": "do not return"},
                "applies_to",
                "The seam applies to B.",
                evidence_refs=[{"kind": "chunk", "key": "b", "chunk_id": 1}],
            ),
        ]
    )

    result = index.find_paths(
        {"kind": "memory", "key": "a"},
        {"kind": "memory", "key": "b"},
        max_hops=2,
    )

    assert result["count"] == 1
    path = result["paths"][0]
    assert [edge["edge_id"] for edge in path["edges"]] == ["edge:a", "edge:b"]
    assert path["evidence_refs"] == [
        {"chunk_id": 0, "key": "a", "kind": "chunk"},
        {"chunk_id": 1, "key": "b", "kind": "chunk"},
    ]
    assert "body" not in path["edges"][0]["from_ref"]
    assert "payload_json" not in path["edges"][0]["to_ref"]
    assert "content" not in path["edges"][1]["to_ref"]


def test_graph_index_rejects_edges_missing_contract_fields(tmp_path):
    index = LocalGraphIndex(JsonGraphStore(tmp_path / "edges.json"))

    try:
        index.upsert_edges([{"edge_id": "bad"}])
    except ValueError as error:
        assert "graph edge missing required field" in str(error)
    else:
        raise AssertionError("expected graph edge validation to fail")

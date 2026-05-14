from core.memory_os._records import upsert_record
from core.memory_os.knowledge_graph import build_graph_evidence
from core.memory_os.ledger import MemoryOSLedger


def _edge(edge_id, from_key, to_key, edge_type, evidence):
    return {
        "edge_id": edge_id,
        "from_ref": {"kind": "claim", "key": from_key},
        "to_ref": {"kind": "claim", "key": to_key},
        "edge_type": edge_type,
        "confidence": 0.86,
        "evidence": evidence,
        "source": "memory_os_test",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-14T00:00:00+00:00",
        "updated_at": "2026-05-14T00:00:00+00:00",
        "project": "Engram",
        "content": "This body must not be exposed by graph evidence.",
    }


def test_build_graph_evidence_limits_paths_and_cites_edges(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(ledger, "graph_edges", "edge:one", _edge("edge:one", "a", "b", "supports", "A supports B."))
    upsert_record(ledger, "graph_edges", "edge:two", _edge("edge:two", "b", "c", "supports", "B supports C."))
    upsert_record(ledger, "graph_edges", "edge:three", _edge("edge:three", "c", "d", "supports", "C supports D."))

    packet = build_graph_evidence(
        ledger,
        project="Engram",
        focus=["supports"],
        max_records=2,
    )

    assert packet["status"] == "ok"
    assert packet["answer"]["packet_type"] == "graph_evidence"
    assert packet["answer"]["edge_count"] == 2
    assert packet["answer"]["path_limit"] == 2
    assert [path["path_id"] for path in packet["answer"]["evidence_paths"]] == ["path_001", "path_002"]
    assert "content" not in packet["answer"]["evidence_paths"][0]["edges"][0]
    assert packet["citations"] == [
        {
            "citation_id": "cit_001",
            "level": "graph",
            "source": "memory_os",
            "edge_id": "edge:one",
            "path_id": "path_001",
        },
        {
            "citation_id": "cit_002",
            "level": "graph",
            "source": "memory_os",
            "edge_id": "edge:two",
            "path_id": "path_002",
        },
    ]


def test_build_graph_evidence_surfaces_contradictions_as_partial(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "graph_edges",
        "edge:contradicts",
        _edge("edge:contradicts", "new_claim", "old_claim", "contradicts", "New evidence contradicts old."),
    )

    packet = build_graph_evidence(
        ledger,
        project="Engram",
        focus=["claim"],
        max_records=5,
    )

    assert packet["status"] == "partial"
    assert packet["answer"]["contradiction_count"] == 1
    assert packet["answer"]["contradictions"][0]["edge_id"] == "edge:contradicts"
    assert packet["errors"] == [
        {
            "code": "contradictions_present",
            "message": "Graph evidence includes contradiction or supersession edges.",
        }
    ]


def test_build_graph_evidence_surfaces_draft_graph_proposals_without_neighbor_bodies(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "drafts",
        "draft:doc",
        {
            "draft_id": "draft:doc",
            "project": "Engram",
            "document_id": "doc_design",
            "candidate_graph_edges": [
                {
                    "proposal_id": "proposal:one",
                    "from_ref": {"kind": "document", "key": "doc_design"},
                    "to_ref": {"kind": "claim", "key": "motion_priority"},
                    "edge_type": "contradicts",
                    "confidence": 0.72,
                    "evidence": "Draft says the book contradicts a stale claim.",
                    "source": "document_intelligence.auto_graph",
                    "status": "draft",
                    "content": "This draft body must not be exposed.",
                }
            ],
        },
    )

    packet = build_graph_evidence(
        ledger,
        project="Engram",
        focus=["motion"],
        max_records=5,
    )

    edge = packet["answer"]["evidence_paths"][0]["edges"][0]
    assert packet["status"] == "partial"
    assert packet["answer"]["draft_proposal_count"] == 1
    assert edge["edge_id"] == "proposal:one"
    assert edge["status"] == "draft"
    assert "content" not in edge
    assert packet["answer"]["contradiction_count"] == 1


def test_build_graph_evidence_returns_no_answer_without_matching_edges(tmp_path):
    packet = build_graph_evidence(
        MemoryOSLedger(tmp_path / "ledger.sqlite3"),
        project="Engram",
        focus=["missing"],
        max_records=5,
    )

    assert packet["status"] == "no_answer"
    assert packet["answer"] is None
    assert packet["citations"] == []

from __future__ import annotations

from core.graph_backend_eval import build_graph_backend_parity_report
from core.graph_manager import normalize_graph_edge_proposal


def _edge(edge_type: str = "related_to") -> dict:
    return {
        "edge_id": f"sha256:{edge_type}",
        "from_ref": {"kind": "concept", "key": "affordance", "document_id": "book-a"},
        "to_ref": {"kind": "concept", "key": "perceived_affordance", "document_id": "book-b"},
        "edge_type": edge_type,
        "confidence": 0.8,
        "evidence": "Both books discuss design cues for action.",
        "source": "document_understanding",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-13T00:00:00-07:00",
        "updated_at": "2026-05-13T00:00:00-07:00",
    }


def test_graph_backend_parity_reports_cross_book_edge_types():
    report = build_graph_backend_parity_report([_edge()])

    assert report["status"] == "pass"
    assert report["edge_count"] == 1
    assert report["cross_document_edge_count"] == 1
    assert "related_to" in report["supported_cross_book_edge_types"]
    assert report["daemon_single_owner_required"] is True
    assert report["write_performed"] is False


def test_graph_backend_parity_blocks_missing_evidence_for_book_edges():
    broken = _edge()
    broken["evidence"] = ""

    report = build_graph_backend_parity_report([broken])

    assert report["status"] == "fail"
    assert report["issues"][0]["code"] == "missing_required_field"
    assert report["issues"][0]["field"] == "evidence"


def test_graph_edge_proposals_accept_cross_book_concept_relationships():
    proposal = normalize_graph_edge_proposal(
        {
            "from_ref": {"kind": "concept", "key": "visual_hierarchy", "document_id": "book-a"},
            "to_ref": {"kind": "concept", "key": "attention_guidance", "document_id": "book-b"},
            "edge_type": "similar_to",
            "confidence": 0.7,
            "evidence": "Both sections describe directing attention through layout.",
        }
    )

    assert proposal["edge_type"] == "similar_to"
    assert proposal["from_ref"]["document_id"] == "book-a"
    assert proposal["to_ref"]["document_id"] == "book-b"

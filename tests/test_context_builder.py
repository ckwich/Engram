from __future__ import annotations

from core.context_builder import build_context_receipt, merge_graph_candidates


def test_build_context_receipt_reports_budget_and_candidates():
    receipt = build_context_receipt(
        query="agent memory",
        filters={"project": "C:/Dev/Engram"},
        semantic_candidate_count=5,
        graph_candidate_count=2,
        selected_chunk_count=3,
        omitted_count=1,
        budget_chars=6000,
        used_chars=4200,
        include_stale=False,
        graph_enabled=True,
        max_hops=1,
        retrieval_mode="hybrid",
        citation_count=3,
    )

    assert receipt["query"] == "agent memory"
    assert receipt["semantic_candidate_count"] == 5
    assert receipt["graph_candidate_count"] == 2
    assert receipt["stale_policy"] == "excluded"
    assert receipt["used_chars"] == 4200
    assert receipt["retrieval_mode"] == "hybrid"
    assert receipt["citation_count"] == 3


def test_merge_graph_candidates_dedupes_existing_refs():
    semantic_refs = [{"key": "alpha", "chunk_id": 0}]
    graph_edges = [
        {"to_ref": {"kind": "memory", "key": "alpha"}},
        {"to_ref": {"kind": "memory", "key": "beta"}},
    ]

    merged = merge_graph_candidates(
        semantic_refs=semantic_refs,
        graph_edges=graph_edges,
        max_graph_candidates=5,
    )

    assert merged == [{"key": "beta", "reason": "graph_neighbor"}]

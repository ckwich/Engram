"""No-write retrieval backend comparison gates.

The live backend remains Chroma until a candidate index proves parity. This
module compares already-built VectorIndex adapters; it does not instantiate or
mutate ChromaDB, LanceDB, or live Engram storage.
"""
from __future__ import annotations

from typing import Any

from core.vector_index import VectorIndex, VectorIndexQuery


COMPARISON_SCHEMA_VERSION = "2026-05-13.retrieval_backend_comparison.v1"


def compare_vector_indexes(
    *,
    baseline_index: VectorIndex,
    candidate_index: VectorIndex,
    queries: list[dict[str, Any]],
    min_overlap: int = 1,
) -> dict[str, Any]:
    """Compare candidate retrieval results against a baseline index."""
    if min_overlap < 0:
        raise ValueError("min_overlap must be non-negative")
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries must include at least one golden query")

    results = [
        _compare_one_query(
            baseline_index=baseline_index,
            candidate_index=candidate_index,
            query_spec=query_spec,
            min_overlap=min_overlap,
        )
        for query_spec in queries
    ]
    failed = [result for result in results if result["status"] != "pass"]
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "operation": "compare_vector_indexes",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_retrieval_changed": False,
        "status": "pass" if not failed else "fail",
        "query_count": len(results),
        "failed_count": len(failed),
        "min_overlap": min_overlap,
        "results": results,
        "error": None,
    }


def skipped_retrieval_comparison(reason: str) -> dict[str, Any]:
    """Return the stable skipped shape used by readiness reports."""
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "operation": "compare_vector_indexes",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_retrieval_changed": False,
        "status": "skipped",
        "query_count": 0,
        "failed_count": 0,
        "min_overlap": None,
        "results": [],
        "error": None,
        "reason": reason,
    }


def _compare_one_query(
    *,
    baseline_index: VectorIndex,
    candidate_index: VectorIndex,
    query_spec: dict[str, Any],
    min_overlap: int,
) -> dict[str, Any]:
    query = _query_from_spec(query_spec)
    baseline_results = baseline_index.search(query)
    candidate_results = candidate_index.search(query)
    baseline_ids = [result.document_id for result in baseline_results]
    candidate_ids = [result.document_id for result in candidate_results]
    expected_ids = [str(item) for item in query_spec.get("expected_document_ids", [])]
    missing_expected = [
        document_id for document_id in expected_ids if document_id not in candidate_ids
    ]
    overlap = sorted(set(baseline_ids) & set(candidate_ids))
    candidate_expected_hit = not missing_expected
    overlap_pass = len(overlap) >= min_overlap if baseline_ids else True
    status = "pass" if candidate_expected_hit and overlap_pass else "fail"
    return {
        "query_id": str(query_spec.get("query_id") or query.query_text),
        "query_text": query.query_text,
        "status": status,
        "limit": query.limit,
        "retrieval_mode": query.retrieval_mode,
        "baseline_top_document_ids": baseline_ids,
        "candidate_top_document_ids": candidate_ids,
        "expected_document_ids": expected_ids,
        "missing_expected_document_ids": missing_expected,
        "candidate_expected_hit": candidate_expected_hit,
        "top_k_overlap_document_ids": overlap,
        "top_k_overlap_count": len(overlap),
        "min_overlap_pass": overlap_pass,
    }


def _query_from_spec(query_spec: dict[str, Any]) -> VectorIndexQuery:
    if not isinstance(query_spec, dict):
        raise ValueError("golden query must be an object")
    query_text = str(query_spec.get("query_text") or "").strip()
    if not query_text:
        raise ValueError("golden query query_text is required")
    query_embedding = query_spec.get("query_embedding")
    if not isinstance(query_embedding, list) or not query_embedding:
        raise ValueError("golden query query_embedding is required")
    return VectorIndexQuery(
        query_text=query_text,
        query_embedding=[float(value) for value in query_embedding],
        limit=int(query_spec.get("limit") or 5),
        filters=dict(query_spec.get("filters") or {}),
        retrieval_mode=str(query_spec.get("retrieval_mode") or "semantic"),
    )

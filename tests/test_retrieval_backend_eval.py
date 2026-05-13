from __future__ import annotations

from core.retrieval_backend_eval import compare_vector_indexes
from core.vector_index import InMemoryVectorIndex, VectorIndexDocument


def _index(documents: list[VectorIndexDocument]) -> InMemoryVectorIndex:
    index = InMemoryVectorIndex()
    index.rebuild(documents)
    return index


def test_compare_vector_indexes_passes_when_candidate_matches_expected_results():
    documents = [
        VectorIndexDocument("alpha-0", "alpha", 0, "Alpha design memory", [1.0]),
        VectorIndexDocument("beta-0", "beta", 0, "Beta layout memory", [0.1]),
    ]

    report = compare_vector_indexes(
        baseline_index=_index(documents),
        candidate_index=_index(documents),
        queries=[
            {
                "query_id": "alpha",
                "query_text": "alpha design",
                "query_embedding": [1.0],
                "limit": 2,
                "expected_document_ids": ["alpha-0"],
            }
        ],
    )

    assert report["status"] == "pass"
    assert report["query_count"] == 1
    assert report["results"][0]["candidate_expected_hit"] is True
    assert report["results"][0]["top_k_overlap_count"] == 2


def test_compare_vector_indexes_fails_when_candidate_misses_expected_result():
    baseline_documents = [
        VectorIndexDocument("alpha-0", "alpha", 0, "Alpha design memory", [1.0]),
        VectorIndexDocument("beta-0", "beta", 0, "Beta layout memory", [0.1]),
    ]
    candidate_documents = [
        VectorIndexDocument("alpha-0", "alpha", 0, "Alpha design memory", [1.0]),
    ]

    report = compare_vector_indexes(
        baseline_index=_index(baseline_documents),
        candidate_index=_index(candidate_documents),
        queries=[
            {
                "query_id": "beta",
                "query_text": "beta layout",
                "query_embedding": [0.1],
                "limit": 2,
                "expected_document_ids": ["beta-0"],
            }
        ],
    )

    assert report["status"] == "fail"
    assert report["results"][0]["candidate_expected_hit"] is False
    assert report["results"][0]["missing_expected_document_ids"] == ["beta-0"]

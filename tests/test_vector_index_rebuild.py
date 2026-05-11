from __future__ import annotations

import pytest

from core.vector_index import InMemoryVectorIndex, VectorIndexQuery
from core.vector_index_rebuild import rebuild_vector_index_from_sources


def _source(document_id: str, parent_key: str, chunk_id: int, text: str) -> dict:
    return {
        "document_id": document_id,
        "parent_key": parent_key,
        "chunk_id": chunk_id,
        "text": text,
        "metadata": {"project": "Engram", "parent_key": parent_key},
        "citation": {
            "source": "memory_os_migration",
            "key": parent_key,
            "chunk_id": chunk_id,
            "document_id": document_id,
        },
    }


def test_rebuild_vector_index_from_sources_batches_embeddings_and_returns_receipt():
    index = InMemoryVectorIndex()
    sources = [
        _source("alpha-0", "alpha", 0, "Alpha migration notes"),
        _source("beta-0", "beta", 0, "Beta design notes"),
        _source("gamma-0", "gamma", 0, "Gamma graph notes"),
    ]
    batches: list[list[str]] = []

    def embed_texts(texts: list[str]) -> list[list[float]]:
        batches.append(list(texts))
        return [[float(len(text)), 1.0] for text in texts]

    receipt = rebuild_vector_index_from_sources(index, sources, embed_texts, batch_size=2)

    assert batches == [
        ["Alpha migration notes", "Beta design notes"],
        ["Gamma graph notes"],
    ]
    assert receipt == {
        "schema_version": "2026-05-11.vector_index_rebuild.v1",
        "status": "pass",
        "source_count": 3,
        "embedded_count": 3,
        "document_count": 3,
        "batch_count": 2,
        "embedding_dimension": 2,
        "document_ids": ["alpha-0", "beta-0", "gamma-0"],
        "index_stats": {"document_count": 3},
    }

    results = index.search(VectorIndexQuery("alpha", [float(len("Alpha migration notes")), 1.0], limit=1))
    assert results[0].document_id == "alpha-0"
    assert results[0].citation == sources[0]["citation"]


def test_rebuild_vector_index_rejects_embedding_count_mismatches_before_rebuild():
    index = InMemoryVectorIndex()
    sources = [
        _source("alpha-0", "alpha", 0, "Alpha migration notes"),
        _source("beta-0", "beta", 0, "Beta design notes"),
    ]

    with pytest.raises(ValueError, match="returned 1 embeddings for 2 texts"):
        rebuild_vector_index_from_sources(
            index,
            sources,
            lambda texts: [[1.0, 0.0]],
            batch_size=2,
        )

    assert index.stats() == {"document_count": 0}


def test_rebuild_vector_index_rejects_inconsistent_embedding_dimensions():
    index = InMemoryVectorIndex()
    sources = [
        _source("alpha-0", "alpha", 0, "Alpha migration notes"),
        _source("beta-0", "beta", 0, "Beta design notes"),
    ]

    with pytest.raises(ValueError, match="embedding dimensions must be consistent"):
        rebuild_vector_index_from_sources(
            index,
            sources,
            lambda texts: [[1.0, 0.0], [1.0]],
            batch_size=2,
        )

    assert index.stats() == {"document_count": 0}

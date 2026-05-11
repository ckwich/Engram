"""Auditable vector-index rebuild helpers for the Engram Memory OS rebuild.

This module consumes already-prepared vector source records and a caller-owned
embedding function. It does not choose an embedding provider or replace live
retrieval behavior.
"""
from __future__ import annotations

from collections.abc import Callable

from core.memory_os_migration import build_vector_index_documents
from core.vector_index import VectorIndex


REBUILD_SCHEMA_VERSION = "2026-05-11.vector_index_rebuild.v1"


EmbeddingBatchFn = Callable[[list[str]], list[list[float]]]


def rebuild_vector_index_from_sources(
    index: VectorIndex,
    source_records: list[dict],
    embed_texts: EmbeddingBatchFn,
    *,
    batch_size: int = 128,
) -> dict:
    """Embed source record text in batches, rebuild an index, and return a receipt."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    embeddings_by_document_id: dict[str, list[float]] = {}
    batch_count = 0
    embedding_dimension: int | None = None

    for batch in _batched(source_records, batch_size):
        texts = [str(source["text"]) for source in batch]
        embeddings = embed_texts(texts)
        if len(embeddings) != len(texts):
            raise ValueError(
                f"embedding provider returned {len(embeddings)} embeddings for {len(texts)} texts"
            )

        batch_count += 1
        for source, embedding in zip(batch, embeddings):
            vector = [float(value) for value in embedding]
            if not vector:
                raise ValueError("embedding provider returned an empty embedding")
            if embedding_dimension is None:
                embedding_dimension = len(vector)
            elif len(vector) != embedding_dimension:
                raise ValueError("embedding dimensions must be consistent")
            embeddings_by_document_id[str(source["document_id"])] = vector

    documents = build_vector_index_documents(source_records, embeddings_by_document_id)
    index.rebuild(documents)

    return {
        "schema_version": REBUILD_SCHEMA_VERSION,
        "status": "pass",
        "source_count": len(source_records),
        "embedded_count": len(embeddings_by_document_id),
        "document_count": len(documents),
        "batch_count": batch_count,
        "embedding_dimension": embedding_dimension or 0,
        "document_ids": [document.document_id for document in documents],
        "index_stats": index.stats(),
    }


def _batched(items: list[dict], batch_size: int) -> list[list[dict]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]

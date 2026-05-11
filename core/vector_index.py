"""Vector index contracts for the Engram Memory OS rebuild.

The rebuilt retrieval layer will need swappable adapters. This module defines
the contract and a deterministic in-memory implementation for conformance tests;
it does not replace ChromaDB or change live retrieval behavior.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class VectorIndexDocument:
    """One indexed retrieval unit."""

    document_id: str
    parent_key: str
    chunk_id: int
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    citation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorIndexQuery:
    """A vector query plus exact metadata filters."""

    query_text: str
    query_embedding: list[float]
    limit: int = 5
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorIndexSearchResult:
    """A cited chunk result returned by a VectorIndex adapter."""

    document_id: str
    parent_key: str
    chunk_id: int
    text: str
    score: float
    metadata: dict[str, Any]
    citation: dict[str, Any]


@runtime_checkable
class VectorIndex(Protocol):
    """Swappable vector index adapter contract."""

    def rebuild(self, documents: list[VectorIndexDocument]) -> None:
        """Replace all indexed documents with the provided set."""

    def upsert_many(self, documents: list[VectorIndexDocument]) -> None:
        """Add or replace documents by document_id."""

    def search(self, query: VectorIndexQuery) -> list[VectorIndexSearchResult]:
        """Return ranked, cited chunks matching the query and filters."""

    def delete_by_parent_key(self, parent_key: str) -> int:
        """Delete all chunks for a parent memory/source key and return the count."""

    def stats(self) -> dict[str, int]:
        """Return compact adapter stats for health and rebuild receipts."""


class InMemoryVectorIndex:
    """Deterministic VectorIndex implementation for tests and adapter parity."""

    def __init__(self) -> None:
        self._documents: dict[str, VectorIndexDocument] = {}

    def rebuild(self, documents: list[VectorIndexDocument]) -> None:
        self._documents = {}
        self.upsert_many(documents)

    def upsert_many(self, documents: list[VectorIndexDocument]) -> None:
        for document in documents:
            self._validate_document(document)
            self._documents[document.document_id] = document

    def search(self, query: VectorIndexQuery) -> list[VectorIndexSearchResult]:
        self._validate_query(query)
        results: list[VectorIndexSearchResult] = []
        for document in self._documents.values():
            if not self._matches_filters(document.metadata, query.filters):
                continue
            score = _cosine_similarity(query.query_embedding, document.embedding)
            citation = document.citation or {
                "source": "vector_index",
                "key": document.parent_key,
                "chunk_id": document.chunk_id,
            }
            results.append(
                VectorIndexSearchResult(
                    document_id=document.document_id,
                    parent_key=document.parent_key,
                    chunk_id=document.chunk_id,
                    text=document.text,
                    score=score,
                    metadata=dict(document.metadata),
                    citation=dict(citation),
                )
            )

        results.sort(key=lambda result: (-result.score, result.document_id))
        return results[: query.limit]

    def delete_by_parent_key(self, parent_key: str) -> int:
        to_delete = [
            document_id
            for document_id, document in self._documents.items()
            if document.parent_key == parent_key
        ]
        for document_id in to_delete:
            del self._documents[document_id]
        return len(to_delete)

    def stats(self) -> dict[str, int]:
        return {"document_count": len(self._documents)}

    @staticmethod
    def _validate_document(document: VectorIndexDocument) -> None:
        if not document.document_id:
            raise ValueError("document_id is required")
        if not document.parent_key:
            raise ValueError("parent_key is required")
        if not isinstance(document.chunk_id, int):
            raise ValueError("chunk_id must be an integer")
        if not document.embedding:
            raise ValueError("embedding is required")

    @staticmethod
    def _validate_query(query: VectorIndexQuery) -> None:
        if query.limit < 1:
            raise ValueError("limit must be positive")
        if not query.query_embedding:
            raise ValueError("query_embedding is required")

    @staticmethod
    def _matches_filters(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, expected in filters.items():
            actual = metadata.get(key)
            if isinstance(expected, (list, tuple, set)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions must match")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)

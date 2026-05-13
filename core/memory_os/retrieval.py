"""Memory OS retrieval service over migrated ledger chunks."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Callable

from core.lancedb_vector_index import LanceDBVectorIndex
from core.memory_os._records import hash_payload, list_records
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os_migration import MemoryOSMigrationKernel, build_vector_index_documents
from core.vector_index import VectorIndex, VectorIndexQuery, VectorIndexSearchResult


class MemoryOSRetrievalIndex:
    """Rebuild and query a vector index from Memory OS ledger chunk records."""

    def __init__(
        self,
        ledger: MemoryOSLedger,
        index_uri: str | Path,
        *,
        embed_text: Callable[[str], list[float]],
        vector_index: VectorIndex | None = None,
    ) -> None:
        self.ledger = ledger
        self.index_uri = Path(index_uri)
        self.embed_text = embed_text
        self.vector_index = vector_index or LanceDBVectorIndex(self.index_uri)

    def rebuild_from_ledger(self) -> dict[str, Any]:
        sources = self._read_vector_sources()
        embeddings = {
            str(source["document_id"]): self.embed_text(str(source["text"]))
            for source in sources
        }
        documents = build_vector_index_documents(sources, embeddings)
        self.vector_index.rebuild(documents)
        return {
            "backend": type(self.vector_index).__name__,
            "source_count": len(sources),
            "indexed_count": len(documents),
            "source_manifest_hash": hash_payload(
                [
                    {
                        "document_id": source["document_id"],
                        "parent_key": source["parent_key"],
                        "chunk_id": source["chunk_id"],
                        "text_hash": source.get("metadata", {}).get("text_hash"),
                    }
                    for source in sources
                ]
            ),
            "stats": self.vector_index.stats(),
        }

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        return self._search(query, filters=filters, limit=limit, retrieval_mode="semantic")

    def hybrid_search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        return self._search(query, filters=filters, limit=limit, retrieval_mode="hybrid")

    def _search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None,
        limit: int,
        retrieval_mode: str,
    ) -> dict[str, Any]:
        results = self.vector_index.search(
            VectorIndexQuery(
                query_text=query,
                query_embedding=self.embed_text(query),
                limit=limit,
                filters=filters or {},
                retrieval_mode=retrieval_mode,
            )
        )
        return {
            "query": query,
            "retrieval_mode": retrieval_mode,
            "count": len(results),
            "results": [self._result_payload(result) for result in results],
        }

    def _read_vector_sources(self) -> list[dict[str, Any]]:
        kernel = MemoryOSMigrationKernel(self.ledger.path.parent)
        try:
            return kernel.read_vector_source_records()
        except sqlite3.DatabaseError:
            return [_generic_chunk_source(record) for record in list_records(self.ledger, "chunks")]

    @staticmethod
    def _result_payload(result: VectorIndexSearchResult) -> dict[str, Any]:
        return {
            "document_id": result.document_id,
            "key": result.parent_key,
            "chunk_id": result.chunk_id,
            "text": result.text,
            "score": result.score,
            "metadata": result.metadata,
            "citation": result.citation
            or {
                "source": "memory_os_retrieval",
                "key": result.parent_key,
                "chunk_id": result.chunk_id,
                "document_id": result.document_id,
            },
        }


def _generic_chunk_source(record: dict[str, Any]) -> dict[str, Any]:
    key = str(record.get("memory_key") or record.get("key") or record.get("parent_key") or "")
    chunk_id = int(record.get("chunk_id", 0))
    document_id = str(record.get("document_id") or f"{key}:chunk:{chunk_id}")
    text = str(record.get("text") or "")
    metadata = dict(record.get("metadata") or {})
    for field in (
        "title",
        "tags",
        "project",
        "domain",
        "status",
        "canonical",
        "section_title",
        "heading_path",
        "chunk_kind",
    ):
        if field in record and field not in metadata:
            metadata[field] = record[field]
    metadata.setdefault("text_hash", hash_payload(text))
    return {
        "document_id": document_id,
        "parent_key": key,
        "chunk_id": chunk_id,
        "text": text,
        "metadata": metadata,
        "citation": {
            "source": "memory_os",
            "key": key,
            "chunk_id": chunk_id,
            "document_id": document_id,
        },
    }

"""Optional LanceDB adapter for the VectorIndex contract.

This adapter is a Phase 2 spike. It is not wired into live retrieval yet and
does not make LanceDB a required dependency.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core.vector_index import (
    VectorIndexDocument,
    VectorIndexQuery,
    VectorIndexSearchResult,
)


class LanceDBVectorIndex:
    """VectorIndex adapter backed by an optional local LanceDB table."""

    def __init__(
        self,
        uri: str | Path,
        table_name: str = "chunks",
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self.uri = str(uri)
        self.table_name = table_name
        self._connect = connect or _load_lancedb_connect()
        self._db = self._connect(self.uri)
        self._table = None

    def rebuild(self, documents: list[VectorIndexDocument]) -> None:
        rows = [self._row_from_document(document) for document in documents]
        if not rows:
            self._table = None
            return
        self._table = self._db.create_table(self.table_name, data=rows, mode="overwrite")

    def upsert_many(self, documents: list[VectorIndexDocument]) -> None:
        if not documents:
            return
        rows = [self._row_from_document(document) for document in documents]
        if self._table is None:
            self._table = self._db.create_table(self.table_name, data=rows, mode="overwrite")
            return
        self._delete_document_ids([document.document_id for document in documents])
        self._table.add(rows)

    def search(self, query: VectorIndexQuery) -> list[VectorIndexSearchResult]:
        if query.limit < 1:
            raise ValueError("limit must be positive")
        if not query.query_embedding:
            raise ValueError("query_embedding is required")
        if self._table is None:
            return []

        search_limit = max(query.limit, query.limit * 4)
        rows = self._table.search(query.query_embedding).limit(search_limit).to_list()
        results: list[VectorIndexSearchResult] = []
        for row in rows:
            metadata = _loads_json_object(row.get("metadata_json"))
            if not _matches_filters(metadata, query.filters):
                continue
            citation = _loads_json_object(row.get("citation_json")) or {
                "source": "lancedb",
                "key": row["parent_key"],
                "chunk_id": row["chunk_id"],
            }
            distance = float(row.get("_distance", 0.0))
            results.append(
                VectorIndexSearchResult(
                    document_id=row["document_id"],
                    parent_key=row["parent_key"],
                    chunk_id=int(row["chunk_id"]),
                    text=row["text"],
                    score=1.0 / (1.0 + max(distance, 0.0)),
                    metadata=metadata,
                    citation=citation,
                )
            )
            if len(results) >= query.limit:
                break
        return results

    def delete_by_parent_key(self, parent_key: str) -> int:
        if self._table is None:
            return 0
        before = self._table.count_rows()
        self._table.delete(f"parent_key = '{_escape_sql_literal(parent_key)}'")
        after = self._table.count_rows()
        return max(before - after, 0)

    def stats(self) -> dict[str, int]:
        if self._table is None:
            return {"document_count": 0}
        return {"document_count": int(self._table.count_rows())}

    def _delete_document_ids(self, document_ids: list[str]) -> None:
        if self._table is None or not document_ids:
            return
        values = ", ".join(f"'{_escape_sql_literal(document_id)}'" for document_id in document_ids)
        self._table.delete(f"document_id IN ({values})")

    @staticmethod
    def _row_from_document(document: VectorIndexDocument) -> dict[str, Any]:
        return {
            "document_id": document.document_id,
            "parent_key": document.parent_key,
            "chunk_id": document.chunk_id,
            "text": document.text,
            "vector": document.embedding,
            "metadata_json": json.dumps(document.metadata, ensure_ascii=False, sort_keys=True),
            "citation_json": json.dumps(document.citation, ensure_ascii=False, sort_keys=True),
            "project": document.metadata.get("project"),
            "domain": document.metadata.get("domain"),
            "status": document.metadata.get("status"),
            "canonical": document.metadata.get("canonical"),
        }


def _load_lancedb_connect():
    try:
        import lancedb
    except ImportError as error:
        raise RuntimeError(
            "LanceDB is not installed. Install the optional 'lancedb' dependency "
            "before using LanceDBVectorIndex."
        ) from error
    return lancedb.connect


def _loads_json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {}


def _matches_filters(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        actual = metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _escape_sql_literal(value: str) -> str:
    return str(value).replace("'", "''")

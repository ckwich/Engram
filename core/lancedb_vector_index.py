"""Optional LanceDB adapter for the VectorIndex contract.

This adapter is a Phase 2 spike. It is not wired into live retrieval yet and
does not make LanceDB a required dependency.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core.hybrid_retrieval import lexical_relevance_score, normalize_retrieval_mode
from core.vector_index import (
    VectorIndexDocument,
    VectorIndexQuery,
    VectorIndexSearchResult,
    rank_vector_result_score,
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
        self._ensure_table_loaded()
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
        self._ensure_table_loaded()
        if self._table is None:
            return []

        retrieval_mode = normalize_retrieval_mode(query.retrieval_mode)
        search_limit = max(query.limit, query.limit * 4)
        rows = _vector_candidate_rows(self._table, query, initial_limit=search_limit)
        if retrieval_mode == "hybrid":
            rows = _merge_rows_by_document_id(
                rows,
                _lexical_candidate_rows(self._table, query, limit=search_limit),
            )
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
            distance = _row_distance(row, query.query_embedding)
            semantic_score = 1.0 / (1.0 + max(distance, 0.0))
            score = rank_vector_result_score(
                query,
                _candidate_texts(row, metadata),
                semantic_score,
            )
            results.append(
                VectorIndexSearchResult(
                    document_id=row["document_id"],
                    parent_key=row["parent_key"],
                    chunk_id=int(row["chunk_id"]),
                    text=row["text"],
                    score=score,
                    metadata=metadata,
                    citation=citation,
                )
            )
        results.sort(key=lambda result: (-result.score, result.document_id))
        return results[: query.limit]

    def delete_by_parent_key(self, parent_key: str) -> int:
        self._ensure_table_loaded()
        if self._table is None:
            return 0
        before = self._table.count_rows()
        self._table.delete(f"parent_key = '{_escape_sql_literal(parent_key)}'")
        after = self._table.count_rows()
        return max(before - after, 0)

    def stats(self) -> dict[str, int]:
        self._ensure_table_loaded()
        if self._table is None:
            return {"document_count": 0}
        return {"document_count": int(self._table.count_rows())}

    def _delete_document_ids(self, document_ids: list[str]) -> None:
        self._ensure_table_loaded()
        if self._table is None or not document_ids:
            return
        values = ", ".join(f"'{_escape_sql_literal(document_id)}'" for document_id in document_ids)
        self._table.delete(f"document_id IN ({values})")

    def _ensure_table_loaded(self) -> None:
        if self._table is not None:
            return

        open_table = getattr(self._db, "open_table", None)
        if callable(open_table):
            table_names = self._list_table_names()
            if table_names is not None and self.table_name not in table_names:
                return
            try:
                self._table = open_table(self.table_name)
                return
            except Exception:
                pass

        try:
            self._table = self._db[self.table_name]
        except (KeyError, TypeError, AttributeError):
            self._table = None

    def _list_table_names(self) -> set[str] | None:
        for method_name in ("list_tables", "table_names"):
            table_names = getattr(self._db, method_name, None)
            if not callable(table_names):
                continue
            try:
                names = _normalize_table_names(table_names())
                if names is not None:
                    return names
            except Exception:
                continue
        return None

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


def _normalize_table_names(value: Any) -> set[str] | None:
    tables = getattr(value, "tables", None)
    if tables is None and isinstance(value, dict):
        tables = value.get("tables")
    if tables is None:
        tables = value
    try:
        return {str(name) for name in tables}
    except TypeError:
        return None


def _matches_filters(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        actual = metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _candidate_texts(row: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    return [
        str(row.get("text") or ""),
        str(row.get("parent_key") or ""),
        *[str(value) for value in metadata.values()],
    ]


_FILTER_COLUMNS = {"project", "domain", "status", "canonical"}


def _vector_candidate_rows(
    table: Any,
    query: VectorIndexQuery,
    *,
    initial_limit: int,
) -> list[dict[str, Any]]:
    """Fetch enough vector candidates to satisfy exact filters when possible."""
    total_rows = _table_count(table)
    if total_rows == 0:
        return []
    current_limit = max(query.limit, initial_limit)
    if total_rows is not None:
        current_limit = min(current_limit, total_rows)
    filter_predicate = _filter_where_predicate(query.filters)

    if filter_predicate:
        rows, pushdown_applied = _adaptive_vector_candidate_rows(
            table,
            query,
            initial_limit=current_limit,
            total_rows=total_rows,
            filter_predicate=filter_predicate,
        )
        if not pushdown_applied or _matching_filter_count(rows, query.filters) >= query.limit:
            return rows

    rows, _ = _adaptive_vector_candidate_rows(
        table,
        query,
        initial_limit=current_limit,
        total_rows=total_rows,
        filter_predicate=None,
    )
    return rows


def _adaptive_vector_candidate_rows(
    table: Any,
    query: VectorIndexQuery,
    *,
    initial_limit: int,
    total_rows: int | None,
    filter_predicate: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    current_limit = initial_limit
    rows: list[dict[str, Any]] = []
    pushdown_applied = False
    while True:
        rows, current_pushdown_applied = _search_rows(
            table,
            query.query_embedding,
            current_limit,
            filter_predicate,
        )
        pushdown_applied = pushdown_applied or current_pushdown_applied
        if _matching_filter_count(rows, query.filters) >= query.limit:
            return rows, pushdown_applied
        if not rows:
            return rows, pushdown_applied
        if len(rows) < current_limit:
            return rows, pushdown_applied
        if total_rows is not None and current_limit >= total_rows:
            return rows, pushdown_applied

        next_limit = current_limit * 2
        if total_rows is not None:
            next_limit = min(next_limit, total_rows)
        if next_limit <= current_limit:
            return rows, pushdown_applied
        current_limit = next_limit


def _search_rows(
    table: Any,
    query_embedding: list[float],
    limit: int,
    filter_predicate: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    search = table.search(query_embedding)
    pushdown_applied = False
    if filter_predicate:
        search, pushdown_applied = _apply_where_filter(search, filter_predicate)
    try:
        return [dict(row) for row in search.limit(limit).to_list()], pushdown_applied
    except Exception:
        if pushdown_applied:
            return [], True
        raise


def _apply_where_filter(search: Any, filter_predicate: str) -> tuple[Any, bool]:
    where = getattr(search, "where", None)
    if not callable(where):
        return search, False
    try:
        return where(filter_predicate, prefilter=True), True
    except TypeError:
        try:
            return where(filter_predicate), True
        except Exception:
            return search, False
    except Exception:
        return search, False


def _matching_filter_count(rows: list[dict[str, Any]], filters: dict[str, Any]) -> int:
    matched = 0
    for row in rows:
        metadata = _loads_json_object(row.get("metadata_json"))
        if _matches_filters(metadata, filters):
            matched += 1
    return matched


def _table_count(table: Any) -> int | None:
    count_rows = getattr(table, "count_rows", None)
    if callable(count_rows):
        try:
            return int(count_rows())
        except Exception:
            return None
    return None


def _filter_where_predicate(filters: dict[str, Any]) -> str | None:
    clauses: list[str] = []
    for key, expected in filters.items():
        if key not in _FILTER_COLUMNS:
            continue
        clause = _filter_where_clause(key, expected)
        if clause:
            clauses.append(clause)
    if not clauses:
        return None
    return " AND ".join(clauses)


def _filter_where_clause(key: str, expected: Any) -> str | None:
    if isinstance(expected, (list, tuple, set)):
        values = sorted(expected, key=lambda value: str(value))
        if not values:
            return None
        non_null_values = [value for value in values if value is not None]
        clauses: list[str] = []
        if any(value is None for value in values):
            clauses.append(f"{key} IS NULL")
        if non_null_values:
            sql_values = ", ".join(_sql_value(value) for value in non_null_values)
            clauses.append(f"{key} IN ({sql_values})")
        return " OR ".join(f"({clause})" for clause in clauses)
    if expected is None:
        return f"{key} IS NULL"
    return f"{key} = {_sql_value(expected)}"


def _sql_value(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return f"'{_escape_sql_literal(str(value))}'"


def _lexical_candidate_rows(table: Any, query: VectorIndexQuery, *, limit: int) -> list[dict[str, Any]]:
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for row in _table_rows(table):
        metadata = _loads_json_object(row.get("metadata_json"))
        if not _matches_filters(metadata, query.filters):
            continue
        lexical_score = lexical_relevance_score(query.query_text, _candidate_texts(row, metadata))
        if lexical_score <= 0:
            continue
        candidates.append((lexical_score, str(row.get("document_id") or ""), row))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in candidates[:limit]]


def _table_rows(table: Any) -> list[dict[str, Any]]:
    to_list = getattr(table, "to_list", None)
    if callable(to_list):
        try:
            rows = to_list()
            return [dict(row) for row in rows]
        except Exception:
            pass
    to_pandas = getattr(table, "to_pandas", None)
    if callable(to_pandas):
        try:
            return [dict(row) for row in to_pandas().to_dict("records")]
        except Exception:
            pass
    to_arrow = getattr(table, "to_arrow", None)
    if callable(to_arrow):
        try:
            return [dict(row) for row in to_arrow().to_pylist()]
        except Exception:
            pass
    return []


def _merge_rows_by_document_id(
    primary_rows: list[dict[str, Any]],
    additional_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*primary_rows, *additional_rows]:
        document_id = str(row.get("document_id") or "")
        if not document_id:
            continue
        merged.setdefault(document_id, row)
    return list(merged.values())


def _row_distance(row: dict[str, Any], query_embedding: list[float]) -> float:
    if "_distance" in row:
        return float(row.get("_distance", 0.0))
    vector = row.get("vector")
    if not isinstance(vector, (list, tuple)) or len(vector) != len(query_embedding):
        return 1_000_000.0
    return sum((float(left) - float(right)) ** 2 for left, right in zip(vector, query_embedding))


def _escape_sql_literal(value: str) -> str:
    return str(value).replace("'", "''")

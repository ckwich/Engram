from __future__ import annotations

import builtins

import pytest

from core.lancedb_vector_index import LanceDBVectorIndex
from core.vector_index import VectorIndexDocument, VectorIndexQuery


class FakeLanceSearch:
    def __init__(self, rows: list[dict], query_embedding: list[float]) -> None:
        self.rows = rows
        self.query_embedding = query_embedding
        self.limit_value = len(rows)

    def limit(self, value: int):
        self.limit_value = value
        return self

    def to_list(self) -> list[dict]:
        rows = []
        for row in self.rows:
            distance = abs(row["vector"][0] - self.query_embedding[0])
            rows.append({**row, "_distance": distance})
        rows.sort(key=lambda item: (item["_distance"], item["document_id"]))
        return rows[: self.limit_value]


class FakeLanceTable:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)

    def add(self, rows: list[dict]) -> None:
        self.rows.extend(rows)

    def search(self, query_embedding: list[float]) -> FakeLanceSearch:
        return FakeLanceSearch(self.rows, query_embedding)

    def delete(self, predicate: str) -> None:
        if predicate.startswith("parent_key = "):
            value = predicate.split(" = ", 1)[1].strip("'")
            self.rows = [row for row in self.rows if row["parent_key"] != value]
            return
        if predicate.startswith("document_id IN "):
            raw_values = predicate.removeprefix("document_id IN ").strip("()")
            values = {value.strip().strip("'") for value in raw_values.split(",")}
            self.rows = [row for row in self.rows if row["document_id"] not in values]
            return
        raise AssertionError(f"unexpected predicate: {predicate}")

    def count_rows(self) -> int:
        return len(self.rows)


class FakeLanceDB:
    def __init__(self) -> None:
        self.tables: dict[str, FakeLanceTable] = {}
        self.created: list[dict] = []

    def create_table(self, table_name: str, data: list[dict], mode: str):
        self.created.append({"table_name": table_name, "mode": mode, "data": data})
        table = FakeLanceTable(data)
        self.tables[table_name] = table
        return table

    def __getitem__(self, table_name: str) -> FakeLanceTable:
        return self.tables[table_name]


class FakeLanceDBWithTableListing(FakeLanceDB):
    def __init__(self) -> None:
        super().__init__()
        self.list_tables_calls = 0
        self.table_names_calls = 0
        self.open_table_calls = 0

    def list_tables(self) -> list[str]:
        self.list_tables_calls += 1
        return list(self.tables)

    def table_names(self) -> list[str]:
        self.table_names_calls += 1
        raise AssertionError("deprecated table_names should not be called when list_tables is available")

    def open_table(self, table_name: str) -> FakeLanceTable:
        self.open_table_calls += 1
        return self.tables[table_name]


def test_lancedb_vector_index_reopens_existing_table_before_search(tmp_path):
    fake_db = FakeLanceDB()
    first = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    first.rebuild([VectorIndexDocument("alpha-0", "alpha", 0, "Alpha notes", [1.0])])

    reopened = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    results = reopened.search(VectorIndexQuery("alpha", [1.0], limit=5))

    assert [result.document_id for result in results] == ["alpha-0"]
    assert reopened.stats() == {"document_count": 1}


def test_lancedb_vector_index_prefers_list_tables_over_deprecated_table_names(tmp_path):
    fake_db = FakeLanceDBWithTableListing()
    first = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    first.rebuild([VectorIndexDocument("alpha-0", "alpha", 0, "Alpha notes", [1.0])])

    reopened = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    results = reopened.search(VectorIndexQuery("alpha", [1.0], limit=5))

    assert [result.document_id for result in results] == ["alpha-0"]
    assert fake_db.list_tables_calls >= 1
    assert fake_db.table_names_calls == 0
    assert fake_db.open_table_calls >= 1


def test_lancedb_vector_index_rebuild_searches_and_filters_with_citations(tmp_path):
    fake_db = FakeLanceDB()
    index = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    index.rebuild(
        [
            VectorIndexDocument(
                document_id="alpha-0",
                parent_key="alpha",
                chunk_id=0,
                text="Alpha migration notes",
                embedding=[1.0],
                metadata={"project": "Engram", "domain": "migration"},
                citation={"source": "memory", "key": "alpha", "chunk_id": 0},
            ),
            VectorIndexDocument(
                document_id="external-0",
                parent_key="external",
                chunk_id=0,
                text="External migration notes",
                embedding=[1.0],
                metadata={"project": "Other", "domain": "migration"},
                citation={"source": "memory", "key": "external", "chunk_id": 0},
            ),
        ]
    )

    results = index.search(
        VectorIndexQuery(
            query_text="migration",
            query_embedding=[1.0],
            limit=5,
            filters={"project": "Engram"},
        )
    )

    assert fake_db.created[0]["mode"] == "overwrite"
    assert fake_db.created[0]["data"][0]["vector"] == [1.0]
    assert fake_db.created[0]["data"][0]["metadata_json"]
    assert [result.document_id for result in results] == ["alpha-0"]
    assert results[0].score == 1.0
    assert results[0].metadata == {"project": "Engram", "domain": "migration"}
    assert results[0].citation == {"source": "memory", "key": "alpha", "chunk_id": 0}


def test_lancedb_vector_index_upsert_and_delete_use_contract_ids(tmp_path):
    fake_db = FakeLanceDB()
    index = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    index.rebuild(
        [
            VectorIndexDocument("alpha-0", "alpha", 0, "Alpha 0", [1.0]),
            VectorIndexDocument("alpha-1", "alpha", 1, "Alpha 1", [1.0]),
            VectorIndexDocument("beta-0", "beta", 0, "Beta 0", [0.5]),
        ]
    )

    index.upsert_many([VectorIndexDocument("beta-0", "beta", 0, "Beta updated", [0.9])])
    deleted = index.delete_by_parent_key("alpha")
    results = index.search(VectorIndexQuery("beta", [1.0], limit=10))

    assert deleted == 2
    assert index.stats() == {"document_count": 1}
    assert [result.document_id for result in results] == ["beta-0"]
    assert results[0].text == "Beta updated"


def test_lancedb_vector_index_hybrid_mode_reranks_exact_identifier_candidates(tmp_path):
    fake_db = FakeLanceDB()
    index = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    index.rebuild(
        [
            VectorIndexDocument(
                document_id="semantic-0",
                parent_key="semantic",
                chunk_id=0,
                text="General mapping guidance without the exact tool name.",
                embedding=[1.0],
            ),
            VectorIndexDocument(
                document_id="identifier-0",
                parent_key="identifier",
                chunk_id=0,
                text="Use prepare_codebase_mapping before storing mapped repo context.",
                embedding=[0.5],
                metadata={"tool": "prepare_codebase_mapping"},
            ),
        ]
    )

    semantic_results = index.search(
        VectorIndexQuery(
            query_text="prepare_codebase_mapping",
            query_embedding=[1.0],
            limit=2,
        )
    )
    hybrid_results = index.search(
        VectorIndexQuery(
            query_text="prepare_codebase_mapping",
            query_embedding=[1.0],
            limit=2,
            retrieval_mode="hybrid",
        )
    )

    assert [result.document_id for result in semantic_results] == ["semantic-0", "identifier-0"]
    assert [result.document_id for result in hybrid_results] == ["identifier-0", "semantic-0"]


def test_lancedb_vector_index_missing_dependency_error_is_actionable(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "lancedb":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(RuntimeError, match="Install the optional 'lancedb' dependency"):
        LanceDBVectorIndex(tmp_path / "lance")

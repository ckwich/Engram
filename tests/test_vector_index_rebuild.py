from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.memory_os_migration import MemoryOSMigrationKernel
from core.vector_index import InMemoryVectorIndex, VectorIndexQuery
from core.vector_index_rebuild import (
    rebuild_vector_index_from_sources,
    run_vector_index_rebuild_dry_run,
)


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


def _write_memory(path: Path, payload: dict) -> dict:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


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


def test_vector_index_rebuild_dry_run_writes_report_for_migrated_store(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    report_path = tmp_path / "vector_rebuild_report.json"
    legacy_dir.mkdir()
    _write_memory(
        legacy_dir / "alpha.json",
        {"key": "alpha", "title": "Alpha", "content": "# Alpha\n\nAlpha content", "chunk_count": 1},
    )
    _write_memory(
        legacy_dir / "beta.json",
        {"key": "beta", "title": "Beta", "content": "# Beta\n\nBeta content", "chunk_count": 1},
    )
    MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir)

    report = run_vector_index_rebuild_dry_run(store_root, report_path=report_path, batch_size=1)

    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert report["schema_version"] == "2026-05-11.vector_index_rebuild.dry_run.v1"
    assert report["mode"] == "dry_run"
    assert report["embedding_provider"] == "deterministic_dry_run_stub"
    assert report["store_root"] == str(store_root)
    assert report["source_count"] == 2
    assert report["rebuild_receipt"]["document_count"] == 2
    assert report["rebuild_receipt"]["batch_count"] == 2
    assert report["rebuild_receipt"]["index_stats"] == {"document_count": 2}


def test_vector_index_rebuild_dry_run_cli_prints_and_writes_same_report(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    report_path = tmp_path / "vector_rebuild_report.json"
    legacy_dir.mkdir()
    _write_memory(
        legacy_dir / "alpha.json",
        {"key": "alpha", "title": "Alpha", "content": "# Alpha\n\nAlpha content", "chunk_count": 1},
    )
    MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.vector_index_rebuild",
            "dry-run",
            "--store-root",
            str(store_root),
            "--report",
            str(report_path),
            "--batch-size",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    file_report = json.loads(report_path.read_text(encoding="utf-8"))
    stdout_report = json.loads(result.stdout)
    assert stdout_report == file_report
    assert stdout_report["mode"] == "dry_run"
    assert stdout_report["rebuild_receipt"]["document_count"] == 1


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

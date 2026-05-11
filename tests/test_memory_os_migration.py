from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.memory_os_migration import (
    MemoryOSMigrationKernel,
    build_vector_index_documents,
    legacy_json_filename,
)
from core.vector_index import VectorIndexDocument


def _write_memory(path: Path, payload: dict) -> dict:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _chunk_doc_id(key: str, chunk_id: int) -> str:
    key_hash = hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{key_hash}_{chunk_id}"


def test_legacy_import_dry_run_reports_counts_without_writing_store(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "tags": ["one"],
            "related_to": ["beta"],
            "project": "Engram",
            "domain": "migration",
            "status": "active",
            "canonical": True,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-02T00:00:00+00:00",
            "chars": 13,
            "lines": 1,
            "chunk_count": 2,
            "legacy_note": "preserve me in the artifact",
        },
    )
    _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "tags": "two,three",
            "related_to": "alpha",
            "chunk_count": 1,
        },
    )
    (legacy_dir / "broken.json").write_text("{not-json", encoding="utf-8")

    report = MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir, dry_run=True)

    assert report["dry_run"] is True
    assert report["source_count"] == 3
    assert report["valid_count"] == 2
    assert report["invalid_count"] == 1
    assert report["would_import_count"] == 2
    assert report["imported_count"] == 0
    assert report["key_set"] == ["alpha", "beta"]
    assert report["chunk_count_total"] == 3
    assert report["related_to_count"] == 2
    assert report["unsupported_fields"] == {"alpha": ["legacy_note"]}
    assert report["field_mappings"]["related_to"] == "memories.related_to_json"
    assert not (store_root / "ledger.sqlite3").exists()
    assert not (store_root / "objects").exists()


def test_legacy_import_stores_queryable_chunk_records(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nAlpha content\n\n## Alpha\n\nDetailed content",
            "tags": ["one"],
            "project": "Engram",
            "domain": "migration",
            "chunk_count": 99,
        },
    )

    kernel = MemoryOSMigrationKernel(store_root)
    dry_run = kernel.import_legacy_json(legacy_dir, dry_run=True)
    import_report = kernel.import_legacy_json(legacy_dir)
    chunks = kernel.read_chunk_records("alpha")

    assert dry_run["chunk_count_total"] == 99
    assert dry_run["derived_chunk_count_total"] == 2
    assert dry_run["chunk_count_mismatches"] == [
        {"key": "alpha", "legacy_chunk_count": 99, "derived_chunk_count": 2}
    ]
    assert import_report["derived_chunk_count_total"] == 2
    assert len(chunks) == 2
    assert chunks[0] == {
        "document_id": _chunk_doc_id("alpha", 0),
        "memory_key": "alpha",
        "chunk_id": 0,
        "chunk_index": 0,
        "text": "# Alpha\n\nAlpha content",
        "text_hash": hashlib.sha256("# Alpha\n\nAlpha content".encode("utf-8")).hexdigest(),
        "chars": 22,
        "section_title": "Alpha",
        "heading_path": ["Alpha"],
        "chunk_kind": "section",
    }
    assert chunks[1]["document_id"] == _chunk_doc_id("alpha", 1)
    assert chunks[1]["text"] == "## Alpha\n\nDetailed content"
    assert chunks[1]["section_title"] == "Alpha"
    assert chunks[1]["heading_path"] == ["Alpha", "Alpha"]


def test_bundle_restore_preserves_chunk_records(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nAlpha content\n\n## Details\n\nDetailed content",
            "chunk_count": 2,
        },
    )

    kernel = MemoryOSMigrationKernel(store_root)
    kernel.import_legacy_json(legacy_dir)
    bundle = kernel.export_bundle()
    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(bundle)

    assert restored.read_chunk_records("alpha") == kernel.read_chunk_records("alpha")


def test_legacy_related_to_links_import_as_stable_graph_edge_records(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "related_to": ["beta", "gamma"],
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-02T00:00:00+00:00",
        },
    )
    _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "related_to": ["alpha"],
            "created_at": "2026-05-03T00:00:00+00:00",
            "updated_at": "2026-05-04T00:00:00+00:00",
        },
    )

    kernel = MemoryOSMigrationKernel(store_root)
    kernel.import_legacy_json(legacy_dir)
    edges = kernel.read_graph_edge_records()

    assert [(edge["from_ref"]["key"], edge["to_ref"]["key"]) for edge in edges] == [
        ("alpha", "beta"),
        ("alpha", "gamma"),
        ("beta", "alpha"),
    ]
    assert {edge["edge_type"] for edge in edges} == {"related_to"}
    assert {edge["source"] for edge in edges} == {"legacy_related_to"}
    assert all(edge["edge_id"].startswith("sha256:") for edge in edges)
    assert all("content" not in edge for edge in edges)

    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(kernel.export_bundle())

    assert restored.read_graph_edge_records() == edges


def test_legacy_graph_edge_document_imports_generic_refs_and_restores_bundle(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    graph_path = tmp_path / "edges.json"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
        },
    )
    graph_edge = {
        "edge_id": "sha256:external-edge",
        "from_ref": {"kind": "source", "key": "design-doc"},
        "to_ref": {"kind": "memory", "key": "alpha"},
        "edge_type": "supports",
        "confidence": 0.8,
        "evidence": "Design doc supports alpha.",
        "source": "legacy_graph",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-05T00:00:00+00:00",
        "updated_at": "2026-05-05T00:00:00+00:00",
    }
    graph_path.write_text(
        json.dumps({"schema_version": "2026-04-27", "edges": [graph_edge]}, indent=2),
        encoding="utf-8",
    )

    kernel = MemoryOSMigrationKernel(store_root)
    kernel.import_legacy_json(legacy_dir)
    import_report = kernel.import_legacy_graph_edges(graph_path)
    edges = kernel.read_graph_edge_records()

    assert import_report == {
        "schema_version": "2026-05-11.memory_os_migration.v4",
        "source_count": 1,
        "imported_count": 1,
        "invalid_count": 0,
        "edge_ids": ["sha256:external-edge"],
        "invalid": [],
    }
    assert edges == [graph_edge]

    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(kernel.export_bundle())

    assert restored.read_graph_edge_records() == [graph_edge]


def test_chunk_ledger_exports_vector_source_records_with_metadata_and_citations(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha Memory",
            "content": "# Alpha\n\nAlpha content",
            "tags": ["migration", "agent"],
            "project": "Engram",
            "domain": "memory-os",
            "status": "active",
            "canonical": True,
            "chunk_count": 1,
        },
    )

    kernel = MemoryOSMigrationKernel(store_root)
    kernel.import_legacy_json(legacy_dir)
    sources = kernel.read_vector_source_records("alpha")

    assert len(sources) == 1
    source = sources[0]
    assert source["document_id"] == _chunk_doc_id("alpha", 0)
    assert source["parent_key"] == "alpha"
    assert source["chunk_id"] == 0
    assert source["text"] == "# Alpha\n\nAlpha content"
    assert source["metadata"] == {
        "key": "alpha",
        "title": "Alpha Memory",
        "tags": ["migration", "agent"],
        "project": "Engram",
        "domain": "memory-os",
        "status": "active",
        "canonical": True,
        "section_title": "Alpha",
        "heading_path": ["Alpha"],
        "chunk_kind": "section",
        "text_hash": hashlib.sha256("# Alpha\n\nAlpha content".encode("utf-8")).hexdigest(),
    }
    assert source["citation"] == {
        "source": "memory_os_migration",
        "key": "alpha",
        "chunk_id": 0,
        "document_id": _chunk_doc_id("alpha", 0),
    }


def test_vector_source_records_convert_to_documents_only_with_supplied_embeddings(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha Memory",
            "content": "Alpha content",
            "chunk_count": 1,
        },
    )

    kernel = MemoryOSMigrationKernel(store_root)
    kernel.import_legacy_json(legacy_dir)
    sources = kernel.read_vector_source_records()
    embeddings = {sources[0]["document_id"]: [1.0, 0.0]}

    documents = build_vector_index_documents(sources, embeddings)

    assert documents == [
        VectorIndexDocument(
            document_id=sources[0]["document_id"],
            parent_key="alpha",
            chunk_id=0,
            text="Alpha content",
            embedding=[1.0, 0.0],
            metadata=sources[0]["metadata"],
            citation=sources[0]["citation"],
        )
    ]
    with pytest.raises(ValueError, match="missing embedding"):
        build_vector_index_documents(sources, {})


def test_legacy_import_exports_bundle_and_restores_legacy_json_artifacts(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    restored_json_dir = tmp_path / "legacy_restored"
    legacy_dir.mkdir()

    alpha = _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nAlpha content",
            "tags": ["one", "two"],
            "related_to": ["beta"],
            "project": "Engram",
            "domain": "migration",
            "status": "active",
            "canonical": True,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-02T00:00:00+00:00",
            "chars": 22,
            "lines": 3,
            "chunk_count": 4,
            "legacy_note": "artifact-only field",
        },
    )
    beta = _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "tags": ["three"],
            "related_to": [],
            "chunk_count": 1,
        },
    )

    kernel = MemoryOSMigrationKernel(store_root)
    import_report = kernel.import_legacy_json(legacy_dir)

    assert import_report["dry_run"] is False
    assert import_report["imported_count"] == 2
    assert import_report["key_set"] == ["alpha", "beta"]
    assert (store_root / "ledger.sqlite3").exists()
    assert (store_root / "objects").exists()
    assert kernel.read_memory_record("alpha")["related_to"] == ["beta"]
    assert kernel.read_memory_record("alpha")["chunk_count"] == 4

    bundle = kernel.export_bundle()
    restored = MemoryOSMigrationKernel(restore_root)
    restore_report = restored.restore_bundle(bundle)

    assert restore_report["restored_count"] == 2
    assert restored.key_set() == ["alpha", "beta"]
    assert restored.read_memory_record("alpha")["tags"] == ["one", "two"]
    assert restored.read_memory_record("alpha")["related_to"] == ["beta"]
    assert restored.read_memory_record("alpha")["canonical"] is True
    assert restored.read_memory_record("beta")["tags"] == ["three"]

    legacy_report = restored.restore_legacy_json(restored_json_dir)

    assert legacy_report["restored_count"] == 2
    assert json.loads((restored_json_dir / legacy_json_filename("alpha")).read_text(encoding="utf-8")) == alpha
    assert json.loads((restored_json_dir / legacy_json_filename("beta")).read_text(encoding="utf-8")) == beta

    shutil.rmtree(store_root)
    shutil.rmtree(restore_root)


def test_round_trip_cli_writes_durable_parity_report(tmp_path):
    legacy_dir = tmp_path / "legacy"
    work_root = tmp_path / "migration_work"
    report_path = tmp_path / "migration_report.json"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "tags": ["one"],
            "related_to": ["beta"],
            "chunk_count": 1,
        },
    )
    _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "tags": ["two"],
            "related_to": [],
            "chunk_count": 1,
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.memory_os_migration",
            "round-trip",
            "--legacy-dir",
            str(legacy_dir),
            "--work-root",
            str(work_root),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    stdout_report = json.loads(result.stdout)
    assert stdout_report == report
    assert report["status"] == "pass"
    assert report["dry_run"]["valid_count"] == 2
    assert report["dry_run"]["derived_chunk_count_total"] == 2
    assert report["dry_run"]["chunk_count_mismatch_count"] == 0
    assert report["import"]["imported_count"] == 2
    assert report["bundle"]["memory_count"] == 2
    assert report["restore"]["restored_count"] == 2
    assert report["legacy_json_restore"]["restored_count"] == 2
    assert report["parity"]["key_sets_match"] is True
    assert (work_root / "store" / "ledger.sqlite3").exists()
    assert (work_root / "restored_store" / "ledger.sqlite3").exists()
    assert (work_root / "restored_json").is_dir()

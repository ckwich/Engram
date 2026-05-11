from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.document_intelligence import (
    prepare_document_record,
    prepare_document_draft,
    prepare_document_extraction_request,
    prepare_document_promotion_transaction,
    prepare_extractor_receipt,
    prepare_visual_artifact_record,
    prepare_visual_extraction_request,
    preview_document_extraction,
    preview_visual_extraction,
)
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
        "schema_version": "2026-05-11.memory_os_migration.v7",
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


def test_document_intelligence_evidence_records_round_trip_without_promoting_memory(tmp_path):
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    document = prepare_document_record(
        title="Architecture Scan",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "a" * 64,
        media_type="application/pdf",
    )
    request = prepare_visual_extraction_request(
        document_record=document,
        image_refs=[
            {
                "source_uri": "file:///docs/architecture.pdf",
                "page": 3,
                "image_hash": "sha256:" + "b" * 64,
            }
        ],
        requested_capabilities=["ocr_text", "diagram_description"],
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
    )
    artifact = prepare_visual_artifact_record(
        document_id=document["document_id"],
        artifact_type="diagram",
        source_ref={"source_uri": "file:///docs/architecture.pdf", "page": 3},
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
        text="Agent memory OS",
        description="A diagram showing source to memory promotion.",
        page_number=3,
        bounding_box={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        confidence=0.91,
    )
    receipt = prepare_extractor_receipt(
        document_record=document,
        visual_artifacts=[artifact],
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
    )

    kernel = MemoryOSMigrationKernel(store_root)
    report = kernel.store_document_evidence_records([document, request, artifact, receipt])
    records = kernel.read_document_evidence_records(document_id=document["document_id"])
    visual_records = kernel.read_document_evidence_records(
        document_id=document["document_id"],
        record_type="visual_artifact",
    )

    assert report["schema_version"] == "2026-05-11.memory_os_migration.v7"
    assert report["stored_count"] == 4
    assert report["record_ids"] == [
        document["document_id"],
        request["request_id"],
        artifact["artifact_id"],
        receipt["receipt_id"],
    ]
    assert records == [document, request, artifact, receipt]
    assert visual_records == [artifact]
    assert all(record["active_memory_write_performed"] is False for record in records)

    bundle = kernel.export_bundle()
    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(bundle)

    assert bundle["document_evidence_count"] == 4
    assert restored.read_document_evidence_records(document_id=document["document_id"]) == records


def test_document_extraction_request_records_round_trip_before_document_exists(tmp_path):
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    request = prepare_document_extraction_request(
        source_ref={
            "source_uri": "file:///docs/architecture.pdf",
            "content_hash": "sha256:" + "d" * 64,
        },
        source_type="pdf",
        requested_outputs=["markdown", "metadata", "page_images"],
        extractor_id="local-pdf-extractor",
        extractor_kind="external_document",
    )

    kernel = MemoryOSMigrationKernel(store_root)
    report = kernel.store_document_evidence_records([request])
    stored_requests = kernel.read_document_evidence_records(
        document_id=request["request_id"],
        record_type="document_extraction_request",
    )
    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(kernel.export_bundle())

    assert report["record_ids"] == [request["request_id"]]
    assert stored_requests == [request]
    assert restored.read_document_evidence_records(record_type="document_extraction_request") == [request]


def test_document_evidence_store_rejects_active_memory_records(tmp_path):
    document = prepare_document_record(
        title="Architecture Scan",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "a" * 64,
        media_type="application/pdf",
    )
    document["active_memory_write_performed"] = True

    with pytest.raises(ValueError, match="document evidence records must not be active memory writes"):
        MemoryOSMigrationKernel(tmp_path / "store").store_document_evidence_records([document])


def test_document_evidence_store_rejects_executed_write_records(tmp_path):
    document = prepare_document_record(
        title="Architecture Note",
        source_uri="file:///docs/architecture.md",
        source_type="markdown",
        content_hash="sha256:" + "c" * 64,
        media_type="text/markdown",
    )
    draft = prepare_document_draft(
        document_record=document,
        analysis={"claims": ["Reviewed claim"]},
    )
    transaction = prepare_document_promotion_transaction(
        document_draft=draft,
        selected_memory_indexes=[0],
        selected_edge_indexes=[],
        approved_by="agent-review",
    )
    transaction["write_performed"] = True

    with pytest.raises(ValueError, match="document evidence records must not be executed write receipts"):
        MemoryOSMigrationKernel(tmp_path / "store").store_document_evidence_records([transaction])


def test_document_draft_records_persist_and_restore_with_evidence_records(tmp_path):
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    document = prepare_document_record(
        title="Architecture Note",
        source_uri="file:///docs/architecture.md",
        source_type="markdown",
        content_hash="sha256:" + "c" * 64,
        media_type="text/markdown",
    )
    draft = prepare_document_draft(
        document_record=document,
        analysis={
            "summary": "Architecture note.",
            "decisions": ["Keep document draft promotion explicit."],
        },
        chunk_refs=[{"document_id": document["document_id"], "chunk_id": 0}],
    )

    kernel = MemoryOSMigrationKernel(store_root)
    report = kernel.store_document_evidence_records([document, draft])
    draft_records = kernel.read_document_evidence_records(
        document_id=document["document_id"],
        record_type="document_draft",
    )
    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(kernel.export_bundle())

    assert report["schema_version"] == "2026-05-11.memory_os_migration.v7"
    assert report["record_ids"] == [document["document_id"], draft["draft_id"]]
    assert draft_records == [draft]
    assert restored.read_document_evidence_records(record_type="document_draft") == [draft]


def test_document_promotion_transaction_records_persist_and_restore(tmp_path):
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    document = prepare_document_record(
        title="Architecture Note",
        source_uri="file:///docs/architecture.md",
        source_type="markdown",
        content_hash="sha256:" + "c" * 64,
        media_type="text/markdown",
    )
    draft = prepare_document_draft(
        document_record=document,
        analysis={"claims": ["Reviewed claim"]},
    )
    transaction = prepare_document_promotion_transaction(
        document_draft=draft,
        selected_memory_indexes=[0],
        selected_edge_indexes=[],
        approved_by="agent-review",
    )

    kernel = MemoryOSMigrationKernel(store_root)
    report = kernel.store_document_evidence_records([document, draft, transaction])
    transaction_records = kernel.read_document_evidence_records(
        document_id=document["document_id"],
        record_type="document_promotion_transaction",
    )
    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(kernel.export_bundle())

    assert report["schema_version"] == "2026-05-11.memory_os_migration.v7"
    assert report["record_ids"] == [document["document_id"], draft["draft_id"], transaction["transaction_id"]]
    assert transaction_records == [transaction]
    assert restored.read_document_evidence_records(record_type="document_promotion_transaction") == [transaction]


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


def test_migration_cli_import_export_restore_bundle_commands(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    import_report_path = tmp_path / "import_report.json"
    restore_report_path = tmp_path / "restore_report.json"
    bundle_path = tmp_path / "bundle.json"
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

    import_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.memory_os_migration",
            "import-legacy",
            "--legacy-dir",
            str(legacy_dir),
            "--store-root",
            str(store_root),
            "--report",
            str(import_report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert import_result.returncode == 0, import_result.stderr
    import_report = json.loads(import_report_path.read_text(encoding="utf-8"))
    assert json.loads(import_result.stdout) == import_report
    assert import_report["imported_count"] == 2
    assert import_report["key_set"] == ["alpha", "beta"]

    export_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.memory_os_migration",
            "export-bundle",
            "--store-root",
            str(store_root),
            "--bundle",
            str(bundle_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert export_result.returncode == 0, export_result.stderr
    export_report = json.loads(export_result.stdout)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert export_report["bundle_path"] == str(bundle_path)
    assert export_report["memory_count"] == 2
    assert bundle["memory_count"] == 2
    assert bundle["document_evidence_count"] == 0

    restore_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.memory_os_migration",
            "restore-bundle",
            "--store-root",
            str(restore_root),
            "--bundle",
            str(bundle_path),
            "--report",
            str(restore_report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert restore_result.returncode == 0, restore_result.stderr
    restore_report = json.loads(restore_report_path.read_text(encoding="utf-8"))
    assert json.loads(restore_result.stdout) == restore_report
    assert restore_report["restored_count"] == 2
    assert restore_report["key_set"] == ["alpha", "beta"]
    assert MemoryOSMigrationKernel(restore_root).read_graph_edge_records("alpha")[0]["to_ref"]["key"] == "beta"


def test_migration_cli_imports_legacy_graph_edge_documents(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    graph_path = tmp_path / "edges.json"
    report_path = tmp_path / "graph_import_report.json"
    legacy_dir.mkdir()
    _write_memory(
        legacy_dir / "alpha.json",
        {"key": "alpha", "title": "Alpha", "content": "Alpha content", "chunk_count": 1},
    )
    graph_edge = {
        "edge_id": "sha256:graph-cli-edge",
        "from_ref": {"kind": "source", "key": "design-doc"},
        "to_ref": {"kind": "memory", "key": "alpha"},
        "edge_type": "supports",
        "confidence": 0.75,
        "evidence": "Design doc supports alpha.",
        "source": "legacy_graph",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-06T00:00:00+00:00",
        "updated_at": "2026-05-06T00:00:00+00:00",
    }
    graph_path.write_text(
        json.dumps({"schema_version": "2026-04-27", "edges": [graph_edge]}, indent=2),
        encoding="utf-8",
    )
    MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.memory_os_migration",
            "import-graph-edges",
            "--store-root",
            str(store_root),
            "--graph-path",
            str(graph_path),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert json.loads(result.stdout) == report
    assert report["imported_count"] == 1
    assert report["edge_ids"] == ["sha256:graph-cli-edge"]
    assert MemoryOSMigrationKernel(store_root).read_graph_edge_records()[0] == graph_edge


def test_migration_cli_lists_document_intelligence_records(tmp_path):
    store_root = tmp_path / "store"
    report_path = tmp_path / "document_records_report.json"
    document = prepare_document_record(
        title="Architecture Note",
        source_uri="file:///docs/architecture.md",
        source_type="markdown",
        content_hash="sha256:" + "c" * 64,
        media_type="text/markdown",
    )
    draft = prepare_document_draft(
        document_record=document,
        analysis={"claims": ["Reviewed claim"]},
    )
    MemoryOSMigrationKernel(store_root).store_document_evidence_records([document, draft])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.memory_os_migration",
            "list-document-records",
            "--store-root",
            str(store_root),
            "--document-id",
            document["document_id"],
            "--record-type",
            "document_draft",
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert json.loads(result.stdout) == report
    assert report["schema_version"] == "2026-05-11.memory_os_migration.v7"
    assert report["filters"] == {
        "document_id": document["document_id"],
        "record_type": "document_draft",
    }
    assert report["count"] == 1
    assert report["records"] == [draft]


def test_document_intelligence_review_first_workflow_round_trips_without_active_writes(tmp_path):
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    text_preview = preview_document_extraction(
        title="Architecture Note",
        source_uri="file:///docs/architecture.md",
        source_type="markdown",
        content="# Architecture\n\nDecision: Keep document intelligence review-first.",
        media_type="text/markdown",
        metadata={"project": "Engram", "domain": "memory-os"},
    )
    visual_request = prepare_visual_extraction_request(
        document_record=text_preview["document_record"],
        image_refs=[{"source_uri": "file:///docs/architecture.png", "page": 1}],
        requested_capabilities=["diagram_description", "ocr_text"],
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
    )
    visual_preview = preview_visual_extraction(
        document_record=text_preview["document_record"],
        observations=[
            {
                "artifact_type": "diagram",
                "source_ref": {"source_uri": "file:///docs/architecture.png", "page": 1},
                "description": "Diagram says document evidence becomes drafts before memory.",
                "page_number": 1,
                "confidence": 0.9,
            }
        ],
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
    )
    draft = prepare_document_draft(
        document_record=text_preview["document_record"],
        analysis={
            "summary": "Architecture note about review-first document intelligence.",
            "decisions": ["Keep document intelligence review-first."],
            "claims": ["Visual artifacts stay evidence until promotion."],
        },
        chunk_refs=[text_preview["chunks"][0]["provenance"]],
        visual_artifacts=visual_preview["visual_artifacts"],
    )
    transaction = prepare_document_promotion_transaction(
        document_draft=draft,
        selected_memory_indexes=[0],
        selected_edge_indexes=[],
        approved_by="agent-review",
    )

    records = [
        text_preview["document_record"],
        visual_request,
        *visual_preview["visual_artifacts"],
        visual_preview["extractor_receipt"],
        draft,
        transaction,
    ]
    kernel = MemoryOSMigrationKernel(store_root)
    report = kernel.store_document_evidence_records(records)
    restored = MemoryOSMigrationKernel(restore_root)
    restored.restore_bundle(kernel.export_bundle())
    restored_records = restored.read_document_evidence_records(
        document_id=text_preview["document_record"]["document_id"]
    )

    assert report["stored_count"] == len(records)
    assert [record["record_type"] for record in restored_records] == [
        "document",
        "visual_extraction_request",
        "visual_artifact",
        "extractor_receipt",
        "document_draft",
        "document_promotion_transaction",
    ]
    assert all(record.get("active_memory_write_performed") is False for record in restored_records)
    assert all(record.get("write_performed") is not True for record in restored_records)

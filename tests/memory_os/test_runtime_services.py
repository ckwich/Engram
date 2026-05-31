from __future__ import annotations

import json
from pathlib import Path

from core.graph_store import JsonGraphStore
from core.memory_os._records import read_record, upsert_record
from core.memory_os.graph_ref_repair import GraphReferenceRepairService
from core.memory_os.knowledge_service import KnowledgeQueryService
from core.memory_os.legacy_migration_service import LegacyMigrationService
from core.memory_os.metadata_repair import MetadataRepairService
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text: str) -> list[float]:
    return [1.0, 0.0] if str(text).strip() else [0.0, 1.0]


def _runtime(tmp_path: Path) -> MemoryOSRuntime:
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "graph_edges.json"),
    )
    runtime.initialize()
    return runtime


def _write_legacy(path: Path, filename: str, payload: dict) -> None:
    (path / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_legacy_migration_service_applies_reviewed_legacy_memories(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    _write_legacy(
        legacy_dir,
        "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha visual hierarchy memory.",
            "project": "Engram",
            "status": "active",
        },
    )

    runtime = _runtime(tmp_path)
    service = runtime.legacy_migration

    assert isinstance(service, LegacyMigrationService)
    prepared = service.prepare_legacy_memory_os_migration(legacy_dir=legacy_dir)
    applied = service.apply_legacy_memory_os_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="agent-review",
    )

    assert prepared["write_performed"] is False
    assert prepared["would_import_count"] == 1
    assert applied["status"] == "ok"
    assert applied["changed_count"] == 1
    assert read_record(runtime.ledger, "memories", "alpha")["legacy_import"]["imported_by"] == "agent-review"


def test_knowledge_service_serves_project_orientation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.store_memory(
        key="engram_runtime_services",
        content="# Summary\n\nEngram runtime now delegates knowledge routing to a focused service.",
        title="Runtime Services",
        project="Engram",
        tags=["reviewed", "architecture"],
    )
    service = runtime.knowledge_service

    assert isinstance(service, KnowledgeQueryService)
    response = service.query_knowledge(
        {
            "request_id": "req-runtime-services",
            "ask": {
                "goal": "Orient me to runtime service extraction.",
                "task_type": "project_orientation",
                "project": "Engram",
                "focus": ["runtime", "service"],
            },
        }
    )

    assert response["status"] == "ok"
    assert response["planner"]["strategy"] == "project_orientation"
    assert "focused service" in response["answer"]["summary"]


def test_metadata_repair_service_repairs_document_catalog_fields(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    document_id = "doc_advanced_game_design"
    upsert_record(
        runtime.ledger,
        "documents",
        document_id,
        {
            "document_id": document_id,
            "title": "Advanced Game Design",
            "source_ref": {"source_uri": "file:///books/advanced-game-design.pdf", "source_type": "pdf"},
            "document_catalog": {
                "schema_version": "2026-05-17.document-catalog.v1",
                "content_form": "book",
                "primary_subject": "game_design",
                "corpus_tags": ["book", "game-design"],
            },
            "usable": True,
            "ingestion_status": "usable",
        },
    )
    upsert_record(
        runtime.ledger,
        "chunks",
        f"{document_id}:chunk:0",
        {
            "chunk_record_id": f"{document_id}:chunk:0",
            "document_id": document_id,
            "chunk_id": 0,
            "text": "Game design books need consistent catalog metadata.",
        },
    )
    service = runtime.metadata_repair

    assert isinstance(service, MetadataRepairService)
    prepared = service.repair_document_metadata(project="Design Books", document_ids=[document_id])
    applied = service.repair_document_metadata(
        project="Design Books",
        document_ids=[document_id],
        accept=True,
        approved_by="agent-review",
    )

    repaired = read_record(runtime.ledger, "documents", document_id)
    assert prepared["status"] == "prepared"
    assert applied["status"] == "ok"
    assert repaired["project"] == "Design Books"
    assert repaired["domain"] == "game_design"
    assert "game-design" in repaired["tags"]


def test_graph_ref_repair_service_repairs_graph_ref_identities(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    upsert_record(
        runtime.ledger,
        "graph_edges",
        "edge:document:chunk",
        {
            "edge_id": "edge:document:chunk",
            "from_ref": {"kind": "document", "document_id": "doc_design"},
            "to_ref": {
                "kind": "chunk",
                "document_id": "doc_design",
                "chunk_id": 2,
                "chunk_record_id": "doc_design:chunk:2",
            },
            "edge_type": "contains",
            "confidence": 1.0,
            "evidence": "Document contains chunk.",
            "source": "document_ingestion.structural",
            "status": "active",
            "created_by": "agent",
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:00+00:00",
        },
    )
    service = runtime.graph_ref_repair

    assert isinstance(service, GraphReferenceRepairService)
    repaired = service.repair_graph_edge_refs(
        source="document_ingestion.structural",
        accept=True,
        approved_by="agent-review",
    )

    edge = read_record(runtime.ledger, "graph_edges", "edge:document:chunk")
    assert repaired["status"] == "ok"
    assert repaired["repaired_count"] == 1
    assert edge["from_ref"]["key"] == "doc_design"
    assert edge["to_ref"]["key"] == "doc_design:chunk:2"

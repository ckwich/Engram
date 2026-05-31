from __future__ import annotations

from pathlib import Path

from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, read_record, upsert_record
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    return [1.0, 0.0] if str(text).strip() else [0.0, 1.0]


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def test_repair_book_metadata_normalizes_documents_chunks_jobs_and_retrieval(tmp_path: Path):
    runtime = _runtime(tmp_path)
    document_id = "doc_ux_for_beginners"
    ingestion_id = "doc_ingest_ux"
    document = {
        "document_id": document_id,
        "title": "UX for Beginners",
        "source_ref": {"source_uri": "file:///books/ux-for-beginners.pdf", "source_type": "pdf"},
        "document": {"document_id": document_id, "title": "UX for Beginners", "source_type": "pdf"},
        "document_catalog": {
            "schema_version": "2026-05-17.document-catalog.v1",
            "content_form": "book",
            "primary_subject": "ux_design",
            "secondary_subjects": ["interface_design"],
            "collections": ["ux_design_books"],
            "reading_role": "reference",
            "adjacent_to_game_design": False,
            "exclude_from_core_game_design_corpus": True,
            "corpus_tags": ["book", "ux-design"],
            "classification_basis": "title_path_rules",
            "classification_confidence": 0.72,
        },
        "usable": True,
        "ingestion_status": "usable",
    }
    upsert_record(runtime.ledger, "documents", document_id, document)
    upsert_record(
        runtime.ledger,
        "jobs",
        ingestion_id,
        {
            "record_type": "document_ingestion",
            "job_id": ingestion_id,
            "ingestion_id": ingestion_id,
            "document_id": document_id,
            "project": "Engram",
            "domain": "document_intelligence",
            "status": "completed",
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
            "text": "UX beginners need practical design lessons.",
        },
    )
    runtime.retrieval.upsert_chunk_records(
        document_id,
        [
            {
                "document_id": f"{document_id}:chunk:0",
                "parent_key": document_id,
                "key": document_id,
                "chunk_id": 0,
                "text": "UX beginners need practical design lessons.",
                "metadata": {
                    "project": "Engram",
                    "domain": "document_intelligence",
                    "tags": ["document-ingestion"],
                },
            }
        ],
    )

    before = runtime.search_memories(
        "UX beginners lessons",
        project="Design Skills",
        domain="ux_design",
        tags=["book"],
        limit=3,
    )
    assert before["results"] == []

    dry_run = runtime.repair_document_metadata(
        project="Design Skills",
        document_ids=[document_id],
        accept=False,
        approved_by=None,
    )

    assert dry_run["status"] == "prepared"
    assert dry_run["write_performed"] is False
    assert dry_run["repairs"][0]["document_id"] == document_id
    assert read_record(runtime.ledger, "documents", document_id).get("project") is None

    applied = runtime.repair_document_metadata(
        project="Design Skills",
        document_ids=[document_id],
        accept=True,
        approved_by="agent-review",
    )

    assert applied["status"] == "ok"
    assert applied["write_performed"] is True
    assert applied["repaired_document_count"] == 1
    repaired_doc = read_record(runtime.ledger, "documents", document_id)
    assert repaired_doc["project"] == "Design Skills"
    assert repaired_doc["domain"] == "ux_design"
    assert repaired_doc["tags"] == ["document-ingestion", "book", "ux-design"]
    repaired_job = read_record(runtime.ledger, "jobs", ingestion_id)
    assert repaired_job["project"] == "Design Skills"
    assert repaired_job["domain"] == "ux_design"
    repaired_chunks = [
        record for record in list_records(runtime.ledger, "chunks") if record.get("document_id") == document_id
    ]
    assert repaired_chunks
    assert {chunk["project"] for chunk in repaired_chunks} == {"Design Skills"}
    assert {chunk["domain"] for chunk in repaired_chunks} == {"ux_design"}
    assert all(chunk["tags"] == ["document-ingestion", "book", "ux-design"] for chunk in repaired_chunks)

    after = runtime.search_memories(
        "UX beginners lessons",
        project="Design Skills",
        domain="ux_design",
        tags=["book"],
        limit=3,
    )
    assert any(item["key"] == document_id for item in after["results"])

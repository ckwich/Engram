from __future__ import annotations

from core.chunk_preview import preview_memory_chunks
from core.context_compiler import list_context_profiles
from core.document_artifacts import build_document_artifact_manifest
from core.document_intelligence import (
    list_document_extractors,
    prepare_document_draft,
    prepare_document_promotion_transaction,
    prepare_document_record,
    preview_document_extraction,
)
from core.document_quality import build_document_quality_report
from core.ingestion_pipelines import list_ingestion_pipelines
from core.policy.write_policy import assert_write_policy_metadata
from core.project_capsule import build_project_capsule_draft
from core.source_connectors import preview_document_source_connector, preview_source_connector


def test_preview_and_catalog_payloads_report_no_write_contracts(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("# Note\n\nSource text.", encoding="utf-8")

    payloads = {
        "chunk_preview_receipt": preview_memory_chunks("Alpha\n\nBeta")["receipt"],
        "ingestion_pipeline_catalog": list_ingestion_pipelines(),
        "context_profile_catalog": list_context_profiles(),
        "source_connector_preview": preview_source_connector(
            connector_type="local_path",
            target=str(note),
        ),
        "document_source_connector_preview": preview_document_source_connector(
            connector_type="local_path",
            target=str(note),
        ),
        "document_extractor_catalog": list_document_extractors(),
    }

    for operation, payload in payloads.items():
        assert_write_policy_metadata(payload, operation=operation)


def test_document_evidence_payloads_report_no_active_memory_writes(tmp_path):
    document = prepare_document_record(
        title="Evidence Note",
        source_uri="file:///evidence.md",
        source_type="markdown",
        content_hash="sha256:" + "a" * 64,
        media_type="text/markdown",
        metadata={"project": "Engram"},
    )
    preview = preview_document_extraction(
        title="Evidence Note",
        source_uri="file:///evidence.md",
        source_type="markdown",
        content="# Summary\n\nEvidence.",
        media_type="text/markdown",
        metadata={"project": "Engram"},
    )
    draft = prepare_document_draft(
        document_record=document,
        analysis={"summary": ["Evidence summary."]},
        chunk_refs=[{"key": "evidence_note", "chunk_id": 0}],
    )
    transaction = prepare_document_promotion_transaction(
        document_draft=draft,
        approved_by="reviewer",
        selected_memory_indexes=[0],
    )
    quality = build_document_quality_report(
        {
            "source": {"source_uri": "file:///evidence.md", "content_hash": "sha256:" + "a" * 64},
            "document": {"document_id": document["document_id"], "title": "Evidence Note", "page_count": 1},
            "pages": [{"page_number": 1, "text_status": "ok", "image_count": 0}],
            "quality_seed": {},
        }
    )
    manifest = build_document_artifact_manifest(
        {
            "source": {
                "source_uri": "file:///evidence.md",
                "source_type": "markdown",
                "content_hash": "sha256:" + "a" * 64,
            },
            "document": {"document_id": document["document_id"], "content_hash": "sha256:" + "a" * 64, "page_count": 1},
            "pages": [{"page_number": 1, "text_status": "ok", "image_count": 0}],
            "text": {"content": "Evidence page."},
            "quality_seed": {},
        },
        data_root=tmp_path,
    )

    payloads = {
        "document_record": document,
        "document_extraction_preview": preview,
        "document_draft": draft,
        "document_promotion_transaction": transaction,
        "document_quality_report": quality,
        "document_artifact_manifest": manifest,
    }

    for operation, payload in payloads.items():
        assert_write_policy_metadata(payload, operation=operation)


def test_project_capsule_draft_reports_review_required_no_write_contract():
    capsule = build_project_capsule_draft(
        project="Engram",
        task="Prepare repo context",
        summary="Review this before a session.",
        must_read_keys=["engram_direction"],
        context_packet={
            "profile": {"id": "repo_resume"},
            "context": {
                "chunks": [{"key": "engram_direction", "chunk_id": 0}],
                "citations": [{"key": "engram_direction", "chunk_id": 0}],
            },
            "warnings": [],
        },
        quality_payload={"summary": {}, "issue_count": 0},
    )

    assert_write_policy_metadata(capsule, operation="project_capsule_draft")
    assert capsule["promotion_required"] is True

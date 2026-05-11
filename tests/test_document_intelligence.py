from __future__ import annotations

import pytest

from core.document_intelligence import (
    prepare_document_record,
    prepare_extractor_receipt,
    prepare_visual_artifact_record,
)


def test_prepare_document_record_is_stable_reviewable_evidence_without_writes():
    document = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "a" * 64,
        media_type="application/pdf",
        metadata={"project": "Engram"},
    )
    duplicate = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "a" * 64,
        media_type="application/pdf",
        metadata={"project": "Engram"},
    )

    assert document["document_id"].startswith("doc_")
    assert len(document["document_id"]) == len("doc_") + 16
    assert duplicate["document_id"] == document["document_id"]
    assert document == {
        "schema_version": "2026-05-11.document-intelligence.v1",
        "record_type": "document",
        "document_id": document["document_id"],
        "title": "Architecture Notes",
        "source_uri": "file:///docs/architecture.pdf",
        "source_type": "pdf",
        "content_hash": "sha256:" + "a" * 64,
        "media_type": "application/pdf",
        "metadata": {"project": "Engram"},
        "review_status": "evidence",
        "active_memory_write_performed": False,
        "promotion_required": True,
    }


def test_prepare_visual_artifact_record_marks_ocr_vision_as_reviewable_evidence():
    artifact = prepare_visual_artifact_record(
        document_id="doc_alpha",
        artifact_type="diagram",
        source_ref={
            "source_uri": "file:///docs/architecture.pdf",
            "page": 3,
            "image_hash": "sha256:" + "b" * 64,
        },
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
        text="Service boundary diagram",
        description="A diagram showing Engram core, vector index, and graph store boundaries.",
        page_number=3,
        bounding_box={"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.25},
        confidence=0.82,
    )

    assert artifact["schema_version"] == "2026-05-11.document-intelligence.v1"
    assert artifact["record_type"] == "visual_artifact"
    assert artifact["artifact_id"].startswith("vis_")
    assert len(artifact["artifact_id"]) == len("vis_") + 16
    assert artifact["document_id"] == "doc_alpha"
    assert artifact["artifact_type"] == "diagram"
    assert artifact["extractor"] == {
        "id": "local-vision-v1",
        "kind": "ocr_vision",
        "external_framework_required": True,
    }
    assert artifact["review_status"] == "evidence"
    assert artifact["trusted_memory"] is False
    assert artifact["promotion_required"] is True
    assert artifact["active_memory_write_performed"] is False
    assert artifact["provenance"]["page_number"] == 3
    assert artifact["provenance"]["bounding_box"] == {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.25}


def test_prepare_visual_artifact_record_validates_confidence_bbox_and_provenance():
    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        prepare_visual_artifact_record(
            document_id="doc_alpha",
            artifact_type="screenshot",
            source_ref={"source_uri": "file:///ui.png"},
            extractor_id="agent",
            extractor_kind="agent_native",
            confidence=1.4,
        )

    with pytest.raises(ValueError, match="bounding_box.width must be positive"):
        prepare_visual_artifact_record(
            document_id="doc_alpha",
            artifact_type="screenshot",
            source_ref={"source_uri": "file:///ui.png"},
            extractor_id="agent",
            extractor_kind="agent_native",
            bounding_box={"x": 0, "y": 0, "width": 0, "height": 0.4},
        )

    with pytest.raises(ValueError, match="source_ref is required"):
        prepare_visual_artifact_record(
            document_id="doc_alpha",
            artifact_type="screenshot",
            source_ref={},
            extractor_id="agent",
            extractor_kind="agent_native",
        )


def test_prepare_extractor_receipt_links_visual_evidence_without_promoting_memory():
    document = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "a" * 64,
        media_type="application/pdf",
    )
    visual_artifact = prepare_visual_artifact_record(
        document_id=document["document_id"],
        artifact_type="figure",
        source_ref={"source_uri": "file:///docs/architecture.pdf", "page": 2},
        extractor_id="agent",
        extractor_kind="agent_native",
        description="A simple architecture figure.",
        confidence=0.9,
    )

    receipt = prepare_extractor_receipt(
        document_record=document,
        visual_artifacts=[visual_artifact],
        extractor_id="agent",
        extractor_kind="agent_native",
    )

    assert receipt["schema_version"] == "2026-05-11.document-intelligence.v1"
    assert receipt["record_type"] == "extractor_receipt"
    assert receipt["document_id"] == document["document_id"]
    assert receipt["visual_artifact_ids"] == [visual_artifact["artifact_id"]]
    assert receipt["artifact_count"] == 1
    assert receipt["image_recognition_used"] is True
    assert receipt["external_framework_required"] is False
    assert receipt["active_memory_write_performed"] is False
    assert receipt["promotion_required"] is True
    assert receipt["promotion_guidance"]["default_action"] == "review_before_promotion"

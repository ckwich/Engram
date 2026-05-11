from __future__ import annotations

import pytest

from core.document_intelligence import (
    prepare_document_record,
    prepare_document_draft,
    prepare_extractor_receipt,
    prepare_visual_extraction_request,
    prepare_visual_artifact_record,
    preview_document_extraction,
    preview_visual_extraction,
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


def test_prepare_visual_extraction_request_marks_external_framework_work_as_reviewable():
    document = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "e" * 64,
        media_type="application/pdf",
    )

    request = prepare_visual_extraction_request(
        document_record=document,
        image_refs=[
            {
                "source_uri": "file:///docs/architecture.pdf",
                "page": 7,
                "image_hash": "sha256:" + "f" * 64,
            }
        ],
        requested_capabilities=["ocr_text", "diagram_description"],
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
        instructions="Extract visible labels and describe the architecture diagram.",
    )
    duplicate = prepare_visual_extraction_request(
        document_record=document,
        image_refs=[
            {
                "source_uri": "file:///docs/architecture.pdf",
                "page": 7,
                "image_hash": "sha256:" + "f" * 64,
            }
        ],
        requested_capabilities=["diagram_description", "ocr_text"],
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
        instructions="Extract visible labels and describe the architecture diagram.",
    )

    assert duplicate["request_id"] == request["request_id"]
    assert request["schema_version"] == "2026-05-11.document-intelligence.visual-request.v1"
    assert request["record_type"] == "visual_extraction_request"
    assert request["document_id"] == document["document_id"]
    assert request["extractor"] == {
        "id": "local-vision-v1",
        "kind": "ocr_vision",
        "external_framework_required": True,
    }
    assert request["requested_capabilities"] == ["diagram_description", "ocr_text"]
    assert request["image_recognition_required"] is True
    assert request["active_memory_write_performed"] is False
    assert request["promotion_required"] is True
    assert "artifact_type" in request["expected_observation_fields"]


def test_prepare_visual_extraction_request_validates_images_and_capabilities():
    document = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "e" * 64,
        media_type="application/pdf",
    )

    with pytest.raises(ValueError, match="image_refs must include at least one item"):
        prepare_visual_extraction_request(
            document_record=document,
            image_refs=[],
            requested_capabilities=["ocr_text"],
            extractor_id="local-vision-v1",
            extractor_kind="ocr",
        )

    with pytest.raises(ValueError, match="Unsupported visual capability"):
        prepare_visual_extraction_request(
            document_record=document,
            image_refs=[{"source_uri": "file:///docs/architecture.pdf", "page": 1}],
            requested_capabilities=["read_minds"],
            extractor_id="local-vision-v1",
            extractor_kind="ocr",
        )


def test_prepare_document_draft_turns_evidence_into_reviewable_proposals_without_writes():
    preview = preview_document_extraction(
        title="Architecture Note",
        source_uri="file:///docs/architecture.md",
        source_type="markdown",
        content="# Architecture\n\nDecision: Keep review-first document import.",
        media_type="text/markdown",
        metadata={"project": "Engram", "domain": "memory-os"},
    )
    artifact = prepare_visual_artifact_record(
        document_id=preview["document_record"]["document_id"],
        artifact_type="diagram",
        source_ref={"source_uri": "file:///docs/architecture.md", "page": 1},
        extractor_id="agent-vision",
        extractor_kind="agent_native",
        description="A diagram linking document evidence to reviewed memories.",
        page_number=1,
        confidence=0.88,
    )

    draft = prepare_document_draft(
        document_record=preview["document_record"],
        analysis={
            "summary": "Architecture note about document import.",
            "decisions": ["Keep document imports review-first."],
            "claims": ["Visual evidence stays evidence until promotion."],
        },
        chunk_refs=[preview["chunks"][0]["provenance"]],
        visual_artifacts=[artifact],
        candidate_graph_edges=[
            {
                "from_ref": {"kind": "document", "key": preview["document_record"]["document_id"]},
                "to_ref": {"kind": "memory", "key": "engram_document_intelligence"},
                "edge_type": "supports",
                "confidence": 0.7,
                "evidence": "The architecture note supports document intelligence planning.",
            }
        ],
        created_by="agent",
    )
    duplicate = prepare_document_draft(
        document_record=preview["document_record"],
        analysis={
            "summary": ["Architecture note about document import."],
            "claims": ["Visual evidence stays evidence until promotion."],
            "decisions": ["Keep document imports review-first."],
        },
        chunk_refs=[preview["chunks"][0]["provenance"]],
        visual_artifacts=[artifact],
        candidate_graph_edges=[
            {
                "from_ref": {"kind": "document", "key": preview["document_record"]["document_id"]},
                "to_ref": {"kind": "memory", "key": "engram_document_intelligence"},
                "edge_type": "supports",
                "confidence": 0.7,
                "evidence": "The architecture note supports document intelligence planning.",
            }
        ],
        created_by="agent",
    )

    assert duplicate["draft_id"] == draft["draft_id"]
    assert draft["schema_version"] == "2026-05-11.document-intelligence.draft.v1"
    assert draft["record_type"] == "document_draft"
    assert draft["status"] == "draft"
    assert draft["active_memory_write_performed"] is False
    assert draft["review_required"] is True
    assert draft["promotion_guidance"]["auto_promote"] is False
    assert draft["evidence_refs"]["visual_artifact_ids"] == [artifact["artifact_id"]]
    assert draft["evidence_refs"]["chunk_refs"] == [preview["chunks"][0]["provenance"]]
    assert draft["analysis"]["summary"] == ["Architecture note about document import."]
    assert draft["proposed_memories"][0]["status"] == "draft"
    assert "## Decisions" in draft["proposed_memories"][0]["content"]
    assert draft["proposed_edges"][0]["review_status"] == "draft"
    assert draft["receipt"] == {
        "analysis_item_count": 3,
        "chunk_ref_count": 1,
        "visual_artifact_count": 1,
        "proposed_memory_count": 1,
        "proposed_edge_count": 1,
    }


def test_prepare_document_draft_validates_reviewable_evidence_boundary():
    document = prepare_document_record(
        title="Architecture Note",
        source_uri="file:///docs/architecture.md",
        source_type="markdown",
        content_hash="sha256:" + "c" * 64,
        media_type="text/markdown",
    )
    other_artifact = prepare_visual_artifact_record(
        document_id="doc_other",
        artifact_type="diagram",
        source_ref={"source_uri": "file:///docs/other.md"},
        extractor_id="agent-vision",
        extractor_kind="agent_native",
        description="Other doc.",
    )

    with pytest.raises(ValueError, match="analysis or candidate_graph_edges must include at least one item"):
        prepare_document_draft(document_record=document, analysis={})

    with pytest.raises(ValueError, match="visual_artifact document_id does not match document_record.document_id"):
        prepare_document_draft(
            document_record=document,
            analysis={"claims": ["Claim"]},
            visual_artifacts=[other_artifact],
        )


def test_preview_document_extraction_returns_no_write_chunks_and_receipt_for_markdown():
    content = "# Memory OS\n\nAgent memory substrate.\n\n## Retrieval\n\nChunk before full memory."
    preview = preview_document_extraction(
        title="Memory OS Notes",
        source_uri="file:///docs/memory-os.md",
        source_type="markdown",
        content=content,
        media_type="text/markdown",
        metadata={"project": "Engram"},
    )

    assert preview["schema_version"] == "2026-05-11.document-intelligence.preview.v1"
    assert preview["write_performed"] is False
    assert preview["active_memory_write_performed"] is False
    assert preview["review_required"] is True
    assert preview["document_record"]["record_type"] == "document"
    assert preview["document_record"]["metadata"] == {"project": "Engram"}
    assert preview["extractor_receipt"]["image_recognition_used"] is False
    assert preview["extractor_receipt"]["external_framework_required"] is False
    assert preview["receipt"] == {
        "input_chars": len(content),
        "chunk_count": 2,
        "visual_artifact_count": 0,
        "extractor_kind": "agent_native",
    }
    assert [
        {
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
            "heading_path": chunk["heading_path"],
            "provenance": chunk["provenance"],
        }
        for chunk in preview["chunks"]
    ] == [
        {
            "chunk_id": 0,
            "text": "# Memory OS\n\nAgent memory substrate.",
            "heading_path": ["Memory OS"],
            "provenance": {
                "document_id": preview["document_record"]["document_id"],
                "source_uri": "file:///docs/memory-os.md",
                "chunk_id": 0,
            },
        },
        {
            "chunk_id": 1,
            "text": "## Retrieval\n\nChunk before full memory.",
            "heading_path": ["Memory OS", "Retrieval"],
            "provenance": {
                "document_id": preview["document_record"]["document_id"],
                "source_uri": "file:///docs/memory-os.md",
                "chunk_id": 1,
            },
        },
    ]


def test_preview_document_extraction_rejects_blank_content():
    with pytest.raises(ValueError, match="content is required"):
        preview_document_extraction(
            title="Blank",
            source_uri="file:///blank.txt",
            source_type="plain_text",
            content="   ",
            media_type="text/plain",
        )


def test_preview_visual_extraction_normalizes_caller_supplied_ocr_vision_observations():
    document = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "c" * 64,
        media_type="application/pdf",
    )

    preview = preview_visual_extraction(
        document_record=document,
        observations=[
            {
                "artifact_type": "diagram",
                "source_ref": {
                    "source_uri": "file:///docs/architecture.pdf",
                    "page": 4,
                    "image_hash": "sha256:" + "d" * 64,
                },
                "text": "Graph store",
                "description": "A graph store diagram with entity and claim nodes.",
                "page_number": 4,
                "bounding_box": {"x": 0.2, "y": 0.25, "width": 0.4, "height": 0.3},
                "confidence": 0.74,
            }
        ],
        extractor_id="local-vision-v1",
        extractor_kind="ocr_vision",
    )

    assert preview["schema_version"] == "2026-05-11.document-intelligence.visual-preview.v1"
    assert preview["write_performed"] is False
    assert preview["active_memory_write_performed"] is False
    assert preview["review_required"] is True
    assert preview["document_id"] == document["document_id"]
    assert preview["receipt"] == {
        "observation_count": 1,
        "visual_artifact_count": 1,
        "extractor_kind": "ocr_vision",
        "external_framework_required": True,
    }
    assert len(preview["visual_artifacts"]) == 1
    artifact = preview["visual_artifacts"][0]
    assert artifact["document_id"] == document["document_id"]
    assert artifact["artifact_type"] == "diagram"
    assert artifact["extractor"]["external_framework_required"] is True
    assert artifact["trusted_memory"] is False
    assert preview["extractor_receipt"]["visual_artifact_ids"] == [artifact["artifact_id"]]
    assert preview["extractor_receipt"]["image_recognition_used"] is True
    assert preview["extractor_receipt"]["external_framework_required"] is True


def test_preview_visual_extraction_requires_observations():
    document = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture.pdf",
        source_type="pdf",
        content_hash="sha256:" + "c" * 64,
        media_type="application/pdf",
    )

    with pytest.raises(ValueError, match="observations must include at least one item"):
        preview_visual_extraction(
            document_record=document,
            observations=[],
            extractor_id="agent",
            extractor_kind="agent_native",
        )

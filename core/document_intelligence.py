"""No-write document intelligence primitives for the Engram Memory OS rebuild."""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import unquote, urlparse

from core.chunker import chunk_content_with_metadata
from core.graph_manager import normalize_graph_edge_proposal


DOCUMENT_INTELLIGENCE_SCHEMA_VERSION = "2026-05-11.document-intelligence.v1"
DOCUMENT_EXTRACTOR_CATALOG_SCHEMA_VERSION = "2026-05-11.document-intelligence.extractors.v1"
DOCUMENT_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.preview.v1"
VISUAL_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.visual-preview.v1"
VISUAL_REQUEST_SCHEMA_VERSION = "2026-05-11.document-intelligence.visual-request.v1"
DOCUMENT_EXTRACTION_REQUEST_SCHEMA_VERSION = "2026-05-11.document-intelligence.extraction-request.v1"
DOCUMENT_EXTRACTION_RESULT_SCHEMA_VERSION = "2026-05-11.document-intelligence.extraction-result.v1"
DOCUMENT_DRAFT_SCHEMA_VERSION = "2026-05-11.document-intelligence.draft.v1"
DOCUMENT_UNDERSTANDING_SCHEMA_VERSION = "2026-05-12.document-intelligence.understanding.v1"
DOCUMENT_PROMOTION_SCHEMA_VERSION = "2026-05-11.document-intelligence.promotion.v1"
LOW_CONFIDENCE_THRESHOLD = 0.5
AUTO_GRAPH_SOURCE = "document_intelligence.auto_graph"
VALID_EXTRACTOR_KINDS = {"agent_native", "ocr", "vision", "ocr_vision"}
VALID_DOCUMENT_EXTRACTOR_KINDS = {
    "agent_native",
    "docx",
    "external_document",
    "html",
    "ocr",
    "ocr_document",
    "ocr_vision",
    "pdf",
    "vision",
}
VALID_DOCUMENT_OUTPUTS = {
    "figures",
    "html",
    "markdown",
    "metadata",
    "page_images",
    "plain_text",
    "tables",
    "visual_artifacts",
}
VISUAL_DOCUMENT_OUTPUTS = {"figures", "page_images", "tables", "visual_artifacts"}
VISUAL_SOURCE_TYPES = {"image", "image_folder", "pdf", "scan", "screenshot"}
DOCUMENT_ANALYSIS_SECTIONS = {
    "summary": "Summary",
    "decisions": "Decisions",
    "claims": "Claims",
    "entities": "Entities",
    "constraints": "Constraints",
    "tasks": "Tasks",
    "risks": "Risks",
    "dates": "Dates",
    "open_questions": "Open Questions",
    "external_pointers": "External Pointers",
}
DOCUMENT_UNDERSTANDING_ANALYSIS_FIELDS = {
    "summary",
    "claims",
    "concepts",
    "entities",
    "high_value_sections",
    "warnings",
}
VALID_VISUAL_CAPABILITIES = {
    "caption_alt_text",
    "chart_summary",
    "diagram_description",
    "figure_description",
    "ocr_text",
    "screenshot_state",
    "table_structure",
}
PROMOTION_GUIDANCE = {
    "default_action": "review_before_promotion",
    "auto_promote": False,
    "allowed_destinations": ["memory", "graph_edge", "document_store", "external_pointer"],
}
EXPECTED_VISUAL_OBSERVATION_FIELDS = [
    "artifact_type",
    "source_ref",
    "source_artifact_id",
    "text",
    "description",
    "page_number",
    "bounding_box",
    "coordinates",
    "confidence",
    "metadata",
]
EXPECTED_DOCUMENT_EXTRACTION_FIELDS = [
    "title",
    "source_uri",
    "source_type",
    "content",
    "media_type",
    "content_hash",
    "metadata",
    "image_refs",
]


def list_document_extractors() -> dict[str, Any]:
    """List provider-neutral document extraction capabilities without running providers."""
    return {
        "schema_version": DOCUMENT_EXTRACTOR_CATALOG_SCHEMA_VERSION,
        "write_policy": "read_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "extractors": [
            {
                "id": "engram-text-preview",
                "kind": "agent_native",
                "label": "Bundled text/markup preview",
                "source_types": ["html", "markdown", "text"],
                "requested_outputs": ["markdown", "metadata", "chunks"],
                "runs_inside_engram": True,
                "external_framework_required": False,
                "next_tools": ["preview_document_extraction"],
            },
            {
                "id": "engram-local-pdf-disassembly",
                "kind": "pdf",
                "label": "Bundled local PDF inventory and text extraction",
                "source_types": ["pdf"],
                "requested_outputs": ["metadata", "plain_text", "image_inventory"],
                "runs_inside_engram": True,
                "external_framework_required": False,
                "required_tools": ["pdfinfo", "pdftotext", "pdfimages"],
                "next_tools": [
                    "prepare_document_disassembly",
                    "preview_document_extraction",
                    "prepare_visual_extraction_request",
                ],
            },
            {
                "id": "external-document-parser",
                "kind": "external_document",
                "label": "External PDF/DOCX parser",
                "source_types": ["docx", "pdf", "url"],
                "requested_outputs": ["markdown", "metadata", "page_images"],
                "runs_inside_engram": False,
                "external_framework_required": True,
                "next_tools": [
                    "prepare_document_extraction_request",
                    "prepare_document_extraction_result",
                    "preview_document_extraction",
                ],
            },
            {
                "id": "external-ocr-vision",
                "kind": "ocr_vision",
                "label": "External OCR/vision analyzer",
                "source_types": ["image", "pdf", "scan", "screenshot"],
                "requested_outputs": ["visual_artifacts"],
                "requested_capabilities": sorted(VALID_VISUAL_CAPABILITIES),
                "runs_inside_engram": False,
                "external_framework_required": True,
                "next_tools": [
                    "prepare_visual_extraction_request",
                    "preview_visual_extraction",
                ],
            },
        ],
    }


def prepare_document_record(
    *,
    title: str,
    source_uri: str,
    source_type: str,
    content_hash: str,
    media_type: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare a reviewable source document evidence record without writing it."""
    normalized_title = _require_text(title, "title")
    normalized_source_uri = _require_text(source_uri, "source_uri")
    normalized_source_type = _require_text(source_type, "source_type")
    normalized_content_hash = _require_hash(content_hash, "content_hash")
    normalized_media_type = _require_text(media_type, "media_type")
    normalized_metadata = dict(metadata or {})
    return {
        "schema_version": DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
        "record_type": "document",
        "document_id": _document_id(
            title=normalized_title,
            source_uri=normalized_source_uri,
            metadata=normalized_metadata,
        ),
        "title": normalized_title,
        "source_uri": normalized_source_uri,
        "source_type": normalized_source_type,
        "content_hash": normalized_content_hash,
        "media_type": normalized_media_type,
        "metadata": normalized_metadata,
        "review_status": "evidence",
        "write_policy": "draft_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "promotion_required": True,
    }


def prepare_visual_artifact_record(
    *,
    document_id: str,
    artifact_type: str,
    source_ref: dict[str, Any],
    extractor_id: str,
    extractor_kind: str,
    text: str | None = None,
    description: str | None = None,
    page_number: int | None = None,
    bounding_box: dict[str, float] | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare reviewable visual/OCR evidence without promoting memory."""
    normalized_document_id = _require_text(document_id, "document_id")
    normalized_artifact_type = _require_text(artifact_type, "artifact_type")
    normalized_source_ref = _normalize_source_ref(source_ref)
    normalized_extractor_id = _require_text(extractor_id, "extractor_id")
    normalized_extractor_kind = _normalize_extractor_kind(extractor_kind)
    normalized_text = _optional_text(text, "text")
    normalized_description = _optional_text(description, "description")
    normalized_page = _optional_positive_int(page_number, "page_number")
    normalized_box = _normalize_bounding_box(bounding_box)
    normalized_confidence = _normalize_confidence(confidence)
    normalized_source_artifact_id = _source_artifact_id_from_ref(normalized_source_ref)

    artifact_seed = "|".join(
        [
            normalized_document_id,
            normalized_artifact_type,
            normalized_extractor_id,
            normalized_extractor_kind,
            _stable_repr(normalized_source_ref),
            str(normalized_page),
            _stable_repr(normalized_box),
            normalized_text or "",
            normalized_description or "",
        ]
    )
    return {
        "schema_version": DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
        "record_type": "visual_artifact",
        "artifact_id": _readable_stable_id(
            "vis",
            artifact_seed,
            normalized_document_id,
            normalized_artifact_type,
            normalized_extractor_id,
        ),
        "document_id": normalized_document_id,
        "artifact_type": normalized_artifact_type,
        "text": normalized_text,
        "description": normalized_description,
        "confidence": normalized_confidence,
        "extractor": {
            "id": normalized_extractor_id,
            "kind": normalized_extractor_kind,
            "external_framework_required": normalized_extractor_kind != "agent_native",
        },
        "provenance": {
            "source_ref": normalized_source_ref,
            "source_artifact_id": normalized_source_artifact_id,
            "page_number": normalized_page,
            "bounding_box": normalized_box,
            "coordinates": normalized_box,
        },
        "metadata": dict(metadata or {}),
        "review_status": "evidence",
        "trusted_memory": False,
        "write_policy": "draft_only",
        "write_performed": False,
        "promotion_required": True,
        "active_memory_write_performed": False,
    }


def prepare_extractor_receipt(
    *,
    document_record: dict[str, Any],
    visual_artifacts: list[dict[str, Any]] | None = None,
    extractor_id: str,
    extractor_kind: str,
) -> dict[str, Any]:
    """Prepare an extraction receipt linking document and visual evidence."""
    document_id = _require_text(document_record.get("document_id"), "document_record.document_id")
    normalized_extractor_id = _require_text(extractor_id, "extractor_id")
    normalized_extractor_kind = _normalize_extractor_kind(extractor_kind)
    artifacts = list(visual_artifacts or [])
    artifact_ids = [_require_text(item.get("artifact_id"), "visual_artifact.artifact_id") for item in artifacts]
    external_required = normalized_extractor_kind != "agent_native" or any(
        item.get("extractor", {}).get("external_framework_required") for item in artifacts
    )
    receipt_seed = "|".join(
        [document_id, normalized_extractor_id, normalized_extractor_kind, *artifact_ids]
    )
    return {
        "schema_version": DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
        "record_type": "extractor_receipt",
        "receipt_id": _readable_stable_id("doc_extract", receipt_seed, document_id, normalized_extractor_id),
        "document_id": document_id,
        "extractor": {
            "id": normalized_extractor_id,
            "kind": normalized_extractor_kind,
        },
        "visual_artifact_ids": artifact_ids,
        "artifact_count": len(artifact_ids),
        "image_recognition_used": bool(artifact_ids),
        "external_framework_required": bool(external_required),
        "active_memory_write_performed": False,
        "promotion_required": True,
        "promotion_guidance": dict(PROMOTION_GUIDANCE),
    }


def prepare_visual_extraction_request(
    *,
    document_record: dict[str, Any],
    image_refs: list[dict[str, Any]],
    requested_capabilities: list[str],
    extractor_id: str,
    extractor_kind: str,
    instructions: str | None = None,
) -> dict[str, Any]:
    """Prepare a reviewable OCR/vision work request without running an extractor."""
    document_id = _require_text(document_record.get("document_id"), "document_record.document_id")
    normalized_images = _normalize_image_refs(image_refs)
    normalized_capabilities = _normalize_visual_capabilities(requested_capabilities)
    normalized_extractor_id = _require_text(extractor_id, "extractor_id")
    normalized_extractor_kind = _normalize_extractor_kind(extractor_kind)
    normalized_instructions = _optional_text(instructions, "instructions")
    external_framework_required = normalized_extractor_kind != "agent_native"
    request_seed = "|".join(
        [
            document_id,
            _stable_repr(normalized_images),
            _stable_repr(normalized_capabilities),
            normalized_extractor_id,
            normalized_extractor_kind,
            normalized_instructions or "",
        ]
    )
    return {
        "schema_version": VISUAL_REQUEST_SCHEMA_VERSION,
        "record_type": "visual_extraction_request",
        "request_id": _readable_stable_id("vis_req", request_seed, document_id, normalized_extractor_id),
        "document_id": document_id,
        "image_refs": normalized_images,
        "requested_capabilities": normalized_capabilities,
        "instructions": normalized_instructions,
        "extractor": {
            "id": normalized_extractor_id,
            "kind": normalized_extractor_kind,
            "external_framework_required": external_framework_required,
        },
        "image_recognition_required": True,
        "visual_interpretation_required": True,
        "coverage_required": True,
        "expected_observation_fields": list(EXPECTED_VISUAL_OBSERVATION_FIELDS),
        "visual_evidence_contract": _visual_evidence_contract(),
        "framework_strategy": _visual_framework_strategy(external_framework_required),
        "review_status": "request",
        "active_memory_write_performed": False,
        "promotion_required": True,
        "promotion_guidance": dict(PROMOTION_GUIDANCE),
    }


def prepare_document_extraction_request(
    *,
    source_ref: dict[str, Any],
    source_type: str,
    requested_outputs: list[str],
    extractor_id: str,
    extractor_kind: str,
    instructions: str | None = None,
) -> dict[str, Any]:
    """Prepare a reviewable external document extraction request without running a provider."""
    normalized_source_ref = _normalize_source_ref(source_ref)
    normalized_source_type = _require_text(source_type, "source_type")
    normalized_outputs = _normalize_document_outputs(requested_outputs)
    normalized_extractor_id = _require_text(extractor_id, "extractor_id")
    normalized_extractor_kind = _normalize_document_extractor_kind(extractor_kind)
    normalized_instructions = _optional_text(instructions, "instructions")
    request_seed = "|".join(
        [
            _stable_repr(normalized_source_ref),
            normalized_source_type,
            _stable_repr(normalized_outputs),
            normalized_extractor_id,
            normalized_extractor_kind,
            normalized_instructions or "",
        ]
    )
    image_recognition = (
        normalized_source_type in VISUAL_SOURCE_TYPES
        or bool(set(normalized_outputs) & VISUAL_DOCUMENT_OUTPUTS)
        or normalized_extractor_kind in {"ocr", "ocr_document", "ocr_vision", "vision"}
    )
    return {
        "schema_version": DOCUMENT_EXTRACTION_REQUEST_SCHEMA_VERSION,
        "record_type": "document_extraction_request",
        "request_id": _readable_stable_id(
            "doc_req",
            request_seed,
            _source_ref_label(normalized_source_ref),
            normalized_source_type,
            normalized_extractor_id,
        ),
        "source_ref": normalized_source_ref,
        "source_type": normalized_source_type,
        "requested_outputs": normalized_outputs,
        "instructions": normalized_instructions,
        "extractor": {
            "id": normalized_extractor_id,
            "kind": normalized_extractor_kind,
            "external_framework_required": normalized_extractor_kind != "agent_native",
        },
        "external_framework_required": normalized_extractor_kind != "agent_native",
        "image_recognition_may_be_required": image_recognition,
        "expected_extraction_fields": list(EXPECTED_DOCUMENT_EXTRACTION_FIELDS),
        "review_status": "request",
        "write_performed": False,
        "active_memory_write_performed": False,
        "promotion_required": True,
        "promotion_guidance": {
            "default_action": "run_external_extractor_then_preview",
            "auto_promote": False,
            "next_tools": [
                "preview_document_extraction",
                "preview_visual_extraction",
                "prepare_document_draft",
            ],
        },
    }


def prepare_document_extraction_result(
    *,
    extraction_request: dict[str, Any],
    title: str,
    content: str,
    media_type: str,
    metadata: dict[str, Any] | None = None,
    image_refs: list[dict[str, Any]] | None = None,
    requested_visual_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Prepare a reviewable external parser result without writing memory."""
    if not isinstance(extraction_request, dict):
        raise ValueError("extraction_request must be an object")
    request_id = _require_text(extraction_request.get("request_id"), "extraction_request.request_id")
    source_ref = _normalize_source_ref(extraction_request.get("source_ref"))
    source_uri = _require_text(source_ref.get("source_uri"), "extraction_request.source_ref.source_uri")
    source_type = _require_text(extraction_request.get("source_type"), "extraction_request.source_type")
    normalized_title = _require_text(title, "title")
    normalized_content = _require_text(content, "content")
    normalized_media_type = _require_text(media_type, "media_type")
    normalized_metadata = _normalize_metadata(metadata)
    normalized_metadata["extraction_request_id"] = request_id
    normalized_images = _normalize_optional_source_refs(image_refs)
    normalized_visual_capabilities = (
        _normalize_visual_capabilities(requested_visual_capabilities)
        if requested_visual_capabilities is not None
        else []
    )
    content_hash = "sha256:" + hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    document_record = prepare_document_record(
        title=normalized_title,
        source_uri=source_uri,
        source_type=source_type,
        content_hash=content_hash,
        media_type=normalized_media_type,
        metadata=normalized_metadata,
    )
    result_seed = "|".join(
        [
            request_id,
            document_record["document_id"],
            content_hash,
            _stable_repr(normalized_images),
        ]
    )
    requires_visual_review = bool(normalized_images) or _normalize_bool(
        extraction_request.get("image_recognition_may_be_required")
    )
    visual_request_arguments = None
    if normalized_images and normalized_visual_capabilities:
        visual_request_arguments = {
            "document_record": document_record,
            "image_refs": normalized_images,
            "requested_capabilities": normalized_visual_capabilities,
            "extractor_id": "engram-visual-request",
            "extractor_kind": "ocr_vision",
            "instructions": "Review image-derived text, diagrams, tables, or figures before any memory promotion.",
        }

    return {
        "schema_version": DOCUMENT_EXTRACTION_RESULT_SCHEMA_VERSION,
        "record_type": "document_extraction_result",
        "result_id": _readable_stable_id(
            "doc_result",
            result_seed,
            document_record["document_id"],
            _source_ref_label(source_ref),
        ),
        "request_id": request_id,
        "source_ref": source_ref,
        "source_type": source_type,
        "requested_outputs": list(extraction_request.get("requested_outputs") or []),
        "extractor": dict(extraction_request.get("extractor") or {}),
        "document_record": document_record,
        "content_hash": content_hash,
        "image_refs": normalized_images,
        "requires_visual_review": requires_visual_review,
        "visual_extraction_request_arguments": visual_request_arguments,
        "document_extraction_arguments": {
            "title": normalized_title,
            "source_uri": source_uri,
            "source_type": source_type,
            "content": normalized_content,
            "media_type": normalized_media_type,
            "metadata": normalized_metadata,
        },
        "review_status": "evidence",
        "write_performed": False,
        "active_memory_write_performed": False,
        "promotion_required": True,
        "promotion_guidance": {
            "default_action": "preview_before_draft",
            "auto_promote": False,
            "next_tools": [
                "preview_document_extraction",
                "prepare_visual_extraction_request",
                "preview_visual_extraction",
                "prepare_document_draft",
            ],
        },
    }


def prepare_document_draft(
    *,
    document_record: dict[str, Any],
    analysis: dict[str, Any],
    chunk_refs: list[dict[str, Any]] | None = None,
    visual_artifacts: list[dict[str, Any]] | None = None,
    candidate_graph_edges: list[dict[str, Any]] | None = None,
    created_by: str = "agent",
) -> dict[str, Any]:
    """Prepare a no-write document draft from reviewed document evidence."""
    document_id = _require_text(document_record.get("document_id"), "document_record.document_id")
    title = _require_text(document_record.get("title", document_id), "document_record.title")
    normalized_analysis = _normalize_document_analysis(analysis)
    normalized_chunk_refs = _normalize_chunk_refs(chunk_refs or [])
    normalized_visuals = _normalize_visual_artifacts(visual_artifacts or [], document_id)
    normalized_edges = _normalize_candidate_graph_edges(candidate_graph_edges or [])
    normalized_created_by = _require_text(created_by, "created_by")
    if _analysis_item_count(normalized_analysis) == 0 and not normalized_edges:
        raise ValueError("analysis or candidate_graph_edges must include at least one item")

    visual_artifact_ids = [
        _require_text(artifact.get("artifact_id"), "visual_artifact.artifact_id")
        for artifact in normalized_visuals
    ]
    draft_seed = "|".join(
        [
            document_id,
            _stable_repr(normalized_analysis),
            _stable_repr(normalized_chunk_refs),
            _stable_repr(visual_artifact_ids),
            _stable_repr(normalized_edges),
            normalized_created_by,
        ]
    )
    draft_id = _readable_stable_id("doc_draft", draft_seed, document_id, normalized_created_by)
    content = _analysis_markdown(title, normalized_analysis)
    metadata = document_record.get("metadata") if isinstance(document_record.get("metadata"), dict) else {}
    source_type = _optional_text(document_record.get("source_type"), "document_record.source_type")
    tags = ["document-intelligence"]
    if source_type:
        tags.append(source_type)
    proposed_memory = {
        "key": _readable_stable_id("doc_mem", draft_seed, document_id, title),
        "title": f"Document Draft: {title}",
        "content": content,
        "tags": tags,
        "project": metadata.get("project"),
        "domain": metadata.get("domain"),
        "status": "draft",
        "canonical": False,
        "source_document": {
            "document_id": document_id,
            "draft_id": draft_id,
            "source_uri": document_record.get("source_uri"),
            "review_status": "draft",
            "promotion_required": True,
        },
    }
    proposed_edges = [
        {
            **edge,
            "review_status": "draft",
            "promotion_required": True,
            "active_memory_write_performed": False,
        }
        for edge in normalized_edges
    ]
    return {
        "schema_version": DOCUMENT_DRAFT_SCHEMA_VERSION,
        "record_type": "document_draft",
        "draft_id": draft_id,
        "document_id": document_id,
        "status": "draft",
        "created_by": normalized_created_by,
        "write_policy": "draft_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "review_required": True,
        "promotion_required": True,
        "promotion_guidance": dict(PROMOTION_GUIDANCE),
        "analysis": normalized_analysis,
        "evidence_refs": {
            "document_id": document_id,
            "source_uri": document_record.get("source_uri"),
            "chunk_refs": normalized_chunk_refs,
            "visual_artifact_ids": visual_artifact_ids,
        },
        "proposed_memories": [proposed_memory],
        "proposed_edges": proposed_edges,
        "receipt": {
            "analysis_item_count": _analysis_item_count(normalized_analysis),
            "chunk_ref_count": len(normalized_chunk_refs),
            "visual_artifact_count": len(normalized_visuals),
            "proposed_memory_count": 1,
            "proposed_edge_count": len(proposed_edges),
        },
    }


def prepare_document_understanding_packet(
    *,
    document_record: dict[str, Any],
    analysis: dict[str, Any],
    chunk_refs: list[dict[str, Any]] | None = None,
    visual_artifacts: list[dict[str, Any]] | None = None,
    candidate_graph_edges: list[dict[str, Any]] | None = None,
    created_by: str = "agent",
) -> dict[str, Any]:
    """Normalize agent-supplied document understanding into reviewable evidence."""
    document_id = _require_text(document_record.get("document_id"), "document_record.document_id")
    normalized_created_by = _require_text(created_by, "created_by")
    normalized_chunk_refs = _normalize_chunk_refs(chunk_refs or [])
    normalized_visuals = _normalize_visual_artifacts(visual_artifacts or [], document_id)
    supplied_edges = _normalize_candidate_graph_edges(candidate_graph_edges or [])
    normalized = _normalize_understanding_analysis(analysis, document_id)
    auto_edges = _auto_document_understanding_edges(
        document_id=document_id,
        normalized=normalized,
        chunk_refs=normalized_chunk_refs,
        visual_artifacts=normalized_visuals,
    )
    normalized_edges = _dedupe_graph_edges([*supplied_edges, *auto_edges])
    if _understanding_item_count(normalized) == 0 and not normalized_edges:
        raise ValueError("analysis or candidate_graph_edges must include at least one item")

    visual_artifact_ids = [
        _require_text(artifact.get("artifact_id"), "visual_artifact.artifact_id")
        for artifact in normalized_visuals
    ]
    low_confidence_warnings = _understanding_low_confidence_warnings(normalized, normalized_visuals)
    draft_analysis = _understanding_draft_analysis(normalized)
    document_draft = None
    if _analysis_item_count(_normalize_document_analysis(draft_analysis)) > 0 or normalized_edges:
        document_draft = prepare_document_draft(
            document_record=document_record,
            analysis=draft_analysis,
            chunk_refs=normalized_chunk_refs,
            visual_artifacts=normalized_visuals,
            candidate_graph_edges=normalized_edges,
            created_by=normalized_created_by,
        )

    packet_seed = "|".join(
        [
            document_id,
            _stable_repr(normalized),
            _stable_repr(normalized_chunk_refs),
            _stable_repr(visual_artifact_ids),
            _stable_repr(normalized_edges),
            normalized_created_by,
        ]
    )
    return {
        "schema_version": DOCUMENT_UNDERSTANDING_SCHEMA_VERSION,
        "record_type": "document_understanding_packet",
        "packet_id": _readable_stable_id("doc_packet", packet_seed, document_id, normalized_created_by),
        "document_id": document_id,
        "created_by": normalized_created_by,
        "review_status": "packet",
        "write_performed": False,
        "active_memory_write_performed": False,
        "promotion_required": True,
        "promotion_guidance": dict(PROMOTION_GUIDANCE),
        "summary_slots": normalized["summary_slots"],
        "claim_candidates": normalized["claim_candidates"],
        "concept_candidates": normalized["concept_candidates"],
        "entity_candidates": normalized["entity_candidates"],
        "high_value_sections": normalized["high_value_sections"],
        "low_confidence_warnings": low_confidence_warnings,
        "candidate_graph_edges": normalized_edges,
        "evidence_refs": {
            "document_id": document_id,
            "source_uri": document_record.get("source_uri"),
            "chunk_refs": normalized_chunk_refs,
            "visual_artifact_ids": visual_artifact_ids,
        },
        "document_draft": document_draft,
        "receipt": {
            "summary_slot_count": len(normalized["summary_slots"]),
            "claim_candidate_count": len(normalized["claim_candidates"]),
            "concept_candidate_count": len(normalized["concept_candidates"]),
            "entity_candidate_count": len(normalized["entity_candidates"]),
            "high_value_section_count": len(normalized["high_value_sections"]),
            "low_confidence_warning_count": len(low_confidence_warnings),
            "candidate_graph_edge_count": len(normalized_edges),
            "supplied_graph_edge_count": len(supplied_edges),
            "auto_graph_edge_count": len(auto_edges),
            "chunk_ref_count": len(normalized_chunk_refs),
            "visual_artifact_count": len(normalized_visuals),
        },
    }


def prepare_document_promotion_transaction(
    *,
    document_draft: dict[str, Any],
    approved_by: str,
    selected_memory_indexes: list[int] | None = None,
    selected_edge_indexes: list[int] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Prepare a no-write transaction plan for promoting reviewed document drafts."""
    normalized_approved_by = _require_text(approved_by, "approved_by")
    if not isinstance(document_draft, dict):
        raise ValueError("document_draft must be an object")
    if _normalize_bool(document_draft.get("active_memory_write_performed")):
        raise ValueError("document_draft must not already be an active memory write")

    draft_id = _require_text(document_draft.get("draft_id"), "document_draft.draft_id")
    document_id = _optional_text(document_draft.get("document_id"), "document_draft.document_id")
    proposed_memories = _normalize_proposed_items(document_draft.get("proposed_memories", []), "proposed_memories")
    proposed_edges = _normalize_proposed_items(document_draft.get("proposed_edges", []), "proposed_edges")
    memory_indexes = _normalize_selected_indexes(
        selected_memory_indexes,
        len(proposed_memories),
        "memory",
    )
    edge_indexes = _normalize_selected_indexes(
        selected_edge_indexes,
        len(proposed_edges),
        "edge",
    )
    if not memory_indexes and not edge_indexes:
        raise ValueError("at least one memory or graph edge must be selected")

    operations: list[dict[str, Any]] = []
    for index in memory_indexes:
        operations.append(
            {
                "kind": "memory",
                "tool": "write_memory",
                "source_index": index,
                "target_status": "active",
                "payload": _promoted_memory_payload(proposed_memories[index]),
            }
        )
    for index in edge_indexes:
        operations.append(
            {
                "kind": "graph_edge",
                "tool": "add_graph_edge",
                "source_index": index,
                "target_status": "active",
                "payload": _promoted_graph_edge_payload(proposed_edges[index], normalized_approved_by),
            }
        )

    transaction_seed = "|".join(
        [
            draft_id,
            _stable_repr(memory_indexes),
            _stable_repr(edge_indexes),
            normalized_approved_by,
            _optional_text(notes, "notes") or "",
        ]
    )
    return {
        "schema_version": DOCUMENT_PROMOTION_SCHEMA_VERSION,
        "record_type": "document_promotion_transaction",
        "transaction_id": _readable_stable_id(
            "doc_promote",
            transaction_seed,
            document_id,
            draft_id,
            normalized_approved_by,
        ),
        "draft_id": draft_id,
        "document_id": document_id,
        "status": "prepared",
        "approved_by": normalized_approved_by,
        "notes": _optional_text(notes, "notes"),
        "write_policy": "promotion_required",
        "write_performed": False,
        "active_memory_write_performed": False,
        "operations": operations,
        "receipt": {
            "selected_memory_count": len(memory_indexes),
            "selected_edge_count": len(edge_indexes),
            "operation_count": len(operations),
        },
    }


def preview_document_extraction(
    *,
    title: str,
    source_uri: str,
    source_type: str,
    content: str,
    media_type: str,
    metadata: dict[str, Any] | None = None,
    extractor_id: str = "engram-text-preview",
    extractor_kind: str = "agent_native",
) -> dict[str, Any]:
    """Preview text/markdown document evidence and chunks without writing."""
    normalized_content = _require_text(content, "content")
    content_hash = "sha256:" + hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    document_record = prepare_document_record(
        title=title,
        source_uri=source_uri,
        source_type=source_type,
        content_hash=content_hash,
        media_type=media_type,
        metadata=metadata,
    )
    chunks = [
        _preview_chunk(document_record, chunk)
        for chunk in chunk_content_with_metadata(normalized_content)
    ]
    extractor_receipt = prepare_extractor_receipt(
        document_record=document_record,
        visual_artifacts=[],
        extractor_id=extractor_id,
        extractor_kind=extractor_kind,
    )
    return {
        "schema_version": DOCUMENT_PREVIEW_SCHEMA_VERSION,
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "review_required": True,
        "document_record": document_record,
        "chunks": chunks,
        "visual_artifacts": [],
        "extractor_receipt": extractor_receipt,
        "receipt": {
            "input_chars": len(normalized_content),
            "chunk_count": len(chunks),
            "visual_artifact_count": 0,
            "extractor_kind": extractor_kind,
        },
    }


def preview_visual_extraction(
    *,
    document_record: dict[str, Any],
    observations: list[dict[str, Any]],
    extractor_id: str,
    extractor_kind: str,
    visual_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview caller-supplied OCR/vision observations as visual evidence."""
    document_id = _require_text(document_record.get("document_id"), "document_record.document_id")
    if not isinstance(observations, list) or not observations:
        raise ValueError("observations must include at least one item")
    normalized_visual_request = _normalize_visual_request(visual_request, document_id)

    artifacts = [
        prepare_visual_artifact_record(
            document_id=document_id,
            artifact_type=observation.get("artifact_type"),
            source_ref=observation.get("source_ref"),
            extractor_id=extractor_id,
            extractor_kind=extractor_kind,
            text=observation.get("text"),
            description=observation.get("description"),
            page_number=observation.get("page_number"),
            bounding_box=observation.get("bounding_box") or observation.get("coordinates"),
            confidence=observation.get("confidence"),
            metadata=observation.get("metadata"),
        )
        for observation in observations
    ]
    visual_coverage = None
    if normalized_visual_request is not None:
        visual_coverage = _build_visual_coverage(normalized_visual_request, artifacts)
    quality_warnings = _visual_quality_warnings(normalized_visual_request, visual_coverage, artifacts)
    status = "partial" if quality_warnings else "ok"

    extractor_receipt = prepare_extractor_receipt(
        document_record=document_record,
        visual_artifacts=artifacts,
        extractor_id=extractor_id,
        extractor_kind=extractor_kind,
    )
    return {
        "schema_version": VISUAL_PREVIEW_SCHEMA_VERSION,
        "status": status,
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "review_required": True,
        "document_id": document_id,
        "visual_artifacts": artifacts,
        "visual_coverage": visual_coverage,
        "quality_warnings": quality_warnings,
        "extractor_receipt": extractor_receipt,
        "receipt": {
            "observation_count": len(observations),
            "visual_artifact_count": len(artifacts),
            "extractor_kind": extractor_kind,
            "external_framework_required": extractor_receipt["external_framework_required"],
            **(
                {"visual_request_coverage_complete": visual_coverage["coverage_complete"]}
                if visual_coverage is not None
                else {}
            ),
        },
    }


def _preview_chunk(document_record: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    chunk_id = int(chunk["chunk_id"])
    return {
        "chunk_id": chunk_id,
        "text": chunk["text"],
        "section_title": chunk.get("section_title", ""),
        "heading_path": list(chunk.get("heading_path", [])),
        "chunk_kind": chunk.get("chunk_kind", "section"),
        "provenance": {
            "document_id": document_record["document_id"],
            "source_uri": document_record["source_uri"],
            "chunk_id": chunk_id,
        },
    }


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _readable_stable_id(prefix: str, seed: str, *readable_parts: Any) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    label = _slugify("_".join(str(part) for part in readable_parts if part not in (None, "")), max_length=96)
    if not label:
        return f"{prefix}_{digest}"
    return f"{prefix}_{label}_{digest}"


def _document_id(*, title: str, source_uri: str, metadata: dict[str, Any]) -> str:
    supplied = _optional_text(metadata.get("document_id"), "metadata.document_id")
    if supplied:
        return _normalize_human_id(supplied, prefix="doc")

    title_slug = _slugify(title)
    if title_slug and title_slug not in {"untitled", "untitled_document", "document"}:
        return f"doc_{title_slug}"

    source_slug = _source_uri_slug(source_uri)
    return f"doc_{source_slug or 'document'}"


def _normalize_human_id(value: str, *, prefix: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{prefix} id is required")
    if text.startswith(f"{prefix}_"):
        suffix = _slugify(text[len(prefix) + 1 :])
    else:
        suffix = _slugify(text)
    if not suffix:
        raise ValueError(f"{prefix} id must include a readable suffix")
    return f"{prefix}_{suffix}"


def _source_uri_slug(source_uri: str) -> str:
    parsed = urlparse(source_uri)
    path = unquote(parsed.path or source_uri)
    leaf = path.rstrip("/").split("/")[-1] if path else source_uri
    stem = leaf.rsplit(".", 1)[0] if "." in leaf else leaf
    return _slugify(stem)


def _source_ref_label(source_ref: dict[str, Any]) -> str:
    source_uri = _optional_text(source_ref.get("source_uri"), "source_ref.source_uri")
    if source_uri:
        slug = _source_uri_slug(source_uri)
        if slug:
            return slug
    source_artifact_id = _optional_text(source_ref.get("source_artifact_id"), "source_ref.source_artifact_id")
    if source_artifact_id:
        return source_artifact_id
    content_hash = _optional_text(source_ref.get("content_hash"), "source_ref.content_hash")
    if content_hash:
        return content_hash.replace("sha256:", "sha256_")[:24]
    return "source"


def _slugify(value: str, *, max_length: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug[:max_length].strip("_")


def _stable_repr(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{key}:{_stable_repr(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_stable_repr(item) for item in value) + "]"
    return str(value)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    text = value.strip()
    return text or None


def _require_hash(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not text.startswith("sha256:") or len(text) != 71:
        raise ValueError(f"{field_name} must be a sha256: hash")
    return text


def _normalize_source_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("source_ref is required")
    return dict(value)


def _source_artifact_id_from_ref(value: dict[str, Any]) -> str | None:
    return _optional_text(
        value.get("source_artifact_id") or value.get("artifact_id") or value.get("ref"),
        "source_ref.source_artifact_id",
    )


def _normalize_image_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("image_refs must include at least one item")
    return [_normalize_source_ref(item) for item in value]


def _normalize_optional_source_refs(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("image_refs must be a list")
    return [_normalize_source_ref(item) for item in value]


def _normalize_visual_capabilities(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("requested_capabilities must include at least one item")
    normalized: set[str] = set()
    for item in value:
        capability = _require_text(item, "requested_capability")
        if capability not in VALID_VISUAL_CAPABILITIES:
            valid = ", ".join(sorted(VALID_VISUAL_CAPABILITIES))
            raise ValueError(f"Unsupported visual capability: {capability}. Valid: {valid}")
        normalized.add(capability)
    return sorted(normalized)


def _visual_evidence_contract() -> dict[str, Any]:
    return {
        "preview_tool": "preview_visual_extraction",
        "artifact_record_type": "visual_artifact",
        "receipt_record_type": "extractor_receipt",
        "expected_observation_fields": list(EXPECTED_VISUAL_OBSERVATION_FIELDS),
        "mandatory_interpretation": True,
        "coverage_rule": "Every requested image_ref must return at least one reviewed visual artifact before draft promotion.",
        "trusted_memory": False,
        "promotion_required": True,
    }


def _visual_framework_strategy(external_framework_required: bool) -> dict[str, Any]:
    return {
        "agent_native_allowed": not external_framework_required,
        "external_framework_required": external_framework_required,
        "return_tool": "preview_visual_extraction",
        "promotion_path": "review_visual_artifacts_before_document_draft",
    }


def _normalize_visual_request(value: Any, document_id: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("visual_request must be an object")
    request_id = _require_text(value.get("request_id"), "visual_request.request_id")
    request_document_id = _require_text(value.get("document_id"), "visual_request.document_id")
    if request_document_id != document_id:
        raise ValueError("visual_request document_id does not match document_record.document_id")
    return {
        "request_id": request_id,
        "image_refs": _normalize_image_refs(value.get("image_refs")),
        "requested_capabilities": _normalize_visual_capabilities(value.get("requested_capabilities") or []),
    }


def _build_visual_coverage(visual_request: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    required_refs = [dict(ref) for ref in visual_request["image_refs"]]
    observed_keys: set[str] = set()
    for artifact in artifacts:
        observed_keys.update(_visual_artifact_match_keys(artifact))

    missing_refs = [
        ref for ref in required_refs
        if not (_visual_ref_match_keys(ref) & observed_keys)
    ]
    return {
        "visual_request_id": visual_request["request_id"],
        "required_image_ref_count": len(required_refs),
        "covered_image_ref_count": len(required_refs) - len(missing_refs),
        "missing_image_refs": missing_refs,
        "coverage_complete": not missing_refs,
    }


def _visual_quality_warnings(
    visual_request: dict[str, Any] | None,
    visual_coverage: dict[str, Any] | None,
    artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    requested_capabilities = set((visual_request or {}).get("requested_capabilities") or [])
    missing_count = (
        len(visual_coverage.get("missing_image_refs") or [])
        if isinstance(visual_coverage, dict)
        else 0
    )
    if missing_count:
        warnings.append(
            {
                "code": "unresolved_visual_evidence",
                "severity": "high",
                "missing_image_ref_count": missing_count,
                "message": "Visual request is missing observations for required image refs.",
            }
        )
        if "ocr_text" in requested_capabilities:
            warnings.append(
                {
                    "code": "missing_ocr_coverage",
                    "severity": "high",
                    "missing_image_ref_count": missing_count,
                    "message": "OCR coverage is missing for one or more requested image refs.",
                }
            )
        if "table_structure" in requested_capabilities:
            warnings.append(
                {
                    "code": "missing_table_coverage",
                    "severity": "high",
                    "missing_image_ref_count": missing_count,
                    "message": "Table structure coverage is missing for one or more requested image refs.",
                }
            )

    for artifact in artifacts:
        confidence = artifact.get("confidence")
        if not isinstance(confidence, (int, float)) or confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        artifact_type = str(artifact.get("artifact_type") or "")
        if artifact_type.startswith("ocr"):
            code = "low_confidence_ocr"
            message = "OCR observation confidence is below review threshold."
        elif artifact_type == "table":
            code = "low_confidence_table"
            message = "Table observation confidence is below review threshold."
        else:
            code = "low_confidence_visual_evidence"
            message = "Visual observation confidence is below review threshold."
        warnings.append(
            {
                "code": code,
                "severity": "medium",
                "artifact_id": artifact.get("artifact_id"),
                "confidence": confidence,
                "message": message,
            }
        )
    return warnings


def _visual_artifact_match_keys(artifact: dict[str, Any]) -> set[str]:
    provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
    source_ref = dict(provenance.get("source_ref") or {})
    source_artifact_id = provenance.get("source_artifact_id")
    if source_artifact_id and "source_artifact_id" not in source_ref:
        source_ref["source_artifact_id"] = source_artifact_id
    page_number = provenance.get("page_number")
    if page_number and "page_number" not in source_ref and "page" not in source_ref:
        source_ref["page_number"] = page_number
    return _visual_ref_match_keys(source_ref)


def _visual_ref_match_keys(ref: dict[str, Any]) -> set[str]:
    if not isinstance(ref, dict):
        return set()
    page_number = _optional_ref_page(ref.get("page_number") or ref.get("page"))
    artifact_identifiers = [
        _optional_ref_text(ref.get(field))
        for field in (
            "source_artifact_id",
            "source_artifact_ref",
            "artifact_id",
            "ref",
            "image_hash",
        )
    ]
    keys: set[str] = set()
    for identifier in artifact_identifiers:
        if not identifier:
            continue
        keys.add(f"artifact:{identifier}|page:{page_number}" if page_number is not None else f"artifact:{identifier}")
    if keys:
        return keys

    source_uri = _optional_ref_text(ref.get("source_uri"))
    if source_uri:
        keys.add(f"source:{source_uri}|page:{page_number}" if page_number is not None else f"source:{source_uri}")
        return keys

    if page_number is not None:
        keys.add(f"page:{page_number}")
    return keys


def _optional_ref_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_ref_page(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        page_number = int(value)
    except (TypeError, ValueError):
        return None
    return page_number if page_number > 0 else None


def _normalize_document_outputs(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("requested_outputs must include at least one item")
    normalized: set[str] = set()
    for item in value:
        output = _require_text(item, "requested_output").lower()
        if output not in VALID_DOCUMENT_OUTPUTS:
            valid = ", ".join(sorted(VALID_DOCUMENT_OUTPUTS))
            raise ValueError(f"Unsupported document output: {output}. Valid: {valid}")
        normalized.add(output)
    return sorted(normalized)


def _normalize_understanding_analysis(value: Any, document_id: str) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise ValueError("analysis must be an object")
    unknown = sorted(set(value) - DOCUMENT_UNDERSTANDING_ANALYSIS_FIELDS)
    if unknown:
        raise ValueError(f"Unsupported understanding analysis field: {unknown[0]}")
    return {
        "summary_slots": _normalize_summary_slots(value.get("summary"), document_id),
        "claim_candidates": _normalize_claim_candidates(value.get("claims"), document_id),
        "concept_candidates": _normalize_concept_candidates(value.get("concepts"), document_id),
        "entity_candidates": _normalize_entity_candidates(value.get("entities"), document_id),
        "high_value_sections": _normalize_high_value_sections(value.get("high_value_sections"), document_id),
        "explicit_warnings": _normalize_understanding_warnings(value.get("warnings")),
    }


def _normalize_summary_slots(value: Any, document_id: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for index, item in enumerate(_understanding_items(value, "analysis.summary")):
        if isinstance(item, str):
            slot = "summary"
            text = _require_text(item, "analysis.summary")
            confidence = None
            evidence_refs: list[Any] = []
        elif isinstance(item, dict):
            slot = _optional_text(item.get("slot"), "analysis.summary.slot") or "summary"
            text = _require_text(item.get("text") or item.get("summary"), "analysis.summary.text")
            confidence = _normalize_confidence(item.get("confidence"))
            evidence_refs = _normalize_evidence_refs(item.get("evidence_refs"))
        else:
            raise ValueError("analysis.summary entries must be strings or objects")
        slots.append(
            {
                "record_type": "summary_slot",
                "summary_id": _readable_stable_id(
                    "summary",
                    f"{document_id}|{index}|{slot}|{text}",
                    document_id,
                    slot,
                    text,
                ),
                "slot": slot,
                "text": text,
                "confidence": confidence,
                "evidence_refs": evidence_refs,
            }
        )
    return slots


def _normalize_claim_candidates(value: Any, document_id: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for item in _understanding_items(value, "analysis.claims"):
        if isinstance(item, str):
            text = _require_text(item, "analysis.claims")
            confidence = None
            evidence_refs: list[Any] = []
        elif isinstance(item, dict):
            text = _require_text(item.get("text") or item.get("claim"), "analysis.claims.text")
            confidence = _normalize_confidence(item.get("confidence"))
            evidence_refs = _normalize_evidence_refs(item.get("evidence_refs"))
        else:
            raise ValueError("analysis.claims entries must be strings or objects")
        claims.append(
            {
                "record_type": "claim_candidate",
                "claim_id": _readable_stable_id(
                    "claim",
                    f"{document_id}|{text}|{_stable_repr(evidence_refs)}",
                    document_id,
                    text,
                ),
                "text": text,
                "confidence": confidence,
                "evidence_refs": evidence_refs,
                "review_status": "candidate",
                "promotion_required": True,
            }
        )
    return claims


def _normalize_concept_candidates(value: Any, document_id: str) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = []
    for item in _understanding_items(value, "analysis.concepts"):
        if isinstance(item, str):
            name = _require_text(item, "analysis.concepts")
            description = None
            confidence = None
        elif isinstance(item, dict):
            name = _require_text(item.get("name") or item.get("concept"), "analysis.concepts.name")
            description = _optional_text(item.get("description"), "analysis.concepts.description")
            confidence = _normalize_confidence(item.get("confidence"))
        else:
            raise ValueError("analysis.concepts entries must be strings or objects")
        concepts.append(
            {
                "record_type": "concept_candidate",
                "concept_id": _readable_stable_id("concept", f"{document_id}|{name}", document_id, name),
                "name": name,
                "description": description,
                "confidence": confidence,
                "review_status": "candidate",
                "promotion_required": True,
            }
        )
    return concepts


def _normalize_entity_candidates(value: Any, document_id: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for item in _understanding_items(value, "analysis.entities"):
        if isinstance(item, str):
            name = _require_text(item, "analysis.entities")
            kind = "entity"
            confidence = None
        elif isinstance(item, dict):
            name = _require_text(item.get("name") or item.get("entity"), "analysis.entities.name")
            kind = _optional_text(item.get("kind"), "analysis.entities.kind") or "entity"
            confidence = _normalize_confidence(item.get("confidence"))
        else:
            raise ValueError("analysis.entities entries must be strings or objects")
        entities.append(
            {
                "record_type": "entity_candidate",
                "entity_id": _readable_stable_id("entity", f"{document_id}|{kind}|{name}", document_id, kind, name),
                "name": name,
                "kind": kind,
                "confidence": confidence,
                "review_status": "candidate",
                "promotion_required": True,
            }
        )
    return entities


def _normalize_high_value_sections(value: Any, document_id: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for item in _understanding_items(value, "analysis.high_value_sections"):
        if isinstance(item, str):
            title = _require_text(item, "analysis.high_value_sections")
            reason = None
            page_number = None
            confidence = None
            chunk_ref = None
        elif isinstance(item, dict):
            title = _require_text(item.get("title") or item.get("section"), "analysis.high_value_sections.title")
            reason = _optional_text(item.get("reason"), "analysis.high_value_sections.reason")
            page_number = _optional_positive_int(item.get("page_number"), "analysis.high_value_sections.page_number")
            confidence = _normalize_confidence(item.get("confidence"))
            chunk_ref = item.get("chunk_ref") if isinstance(item.get("chunk_ref"), dict) else None
        else:
            raise ValueError("analysis.high_value_sections entries must be strings or objects")
        sections.append(
            {
                "record_type": "high_value_section",
                "section_id": _readable_stable_id(
                    "section",
                    f"{document_id}|{title}|{page_number}",
                    document_id,
                    title,
                    page_number,
                ),
                "title": title,
                "reason": reason,
                "page_number": page_number,
                "chunk_ref": chunk_ref,
                "confidence": confidence,
                "review_status": "candidate",
                "promotion_required": True,
            }
        )
    return sections


def _normalize_understanding_warnings(value: Any) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in _understanding_items(value, "analysis.warnings"):
        if isinstance(item, str):
            message = _require_text(item, "analysis.warnings")
            warnings.append({"code": "analysis_warning", "message": message})
            continue
        if not isinstance(item, dict):
            raise ValueError("analysis.warnings entries must be strings or objects")
        warning = {
            "code": _optional_text(item.get("code"), "analysis.warnings.code") or "analysis_warning",
            "message": _require_text(item.get("message"), "analysis.warnings.message"),
        }
        target_id = _optional_text(item.get("target_id"), "analysis.warnings.target_id")
        confidence = _normalize_confidence(item.get("confidence"))
        if target_id:
            warning["target_id"] = target_id
        if confidence is not None:
            warning["confidence"] = confidence
        warnings.append(warning)
    return warnings


def _understanding_items(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a string, object, or list")
    return value


def _normalize_evidence_refs(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("evidence_refs must be a list")
    refs: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            refs.append(dict(item))
        else:
            refs.append(_require_text(item, "evidence_ref"))
    return refs


def _understanding_item_count(value: dict[str, list[dict[str, Any]]]) -> int:
    return sum(
        len(value[key])
        for key in (
            "summary_slots",
            "claim_candidates",
            "concept_candidates",
            "entity_candidates",
            "high_value_sections",
            "explicit_warnings",
        )
    )


def _understanding_draft_analysis(value: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {
        "summary": [item["text"] for item in value["summary_slots"]],
        "claims": [item["text"] for item in value["claim_candidates"]],
        "entities": [
            f"{item['kind']}: {item['name']}"
            for item in value["entity_candidates"]
        ],
    }


def _auto_document_understanding_edges(
    *,
    document_id: str,
    normalized: dict[str, list[dict[str, Any]]],
    chunk_refs: list[dict[str, Any]],
    visual_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    document_ref = {"kind": "document", "key": document_id}
    visual_by_id = {
        _require_text(artifact.get("artifact_id"), "visual_artifact.artifact_id"): artifact
        for artifact in visual_artifacts
    }
    raw_edges: list[dict[str, Any]] = []

    for section in normalized["high_value_sections"]:
        section_ref = {"kind": "section", "key": section["section_id"]}
        _append_auto_edge(
            raw_edges,
            from_ref=document_ref,
            to_ref=section_ref,
            edge_type="contains",
            confidence=section.get("confidence"),
            evidence=f"Document contains high-value section '{section['title']}'.",
        )
        page_ref = _page_ref(document_id, section.get("page_number"))
        if page_ref is not None:
            _append_auto_edge(
                raw_edges,
                from_ref=document_ref,
                to_ref=page_ref,
                edge_type="contains",
                confidence=section.get("confidence"),
                evidence=f"Document contains page {section['page_number']} for section '{section['title']}'.",
            )
        chunk_ref = _chunk_graph_ref(section.get("chunk_ref"), document_id)
        if chunk_ref is not None:
            _append_auto_edge(
                raw_edges,
                from_ref=section_ref,
                to_ref=chunk_ref,
                edge_type="contains",
                confidence=section.get("confidence"),
                evidence=f"Section '{section['title']}' contains cited chunk evidence.",
            )

    for concept in normalized["concept_candidates"]:
        edge_type = "defines" if concept.get("description") else "mentions"
        _append_auto_edge(
            raw_edges,
            from_ref=document_ref,
            to_ref={"kind": "concept", "key": concept["concept_id"]},
            edge_type=edge_type,
            confidence=concept.get("confidence"),
            evidence=f"Document {edge_type} concept '{concept['name']}'.",
        )

    for entity in normalized["entity_candidates"]:
        _append_auto_edge(
            raw_edges,
            from_ref=document_ref,
            to_ref={"kind": "entity", "key": entity["entity_id"]},
            edge_type="mentions",
            confidence=entity.get("confidence"),
            evidence=f"Document mentions {entity['kind']} '{entity['name']}'.",
        )

    for claim in normalized["claim_candidates"]:
        claim_ref = {"kind": "claim", "key": claim["claim_id"]}
        _append_auto_edge(
            raw_edges,
            from_ref=document_ref,
            to_ref=claim_ref,
            edge_type="supports",
            confidence=claim.get("confidence"),
            evidence="Document is cited as evidence for a reviewed claim candidate.",
        )
        for evidence_ref in claim.get("evidence_refs", []):
            chunk_ref = _chunk_graph_ref(evidence_ref, document_id)
            if chunk_ref is not None:
                _append_auto_edge(
                    raw_edges,
                    from_ref=chunk_ref,
                    to_ref=claim_ref,
                    edge_type="supports",
                    confidence=claim.get("confidence"),
                    evidence="Cited chunk supports a reviewed claim candidate.",
                )
                continue
            if isinstance(evidence_ref, str) and evidence_ref in visual_by_id:
                _append_auto_edge(
                    raw_edges,
                    from_ref={"kind": "visual_artifact", "key": evidence_ref},
                    to_ref=claim_ref,
                    edge_type="illustrates",
                    confidence=visual_by_id[evidence_ref].get("confidence"),
                    evidence="Visual artifact is cited as evidence for a reviewed claim candidate.",
                )

    for chunk_ref in chunk_refs:
        graph_ref = _chunk_graph_ref(chunk_ref, document_id)
        if graph_ref is not None:
            _append_auto_edge(
                raw_edges,
                from_ref=document_ref,
                to_ref=graph_ref,
                edge_type="contains",
                confidence=None,
                evidence="Document contains cited chunk evidence.",
            )

    for artifact in visual_artifacts:
        artifact_id = _require_text(artifact.get("artifact_id"), "visual_artifact.artifact_id")
        visual_ref = {"kind": "visual_artifact", "key": artifact_id}
        _append_auto_edge(
            raw_edges,
            from_ref=visual_ref,
            to_ref=document_ref,
            edge_type="derived_from",
            confidence=artifact.get("confidence"),
            evidence="Visual artifact is derived from the source document.",
        )
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        page_ref = _page_ref(document_id, provenance.get("page_number"))
        if page_ref is None:
            continue
        _append_auto_edge(
            raw_edges,
            from_ref=document_ref,
            to_ref=page_ref,
            edge_type="contains",
            confidence=artifact.get("confidence"),
            evidence=f"Document contains page {provenance['page_number']} for visual evidence.",
        )
        _append_auto_edge(
            raw_edges,
            from_ref=page_ref,
            to_ref=visual_ref,
            edge_type="contains",
            confidence=artifact.get("confidence"),
            evidence=f"Page {provenance['page_number']} contains visual artifact evidence.",
        )

    return _dedupe_graph_edges(
        [
            normalize_graph_edge_proposal(edge, default_source=AUTO_GRAPH_SOURCE)
            for edge in raw_edges
        ]
    )


def _append_auto_edge(
    edges: list[dict[str, Any]],
    *,
    from_ref: dict[str, Any],
    to_ref: dict[str, Any],
    edge_type: str,
    confidence: Any,
    evidence: str,
) -> None:
    edges.append(
        {
            "from_ref": from_ref,
            "to_ref": to_ref,
            "edge_type": edge_type,
            "confidence": _normalize_confidence(confidence) if confidence is not None else 0.6,
            "evidence": evidence,
            "source": AUTO_GRAPH_SOURCE,
        }
    )


def _page_ref(document_id: str, page_number: Any) -> dict[str, str] | None:
    normalized_page = _optional_ref_page(page_number)
    if normalized_page is None:
        return None
    return {"kind": "page", "key": f"{document_id}:page:{normalized_page:05d}"}


def _chunk_graph_ref(value: Any, document_id: str) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    key = _optional_ref_text(value.get("key"))
    if key:
        return {"kind": "chunk", "key": key}
    if value.get("chunk_id") is None:
        return None
    chunk_document_id = _optional_ref_text(value.get("document_id")) or document_id
    return {"kind": "chunk", "key": f"{chunk_document_id}:chunk:{value['chunk_id']}"}


def _dedupe_graph_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in edges:
        signature = _stable_repr(
            {
                "from_ref": edge.get("from_ref"),
                "to_ref": edge.get("to_ref"),
                "edge_type": edge.get("edge_type"),
                "source": edge.get("source"),
            }
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(edge)
    return deduped


def _understanding_low_confidence_warnings(
    normalized: dict[str, list[dict[str, Any]]],
    visual_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings = list(normalized["explicit_warnings"])
    for item in normalized["claim_candidates"]:
        warning = _low_confidence_warning(
            code="low_confidence_claim",
            target_id=item["claim_id"],
            confidence=item.get("confidence"),
            message="Claim candidate confidence is below review threshold.",
        )
        if warning:
            warnings.append(warning)
    for item in normalized["concept_candidates"]:
        warning = _low_confidence_warning(
            code="low_confidence_concept",
            target_id=item["concept_id"],
            confidence=item.get("confidence"),
            message="Concept candidate confidence is below review threshold.",
        )
        if warning:
            warnings.append(warning)
    for item in normalized["entity_candidates"]:
        warning = _low_confidence_warning(
            code="low_confidence_entity",
            target_id=item["entity_id"],
            confidence=item.get("confidence"),
            message="Entity candidate confidence is below review threshold.",
        )
        if warning:
            warnings.append(warning)
    for item in normalized["high_value_sections"]:
        warning = _low_confidence_warning(
            code="low_confidence_section",
            target_id=item["section_id"],
            confidence=item.get("confidence"),
            message="High-value section confidence is below review threshold.",
        )
        if warning:
            warnings.append(warning)
    for artifact in visual_artifacts:
        warning = _low_confidence_warning(
            code="low_confidence_visual_artifact",
            target_id=_require_text(artifact.get("artifact_id"), "visual_artifact.artifact_id"),
            confidence=artifact.get("confidence"),
            message="Visual artifact confidence is below review threshold.",
        )
        if warning:
            warnings.append(warning)
    return warnings


def _low_confidence_warning(
    *,
    code: str,
    target_id: str,
    confidence: Any,
    message: str,
) -> dict[str, Any] | None:
    normalized_confidence = _normalize_confidence(confidence)
    if normalized_confidence is None or normalized_confidence >= LOW_CONFIDENCE_THRESHOLD:
        return None
    return {
        "code": code,
        "target_id": target_id,
        "confidence": normalized_confidence,
        "message": message,
    }


def _normalize_document_analysis(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("analysis must be an object")
    unknown = sorted(set(value) - set(DOCUMENT_ANALYSIS_SECTIONS))
    if unknown:
        raise ValueError(f"Unsupported analysis field: {unknown[0]}")
    return {
        field: _normalize_analysis_items(value.get(field), field)
        for field in DOCUMENT_ANALYSIS_SECTIONS
    }


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    return dict(value)


def _normalize_analysis_items(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        raise ValueError(f"analysis.{field_name} must be a string or list")
    items: list[str] = []
    for item in value:
        text = _require_text(item, f"analysis.{field_name}")
        if text not in items:
            items.append(text)
    return items


def _analysis_item_count(analysis: dict[str, list[str]]) -> int:
    return sum(len(items) for items in analysis.values())


def _analysis_markdown(title: str, analysis: dict[str, list[str]]) -> str:
    lines = [f"# Document Draft: {title}", ""]
    for field, heading in DOCUMENT_ANALYSIS_SECTIONS.items():
        items = analysis[field]
        if not items:
            continue
        lines.append(f"## {heading}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _normalize_chunk_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("chunk_refs must be a list")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or not item:
            raise ValueError("chunk_refs entries must be objects")
        normalized.append(dict(item))
    return normalized


def _normalize_visual_artifacts(value: Any, document_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("visual_artifacts must be a list")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("visual_artifacts entries must be objects")
        artifact_document_id = _require_text(item.get("document_id"), "visual_artifact.document_id")
        if artifact_document_id != document_id:
            raise ValueError("visual_artifact document_id does not match document_record.document_id")
        _require_text(item.get("artifact_id"), "visual_artifact.artifact_id")
        normalized.append(dict(item))
    return normalized


def _normalize_candidate_graph_edges(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("candidate_graph_edges must be a list")
    normalized: list[dict[str, Any]] = []
    for edge in value:
        normalized.append(normalize_graph_edge_proposal(edge))
    return normalized


def _normalize_proposed_items(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"document_draft.{field_name} must be a list")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"document_draft.{field_name} entries must be objects")
        normalized.append(dict(item))
    return normalized


def _normalize_selected_indexes(value: Any, total: int, label: str) -> list[int]:
    if value is None:
        return list(range(total))
    if not isinstance(value, list):
        raise ValueError(f"selected {label} indexes must be a list")
    indexes: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"selected {label} indexes must be integers")
        if item < 0 or item >= total:
            raise ValueError(f"selected {label} index out of range")
        if item not in indexes:
            indexes.append(item)
    return indexes


def _promoted_memory_payload(memory: dict[str, Any]) -> dict[str, Any]:
    payload = dict(memory)
    payload["status"] = "active"
    source_document = payload.get("source_document")
    if isinstance(source_document, dict):
        payload["source_document"] = {
            **source_document,
            "review_status": "approved",
            "promotion_required": False,
        }
    return payload


def _promoted_graph_edge_payload(edge: dict[str, Any], approved_by: str) -> dict[str, Any]:
    return {
        "from_ref": dict(edge["from_ref"]),
        "to_ref": dict(edge["to_ref"]),
        "edge_type": _require_text(edge.get("edge_type"), "proposed_edge.edge_type"),
        "confidence": _normalize_confidence(edge.get("confidence", 0.5)),
        "evidence": _require_text(edge.get("evidence"), "proposed_edge.evidence"),
        "source": _optional_text(edge.get("source"), "proposed_edge.source") or "document_intelligence",
        "created_by": approved_by,
    }


def _normalize_extractor_kind(value: Any) -> str:
    text = _require_text(value, "extractor_kind")
    if text not in VALID_EXTRACTOR_KINDS:
        valid = ", ".join(sorted(VALID_EXTRACTOR_KINDS))
        raise ValueError(f"extractor_kind must be one of: {valid}")
    return text


def _normalize_document_extractor_kind(value: Any) -> str:
    text = _require_text(value, "extractor_kind").lower()
    if text not in VALID_DOCUMENT_EXTRACTOR_KINDS:
        valid = ", ".join(sorted(VALID_DOCUMENT_EXTRACTOR_KINDS))
        raise ValueError(f"extractor_kind must be one of: {valid}")
    return text


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 1:
        raise ValueError(f"{field_name} must be positive")
    return value


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _normalize_confidence(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("confidence must be between 0 and 1")
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence must be between 0 and 1") from None
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _normalize_bounding_box(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("bounding_box must be an object")
    required = ["x", "y", "width", "height"]
    normalized: dict[str, float] = {}
    for field in required:
        if field not in value:
            raise ValueError(f"bounding_box.{field} is required")
        if isinstance(value[field], bool):
            raise ValueError(f"bounding_box.{field} must be numeric")
        try:
            normalized[field] = float(value[field])
        except (TypeError, ValueError):
            raise ValueError(f"bounding_box.{field} must be numeric") from None
    if normalized["width"] <= 0:
        raise ValueError("bounding_box.width must be positive")
    if normalized["height"] <= 0:
        raise ValueError("bounding_box.height must be positive")
    return normalized

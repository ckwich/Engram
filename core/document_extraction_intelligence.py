"""Document extraction, records, and text-preview helpers."""
from __future__ import annotations

import hashlib
from typing import Any

from core.chunker import chunk_content_with_metadata
from core.document_intelligence_contracts import (
    DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
    DOCUMENT_EXTRACTOR_CATALOG_SCHEMA_VERSION,
    DOCUMENT_PREVIEW_SCHEMA_VERSION,
    DOCUMENT_EXTRACTION_REQUEST_SCHEMA_VERSION,
    DOCUMENT_EXTRACTION_RESULT_SCHEMA_VERSION,
    VISUAL_DOCUMENT_OUTPUTS,
    VISUAL_SOURCE_TYPES,
    VALID_VISUAL_CAPABILITIES,
    EXPECTED_DOCUMENT_EXTRACTION_FIELDS,
)

from core.document_intelligence_shared import (
    _preview_chunk,
    _readable_stable_id,
    _document_id,
    _source_ref_label,
    _stable_repr,
    _require_text,
    _optional_text,
    _require_hash,
    _normalize_source_ref,
    _normalize_optional_source_refs,
    _normalize_visual_capabilities,
    _normalize_document_outputs,
    _normalize_metadata,
    _normalize_document_extractor_kind,
    _normalize_bool,
)

from core.document_visual_intelligence import prepare_extractor_receipt


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
                    "prepare_document_coverage_workbench",
                    "preview_document_extraction",
                    "prepare_visual_extraction_request",
                ],
            },
            {
                "id": "engram-local-coverage-workbench",
                "kind": "ocr_vision",
                "label": "Bundled local page-render/OCR/table coverage workbench",
                "source_types": ["pdf"],
                "requested_outputs": ["page_images", "ocr_observations", "table_observations"],
                "requested_capabilities": sorted(VALID_VISUAL_CAPABILITIES),
                "runs_inside_engram": True,
                "external_framework_required": False,
                "required_tools": ["pdftoppm"],
                "optional_tools": ["tesseract", "table_detector"],
                "next_tools": [
                    "prepare_document_coverage_workbench",
                    "preview_visual_extraction",
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

"""Visual/OCR/table evidence helpers for document intelligence."""
from __future__ import annotations

from typing import Any

from core.document_intelligence_contracts import (
    DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
    VISUAL_PREVIEW_SCHEMA_VERSION,
    VISUAL_REQUEST_SCHEMA_VERSION,
    PROMOTION_GUIDANCE,
    EXPECTED_VISUAL_OBSERVATION_FIELDS,
)

from core.document_intelligence_shared import (
    _readable_stable_id,
    _stable_repr,
    _require_text,
    _optional_text,
    _normalize_source_ref,
    _source_artifact_id_from_ref,
    _normalize_image_refs,
    _normalize_visual_capabilities,
    _visual_evidence_contract,
    _visual_framework_strategy,
    _normalize_visual_request,
    _build_visual_coverage,
    _visual_quality_warnings,
    _normalize_extractor_kind,
    _optional_positive_int,
    _normalize_confidence,
    _normalize_bounding_box,
)


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

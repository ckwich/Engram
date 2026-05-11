"""No-write document intelligence primitives for the Engram Memory OS rebuild."""
from __future__ import annotations

import hashlib
from typing import Any

from core.chunker import chunk_content_with_metadata


DOCUMENT_INTELLIGENCE_SCHEMA_VERSION = "2026-05-11.document-intelligence.v1"
DOCUMENT_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.preview.v1"
VISUAL_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.visual-preview.v1"
VALID_EXTRACTOR_KINDS = {"agent_native", "ocr", "vision", "ocr_vision"}
PROMOTION_GUIDANCE = {
    "default_action": "review_before_promotion",
    "auto_promote": False,
    "allowed_destinations": ["memory", "graph_edge", "document_store", "external_pointer"],
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
    return {
        "schema_version": DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
        "record_type": "document",
        "document_id": _stable_id("doc", f"{normalized_source_uri}|{normalized_content_hash}"),
        "title": normalized_title,
        "source_uri": normalized_source_uri,
        "source_type": normalized_source_type,
        "content_hash": normalized_content_hash,
        "media_type": normalized_media_type,
        "metadata": dict(metadata or {}),
        "review_status": "evidence",
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
        "artifact_id": _stable_id("vis", artifact_seed),
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
            "page_number": normalized_page,
            "bounding_box": normalized_box,
        },
        "metadata": dict(metadata or {}),
        "review_status": "evidence",
        "trusted_memory": False,
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
        "receipt_id": _stable_id("doc_extract", receipt_seed),
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
) -> dict[str, Any]:
    """Preview caller-supplied OCR/vision observations as visual evidence."""
    document_id = _require_text(document_record.get("document_id"), "document_record.document_id")
    if not isinstance(observations, list) or not observations:
        raise ValueError("observations must include at least one item")

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
            bounding_box=observation.get("bounding_box"),
            confidence=observation.get("confidence"),
            metadata=observation.get("metadata"),
        )
        for observation in observations
    ]
    extractor_receipt = prepare_extractor_receipt(
        document_record=document_record,
        visual_artifacts=artifacts,
        extractor_id=extractor_id,
        extractor_kind=extractor_kind,
    )
    return {
        "schema_version": VISUAL_PREVIEW_SCHEMA_VERSION,
        "write_performed": False,
        "active_memory_write_performed": False,
        "review_required": True,
        "document_id": document_id,
        "visual_artifacts": artifacts,
        "extractor_receipt": extractor_receipt,
        "receipt": {
            "observation_count": len(observations),
            "visual_artifact_count": len(artifacts),
            "extractor_kind": extractor_kind,
            "external_framework_required": extractor_receipt["external_framework_required"],
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


def _normalize_extractor_kind(value: Any) -> str:
    text = _require_text(value, "extractor_kind")
    if text not in VALID_EXTRACTOR_KINDS:
        valid = ", ".join(sorted(VALID_EXTRACTOR_KINDS))
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

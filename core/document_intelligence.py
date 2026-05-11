"""No-write document intelligence primitives for the Engram Memory OS rebuild."""
from __future__ import annotations

import hashlib
from typing import Any

from core.chunker import chunk_content_with_metadata


DOCUMENT_INTELLIGENCE_SCHEMA_VERSION = "2026-05-11.document-intelligence.v1"
DOCUMENT_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.preview.v1"
VISUAL_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.visual-preview.v1"
VISUAL_REQUEST_SCHEMA_VERSION = "2026-05-11.document-intelligence.visual-request.v1"
DOCUMENT_DRAFT_SCHEMA_VERSION = "2026-05-11.document-intelligence.draft.v1"
DOCUMENT_PROMOTION_SCHEMA_VERSION = "2026-05-11.document-intelligence.promotion.v1"
VALID_EXTRACTOR_KINDS = {"agent_native", "ocr", "vision", "ocr_vision"}
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
    "text",
    "description",
    "page_number",
    "bounding_box",
    "confidence",
    "metadata",
]


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
        "request_id": _stable_id("vis_req", request_seed),
        "document_id": document_id,
        "image_refs": normalized_images,
        "requested_capabilities": normalized_capabilities,
        "instructions": normalized_instructions,
        "extractor": {
            "id": normalized_extractor_id,
            "kind": normalized_extractor_kind,
            "external_framework_required": normalized_extractor_kind != "agent_native",
        },
        "image_recognition_required": normalized_extractor_kind in {"vision", "ocr_vision"},
        "expected_observation_fields": list(EXPECTED_VISUAL_OBSERVATION_FIELDS),
        "review_status": "request",
        "active_memory_write_performed": False,
        "promotion_required": True,
        "promotion_guidance": dict(PROMOTION_GUIDANCE),
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
    draft_id = _stable_id("doc_draft", draft_seed)
    content = _analysis_markdown(title, normalized_analysis)
    metadata = document_record.get("metadata") if isinstance(document_record.get("metadata"), dict) else {}
    source_type = _optional_text(document_record.get("source_type"), "document_record.source_type")
    tags = ["document-intelligence"]
    if source_type:
        tags.append(source_type)
    proposed_memory = {
        "key": _stable_id("doc_mem", draft_seed),
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
        "transaction_id": _stable_id("doc_promote", transaction_seed),
        "draft_id": draft_id,
        "document_id": document_id,
        "status": "prepared",
        "approved_by": normalized_approved_by,
        "notes": _optional_text(notes, "notes"),
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


def _normalize_image_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("image_refs must include at least one item")
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
        if not isinstance(edge, dict):
            raise ValueError("candidate_graph_edges entries must be objects")
        for field in ("from_ref", "to_ref"):
            if not isinstance(edge.get(field), dict) or not edge[field]:
                raise ValueError(f"candidate_graph_edge.{field} is required")
        normalized.append(
            {
                "from_ref": dict(edge["from_ref"]),
                "to_ref": dict(edge["to_ref"]),
                "edge_type": _require_text(edge.get("edge_type"), "candidate_graph_edge.edge_type"),
                "confidence": _normalize_confidence(edge.get("confidence", 0.5)),
                "evidence": _require_text(edge.get("evidence"), "candidate_graph_edge.evidence"),
                "source": _optional_text(edge.get("source"), "candidate_graph_edge.source") or "document_intelligence",
                "status": _optional_text(edge.get("status"), "candidate_graph_edge.status") or "draft",
            }
        )
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

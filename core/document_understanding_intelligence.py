"""Document understanding packets, draft synthesis, and auto graph proposals."""
from __future__ import annotations

from typing import Any

from core.document_intelligence_contracts import (
    DOCUMENT_DRAFT_SCHEMA_VERSION,
    DOCUMENT_UNDERSTANDING_SCHEMA_VERSION,
    PROMOTION_GUIDANCE,
)

from core.document_intelligence_shared import (
    _readable_stable_id,
    _stable_repr,
    _require_text,
    _optional_text,
    _normalize_understanding_analysis,
    _understanding_item_count,
    _understanding_draft_analysis,
    _auto_document_understanding_edges,
    _dedupe_graph_edges,
    _understanding_low_confidence_warnings,
    _normalize_document_analysis,
    _analysis_item_count,
    _analysis_markdown,
    _normalize_chunk_refs,
    _normalize_visual_artifacts,
    _normalize_candidate_graph_edges,
)


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

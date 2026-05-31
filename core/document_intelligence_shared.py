"""Shared normalization and graph helpers for document intelligence modules."""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import unquote, urlparse

from core.document_coverage import build_visual_coverage as build_visual_coverage_model
from core.graph_manager import normalize_graph_edge_proposal

from core.document_intelligence_contracts import (
    AUTO_GRAPH_SOURCE,
    DOCUMENT_ANALYSIS_SECTIONS,
    DOCUMENT_DRAFT_SCHEMA_VERSION,
    DOCUMENT_EXTRACTION_REQUEST_SCHEMA_VERSION,
    DOCUMENT_EXTRACTION_RESULT_SCHEMA_VERSION,
    DOCUMENT_EXTRACTOR_CATALOG_SCHEMA_VERSION,
    DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
    DOCUMENT_PREVIEW_SCHEMA_VERSION,
    DOCUMENT_PROMOTION_SCHEMA_VERSION,
    DOCUMENT_UNDERSTANDING_ANALYSIS_FIELDS,
    DOCUMENT_UNDERSTANDING_SCHEMA_VERSION,
    EXPECTED_DOCUMENT_EXTRACTION_FIELDS,
    EXPECTED_VISUAL_OBSERVATION_FIELDS,
    LOW_CONFIDENCE_THRESHOLD,
    PROMOTION_GUIDANCE,
    VALID_DOCUMENT_EXTRACTOR_KINDS,
    VALID_DOCUMENT_OUTPUTS,
    VALID_EXTRACTOR_KINDS,
    VALID_VISUAL_CAPABILITIES,
    VISUAL_DOCUMENT_OUTPUTS,
    VISUAL_PREVIEW_SCHEMA_VERSION,
    VISUAL_REQUEST_SCHEMA_VERSION,
    VISUAL_SOURCE_TYPES,
)

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
    refs: list[dict[str, Any]] = []
    for item in value:
        ref = _normalize_source_ref(item)
        for field in ("requested_capabilities", "required_capabilities"):
            if field in ref:
                ref[field] = _normalize_visual_capabilities(ref.get(field))
        refs.append(ref)
    return refs

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
    return build_visual_coverage_model(visual_request=visual_request, artifacts=artifacts)

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

    missing_capabilities = (
        visual_coverage.get("missing_capabilities") or []
        if isinstance(visual_coverage, dict)
        else []
    )
    missing_ocr = [
        item
        for item in missing_capabilities
        if isinstance(item, dict) and item.get("capability") == "ocr_text"
    ]
    if missing_ocr and not any(warning.get("code") == "missing_ocr_coverage" for warning in warnings):
        warnings.append(
            {
                "code": "missing_ocr_coverage",
                "severity": "high",
                "missing_capability_count": len(missing_ocr),
                "message": "OCR coverage is missing for one or more requested image refs.",
            }
        )
    missing_table = [
        item
        for item in missing_capabilities
        if isinstance(item, dict) and item.get("capability") == "table_structure"
    ]
    if missing_table and not any(warning.get("code") == "missing_table_coverage" for warning in warnings):
        warnings.append(
            {
                "code": "missing_table_coverage",
                "severity": "high",
                "missing_capability_count": len(missing_table),
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

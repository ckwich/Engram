"""Engram Knowledge Contract citation helpers."""
from __future__ import annotations

from typing import Any


SUPPORTED_CITATION_LEVELS = {"artifact", "chunk", "document", "graph"}


def normalize_knowledge_citations(
    citations: list[dict[str, Any]],
    *,
    default_source: str = "memory_os",
) -> list[dict[str, Any]]:
    """Return EKC citations with explicit ids, levels, sources, and refs."""
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(citations or [], start=1):
        if not isinstance(raw, dict):
            continue
        citation = dict(raw)
        citation["citation_id"] = str(citation.get("citation_id") or f"cit_{index:03d}").strip()
        citation["level"] = str(citation.get("level") or _infer_level(citation)).strip()
        citation["source"] = str(citation.get("source") or default_source).strip()
        if citation["level"] == "chunk" and "chunk_id" in citation:
            citation["chunk_id"] = int(citation["chunk_id"])
        normalized.append(_drop_empty_optional_fields(citation))
    return normalized


def validate_knowledge_citation(citation: dict[str, Any]) -> list[str]:
    """Return stable validation error codes for one EKC citation."""
    if not isinstance(citation, dict):
        return ["not_object"]
    errors: list[str] = []
    level = str(citation.get("level") or "").strip()

    if not str(citation.get("citation_id") or "").strip():
        errors.append("missing_citation_id")
    if not level:
        errors.append("missing_level")
    elif level not in SUPPORTED_CITATION_LEVELS:
        errors.append("unsupported_level")
    if not str(citation.get("source") or "").strip():
        errors.append("missing_source")

    if level == "artifact" and not str(citation.get("artifact_id") or "").strip():
        errors.append("missing_artifact_id")
    if level == "chunk":
        if not str(citation.get("key") or "").strip():
            errors.append("missing_key")
        if "chunk_id" not in citation:
            errors.append("missing_chunk_id")
    if level == "document" and not (
        str(citation.get("document_id") or "").strip()
        or str(citation.get("source_ref") or "").strip()
    ):
        errors.append("missing_document_ref")
    if level == "graph" and not (
        str(citation.get("edge_id") or "").strip()
        or str(citation.get("path_id") or "").strip()
    ):
        errors.append("missing_graph_ref")
    return errors


def _infer_level(citation: dict[str, Any]) -> str:
    if citation.get("artifact_id"):
        return "artifact"
    if citation.get("key") or "chunk_id" in citation:
        return "chunk"
    if citation.get("document_id") or citation.get("source_ref"):
        return "document"
    if citation.get("edge_id") or citation.get("path_id"):
        return "graph"
    return ""


def _drop_empty_optional_fields(citation: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in citation.items() if value is not None}

"""General graph edge hygiene helpers for Memory OS."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import now_iso


def normalize_graph_edge_refs(edge: dict[str, Any]) -> dict[str, Any]:
    """Return an edge with compact stable keys added to known graph refs."""
    normalized = dict(edge)
    changed = False
    for field in ("from_ref", "to_ref"):
        ref = edge.get(field)
        if not isinstance(ref, dict):
            continue
        normalized_ref = normalize_graph_ref(ref)
        if normalized_ref != ref:
            normalized[field] = normalized_ref
            changed = True
    if changed:
        normalized["updated_at"] = now_iso()
    return normalized


def normalize_graph_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """Add a compact key to a graph ref without removing source-specific fields."""
    normalized = dict(ref)
    if str(normalized.get("key") or "").strip() or str(normalized.get("id") or "").strip():
        return normalized
    kind = str(normalized.get("kind") or "").strip()
    key = _inferred_ref_key(kind, normalized)
    if key:
        normalized["key"] = key
    return normalized


def graph_ref_identity_missing(edge: dict[str, Any]) -> bool:
    """Return whether either side lacks a compact key/id identity."""
    for field in ("from_ref", "to_ref"):
        ref = edge.get(field)
        if not isinstance(ref, dict):
            return True
        if not str(ref.get("key") or ref.get("id") or "").strip():
            return True
    return False


def _inferred_ref_key(kind: str, ref: dict[str, Any]) -> str | None:
    if kind == "document":
        return _first_text(ref, "document_id")
    if kind == "chunk":
        return _first_text(ref, "chunk_record_id") or _chunk_key(ref)
    if kind == "source":
        return _first_text(ref, "source_id", "source_uri", "sha256", "content_hash")
    if kind == "memory":
        return _first_text(ref, "memory_key")
    if kind == "concept":
        return _first_text(ref, "concept_id")
    if kind == "entity":
        return _first_text(ref, "entity_id")
    return None


def _chunk_key(ref: dict[str, Any]) -> str | None:
    document_id = _first_text(ref, "document_id")
    chunk_id = ref.get("chunk_id")
    if document_id and chunk_id is not None:
        return f"{document_id}:chunk:{chunk_id}"
    return None


def _first_text(ref: dict[str, Any], *fields: str) -> str | None:
    for field in fields:
        text = str(ref.get(field) or "").strip()
        if text:
            return text
    return None

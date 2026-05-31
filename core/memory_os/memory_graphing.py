"""Deterministic graph treatment for reviewed Memory OS memories."""
from __future__ import annotations

import re
from typing import Any

from core.memory_os._records import now_iso, read_record, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


MEMORY_METADATA_GRAPH_SOURCE = "memory_metadata_graph"


def graph_memory_metadata(
    *,
    ledger: MemoryOSLedger,
    graph: Any,
    memory: dict[str, Any],
    chunks: list[dict[str, Any]],
    created_by: str = "memory_os_runtime",
) -> dict[str, Any]:
    """Write deterministic, non-semantic graph coverage for a stored memory."""
    key = str(memory.get("key") or "").strip()
    if not key:
        return _receipt(graph_edges=[], missing_related_to=[], graph_write_performed=False)

    timestamp = now_iso()
    from_ref = {"kind": "memory", "key": key}
    edges: list[dict[str, Any]] = []
    concept_records: dict[str, dict[str, Any]] = {}
    entity_records: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        chunk_record_id = str(chunk.get("chunk_record_id") or "").strip()
        if not chunk_record_id:
            continue
        edges.append(
            _edge(
                from_ref=from_ref,
                to_ref={"kind": "chunk", "key": chunk_record_id},
                edge_type="contains",
                confidence=1.0,
                evidence=f"Memory '{key}' contains chunk '{chunk_record_id}'.",
                created_by=created_by,
                timestamp=timestamp,
            )
        )

    project = _optional_text(memory.get("project"))
    if project:
        entity_id = f"entity:project:{_slugify(project)}"
        entity_records[entity_id] = {
            "entity_id": entity_id,
            "name": project,
            "entity_type": "project",
            "source": MEMORY_METADATA_GRAPH_SOURCE,
            "status": "active",
            "created_by": created_by,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        edges.append(
            _edge(
                from_ref=from_ref,
                to_ref={"kind": "entity", "id": entity_id, "name": project},
                edge_type="applies_to",
                confidence=1.0,
                evidence=f"Memory '{key}' is scoped to project '{project}'.",
                created_by=created_by,
                timestamp=timestamp,
            )
        )

    domain = _optional_text(memory.get("domain"))
    if domain:
        concept_id = f"concept:domain:{_slugify(domain)}"
        concept_records[concept_id] = _concept_record(
            concept_id=concept_id,
            name=domain,
            concept_type="domain",
            created_by=created_by,
            timestamp=timestamp,
        )
        edges.append(
            _edge(
                from_ref=from_ref,
                to_ref={"kind": "concept", "id": concept_id, "name": domain},
                edge_type="mentions",
                confidence=1.0,
                evidence=f"Memory '{key}' declares domain '{domain}'.",
                created_by=created_by,
                timestamp=timestamp,
            )
        )

    for tag in _string_list(memory.get("tags")):
        concept_id = f"concept:tag:{_slugify(tag)}"
        concept_records[concept_id] = _concept_record(
            concept_id=concept_id,
            name=tag,
            concept_type="tag",
            created_by=created_by,
            timestamp=timestamp,
        )
        edges.append(
            _edge(
                from_ref=from_ref,
                to_ref={"kind": "concept", "id": concept_id, "name": tag},
                edge_type="mentions",
                confidence=1.0,
                evidence=f"Memory '{key}' is tagged '{tag}'.",
                created_by=created_by,
                timestamp=timestamp,
            )
        )

    missing_related_to: list[str] = []
    for target_key in _string_list(memory.get("related_to")):
        if read_record(ledger, "memories", target_key) is None:
            missing_related_to.append(target_key)
            continue
        edges.append(
            _edge(
                from_ref=from_ref,
                to_ref={"kind": "memory", "key": target_key},
                edge_type="related_to",
                confidence=1.0,
                evidence=f"Memory '{key}' explicitly lists related_to '{target_key}'.",
                created_by=created_by,
                timestamp=timestamp,
            )
        )

    if edges:
        graph.import_edges(edges)
    for concept in concept_records.values():
        upsert_record(ledger, "concepts", concept["concept_id"], concept)
    for entity in entity_records.values():
        upsert_record(ledger, "entities", entity["entity_id"], entity)
    return _receipt(
        graph_edges=edges,
        missing_related_to=missing_related_to,
        graph_write_performed=bool(edges),
        concept_ids=sorted(concept_records),
        entity_ids=sorted(entity_records),
    )


def _edge(
    *,
    from_ref: dict[str, Any],
    to_ref: dict[str, Any],
    edge_type: str,
    confidence: float,
    evidence: str,
    created_by: str,
    timestamp: str,
) -> dict[str, Any]:
    edge_id = stable_id(
        "edge",
        {
            "source": MEMORY_METADATA_GRAPH_SOURCE,
            "from_ref": from_ref,
            "to_ref": to_ref,
            "edge_type": edge_type,
        },
    )
    return {
        "edge_id": edge_id,
        "from_ref": dict(from_ref),
        "to_ref": dict(to_ref),
        "edge_type": edge_type,
        "confidence": confidence,
        "evidence": evidence,
        "source": MEMORY_METADATA_GRAPH_SOURCE,
        "status": "active",
        "created_by": created_by,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _concept_record(
    *,
    concept_id: str,
    name: str,
    concept_type: str,
    created_by: str,
    timestamp: str,
) -> dict[str, Any]:
    return {
        "concept_id": concept_id,
        "name": name,
        "concept_type": concept_type,
        "source": MEMORY_METADATA_GRAPH_SOURCE,
        "status": "active",
        "created_by": created_by,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _receipt(
    *,
    graph_edges: list[dict[str, Any]],
    missing_related_to: list[str],
    graph_write_performed: bool,
    concept_ids: list[str] | None = None,
    entity_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source": MEMORY_METADATA_GRAPH_SOURCE,
        "graph_edges_written": [edge["edge_id"] for edge in graph_edges],
        "concepts_written": concept_ids or [],
        "entities_written": entity_ids or [],
        "missing_related_to": missing_related_to,
        "write_performed": graph_write_performed,
        "active_memory_write_performed": False,
        "graph_write_performed": graph_write_performed,
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    normalized: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "value"

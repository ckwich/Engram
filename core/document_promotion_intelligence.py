"""Document draft promotion transaction helpers."""
from __future__ import annotations

from typing import Any

from core.document_intelligence_contracts import (
    DOCUMENT_PROMOTION_SCHEMA_VERSION,
)

from core.document_intelligence_shared import (
    _readable_stable_id,
    _stable_repr,
    _require_text,
    _optional_text,
    _normalize_proposed_items,
    _normalize_selected_indexes,
    _promoted_memory_payload,
    _promoted_graph_edge_payload,
    _normalize_bool,
)


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

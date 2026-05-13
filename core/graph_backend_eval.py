"""No-write graph backend parity and cross-document readiness gates."""
from __future__ import annotations

from typing import Any

from core.graph_manager import GRAPH_EDGE_TYPES, REQUIRED_EDGE_FIELDS


GRAPH_PARITY_SCHEMA_VERSION = "2026-05-13.graph_backend_parity.v1"
SUPPORTED_CROSS_BOOK_EDGE_TYPES = sorted(
    {
        "related_to",
        "same_as",
        "similar_to",
        "defines",
        "explains",
        "supports",
        "contradicts",
        "example_of",
        "depends_on",
        "cites",
        "contains",
        "illustrates",
        "supersedes",
        "extends",
        "refines",
        "applies_to",
        "synthesizes",
    }
    & GRAPH_EDGE_TYPES
)


def build_graph_backend_parity_report(edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Report graph edge migration readiness without writing graph storage."""
    if not isinstance(edges, list):
        raise ValueError("edges must be a list")

    issues: list[dict[str, Any]] = []
    edge_types: set[str] = set()
    cross_document_edges: list[dict[str, Any]] = []

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            issues.append(
                {
                    "code": "invalid_edge",
                    "edge_index": index,
                    "message": "edge must be an object",
                }
            )
            continue
        issues.extend(_edge_issues(index, edge))
        edge_type = str(edge.get("edge_type") or "")
        if edge_type:
            edge_types.add(edge_type)
        if _is_cross_document_edge(edge):
            cross_document_edges.append(edge)

    return {
        "schema_version": GRAPH_PARITY_SCHEMA_VERSION,
        "operation": "graph_backend_parity",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_graph_backend_changed": False,
        "status": "pass" if not issues else "fail",
        "edge_count": len(edges),
        "issue_count": len(issues),
        "issues": issues,
        "edge_types": sorted(edge_types),
        "cross_document_edge_count": len(cross_document_edges),
        "supported_cross_book_edge_types": SUPPORTED_CROSS_BOOK_EDGE_TYPES,
        "daemon_single_owner_required": True,
        "kuzu_promotion_gate": {
            "status": "blocked",
            "evidence": (
                "Kuzu must only run behind engramd single-owner mode; direct "
                "multi-process opens are not a safe graph promotion path."
            ),
        },
        "graph_contract": {
            "traversal_returns": "refs_and_evidence",
            "surprise_memory_body_loads": False,
        },
        "error": None,
    }


def skipped_graph_parity(reason: str) -> dict[str, Any]:
    """Return the stable skipped shape used by readiness reports."""
    return {
        "schema_version": GRAPH_PARITY_SCHEMA_VERSION,
        "operation": "graph_backend_parity",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_graph_backend_changed": False,
        "status": "skipped",
        "edge_count": 0,
        "issue_count": 0,
        "issues": [],
        "edge_types": [],
        "cross_document_edge_count": 0,
        "supported_cross_book_edge_types": SUPPORTED_CROSS_BOOK_EDGE_TYPES,
        "daemon_single_owner_required": True,
        "kuzu_promotion_gate": {
            "status": "blocked",
            "evidence": reason,
        },
        "graph_contract": {
            "traversal_returns": "refs_and_evidence",
            "surprise_memory_body_loads": False,
        },
        "error": None,
        "reason": reason,
    }


def _edge_issues(index: int, edge: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for field in sorted(REQUIRED_EDGE_FIELDS):
        value = edge.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(
                {
                    "code": "missing_required_field",
                    "edge_index": index,
                    "field": field,
                }
            )
    edge_type = edge.get("edge_type")
    if edge_type and edge_type not in GRAPH_EDGE_TYPES:
        issues.append(
            {
                "code": "unsupported_edge_type",
                "edge_index": index,
                "edge_type": edge_type,
            }
        )
    return issues


def _is_cross_document_edge(edge: dict[str, Any]) -> bool:
    from_ref = edge.get("from_ref")
    to_ref = edge.get("to_ref")
    if not isinstance(from_ref, dict) or not isinstance(to_ref, dict):
        return False

    from_document = _document_identity(from_ref)
    to_document = _document_identity(to_ref)
    return bool(from_document and to_document and from_document != to_document)


def _document_identity(ref: dict[str, Any]) -> str | None:
    for field in ("document_id", "source_document_id", "book_id", "source_id"):
        value = ref.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

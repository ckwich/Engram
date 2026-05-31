"""Focused graph reference identity repair service for Memory OS."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import hash_payload, list_records
from core.memory_os.graph_hygiene import (
    graph_ref_identity_missing,
    normalize_graph_edge_refs,
)


class GraphReferenceRepairService:
    """Add compact key/id identities to graph edges without changing meaning."""

    def __init__(self, *, ledger: Any, graph: Any, transactions: Any) -> None:
        self.ledger = ledger
        self.graph = graph
        self.transactions = transactions

    def repair_graph_edge_refs(
        self,
        *,
        source: str | None = None,
        limit: int = 1000,
        accept: bool = False,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        normalized_source = _optional_text(source)
        normalized_limit = max(int(limit), 1)
        candidates = []
        for edge in list_records(self.ledger, "graph_edges"):
            if normalized_source and edge.get("source") != normalized_source:
                continue
            repaired = normalize_graph_edge_refs(edge)
            if repaired != edge:
                candidates.append(
                    {
                        "edge_id": edge.get("edge_id"),
                        "source": edge.get("source"),
                        "edge_type": edge.get("edge_type"),
                        "from_ref_before": edge.get("from_ref"),
                        "to_ref_before": edge.get("to_ref"),
                        "from_ref_after": repaired.get("from_ref"),
                        "to_ref_after": repaired.get("to_ref"),
                    }
                )
            if len(candidates) >= normalized_limit:
                break

        response = {
            "operation": "repair_graph_edge_refs",
            "status": "prepared" if candidates else "noop",
            "source": normalized_source,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }
        if not accept:
            return response
        if not candidates:
            return response
        reviewer = _optional_text(approved_by)
        if not reviewer:
            response["status"] = "policy_denied"
            response["error"] = {
                "code": "approved_by_required",
                "message": "approved_by is required when accept=True.",
            }
            return response

        candidate_ids = {str(candidate["edge_id"]) for candidate in candidates if candidate.get("edge_id")}
        repairs = []
        for edge in list_records(self.ledger, "graph_edges"):
            if str(edge.get("edge_id") or "") not in candidate_ids:
                continue
            repaired = normalize_graph_edge_refs(edge)
            if repaired != edge:
                repaired["repaired_by"] = reviewer
                repairs.append(repaired)
        if repairs:
            self.graph.import_edges(repairs)
        receipt = self.transactions.promote(
            operation_kind="repair_graph_edge_refs",
            proposed_writes=[{"table": "graph_edges", "id": edge["edge_id"]} for edge in repairs],
            idempotency_key=f"repair_graph_edge_refs:{normalized_source or 'all'}:{hash_payload(sorted(candidate_ids))}",
            affected_refs=[
                {"kind": "graph_edge", "edge_id": str(edge.get("edge_id") or "")}
                for edge in repairs
            ],
        )
        remaining_missing = sum(
            1
            for edge in list_records(self.ledger, "graph_edges")
            if (not normalized_source or edge.get("source") == normalized_source)
            and graph_ref_identity_missing(edge)
        )
        return {
            **response,
            "status": "ok",
            "write_performed": bool(repairs),
            "graph_write_performed": bool(repairs),
            "repaired_count": len(repairs),
            "remaining_missing_identity_count": remaining_missing,
            "transaction_receipt": receipt,
        }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

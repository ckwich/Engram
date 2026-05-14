"""Bounded EKC graph evidence packets."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import list_records
from core.memory_os.knowledge_citations import normalize_knowledge_citations
from core.memory_os.ledger import MemoryOSLedger


CONTRADICTION_EDGE_TYPES = {"contradicts", "supersedes"}


def build_graph_evidence(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None = None,
    max_records: int = 12,
) -> dict[str, Any]:
    """Build bounded graph evidence without loading neighbor memory bodies."""
    stored_edges = _matching_edges(
        list_records(ledger, "graph_edges"),
        project=project,
        focus=focus,
    )
    draft_edges = _matching_draft_graph_proposals(
        list_records(ledger, "drafts"),
        project=project,
        focus=focus,
    )
    edges = (stored_edges + draft_edges)[: max(int(max_records), 1)]
    if not edges:
        return _no_answer("No graph edges or draft graph proposals matched the requested evidence packet.")

    paths = [_path_payload(index, edge) for index, edge in enumerate(edges, start=1)]
    contradictions = [
        path["edges"][0]
        for path in paths
        if path["edges"][0].get("edge_type") in CONTRADICTION_EDGE_TYPES
    ]
    citations = [
        {
            "level": "graph",
            "edge_id": path["edges"][0]["edge_id"],
            "path_id": path["path_id"],
        }
        for path in paths
    ]
    answer = {
        "packet_type": "graph_evidence",
        "project": project,
        "path_limit": max(int(max_records), 1),
        "edge_count": len(edges),
        "draft_proposal_count": sum(1 for edge in edges if edge.get("status") == "draft"),
        "evidence_paths": paths,
        "contradiction_count": len(contradictions),
        "contradictions": contradictions,
        "write_performed": False,
        "active_memory_write_performed": False,
    }
    return {
        "status": "partial" if contradictions else "ok",
        "answer": answer,
        "citations": normalize_knowledge_citations(citations, default_source="memory_os"),
        "omissions": [],
        "errors": [
            {
                "code": "contradictions_present",
                "message": "Graph evidence includes contradiction or supersession edges.",
            }
        ]
        if contradictions
        else [],
        "source_reads": len(edges),
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _no_answer(message: str) -> dict[str, Any]:
    return {
        "status": "no_answer",
        "answer": None,
        "citations": [],
        "omissions": [{"code": "no_graph_evidence", "message": message}],
        "errors": [{"code": "no_graph_evidence", "message": message}],
        "source_reads": 0,
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _matching_edges(
    edges: list[dict[str, Any]],
    *,
    project: str,
    focus: list[str] | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for edge in edges:
        edge_project = str(edge.get("project") or "").strip()
        if edge_project and edge_project != project:
            continue
        if _matches_focus(edge, focus):
            matches.append(edge)
    return matches


def _matching_draft_graph_proposals(
    drafts: list[dict[str, Any]],
    *,
    project: str,
    focus: list[str] | None,
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for draft in drafts:
        draft_project = str(draft.get("project") or "").strip()
        if draft_project and draft_project != project:
            continue
        for edge in draft.get("candidate_graph_edges") or []:
            if not isinstance(edge, dict):
                continue
            proposal = {
                **edge,
                "edge_id": edge.get("edge_id") or edge.get("proposal_id"),
                "status": edge.get("status") or "draft",
                "created_by": edge.get("created_by") or draft.get("created_by"),
                "created_at": edge.get("created_at") or draft.get("created_at"),
                "updated_at": edge.get("updated_at") or draft.get("updated_at"),
                "project": draft_project or edge.get("project"),
            }
            if _matches_focus(proposal, focus) or _matches_focus(draft, focus):
                proposals.append(proposal)
    return proposals


def _path_payload(index: int, edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "path_id": f"path_{index:03d}",
        "edges": [_edge_payload(edge)],
        "evidence": [str(edge.get("evidence") or "")],
    }


def _edge_payload(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": edge.get("edge_id"),
        "from_ref": edge.get("from_ref") if isinstance(edge.get("from_ref"), dict) else {},
        "to_ref": edge.get("to_ref") if isinstance(edge.get("to_ref"), dict) else {},
        "edge_type": edge.get("edge_type"),
        "confidence": float(edge.get("confidence") or 0.0),
        "evidence": str(edge.get("evidence") or ""),
        "source": edge.get("source"),
        "status": edge.get("status"),
        "created_by": edge.get("created_by"),
        "created_at": edge.get("created_at"),
        "updated_at": edge.get("updated_at"),
    }


def _matches_focus(record: dict[str, Any], focus: list[str] | None) -> bool:
    terms = [str(term).strip().lower() for term in focus or [] if str(term).strip()]
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return any(term in haystack for term in terms)

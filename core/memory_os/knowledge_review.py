"""Read-only EKC review-preparation packet builder."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import list_records
from core.memory_os.knowledge_citations import normalize_knowledge_citations
from core.memory_os.knowledge_pr_read_model import (
    build_knowledge_pr_review_state,
    knowledge_pr_citations,
)
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.project_identity import resolve_project_filter_values


def build_review_preparation(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None = None,
    max_records: int = 12,
) -> dict[str, Any]:
    """Build a review packet from draft, document, and coverage records without writing."""
    project_values = _project_values(ledger, project)
    documents = _project_documents(list_records(ledger, "documents"), project_values=project_values)
    document_by_id = {str(document.get("document_id") or ""): document for document in documents}
    knowledge_pr_state = build_knowledge_pr_review_state(
        ledger,
        project_values=project_values,
        focus=focus,
        limit=max_records,
    )
    drafts = _matching_drafts(
        list_records(ledger, "drafts"),
        project_values=project_values,
        focus=focus,
        document_by_id=document_by_id,
    )
    receipts = [
        receipt
        for receipt in list_records(ledger, "retrieval_receipts")
        if str(receipt.get("document_id") or "") in document_by_id
    ]
    if focus:
        receipts = [receipt for receipt in receipts if _matches_focus(receipt, focus) or _matches_focus(document_by_id.get(str(receipt.get("document_id") or ""), {}), focus)]
    if not drafts and not receipts and not knowledge_pr_state["items"]:
        return _no_answer("No drafts or quality receipts matched the requested review preparation.")

    limited_drafts = drafts[: max(int(max_records), 1)]
    quality_warnings = _quality_warnings(receipts)
    review_items = [
        _review_item(draft, document_by_id=document_by_id, quality_warnings=quality_warnings)
        for draft in limited_drafts
    ]
    cited_documents = _cited_documents(review_items, quality_warnings, document_by_id)
    status = "partial" if quality_warnings or knowledge_pr_state["ci_blocked_count"] else "ok"
    answer = {
        "packet_type": "review_preparation",
        "project": project,
        "draft_count": len(review_items),
        "quality_warning_count": len(quality_warnings),
        "knowledge_pr_count": knowledge_pr_state["knowledge_pr_count"],
        "memory_ci_run_count": knowledge_pr_state["memory_ci_run_count"],
        "knowledge_pr_review_items": knowledge_pr_state["items"],
        "knowledge_pr_review_state": knowledge_pr_state,
        "review_items": review_items,
        "quality_warnings": quality_warnings,
        "write_performed": False,
        "active_memory_write_performed": False,
    }
    errors = (
        [
            {
                "code": "review_warnings_present",
                "message": "Review packet includes quality warnings that should be resolved before promotion.",
            }
        ]
        if quality_warnings
        else []
    )
    if knowledge_pr_state["ci_blocked_count"]:
        errors.append(
            {
                "code": "knowledge_pr_ci_attention_required",
                "message": "One or more Knowledge PRs have blocked Memory CI gates.",
            }
        )
    return {
        "status": status,
        "answer": answer,
        "citations": normalize_knowledge_citations(
            [
                *_document_citation_list(cited_documents),
                *knowledge_pr_citations(knowledge_pr_state),
            ],
            default_source="memory_os",
        ),
        "omissions": [],
        "errors": errors,
        "source_reads": (
            len(limited_drafts)
            + len(cited_documents)
            + len(receipts)
            + knowledge_pr_state["knowledge_pr_count"]
            + knowledge_pr_state["memory_ci_run_count"]
        ),
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _no_answer(message: str) -> dict[str, Any]:
    return {
        "status": "no_answer",
        "answer": None,
        "citations": [],
        "omissions": [{"code": "no_review_records", "message": message}],
        "errors": [{"code": "no_review_records", "message": message}],
        "source_reads": 0,
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _project_documents(records: list[dict[str, Any]], *, project_values: set[str]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if not str(record.get("project") or "").strip() or str(record.get("project") or "").strip() in project_values
    ]


def _matching_drafts(
    drafts: list[dict[str, Any]],
    *,
    project_values: set[str],
    focus: list[str] | None,
    document_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for draft in drafts:
        document_id = str(draft.get("document_id") or "")
        draft_project = str(draft.get("project") or "").strip()
        if draft_project and draft_project not in project_values:
            continue
        if document_id and document_id not in document_by_id and not draft_project:
            continue
        if _matches_focus(draft, focus) or _matches_focus(document_by_id.get(document_id, {}), focus):
            matches.append(draft)
    return matches


def _review_item(
    draft: dict[str, Any],
    *,
    document_by_id: dict[str, dict[str, Any]],
    quality_warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    document_id = str(draft.get("document_id") or "")
    document = document_by_id.get(document_id, {})
    return {
        "draft_id": _draft_id(draft),
        "record_type": draft.get("record_type") or draft.get("type") or "draft",
        "document_id": document_id or None,
        "document_title": document.get("title") or (document.get("document") or {}).get("title"),
        "review_status": draft.get("review_status") or draft.get("status") or "candidate",
        "promotion_required": bool(draft.get("promotion_required", True)),
        "proposed_memory_count": len(draft.get("proposed_memories") or []),
        "candidate_graph_edge_count": len(draft.get("candidate_graph_edges") or []),
        "quality_warning_count": sum(1 for warning in quality_warnings if warning.get("document_id") == document_id),
    }


def _quality_warnings(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for receipt in receipts:
        document_id = str(receipt.get("document_id") or "")
        if int(receipt.get("low_confidence_region_count") or 0) > 0:
            warnings.append(
                {
                    "code": "low_confidence_regions",
                    "severity": "medium",
                    "document_id": document_id,
                    "message": f"{document_id} has low-confidence extracted regions.",
                }
            )
        if int(receipt.get("skipped_region_count") or 0) > 0:
            warnings.append(
                {
                    "code": "skipped_regions",
                    "severity": "high",
                    "document_id": document_id,
                    "message": f"{document_id} has skipped visual or table regions.",
                }
            )
    return warnings


def _cited_documents(
    review_items: list[dict[str, Any]],
    quality_warnings: list[dict[str, Any]],
    document_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    document_ids = []
    for item in review_items:
        if item.get("document_id"):
            document_ids.append(str(item["document_id"]))
    for warning in quality_warnings:
        if warning.get("document_id"):
            document_ids.append(str(warning["document_id"]))
    seen: set[str] = set()
    documents: list[dict[str, Any]] = []
    for document_id in document_ids:
        if document_id in seen or document_id not in document_by_id:
            continue
        seen.add(document_id)
        documents.append(document_by_id[document_id])
    return documents


def _document_citation_list(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_document_citation(document) for document in documents]


def _document_citation(document: dict[str, Any]) -> dict[str, Any]:
    source_ref = document.get("source_ref") if isinstance(document.get("source_ref"), dict) else {}
    return {
        "level": "document",
        "document_id": document.get("document_id"),
        "source_ref": source_ref.get("source_uri"),
    }


def _draft_id(draft: dict[str, Any]) -> str:
    for field in ("draft_id", "packet_id", "artifact_id", "id"):
        if draft.get(field):
            return str(draft[field])
    return "draft:unknown"


def _matches_focus(record: dict[str, Any], focus: list[str] | None) -> bool:
    terms = [str(term).strip().lower() for term in focus or [] if str(term).strip()]
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return any(term in haystack for term in terms)


def _project_values(ledger: MemoryOSLedger, project: str) -> set[str]:
    return set(resolve_project_filter_values(ledger, project)) or {project}

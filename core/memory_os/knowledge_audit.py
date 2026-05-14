"""Deterministic EKC evidence audit helpers."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import list_records
from core.memory_os.knowledge_citations import (
    normalize_knowledge_citations,
    validate_knowledge_citation,
)
from core.memory_os.ledger import MemoryOSLedger


def build_evidence_audit(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None = None,
    max_records: int = 12,
) -> dict[str, Any]:
    """Audit ledgered evidence metadata without reading or writing memory bodies."""
    documents = _matching_records(list_records(ledger, "documents"), project=project, focus=focus)
    document_by_id = {str(document.get("document_id") or ""): document for document in documents}
    artifacts = _matching_artifacts(
        list_records(ledger, "knowledge_artifacts"),
        project=project,
        focus=focus,
        document_by_id=document_by_id,
    )
    receipts = [
        receipt
        for receipt in list_records(ledger, "retrieval_receipts")
        if _receipt_matches(receipt, document_by_id=document_by_id, focus=focus)
    ]
    drafts = _matching_records(list_records(ledger, "drafts"), project=project, focus=focus)
    if not artifacts and not receipts and not drafts:
        return _no_answer("No artifact, coverage, or draft evidence records matched the audit request.")

    limited_artifacts = artifacts[: max(int(max_records), 1)]
    limited_receipts = receipts[: max(int(max_records), 1)]
    limited_drafts = drafts[: max(int(max_records), 1)]
    findings: list[dict[str, Any]] = []
    for artifact in limited_artifacts:
        findings.extend(_artifact_findings(artifact))
    for receipt in limited_receipts:
        findings.extend(_coverage_findings(receipt))
    for draft in limited_drafts:
        findings.extend(_graph_proposal_findings(draft))

    citations = _artifact_citations(limited_artifacts) + _document_citations(limited_receipts, document_by_id)
    answer = {
        "audit_type": "evidence_audit",
        "project": project,
        "artifact_count": len(limited_artifacts),
        "coverage_receipt_count": len(limited_receipts),
        "draft_count": len(limited_drafts),
        "finding_count": len(findings),
        "findings": findings,
        "write_performed": False,
        "active_memory_write_performed": False,
    }
    return {
        "status": "partial" if findings else "ok",
        "answer": answer,
        "citations": normalize_knowledge_citations(citations, default_source="memory_os"),
        "omissions": [],
        "errors": [
            {
                "code": "evidence_audit_findings",
                "message": "Evidence audit found stale, weak, missing, or risky support.",
            }
        ]
        if findings
        else [],
        "source_reads": len(limited_artifacts) + len(limited_receipts) + len(limited_drafts) + len(document_by_id),
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _no_answer(message: str) -> dict[str, Any]:
    return {
        "status": "no_answer",
        "answer": None,
        "citations": [],
        "omissions": [{"code": "no_audit_records", "message": message}],
        "errors": [{"code": "no_audit_records", "message": message}],
        "source_reads": 0,
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _artifact_findings(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    artifact_id = str(artifact.get("artifact_id") or "")
    staleness = artifact.get("staleness") if isinstance(artifact.get("staleness"), dict) else {}
    state = str(staleness.get("state") or "unknown")
    if state not in {"fresh", "unknown"}:
        findings.append(
            {
                "code": "stale_artifact",
                "severity": "high",
                "ref": artifact_id,
                "message": f"{artifact_id} is marked {state}.",
            }
        )
    coverage_receipt = artifact.get("coverage_receipt") if isinstance(artifact.get("coverage_receipt"), dict) else {}
    coverage_missing = {str(item) for item in coverage_receipt.get("coverage_missing") or []}
    if "visual" in coverage_missing:
        findings.append(
            {
                "code": "unresolved_visual_evidence",
                "severity": "high",
                "ref": artifact_id,
                "message": f"{artifact_id} is missing required visual evidence coverage.",
            }
        )
    if "ocr" in coverage_missing:
        findings.append(
            {
                "code": "missing_ocr_coverage",
                "severity": "high",
                "ref": artifact_id,
                "message": f"{artifact_id} is missing required OCR coverage.",
            }
        )
    if "table" in coverage_missing:
        findings.append(
            {
                "code": "missing_table_coverage",
                "severity": "high",
                "ref": artifact_id,
                "message": f"{artifact_id} is missing required table coverage.",
            }
        )
    citations = list(artifact.get("citations") or [])
    if not citations:
        findings.append(
            {
                "code": "missing_citations",
                "severity": "high",
                "ref": artifact_id,
                "message": f"{artifact_id} has no citations.",
            }
        )
    for index, citation in enumerate(citations):
        citation_errors = validate_knowledge_citation(citation)
        if citation_errors:
            findings.append(
                {
                    "code": "invalid_citation",
                    "severity": "high",
                    "ref": artifact_id,
                    "message": f"{artifact_id} citation {index} is invalid: {', '.join(citation_errors)}.",
                }
            )
    return findings


def _coverage_findings(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    document_id = str(receipt.get("document_id") or "")
    low_confidence = int(receipt.get("low_confidence_region_count") or 0)
    skipped = int(receipt.get("skipped_region_count") or 0)
    chunk_count = int(receipt.get("chunk_count") or 0)
    claim_count = int(receipt.get("claim_count") or 0)
    if low_confidence > 0 or skipped > 0:
        findings.append(
            {
                "code": "coverage_risk",
                "severity": "medium" if skipped == 0 else "high",
                "ref": document_id,
                "message": f"{document_id} has low-confidence or skipped evidence regions.",
            }
        )
    if claim_count > 0 and chunk_count == 0:
        findings.append(
            {
                "code": "weak_claim_support",
                "severity": "high",
                "ref": document_id,
                "message": f"{document_id} has claims without chunk evidence.",
            }
        )
    return findings


def _graph_proposal_findings(draft: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    draft_id = _draft_id(draft)
    for edge in draft.get("candidate_graph_edges") or []:
        evidence = edge.get("evidence") if isinstance(edge, dict) else None
        if not evidence:
            findings.append(
                {
                    "code": "graph_proposal_needs_evidence",
                    "severity": "medium",
                    "ref": draft_id,
                    "message": f"{draft_id} includes a graph proposal without evidence.",
                }
            )
            break
    return findings


def _artifact_citations(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "level": "artifact",
            "artifact_id": artifact.get("artifact_id"),
        }
        for artifact in artifacts
        if artifact.get("artifact_id")
    ]


def _document_citations(
    receipts: list[dict[str, Any]],
    document_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for receipt in receipts:
        document_id = str(receipt.get("document_id") or "")
        if document_id in seen:
            continue
        seen.add(document_id)
        document = document_by_id.get(document_id, {})
        source_ref = document.get("source_ref") if isinstance(document.get("source_ref"), dict) else {}
        citations.append(
            {
                "level": "document",
                "document_id": document_id,
                "source_ref": source_ref.get("source_uri"),
            }
        )
    return citations


def _matching_records(
    records: list[dict[str, Any]],
    *,
    project: str,
    focus: list[str] | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in records:
        record_project = str(record.get("project") or "").strip()
        if record_project and record_project != project:
            continue
        if _matches_focus(record, focus):
            matches.append(record)
    return matches


def _matching_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    project: str,
    focus: list[str] | None,
    document_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in artifacts:
        record_project = str(artifact.get("project") or "").strip()
        if record_project and record_project != project:
            continue
        document_id = str(artifact.get("document_id") or "")
        if not (_matches_focus(artifact, focus) or document_id in document_by_id):
            continue
        artifact_id = str(artifact.get("artifact_id") or id(artifact))
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        matches.append(artifact)
    return matches


def _receipt_matches(
    receipt: dict[str, Any],
    *,
    document_by_id: dict[str, dict[str, Any]],
    focus: list[str] | None,
) -> bool:
    document_id = str(receipt.get("document_id") or "")
    document = document_by_id.get(document_id)
    if document is None:
        return False
    return _matches_focus(receipt, focus) or _matches_focus(document, focus)


def _matches_focus(record: dict[str, Any], focus: list[str] | None) -> bool:
    terms = [str(term).strip().lower() for term in focus or [] if str(term).strip()]
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return any(term in haystack for term in terms)


def _draft_id(draft: dict[str, Any]) -> str:
    for field in ("draft_id", "packet_id", "artifact_id", "id"):
        if draft.get(field):
            return str(draft[field])
    return "draft:unknown"

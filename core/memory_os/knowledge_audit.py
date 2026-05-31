"""Deterministic EKC evidence audit helpers."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import list_records
from core.memory_os.knowledge_citations import (
    normalize_knowledge_citations,
    validate_knowledge_citation,
)
from core.memory_os.knowledge_pr_read_model import (
    build_knowledge_pr_review_state,
    knowledge_pr_citations,
)
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.project_identity import resolve_project_filter_values


def build_evidence_audit(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None = None,
    max_records: int = 12,
) -> dict[str, Any]:
    """Audit ledgered evidence metadata without reading or writing memory bodies."""
    project_values = _project_values(ledger, project)
    documents = _matching_records(list_records(ledger, "documents"), project_values=project_values, focus=focus)
    document_by_id = {str(document.get("document_id") or ""): document for document in documents}
    artifacts = _matching_artifacts(
        list_records(ledger, "knowledge_artifacts"),
        project_values=project_values,
        focus=focus,
        document_by_id=document_by_id,
    )
    receipts = [
        receipt
        for receipt in list_records(ledger, "retrieval_receipts")
        if _receipt_matches(receipt, document_by_id=document_by_id, focus=focus)
    ]
    drafts = _matching_records(list_records(ledger, "drafts"), project_values=project_values, focus=focus)
    benchmark_runs = _matching_records(
        list_records(ledger, "benchmark_runs"),
        project_values=project_values,
        focus=focus,
    )
    knowledge_pr_state = build_knowledge_pr_review_state(
        ledger,
        project_values=project_values,
        focus=focus,
        limit=max_records,
    )
    if not artifacts and not receipts and not drafts and not benchmark_runs and not knowledge_pr_state["items"]:
        return _no_answer("No artifact, coverage, or draft evidence records matched the audit request.")

    limited_artifacts = artifacts[: max(int(max_records), 1)]
    limited_receipts = receipts[: max(int(max_records), 1)]
    limited_drafts = drafts[: max(int(max_records), 1)]
    limited_benchmark_runs = benchmark_runs[: max(int(max_records), 1)]
    findings: list[dict[str, Any]] = []
    for artifact in limited_artifacts:
        findings.extend(_artifact_findings(artifact))
    for receipt in limited_receipts:
        findings.extend(_coverage_findings(receipt))
    for draft in limited_drafts:
        findings.extend(_graph_proposal_findings(draft))
    for benchmark_run in limited_benchmark_runs:
        findings.extend(_benchmark_run_findings(benchmark_run))
    for item in knowledge_pr_state["items"]:
        findings.extend(_knowledge_pr_findings(item))

    citations = (
        _artifact_citations(limited_artifacts)
        + _document_citations(limited_receipts, document_by_id)
        + _benchmark_run_citations(limited_benchmark_runs)
        + knowledge_pr_citations(knowledge_pr_state)
    )
    answer = {
        "audit_type": "evidence_audit",
        "project": project,
        "artifact_count": len(limited_artifacts),
        "coverage_receipt_count": len(limited_receipts),
        "draft_count": len(limited_drafts),
        "benchmark_run_count": len(limited_benchmark_runs),
        "knowledge_pr_count": knowledge_pr_state["knowledge_pr_count"],
        "memory_ci_run_count": knowledge_pr_state["memory_ci_run_count"],
        "ci_blocked_count": knowledge_pr_state["ci_blocked_count"],
        "mergeable_count": knowledge_pr_state["mergeable_count"],
        "knowledge_pr_review_state": knowledge_pr_state,
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
        "source_reads": (
            len(limited_artifacts)
            + len(limited_receipts)
            + len(limited_drafts)
            + len(limited_benchmark_runs)
            + len(document_by_id)
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


def _benchmark_run_findings(run: dict[str, Any]) -> list[dict[str, Any]]:
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    if summary.get("status") == "pass":
        return []
    return [
        {
            "code": "benchmark_run_failed",
            "severity": "warning",
            "run_id": run.get("run_id"),
            "message": "Benchmark run did not pass.",
        }
    ]


def _knowledge_pr_findings(item: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    pr_id = str(item.get("knowledge_pr_id") or "")
    ci_status = str(item.get("latest_ci_status") or (item.get("ci_summary") or {}).get("status") or "")
    blocking_gate_ids = [str(gate_id) for gate_id in item.get("blocking_gate_ids") or []]
    if item.get("status") in {"open", "ci_blocked"} and ci_status == "not_run":
        findings.append(
            {
                "code": "memory_ci_not_run",
                "severity": "medium",
                "ref": pr_id,
                "message": f"{pr_id} has not run Memory CI.",
            }
        )
    if blocking_gate_ids:
        findings.append(
            {
                "code": "memory_ci_blocked",
                "severity": "high",
                "ref": pr_id,
                "gate_ids": blocking_gate_ids,
                "message": f"{pr_id} has blocked Memory CI gates.",
            }
        )
    if int(item.get("operation_missing_evidence_count") or 0) > 0:
        findings.append(
            {
                "code": "knowledge_pr_missing_provenance",
                "severity": "high",
                "ref": pr_id,
                "message": f"{pr_id} has proposed operations without evidence refs.",
            }
        )
    if item.get("document_ref_count") and "gate_document_coverage" in blocking_gate_ids:
        findings.append(
            {
                "code": "knowledge_pr_missing_document_completion",
                "severity": "high",
                "ref": pr_id,
                "message": f"{pr_id} has document refs blocked on document coverage.",
            }
        )
    if item.get("status") == "merged" and (
        ci_status != "passed" or blocking_gate_ids or int(item.get("ci_waiver_count") or 0) > 0
    ):
        findings.append(
            {
                "code": "knowledge_pr_merge_without_clean_ci",
                "severity": "high",
                "ref": pr_id,
                "message": f"{pr_id} was merged without clean Memory CI.",
            }
        )
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


def _benchmark_run_citations(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for run in runs:
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            continue
        artifact_id = str(run.get("artifact_id") or "").strip()
        citations.append(
            {
                "level": "artifact" if artifact_id else "memory_ci",
                "source": "memory_os",
                "artifact_id": artifact_id or None,
                "ci_run_id": None if artifact_id else run_id,
                "benchmark_run_id": run_id,
            }
        )
    return citations


def _matching_records(
    records: list[dict[str, Any]],
    *,
    project_values: set[str],
    focus: list[str] | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in records:
        record_project = str(record.get("project") or "").strip()
        if record_project and record_project not in project_values:
            continue
        if _matches_focus(record, focus):
            matches.append(record)
    return matches


def _matching_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    project_values: set[str],
    focus: list[str] | None,
    document_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in artifacts:
        record_project = str(artifact.get("project") or "").strip()
        if record_project and record_project not in project_values:
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


def _project_values(ledger: MemoryOSLedger, project: str) -> set[str]:
    return set(resolve_project_filter_values(ledger, project)) or {project}


def _draft_id(draft: dict[str, Any]) -> str:
    for field in ("draft_id", "packet_id", "artifact_id", "id"):
        if draft.get(field):
            return str(draft[field])
    return "draft:unknown"

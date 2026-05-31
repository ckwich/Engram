"""Read-only Knowledge PR and Memory CI review state helpers."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import list_records
from core.memory_os.ledger import MemoryOSLedger


OPEN_PR_STATUSES = {"open", "ci_blocked", "mergeable"}
BLOCKING_CI_STATUSES = {"blocked", "error"}


def build_knowledge_pr_review_state(
    ledger: MemoryOSLedger,
    *,
    project_values: set[str] | None = None,
    focus: list[str] | None = None,
    document_ids: set[str] | None = None,
    source_uris: set[str] | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    """Summarize Knowledge PR review state without merging or promoting anything."""
    bounded_limit = max(int(limit), 1)
    branch_records = [
        branch
        for branch in list_records(ledger, "knowledge_branches")
        if _matches_project(branch, project_values)
        and _matches_scope_refs(branch, document_ids=document_ids, source_uris=source_uris)
        and _matches_focus(branch, focus)
    ]
    pr_records = [
        pr
        for pr in list_records(ledger, "knowledge_prs")
        if _matches_project(pr, project_values)
        and _matches_scope_refs(pr, document_ids=document_ids, source_uris=source_uris)
        and (_matches_focus(pr, focus) or document_ids or source_uris)
    ]
    pr_ids = {str(pr.get("knowledge_pr_id") or "") for pr in pr_records}
    ci_records = [
        ci
        for ci in list_records(ledger, "memory_ci_runs")
        if str(ci.get("knowledge_pr_id") or "") in pr_ids
    ]
    latest_ci_by_pr = _latest_ci_by_pr(ci_records)
    items = [_knowledge_pr_item(pr, latest_ci_by_pr.get(str(pr.get("knowledge_pr_id") or ""))) for pr in _latest(pr_records, bounded_limit)]
    merge_transaction_refs = _merge_transaction_refs(
        list_records(ledger, "transactions"),
        pr_ids=pr_ids,
        limit=bounded_limit,
    )
    latest_blocking_issues = _latest_blocking_issues(items, limit=bounded_limit)
    blocked_document_coverage_refs = _blocked_document_coverage_refs(pr_records, latest_ci_by_pr, limit=bounded_limit)
    return {
        "branch_count": len(branch_records),
        "knowledge_pr_count": len(pr_records),
        "pull_request_count": len(pr_records),
        "memory_ci_run_count": len(ci_records),
        "open_count": sum(1 for pr in pr_records if _pr_status(pr) in OPEN_PR_STATUSES),
        "mergeable_count": sum(1 for pr in pr_records if _pr_status(pr) == "mergeable"),
        "merged_count": sum(1 for pr in pr_records if _pr_status(pr) == "merged"),
        "ci_blocked_count": sum(1 for pr in pr_records if _is_ci_blocked(pr, latest_ci_by_pr.get(str(pr.get("knowledge_pr_id") or "")))),
        "blocked_ci_gate_count": sum(len(_blocking_gate_ids(pr, latest_ci_by_pr.get(str(pr.get("knowledge_pr_id") or "")))) for pr in pr_records),
        "items": items,
        "latest_ci_runs": _latest(ci_records, bounded_limit),
        "latest_blocking_issues": latest_blocking_issues,
        "blocked_document_coverage_refs": blocked_document_coverage_refs,
        "merge_transaction_refs": merge_transaction_refs,
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def knowledge_pr_citations(state: dict[str, Any], *, include_ci: bool = True) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in state.get("items") or []:
        pr_id = str(item.get("knowledge_pr_id") or "").strip()
        if pr_id:
            citations.append({"level": "knowledge_pr", "knowledge_pr_id": pr_id})
        ci_run_id = str(item.get("latest_ci_run_id") or "").strip()
        if include_ci and ci_run_id:
            citations.append({"level": "memory_ci", "ci_run_id": ci_run_id, "knowledge_pr_id": pr_id})
    return citations


def _knowledge_pr_item(pr: dict[str, Any], latest_ci: dict[str, Any] | None) -> dict[str, Any]:
    pr_id = str(pr.get("knowledge_pr_id") or "")
    ci_summary = pr.get("ci_summary") if isinstance(pr.get("ci_summary"), dict) else {}
    blocking_gate_ids = _blocking_gate_ids(pr, latest_ci)
    proposed_operations = list(pr.get("proposed_operations") or [])
    return {
        "knowledge_pr_id": pr_id,
        "branch_id": pr.get("branch_id"),
        "title": pr.get("title"),
        "status": _pr_status(pr),
        "mergeable": _pr_status(pr) == "mergeable",
        "ci_summary": dict(ci_summary),
        "latest_ci_run_id": latest_ci.get("ci_run_id") if latest_ci else None,
        "latest_ci_status": latest_ci.get("status") if latest_ci else ci_summary.get("status"),
        "blocking_gate_ids": blocking_gate_ids,
        "blocking_issue_count": len(pr.get("blocking_issues") or []),
        "proposed_operation_count": len(proposed_operations),
        "operation_missing_evidence_count": sum(
            1 for operation in proposed_operations if not _operation_has_evidence(operation)
        ),
        "ci_waiver_count": len(pr.get("ci_waivers") or []),
        "source_ref_count": len(pr.get("source_refs") or []),
        "document_ref_count": len(pr.get("document_refs") or []),
        "source_refs": list(pr.get("source_refs") or []),
        "document_refs": list(pr.get("document_refs") or []),
    }


def _latest_ci_by_pr(ci_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for ci in ci_records:
        pr_id = str(ci.get("knowledge_pr_id") or "")
        if pr_id:
            latest[pr_id] = ci
    return latest


def _latest(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return list(reversed(records))[:limit]


def _latest_blocking_issues(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in items:
        for gate_id in item.get("blocking_gate_ids") or []:
            issues.append(
                {
                    "knowledge_pr_id": item.get("knowledge_pr_id"),
                    "gate_id": gate_id,
                    "status": item.get("latest_ci_status"),
                    "title": item.get("title"),
                }
            )
    return issues[:limit]


def _blocked_document_coverage_refs(
    pr_records: list[dict[str, Any]],
    latest_ci_by_pr: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for pr in pr_records:
        pr_id = str(pr.get("knowledge_pr_id") or "")
        latest_ci = latest_ci_by_pr.get(pr_id)
        if "gate_document_coverage" not in _blocking_gate_ids(pr, latest_ci):
            continue
        for document_ref in pr.get("document_refs") or []:
            if isinstance(document_ref, dict):
                refs.append({"knowledge_pr_id": pr_id, **document_ref})
        for result in (latest_ci or {}).get("gate_results") or []:
            if result.get("gate_id") != "gate_document_coverage":
                continue
            for finding in result.get("findings") or []:
                if isinstance(finding, dict) and finding.get("document_id"):
                    refs.append({"knowledge_pr_id": pr_id, "document_id": finding.get("document_id")})
    return refs[:limit]


def _merge_transaction_refs(
    transaction_records: list[dict[str, Any]],
    *,
    pr_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for transaction in transaction_records:
        if transaction.get("operation_kind") != "merge_knowledge_pr":
            continue
        affected = transaction.get("affected_refs") if isinstance(transaction.get("affected_refs"), list) else []
        affected_pr_ids = {
            str(ref.get("knowledge_pr_id") or "")
            for ref in affected
            if isinstance(ref, dict)
        }
        if pr_ids and not (affected_pr_ids & pr_ids):
            continue
        refs.append(
            {
                "transaction_id": transaction.get("transaction_id"),
                "status": transaction.get("status"),
                "affected_knowledge_pr_ids": sorted(affected_pr_ids),
            }
        )
    return _latest(refs, limit)


def _is_ci_blocked(pr: dict[str, Any], latest_ci: dict[str, Any] | None) -> bool:
    if _pr_status(pr) == "ci_blocked":
        return True
    latest_status = str((latest_ci or {}).get("status") or "").strip()
    if latest_status in BLOCKING_CI_STATUSES:
        return True
    summary = pr.get("ci_summary") if isinstance(pr.get("ci_summary"), dict) else {}
    return str(summary.get("status") or "").strip() in BLOCKING_CI_STATUSES


def _blocking_gate_ids(pr: dict[str, Any], latest_ci: dict[str, Any] | None) -> list[str]:
    gate_ids: list[str] = []
    for gate_id in (pr.get("ci_summary") or {}).get("blocking_gate_ids") or []:
        text = str(gate_id or "").strip()
        if text and text not in gate_ids:
            gate_ids.append(text)
    for gate_id in (latest_ci or {}).get("blocking_gate_ids") or []:
        text = str(gate_id or "").strip()
        if text and text not in gate_ids:
            gate_ids.append(text)
    return gate_ids


def _pr_status(pr: dict[str, Any]) -> str:
    return str(pr.get("status") or "open").strip()


def _operation_has_evidence(operation: Any) -> bool:
    if not isinstance(operation, dict):
        return False
    evidence_refs = operation.get("evidence_refs")
    if isinstance(evidence_refs, list) and evidence_refs:
        return True
    return bool(operation.get("evidence") or operation.get("citation_refs"))


def _matches_project(record: dict[str, Any], project_values: set[str] | None) -> bool:
    if not project_values:
        return True
    record_values = _record_project_values(record)
    return not record_values or bool(record_values & project_values)


def _record_project_values(record: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for value in (record.get("project"), record.get("project_id")):
        text = str(value or "").strip()
        if text:
            values.add(text)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in ("project", "project_id"):
        text = str(metadata.get(key) or "").strip()
        if text:
            values.add(text)
    for key in ("projects", "project_aliases"):
        for item in metadata.get(key) or []:
            text = str(item or "").strip()
            if text:
                values.add(text)
    for ref_key in ("source_refs", "document_refs"):
        for ref in record.get(ref_key) or []:
            if isinstance(ref, dict):
                text = str(ref.get("project") or ref.get("project_id") or "").strip()
                if text:
                    values.add(text)
    for operation in record.get("proposed_operations") or []:
        if isinstance(operation, dict):
            text = str(operation.get("project") or operation.get("project_id") or "").strip()
            if text:
                values.add(text)
    return values


def _matches_scope_refs(
    record: dict[str, Any],
    *,
    document_ids: set[str] | None,
    source_uris: set[str] | None,
) -> bool:
    document_ids = {str(value) for value in document_ids or [] if str(value or "").strip()}
    source_uris = {str(value) for value in source_uris or [] if str(value or "").strip()}
    if not document_ids and not source_uris:
        return True
    record_document_ids, record_source_uris = _record_ref_values(record)
    return bool((document_ids & record_document_ids) or (source_uris & record_source_uris))


def _record_ref_values(record: dict[str, Any]) -> tuple[set[str], set[str]]:
    document_ids: set[str] = set()
    source_uris: set[str] = set()
    for ref in record.get("document_refs") or []:
        if isinstance(ref, dict):
            document_id = str(ref.get("document_id") or ref.get("id") or "").strip()
            source_uri = str(ref.get("source_uri") or ref.get("source_ref") or "").strip()
            if document_id:
                document_ids.add(document_id)
            if source_uri:
                source_uris.add(source_uri)
    for ref in record.get("source_refs") or []:
        if isinstance(ref, dict):
            source_uri = str(ref.get("source_uri") or ref.get("source_ref") or ref.get("uri") or "").strip()
            if source_uri:
                source_uris.add(source_uri)
    return document_ids, source_uris


def _matches_focus(record: dict[str, Any], focus: list[str] | None) -> bool:
    terms = [str(term).strip().lower() for term in focus or [] if str(term).strip()]
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return any(term in haystack for term in terms)

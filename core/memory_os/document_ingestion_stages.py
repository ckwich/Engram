"""Read-only stage receipts for document ingestion retry/resume planning."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records


DOCUMENT_INGESTION_STAGE_SCHEMA_VERSION = "2026-05-21.document-ingestion-stages.v1"
DOCUMENT_INGESTION_STAGES = (
    "disassembly_artifacts",
    "retrieval_index",
    "coverage",
    "structural_graph",
    "understanding",
    "semantic_promotion",
    "completion",
)


def build_document_ingestion_stage_report(ledger: Any, record: dict[str, Any]) -> dict[str, Any]:
    """Return an inspectable, read-only retry plan for a document ingestion record."""
    ingestion_id = str(record.get("ingestion_id") or record.get("job_id") or "")
    document_id = str(record.get("document_id") or "")
    readiness = dict(record.get("readiness") or {})
    artifacts = [item for item in record.get("artifacts") or [] if isinstance(item, dict)]
    windows = [item for item in record.get("windows") or [] if isinstance(item, dict)]
    coverage_pass = record.get("coverage_pass") if isinstance(record.get("coverage_pass"), dict) else None
    understanding_packet = (
        record.get("understanding_packet")
        if isinstance(record.get("understanding_packet"), dict)
        else None
    )
    promotion_transaction = (
        record.get("document_promotion_transaction")
        if isinstance(record.get("document_promotion_transaction"), dict)
        else None
    )
    semantic_edges = [
        str(edge_id)
        for edge_id in record.get("semantic_graph_edges_written") or []
        if str(edge_id).strip()
    ]
    structural_edges = [
        str(edge_id)
        for edge_id in record.get("graph_edges_written") or []
        if str(edge_id).strip()
    ]
    chunk_count = _chunk_count(ledger, document_id)
    completion_progress = _completion_progress(ledger, document_id)

    stages = [
        _stage(
            "disassembly_artifacts",
            complete=bool(artifacts and windows),
            status="complete" if artifacts and windows else "pending",
            retry_tool="run_document_ingestion",
            reason=None if artifacts and windows else "document evidence windows have not all been materialized",
        ),
        _stage(
            "retrieval_index",
            complete=bool(readiness.get("searchable") and chunk_count > 0),
            status="complete" if readiness.get("searchable") and chunk_count > 0 else "pending",
            retry_tool="run_document_ingestion",
            reason=None if readiness.get("searchable") else "document chunks are not confirmed searchable",
        ),
        _coverage_stage(readiness, coverage_pass),
        _stage(
            "structural_graph",
            complete=bool(readiness.get("structural_graph_covered")),
            status="complete" if readiness.get("structural_graph_covered") else "pending",
            retry_tool="run_document_ingestion",
            reason=None if readiness.get("structural_graph_covered") else "structural document graph edges are missing",
            evidence={"graph_edge_count": len(structural_edges)},
        ),
        _understanding_stage(record, understanding_packet),
        _semantic_promotion_stage(record, readiness, semantic_edges, promotion_transaction),
        _stage(
            "completion",
            complete=bool(readiness.get("usable") or record.get("completion_artifact_id")),
            status="complete" if readiness.get("usable") or record.get("completion_artifact_id") else "pending",
            retry_tool="complete_document_ingestion",
            reason=None if readiness.get("usable") else "document has not passed the completion gate",
            evidence=completion_progress,
        ),
    ]
    next_stage = next((stage for stage in stages if not stage["complete"]), None)
    retryable_stages = [
        stage
        for stage in stages
        if not stage["complete"] and bool(stage.get("retry_action"))
    ]
    return {
        "schema_version": DOCUMENT_INGESTION_STAGE_SCHEMA_VERSION,
        "ingestion_id": ingestion_id,
        "document_id": document_id or None,
        "stage_count": len(stages),
        "completed_stage_count": sum(1 for stage in stages if stage["complete"]),
        "stages": stages,
        "next_stage": next_stage,
        "retryable_stages": retryable_stages,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None,
    }


def _coverage_stage(readiness: dict[str, Any], coverage_pass: dict[str, Any] | None) -> dict[str, Any]:
    complete = all(
        bool(readiness.get(key))
        for key in ("ocr_covered", "visual_covered", "table_covered")
    )
    if complete:
        return _stage("coverage", complete=True, status="complete", retry_tool="prepare_document_coverage_pass")
    if isinstance(coverage_pass, dict):
        status = "partial" if coverage_pass.get("status") == "partial" else "pending"
        reason = "coverage pass still has blocking issues" if status == "partial" else "coverage pass did not complete"
        retry_tool = str((coverage_pass.get("next_action") or {}).get("tool") or "prepare_document_coverage_pass")
        return _stage(
            "coverage",
            complete=False,
            status=status,
            retry_tool=retry_tool,
            reason=reason,
            evidence={
                "coverage_status": coverage_pass.get("status"),
                "blocking_issue_count": len(coverage_pass.get("blocking_issues") or []),
            },
        )
    return _stage(
        "coverage",
        complete=False,
        status="pending",
        retry_tool="prepare_document_coverage_pass",
        reason="OCR, visual, or table coverage is not confirmed",
    )


def _understanding_stage(
    record: dict[str, Any],
    understanding_packet: dict[str, Any] | None,
) -> dict[str, Any]:
    analysis_policy = str(record.get("analysis_policy") or "defer")
    if isinstance(understanding_packet, dict):
        receipt = understanding_packet.get("receipt") if isinstance(understanding_packet.get("receipt"), dict) else {}
        return _stage(
            "understanding",
            complete=True,
            status="complete",
            retry_tool="resume_document_ingestion",
            evidence={
                "claim_candidate_count": int(receipt.get("claim_candidate_count") or 0),
                "chunk_ref_count": int(receipt.get("chunk_ref_count") or 0),
            },
        )
    return _stage(
        "understanding",
        complete=False,
        status="deferred" if analysis_policy == "defer" else "pending",
        retry_tool="resume_document_ingestion",
        reason="reviewed understanding analysis has not been supplied",
        evidence={"analysis_policy": analysis_policy},
    )


def _semantic_promotion_stage(
    record: dict[str, Any],
    readiness: dict[str, Any],
    semantic_edges: list[str],
    promotion_transaction: dict[str, Any] | None,
) -> dict[str, Any]:
    complete = bool(readiness.get("semantic_graph_covered") and semantic_edges)
    if complete:
        return _stage(
            "semantic_promotion",
            complete=True,
            status="complete",
            retry_tool="resume_document_ingestion",
            evidence={"semantic_graph_edge_count": len(semantic_edges)},
        )
    if not isinstance(promotion_transaction, dict):
        return _stage(
            "semantic_promotion",
            complete=False,
            status="pending",
            retry_tool="resume_document_ingestion",
            reason="semantic graph promotion transaction has not been prepared",
        )
    return _stage(
        "semantic_promotion",
        complete=False,
        status="partial",
        retry_tool="resume_document_ingestion",
        reason="semantic graph promotion transaction exists but active graph coverage is incomplete",
        evidence={
            "operation_count": len(promotion_transaction.get("operations") or []),
            "semantic_graph_edge_count": len(semantic_edges),
        },
    )


def _stage(
    stage_id: str,
    *,
    complete: bool,
    status: str,
    retry_tool: str,
    reason: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_index = DOCUMENT_INGESTION_STAGES.index(stage_id) + 1
    payload = {
        "stage": stage_id,
        "stage_index": stage_index,
        "stage_count": len(DOCUMENT_INGESTION_STAGES),
        "status": status,
        "complete": bool(complete),
        "reason": reason,
        "evidence": dict(evidence or {}),
    }
    if not complete:
        payload["retry_action"] = {"tool": retry_tool}
    return payload


def _chunk_count(ledger: Any, document_id: str) -> int:
    if not document_id:
        return 0
    return sum(
        1
        for chunk in list_records(ledger, "chunks")
        if str(chunk.get("document_id") or "") == document_id
    )


def _completion_progress(ledger: Any, document_id: str) -> dict[str, Any]:
    if not document_id:
        return {}
    job_id = f"document_completion:{document_id}"
    events = [
        event
        for event in list_records(ledger, "job_events")
        if event.get("job_id") == job_id
    ]
    if not events:
        return {}
    latest = max(events, key=lambda event: str(event.get("created_at") or ""))
    return {
        "progress_job_id": job_id,
        "latest_event_type": latest.get("event_type"),
        "event_count": len(events),
    }

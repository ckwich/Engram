"""Read-only Memory OS inspector payloads."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records

INSPECTOR_SCHEMA_VERSION = "2026-05-13.memory-os-inspector.v1"
REVIEW_RECORD_TYPES = {
    "document_draft",
    "document_intake_review",
    "document_understanding_packet",
    "source_draft",
}
REVIEW_STATUSES = {
    "candidate",
    "draft",
    "needs_review",
    "pending",
    "pending_review",
    "ready_for_review",
    "review_required",
}
RELEASE_GATE_COMMANDS = (
    {
        "command": "python server.py --help",
        "purpose": "prove the MCP entrypoint imports and exposes CLI help",
    },
    {
        "command": 'python -c "from core.memory_manager import memory_manager; print(\'ok\')"',
        "purpose": "prove legacy JSON/Chroma compatibility imports",
    },
    {
        "command": "python engramd.py --doctor",
        "purpose": "check daemon process hygiene and store ownership",
    },
    {
        "command": "python engramd.py --smoke-test",
        "purpose": "prove daemon store/search/read/delete health",
    },
    {
        "command": "python server.py --self-test",
        "purpose": "prove direct MCP store/search/retrieve/delete behavior",
    },
    {
        "command": "python server.py --agent-eval",
        "purpose": "agent-facing retrieval/source/document workflow gates",
    },
    {
        "command": "python -m pytest tests/architecture tests/mcp tests/policy tests/backend_gates tests/release -q",
        "purpose": "pre-EKC architecture, policy, backend, and release gates",
    },
    {
        "command": "python -m pytest -q",
        "purpose": "full repository regression suite",
    },
    {
        "command": "git diff --check",
        "purpose": "whitespace and patch hygiene",
    },
)


def build_memory_os_inspector(runtime: Any, *, limit: int = 20) -> dict[str, Any]:
    """Build a compact read-only snapshot of daemon-owned Memory OS state."""
    bounded_limit = max(1, min(int(limit), 100))
    ledger = runtime.ledger
    status = runtime.status()

    jobs = _records_section(ledger, "jobs", bounded_limit)
    transactions = _records_section(ledger, "transactions", bounded_limit)
    coverage_maps = _records_section(ledger, "retrieval_receipts", bounded_limit)
    firewall = _records_section(ledger, "firewall_events", bounded_limit)
    snapshots = _records_section(ledger, "snapshots", bounded_limit)
    skill_packs = _records_section(ledger, "skill_packs", bounded_limit)
    knowledge_artifacts = _records_section(ledger, "knowledge_artifacts", bounded_limit)
    transaction_records = list_records(ledger, "transactions")
    graph_edge_records = list_records(ledger, "graph_edges")
    draft_records = list_records(ledger, "drafts")
    graph_edges = _latest(graph_edge_records, bounded_limit)
    entities = _latest(list_records(ledger, "entities"), bounded_limit)
    concepts = _latest(list_records(ledger, "concepts"), bounded_limit)
    aliases = _latest(list_records(ledger, "aliases"), bounded_limit)
    sources = _records_section(ledger, "sources", bounded_limit)
    documents = _records_section(ledger, "documents", bounded_limit)
    drafts = _section_from_records("drafts", draft_records, bounded_limit)
    review_queue = _section_from_records(
        "review_preparation_queue",
        _review_queue_records(draft_records),
        bounded_limit,
    )
    document_artifact_transactions = _section_from_records(
        "document_artifact_transactions",
        [record for record in transaction_records if _is_document_artifact_transaction(record)],
        bounded_limit,
    )
    promotion_transactions = _section_from_records(
        "promotion_transactions",
        [record for record in transaction_records if _is_document_promotion_transaction(record)],
        bounded_limit,
    )
    graph_evidence = _graph_evidence_section(graph_edge_records, bounded_limit)
    ekc_eval_summary = _ekc_eval_summary()
    release_gate_commands = _release_gate_commands_section()

    return {
        "schema_version": INSPECTOR_SCHEMA_VERSION,
        "write_performed": False,
        "limit": bounded_limit,
        "runtime": status,
        "daemon_status": {
            "status": status.get("status", "unknown") if isinstance(status, dict) else "unknown",
            "runtime": status,
            "write_performed": False,
        },
        "summary": {
            "job_count": jobs["count"],
            "transaction_count": transactions["count"],
            "coverage_map_count": coverage_maps["count"],
            "firewall_event_count": firewall["count"],
            "snapshot_count": snapshots["count"],
            "skill_pack_count": skill_packs["count"],
            "knowledge_artifact_count": knowledge_artifacts["count"],
            "graph_edge_count": len(graph_edges),
            "entity_count": len(entities),
            "concept_count": len(concepts),
            "source_count": sources["count"],
            "document_count": documents["count"],
            "draft_count": drafts["count"],
            "review_queue_count": review_queue["count"],
            "document_artifact_transaction_count": document_artifact_transactions["count"],
            "promotion_transaction_count": promotion_transactions["count"],
            "graph_evidence_count": graph_evidence["edge_count"],
            "graph_contradiction_count": graph_evidence["contradiction_count"],
            "ekc_eval_scenario_count": ekc_eval_summary["scenario_count"],
            "release_gate_command_count": release_gate_commands["count"],
        },
        "migration_import": {
            "sources": sources,
            "documents": documents,
            "drafts": drafts,
        },
        "jobs": jobs,
        "transactions": transactions,
        "graph": {
            "edge_count": len(graph_edges),
            "edges": graph_edges,
            "paths": [],
            "write_performed": False,
        },
        "entity_registry": {
            "entity_count": len(entities),
            "concept_count": len(concepts),
            "alias_count": len(aliases),
            "entities": entities,
            "concepts": concepts,
            "aliases": aliases,
            "write_performed": False,
        },
        "firewall_queue": firewall,
        "coverage_maps": coverage_maps,
        "knowledge_artifacts": knowledge_artifacts,
        "review_preparation_queue": review_queue,
        "document_artifact_transactions": document_artifact_transactions,
        "promotion_transactions": promotion_transactions,
        "graph_evidence": graph_evidence,
        "ekc_eval_summary": ekc_eval_summary,
        "release_gate_commands": release_gate_commands,
        "snapshots": snapshots,
        "skill_packs": skill_packs,
    }


def _records_section(ledger: Any, table: str, limit: int) -> dict[str, Any]:
    records = list_records(ledger, table)
    return _section_from_records(table, records, limit)


def _section_from_records(section_id: str, records: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {
        "table": section_id,
        "count": len(records),
        "items": _latest(records, limit),
        "write_performed": False,
    }


def _latest(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return list(reversed(records))[:limit]


def _review_queue_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if _is_review_queue_record(record)]


def _is_review_queue_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type") or record.get("type") or "").strip()
    status_values = {
        str(record.get(name) or "").strip().lower()
        for name in ("status", "review_status", "review_state", "promotion_status")
        if record.get(name)
    }
    if record_type in REVIEW_RECORD_TYPES:
        return True
    if record_type.endswith("_draft"):
        return True
    if status_values & REVIEW_STATUSES:
        return True
    return bool(
        record.get("promotion_required")
        or record.get("proposed_memories")
        or record.get("candidate_graph_edges")
    )


def _is_document_artifact_transaction(record: dict[str, Any]) -> bool:
    operation_kind = str(record.get("operation_kind") or "").strip()
    artifact_family = str(record.get("artifact_family") or "").strip()
    record_type = str(record.get("record_type") or "").strip()
    return (
        operation_kind == "document_artifact_store"
        or artifact_family == "document_evidence"
        or record_type == "document_artifact_transaction"
    )


def _is_document_promotion_transaction(record: dict[str, Any]) -> bool:
    operation_kind = str(record.get("operation_kind") or "").strip()
    record_type = str(record.get("record_type") or "").strip()
    return (
        record_type == "document_promotion_transaction"
        or operation_kind in {"prepare_document_promotion_transaction", "apply_document_promotion_transaction"}
        or operation_kind == "apply_document_promotion"
    )


def _graph_evidence_section(records: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    edges = _latest(records, limit)
    support_count = sum(1 for record in records if record.get("edge_type") == "supports")
    contradiction_count = sum(1 for record in records if record.get("edge_type") == "contradicts")
    return {
        "edge_count": len(records),
        "support_count": support_count,
        "contradiction_count": contradiction_count,
        "items": edges,
        "write_performed": False,
    }


def _ekc_eval_summary() -> dict[str, Any]:
    try:
        from core.memory_os.knowledge_eval import DEFAULT_WORKFLOW_SCENARIOS
    except Exception as exc:  # pragma: no cover - defensive inspector fallback
        return {
            "scenario_count": 0,
            "workflow_ids": [],
            "task_types": [],
            "status": "unavailable",
            "error": {"code": "runtime_error", "message": str(exc)},
            "write_performed": False,
        }

    workflow_ids = [str(scenario.get("scenario_id") or "") for scenario in DEFAULT_WORKFLOW_SCENARIOS]
    task_types = [str(scenario.get("task_type") or "") for scenario in DEFAULT_WORKFLOW_SCENARIOS]
    return {
        "scenario_count": len(DEFAULT_WORKFLOW_SCENARIOS),
        "workflow_ids": workflow_ids,
        "task_types": task_types,
        "status": "available",
        "write_performed": False,
    }


def _release_gate_commands_section() -> dict[str, Any]:
    return {
        "count": len(RELEASE_GATE_COMMANDS),
        "items": list(RELEASE_GATE_COMMANDS),
        "write_performed": False,
    }

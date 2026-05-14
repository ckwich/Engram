"""Read-only Memory OS inspector payloads."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records

INSPECTOR_SCHEMA_VERSION = "2026-05-13.memory-os-inspector.v1"


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
    graph_edges = _latest(list_records(ledger, "graph_edges"), bounded_limit)
    entities = _latest(list_records(ledger, "entities"), bounded_limit)
    concepts = _latest(list_records(ledger, "concepts"), bounded_limit)
    aliases = _latest(list_records(ledger, "aliases"), bounded_limit)
    sources = _records_section(ledger, "sources", bounded_limit)
    documents = _records_section(ledger, "documents", bounded_limit)
    drafts = _records_section(ledger, "drafts", bounded_limit)

    return {
        "schema_version": INSPECTOR_SCHEMA_VERSION,
        "write_performed": False,
        "limit": bounded_limit,
        "runtime": status,
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
        "snapshots": snapshots,
        "skill_packs": skill_packs,
    }


def _records_section(ledger: Any, table: str, limit: int) -> dict[str, Any]:
    records = list_records(ledger, table)
    return {
        "table": table,
        "count": len(records),
        "items": _latest(records, limit),
        "write_performed": False,
    }


def _latest(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return list(reversed(records))[:limit]

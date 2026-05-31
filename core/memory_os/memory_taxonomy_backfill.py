"""Dry-run-first repair for native memory taxonomy metadata."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import now_iso, upsert_record
from core.memory_os.memory_taxonomy import normalize_memory_payload


BACKFILL_SCHEMA_VERSION = "2026-05-26.memory-taxonomy-backfill.v1"
BACKFILL_TABLES = ("memories", "chunks", "drafts", "documents")
REQUIRED_TAXONOMY_FIELDS = (
    "memory_type",
    "scope",
    "trust_state",
    "retention_policy",
    "sync_policy",
)


def repair_memory_taxonomy_metadata(ledger: Any, *, accept: bool, approved_by: str) -> dict[str, Any]:
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for table in BACKFILL_TABLES:
        for record_id, record in _iter_record_entries(ledger, table):
            if all(field in record for field in REQUIRED_TAXONOMY_FIELDS):
                continue
            candidates.append((table, record_id, record))

    if not accept:
        return {
            "schema_version": BACKFILL_SCHEMA_VERSION,
            "status": "preview",
            "write_performed": False,
            "candidate_count": len(candidates),
            "tables": list(BACKFILL_TABLES),
        }

    reviewer = str(approved_by or "").strip()
    if not reviewer:
        return {
            "schema_version": BACKFILL_SCHEMA_VERSION,
            "status": "policy_denied",
            "write_performed": False,
            "candidate_count": len(candidates),
            "error": {"code": "approved_by_required"},
        }

    updated = 0
    timestamp = now_iso()
    for table, record_id, record in candidates:
        normalized = normalize_memory_payload(record)
        normalized["taxonomy_backfilled_at"] = timestamp
        normalized["taxonomy_backfilled_by"] = reviewer
        upsert_record(ledger, table, record_id, normalized)
        updated += 1

    return {
        "schema_version": BACKFILL_SCHEMA_VERSION,
        "status": "applied",
        "write_performed": bool(updated),
        "candidate_count": len(candidates),
        "updated_count": updated,
        "approved_by": reviewer,
    }


def _iter_record_entries(ledger: Any, table: str) -> list[tuple[str, dict[str, Any]]]:
    ledger.initialize()
    with ledger.connect() as conn:
        rows = conn.execute(f"SELECT id, payload_json FROM {table} ORDER BY created_at, id").fetchall()  # nosec B608
    entries: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        decoded = json.loads(row["payload_json"])
        if isinstance(decoded, dict):
            entries.append((str(row["id"]), decoded))
    return entries

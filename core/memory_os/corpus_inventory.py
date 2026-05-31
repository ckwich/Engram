"""No-write inventory for legacy JSON versus daemon-owned Memory OS corpus."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.memory_os_migration import LEGACY_STATUS_POLICY, MemoryOSMigrationKernel, NULL_STATUS_LABEL

CORPUS_INVENTORY_SCHEMA_VERSION = "2026-05-15.corpus-inventory.v1"
MEMORY_OS_LEDGER_FILENAME = "ledger.sqlite3"
NULL_LABEL = NULL_STATUS_LABEL


def build_corpus_inventory(
    *,
    legacy_dir: str | Path,
    memory_os_root: str | Path,
) -> dict[str, Any]:
    """Compare legacy JSON memory files with an existing Memory OS ledger.

    This function is intentionally no-write: it scans legacy JSON in dry-run
    mode and reads the Memory OS SQLite database directly if it already exists.
    It must not create Memory OS directories, schema tables, indexes, or
    migration artifacts.
    """
    legacy_path = Path(legacy_dir)
    memory_os_path = Path(memory_os_root)
    ledger_path = memory_os_path / MEMORY_OS_LEDGER_FILENAME

    legacy_records, legacy_invalid = MemoryOSMigrationKernel(memory_os_path)._scan_legacy_dir(legacy_path)
    memory_os = _read_memory_os_ledger(ledger_path)

    legacy_keys = {record["key"] for record in legacy_records}
    memory_os_keys = {record["key"] for record in memory_os["memories"]}
    legacy_status_counts = _counts(record.get("legacy_status") for record in legacy_records)
    legacy_project_counts = _counts(record.get("project") for record in legacy_records)
    memory_os_status_counts = _counts(record.get("status") for record in memory_os["memories"])
    memory_os_project_counts = _counts(record.get("project") for record in memory_os["memories"])

    return {
        "schema_version": CORPUS_INVENTORY_SCHEMA_VERSION,
        "write_policy": "no_write",
        "write_performed": False,
        "paths": {
            "legacy_dir": str(legacy_path),
            "memory_os_root": str(memory_os_path),
            "memory_os_ledger": str(ledger_path),
        },
        "legacy_json_count": len(legacy_records) + len(legacy_invalid),
        "legacy_valid_json_count": len(legacy_records),
        "legacy_invalid_json_count": len(legacy_invalid),
        "legacy_related_to_count": sum(1 for record in legacy_records if record["related_to"]),
        "legacy_related_to_edge_count": sum(len(record["related_to"]) for record in legacy_records),
        "legacy_chunk_metadata_total": sum(
            int(record["chunk_count"])
            for record in legacy_records
            if isinstance(record.get("chunk_count"), int)
        ),
        "legacy_derived_chunk_count_total": sum(len(record["chunks"]) for record in legacy_records),
        "legacy_status_counts": dict(sorted(legacy_status_counts.items())),
        "legacy_project_counts": dict(sorted(legacy_project_counts.items())),
        "memory_os_ledger_exists": ledger_path.exists(),
        "memory_os_memory_count": memory_os["table_counts"]["memories"],
        "memory_os_chunk_count": memory_os["table_counts"]["chunks"],
        "memory_os_document_count": memory_os["table_counts"]["documents"],
        "memory_os_graph_edge_count": memory_os["table_counts"]["graph_edges"],
        "memory_os_project_counts": dict(sorted(memory_os_project_counts.items())),
        "memory_os_status_counts": dict(sorted(memory_os_status_counts.items())),
        "missing_in_memory_os": sorted(legacy_keys - memory_os_keys),
        "extra_in_memory_os": sorted(memory_os_keys - legacy_keys),
        "project_identity_collisions": _project_identity_collisions(
            [record.get("project") for record in legacy_records]
            + [record.get("project") for record in memory_os["memories"]]
        ),
        "status_policy": LEGACY_STATUS_POLICY,
        "status_mapping_gaps": _status_mapping_gaps(legacy_status_counts),
        "unsupported_legacy_fields": {
            record["key"]: record["unsupported_fields"]
            for record in legacy_records
            if record["unsupported_fields"]
        },
        "invalid_legacy_records": legacy_invalid,
    }


def _read_memory_os_ledger(ledger_path: Path) -> dict[str, Any]:
    table_counts = {
        "memories": 0,
        "chunks": 0,
        "documents": 0,
        "graph_edges": 0,
    }
    payloads = {
        "memories": [],
        "chunks": [],
        "documents": [],
        "graph_edges": [],
    }
    if not ledger_path.exists():
        return {"table_counts": table_counts, **payloads}

    with sqlite3.connect(ledger_path) as conn:
        conn.row_factory = sqlite3.Row
        existing_tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        for table in table_counts:
            if table not in existing_tables:
                continue
            table_counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # nosec B608
            rows = conn.execute(f"SELECT id, payload_json FROM {table} ORDER BY id").fetchall()  # nosec B608
            payloads[table] = [_decode_record(row["id"], row["payload_json"]) for row in rows]
    return {"table_counts": table_counts, **payloads}


def _decode_record(record_id: str, payload_json: str) -> dict[str, Any]:
    try:
        decoded = json.loads(payload_json)
    except json.JSONDecodeError:
        return {"id": record_id, "key": record_id, "decode_error": "invalid_json"}
    if not isinstance(decoded, dict):
        return {"id": record_id, "key": record_id, "decode_error": "payload_not_object"}
    record = dict(decoded)
    record.setdefault("id", record_id)
    record.setdefault("key", record_id)
    return record


def _counts(values: Any) -> Counter[str]:
    counter: Counter[str] = Counter()
    for value in values:
        counter[_label(value)] += 1
    return counter


def _status_mapping_gaps(status_counts: Counter[str]) -> list[str]:
    return sorted(status for status in status_counts if status not in LEGACY_STATUS_POLICY)


def _project_identity_collisions(labels: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for raw_label in labels:
        label = _label(raw_label)
        if label == NULL_LABEL:
            continue
        canonical = _canonical_project_label(label)
        if not canonical:
            continue
        grouped[canonical][label] += 1

    collisions = []
    for canonical, counts in sorted(grouped.items()):
        if len(counts) < 2:
            continue
        collisions.append(
            {
                "canonical_project": canonical,
                "labels": sorted(counts),
                "memory_count": sum(counts.values()),
            }
        )
    return collisions


def _label(value: Any) -> str:
    if value is None:
        return NULL_LABEL
    text = str(value).strip()
    return text or NULL_LABEL


def _canonical_project_label(label: str) -> str:
    normalized = label.replace("\\", "/").strip().strip("/")
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized

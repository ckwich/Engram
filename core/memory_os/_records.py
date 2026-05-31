"""SQLite JSON-record helpers for Memory OS service kernels."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.schema import TABLES

_VALID_TABLES = frozenset(TABLES)
_CHUNK_LOOKUP_FIELDS = frozenset({"memory_key", "document_id"})


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def upsert_record(ledger: MemoryOSLedger, table: str, record_id: str, payload: dict[str, Any]) -> None:
    table_name = _checked_table_name(table)
    ledger.initialize()
    timestamp = now_iso()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    query = f"""
    INSERT INTO {table_name} (id, payload_json, created_at, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        payload_json = excluded.payload_json,
        updated_at = excluded.updated_at
    """  # nosec B608
    with ledger.connect() as conn:
        conn.execute(
            query,
            (record_id, encoded, timestamp, timestamp),
        )
        conn.commit()


def read_record(ledger: MemoryOSLedger, table: str, record_id: str) -> dict[str, Any] | None:
    table_name = _checked_table_name(table)
    ledger.initialize()
    query = f"SELECT payload_json FROM {table_name} WHERE id = ?"  # nosec B608
    with ledger.connect() as conn:
        row = conn.execute(
            query,
            (record_id,),
        ).fetchone()
    if row is None:
        return None
    decoded = json.loads(row["payload_json"])
    return decoded if isinstance(decoded, dict) else None


def list_records(ledger: MemoryOSLedger, table: str) -> list[dict[str, Any]]:
    table_name = _checked_table_name(table)
    ledger.initialize()
    query = f"SELECT payload_json FROM {table_name} ORDER BY created_at, id"  # nosec B608
    with ledger.connect() as conn:
        rows = conn.execute(query).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        decoded = json.loads(row["payload_json"])
        if isinstance(decoded, dict):
            records.append(decoded)
    return records


def read_chunk_by_lookup(
    ledger: MemoryOSLedger,
    *,
    memory_key: str | None = None,
    document_id: str | None = None,
    chunk_id: int,
) -> dict[str, Any] | None:
    """Read one chunk by indexed JSON identity fields without loading all chunks."""
    normalized_memory_key = str(memory_key or "").strip()
    normalized_document_id = str(document_id or "").strip()
    if not normalized_memory_key and not normalized_document_id:
        return None
    ledger.initialize()
    try:
        with ledger.connect() as conn:
            if normalized_memory_key:
                record = _read_chunk_by_json_field(
                    conn,
                    field="memory_key",
                    value=normalized_memory_key,
                    chunk_id=chunk_id,
                )
                if record is not None:
                    return record
            if normalized_document_id:
                return _read_chunk_by_json_field(
                    conn,
                    field="document_id",
                    value=normalized_document_id,
                    chunk_id=chunk_id,
                )
    except sqlite3.DatabaseError:
        return None
    return None


def _read_chunk_by_json_field(
    conn: sqlite3.Connection,
    *,
    field: str,
    value: str,
    chunk_id: int,
) -> dict[str, Any] | None:
    field_name = _checked_chunk_lookup_field(field)
    if field_name not in _CHUNK_LOOKUP_FIELDS:
        raise ValueError(f"unsupported chunk lookup field: {field}")
    query = f"""
    SELECT payload_json
    FROM chunks
    WHERE json_extract(payload_json, '$.{field_name}') = ?
      AND CAST(json_extract(payload_json, '$.chunk_id') AS INTEGER) = ?
    ORDER BY id
    LIMIT 1
    """  # nosec B608
    row = conn.execute(
        query,
        (value, int(chunk_id)),
    ).fetchone()
    if row is None:
        return None
    decoded = json.loads(row["payload_json"])
    return decoded if isinstance(decoded, dict) else None


def _checked_table_name(table: str) -> str:
    normalized = str(table or "").strip()
    if normalized not in _VALID_TABLES:
        raise ValueError(f"unsupported ledger table: {normalized}")
    return normalized


def _checked_chunk_lookup_field(field: str) -> str:
    normalized = str(field or "").strip()
    if normalized not in _CHUNK_LOOKUP_FIELDS:
        raise ValueError(f"unsupported chunk lookup field: {normalized}")
    return normalized

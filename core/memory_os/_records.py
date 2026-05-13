"""SQLite JSON-record helpers for Memory OS service kernels."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from core.memory_os.ledger import MemoryOSLedger


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def upsert_record(ledger: MemoryOSLedger, table: str, record_id: str, payload: dict[str, Any]) -> None:
    ledger.initialize()
    timestamp = now_iso()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with ledger.connect() as conn:
        conn.execute(
            f"""
            INSERT INTO {table} (id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (record_id, encoded, timestamp, timestamp),
        )
        conn.commit()


def read_record(ledger: MemoryOSLedger, table: str, record_id: str) -> dict[str, Any] | None:
    ledger.initialize()
    with ledger.connect() as conn:
        row = conn.execute(
            f"SELECT payload_json FROM {table} WHERE id = ?",
            (record_id,),
        ).fetchone()
    if row is None:
        return None
    decoded = json.loads(row["payload_json"])
    return decoded if isinstance(decoded, dict) else None


def list_records(ledger: MemoryOSLedger, table: str) -> list[dict[str, Any]]:
    ledger.initialize()
    with ledger.connect() as conn:
        rows = conn.execute(f"SELECT payload_json FROM {table} ORDER BY created_at, id").fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        decoded = json.loads(row["payload_json"])
        if isinstance(decoded, dict):
            records.append(decoded)
    return records

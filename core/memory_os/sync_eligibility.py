"""Sync eligibility policy for Memory OS ledger rows."""
from __future__ import annotations

from typing import Any

from core.memory_os.schema import (
    SYNC_CONDITIONAL_TABLES,
    SYNC_ELIGIBLE_TABLES,
    SYNC_LOCAL_ONLY_TABLES,
)


def classify_sync_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Classify whether one ledger row may leave this device in a sync changeset."""
    table_name = str(table or "").strip()
    if table_name in SYNC_LOCAL_ONLY_TABLES or table_name == "transactions":
        return {"eligible": False, "reason": "local_only_table"}
    conditional = table_name in SYNC_CONDITIONAL_TABLES
    if table_name not in SYNC_ELIGIBLE_TABLES and not conditional:
        return {"eligible": False, "reason": "unsupported_table"}

    scope = _text(row.get("scope"))
    if scope == "device":
        return {"eligible": False, "reason": "device_scope"}

    sync_policy = _text(row.get("sync_policy"))
    if sync_policy == "local_only":
        return {"eligible": False, "reason": "local_only_policy"}
    if sync_policy == "quarantined":
        return {"eligible": False, "reason": "quarantined_policy"}

    if _text(row.get("retention_policy")) == "local_only":
        return {"eligible": False, "reason": "local_only_retention"}
    if _text(row.get("retention_policy")) == "ephemeral":
        return {"eligible": False, "reason": "ephemeral_retention"}
    if _text(row.get("trust_state")) == "quarantined" or _text(row.get("status")) == "quarantined":
        return {"eligible": False, "reason": "quarantined"}

    if conditional:
        return {"eligible": sync_policy == "sync", "reason": "conditional_table"}
    return {"eligible": True, "reason": "eligible"}


def _text(value: Any) -> str:
    return str(value or "").strip().lower()

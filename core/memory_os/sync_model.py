"""Typed sync record models for offline reconciliation planning."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SyncCursor:
    peer_device_id: str
    table: str
    last_seen_transaction_id: str | None
    updated_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_type": "sync_cursor",
            "peer_device_id": self.peer_device_id,
            "table": self.table,
            "last_seen_transaction_id": self.last_seen_transaction_id,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SyncChangesetSummary:
    changeset_id: str
    source_device_id: str
    target_device_id: str
    row_count: int
    object_count: int
    bundle_hash: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_type": "sync_changeset_summary",
            "changeset_id": self.changeset_id,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "row_count": int(self.row_count),
            "object_count": int(self.object_count),
            "bundle_hash": self.bundle_hash,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SyncConflict:
    conflict_id: str
    table: str
    record_id: str
    local_transaction_id: str | None
    remote_transaction_id: str | None
    status: str
    detected_at: str
    resolution: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_type": "sync_conflict",
            "conflict_id": self.conflict_id,
            "table": self.table,
            "record_id": self.record_id,
            "local_transaction_id": self.local_transaction_id,
            "remote_transaction_id": self.remote_transaction_id,
            "status": self.status,
            "detected_at": self.detected_at,
            "resolution": self.resolution,
        }


@dataclass(frozen=True)
class SyncApplyPlan:
    plan_id: str
    source_device_id: str
    target_device_id: str
    changeset_id: str
    apply_count: int
    conflict_count: int
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_type": "sync_apply_plan",
            "plan_id": self.plan_id,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "changeset_id": self.changeset_id,
            "apply_count": int(self.apply_count),
            "conflict_count": int(self.conflict_count),
            "status": self.status,
        }

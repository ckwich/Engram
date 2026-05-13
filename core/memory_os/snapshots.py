"""Snapshot manifests for Memory OS rollback and replay."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import hash_payload, list_records, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


class SnapshotService:
    """Create durable snapshot manifests from current ledger state."""

    def __init__(self, ledger: MemoryOSLedger) -> None:
        self.ledger = ledger

    def create_snapshot(
        self,
        *,
        created_by: str,
        lancedb_rebuild_manifest_ref: str | None = None,
        kuzu_rebuild_manifest_ref: str | None = None,
    ) -> dict[str, Any]:
        source_state = {
            "sources": len(list_records(self.ledger, "sources")),
            "documents": len(list_records(self.ledger, "documents")),
            "chunks": len(list_records(self.ledger, "chunks")),
            "memories": len(list_records(self.ledger, "memories")),
        }
        policy_state = {
            "firewall_events": len(list_records(self.ledger, "firewall_events")),
        }
        ledger_revision = len(list_records(self.ledger, "transactions"))
        snapshot = {
            "snapshot_id": stable_id(
                "snapshot",
                {
                    "ledger_revision": ledger_revision,
                    "source_state": source_state,
                    "policy_state": policy_state,
                    "created_by": created_by,
                    "created_at": now_iso(),
                },
            ),
            "ledger_revision": ledger_revision,
            "source_manifest_hash": hash_payload(source_state),
            "lancedb_rebuild_manifest_ref": lancedb_rebuild_manifest_ref,
            "kuzu_rebuild_manifest_ref": kuzu_rebuild_manifest_ref,
            "policy_manifest_hash": hash_payload(policy_state),
            "created_by": created_by,
            "created_at": now_iso(),
        }
        upsert_record(self.ledger, "snapshots", snapshot["snapshot_id"], snapshot)
        return snapshot

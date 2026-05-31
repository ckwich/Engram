"""Snapshot manifest receipts for Memory OS diff and replay planning.

These records are not restore-grade rollback points. They capture durable
manifest hashes and operator context only; full rollback requires a future
restore implementation over ledger rows, content objects, and indexes.
"""
from __future__ import annotations

from typing import Any

from core.memory_os._records import hash_payload, list_records, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


SNAPSHOT_MANIFEST_SCHEMA_VERSION = "2026-05-22.snapshot-manifest.v1"


def snapshot_manifest_semantics(*, record_type: str = "snapshot_manifest") -> dict[str, Any]:
    """Return the stable semantics block for current snapshot manifest records."""
    return {
        "record_type": record_type,
        "snapshot_kind": "manifest_only",
        "restore_grade": False,
        "rollback_supported": False,
        "rollback_semantics": {
            "status": "not_implemented",
            "safe_use": "diff_replay_and_operator_review",
            "requires_future_capability": "restore_grade_snapshot_or_transaction_rollback",
        },
        "limitations": {
            "durable_payloads_captured": False,
            "ledger_rows_captured": False,
            "content_objects_captured": False,
            "retrieval_index_bytes_captured": False,
            "graph_store_bytes_captured": False,
        },
        "operator_guidance": (
            "This snapshot manifest is not a restore point; use it for "
            "diffing, replay planning, and operator review only."
        ),
    }


class SnapshotService:
    """Create durable snapshot manifest receipts from current ledger state."""

    def __init__(self, ledger: MemoryOSLedger) -> None:
        self.ledger = ledger

    def create_snapshot(
        self,
        *,
        created_by: str,
        lancedb_rebuild_manifest_ref: str | None = None,
        kuzu_rebuild_manifest_ref: str | None = None,
    ) -> dict[str, Any]:
        created_at = now_iso()
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
            "schema_version": SNAPSHOT_MANIFEST_SCHEMA_VERSION,
            "snapshot_id": stable_id(
                "snapshot",
                {
                    "ledger_revision": ledger_revision,
                    "source_state": source_state,
                    "policy_state": policy_state,
                    "created_by": created_by,
                    "created_at": created_at,
                },
            ),
            "ledger_revision": ledger_revision,
            "source_manifest_hash": hash_payload(source_state),
            "lancedb_rebuild_manifest_ref": lancedb_rebuild_manifest_ref,
            "kuzu_rebuild_manifest_ref": kuzu_rebuild_manifest_ref,
            "policy_manifest_hash": hash_payload(policy_state),
            "created_by": created_by,
            "created_at": created_at,
            **snapshot_manifest_semantics(),
        }
        upsert_record(self.ledger, "snapshots", snapshot["snapshot_id"], snapshot)
        return snapshot

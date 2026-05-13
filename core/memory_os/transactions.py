"""Reviewable transaction receipts for Memory OS writes."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


class MemoryTransactionService:
    """Record dry-run, promotion, and rollback receipts in the ledger."""

    def __init__(self, ledger: MemoryOSLedger) -> None:
        self.ledger = ledger

    def dry_run(
        self,
        *,
        operation_kind: str,
        proposed_writes: list[dict[str, Any]],
        idempotency_key: str,
        affected_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._receipt(
            operation_kind=operation_kind,
            proposed_writes=proposed_writes,
            idempotency_key=idempotency_key,
            affected_refs=affected_refs or [],
            status="dry_run",
            write_performed=False,
        )

    def promote(
        self,
        *,
        operation_kind: str,
        proposed_writes: list[dict[str, Any]],
        idempotency_key: str,
        snapshot_ref: str | None = None,
        affected_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        existing = self._find_by_idempotency_key(idempotency_key)
        if existing is not None:
            replay = dict(existing)
            replay["idempotent_replay"] = True
            return replay

        receipt = self._receipt(
            operation_kind=operation_kind,
            proposed_writes=proposed_writes,
            idempotency_key=idempotency_key,
            affected_refs=affected_refs or [],
            status="promoted",
            write_performed=True,
            snapshot_ref=snapshot_ref,
        )
        upsert_record(self.ledger, "transactions", receipt["transaction_id"], receipt)
        return receipt

    def rollback(self, transaction_id: str, *, snapshot_ref: str) -> dict[str, Any]:
        existing = self._find(transaction_id)
        if existing is None:
            raise KeyError(f"transaction not found: {transaction_id}")
        receipt = dict(existing)
        receipt["status"] = "rolled_back"
        receipt["rollback_snapshot_ref"] = snapshot_ref
        receipt["rolled_back_at"] = now_iso()
        upsert_record(self.ledger, "transactions", transaction_id, receipt)
        return receipt

    def _find(self, transaction_id: str) -> dict[str, Any] | None:
        for record in list_records(self.ledger, "transactions"):
            if record.get("transaction_id") == transaction_id:
                return record
        return None

    def _find_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        for record in list_records(self.ledger, "transactions"):
            if record.get("idempotency_key") == idempotency_key:
                return record
        return None

    @staticmethod
    def _receipt(
        *,
        operation_kind: str,
        proposed_writes: list[dict[str, Any]],
        idempotency_key: str,
        affected_refs: list[dict[str, Any]],
        status: str,
        write_performed: bool,
        snapshot_ref: str | None = None,
    ) -> dict[str, Any]:
        transaction_id = stable_id(
            "txn",
            {
                "operation_kind": operation_kind,
                "idempotency_key": idempotency_key,
                "proposed_writes": proposed_writes,
            },
        )
        return {
            "transaction_id": transaction_id,
            "operation_kind": operation_kind,
            "idempotency_key": idempotency_key,
            "proposed_writes": proposed_writes,
            "affected_refs": affected_refs,
            "snapshot_ref": snapshot_ref,
            "status": status,
            "write_performed": write_performed,
            "idempotent_replay": False,
            "created_at": now_iso(),
        }

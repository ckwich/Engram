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
            if existing.get("status") == "degraded":
                receipt = self._receipt(
                    operation_kind=operation_kind,
                    proposed_writes=proposed_writes,
                    idempotency_key=idempotency_key,
                    affected_refs=affected_refs or [],
                    status="promoted",
                    write_performed=True,
                    snapshot_ref=snapshot_ref,
                )
                receipt["transaction_id"] = existing["transaction_id"]
                receipt["repaired_from_degraded"] = True
                receipt["previous_degraded_error"] = existing.get("error")
                upsert_record(self.ledger, "transactions", receipt["transaction_id"], receipt)
                return receipt
            if existing.get("status") == "promoted":
                repaired_ids = self._mark_degraded_children_repaired(
                    idempotency_key,
                    repaired_by_transaction_id=str(existing.get("transaction_id") or ""),
                )
                replay = dict(existing)
                replay["idempotent_replay"] = True
                if repaired_ids:
                    replay["repaired_degraded_transaction_ids"] = repaired_ids
                return replay
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

    def degraded(
        self,
        *,
        operation_kind: str,
        proposed_writes: list[dict[str, Any]],
        idempotency_key: str,
        failed_gate: str,
        error: dict[str, Any],
        repair_guidance: str,
        affected_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        existing = self._find_by_idempotency_key(idempotency_key)
        original_promoted_transaction_id = None
        if existing is not None and existing.get("status") == "promoted":
            original_promoted_transaction_id = existing.get("transaction_id")
            idempotency_key = f"{idempotency_key}:degraded:{failed_gate}"
            existing_degraded = self._find_by_idempotency_key(idempotency_key)
            if existing_degraded is not None:
                replay = dict(existing_degraded)
                replay["idempotent_replay"] = True
                return replay
            existing = None
        receipt = self._receipt(
            operation_kind=operation_kind,
            proposed_writes=proposed_writes,
            idempotency_key=idempotency_key,
            affected_refs=affected_refs or [],
            status="degraded",
            write_performed=True,
        )
        if existing is not None:
            receipt["transaction_id"] = existing["transaction_id"]
        receipt.update(
            {
                "repair_required": True,
                "failed_gate": failed_gate,
                "error": error,
                "repair_guidance": repair_guidance,
                "original_promoted_transaction_id": original_promoted_transaction_id,
            }
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

    def find_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        existing = self._find_by_idempotency_key(idempotency_key)
        return dict(existing) if existing is not None else None

    def mark_degraded_children_repaired(
        self,
        idempotency_key: str,
        *,
        repaired_by_transaction_id: str,
    ) -> list[str]:
        return self._mark_degraded_children_repaired(
            idempotency_key,
            repaired_by_transaction_id=repaired_by_transaction_id,
        )

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

    def _mark_degraded_children_repaired(
        self,
        idempotency_key: str,
        *,
        repaired_by_transaction_id: str,
    ) -> list[str]:
        repaired_ids: list[str] = []
        child_prefix = f"{idempotency_key}:degraded:"
        for record in list_records(self.ledger, "transactions"):
            if record.get("status") != "degraded":
                continue
            if not str(record.get("idempotency_key") or "").startswith(child_prefix):
                continue
            repaired = dict(record)
            repaired["status"] = "repaired"
            repaired["repair_required"] = False
            repaired["repaired_at"] = now_iso()
            repaired["repaired_by_transaction_id"] = repaired_by_transaction_id
            upsert_record(self.ledger, "transactions", repaired["transaction_id"], repaired)
            repaired_ids.append(str(repaired["transaction_id"]))
        return repaired_ids

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

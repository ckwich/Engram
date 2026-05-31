from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.transactions import MemoryTransactionService


def test_transaction_can_dry_run_promote_once_and_roll_back(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    service = MemoryTransactionService(ledger)

    dry_run = service.dry_run(
        operation_kind="promote_document_draft",
        proposed_writes=[{"kind": "memory", "key": "alpha"}],
        idempotency_key="draft-alpha",
    )
    promoted = service.promote(
        operation_kind="promote_document_draft",
        proposed_writes=[{"kind": "memory", "key": "alpha"}],
        idempotency_key="draft-alpha",
        snapshot_ref="snapshot:before-alpha",
    )
    replay = service.promote(
        operation_kind="promote_document_draft",
        proposed_writes=[{"kind": "memory", "key": "alpha"}],
        idempotency_key="draft-alpha",
        snapshot_ref="snapshot:before-alpha",
    )
    rollback = service.rollback(promoted["transaction_id"], snapshot_ref="snapshot:before-alpha")

    assert dry_run["status"] == "dry_run"
    assert dry_run["write_performed"] is False
    assert promoted["status"] == "promoted"
    assert promoted["write_performed"] is True
    assert replay["transaction_id"] == promoted["transaction_id"]
    assert replay["idempotent_replay"] is True
    assert rollback["status"] == "rolled_back"
    assert rollback["rollback_snapshot_ref"] == "snapshot:before-alpha"


def test_degraded_transaction_can_be_repaired_by_successful_promote(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    service = MemoryTransactionService(ledger)

    degraded = service.degraded(
        operation_kind="store_memory",
        proposed_writes=[{"kind": "memory", "key": "alpha"}],
        idempotency_key="store-alpha",
        affected_refs=[{"kind": "memory", "key": "alpha"}],
        failed_gate="retrieval",
        error={"code": "memory_write_degraded", "message": "forced"},
        repair_guidance="retry store_memory",
    )
    promoted = service.promote(
        operation_kind="store_memory",
        proposed_writes=[{"kind": "memory", "key": "alpha"}],
        idempotency_key="store-alpha",
    )

    assert degraded["status"] == "degraded"
    assert degraded["repair_required"] is True
    assert promoted["transaction_id"] == degraded["transaction_id"]
    assert promoted["status"] == "promoted"
    assert promoted["repaired_from_degraded"] is True
    assert promoted["previous_degraded_error"]["message"] == "forced"

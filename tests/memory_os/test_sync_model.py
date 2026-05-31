from core.memory_os.sync_model import (
    SyncApplyPlan,
    SyncChangesetSummary,
    SyncConflict,
    SyncCursor,
)


def test_sync_cursor_as_dict_is_stable():
    cursor = SyncCursor(
        peer_device_id="device:desktop",
        table="memories",
        last_seen_transaction_id="txn:abc",
        updated_at="2026-05-26T00:00:00+00:00",
    )

    assert cursor.as_dict() == {
        "record_type": "sync_cursor",
        "peer_device_id": "device:desktop",
        "table": "memories",
        "last_seen_transaction_id": "txn:abc",
        "updated_at": "2026-05-26T00:00:00+00:00",
    }


def test_sync_changeset_summary_as_dict_keeps_counts_and_hashes():
    summary = SyncChangesetSummary(
        changeset_id="sync_changeset:abc",
        source_device_id="device:laptop",
        target_device_id="device:desktop",
        row_count=12,
        object_count=3,
        bundle_hash="sha256:bundle",
        created_at="2026-05-26T00:00:00+00:00",
    )

    assert summary.as_dict()["record_type"] == "sync_changeset_summary"
    assert summary.as_dict()["row_count"] == 12
    assert summary.as_dict()["bundle_hash"] == "sha256:bundle"


def test_sync_conflict_as_dict_preserves_resolution_state():
    conflict = SyncConflict(
        conflict_id="sync_conflict:abc",
        table="memories",
        record_id="memory:one",
        local_transaction_id="txn:local",
        remote_transaction_id="txn:remote",
        status="pending_review",
        detected_at="2026-05-26T00:00:00+00:00",
    )

    assert conflict.as_dict() == {
        "record_type": "sync_conflict",
        "conflict_id": "sync_conflict:abc",
        "table": "memories",
        "record_id": "memory:one",
        "local_transaction_id": "txn:local",
        "remote_transaction_id": "txn:remote",
        "status": "pending_review",
        "detected_at": "2026-05-26T00:00:00+00:00",
        "resolution": None,
    }


def test_sync_apply_plan_as_dict_keeps_review_counts():
    plan = SyncApplyPlan(
        plan_id="sync_apply_plan:abc",
        source_device_id="device:laptop",
        target_device_id="device:desktop",
        changeset_id="sync_changeset:abc",
        apply_count=10,
        conflict_count=2,
        status="needs_review",
    )

    assert plan.as_dict()["record_type"] == "sync_apply_plan"
    assert plan.as_dict()["status"] == "needs_review"
    assert plan.as_dict()["conflict_count"] == 2

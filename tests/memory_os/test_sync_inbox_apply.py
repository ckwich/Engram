import core.memory_os.sync_apply as sync_apply_module
import core.memory_os.sync_inbox_apply as sync_inbox_apply_module
from core.memory_os._records import read_record, upsert_record
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_changesets import export_sync_changeset, prepare_sync_changeset
from core.memory_os.sync_identity import (
    ensure_device_identity,
    export_local_sync_identity,
    register_sync_peer,
)
from core.memory_os.sync_inbox_apply import apply_sync_inbox, prepare_sync_inbox_apply
from core.memory_os.sync_inbox_apply import prune_applied_sync_inbox_artifacts
from core.memory_os.sync_transport import store_inbound_sync_bundle


def _staged_bundle_for_target(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(laptop.ledger, export_local_sync_identity(desktop.ledger), accept=True, approved_by="tester")
    register_sync_peer(desktop.ledger, export_local_sync_identity(laptop.ledger), accept=True, approved_by="tester")
    laptop.store_memory(
        key="staged_inbox_note",
        content="Created on laptop and staged in the desktop sync inbox.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    exported = export_sync_changeset(
        laptop,
        prepare_sync_changeset(laptop, peer_id=desktop_id),
        accept=True,
        approved_by="tester",
    )
    bundle = laptop.content_store.read_bytes(exported["artifact_id"])
    inbox = store_inbound_sync_bundle(
        desktop,
        bundle,
        {"transport_type": "sync_peer", "peer_id": export_local_sync_identity(laptop.ledger)["device_id"]},
    )
    return desktop, inbox


def test_prepare_sync_inbox_apply_classifies_staged_bundles_without_writing(tmp_path):
    runtime, inbox = _staged_bundle_for_target(tmp_path)

    plan = prepare_sync_inbox_apply(runtime)
    stored_inbox = read_record(runtime.ledger, "sync_inbox", inbox["inbox_id"])

    assert plan["status"] == "ready"
    assert plan["write_performed"] is False
    assert plan["pending_bundle_count"] == 1
    assert plan["insert_count"] >= 1
    assert plan["bundles"][0]["artifact_id"] == inbox["artifact_id"]
    assert plan["bundles"][0]["prepare_duration_ms"] >= 0
    assert "apply_rows" not in plan["bundles"][0]
    assert stored_inbox["status"] == "received"
    assert stored_inbox["apply_performed"] is False


def test_prepare_sync_apply_batches_local_row_reads(tmp_path, monkeypatch):
    runtime, inbox = _staged_bundle_for_target(tmp_path)
    bundle = runtime.content_store.read_bytes(inbox["artifact_id"])
    calls = []
    original_read_record = sync_apply_module.read_record

    def counting_read_record(ledger, table, record_id):
        calls.append((table, record_id))
        return original_read_record(ledger, table, record_id)

    monkeypatch.setattr(sync_apply_module, "read_record", counting_read_record)

    plan = sync_apply_module.prepare_sync_apply(runtime, bundle)

    assert plan["status"] == "ready"
    assert plan["insert_count"] >= 1
    per_row_reads = [
        call for call in calls
        if call[0] in sync_apply_module.SYNC_IMPORT_TABLES
    ]
    assert per_row_reads == []


def test_prepare_sync_inbox_apply_reuses_runtime_cached_plan(tmp_path, monkeypatch):
    runtime, _inbox = _staged_bundle_for_target(tmp_path)

    first = sync_inbox_apply_module.prepare_sync_inbox_apply(runtime, limit=1)

    assert first["status"] == "ready"
    assert first["bundles"][0]["cache_status"] == "miss"

    def fail_prepare_sync_apply(_runtime, _bundle):
        raise AssertionError("cached inbox plan should avoid decrypting the bundle again")

    monkeypatch.setattr(sync_inbox_apply_module, "prepare_sync_apply", fail_prepare_sync_apply)

    second = sync_inbox_apply_module.prepare_sync_inbox_apply(runtime, limit=1)

    assert second["status"] == "ready"
    assert second["bundles"][0]["cache_status"] == "hit"
    assert second["bundles"][0]["changeset_id"] == first["bundles"][0]["changeset_id"]


def test_apply_sync_inbox_requires_acceptance(tmp_path):
    runtime, _inbox = _staged_bundle_for_target(tmp_path)

    result = apply_sync_inbox(runtime, accept=False, approved_by="tester")

    assert result["status"] == "policy_denied"
    assert result["write_performed"] is False
    assert result["error"]["code"] == "acceptance_required"


def test_apply_sync_inbox_applies_and_marks_staged_bundle(tmp_path):
    runtime, inbox = _staged_bundle_for_target(tmp_path)
    artifact_path = runtime.content_store.path_for(inbox["artifact_id"])

    assert artifact_path.exists()
    result = apply_sync_inbox(runtime, accept=True, approved_by="tester", limit=0)
    replay = prepare_sync_inbox_apply(runtime, limit=0)
    imported = read_record(runtime.ledger, "memories", "staged_inbox_note")
    stored_inbox = read_record(runtime.ledger, "sync_inbox", inbox["inbox_id"])

    assert result["status"] == "applied"
    assert result["write_performed"] is True
    assert result["processed_bundle_count"] == 1
    assert result["applied_bundle_count"] == 1
    assert result["applied_count"] >= 1
    assert imported["key"] == "staged_inbox_note"
    assert stored_inbox["status"] == "applied"
    assert stored_inbox["apply_performed"] is True
    assert stored_inbox["apply_result"]["changeset_id"] == result["bundles"][0]["changeset_id"]
    assert result["bundles"][0]["artifact_prune"]["status"] == "deleted"
    assert stored_inbox["artifact_prune_status"] == "deleted"
    assert stored_inbox["artifact_size_bytes_pruned"] > 0
    assert not artifact_path.exists()
    assert replay["status"] == "empty"
    assert replay["pending_bundle_count"] == 0


def test_prune_applied_sync_inbox_artifacts_requires_acceptance(tmp_path):
    runtime, inbox = _staged_bundle_for_target(tmp_path)
    result = apply_sync_inbox(runtime, accept=True, approved_by="tester", limit=0)

    denied = prune_applied_sync_inbox_artifacts(runtime, accept=True, approved_by=None, limit=0)
    dry_run = prune_applied_sync_inbox_artifacts(runtime, accept=False, approved_by=None, limit=0)

    assert result["status"] == "applied"
    assert denied["status"] == "policy_denied"
    assert denied["error"]["code"] == "acceptance_required"
    assert dry_run["status"] == "empty"
    assert dry_run["candidate_count"] == 0
    assert read_record(runtime.ledger, "sync_inbox", inbox["inbox_id"])["artifact_prune_status"] == "deleted"


def test_prune_applied_sync_inbox_artifacts_deletes_legacy_applied_payload(tmp_path):
    runtime, inbox = _staged_bundle_for_target(tmp_path)
    record = read_record(runtime.ledger, "sync_inbox", inbox["inbox_id"])
    artifact_path = runtime.content_store.path_for(inbox["artifact_id"])
    upsert_record(
        runtime.ledger,
        "sync_inbox",
        inbox["inbox_id"],
        {
            **record,
            "status": "applied",
            "apply_performed": True,
            "applied_at": "2026-05-28T00:00:00-07:00",
        },
    )

    dry_run = prune_applied_sync_inbox_artifacts(runtime, accept=False, approved_by=None, limit=0)

    assert dry_run["status"] == "ready"
    assert dry_run["candidate_count"] == 1
    assert dry_run["bytes_prunable"] > 0
    assert artifact_path.exists()

    pruned = prune_applied_sync_inbox_artifacts(runtime, accept=True, approved_by="tester", limit=0)
    stored = read_record(runtime.ledger, "sync_inbox", inbox["inbox_id"])

    assert pruned["status"] == "pruned"
    assert pruned["pruned_count"] == 1
    assert pruned["bytes_pruned"] == dry_run["bytes_prunable"]
    assert stored["artifact_prune_status"] == "deleted"
    assert not artifact_path.exists()

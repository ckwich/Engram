from core.memory_os._records import list_records, read_record
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_apply import (
    apply_sync_changeset,
    list_sync_conflicts,
    prepare_sync_apply,
    resolve_sync_conflict,
)
from core.memory_os.sync_changesets import export_sync_changeset, prepare_sync_changeset
from core.memory_os.sync_identity import ensure_device_identity, export_local_sync_identity, register_sync_peer


def _conflicted_runtime(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(laptop.ledger, export_local_sync_identity(desktop.ledger), accept=True, approved_by="tester")
    register_sync_peer(desktop.ledger, export_local_sync_identity(laptop.ledger), accept=True, approved_by="tester")
    laptop.store_memory(
        key="shared_key",
        content="Laptop version.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )
    desktop.store_memory(
        key="shared_key",
        content="Desktop version.",
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
    plan = prepare_sync_apply(desktop, laptop.content_store.read_bytes(exported["artifact_id"]))
    apply_sync_changeset(
        desktop,
        laptop.content_store.read_bytes(exported["artifact_id"]),
        plan,
        accept=True,
        approved_by="tester",
    )
    return desktop


def test_conflict_apply_writes_sync_conflict_and_knowledge_pr(tmp_path):
    runtime = _conflicted_runtime(tmp_path)

    conflicts = list_sync_conflicts(runtime)

    assert conflicts["unresolved_conflict_count"] == 1
    conflict = conflicts["conflicts"][0]
    assert conflict["status"] == "pending_review"
    assert conflict["table"] == "memories"
    assert "remote_payload" not in conflict
    assert conflict["knowledge_pr_id"].startswith("kpr:")
    assert read_record(runtime.ledger, "knowledge_prs", conflict["knowledge_pr_id"]) is not None


def test_resolve_sync_conflict_requires_explicit_review_and_does_not_overwrite_memory(tmp_path):
    runtime = _conflicted_runtime(tmp_path)
    conflict = list_records(runtime.ledger, "sync_conflicts")[0]
    before = read_record(runtime.ledger, "memories", "shared_key")

    denied = resolve_sync_conflict(
        runtime,
        conflict["conflict_id"],
        resolution="keep_local",
        accept=False,
        approved_by="tester",
    )
    resolved = resolve_sync_conflict(
        runtime,
        conflict["conflict_id"],
        resolution="keep_local",
        accept=True,
        approved_by="tester",
    )
    after = read_record(runtime.ledger, "memories", "shared_key")

    assert denied["status"] == "policy_denied"
    assert denied["write_performed"] is False
    assert resolved["status"] == "resolved"
    assert resolved["write_performed"] is True
    assert after["content_hash"] == before["content_hash"]

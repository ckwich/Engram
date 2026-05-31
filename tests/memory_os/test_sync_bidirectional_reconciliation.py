from core.memory_os._records import read_record
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_apply import apply_sync_changeset, prepare_sync_apply
from core.memory_os.sync_changesets import (
    export_sync_changeset,
    inspect_sync_convergence,
    prepare_sync_changeset,
)
from core.memory_os.sync_identity import ensure_device_identity, export_local_sync_identity, register_sync_peer


def _paired_runtimes(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(laptop.ledger, export_local_sync_identity(desktop.ledger), accept=True, approved_by="tester")
    register_sync_peer(desktop.ledger, export_local_sync_identity(laptop.ledger), accept=True, approved_by="tester")
    return laptop, desktop


def _round_trip_sync(left, right, approved_by="tester"):
    right_id = export_local_sync_identity(right.ledger)["device_id"]
    left_export = export_sync_changeset(
        left,
        prepare_sync_changeset(left, peer_id=right_id),
        accept=True,
        approved_by=approved_by,
    )
    left_bundle = left.content_store.read_bytes(left_export["artifact_id"])
    right_plan = prepare_sync_apply(right, left_bundle)
    apply_sync_changeset(right, left_bundle, right_plan, accept=True, approved_by=approved_by)

    left_id = export_local_sync_identity(left.ledger)["device_id"]
    right_export = export_sync_changeset(
        right,
        prepare_sync_changeset(right, peer_id=left_id),
        accept=True,
        approved_by=approved_by,
    )
    right_bundle = right.content_store.read_bytes(right_export["artifact_id"])
    left_plan = prepare_sync_apply(left, right_bundle)
    apply_sync_changeset(left, right_bundle, left_plan, accept=True, approved_by=approved_by)


def test_bidirectional_sync_imports_distinct_rows_from_both_devices(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    laptop.store_memory(
        key="laptop_note",
        content="Created on laptop.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )
    desktop.store_memory(
        key="desktop_note",
        content="Created on desktop.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )

    _round_trip_sync(laptop, desktop)

    assert read_record(laptop.ledger, "memories", "desktop_note")["content_hash"].startswith("sha256:")
    assert read_record(desktop.ledger, "memories", "laptop_note")["content_hash"].startswith("sha256:")
    convergence = inspect_sync_convergence(laptop, peer_id=export_local_sync_identity(desktop.ledger)["device_id"])
    assert convergence["converged"] is True


def test_same_key_different_content_creates_conflict_without_overwrite(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
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

    _round_trip_sync(laptop, desktop)

    assert read_record(laptop.ledger, "memories", "shared_key")["content_hash"] != read_record(
        desktop.ledger,
        "memories",
        "shared_key",
    )["content_hash"]
    laptop_state = inspect_sync_convergence(laptop, peer_id=export_local_sync_identity(desktop.ledger)["device_id"])
    assert laptop_state["converged"] is False
    assert laptop_state["unresolved_conflict_count"] == 1

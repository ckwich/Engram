from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_apply import apply_sync_changeset, prepare_sync_apply
from core.memory_os.sync_changesets import export_sync_changeset, prepare_sync_changeset
from core.memory_os.sync_identity import (
    ensure_device_identity,
    export_local_sync_identity,
    register_sync_peer,
)


def _encrypted_bundle_for_target(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(laptop.ledger, export_local_sync_identity(desktop.ledger), accept=True, approved_by="tester")
    register_sync_peer(desktop.ledger, export_local_sync_identity(laptop.ledger), accept=True, approved_by="tester")
    laptop.store_memory(
        key="laptop_export_note",
        content="Created on laptop for sync apply.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    export = export_sync_changeset(
        laptop,
        prepare_sync_changeset(laptop, peer_id=desktop_id),
        accept=True,
        approved_by="tester",
    )
    return desktop, laptop.content_store.read_bytes(export["artifact_id"])


def test_prepare_sync_apply_verifies_encrypted_idempotent_replay(tmp_path):
    runtime, bundle = _encrypted_bundle_for_target(tmp_path)

    plan = prepare_sync_apply(runtime, bundle)

    assert plan["write_performed"] is False
    assert plan["status"] == "ready"
    assert plan["signature_verified"] is True
    assert plan["conflict_count"] == 0
    assert plan["insert_count"] >= 1
    assert plan["required_snapshot"]["present"] is True


def test_apply_sync_changeset_requires_snapshot(tmp_path):
    runtime, bundle = _encrypted_bundle_for_target(tmp_path)
    plan = prepare_sync_apply(runtime, bundle)
    plan["required_snapshot"] = {"present": False}

    result = apply_sync_changeset(runtime, bundle, plan, accept=True, approved_by="tester")

    assert result["status"] == "policy_denied"
    assert result["write_performed"] is False
    assert result["error"]["code"] == "runtime_snapshot_required"


def test_apply_sync_changeset_imports_rows_objects_and_cursor(tmp_path):
    runtime, bundle = _encrypted_bundle_for_target(tmp_path)
    plan = prepare_sync_apply(runtime, bundle)

    result = apply_sync_changeset(runtime, bundle, plan, accept=True, approved_by="tester")
    replay = prepare_sync_apply(runtime, bundle)

    assert result["status"] == "applied"
    assert result["write_performed"] is True
    assert result["snapshot"]["restore_grade"] is True
    assert result["applied_count"] >= 1
    assert result["conflict_count"] == 0
    assert replay["idempotent_count"] >= result["applied_count"]


def test_apply_sync_changeset_retries_same_review_plan_idempotently(tmp_path):
    runtime, bundle = _encrypted_bundle_for_target(tmp_path)
    plan = prepare_sync_apply(runtime, bundle)

    first = apply_sync_changeset(runtime, bundle, plan, accept=True, approved_by="tester")
    second = apply_sync_changeset(runtime, bundle, plan, accept=True, approved_by="tester")

    assert first["status"] == "applied"
    assert second["status"] == "applied"
    assert second["idempotent_replay"] is True
    assert second["transaction"]["idempotent_replay"] is True


def test_apply_sync_changeset_rejects_tampered_review_plan(tmp_path):
    runtime, bundle = _encrypted_bundle_for_target(tmp_path)
    plan = prepare_sync_apply(runtime, bundle)
    plan["insert_count"] = 0

    result = apply_sync_changeset(runtime, bundle, plan, accept=True, approved_by="tester")

    assert result["status"] == "policy_denied"
    assert result["write_performed"] is False
    assert result["error"]["code"] == "review_plan_mismatch"


def test_prepare_sync_apply_rejects_malformed_object_artifact_id(tmp_path):
    runtime, bundle = _encrypted_bundle_for_target(tmp_path)
    payload = prepare_sync_apply.__globals__["decrypt_sync_bundle"](runtime, bundle)
    payload["objects"][0]["artifact_id"] = "not-an-artifact-id"

    class FakeRuntime:
        ledger = runtime.ledger

    def fake_decrypt(_runtime, _bundle):
        return payload

    original = prepare_sync_apply.__globals__["decrypt_sync_bundle"]
    prepare_sync_apply.__globals__["decrypt_sync_bundle"] = fake_decrypt
    try:
        result = prepare_sync_apply(FakeRuntime(), bundle)
    finally:
        prepare_sync_apply.__globals__["decrypt_sync_bundle"] = original

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "malformed_object_artifact_id"

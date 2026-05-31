import os

from core.memory_os._records import list_records, upsert_record
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_crypto import LOCAL_SYNC_IDENTITY_FILE, load_or_create_local_sync_keys
from core.memory_os.sync_identity import (
    ensure_device_identity,
    export_local_sync_identity,
    register_sync_peer,
    revoke_sync_peer,
    rotate_local_sync_keys,
)


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    return runtime


def test_device_identity_is_stable_and_ledgered(tmp_path):
    runtime = _runtime(tmp_path)

    first = ensure_device_identity(runtime.ledger, device_name="laptop")
    second = ensure_device_identity(runtime.ledger, device_name="laptop")

    assert first["device_id"] == second["device_id"]
    assert first["device_name"] == "laptop"
    assert first["signing_public_key"].startswith("ed25519:")
    assert first["exchange_public_key"].startswith("x25519:")
    assert first["signing_key_fingerprint"].startswith("sha256:")
    assert first["status"] == "active"
    assert "private_key" not in first


def test_export_local_identity_contains_no_secret_material(tmp_path):
    runtime = _runtime(tmp_path)
    ensure_device_identity(runtime.ledger, device_name="laptop")

    packet = export_local_sync_identity(runtime.ledger)

    assert packet["record_type"] == "sync_public_identity"
    assert packet["signing_public_key"].startswith("ed25519:")
    assert packet["exchange_public_key"].startswith("x25519:")
    assert "private" not in str(packet).lower()


def test_key_rotation_supersedes_old_identity(tmp_path):
    runtime = _runtime(tmp_path)
    first = ensure_device_identity(runtime.ledger, device_name="laptop")

    rotated = rotate_local_sync_keys(runtime.ledger, accept=True, approved_by="tester")

    assert rotated["write_performed"] is True
    assert rotated["previous_signing_key_fingerprint"] == first["signing_key_fingerprint"]
    assert rotated["local_device"]["device_id"] == first["device_id"]
    assert rotated["local_device"]["signing_key_fingerprint"] != first["signing_key_fingerprint"]
    assert "private" not in str(rotated).lower()
    assert any(record.get("status") == "superseded" for record in list_records(runtime.ledger, "sync_devices"))


def test_register_peer_requires_acceptance_and_rejects_private_material(tmp_path):
    local = _runtime(tmp_path / "local")
    peer = _runtime(tmp_path / "peer")
    ensure_device_identity(local.ledger, device_name="laptop")
    ensure_device_identity(peer.ledger, device_name="desktop")
    packet = export_local_sync_identity(peer.ledger)

    dry_run = register_sync_peer(local.ledger, packet, accept=False, approved_by="tester")
    rejected = register_sync_peer(
        local.ledger,
        {**packet, "private_key": "do-not-import"},
        accept=True,
        approved_by="tester",
    )
    registered = register_sync_peer(local.ledger, packet, accept=True, approved_by="tester")

    assert dry_run["write_performed"] is False
    assert dry_run["status"] == "policy_denied"
    assert rejected["write_performed"] is False
    assert rejected["error"]["code"] == "private_key_material_rejected"
    assert registered["write_performed"] is True
    assert registered["peer"]["device_id"] == packet["device_id"]
    assert registered["peer"]["status"] == "active"


def test_revoked_peer_cannot_be_re_registered(tmp_path):
    local = _runtime(tmp_path / "local")
    peer = _runtime(tmp_path / "peer")
    ensure_device_identity(local.ledger, device_name="laptop")
    ensure_device_identity(peer.ledger, device_name="desktop")
    packet = export_local_sync_identity(peer.ledger)

    registered = register_sync_peer(local.ledger, packet, accept=True, approved_by="tester")
    revoked = revoke_sync_peer(
        local.ledger,
        peer_id=packet["device_id"],
        reason="lost_device",
        accept=True,
        approved_by="tester",
    )
    reactivated = register_sync_peer(local.ledger, packet, accept=True, approved_by="tester")

    assert registered["status"] == "registered"
    assert revoked["peer"]["status"] == "revoked"
    assert reactivated["write_performed"] is False
    assert reactivated["error"]["code"] == "peer_revoked"
    peer_record = [
        record for record in list_records(local.ledger, "sync_devices")
        if record.get("device_id") == packet["device_id"]
    ][0]
    assert peer_record["status"] == "revoked"
    assert peer_record["sync_allowed"] is False


def test_revoked_peer_cannot_sync(tmp_path):
    runtime = _runtime(tmp_path)

    result = revoke_sync_peer(
        runtime.ledger,
        peer_id="device:desktop",
        reason="lost_device",
        accept=True,
        approved_by="tester",
    )

    assert result["write_performed"] is True
    assert result["peer"]["status"] == "revoked"
    assert result["peer"]["sync_allowed"] is False


def test_runtime_sync_status_reports_devices_and_conflicts(tmp_path):
    runtime = _runtime(tmp_path)
    ensure_device_identity(runtime.ledger, device_name="laptop")
    revoke_sync_peer(
        runtime.ledger,
        peer_id="device:desktop",
        reason="lost_device",
        accept=True,
        approved_by="tester",
    )

    status = runtime.sync_status()
    runtime_status = runtime.status()
    inspector = runtime.inspector(limit=10)

    assert status["status"] == "ready"
    assert status["local_device"]["device_id"].startswith("device:")
    assert status["peer_count"] == 1
    assert runtime_status["components"]["sync"]["status"] == "ready"
    assert inspector["sync"]["status"]["status"] == "ready"


def test_runtime_identity_reports_write_only_when_state_created(tmp_path):
    runtime = _runtime(tmp_path)

    first = runtime.ensure_sync_device_identity(device_name="laptop")
    second = runtime.ensure_sync_device_identity(device_name="laptop")

    assert first["write_performed"] is True
    assert second["write_performed"] is False


def test_inspector_redacts_sensitive_sync_records(tmp_path):
    runtime = _runtime(tmp_path)
    upsert_record(
        runtime.ledger,
        "sync_devices",
        "sync_device:malformed",
        {
            "record_type": "sync_peer",
            "device_id": "device:malformed",
            "signing_public_key": "ed25519:public",
            "signing_private_key": "should-not-leak",
            "nested": {"exchange_private_key": "should-not-leak-either"},
            "status": "active",
        },
    )

    inspector = runtime.inspector(limit=10)

    assert "should-not-leak" not in str(inspector)
    assert "should-not-leak-either" not in str(inspector)
    assert inspector["sync"]["devices"]["items"][0]["signing_private_key"]["redacted"] is True
    assert inspector["sync"]["devices"]["items"][0]["nested"]["exchange_private_key"]["redacted"] is True


def test_existing_sync_key_file_permissions_are_repaired_on_load(tmp_path):
    keys_dir = tmp_path / "keys"
    keys = load_or_create_local_sync_keys(keys_dir)
    key_path = keys_dir / LOCAL_SYNC_IDENTITY_FILE
    if os.name != "posix":
        return

    os.chmod(key_path, 0o644)
    loaded = load_or_create_local_sync_keys(keys_dir)

    assert loaded.signing_public_key == keys.signing_public_key
    assert (key_path.stat().st_mode & 0o777) == 0o600

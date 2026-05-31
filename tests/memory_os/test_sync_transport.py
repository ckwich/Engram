from core.memory_limits import DAEMON_MAX_CONTENT_LENGTH_ENV
from core.memory_os._records import upsert_record
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_file_transport import export_bundle_to_file, import_bundle_from_file
from core.memory_os.sync_transport import list_sync_inbox, register_sync_transport_receipt, store_inbound_sync_bundle


def test_file_transport_moves_only_encrypted_bundle_bytes(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    bundle = b'{"schema_version":"2026-05-26.sync-envelope.v1","ciphertext":"abc"}'

    path = export_bundle_to_file(runtime, bundle, tmp_path / "outbox" / "delta.engram-sync")
    imported = import_bundle_from_file(runtime, path)

    assert imported["write_performed"] is True
    assert imported["apply_performed"] is False
    assert imported["inbox_id"].startswith("sync_inbox:")
    assert imported["artifact_id"].startswith("sha256:")
    assert b"ciphertext" in path.read_bytes()
    assert b"payload_json" not in path.read_bytes()


def test_transport_receipt_records_delivery_without_apply(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)

    receipt = register_sync_transport_receipt(
        runtime,
        {
            "transport_type": "file_bundle",
            "peer_id": "device:desktop",
            "artifact_id": "sha256:abc",
            "direction": "inbound",
            "status": "received",
        },
    )

    assert receipt["receipt_id"].startswith("sync_transport:")
    assert receipt["apply_performed"] is False


def test_transport_receipt_rejects_apply_success_claim(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)

    receipt = register_sync_transport_receipt(
        runtime,
        {
            "transport_type": "file_bundle",
            "peer_id": "device:desktop",
            "direction": "inbound",
            "status": "applied",
            "apply_performed": True,
        },
    )

    assert receipt["status"] == "policy_denied"
    assert receipt["error"]["code"] == "transport_must_not_claim_apply"


def test_inbound_sync_bundle_limit_respects_daemon_content_length_env(tmp_path, monkeypatch):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    bundle = b"x" * 1500

    monkeypatch.setenv(DAEMON_MAX_CONTENT_LENGTH_ENV, "1024")
    denied = store_inbound_sync_bundle(runtime, bundle)

    monkeypatch.setenv(DAEMON_MAX_CONTENT_LENGTH_ENV, "4096")
    accepted = store_inbound_sync_bundle(runtime, bundle)

    assert denied["status"] == "policy_denied"
    assert denied["error"]["code"] == "sync_bundle_too_large"
    assert accepted["status"] == "received"
    assert accepted["apply_performed"] is False


def test_list_sync_inbox_returns_only_bundle_records(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    bundle = b'{"schema_version":"2026-05-26.sync-envelope.v1","ciphertext":"abc"}'

    stored = store_inbound_sync_bundle(runtime, bundle, {"transport_type": "sync_peer", "peer_id": "device:mac"})
    upsert_record(
        runtime.ledger,
        "sync_inbox",
        "sync_inbox:import-row",
        {
            "record_type": "sync_import_row",
            "source_device_id": "device:mac",
            "source_changeset_id": "sync_changeset:abc",
            "table": "memories",
            "record_id": "memory:abc",
            "source_payload_hash": "sha256:abc",
            "sync_policy": "local_only",
        },
    )
    upsert_record(
        runtime.ledger,
        "sync_inbox",
        "sync_inbox:conflict-payload",
        {
            "record_type": "sync_conflict_payload",
            "conflict_id": "sync_conflict:abc",
            "table": "memories",
            "record_id": "memory:abc",
            "sync_policy": "local_only",
        },
    )

    inbox = list_sync_inbox(runtime)

    assert inbox["inbox_count"] == 1
    assert inbox["inbox"][0]["inbox_id"] == stored["inbox_id"]
    assert inbox["inbox"][0]["artifact_id"] == stored["artifact_id"]

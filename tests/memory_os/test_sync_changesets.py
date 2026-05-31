import json

import pytest

from core.memory_os._records import list_records, upsert_record
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_changesets import (
    _rows_matching_json_field,
    export_sync_changeset,
    prepare_sync_changeset,
)
from core.memory_os.sync_crypto import decrypt_sync_bundle
from core.memory_os.sync_identity import (
    ensure_device_identity,
    export_local_sync_identity,
    register_sync_peer,
)


def _paired_runtimes(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(
        laptop.ledger,
        export_local_sync_identity(desktop.ledger),
        accept=True,
        approved_by="tester",
    )
    register_sync_peer(
        desktop.ledger,
        export_local_sync_identity(laptop.ledger),
        accept=True,
        approved_by="tester",
    )
    laptop.store_memory(
        key="sync_project_decision",
        title="Sync Project Decision",
        content="Use reviewed encrypted changesets only for offline divergence.",
        project="/Users/example/Projects/Engram",
        domain="sync",
        tags=["sync", "test"],
        memory_type="decision",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )
    laptop.store_memory(
        key="sync_local_device_note",
        title="Local Device Note",
        content="This row must stay on the local device.",
        domain="sync",
        memory_type="fact",
        scope="device",
        sync_policy="local_only",
    )
    return laptop, desktop


def test_prepare_sync_changeset_is_no_write(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)

    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    before = laptop.sync_status()
    plan = prepare_sync_changeset(laptop, peer_id=desktop_id)
    after = laptop.sync_status()

    assert plan["write_performed"] is False
    assert before == after
    assert plan["status"] == "ready"
    assert plan["changeset"]["table_count"] >= 2
    assert plan["changeset"]["row_count"] >= 2
    assert plan["changeset"]["object_count"] >= 1
    assert plan["changeset"]["excluded_rows"]["device_scope"] >= 1
    assert any(ref["table"] == "memories" for ref in plan["row_refs"])
    assert all(ref["table"] != "sync_devices" for ref in plan["row_refs"])


def test_sync_chunk_dependency_lookup_uses_memory_key_index(tmp_path):
    laptop, _desktop = _paired_runtimes(tmp_path)

    refs = _rows_matching_json_field(laptop, "chunks", "memory_key", "sync_project_decision")

    assert refs
    with laptop.ledger.connect() as conn:
        plan = conn.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT id FROM chunks
            WHERE json_extract(payload_json, '$.memory_key') = ?
            ORDER BY id
            """,
            ("sync_project_decision",),
        ).fetchall()
    details = " ".join(str(row["detail"]) for row in plan)
    assert "idx_chunks_memory_key_chunk_id" in details


def test_export_sync_changeset_writes_content_addressed_bundle(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)

    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    plan = prepare_sync_changeset(laptop, peer_id=desktop_id)
    export = export_sync_changeset(laptop, plan, accept=True, approved_by="tester")

    assert export["status"] == "exported"
    assert export["artifact_id"].startswith("sha256:")
    assert export["write_performed"] is True
    assert export["envelope"]["encrypted"] is True
    assert export["envelope"]["signature"].startswith("ed25519:")
    assert "rows" not in json.dumps(export)
    stored_bytes = laptop.content_store.read_bytes(export["artifact_id"])
    decrypted = decrypt_sync_bundle(desktop, stored_bytes)
    assert decrypted["source_device_id"] == export["source_device_id"]
    assert decrypted["target_device_id"] == desktop_id
    assert any(row["table"] == "memories" for row in decrypted["rows"])
    assert any(obj["artifact_id"].startswith("sha256:") for obj in decrypted["objects"])


def test_exported_bundle_does_not_expose_plaintext_rows(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)

    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    plan = prepare_sync_changeset(laptop, peer_id=desktop_id)
    export = export_sync_changeset(laptop, plan, accept=True, approved_by="tester")
    stored_bytes = laptop.content_store.read_bytes(export["artifact_id"])

    assert b'"rows"' not in stored_bytes
    assert b'"payload_json"' not in stored_bytes
    assert b"sync_project_decision" not in stored_bytes


def test_decrypt_rejects_tampered_envelope_metadata(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    export = export_sync_changeset(
        laptop,
        prepare_sync_changeset(laptop, peer_id=desktop_id),
        accept=True,
        approved_by="tester",
    )
    bundle = json.loads(laptop.content_store.read_bytes(export["artifact_id"]).decode("utf-8"))
    bundle["envelope"]["source_signing_public_key"] = "ed25519:" + "A" * 43

    with pytest.raises(Exception):
        decrypt_sync_bundle(desktop, json.dumps(bundle, sort_keys=True).encode("utf-8"))


def test_export_requires_acceptance_and_registered_peer(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    plan = prepare_sync_changeset(laptop, peer_id=desktop_id)
    denied = export_sync_changeset(laptop, plan, accept=False, approved_by="tester")
    unknown = prepare_sync_changeset(laptop, peer_id="device:unknown")

    assert denied["status"] == "policy_denied"
    assert denied["write_performed"] is False
    assert unknown["status"] == "policy_denied"
    assert unknown["error"]["code"] == "peer_not_registered"


def test_prepare_sync_changeset_uses_transaction_frontier(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    transaction_ids = [
        record["transaction_id"]
        for record in list_records(laptop.ledger, "transactions")
        if record.get("operation_kind") == "store_memory"
    ]
    upsert_record(
        laptop.ledger,
        "sync_cursors",
        "sync_cursor:desktop:all",
        {
            "record_type": "sync_cursor",
            "peer_device_id": desktop_id,
            "table": "*",
            "last_seen_transaction_id": transaction_ids[-1],
            "updated_at": "2026-05-26T00:00:00+00:00",
        },
    )
    laptop.store_memory(
        key="sync_after_cursor",
        title="After Cursor",
        content="This memory should be the only memory row exported after the cursor.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )

    plan = prepare_sync_changeset(laptop, peer_id=desktop_id)

    memory_ids = {ref["id"] for ref in plan["row_refs"] if ref["table"] == "memories"}
    assert "sync_after_cursor" in memory_ids
    assert "sync_project_decision" not in memory_ids

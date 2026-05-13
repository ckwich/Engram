from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.snapshots import SnapshotService


def test_snapshot_manifest_records_rebuild_and_policy_refs(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    service = SnapshotService(ledger)

    snapshot = service.create_snapshot(
        created_by="agent",
        lancedb_rebuild_manifest_ref="artifact:lance",
        kuzu_rebuild_manifest_ref="artifact:kuzu",
    )

    assert snapshot["snapshot_id"].startswith("snapshot:")
    assert snapshot["ledger_revision"] == 0
    assert snapshot["source_manifest_hash"].startswith("sha256:")
    assert snapshot["lancedb_rebuild_manifest_ref"] == "artifact:lance"
    assert snapshot["kuzu_rebuild_manifest_ref"] == "artifact:kuzu"
    assert snapshot["policy_manifest_hash"].startswith("sha256:")
    assert snapshot["created_by"] == "agent"
